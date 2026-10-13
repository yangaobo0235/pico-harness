# 故障排查

按启动、配置、模型请求、工具执行、状态与工件逐层检查。先定位失败发生在哪一段，再执行对应命令，保留版本、退出码和必要的脱敏日志。

Pico 没有自检子命令，也不会主动探测端点可用性。可依赖的现场证据只有三类：首屏打印的装配结果、`.pico/` 下的运行工件、以及抛给终端的异常文本。

## 诊断顺序

```text
uv run pico --help
  -> 入口能否加载，参数默认值是否符合预期
uv run pico "只读一个问题"
  -> 首屏的 WORKSPACE / MODEL / BRANCH / APPROVAL / SESSION 是否正确
.pico/sessions/<session-id>.json
  -> 会话是否落盘，恢复状态是什么
.pico/runs/<run_id>/report.json
  -> 停止原因、工具步数、prompt 元数据
.pico/runs/<run_id>/trace.jsonl
  -> 逐步过程：哪一次调用失败、失败文本是什么
```

源码环境用 `uv run pico`，安装为本地包后直接用 `pico`。真实请求会产生费用，排查时优先用只读问题。

## 启动问题

| 现象 | 检查 | 处理 |
| --- | --- | --- |
| 找不到 `pico` 命令 | 是否执行过 `pip install -e .` | 在源码根用 `uv run pico` |
| `ModuleNotFoundError: No module named 'pico'` | 解释器是否为仓库 `.venv`，`src` 是否被标为 Sources Root | 用仓库 `.venv`，或走 `python -m pico` |
| Python 版本不被接受 | `python --version` 是否为 3.12 | 安装 3.12；`>=3.12,<3.13` 是硬约束 |
| `unknown provider: xxx. expected one of: ...` | `--provider` 或 `PICO_PROVIDER` 的取值 | 改成四个合法名称之一 |
| `unknown approval policy: xxx` | `--approval` 的拼写 | 只接受 `ask`、`auto`、`never` |
| `invalid .env line: xxx` | `.env` 里是否有缺少 `=` 的行 | 补齐赋值；解析器不会跳过这类行 |
| `invalid .env variable name: xxx` | 变量名是否以字母或下划线开头 | 改成合法名称；含空格或 `-` 的名字会被拒绝 |
| 首屏的 WORKSPACE 不是目标仓库 | `--cwd` 是否给对 | 会话与工件写在解析出的仓库根下 |

`.env` 的两类错误是刻意直接抛出的：静默跳过会让“key 没生效”变成要靠请求失败才能发现的问题。

## 配置与凭证问题

```powershell
Get-Content .env | Select-String -Pattern "PICO_"
uv run pico --provider deepseek "reply with OK"
```

Pico 不会校验凭证是否有效，缺失的 key 会以空值传给 client：Anthropic 兼容请求照常带 `x-api-key` 头，OpenAI 兼容请求在 key 为空时不发 `Authorization`。也就是说，配置错误的表现是服务端返回的鉴权失败，不是本地报错。

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `HTTP 401` 或 `HTTP 403` | key 未配置、已失效，或命中了回退链里的另一把 key | 只填 `PICO_DEEPSEEK_API_KEY` 或 `PICO_RIGHT_CODES_API_KEY`，其余留空 |
| 额度不足的错误正文 | 协议与端点已打通，当前 key 没有可用额度 | 换一把有额度的 key，或在网关后台处理额度 |
| `Could not reach the ... backend.` 附带 Base URL 与 Model | 端点写错、模型名不存在或网络不可达 | 对照消息里两项，它们就是最常见的故障点 |
| `.env` 里写了 `$OTHER` 形式的值 | 解析器只读字面量，不展开变量引用 | 直接把 key 字符串写进目标变量 |
| 换了 provider 但行为没变 | 旧环境变量或 `PICO_PROVIDER` 覆盖了预期 | 显式传 `--provider`，它的优先级最高 |

优先级固定为：显式 CLI 参数 > `.env` 里的 `PICO_*` > 旧环境变量 > 代码默认值。`.env` 从 `--cwd` 起向上查找第一个存在的文件，并在创建 provider client 之前覆盖进程里的同名变量。

Ollama 需要本机服务在跑、模型镜像已拉取。`--model` 之外的模型变量对 Ollama 无效，因为它的可用模型由本机镜像决定。

## 模型请求问题

两个兼容网关在 5xx 与网络错误时最多尝试三次，线性退避；Ollama 单次尝试不重试。超时由 provider 决定读哪个参数，默认 300 秒。

one-shot 失败时异常文本写到 stderr 并返回退出码 `1`；REPL 里同一异常只打印一次并继续循环。

| 报错文本 | 含义 | 下一步 |
| --- | --- | --- |
| `Anthropic-compatible response ended before a text block` | 响应里只有 thinking 等非文本块 | 确认模型支持当前协议；DeepSeek 侧的 thinking 已由 runtime 显式关闭 |
| `... request failed with HTTP <code>: <body>` | 非 2xx，正文原样保留 | 读正文里的字段名，它通常直接指出参数问题 |
| `... error: <detail>` | 2xx 里带回业务错误 | 按 detail 处理，多为额度或模型名 |
| 输出反复无法解析、最终 `retry_limit_reached` | 模型持续返回不符合文本工具协议的内容 | 换更强的模型或提高 `--max-new-tokens`；单步输出被截断时协议标签会不完整 |

## 工具与审批问题

工具失败不会中断整轮请求：执行器把拒绝和异常都规范化成 `error: ...` 文本回灌给模型，由它在下一步改正。

| 现象 | 排查要点 |
| --- | --- |
| `error: unknown tool 'xxx'` | 模型用了未登记的名字，当前只有七个工具 |
| `error: tool 'xxx' is not allowed in this run` | 装配方传入了允许名单，评测按任务的 `allowed_tools` 收紧；子 Agent 走只读与深度限制，不共用这条名单 |
| `error: invalid arguments for xxx` 附带 example | 参数格式错误，回灌的示例就是正确写法 |
| `path escapes workspace: ...` | 解析 `..` 与符号链接之后仍在仓库外；跨盘符路径同样按越界处理 |
| `old_text must occur exactly once, found N` | `patch_file` 要求唯一匹配，扩大上下文或改用 `write_file` |
| `timeout must be in [1, 120]` | `run_shell` 的超时区间，长任务应由模型分次发起 |
| `error: repeated identical tool call` | 同一工具同一参数的重复调用被拦下，历史里也会折叠重复读取 |
| `error: approval denied for xxx` | `never` 策略、只读子 Agent，或用户在 `[y/N]` 处拒绝 |
| 命令里看不到自定义环境变量 | `run_shell` 只继承白名单变量，与任务无关的凭证不会进入执行环境 |
| 工具输出被截断 | 所有结果统一裁剪到 4000 字符 |

`ask` 策略下读到 EOF 一律按拒绝处理：管道输入结束或按下 Ctrl-D 时没有人可以回答，这是唯一安全的默认值。需要无人值守时把策略设为 `auto` 或 `never`，而不是在审批环节加自动同意。

## 上下文与预算问题

一轮 prompt 的预算是 12000 字符，分配给稳定指令 3600、工作记忆 1600、相关记忆 1200、历史 5200，当前请求不裁剪。超预算时按相关记忆、历史、工作记忆、稳定指令的顺序收缩，各段有下限；全部到下限后接受超预算继续发送。

模型“忘记”早期内容时，读 `report.json` 里的 `prompt_metadata`：各段字符数、收缩记录和被牺牲的段落都在那里，不需要重跑同样输入。相关记忆单轮最多注入 3 条，最近 6 条历史按原文保留，更早的走摘要或折叠。

## 恢复与状态问题

| `resume_status` | 含义 | 建议动作 |
| --- | --- | --- |
| `no-checkpoint` | 会话里没有 checkpoint，全新起步 | 无需处理 |
| `full-valid` | 关键文件新鲜度与 runtime 身份都对得上 | 直接继续 |
| `partial-stale` | 有记录过的文件变陈旧 | 让模型重读该文件再动手 |
| `workspace-mismatch` | 文件没变但工作区指纹变了 | 视为换了一个现场，重建目标与下一步 |
| `schema-mismatch` | checkpoint 来自不兼容的旧格式，不做迁移 | 放弃该现场，从新会话开始 |

找不到会话时用 `/session` 打印路径，再确认 `--cwd` 是否指向同一个仓库：会话写在被操作仓库的 `.pico/sessions/`，不跨仓库共享。列出多个会话时按文件修改时间排序，`latest` 取最后一个。

恢复读取历史，不会重放也绝不会撤销此前的文件与命令效果。

## 长期记忆问题

晋升需要两个条件同时成立：本轮用户输入表达了保留意图，且最终答案使用了约定前缀行。只有其中之一时不会写入，也不会给出拒绝记录。

| 拒绝原因 | 触发条件 |
| --- | --- |
| `empty` | 前缀之后没有内容 |
| `secret_shaped` | 含占位符或密钥形态文本 |
| `transient_task_state` | 只是当前目标、卡点、下一步一类现场信息 |
| `noisy_output` | 夹带 stdout、stderr、traceback、exit_code，或超过 220 字符 |

拒绝记录以 `主题:原因` 的形式进入 `report.json` 的 `durable_rejections`，用来区分“模型没给候选”和“给了候选但被规则挡下”。

`.pico/memory/` 是纯 markdown，可以手工编辑。认不出的行会被跳过而不是报错，所以改坏格式的后果是那条信息暂时消失，不是读取失败。

## 工件与脱敏

写入 Trace 与 Report 前，Pico 按“变量名像凭证”和“调用方显式声明”两条线索替换环境变量值，占位符是 `<redacted>`，命中名单统计在 `redacted_env` 里。

默认名单覆盖常见 provider 变量与 `GITHUB_PAT`；命名启发式是 `API_KEY`、`TOKEN`、`SECRET`、`PASSWORD`。需要追加时使用 `PICO_SECRET_ENV_NAMES`（逗号分隔）或重复传 `--secret-env-name NAME`。

覆盖范围只有环境变量值形态：出现在配置文件、命令输出或模型回答里的其他密钥形态不会被自动识别。粘贴日志前仍然要人工过一遍。

## 问题报告

- 操作系统、Python 版本与 Pico 提交号。
- 启动方式、完整命令行与复现步骤。
- 实际输出、退出码，以及脱敏后的 `report.json` 关键段落。
- 停止原因与 `resume_status`。
- 是否执行过真实模型请求，用的是哪个 provider 与模型。

贡献流程与验证命令见[贡献指南](../../CONTRIBUTING.md)，测试范围与标记见[测试指南](../development/testing.md)，模块归属见[架构与代码归属](../architecture/overview.md)。
