# Benchmark

Pico 的仓库级评测工具，用固定任务、验证器和运行记录比较特定能力的效果、成本与运行特性。评测代码不进入产品 wheel，产品源码不直接导入本目录。

## 评测范围

| 目录 | 用途 |
| --- | --- |
| `picobench` | Runtime、Context、Memory/Skill、Tool/MCP 与用量实验 |
| `appworld` | AppWorld 任务适配和候选改进实验 |
| `pinchbench` | 直接执行与消息入口任务卡 |
| `clawbench` | 持续会话与流式评测适配 |
| `skill_retrieval` | 本地技能检索查询输入 |
| `evolver` | 改进实验的被测项目模板 |

任务卡是测试输入，包含不同能力的探测条件。运行某项任务前确认所需工具、依赖与配置是否齐全。

## 评测流程

```text
固定任务、模型、配置和预算
  -> 执行计划并记录原始调用
  -> 验证任务结果与记录完整性
  -> 从记录重建指标
  -> 比较重复运行结果
  -> 说明结论适用的任务与环境
```

修改任务、验证器或计划会改变比较条件，结果报告应说明版本与输入差异。

## PicoBench 快速检查

在源码开发环境执行：

```powershell
uv run python -m benchmarks.picobench --mode smoke --output-root .pico/evidence/picobench-smoke
uv run python -m benchmarks.picobench --help
```

Smoke 不需要真实模型凭证，检查运行时装配与证据处理。

| 内容 | 位置 |
| --- | --- |
| 计划 | `picobench/suites` |
| 任务 | `picobench/tasks` |
| 轨道与验证器 | `picobench/packs` |
| 本地输出 | 所选 `--output-root` |

完整 campaign、独立成本实验和各轨道按对应模块的 CLI 配置。

## ClawBench 适配

```powershell
uv run python benchmarks/clawbench/stream.py --help
```

需要外部任务目录与可用模型。`--session-id` 固定多轮会话，`--trace-dir` 指定本地记录。Shell 入口为 `benchmarks/clawbench/run.sh`。

## 提示词缓存实验

| 实验 | 测试入口 |
| --- | --- |
| 缓存断点策略 | `tests/unit/observability/test_token_wise_cache_strategies.py` |
| 对话与工具工作负载 | `tests/unit/observability/test_token_wise_workload_scenarios.py` |

两个入口使用 `real_llm` 标记，输出写入 `.pico/evidence/prompt-cache`。真实模型实验需要凭证和预算，选择方式见[测试指南](../docs/development/testing.md)。

## 结果与输出

- 固定模型、Provider、配置、任务集合、预算和重复次数。
- 先验证任务是否完整，再比较成本与时延。
- 分别记录输入、输出、缓存写入和缓存读取 Token。
- 保留任务成功、记录完整和测量有效的独立判断。
- 结论说明适用环境，失败或遗漏调用不能作为费用下降的证据。
- 原始记录、生成报告和凭证放在被忽略的 `.pico` 或仓库外。

提交说明只保留可复现的使用方式，以及有明确测量条件的结论。
