# 配置参考

Pico 使用 JSON 保存模型、工具、渠道和运行配置。首次使用通过 `pico onboard --skip-memory` 创建配置；需要手动调整时按下列字段与路径规则操作。

## 配置位置

| 内容 | 默认位置或选择方式 |
| --- | --- |
| 主配置 | `~/.pico/config.json` |
| 产品状态根目录 | `~/.pico`，可通过 `PICO_HOME` 覆盖 |
| 独立配置 | 支持该选项的命令使用 `--config /path/to/config.json` |
| 默认前台项目状态 | `~/.pico/projects/<project-id>` |

字段支持配置模型约定的 camelCase 与 snake_case 名称。完整定义见[基础配置模型](../../src/pico/config/models/runtime.py)和[功能配置模型](../../src/pico/config/models/features.py)。

## 最小配置示例

下面连接 OpenAI 兼容端点，关闭外部长期记忆，并限制工具文件访问范围：

```json
{
  "agents": {
    "defaults": {
      "provider": "custom",
      "model": "your-model",
      "maxToolIterations": 40,
      "contextWindowTokens": 65536
    }
  },
  "providers": {
    "custom": {
      "apiBase": "https://your-endpoint.example/v1",
      "apiKey": "replace-with-your-key"
    }
  },
  "tools": {
    "restrictToWorkspace": true
  },
  "memory": {
    "backend": null
  }
}
```

`your-model`、端点和 Key 是占位值，替换为实际服务配置。该示例的工具边界限制不等于开启 Sandbox；命令执行环境由 `tools.sandbox` 决定。

## 配置块职责

| 配置块 | 主要用途 |
| --- | --- |
| `agents.defaults` | Provider、模型、迭代上限、上下文窗口和工作目录 |
| `providers` | 模型端点、凭证及 Provider 专属设置 |
| `tools` | 路径限制、Shell、Sandbox、MCP 和禁用工具 |
| `channels` | 渠道连接、发送者规则与消息进度 |
| `context` | 上下文预算、历史选择与裁剪 |
| `memory` | 外部长期记忆 Backend 和 Recall 参数 |
| `plugins` | 插件禁用列表和专属配置 |
| `callEfficiency` | 调用缓存与用量计量 |
| `runtime` | 执行约束和检查点 |
| `tracing` | Trace 记录与查看器设置 |

## 工作目录与项目状态

工作目录决定工具操作的现场；状态目录保存会话和运行数据。

| 启动方式 | 工作目录 | 项目状态 |
| --- | --- | --- |
| 默认前台 CLI/TUI | 当前目录 | 产品状态根目录下的 `projects/<project-id>` |
| 显式 `--workspace` | 参数指定的目录 | 同一目录 |
| 配置自定义 `agents.defaults.workspace` | 配置指定的目录 | 同一目录 |
| Gateway | 配置或参数指定的目录 | 同一目录 |

默认前台目录按项目隔离状态。显式目录和长期服务可以使用专用运行目录，避免把会话等数据放进源码仓库。路径解析实现见[路径规则](../../src/pico/config/paths.py)。

## 模型服务

`agents.defaults.provider` 选择 Provider，`agents.defaults.model` 选择模型标识，`providers` 提供端点与凭证。

```powershell
pico provider --help
pico doctor --json
pico doctor --probe
```

先检查配置，再执行真实请求。模型名称正确且配置能加载，并不保证凭证、端点和网络可用。

## 消息渠道

飞书、企业微信和 QQ 分别使用 `channels.feishu`、`channels.wecom`、`channels.qq`。需要安装渠道依赖、设置有效凭证与平台权限，并运行 Gateway。

```powershell
pico channels show feishu
pico channels list
```

`channels show` 列出可配置字段。按所选平台设置发送者和群消息规则，使用真实入站消息验证收发。

## 插件与外部记忆

| 项目 | 规则 |
| --- | --- |
| 插件来源 | 内置位置、用户产品目录的 `plugins`、已安装的 `pico.plugins` entry point |
| 工作区插件目录 | `.pico/plugins` 不自动作为执行来源 |
| 插件禁用 | `plugins.disabled` 按插件 ID 设置 |
| 插件配置 | `plugins.config` 按插件 ID 提供专属配置 |
| 外部记忆关闭 | `memory.backend = null` |
| 外部记忆启用 | 安装能提供对应 Backend 能力的插件，再选择 Backend 名称 |

插件属于可执行代码，来源由部署者控制。发现状态与当前 Backend 可通过 `pico plugins --verbose` 查看。

公开发行包不附带外部长期记忆实现。关闭该能力保留会话、上下文和本地技能。扩展协议分别位于 `src/pico/integrations/plugins` 和 `src/pico/capabilities/memory/contracts.py`。

## 本地配置管理

真实配置中的凭证留在本地；提交示例只使用占位值。修改已有配置前保留备份，诊断和实际运行使用同一 `--config` 路径。连接与运行问题见[故障排查](../guides/troubleshooting.md)。
