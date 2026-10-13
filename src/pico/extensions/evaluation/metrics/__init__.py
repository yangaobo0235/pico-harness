"""指标层：从已经落盘的运行工件与实验记录里重建数字。

这一层把「测量」和「执行」分开：`aggregates` 读 benchmark 工件与 ``.pico/runs`` 下的
``report.json`` / ``trace.jsonl``，`ablations` 用 feature flag 与两种按 Prompt 内容应答的假模型做消融
并落成 v2 工件，`experiments` 提供压力、记忆、安全三组合成实验及其真实模型版本，
`provider_experiments` 让同一份 benchmark 在不同后端上对照，`reporting` 把上面所有的产物排成 markdown。
稳定入口按四类列在下面。

边界：本层不参与运行时执行——不装配 CLI、不创建 bootstrap 容器，也不被 runtime 反向导入；它只在
外部调用时驱动 `Pico` 跑一遍被构造出来的现场。指标口径以这里为准，但产生记录的现场属于 runtime 与
`pico.extensions.evaluation` 的 benchmark engine。需要真实模型或额外预算的入口（名字里带 ``real`` 的
实验与 `run_provider_experiments`）只由带 ``real_llm`` marker 的实验或显式脚本调用，默认回归不触发付费
请求；其余入口全部落在临时目录里，重复调用只重复产出同口径的记录。
"""

from pico.extensions.evaluation.metrics.ablations import (
    measure_feature_ablation_metrics,
    run_context_ablation_v2,
    run_memory_ablation_v2,
    run_memory_dependency_experiment,
    run_recovery_ablation_v2,
)
from pico.extensions.evaluation.metrics.aggregates import (
    METRICS_SCHEMA_VERSION,
    aggregate_benchmark_artifact,
    aggregate_run_artifacts,
)
from pico.extensions.evaluation.metrics.experiments import (
    build_stress_agent_metrics,
    run_large_scale_memory_experiment,
    run_security_experiment_suite,
)
from pico.extensions.evaluation.metrics.reporting import (
    collect_resume_metrics,
    render_large_scale_experiment_report,
    render_resume_metrics_markdown,
    write_benchmark_core_report,
)

__all__ = [
    "METRICS_SCHEMA_VERSION",
    "aggregate_benchmark_artifact",
    "aggregate_run_artifacts",
    "build_stress_agent_metrics",
    "collect_resume_metrics",
    "measure_feature_ablation_metrics",
    "render_large_scale_experiment_report",
    "render_resume_metrics_markdown",
    "run_context_ablation_v2",
    "run_large_scale_memory_experiment",
    "run_memory_ablation_v2",
    "run_memory_dependency_experiment",
    "run_recovery_ablation_v2",
    "run_security_experiment_suite",
    "write_benchmark_core_report",
]
