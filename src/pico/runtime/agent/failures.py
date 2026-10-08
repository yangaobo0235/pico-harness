"""Classify tool failures and generate bounded recovery hints."""

from __future__ import annotations

import json
import re

from pico.capabilities.tools.contracts import ToolResult

_TRANSIENT_FAILURE_MARKERS = (
    "429",
    "rate limit",
    "timed out",
    "timeout",
    "no healthy upstream",
    "502",
    "503",
)


_EMPTY_SUCCESS_MARKERS = ("no matches found", "no files found")


def _is_tool_failure(result: object) -> bool:
    if isinstance(result, ToolResult):
        return result.failed

    s = str(result).strip()
    match = re.search(r"(?:^|\n)Exit code:\s*(-?\d+)(?:\s|$)", s)
    if match:
        return match.group(1) != "0"
    if s.startswith("{"):
        try:
            payload = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            pass
        else:
            if isinstance(payload, dict) and payload.get("error"):
                return True
    low = s.lower()
    return (
        low.startswith("error:")
        or low.startswith("error ")
        or low.startswith("proxy error:")
        or low.startswith("(mcp tool call failed:")
        or low.startswith("(mcp tool call timed out ")
        or low.startswith("(mcp tool call was cancelled)")
    )


def _is_hard_tool_failure(result: object) -> bool:
    """判断工具结果是否属于“原样重试仍会复现”的确定性失败。

    返回 ``True`` 表示同一 Tool 和相同参数再次执行通常只会得到同类错误，可以计入连续
    失败并触发循环打断；成功结果、可重试的临时错误以及合法的空搜索结果返回 ``False``。
    429、超时、502/503 等标记会先被排除，因为外部依赖恢复后重试可能成功；"no matches
    found" 和 "no files found" 也不是失败。最终的失败判定复用 `_is_tool_failure`，本函数
    只负责增加“是否值得打断重复尝试”这一层语义。
    """
    s = str(result)
    low = s.lower()
    if any(m in low for m in _TRANSIENT_FAILURE_MARKERS):
        return False
    if s.strip().rstrip(".").lower() in _EMPTY_SUCCESS_MARKERS:
        return False
    return _is_tool_failure(result)


def _loop_break_nudge(tool: str, n: int) -> str:
    """生成同一工具连续确定性失败 ``n`` 次后注入模型的改路提示。

    ``tool`` 是失败的 Tool 名称，``n`` 是当前连续次数。返回文本不会替模型选择具体方案，
    而是明确禁止不变重试，并按外部依赖、文件路径和其他失败三类给出检查方向。它只在
    `_is_hard_tool_failure` 已确认失败可复现后使用，目的是让模型改变工具、命令或策略，
    而不是把瞬时网络错误误判为 Agent 卡死。
    """
    return (
        f"[loop] `{tool}` has failed {n} times in a row with the same kind of error. "
        "Stop repeating it. If it is an external dependency (network/API/search), "
        "complete what you can offline from local data and report what stayed blocked. "
        "If it is a file or path error, re-examine the EXACT path before any retry — "
        "do not call it again unchanged. Otherwise change approach: a different tool, "
        "command, or strategy."
    )
