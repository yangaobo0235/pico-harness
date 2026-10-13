# 测试指南

Pico 的默认回归只验证受控环境中的行为：不连接真实模型，不启动服务，不依赖仓库外的程序。真实模型、外部运行时和计时敏感实验通过 marker 显式选择。

测试结果要说明执行范围、环境条件和跳过原因。跳过只说明环境不具备条件，不能据此判断对应功能已经验证。

## 环境准备

按[贡献指南](../../CONTRIBUTING.md)安装 Python 3.12、uv 与 Git，在仓库根目录执行：

```powershell
uv sync
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

`uv sync` 安装 dev 组的 `pytest`、`pytest-timeout`、`pytest-xdist`、`pre-commit` 和 `ruff`。运行时没有第三方依赖，测试也没有：需要外部程序的场景走 marker，而不是再加一个包。

pytest 配置里 `pythonpath = ["src", "."]`，`import pico` 命中 `src/pico`，`scripts` 与 `benchmarks` 按仓库根解析。所有检查都在仓库根目录执行。

## 测试目录

| 位置 | 验证范围 |
| --- | --- |
| `tests/unit` | 单个职责模块与受控依赖，目录结构镜像 `src/pico` 的分层 |
| `tests/contracts` | 公共入口、请求与消息形状、Provider 与工具协议约定 |
| `tests/integration` | 多模块组合与持久化行为，包括会话、checkpoint 与运行工件 |
| `tests/tooling` | CI 与开发脚本自身 |
| `tests/fixtures` | 测试输入与评测用的 fixture 仓库 |

分层重构之前留下的功能测试文件仍在 `tests` 顶层，读侧行为与它们的断言保持一致；新增测试放入对应的镜像目录，例如上下文收缩的断言落在 `tests/unit/runtime/context`，工具护栏落在 `tests/unit/capabilities/tools`。

## 本地检查流程

### 1. Python 静态检查

```powershell
uv run ruff check src scripts tests examples
uv run ruff format --check src scripts tests examples
```

### 2. 架构边界检查

```powershell
uv run python -m scripts.ci.check_architecture
```

它按 AST 检查静态导入边界，包含函数内的运行时导入，`TYPE_CHECKING` 分支里的纯类型依赖除外。退役的扁平入口 `pico.evaluator`、`pico.metrics`、`pico.models`、`pico.memory` 出现在任何地方都会失败。边界规则见[架构与代码归属](../architecture/overview.md)。

### 3. 功能回归

```powershell
uv run pytest tests -n 4 -q --strict-markers
```

`--strict-markers` 保证拼错的 marker 不会被静默忽略；`-n 4` 是并行 worker 数。

### 4. 构建

```powershell
uv build
```

支持 Make 的环境可以直接 `make check`，它等于 check-architecture + lint + test + build。

## 工程命令

| 命令 | 作用 |
| --- | --- |
| `make install` | 安装依赖并装上 Git hooks |
| `make format` | 格式化 Python 源码 |
| `make check` | 完整本地检查 |
| `make lint-python` | Ruff 检查与格式检查 |
| `make test` | 确定性 Python 回归，不含 opt-in 用例 |
| `make test-performance` | 计时敏感实验，单 worker |
| `make check-architecture` | 导入边界检查 |
| `make benchmark` | 脚本化模型跑冻结基准 |
| `make benchmark-regression` | harness 回归轨道 |
| `make experiments-large` | 大规模记忆与上下文实验 |
| `make experiments-provider` | 真实 provider 对比，需要 key 与预算 |
| `make resume-metrics` | 从运行工件汇总恢复指标 |
| `make check-commits` | 校验提交范围内的 Conventional Commit 主题 |
| `make check-pr-title` | 校验 `PR_TITLE` |
| `make check-large-files` | 检查提交范围内被禁止的资产与超大文件 |
| `make build` | 构建 wheel 与源码归档 |
| `make clean` | 清理缓存与构建产物，包含 `.pico` |

Windows 上没有 Make 时，用上面出现的等价 `uv run` 命令逐条执行；脚本入口都可以直接 `uv run python -m scripts.ci.<name>` 或 `uv run python -m scripts.dev.<name>` 调用。

## 按改动选择测试

| 改动位置 | 建议范围 |
| --- | --- |
| `runtime/agent` | 对应单元测试，外加恢复与 checkpoint 的集成测试 |
| `runtime/context` | 单元测试，并确认 `report.json` 的 prompt 元数据字段仍然自洽 |
| `capabilities/tools` | 单元测试与安全不变量测试 |
| `security` | 单元测试，路径越界与审批分支都要覆盖 |
| `config` | 单元测试与公共入口契约测试 |
| `integrations/llm` | Provider 协议契约测试，真实请求另走 `real_llm` |
| `observability/runs` | 工件写入与读取的集成测试 |
| `extensions/evaluation` | 单元测试，并跑一次 `make benchmark` |
| `scripts` | `tests/tooling` |

```powershell
uv run pytest tests/unit/runtime/agent -q
uv run pytest tests/test_safety_invariants.py -q
```

入口解析、业务执行和外部适配分别选择对应测试。取消、恢复或跨入口行为需要运行集成测试。行为变更的断言应覆盖实际触发条件和结果，而不只是返回值不为空。

修改持久化字段（会话 JSON、checkpoint、运行工件）时，同时更新读取路径的兼容处理，并让旧形状能被 `ensure_session_shape` 补齐。

## 标记与跳过

默认 addopts 排除四类 marker：

| marker | 需要的条件 |
| --- | --- |
| `real_llm` | 可用模型服务与预算，且会产生费用 |
| `external_runtime` | Python 测试环境之外的程序或运行时 |
| `e2e` | 真实子进程，通常还需要可用终端 |
| `performance` | 适合独立计时的环境 |

`rg` 缺失、Ollama 未启动、跨盘符路径不可用这类条件应当在用例内显式判断并跳过，而不是让默认回归依赖它们。跳过原因要写清楚缺什么，让读者能区分“环境不具备”和“功能未实现”。

## 真实模型测试

先配好 key 与预算，再选择具体文件和标记，一次只跑一个文件：

```powershell
uv run pytest <test-file> -m real_llm -n 0 -q
```

这类用例不在默认回归和 CI 里，也不会被 `make test` 收集。真实请求可能产生费用，运行前确认服务、模型和额度；PR 中标明未执行的范围。判定失败时保留 `report.json` 的停止原因和 `resume_status`，它们比一段截断的 stdout 更能说明问题。

## 性能测试

```powershell
uv run pytest tests -m performance -n 0 -q
```

并行 worker 会影响计时，所以强制单 worker。全局 `timeout = 120` 秒对所有用例生效，用例自己不另设超时。阈值失败时保留结果，检查测量环境和实现，报告里写明实际条件。

## 平台范围

| 环境 | 检查范围与条件 |
| --- | --- |
| Windows | 完整 CLI、控制循环、工具、会话与工件回归 |
| Linux | 同上，CI 矩阵包含 `ubuntu-latest` 与 `windows-latest` |
| `rg` | 缺失时 `search` 走 Python 回退路径，两条路径的返回形状一致 |
| 符号链接与跨盘符 | 探测当前用户权限和挂载情况，按实际能力执行 |
| 评测任务卡的 verifier | 任务卡以 `python3 -c '...'` 书写，只在 POSIX shell 语义下成立；Windows 上按探测结果跳过，跳过表示该范围未验证 |
| IANA 时区 | 评测工件的 `captured_at` 使用 `Asia/Shanghai`；Windows 无系统 tz 库，由 dev 组的 `tzdata` 提供 |
| Ollama | 需要本机服务在跑且镜像已拉取，属于 `external_runtime` |
| 真实模型 | 分别按 provider 验证端到端链路 |

CI 在两个操作系统上执行 `uv sync --frozen`、Ruff 两项检查、架构检查、默认回归和 `uv build`，PR 另外校验标题格式。真实模型与实验不在 CI 里跑。

## 与评测的分工

评测不是测试。`make benchmark` 用 `FakeModelClient` 的确定性输出驱动完整链路，验证的是运行组合与工件口径，不需要凭证也不产生费用；能力与成本结论走 `make experiments-large` 和 `make experiments-provider`。两者的字段口径、失败分类和复现条件见[Benchmark 说明](../../benchmarks/README.md)。

构建后的 wheel 建议在仓库外的干净环境里安装一次，可以提前发现对源码树路径的意外依赖。
