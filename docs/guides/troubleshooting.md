# 故障排查

按启动、配置、模型、工具和交付逐层检查。先定位失败阶段，再执行对应命令，保留版本、退出码和必要的脱敏日志。

## 诊断流程

```text
pico --version
  -> Python 入口能否启动
pico --check
  -> TUI 资源与终端条件是否满足
pico doctor --json
  -> 配置是否有效
pico doctor --probe
  -> 真实模型请求能否完成
pico tracing
  -> 查看模型、工具和任务阶段
```

源码环境使用 `uv run pico` 替代独立命令。`doctor --probe` 会发送真实请求，可能产生费用。

## 启动问题

| 现象 | 检查 | 处理 |
| --- | --- | --- |
| 找不到 `pico` | 工具是否安装、PATH 是否生效 | 从源码用 `uv run pico`，或构建后安装独立工具 |
| Python 找不到模块 | 是否完成 `uv sync`、IDE 解释器是否正确 | 使用仓库 `.venv` 的解释器 |
| TUI 缺少 bundle | `apps/tui/dist/entry.js` 是否存在 | 安装前端依赖并执行 `npm run build:tui` |
| TUI 找不到 Node | `node --version`、IDE 进程的 PATH | 使用 Node.js 22，并重新加载相应运行环境 |
| TUI 没有 TTY | 是否在输出重定向或普通控制台运行 | 使用实际终端或 IDE 模拟终端 |
| 渠道缺少 SDK | 是否安装对应 extra | 安装渠道依赖并使用该环境启动 |

源码修复 TUI 资源：

```powershell
npm ci --prefix apps/tui
npm run build:tui
```

独立工具更新资源或渠道依赖：

```powershell
uv tool install --reinstall .
uv tool install --reinstall ".[channels]"
```

按需要选择其中一条。安装方式见[安装指南](../getting-started/installation.md)。

## 模型与配置问题

```powershell
pico doctor --json
pico doctor --probe
```

检查 Provider、模型标识、端点、凭证和网络。诊断与实际运行使用同一个 `--config` 文件。

出现 Memory Backend 缺失时，公开发行包使用 `pico onboard --skip-memory` 关闭外部长期记忆。重新进入已有配置向导使用 `--reset`，先备份配置。

## 工具与交付问题

| 问题 | 排查要点 |
| --- | --- |
| 文件工具失败 | 当前工作目录、路径边界、读写权限 |
| Shell 或 Sandbox 失败 | 执行器状态、系统支持、依赖与超时 |
| 模型描述失败但无工具证据 | 结合 Trace 核对实际调用和返回值 |
| 消息未进入 | 平台权限、应用发布、接收事件与发送者规则 |
| 消息执行后未收到回复 | Gateway 生命周期、回复地址和平台发送结果 |
| 定时任务未执行或未交付 | 计划是否有效、负责的进程是否存活、投递目标是否正确 |

渠道验证按“入站接收 → 任务执行 → 结果投递”检查。定时任务先运行 `pico cron list` 查看计划，再确认相应 CLI/TUI 或 Gateway 仍在运行。

## 会话与状态位置

默认前台会话按项目保存到 `~/.pico/projects/<project-id>`。显式 `--workspace`、自定义 workspace 和 Gateway 在所选目录保存状态。

找不到会话时检查当前目录、配置路径与 `PICO_HOME`，再使用 `pico sessions list` 查看当前项目的会话。路径规则见[配置参考](../reference/configuration.md)。

恢复对话会读取历史，不会自动撤销或重放工具产生的文件与外部操作。

## 问题报告

- 系统及 Python、Node.js、Pico 版本。
- 启动入口、复现步骤与预期结果。
- 实际输出、退出码和必要的脱敏日志。
- 是否执行过真实模型、消息渠道或 Sandbox 验证。

安全问题按[安全报告流程](../../SECURITY.md)私下提交。
