"""会话历史段的渲染。

历史段是 Prompt 里最大的一块，也是最常超预算的一块。渲染策略按“从新到旧逐条回填”：最近的
条目优先完整保留，装不下时先压缩当前条目，再考虑丢弃更早的条目；被历史压缩器已经降级成摘要
的条目再退一步，按最小宽度裁剪后尝试放入。

这里不决定历史里放什么内容（那是 `pico.runtime.context.history_trimmer`），也不决定预算多大
（那是 `pico.runtime.context.budget`）；只负责在给定的字符数内尽量保住信息。
"""

from typing import Any

from pico.runtime.context.budget import RECENT_HISTORY_WINDOW
from pico.runtime.context.history_trimmer import EMPTY_TRANSCRIPT, TRANSCRIPT_HEADER, compress_history, raw_text
from pico.runtime.context.segments.render import SectionRender
from pico.shared.text import tail_clip

#: 一条早期条目退化到最小可读宽度时的字符数。
MINIMAL_ENTRY_CLIP = 20
#: 摘要条目仍要保留的下限，低于这个值不如整条丢掉。
RECENT_ENTRY_FLOOR = 20


def _empty_render(budget: int) -> SectionRender:
    """空历史的固定渲染结果：段落标题加 ``- empty``，统计项全部归零。"""
    return SectionRender(
        raw=EMPTY_TRANSCRIPT,
        budget=budget,
        rendered=EMPTY_TRANSCRIPT,
        details={
            "rendered_entries": [],
            "older_entries_count": 0,
            "collapsed_duplicate_reads": 0,
            "reused_file_summary_count": 0,
            "summarized_tool_count": 0,
        },
    )


def render_history(
    history: list[dict[str, Any]],
    budget: int,
    file_summaries: dict[str, str],
    *,
    recent_window: int = RECENT_HISTORY_WINDOW,
) -> SectionRender:
    """在 ``budget`` 个字符内渲染会话历史。

    先按 `recent_window` 划分“保留原文”和“允许摘要”的分界，再从最新条目向旧遍历：条目能整体
    放进剩余预算就直接放入；放不下时，最近条目按剩余空间裁剪（至少留 `RECENT_ENTRY_FLOOR`
    字符），早期条目则退到 `MINIMAL_ENTRY_CLIP` 宽度再试一次，仍然放不下就跳过整条。
    遍历顺序是从新到旧，因此预算不够时先牺牲的一定是更早的记录。

    极端情况下（标题都放不下）退回对未压缩文本做尾部裁剪，保证渲染结果长度可预测。
    ``details`` 里的计数项解释这次压缩实际做了什么，用于对照实验。
    """
    budget = int(budget)
    raw = raw_text(history)
    if not history:
        return _empty_render(budget)

    recent_start = max(0, len(history) - recent_window)
    entries, history_details = compress_history(history, recent_start, file_summaries)

    rendered_entries: list[str] = []
    for entry in reversed(entries):
        recent = bool(entry.get("recent", False))
        candidate_lines = list(entry.get("lines", []))
        candidate_rendered = "\n".join([TRANSCRIPT_HEADER, *candidate_lines, *rendered_entries])
        if len(candidate_rendered) <= budget:
            rendered_entries = candidate_lines + rendered_entries
            continue
        if recent:
            available = budget - len(TRANSCRIPT_HEADER)
            if rendered_entries:
                available -= sum(len(line) + 1 for line in rendered_entries)
            available = max(RECENT_ENTRY_FLOOR, available - 1)
            candidate_lines = [tail_clip(line, available) for line in candidate_lines]
            candidate_rendered = "\n".join([TRANSCRIPT_HEADER, *candidate_lines, *rendered_entries])
            if len(candidate_rendered) <= budget:
                rendered_entries = candidate_lines + rendered_entries
            continue
        smaller_lines = [tail_clip(line, MINIMAL_ENTRY_CLIP) for line in candidate_lines]
        smaller_rendered = "\n".join([TRANSCRIPT_HEADER, *smaller_lines, *rendered_entries])
        if len(smaller_rendered) <= budget:
            rendered_entries = smaller_lines + rendered_entries

    rendered = "\n".join([TRANSCRIPT_HEADER, *rendered_entries])
    if len(rendered) > budget and budget > 0:
        rendered = tail_clip(raw, budget)

    return SectionRender(
        raw=raw,
        budget=budget,
        rendered=rendered,
        details={
            "recent_window": recent_window,
            "recent_start": recent_start,
            "rendered_entries": rendered_entries,
            **history_details,
        },
    )
