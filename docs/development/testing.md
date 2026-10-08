# 测试指南

Pico 的默认回归验证受控环境中的行为，真实模型、消息平台、VM 和性能实验通过标记显式选择。测试结果应说明执行范围、环境条件和跳过原因。

## 环境准备

按[贡献指南](../../CONTRIBUTING.md)安装 Python 和 Node.js 开发依赖。在仓库根目录执行检查，使用 `uv run` 保证 Python 从当前开发环境加载。

## 测试目录

| 位置 | 验证范围 |
| --- | --- |
| `tests/unit` | 单个职责模块与受控依赖 |
| `tests/contracts` | 请求、Provider、Backend、插件和协议约定 |
| `tests/integration` | 多模块组合及持久化行为 |
| `tests/e2e` | 实际进程与终端链路 |
| `tests/packaging` | 安装器、发行资源和仓库策略 |
| `tests/tooling` | CI、开发与发布脚本 |
| `tests/fixtures` | 测试输入 |
| `apps/tui/tests/unit` | 终端界面、状态、Hook 和 RPC 客户端 |

## 本地检查流程

### 1. Python 静态检查

```powershell
uv run ruff check src scripts tests benchmarks hatch_build.py
uv run ruff format --check src scripts tests benchmarks hatch_build.py
```

### 2. 架构、发布树与文档检查

```powershell
uv run python -m scripts.ci.check_architecture
uv run python -m scripts.ci.check_repository
uv run python -m scripts.ci.check_docs
```

### 3. 前端协议、类型与构建检查

```powershell
npm --prefix apps/tui run lint
npm --prefix apps/tui run lint:rpc
npm --prefix apps/tui run lint:rpc-surface
npm run typecheck:tui
npm run build:tui
```

### 4. 功能回归

```powershell
uv run pytest tests -n 4 -q --strict-markers
npm run test:tui
```

支持 Make 的环境可用 `make check` 执行完整本地检查。默认 Python 回归隔离 Home 与受控依赖，不连接真实模型、消息平台或 VM。

## 按改动选择测试

修改 Agent 执行逻辑时：

```powershell
uv run pytest tests/unit/runtime/agent -q
```

入口解析、业务执行和外部适配分别选择对应测试。取消、恢复或跨入口行为还需运行集成测试。行为变更的断言应覆盖实际触发条件和结果。

## 真实环境与性能测试

默认排除以下标记：

| 标记 | 条件 |
| --- | --- |
| `real_llm`、`llm_judge` | 可用模型服务与预算 |
| `real_channel` | 消息平台应用及凭证 |
| `real_vm` | 实际 VM 执行环境 |
| `external_runtime` | 指定外部程序 |
| `e2e` | 实际子进程或终端环境 |
| `performance` | 适合独立计时的环境 |

选择具体文件与标记，例如 `uv run pytest <test-file> -m real_llm -n 0 -q`。模型请求可能产生费用，运行前确认服务与预算。

性能测试独立执行：

```powershell
uv run pytest tests -m performance -n 0 -q
```

并行负载会影响计时。阈值失败时保留结果，检查测量环境和实现，报告中写明实际条件。

## 平台范围

| 环境 | 检查范围与条件 |
| --- | --- |
| Windows | 核心 CLI、Agent、会话、调度和前端自动化回归 |
| 符号链接 | 探测当前用户权限，按实际能力执行 |
| POSIX 接口 | PTY、Unix Socket、文件描述符及权限位测试需要对应系统接口 |
| TUI 交互 | 在有 TTY 的实际终端或模拟终端中检查 |
| 模型、渠道与 VM | 分别验证真实端到端链路 |

平台跳过说明环境不具备条件，不能据此判断对应功能已经验证。

## 发行包与评测

构建后的 wheel 安装到仓库外，检查 CLI、模板、技能、TUI 和 Trace 查看器资源。使用独立环境可以发现资源遗漏以及对工作区源码的意外依赖。

构建与发行校验见[贡献指南](../../CONTRIBUTING.md)，能力和成本实验见[Benchmark 说明](../../benchmarks/README.md)。
