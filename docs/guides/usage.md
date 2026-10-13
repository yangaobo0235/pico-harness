# 使用指南

Pico 从终端接收仓库里的工作。一段持续对话是一个 Session，其中一次输入是一个 Turn；一个 Turn 可以包含多次模型调用和工具执行，模型看不到也调不动的东西不会发生。

终端是当前唯一入口：没有服务进程、消息渠道和图形界面。以下命令都在 Pico 仓库里执行；在其他仓库里工作时把 `uv run pico` 换成安装后的 `pico --cwd <目标仓库>`。

## 运行方式

| 方式 | 命令 | 行为 |
| --- | --- | --- |
| one-shot | `uv run pico "检查测试失败并给出修复建议"` | 执行一次请求，打印答案，退出 |
| 交互 REPL | `uv run pico` | 复用同一个实例，历史与工作记忆跨轮延续 |
| 恢复会话 | `uv run pico --resume latest` | 载入最近修改的会话文件继续工作 |
| 恢复指定会话 | `uv run pico --resume 20260415-093012-ab12cd` | 载入指定会话 ID |

位置参数 `prompt` 可以传多个词，Pico 把它们拼成一次 one-shot 请求；没有位置参数时进入 REPL。

## 执行任务

```powershell
uv run pico "阅读 src 下的入口文件，说明一次请求经过哪些模块"
uv run pico --cwd D:\path\to\repo "找出所有 TODO 并按文件汇总"
```

默认操作当前目录。Pico 在启动时采集工作区快照：仓库根、当前目录、分支与默认分支，以及 `AGENTS.md`、`README.md` 一类项目文档。文件类工具的相对路径都锚定在仓库根之内，在子目录启动时这一点尤其重要。

## 常用参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--cwd` | `.` | 被操作的仓库 |
| `--provider` | `PICO_PROVIDER`，再默认 `deepseek` | `ollama`、`openai`、`anthropic`、`deepseek` 之一 |
| `--model` | Provider 变量 | 模型名覆盖 |
| `--host` | `http://127.0.0.1:11434` | Ollama 服务地址 |
| `--base-url` | Provider 默认 | deepseek / openai / anthropic 的 API 根地址 |
| `--ollama-timeout` | `300` | 秒；provider 为 Ollama 时生效 |
| `--openai-timeout` | `300` | 秒；其余 provider 生效 |
| `--resume` | 无 | 会话 ID 或 `latest` |
| `--approval` | `ask` | `ask`、`auto`、`never` |
| `--secret-env-name` | 空 | 可重复，追加需要脱敏的环境变量名 |
| `--max-steps` | `6` | 单次请求的工具与模型迭代上限 |
| `--max-new-tokens` | `512` | 单步模型输出上限 |
| `--temperature` | `0.2` | 采样温度 |
| `--top-p` | `0.9` | 仅发送给 Ollama |

两个超时参数按选中的 provider 取用，不会因为写了另一个名字而生效。非法的 `--provider` 与 `--approval` 在解析阶段就失败，不会退化成默认值——静默采用默认审批策略比报错危险得多。完整取值与来源见[配置参考](../reference/configuration.md)。

## 交互命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 打印内置命令清单，不消耗模型请求 |
| `/memory` | 打印提炼后的工作记忆 |
| `/session` | 打印当前会话文件路径 |
| `/reset` | 清空历史与工作记忆，保留会话 ID 与 checkpoint |
| `/exit`、`/quit` | 退出 REPL |

空输入直接跳过，方便连续回车。REPL 里的内置命令在本地处理，不进入模型上下文。

## 工具与审批

模型可以申请的动只有七个，其中三个是高风险动作，受审批策略控制：

| 工具 | 类型 | 受审批控制 | 边界 |
| --- | --- | --- | --- |
| `list_files` | 只读 | 否 | 单次最多 200 条，跳过 `.git`、`.venv`、`.pico` 等目录 |
| `read_file` | 只读 | 否 | 默认读第 1 到 200 行 |
| `search` | 只读 | 否 | 优先用 `rg`，缺失时走 Python 遍历，两条路径返回同样的 `相对路径:行号:内容`；命中上限 200 条 |
| `run_shell` | 写入风险 | 是 | 超时 1 到 120 秒，默认 20 秒；执行环境是白名单变量，不是完整父进程环境 |
| `write_file` | 写入风险 | 是 | 路径必须解析在仓库根之内 |
| `patch_file` | 写入风险 | 是 | `old_text` 必须在文件里精确出现一次 |
| `delegate` | 只读 | 否 | 交给受限子 Agent，默认 3 步 |

`ask` 会在终端打印工具名与参数并等待 `[y/N]` 回答，只有 `y` 与 `yes` 算同意，读到 EOF 按拒绝处理；一次放行不会外溢到后续同类调用。`auto` 全部放行，`never` 全部拒绝。

`delegate` 派出的子 Agent 只读、审批策略固定为 `never`，即使父 Agent 处于 `auto` 也不能改文件。深度耗尽后该工具连定义都不再暴露给模型，递归展开在注册层就被切断。

工具结果统一裁剪到 4000 字符再写回历史。高风险动作执行前后各采集一次工作区快照，差异随运行工件一起记录。

## 继续与恢复

```powershell
uv run pico
/session
uv run pico --resume 20260415-093012-ab12cd
```

会话保存在被操作仓库的 `.pico/sessions/<session-id>.json`，内含历史、工作记忆、checkpoint、runtime 身份与恢复状态。恢复时 Pico 核对关键文件的新鲜度与工作区指纹，把结论记录成 `resume_status`；状态含义见[故障排查](troubleshooting.md)。

恢复读取历史，不会重放此前的文件编辑或 Shell 命令，也不会撤销它们。

## 长期记忆

跨会话事实在 `.pico/memory/` 下，一份 `MEMORY.md` 索引加若干 `topics/<slug>.md` 笔记。晋升需要同时满足两个条件：

| 条件 | 要求 |
| --- | --- |
| 用户意图 | 本轮输入里出现 记住、保存、记录、沉淀 或 capture、remember、save、store、persist、note |
| 答案格式 | 最终答案里用 `Project convention:`、`Decision:`、`Dependency:`、`Preference:` 或对应中文前缀起行 |

```powershell
uv run pico "记住这条约定：Project convention: 新增工具必须声明 risky 标记"
```

含密钥形态、属于当前任务现场（当前目标、卡点、下一步等）、夹带 stdout/stderr/traceback 或超过 220 字符的候选会被拒绝，拒绝原因写进报告。晋升是用户请求的结果，不是模型自发的行为：没有意图词时，即使答案里出现约定前缀也不会写入。

## 运行工件

每次运行在 `.pico/runs/<run_id>/` 下写三份文件，`.pico/` 整体不进 Git：

| 文件 | 内容 |
| --- | --- |
| `task_state.json` | 尝试次数、工具步数、状态、停止原因与最终答案 |
| `trace.jsonl` | prompt、模型、工具、checkpoint 与结束阶段的事件时间线 |
| `report.json` | 结果摘要、prompt 元数据、长期记忆变动与脱敏统计 |

报告的停止原因有四种：`final_answer_returned`、`step_limit_reached`、`retry_limit_reached`、`model_error`。预算耗尽时循环会再请求一次并要求只给结论，所以步数超限仍然可能带着一段答案结束。

## 在脚本里使用

```powershell
uv run pico "列出仓库根的一级目录"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

| 场景 | 退出码 |
| --- | --- |
| one-shot 成功 | `0` |
| one-shot 模型请求抛错 | `1`，异常文本写到 stderr |
| REPL 中 Ctrl-D 或 Ctrl-C | `0` |
| REPL 中单次模型请求失败 | 继续循环，错误写到 stderr，不改变退出码 |

脚本调用建议同时检查退出码与 `report.json`：非零退出码只说明请求链路失败，任务是否做完要看停止原因和最终答案。

## 边界与取舍

一轮 prompt 的预算是 12000 字符，按稳定指令、工作记忆、相关记忆、历史、当前请求分段分配；当前请求永不裁剪，超预算时先牺牲相关记忆与历史。最近 6 条历史按原文保留，更早的走摘要或折叠重复读取。数字与收缩顺序见[配置参考](../reference/configuration.md)。

Pico 不判断命令内容是否安全，也不维护命令白名单——那会让模型无法执行仓库真正需要的构建脚本。安全边界落在三处：路径锚定、审批策略、Shell 环境白名单。

排查步骤见[故障排查](troubleshooting.md)，工程命令见[测试指南](../development/testing.md)，模块归属见[架构与代码归属](../architecture/overview.md)。
