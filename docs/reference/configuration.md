# 配置参考

Pico 的配置只有三个来源：被操作仓库的 `.env`、命令行参数、以及代码里的默认值。没有主配置文件，没有用户级配置目录，也没有需要初始化的向导。

真实凭证只从环境变量读取。命令行不接受 key，避免它进入进程列表和 shell 历史。

## 配置位置

| 内容 | 位置或选择方式 |
| --- | --- |
| 项目配置 | 被操作仓库的 `.env`，从 `--cwd` 起向上查找第一个存在的文件 |
| 配置示例 | 仓库保留 `.env.example`，本地复制成 `.env` |
| 会话与运行工件 | 被操作仓库的 `.pico/`，随仓库移动，不进 Git |
| Provider 选择 | `--provider` > `PICO_PROVIDER` > 默认 `deepseek` |
| 工作目录 | `--cwd`，默认 `.` |

路径拼接集中在 `src/pico/config/paths.py`，会话、运行工件与长期记忆各占 `.pico/` 下的一个子目录。

## 最小配置示例

只使用默认 provider 时，`.env` 里一行 key 就够启动：

```text
PICO_DEEPSEEK_API_KEY=replace-with-your-key
```

`replace-with-your-key` 是占位值，替换成实际凭证。两条兼容网关共用一把 key 时改成：

```text
PICO_PROVIDER=openai
PICO_RIGHT_CODES_API_KEY=replace-with-your-key
```

示例里的 provider 与 key 只决定这一次请求走哪条链路，不写入任何状态文件。`.env` 不参与 Git，也不被打包进发行物。

## 优先级

```text
显式 CLI 参数 > .env 里的 PICO_* 变量 > 旧环境变量 > 代码默认值
```

| 配置项 | 显式来源 | 环境变量 | 代码默认 |
| --- | --- | --- | --- |
| Provider | `--provider` | `PICO_PROVIDER` | `deepseek` |
| 模型名 | `--model` | `PICO_<PROVIDER>_MODEL`，回退 `<PROVIDER>_MODEL` | Provider 目录里的默认模型 |
| Base URL | `--base-url` | `PICO_<PROVIDER>_API_BASE`，回退 `<PROVIDER>_API_BASE` | Provider 目录里的默认端点 |
| API key | 不支持 | `PICO_<PROVIDER>_API_KEY` 及回退链 | 无默认值 |
| Ollama 地址 | `--host` | 不读取 | `http://127.0.0.1:11434` |
| 审批策略 | `--approval` | 不读取 | `ask` |
| 追加脱敏名单 | `--secret-env-name` | `PICO_SECRET_ENV_NAMES` | 空 |

`.env` 在创建 provider client 之前加载，并覆盖进程里的同名环境变量，所以“仓库里的配置”和“shell 里残留的旧值”之间不存在谁赢得不确定的情况。

## `.env` 解析规则

| 写法 | 行为 |
| --- | --- |
| `NAME=value` | 按第一个 `=` 切分，值里的等号保留 |
| `export NAME=value` | 接受，方便从 shell 脚本粘贴 |
| `NAME="value"`、`NAME='value'` | 去掉成对的首尾引号，不处理转义 |
| `#` 开头的行与空行 | 跳过 |
| `NAME=$OTHER` | 按字面量 `$OTHER` 读取，不展开变量引用 |
| 缺少 `=` 或变量名非法 | 抛 `ValueError`，不跳过 |

共享一把 key 的网关推荐只填 `PICO_RIGHT_CODES_API_KEY`，不要写 `PICO_OPENAI_API_KEY=$PICO_RIGHT_CODES_API_KEY` 这种展开形式。需要分别控制时，把 key 字符串各写一份。

## Provider 目录

| provider | transport | 默认 Base URL | 默认模型 | API key 回退顺序 |
| --- | --- | --- | --- | --- |
| `deepseek` | Anthropic 兼容 Messages | `https://api.deepseek.com/anthropic` | `deepseek-v4-pro` | `PICO_DEEPSEEK_API_KEY`、`DEEPSEEK_API_KEY` |
| `openai` | OpenAI 兼容 `/responses` | `https://www.right.codes/codex/v1` | `gpt-5.4` | `PICO_OPENAI_API_KEY`、`OPENAI_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_ANTHROPIC_API_KEY`、`ANTHROPIC_API_KEY` |
| `anthropic` | Anthropic 兼容 Messages | `https://www.right.codes/claude/v1` | `claude-sonnet-4-6` | `PICO_ANTHROPIC_API_KEY`、`ANTHROPIC_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_OPENAI_API_KEY`、`OPENAI_API_KEY` |
| `ollama` | 本机服务 | `http://127.0.0.1:11434` | `qwen3.5:4b` | 不需要 |

跨网关的 key 回退是配置事实，写在 `src/pico/config/providers.py`；协议差异属于 `pico.integrations.llm`，装配哪个 client 属于 `pico.bootstrap.providers`。

两点例外值得单独记住：

- DeepSeek 请求里显式关闭 provider-native thinking（`{"type":"disabled"}`）。Pico 的工具协议是文本编码，不回放 thinking block，留着它只会耗尽单步输出预算。后续接入原生工具协议时，必须先实现 thinking block 的完整回放，不能只删掉这个开关。
- Ollama 的模型名不读环境变量，只认 `--model`。可用模型由本机已拉取的镜像决定，配一个不存在的名字比采用默认值更容易造成困惑。

## 环境变量清单

| 变量 | 默认 | 影响 |
| --- | --- | --- |
| `PICO_PROVIDER` | `deepseek` | 未传 `--provider` 时选哪个后端 |
| `PICO_DEEPSEEK_API_BASE` | `https://api.deepseek.com/anthropic` | DeepSeek 端点 |
| `PICO_DEEPSEEK_API_KEY` | 无 | DeepSeek 凭证 |
| `PICO_DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `PICO_OPENAI_API_BASE` | `https://www.right.codes/codex/v1` | OpenAI 兼容端点 |
| `PICO_OPENAI_API_KEY` | 无 | OpenAI 兼容凭证 |
| `PICO_OPENAI_MODEL` | `gpt-5.4` | OpenAI 兼容模型名 |
| `PICO_ANTHROPIC_API_BASE` | `https://www.right.codes/claude/v1` | Anthropic 兼容端点 |
| `PICO_ANTHROPIC_API_KEY` | 无 | Anthropic 兼容凭证 |
| `PICO_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Anthropic 兼容模型名 |
| `PICO_RIGHT_CODES_API_KEY` | 无 | 两条兼容网关路径共用的 key |
| `PICO_SECRET_ENV_NAMES` | 空 | 逗号分隔，追加需要脱敏的环境变量名 |

旧命名 `<PROVIDER>_API_KEY`、`<PROVIDER>_API_BASE`、`<PROVIDER>_MODEL` 仍然参与回退，历史 `.env` 不必一次改完。空字符串视为“没有配置”，因此显式写空值等于落到下一项，而不是把空凭证传给 provider。

## 命令行参数

| 参数 | 默认 | 影响 |
| --- | --- | --- |
| `prompt` | 无 | 位置参数，可多个，拼成一次 one-shot 请求；为空时进入 REPL |
| `--cwd` | `.` | 被操作仓库，同时决定 `.env` 与 `.pico/` 的位置 |
| `--provider` | 见优先级 | 四个合法名称之一 |
| `--model` | Provider 默认 | 模型名覆盖 |
| `--host` | `http://127.0.0.1:11434` | Ollama 服务地址 |
| `--base-url` | Provider 默认 | 云端 provider 的 API 根地址 |
| `--ollama-timeout` | `300` | 秒；仅 Ollama 使用 |
| `--openai-timeout` | `300` | 秒；其余 provider 使用 |
| `--resume` | 无 | 会话 ID 或 `latest` |
| `--approval` | `ask` | `ask`、`auto`、`never` |
| `--secret-env-name` | 空 | 可重复，追加脱敏变量名 |
| `--max-steps` | `6` | 单次请求的工具与模型迭代上限 |
| `--max-new-tokens` | `512` | 单步模型输出上限 |
| `--temperature` | `0.2` | 采样温度 |
| `--top-p` | `0.9` | 仅发送给 Ollama |

帮助文本带默认值（`ArgumentDefaultsHelpFormatter`），因为审批策略、步数预算和 provider 选择都会实质影响一次运行的行为。

## 运行默认值

这些数字集中在 `src/pico/config/models/runtime.py`，命令行与实验脚本可以改写，协议含义不随之变化。

| 常量 | 取值 | 说明 |
| --- | --- | --- |
| `DEFAULT_MAX_STEPS` | `6` | 一轮请求的迭代预算 |
| `DEFAULT_MAX_NEW_TOKENS` | `512` | 单步输出预算 |
| `DEFAULT_REQUEST_TIMEOUT_S` | `300` | 模型请求超时 |
| `MAX_TOOL_OUTPUT` | `4000` | 工具结果写回历史的字符上限 |
| `MAX_HISTORY` | `12000` | 历史渲染的字符上限 |
| Shell 超时 | 默认 `20`，区间 `[1, 120]` | 上限刻意压小，长任务由模型分次发起 |
| `TOOL_SEARCH_MAX_MATCHES` | `200` | `rg` 与 Python 回退路径共用同一个上限 |
| `TOOL_LIST_FILES_MAX_ENTRIES` | `200` | 单次列目录条目上限 |
| `read_file` 默认行区间 | `1` 到 `200` | 越界行区间报参数错误 |
| 委派子 Agent | 默认 `3` 步，最大深度 `1` | 只读，审批策略固定为 `never` |
| Shell 环境白名单 | `HOME`、`LANG`、`LC_ALL`、`LC_CTYPE`、`LOGNAME`、`PATH`、`PWD`、`SHELL`、`TERM`、`TMPDIR`、`TMP`、`TEMP`、`USER` | 不继承父进程全部环境，避免把无关凭证带进命令执行 |

## 上下文预算

预算单位是字符而不是 Token：Pico 不绑定某个供应商的分词器，字符数是各方都能复核的事实。

| 段落 | 默认预算 | 默认下限 | 收缩顺序 |
| --- | --- | --- | --- |
| `prefix` 稳定指令 | `3600` | `1200` | 最后收缩 |
| `memory` 工作记忆 | `1600` | `400` | 第三 |
| `relevant_memory` 相关记忆 | `1200` | `300` | 首先收缩 |
| `history` 历史 | `5200` | `1500` | 第二 |
| `current_request` 当前请求 | 不设预算 | 不裁剪 | 不参与收缩 |

一轮总预算 `DEFAULT_TOTAL_BUDGET = 12000`。未显式覆盖时，各段下限取预算的四分之一且不低于 20 字符，保证压到最狠时段标题和一两行仍然可见。所有段落都到下限后，运行接受超预算继续发送，而不是无限收缩。

相关记忆单轮最多注入 3 条；最近 6 条历史按原文保留，更早的做摘要或折叠重复读取。

## 审批策略

| 策略 | 对高风险工具的行为 | 适用场景 |
| --- | --- | --- |
| `ask` | 在终端询问 `[y/N]`，只有 `y` 与 `yes` 算同意，EOF 按拒绝 | 默认，人工在场 |
| `auto` | 全部放行 | 无人值守的仓库 |
| `never` | 全部拒绝 | 只允许调查的场合 |

只读工具不进入审批。`read_only` 优先于策略：委派出的子 Agent 即使带着 `auto` 也不能写文件。非法的策略值不会换来放权——它落到逐次询问，而没人可以回答时按拒绝处理；命令行上的 `--approval` 更早就失败，因为拼错的 `atuo` 若静默采用默认值，用户会以为自己收紧或放宽了权限。

## 脱敏配置

| 项 | 取值 | 说明 |
| --- | --- | --- |
| 默认名单 | `PICO_*_API_KEY`、`OPENAI_API_KEY`、`OPENAI_API_TOKEN`、`ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`DEEPSEEK_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`GITHUB_PAT`、`GH_PAT` | 无需用户声明也视为敏感 |
| 追加方式 | `PICO_SECRET_ENV_NAMES`（逗号分隔）、`--secret-env-name NAME`（可重复） | 名单比较不区分大小写 |
| 命名启发式 | 等于、以 `API_KEY`、`TOKEN`、`SECRET`、`PASSWORD` 结尾 | `DATABASE_URL` 这类不命中 |
| 占位符 | `<redacted>` | 替换按值长度从长到短，避免短 token 吃掉长 key 的前缀 |

脱敏只覆盖环境变量值形态，不承诺识别出现在配置文件、命令输出或模型回答里的其他密钥形态。

## 代码内开关

下面几项不通过 `.env` 配置，改它们需要改代码，且会被架构检查与测试一起看到。

| 项 | 默认 | 归属 |
| --- | --- | --- |
| Feature flag | `memory`、`relevant_memory`、`context_reduction`、`prompt_cache` 全部开启 | `config/models/features.py`，消融实验临时改写 |
| 扫描跳过的目录 | `.git`、`.pico`、`__pycache__`、`.pytest_cache`、`.ruff_cache`、`.venv`、`venv` | `config/models/runtime.py` |
| 优先读取的项目文档 | `AGENTS.md`、`README.md`、`pyproject.toml`、`package.json` | 同上，按最可能改变行动方式的顺序 |

## 范围之外

Pico 不提供主配置文件、服务进程、消息渠道、图形界面和扩展协议，因此也没有对应的配置面。`.pico/` 之外的目录布局不受支持：需要仓库外状态目录的部署方式，由调用方显式传入根路径。

运行取值与模块归属见[架构与代码归属](../architecture/overview.md)，配置错误的排查路径见[故障排查](../guides/troubleshooting.md)。
