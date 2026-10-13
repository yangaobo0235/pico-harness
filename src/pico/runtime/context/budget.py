"""Prompt 各段的预算、下限与收缩顺序。

一轮 Prompt 由固定的几段组成：稳定指令、工作记忆、相关记忆、历史、当前请求。预算决定“默认
给每段多少字符”，下限决定“最多能压到多少”，收缩顺序决定“先牺牲谁”。三者合起来表达一个策略
偏好：本轮用户输入永远完整，稳定指令最后动。

本模块只描述数字与顺序，不做裁剪；具体渲染属于 `pico.runtime.context.segments`，把三段拼成
Prompt 属于 `pico.runtime.context.assembler`。预算单位是字符而不是 Token，因为 Pico 不绑定
某个供应商的分词器，字符数是各方都能复核的事实。
"""

from typing import Any

INSTRUCTIONS_SECTION = "prefix"
MEMORY_SECTION = "memory"
RELEVANT_MEMORY_SECTION = "relevant_memory"
HISTORY_SECTION = "history"
CURRENT_REQUEST_SECTION = "current_request"

#: 渲染与元数据里固定使用的段落顺序；当前请求始终排在最后且不设预算。
SECTION_ORDER = (
    INSTRUCTIONS_SECTION,
    MEMORY_SECTION,
    RELEVANT_MEMORY_SECTION,
    HISTORY_SECTION,
    CURRENT_REQUEST_SECTION,
)

#: 有预算的段落，即除当前请求之外的全部段落。
BUDGETED_SECTIONS = SECTION_ORDER[:-1]

DEFAULT_TOTAL_BUDGET = 12000
DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    INSTRUCTIONS_SECTION: 3600,
    MEMORY_SECTION: 1600,
    RELEVANT_MEMORY_SECTION: 1200,
    HISTORY_SECTION: 5200,
}
DEFAULT_SECTION_FLOORS: dict[str, int] = {
    INSTRUCTIONS_SECTION: 1200,
    MEMORY_SECTION: 400,
    RELEVANT_MEMORY_SECTION: 300,
    HISTORY_SECTION: 1500,
}
#: 超预算时的收缩顺序：先牺牲相关笔记与历史，再动工作记忆，稳定指令放最后。
DEFAULT_REDUCTION_ORDER = (
    RELEVANT_MEMORY_SECTION,
    HISTORY_SECTION,
    MEMORY_SECTION,
    INSTRUCTIONS_SECTION,
)

#: 单轮注入的相关记忆条数上限。
RELEVANT_MEMORY_LIMIT = 3
#: 历史窗口里“按最近原文保留”的条目数，更早的条目走压缩路径。
RECENT_HISTORY_WINDOW = 6
#: 段落下限的最低保底字符数，避免压成零之后段标题也一起消失。
MINIMUM_SECTION_FLOOR = 20


def compute_section_floors(
    section_budgets: dict[str, int],
    overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    """按默认预算比例推出各段下限，再套用显式覆盖。

    未覆盖的段取下限为预算的四分之一，并保证不低于 `MINIMUM_SECTION_FLOOR`，这样一段内容
    即使被压到最狠也还能显示标题和一两行。``overrides`` 用于消融实验里刻意把某段压到底，
    数值原样采用，不再做比例修正。
    """
    floors = {section: max(MINIMUM_SECTION_FLOOR, int(budget) // 4) for section, budget in section_budgets.items()}
    floors.update({str(key): int(value) for key, value in (overrides or {}).items()})
    return floors


def next_reduction(
    budgets: dict[str, int],
    floors: dict[str, int],
    reduction_order: tuple[str, ...],
    overflow: int,
) -> tuple[str, int] | None:
    """在收缩顺序里找出第一个还能继续压缩的段落及其新预算。

    返回 ``None`` 表示所有段落都已到下限，调用方应当接受当前 Prompt 超预算并继续发送，
    而不是无限循环。“至少要比现在小”在这里检查一次，避免把 ``new_budget == current``
    这种零收益的收缩写进收缩日志。
    """
    for section in reduction_order:
        floor = int(floors.get(section, 0))
        current = int(budgets.get(section, 0))
        if current <= floor:
            continue
        candidate = max(floor, current - overflow)
        if candidate >= current:
            continue
        return section, candidate
    return None


def reduction_record(section: str, before: int, after: int, overflow: int) -> dict[str, Any]:
    """构造一条收缩记录，进入 Trace 与报告。

    记录里同时保留收缩前的预算、收缩后的预算和当时的溢出字符数，复盘时可以重建“为什么这一段
    被压到这么小”，而不需要重跑一次相同输入。
    """
    return {
        "section": section,
        "before_chars": int(before),
        "after_chars": int(after),
        "overflow_chars": int(overflow),
    }
