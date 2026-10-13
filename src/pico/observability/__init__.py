"""可观测性职责组：记录运行事实。

`runs` 按 ``run_id`` 写出状态、Trace 与报告，是 Pico 唯一的执行记录通道。这里不采集模型内部
状态，也不做指标聚合、成本核算或仪表盘：Pico 记录“发生了什么”，解释“意味着什么”属于评测扩展
与实验脚本。

写入内容在进入本层之前已经完成脱敏，因此这里出现的凭证一律是占位符。若需要更严格的保证，
应当在上游减少记录，而不是在下游过滤。
"""

from pico.observability.runs import RunStore, build_report

__all__ = ["RunStore", "build_report"]
