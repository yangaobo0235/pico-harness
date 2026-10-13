"""把较长的会话历史压成还能读的形状。

历史里真正影响下一步决策的通常只是最近几条；更早的条目如果原样带入，会挤掉相关记忆和指令。
本模块保留最近窗口内的原文，把更早的条目降级为一行摘要，并把重复读取同一文件的历史折叠成
已经沉淀下来的文件摘要。

压缩只影响 Prompt 里看到的内容，不修改会话存储：`history` 始终保留完整记录，可随时导出或
复盘。谁决定最近窗口有多大、哪一段该让出预算，属于 `pico.runtime.context.budget`。
"""

import json
from typing import Any

from pico.config.models.runtime import MAX_HISTORY
from pico.runtime.context.budget import RECENT_HISTORY_WINDOW
from pico.shared.text import clip, tail_clip

TRANSCRIPT_HEADER = "Transcript:"
EMPTY_TRANSCRIPT = f"{TRANSCRIPT_HEADER}\n- empty"

#: 最近窗口内一条工具结果的正文上限。
RECENT_CONTENT_CLIP = 900
#: 早期条目的文本上限，太短的裁剪值会让条目失去意义。
OLD_ENTRY_CLIP = 60
#: 摘要渲染里早期工具结果与早期对话文本的上限。
SUMMARY_OLDER_TOOL_CLIP = 180
SUMMARY_OLDER_TEXT_CLIP = 220
#: 一条早期 Shell 摘要里最多保留的输出行数。
OLD_TOOL_SUMMARY_LINES = 3

#: 压缩统计里固定上报的计数项，便于实验脚本比较“压缩掉了多少”。
DETAIL_COUNTERS = (
    "older_entries_count",
    "collapsed_duplicate_reads",
    "reused_file_summary_count",
    "summarized_tool_count",
)


def render_item(item: dict[str, Any], line_limit: int) -> list[str]:
    """把一条历史记录渲染成一行或多行文本。

    工具条目渲染成两行：第一行是 ``[tool:name] {参数 JSON}``，第二行是结果正文——参数和结果的
    长度约束完全不同，因此分开裁剪。非工具条目渲染成单行 ``[role] 内容``。键缺失按空值处理，
    损坏的历史不会让整轮 Prompt 组装失败。
    """
    role = str(item.get("role", ""))
    if role == "tool":
        prefix = f"[tool:{item.get('name', '')}] {json.dumps(item.get('args') or {}, sort_keys=True)}"
        return [prefix, tail_clip(item.get("content", ""), max(20, line_limit))]
    return [f"[{role}] {tail_clip(item.get('content', ''), line_limit)}"]


def raw_text(history: list[dict[str, Any]]) -> str:
    """返回未经压缩的完整历史文本，只用于元数据里的原始长度对照。

    这份文本不会被发送，它用来量化“压缩省掉了多少字符”，因此与 `render_item` 共用同一种行
    格式，保证两者长度可以直接比较。
    """
    if not history:
        return EMPTY_TRANSCRIPT
    lines: list[str] = []
    for item in history:
        if str(item.get("role", "")) == "tool":
            lines.append(f"[tool:{item.get('name', '')}] {json.dumps(item.get('args') or {}, sort_keys=True)}")
            lines.append(str(item.get("content", "")))
        else:
            lines.append(f"[{item.get('role', '')}] {item.get('content', '')}")
    return "\n".join([TRANSCRIPT_HEADER, *lines])


def summarize_old_tool_item(item: dict[str, Any]) -> str:
    """把一条早期的工具条目压成一行。

    Shell 条目写成 ``命令 -> 前几行输出``，因为最有信息量的部分通常在开头，没有输出时写成
    ``(empty)`` 以表示“确实跑过但没产生文本”。其他工具保留参数行（``[tool:name] {args}``），
    让模型仍然知道这一步动作的对象；完整正文此时已经不再有价值。
    """
    if str(item.get("name", "")) == "run_shell":
        command = str((item.get("args") or {}).get("command", "")).strip() or "shell"
        lines = [line.strip() for line in str(item.get("content", "")).splitlines() if line.strip()]
        summary = " | ".join(lines[:OLD_TOOL_SUMMARY_LINES]) if lines else "(empty)"
        return f"{command} -> {summary}"
    return render_item(item, OLD_ENTRY_CLIP)[0]


def compress_history(
    history: list[dict[str, Any]],
    recent_start: int,
    file_summaries: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按“最近窗口保留原文、更早条目走摘要”的规则生成待渲染条目。

    返回 ``(条目列表, 统计信息)``。条目形如 ``{"recent": bool, "lines": [...]}``，渲染方按从新
    到旧的顺序回填预算。三条压缩规则各自计数：同一文件的重复读取只保留第一次；有可用文件摘要
    时把读取结果替换成摘要；其余早期工具条目替换成单行摘要。非工具条目按 `OLD_ENTRY_CLIP`
    截断但仍然保留。

    ``recent_start`` 是窗口起点下标，``file_summaries`` 是工作记忆里已经沉淀的 ``路径 -> 摘要``；
    两者都由调用方准备好，本函数不访问会话或记忆对象，因此可以单独测试。
    """
    entries: list[dict[str, Any]] = []
    seen_older_reads: set[str] = set()
    details: dict[str, Any] = {name: 0 for name in DETAIL_COUNTERS}

    for index, item in enumerate(history):
        recent = index >= recent_start
        if recent:
            entries.append({"recent": True, "lines": render_item(item, RECENT_CONTENT_CLIP)})
            continue

        if str(item.get("role", "")) == "tool" and str(item.get("name", "")) == "read_file":
            path = str((item.get("args") or {}).get("path", "")).strip()
            if path in seen_older_reads:
                details["collapsed_duplicate_reads"] += 1
                continue
            seen_older_reads.add(path)
            summary = str(file_summaries.get(path, "")).strip()
            if summary:
                entries.append({"recent": False, "lines": [f"{path} -> {summary}"]})
                details["older_entries_count"] += 1
                details["reused_file_summary_count"] += 1
                continue

        if str(item.get("role", "")) == "tool":
            entries.append({"recent": False, "lines": [summarize_old_tool_item(item)]})
            details["older_entries_count"] += 1
            details["summarized_tool_count"] += 1
            continue

        entries.append({"recent": False, "lines": render_item(item, OLD_ENTRY_CLIP)})

    return entries, details


def summary_text(
    history: list[dict[str, Any]], *, recent_window: int = RECENT_HISTORY_WINDOW, limit: int = MAX_HISTORY
) -> str:
    """渲染一份“给压缩场景使用”的历史摘要文本。

    与 `render_item` 不同，这里用头部裁剪（保留开头并附截断长度），因为它服务于“把整段会话压成
    一小份笔记”，例如委派子 Agent 时带走的上文。规则与历史压缩一致：同一文件的重复读取只保留
    第一次，最近 ``recent_window`` 条按较宽上限保留，更早的条目按 `SUMMARY_OLDER_TOOL_CLIP` 与
    `SUMMARY_OLDER_TEXT_CLIP` 收窄。

    空历史返回 ``- empty``，让调用方仍然能拼出一句完整事实。
    """
    if not history:
        return "- empty"

    lines: list[str] = []
    seen_reads: set[str] = set()
    recent_start = max(0, len(history) - recent_window)
    for index, item in enumerate(history):
        recent = index >= recent_start
        if str(item.get("role", "")) == "tool" and str(item.get("name", "")) == "read_file" and not recent:
            path = str((item.get("args") or {}).get("path", ""))
            if path in seen_reads:
                continue
            seen_reads.add(path)

        if str(item.get("role", "")) == "tool":
            line_limit = RECENT_CONTENT_CLIP if recent else SUMMARY_OLDER_TOOL_CLIP
            lines.append(f"[tool:{item.get('name', '')}] {json.dumps(item.get('args') or {}, sort_keys=True)}")
            lines.append(clip(item.get("content", ""), line_limit))
        else:
            line_limit = RECENT_CONTENT_CLIP if recent else SUMMARY_OLDER_TEXT_CLIP
            lines.append(f"[{item.get('role', '')}] {clip(item.get('content', ''), line_limit)}")

    return clip("\n".join(lines), limit)
