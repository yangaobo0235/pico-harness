"""按运行组织的事实记录。

`store` 负责把状态、Trace 和报告写到 ``.pico/runs/<run_id>/``，`report` 定义报告字段。
两者都不解释这些数字的业务含义，也不跨运行做聚合——聚合属于 `pico.extensions.evaluation`。
"""

from pico.observability.runs.report import build_report
from pico.observability.runs.store import RunStore

__all__ = ["RunStore", "build_report"]
