"""固定基准评测扩展：把完整的运行时当成被测对象，产出一份可归档的结果工件。

`config` 保存不随运行变化的输入定义与默认设定，`artifacts` 采集工件所需的外部事实，
`benchmark` 负责基准的读入、字段校验与结果汇总，`engine` 装配运行时、跑完每个任务并写出工件。
包级只导出四个稳定入口：`BenchmarkEvaluator` 与 `run_fixed_benchmark` 驱动一次评测，
`load_benchmark` 与 `validate_benchmark` 供调用方只读基准而不跑任务。

本扩展只做观测与评测，不改变运行时行为：它通过 `pico.runtime`、`pico.capabilities`、
`pico.integrations` 与 `pico.observability` 的既有公开接口装配实例，不 monkey-patch、不注入
测试替身以外的私有状态，也不导入 `pico.interfaces` 或 `pico.bootstrap`——命令行与装配容器属于
面向用户与组合根的上层，评测若反过来依赖它们，就再也无法在 CI 里独立运行。指标聚合、成本核算
与仪表盘属于同级的 `metrics` 侧与实验脚本，不在这里；需要替换模型后端时用 ``model_client_factory``
参数，而不是在本包加分支。
"""

from pico.extensions.evaluation.benchmark import load_benchmark, validate_benchmark
from pico.extensions.evaluation.engine import BenchmarkEvaluator, run_fixed_benchmark

__all__ = [
    "BenchmarkEvaluator",
    "load_benchmark",
    "run_fixed_benchmark",
    "validate_benchmark",
]
