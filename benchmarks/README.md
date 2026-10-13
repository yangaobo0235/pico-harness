# Benchmark

`benchmarks/` 存放 Pico 的冻结评测输入与已归档的结果摘要。评测用固定任务、验证器和运行记录比较特定能力的效果、成本与运行特性，结论要能落到具体字段和具体条件上。

评测实现住在 `src/pico/extensions/evaluation`，产品源码不导入本目录，`scripts/dev` 只是它的调用方。

## 目录内容

| 内容 | 位置 |
| --- | --- |
| 冻结任务输入 | `coding_tasks.json`，`schema_version` 恒为 `1` |
| 基准工件 | `benchmark-v1.json`（默认输出路径） |
| 回归工件 | `artifacts/harness-regression-v2.json`，`artifacts/` 不进 Git |
| 历史结果摘要 | `results/<日期>/`，只提交可复核的 JSON 与 Markdown |
| fixture 仓库 | `tests/fixtures/bench_repo_readme`、`tests/fixtures/bench_repo_patch` |
| 评测实现 | `src/pico/extensions/evaluation/` 下的 `benchmark`、`engine`、`artifacts`、`metrics` |

原始运行数据、临时 workspace 副本和凭证不提交；`results/` 里的归档刻意排除在格式检查之外。

## 评测流程

```text
读取并校验冻结任务
  -> 为每个任务从 fixture 复制一份干净工作区
  -> 装配完整运行时（Pico + WorkspaceContext + SessionStore + RunStore + FakeModelClient）
  -> 必要时按 setup 预置现场
  -> 执行一次请求，跑外部 verifier
  -> 记录逐任务结果与 trace 聚合
  -> 汇总成一份工件
```

判定一次任务通过需要四个条件同时成立：verifier 命令返回成功、预期工件文件确实存在、工具步数在预算内、停止原因是 `final_answer_returned`。缺任何一个都记为失败，并归入一个失败类别。

引擎不做并行、不做重试、不做多次采样取中位数：一次评测要的是“这一次确实发生了什么”，自动重试会把不确定的行为伪装成确定的结论。

## 运行

```powershell
make benchmark
make benchmark-regression
```

没有 Make 时用等价命令：

```powershell
uv run python -m scripts.dev.run_benchmark
uv run python -m scripts.dev.run_benchmark --regression
uv run python -m scripts.dev.run_benchmark --help
```

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--benchmark-path` | `benchmarks/coding_tasks.json` | 任务输入 |
| `--artifact-path` | 基准走 `benchmarks/benchmark-v1.json`，回归走 `artifacts/harness-regression-v2.json` | 工件输出 |
| `--workspace-root` | 临时目录 | fixture 副本与运行目录的落点，不会自动清理 |
| `--regression` | 关闭 | 换用回归轨道，任务集合相同，只是工件名不同 |

`--workspace-root` 省略时每次新建一个临时目录，一次调用不在仓库里留痕迹，但也没有回收逻辑；需要保留现场做复盘时显式指定路径。

脚本化模型用确定性输出驱动完整链路，因此这两条命令不需要 API key，也不产生费用，CI 环境同样可跑。

## 任务输入与校验

字段合法性由 `pico.extensions.evaluation.benchmark:validate_benchmark` 判定，校验失败的顺序就是让这份基准不可执行的第一个原因。

| 字段 | 要求 |
| --- | --- |
| `id` | 非空且不重复，裁剪两端空白 |
| `prompt` | 交给 agent 的原始请求 |
| `fixture_repo` | 相对仓库根存在的目录，空目录视为不存在 |
| `allowed_tools` | 非空列表，每一项必须在当前登记的工具名录里 |
| `step_budget` | 转成整数后不小于 `1` |
| `expected_artifact` | 期望被写出或改写的文件说明 |
| `verifier` | 在任务工作区里执行的外部命令 |
| `category` | 结果统计里的归类标签 |
| `setup` | 可选，`context_reduction`、`freshness_mismatch`、`workspace_mismatch` 三种现场；未知 `kind` 什么都不做 |

校验只做“能否执行”这一层：不检查 prompt 与脚本输出是否匹配，不比较任务数量下限，也不预跑 verifier。基准的作者就是仓库维护者，多余的启发式只会让一次刻意的实验在加载阶段被拒之门外。把基准文件挪到别的目录深度会改变 `repo_root` 的反推结果，需要精确控制时显式传入。

## 任务覆盖的能力

| 任务 | 类别 | 探测点 |
| --- | --- | --- |
| `readme_intro_locked`、`readme_schema_note` | documentation | `patch_file` 在 README 上的唯一匹配替换 |
| `sample_beta_locked`、`sample_gamma_locked` | text-edit | 同一定位方式在另一个 fixture 上的表现 |
| `invalid_patch_recovery` | tool-boundary | 缺参数的调用被拒后能否自我纠正 |
| `path_escape_recovery` | tool-boundary | 越界读取被拦下后的恢复路径 |
| `repeated_read_recovery` | tool-boundary | 重复同一读取时的拦截与历史折叠 |
| `context_reduction_checkpoint` | recovery | 长历史与长笔记下的段落收缩与 checkpoint 生成 |
| `freshness_reanchor_resume` | recovery | 文件摘要过期时的 `partial-stale` 判定 |
| `workspace_mismatch_resume` | recovery | 工作区指纹漂移时的 `workspace-mismatch` 判定 |
| `durable_promotion_accept`、`durable_promotion_reject` | durable-contract | 长期记忆晋升的接受与拒绝口径 |

## 脚本化模型与工件口径

| 项 | 取值 |
| --- | --- |
| 模型身份 | `FakeModelClient` / `scripted-deterministic` |
| 解码参数 | `temperature = 0.0`、`top_p = 1.0`、`max_new_tokens = 64` |
| 时间戳时区 | `Asia/Shanghai`，写死而不是取本机时区 |
| 快照指纹 | fixture 全量内容的 `sha256:` 摘要，工件文件另有独立摘要 |
| 环境事实 | Git 提交号与分支、`LC_CTYPE` locale，单次 Git 调用超时 5 秒 |
| 路径写法 | 工件里只记相对 workspace 根的正向相对路径 |

评测的解码参数刻意不复用运行默认值：日常对话的默认值会随产品调参漂移，两者混用会让历史工件无法解释。脚本输出也只覆盖基准内的任务，不给未知任务兜底——“缺脚本”本身就是基准被改动过的信号。

Git 与 locale 采集失败按“这项事实缺失”处理而不抛错：缺一条提交号只让工件少一项，让整次评测失败毫无价值。时间戳相反，缺少 tzdata 时直接抛异常，因为时间是可复现性的证据，静默退回 UTC 会让两次运行看起来可比其实不可比。

## 结果字段

逐任务结果行同时带上运行现场的引用：`run_dir_relpath`、`task_state_relpath`、`report_relpath` 指向工件位置，`task_state` 与 `report` 内联完整内容（其中含 checkpoint ID 与恢复状态），verifier 的退出码与输出、预期工件摘要、步数与停止原因逐条记录，未通过时给出第一个命中的失败类别。Trace 事件留在 `trace.jsonl` 里，由 `aggregates` 层按运行目录重建耗时与缓存命中。

汇总字段由 `summarize_rows` 产出：

| 字段 | 含义 |
| --- | --- |
| `total_tasks`、`passed`、`failed` | 任务计数 |
| `pass_rate` | 通过率，空输入为 `0.0` |
| `within_budget`、`within_budget_rate` | 步数在预算内的比例 |
| `verifier_passes`、`verifier_pass_rate` | 外部验证器通过的比例 |
| `failure_category_counts` | 未通过行的类别计数，缺失类别归入 `unknown` |

这里不做显著性检验、不算分位数、也不合并多次运行；跨运行比较属于调用方的实验脚本。

## 消融与实验

| 入口 | 命令 | 说明 |
| --- | --- | --- |
| 大规模实验 | `make experiments-large` | 需要 `--benchmark-artifact` 与 `--runs-root`，产出 context、memory、recovery 三组对照工件 |
| Provider 对比 | `make experiments-provider` | 真实模型，需要 key 与预算 |
| 恢复指标 | `make resume-metrics` | 从基准工件与 `.pico/runs/` 汇总恢复与重启指标 |

聚合与消融的实现集中在 `pico.extensions.evaluation.metrics`：`ablations` 在同一次运行里只关掉一项能力做对照并落成带版本的 JSON 工件，`aggregates` 只读磁盘上已存在的运行工件重建指标，`experiments` 反复把 agent 放进构造好的现场产出对照记录，`provider_experiments` 对同一份基准在不同后端上各跑一遍。

需要真实模型的那几个函数只由带 `real_llm` marker 的实验或显式脚本入口调用，默认回归不触发付费请求。provider 缺凭证时按 `blocked` 记录而不是抛错，让“哪一档没配”本身成为一条可读的结论。

真实后端对照实验的环境变量回退顺序与默认端点属于实验口径，刻意不复用产品配置目录，例如 `gpt` 在这一层默认落到 `https://api.openai.com/v1`，而产品配置落到共享网关。两者不同是历史事实，改写会让新旧工件对不上。

## 结果与结论规范

- 固定模型、Provider、配置、任务集合、预算和重复次数，任何一项变动都要在结论里写明。
- 先判断任务是否完整，再比较成本与时延。
- 分别保留“任务成功”“记录完整”“测量有效”三个独立判断，不合并成一个总分。
- 结论说明适用环境，失败或被跳过的调用不能作为费用下降的证据。
- 原始运行数据留在被忽略的 `artifacts/`、`.pico/` 或仓库外，`results/<日期>/` 只放可复核的摘要与来源说明。
- 修改任务、验证器或脚本输出会改变比较条件，与历史结果不可直接对照。

指标与标记的选择方式见[测试指南](../docs/development/testing.md)，字段口径的来源见[配置参考](../docs/reference/configuration.md)，模块归属见[架构与代码归属](../docs/architecture/overview.md)。贡献流程见[贡献指南](../CONTRIBUTING.md)。
