# 使用指南

Pico 从终端、消息渠道和定时任务接收工作。一段持续对话称为 Session，其中一次请求称为 Turn；一个 Turn 可以包含多次模型调用和工具执行。

以下命令适用于独立安装的 `pico`。源码开发在仓库根目录加 `uv run` 前缀即可。

## 运行入口

| 入口 | 命令 | 适用场景 |
| --- | --- | --- |
| TUI | `pico` | 查看对话、流式结果与工具事件 |
| 单次 CLI | `pico run -m "..."` | 执行一项任务或脚本调用 |
| 交互 CLI | `pico run` | 在同一前台进程持续对话 |
| Gateway | `pico gateway --workspace /path/to/workspace` | 持续处理消息渠道任务 |
| Trace 查看器 | `pico tracing` | 分析模型和工具执行记录 |

## CLI 与终端界面

### 1. 执行任务

```powershell
pico run -m "分析这个项目的登录流程，列出入口和调用链"
```

默认操作当前目录。需要指定工作目录时使用：

```powershell
pico run --workspace /path/to/project -m "阅读 README，说明项目入口"
```

### 2. 打开 TUI

```powershell
pico
```

TUI 需要实际终端或 IDE 模拟终端。Python 宿主执行模型与工具，Node.js 界面展示增量输出并接收交互。

### 3. 继续或恢复会话

```powershell
pico run --continue -m "解释刚才调用链中的凭证校验"
pico sessions list
pico run --resume <session-id>
```

`<session-id>` 替换为列出的会话 ID。`--session`、`--continue` 和 `--resume` 互斥。默认独立 CLI 调用建立新会话。

恢复会话会加载历史，不会自动重放文件编辑、Shell 命令或外部消息。Ctrl+C 取消当前工作并触发清理。

### 4. 在脚本中使用

```powershell
pico run --no-markdown -m "列出当前仓库的入口文件"
pico run --help
```

`--no-markdown` 输出直接可读的文本。脚本同时检查退出码与必要的执行记录。

## 消息渠道

支持飞书、企业微信和 QQ。渠道运行流程：

```text
安装渠道依赖
  -> 配置应用凭证、平台权限和发送者规则
  -> 启用渠道
  -> 启动 Gateway
  -> 发送真实消息
  -> 确认入站、任务执行和回复地址
```

管理入口：

```powershell
pico channels --help
pico channels list
pico gateway --workspace /path/to/workspace
```

飞书采用 WebSocket 长连接，需要机器人能力、接收事件及已发布的应用版本。其他渠道按各自平台要求配置。

Gateway 必须持续运行。配置保存成功后，还需要用真实消息验证回复是否送达正确会话。渠道字段见[配置参考](../reference/configuration.md)。

## 定时任务

```powershell
pico cron --help
pico cron list
```

根据子命令帮助设置任务时间、内容和投递目标。到期任务进入同一套 Agent 执行流程。

| 任务范围 | 执行进程 | 运行要求 |
| --- | --- | --- |
| CLI/TUI 任务 | 对应交互式进程 | 该进程保持运行 |
| 消息渠道任务 | Gateway | 渠道启用且 Gateway 保持运行 |

关闭终端后，该终端无法持续投递提醒。需要长期接收的任务使用消息渠道和 Gateway。

## 本地技能

Skill 使用包含元数据与操作说明的 `SKILL.md`：

```text
skills/
`-- skill-name/
    `-- SKILL.md
```

工作区技能位于 `<workspace>/skills/<skill-name>/SKILL.md`，内置技能位于 `src/pico/resources/skills`。注册表负责来源与同名技能优先级。

```powershell
pico skills --help
```

技能发现、本轮注入和最终任务效果分别观察。本地技能独立于外部长期记忆，`memory.backend = null` 时仍可使用。

## 状态与诊断

| 命令 | 用途 |
| --- | --- |
| `pico status` | 查看运行配置状态 |
| `pico provider --help` | 管理模型服务配置 |
| `pico plugins --verbose` | 查看插件来源、Manifest 与 Backend 选择 |
| `pico doctor --json` | 静态配置检查 |
| `pico doctor --probe` | 真实模型探测 |
| `pico tracing` | 查看模型、工具与运行 Trace |

真实模型探测可能产生费用。任务未完成、工具失败或达到执行上限时，结合实际输出与 Trace 判断结果。具体排查步骤见[故障排查](troubleshooting.md)。
