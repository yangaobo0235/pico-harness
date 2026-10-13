"""固定基准评测的输入定义与默认设定。

这里集中 `pico.extensions.evaluation` 内部所有"不随一次运行变化"的事实：基准 JSON 的
`schema_version`、默认输入输出路径、被评测模型的解码参数默认值、基准与任务的必填字段清单、
fixture 仓库到工件文件的映射，以及每个任务预置的脚本化模型输出。放在一起是为了让
"这批工件是在什么设定下产出的"只有一个可读的来源，改动能被 `git diff` 直接看见。

本模块不读取任何文件、不校验基准、也不装配 Agent：字段校验与加载属于 `benchmark.py`，运行事实
的采集属于 `artifacts.py`，驱动控制循环属于 `engine.py`。这里有意不共用
`pico.config.models.runtime` 的运行默认值——评测要的是可复现的极端设定（``temperature`` 固定
``0.0``、`max_new_tokens` 固定 ``64``），而日常对话的默认值会随产品调参漂移，两者混用会让历史工件
无法解释；`SCRIPTED_MODEL_OUTPUTS` 也只覆盖基准内的任务，不给未知任务兜底，因为"缺脚本"本身
就是基准被改动过的信号。
"""

from pathlib import Path

#: 本扩展唯一能读写的基准 schema 版本；其他版本一律视为不兼容，不做向前兼容解析。
BENCHMARK_SCHEMA_VERSION = 1

#: 默认基准定义文件；`repo_root` 由它自身的位置反推（见 `engine.BenchmarkEvaluator`）。
DEFAULT_BENCHMARK_PATH = Path("benchmarks/coding_tasks.json")
#: 默认结果工件路径，内容与 `run_fixed_benchmark` 返回的字典逐字相同。
DEFAULT_ARTIFACT_PATH = Path("benchmarks/benchmark-v1.json")
#: harness 回归 v2 的工件路径：同一套任务，只是换个可归档的名字，便于和基准 v1 并存对比。
DEFAULT_HARNESS_REGRESSION_V2_ARTIFACT_PATH = Path("artifacts/harness-regression-v2.json")

#: 记录进工件的模型身份；评测跑的是脚本化假模型，因此这里写的是类名而不是真实模型。
DEFAULT_MODEL_NAME = "FakeModelClient"
DEFAULT_MODEL_VERSION = "scripted-deterministic"

#: 解码参数固定成"完全确定"的一组值，任何漂移都会让 fixture 快照与工件指纹失去意义。
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_NEW_TOKENS = 64

#: 工件里的 `captured_at` 用的时区名。写死而不是取本机时区，为了让同一提交在任何机器上
#: 得到同形的时间戳；需要 tzdata，缺失时按异常暴露，不静默退回 UTC。
DEFAULT_TIMEZONE = "Asia/Shanghai"

#: 基准顶层必须出现的字段，缺任何一个都在加载阶段直接拒绝。
REQUIRED_BENCHMARK_KEYS: tuple[str, ...] = ("schema_version", "tasks")
#: 单个任务必须出现的字段；`setup` 不在其中，因为只有少数任务需要预置现场。
REQUIRED_TASK_KEYS: tuple[str, ...] = (
    "id",
    "prompt",
    "fixture_repo",
    "allowed_tools",
    "step_budget",
    "expected_artifact",
    "verifier",
    "category",
)

#: fixture 仓库目录名 -> 该任务期望被写出（或改写）的工件文件名，用于判断"任务是否真的动了文件"。
TASK_FIXTURE_ARTIFACTS: dict[str, str] = {
    "bench_repo_readme": "README.md",
    "bench_repo_patch": "sample.txt",
}

#: 任务 ID -> 脚本化模型输出序列。每条文本就是控制循环读到的一轮回答，含刻意留下的
#: 非法参数与越界路径，用来驱动恢复类分支；最后一条总是 `<final>`，因此正常任务必然收敛。
SCRIPTED_MODEL_OUTPUTS: dict[str, list[str]] = {
    "readme_intro_locked": [
        '<tool name="patch_file" path="README.md"><old_text>This is a placeholder benchmark fixture.</old_text><new_text>This fixture is a locked benchmark workspace.</new_text></tool>',
        "<final>Done.</final>",
    ],
    "readme_schema_note": [
        '<tool name="patch_file" path="README.md"><old_text>- Placeholder note about the repo.</old_text><new_text>- The benchmark schema and baseline are fixed.</new_text></tool>',
        "<final>Done.</final>",
    ],
    "readme_ordering_note": [
        '<tool name="patch_file" path="README.md"><old_text>- Placeholder note about the file layout.</old_text><new_text>- Deterministic file ordering keeps benchmark diffs stable.</new_text></tool>',
        "<final>Done.</final>",
    ],
    "sample_beta_locked": [
        '<tool name="patch_file" path="sample.txt"><old_text>beta</old_text><new_text>beta-locked</new_text></tool>',
        "<final>Done.</final>",
    ],
    "sample_gamma_locked": [
        '<tool name="patch_file" path="sample.txt"><old_text>gamma</old_text><new_text>gamma-locked</new_text></tool>',
        "<final>Done.</final>",
    ],
    "sample_placeholder_delta": [
        '<tool name="patch_file" path="sample.txt"><old_text>placeholder</old_text><new_text>delta</new_text></tool>',
        "<final>Done.</final>",
    ],
    "invalid_patch_recovery": [
        '<tool>{"name":"patch_file","args":{"path":"README.md","old_text":"This is a placeholder benchmark fixture."}}</tool>',
        '<tool name="patch_file" path="README.md"><old_text>This is a placeholder benchmark fixture.</old_text><new_text>This fixture recovered after invalid patch args.</new_text></tool>',
        "<final>Done.</final>",
    ],
    "path_escape_recovery": [
        '<tool>{"name":"read_file","args":{"path":"../outside.txt","start":1,"end":1}}</tool>',
        '<tool name="patch_file" path="sample.txt"><old_text>alpha</old_text><new_text>alpha-guarded</new_text></tool>',
        "<final>Done.</final>",
    ],
    "repeated_read_recovery": [
        '<tool>{"name":"read_file","args":{"path":"sample.txt","start":1,"end":4}}</tool>',
        '<tool>{"name":"read_file","args":{"path":"sample.txt","start":1,"end":4}}</tool>',
        '<tool>{"name":"read_file","args":{"path":"sample.txt","start":1,"end":4}}</tool>',
        '<tool name="patch_file" path="sample.txt"><old_text>placeholder</old_text><new_text>repeat-guarded</new_text></tool>',
        "<final>Done.</final>",
    ],
    "context_reduction_checkpoint": [
        "<final>Done.</final>",
    ],
    "freshness_reanchor_resume": [
        "<final>Done.</final>",
    ],
    "workspace_mismatch_resume": [
        "<final>Done.</final>",
    ],
    "durable_promotion_accept": [
        "<final>Project convention: Preserve benchmark regression artifacts under artifacts/.\nDecision: Keep harness regression deterministic and reproducible.</final>",
    ],
    "durable_promotion_reject": [
        "<final>Project convention: Keep verifier outcomes stable across reruns.\nDependency: API key is sk-benchmark-secret.\nDecision: Current goal is debug the harness.</final>",
    ],
}
