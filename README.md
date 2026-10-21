# Pico

[![CI](https://github.com/yangaobo0235/pico-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yangaobo0235/pico-harness/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

面向本地项目与消息渠道的 AI 助手。Python 运行时统一处理模型、工具、上下文、会话、调度和交付；React + TypeScript 提供 Ink 终端界面和浏览器 Trace 查看器。

## 可以做什么

- 在终端执行单次任务、持续对话、恢复和导出会话。
- 连接配置的模型 Provider，调用文件、搜索、Shell、网页和 MCP 工具。
- 根据上下文预算选择历史、本地技能和可选记忆，处理排队、取消与并发。
- 接收飞书、企业微信、QQ 消息，安排定时任务并向来源交付结果。
- 保存会话、Trace、调用用量与成本，在浏览器筛选、搜索和查看执行详情。
- 通过插件扩展工具和长期记忆 Backend。

公开包不附带外部长期记忆实现，首次配置使用 `--skip-memory`；会话、上下文与本地技能仍可使用。

## 技术与结构

| 部分 | 技术与位置 |
| --- | --- |
| 共享执行内核 | Python 3.12、asyncio、Typer、Pydantic，`src/pico` |
| 终端界面 | Node.js 22、React、TypeScript、Ink，`apps/tui` |
| Trace 查看器 | React DOM、TypeScript、Vite、Node 服务，`apps/tracing-viewer` |
| 共享协议 | OpenRPC/JSON Schema，`contracts` 与 `packages/contracts` |
| 状态与调度 | 文件持久化、Portalocker、Croniter |
| 工程与验证 | uv、npm workspaces、Hatchling、Pytest、Vitest、Ruff、ESLint |

CLI、TUI-RPC、Gateway 和 Cron 创建统一请求，由调度器进入 Agent 的模型/工具循环，再保存会话、记录用量并交付。界面不承担模型与工具副作用。模块地图、依赖方向和生命周期见[项目结构](docs/开发/项目结构.md)。

## 快速开始

需要 Python 3.12、Node.js 22、npm、uv、Git，以及可用的模型端点与凭证。基础运行无需数据库或消息队列。

```powershell
git clone https://github.com/yangaobo0235/pico-harness.git
Set-Location pico-harness
uv sync --frozen --extra dev
npm ci
npm run build
uv run pico onboard --skip-memory
uv run pico
```

向导默认发送首次真实请求；暂不请求可追加 `--skip-test`。需要消息渠道时同步依赖增加 `--extra channels`。安装独立命令、指定工作目录和常见安装问题见[安装与配置](docs/使用/安装与配置.md)。

| 场景 | 源码环境命令 |
| --- | --- |
| 单次任务 | `uv run pico run -m "分析项目入口"` |
| 恢复最近对话 | `uv run pico run --continue` |
| 消息 Gateway | `uv run pico gateway --workspace /path/to/workspace` |
| 静态诊断 | `uv run pico doctor --json` |
| 真实模型探测 | `uv run pico doctor --probe` |
| 查看执行记录 | `uv run pico tracing` |

模型请求可能产生费用。工具文件边界、执行环境、渠道接收规则与插件来源由实际配置决定；私人配置、会话和 Trace 不加入 Git。

## 文档入口

完整入口为[文档导航与维护约定](docs/文档导航.md)。`docs` 使用中文目录和文件名，日常改动优先更新已有主题。

| 想了解什么 | 文档 |
| --- | --- |
| 安装并启动 | [安装与配置](docs/使用/安装与配置.md) |
| 对话、会话、渠道、Cron、Trace | [助手使用](docs/使用/助手使用.md) |
| 模型、工具、插件配置与状态文件 | [配置与状态](docs/参考/配置与状态.md) |
| 人工和 AI 怎样维护代码 | [开发规范](docs/开发/开发规范.md) |
| 环境、IDE 与前后端启动 | [本地开发](docs/开发/本地开发.md) |
| 模块职责与执行原理 | [项目结构](docs/开发/项目结构.md) |
| 接入工具、插件和协议 | [扩展开发](docs/开发/扩展开发.md) |
| 回归、平台、PTY 和真实验收 | [测试说明](docs/开发/测试说明.md) |
| 长期运行、备份、升级和发行门禁 | [运行与发布](docs/运维/运行与发布.md) |
| 故障定位与恢复 | [故障排查](docs/运维/故障排查.md) |

贡献协作见 [CONTRIBUTING.md](CONTRIBUTING.md)，AI 开发入口见 [AGENTS.md](AGENTS.md)，能力与成本评测见 [Benchmark 说明](benchmarks/README.md)。临时计划与执行日志留在 Git 忽略的本机目录，完成后将长期结论写回正式手册。

## License

本项目使用 [Apache License 2.0](LICENSE)，处于 pre-1.0 阶段。第三方归属见 [NOTICES.md](NOTICES.md)，安全报告见 [SECURITY.md](SECURITY.md)。
