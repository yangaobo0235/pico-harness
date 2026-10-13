"""工作记忆与相关记忆两段的渲染。

`memory` 段带上会话当前的记忆概览，`relevant_memory` 只带本轮检索命中的少数笔记。两段都可能
很长，因此各自有裁剪规则：记忆概览按整段尾部裁剪，相关笔记按条平分预算，避免一条超长笔记把
其他笔记全部挤掉。

检索本身属于 `pico.capabilities.memory`，这里只负责把已经选出来的条目写成模型读得懂的文本，
并如实报告“选中了几条、渲染了几条”。
"""

from typing import Any

from pico.runtime.context.segments.render import SectionRender
from pico.shared.text import tail_clip

MEMORY_HEADER = "Memory:"
RELEVANT_MEMORY_HEADER = "Relevant memory:"
#: 记忆功能被关闭时写进 Prompt 的事实，而不是留下一段空白。
MEMORY_DISABLED_TEXT = f"{MEMORY_HEADER}\n- disabled"
EMPTY_RELEVANT_MEMORY = f"{RELEVANT_MEMORY_HEADER}\n- none"
#: 每条笔记最少分到的字符数，低于这个值宁可不显示这条笔记。
MINIMUM_NOTE_BUDGET = 1


def render_memory(raw: str, budget: int) -> SectionRender:
    """把记忆概览按预算尾部裁剪。

    概览文本内部已经按“任务、约定、文件摘要”排过序，因此从头保留最能代表当前状态的部分。
    ``budget`` 为 0 时渲染结果也是空串，``raw`` 仍完整记录长度。
    """
    return SectionRender(raw=raw, budget=int(budget), rendered=tail_clip(raw, budget))


def per_note_budget(budget: int, note_count: int, header: str = RELEVANT_MEMORY_HEADER) -> int:
    """算出每条笔记平均分到多少字符。

    先扣掉标题行与每条前的 ``- `` 前缀开销，再按条数均分；至少保留
    `MINIMUM_NOTE_BUDGET`，因为“只显示了前半句”仍然比“整条消失”更有指导意义。
    """
    if note_count <= 0:
        return 0
    overhead = len(header) + 3 * note_count
    usable = max(0, budget - overhead)
    return max(MINIMUM_NOTE_BUDGET, usable // note_count)


def render_relevant_memory(selected_notes: list[dict[str, Any]], budget: int) -> SectionRender:
    """渲染本轮选中的相关笔记。

    笔记按平分预算的方式裁剪；如果整体仍然超限就逐条减一个字符，直到装得下或每条只剩一个
    字符。走到极端仍放不下时，退回对整段文本做一次尾部裁剪，并把渲染结果记成单条——这保证
    ``details`` 里 ``rendered_count`` 与实际行数一致，而不是给出一个骗过预算但内容错位的列表。

    ``details`` 同时记录选中与渲染的笔记文本，供 Trace 复盘“这条笔记有没有真的进入 Prompt”。
    """
    note_texts = [str(note.get("text", "")) for note in selected_notes if str(note.get("text", "")).strip()]
    raw_lines = [RELEVANT_MEMORY_HEADER] + [f"- {text}" for text in note_texts]
    raw = "\n".join(raw_lines) if note_texts else EMPTY_RELEVANT_MEMORY
    if not note_texts:
        return SectionRender(
            raw=raw,
            budget=budget,
            rendered=raw,
            details={
                "selected_notes": [],
                "rendered_notes": [],
                "selected_count": 0,
                "rendered_count": 0,
                "note_budget": 0,
            },
        )

    share = per_note_budget(budget, len(note_texts))
    while True:
        rendered_notes = [tail_clip(text, share) for text in note_texts]
        rendered = "\n".join([RELEVANT_MEMORY_HEADER] + [f"- {text}" for text in rendered_notes])
        if len(rendered) <= budget or share <= 1:
            break
        share -= 1

    if len(rendered) > budget and budget > 0:
        rendered = tail_clip(raw, budget)
        rendered_notes = [rendered]

    return SectionRender(
        raw=raw,
        budget=budget,
        rendered=rendered,
        details={
            "selected_notes": note_texts,
            "rendered_notes": rendered_notes,
            "selected_count": len(note_texts),
            "rendered_count": len(rendered_notes),
            "note_budget": share,
        },
    )
