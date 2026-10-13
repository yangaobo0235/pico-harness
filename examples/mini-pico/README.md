# mini-pico

pico 的教学尺寸实现：一个能从头读到尾、也能真的跑起来的极小 agent harness。

它只保留一条主线——一次请求如何被扩展成「组装上下文 → 请求模型 → 解析输出 → 执行工具 → 回灌结果 → 继续下一轮」的控制循环，并把这轮发生的每一件事落成可复盘的文件。运行时零第三方依赖，默认后端是脚本化的假模型客户端，因此不需要 API key、不需要联网就能看见完整行为。

它不是产品，也不打算变成产品。会话恢复、上下文预算、记忆、checkpoint、工件脱敏、多 Provider、交互式审批、子 Agent 委派这些生产必需的部分都被有意省略，它们属于主项目 `src/pico/`。

## 为什么是单层包

主项目按职责分层（`interfaces` / `bootstrap` / `runtime` / `capabilities` / `integrations` / `security` / `observability` / `contracts` / `shared`），因为生产代码需要「改一处不牵动别处」的边界、可测试性与依赖方向。**生产包用的就是 `src/pico/` 那套分层结构，这个例子不是那种结构的简化版，而是另一种取舍**：

- 教学实现的第一目标是「一个人在一小时内读完」，所以模块数压到 11 个、总量约一千行，单个模块不超过 200 行，读完一次跳转不超过两层。
- 分层要付出「同一件事散落在多个目录」的成本。对读者来说，`TaskState` 与写出 `task_state.json` 的 `RunStore` 放在同一个 `state.py` 里，比分别读到 `contracts/` 和 `observability/` 更容易建立因果。
- 反过来，分层解决的是演进问题而不是理解问题。示例不演进，所以这笔成本可以省掉。

因此这里刻意保持单层 `mini_pico/` + `tests/`。想理解分层为什么值得，请读主项目；想理解 agent harness 本身在做什么，先读这里。

## 与主项目的对应关系

| mini-pico 模块 | 这里负责什么 | 主项目里归谁 |
| --- | --- | --- |
| `mini_pico/cli.py` | 参数解析、单次执行、最小 REPL | `src/pico/interfaces/cli/app.py`、`src/pico/interfaces/cli/repl.py` |
| `mini_pico/runtime.py` | 运行时门面 `Pico`：装配、历史、文本协议解析、报告 | `src/pico/runtime/agent/agent.py`、`src/pico/runtime/agent/prompts.py` |
| `mini_pico/agent_loop.py` | 控制循环，工具步数与请求次数两个上限 | `src/pico/runtime/agent/loop.py` |
| `mini_pico/context_manager.py` | 每轮 Prompt 的拼装与长度元数据 | `src/pico/runtime/context/assembler.py`、`src/pico/runtime/context/budget.py`、`src/pico/runtime/context/segments/history.py`、`src/pico/runtime/context/instructions/builder.py` |
| `mini_pico/providers.py` | `complete(prompt, max_new_tokens)` 这个形状与假后端 | `src/pico/integrations/llm/contracts.py`、`src/pico/integrations/llm/providers/fake.py`，真实端点是同目录的 `openai_compat.py`、`anthropic_compat.py`、`ollama.py` |
| `mini_pico/tools.py` | 工具目录、Prompt 签名与参数校验 | `src/pico/capabilities/tools/registry.py`、`src/pico/capabilities/tools/builtin/filesystem.py`、`src/pico/capabilities/tools/builtin/file_search.py` |
| `mini_pico/tool_executor.py` | 执行护栏，统一产出 `ToolExecutionResult` | `src/pico/capabilities/tools/executor.py`、`src/pico/capabilities/tools/contracts.py`、`src/pico/security/authorization/approval.py` |
| `mini_pico/state.py` 的 `TaskState` | 「这次请求到哪了」的状态词汇与字段集合 | `src/pico/contracts/turns.py` |
| `mini_pico/state.py` 的 `RunStore` | 三份运行工件的落盘 | `src/pico/observability/runs/store.py`、`src/pico/observability/runs/report.py` |
| `mini_pico/workspace.py` 的 `Workspace` | 路径归属判断与工作区快照 | `src/pico/runtime/workspace/snapshot.py`、`src/pico/security/authorization/workspace_paths.py` |
| `mini_pico/workspace.py` 的 `clip` | 超长文本的定长裁剪 | `src/pico/shared/text.py` |

对应关系不是名字一一对应，而是职责一一对应。例如 `Pico.parse` 在主项目里被移出运行时，成为 `runtime/agent/prompts.py`；`RuntimeError` 级别的会话恢复在这里根本没有对应物。

## 一次运行长什么样

```text
用户输入
  -> TaskState.create()，建立 .mini-pico/runs/<run_id>/ 并写第一份 task_state.json
  -> ContextManager.build()：工具签名 + 工作区快照 + 最近 12 条历史 + 本轮请求
  -> FakeModelClient.complete()
  -> Pico.parse()：tool / final / retry
  -> tool  -> ToolExecutor.execute() -> 结果写回 history -> 下一轮
  -> retry -> 提示文本写回 history  -> 下一轮（只消耗请求次数，不消耗工具步数）
  -> final -> 写 task_state.json、trace.jsonl、report.json，返回答案
```

工件目录 `<cwd>/.mini-pico/runs/<run_id>/` 下固定三个文件：`task_state.json` 是进展快照，`trace.jsonl` 是逐行追加的事件流（`run_started`、`prompt_built`、`model_requested`、`model_parsed`、`tool_executed`、`run_finished`），`report.json` 是收尾摘要。预算耗尽时循环不抛异常，而是返回一句兜底文本并把状态记为 `stopped`，`stop_reason` 区分 `step_limit_reached` 与 `retry_limit_reached`。

工具协议是文本标记，不是 provider 的原生 function calling：

```text
<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":40}}</tool>
<final>你的最终答案</final>
```

## 运行

在这个目录里执行：

```powershell
uv sync
uv run mini-pico "read README"
uv run pytest -q
```

不带位置参数就进入 REPL（空行忽略，`/exit` 或 `/quit` 退出，Ctrl-C 与 EOF 也算正常退出）：

```powershell
uv run mini-pico
```

源码树里 `python -m mini_pico` 与 `mini-pico` 命令调用同一个入口。参数面：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `prompt`（位置参数） | 空 | 留空即进入 REPL |
| `--cwd` | `.` | 被操作的工作区根目录，工件写在它的 `.mini-pico/runs/` 下 |
| `--approval` | `auto` | `never` 时所有高风险工具在执行前被拒绝，读取与搜索仍可用 |
| `--max-steps` | `4` | 工具调用步数上限 |
| `--max-new-tokens` | `512` | 单步请求模型的输出上限 |

想看控制循环本身，改 `FakeModelClient` 的脚本最直接：

```python
from mini_pico import FakeModelClient, Pico, RunStore, Workspace

agent = Pico(
    model_client=FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":2}}</tool>',
            "<final>Done.</final>",
        ]
    ),
    workspace=Workspace.build("."),
    run_store=RunStore(".mini-pico/runs"),
)
print(agent.ask("read README"))
```

## 建议的阅读顺序

1. `mini_pico/workspace.py`：唯一的边界——路径不能出工作区，长文本要带截断事实。
2. `mini_pico/state.py`：运行过程用哪些字段描述自己，落成哪三份文件。
3. `mini_pico/tools.py` 与 `mini_pico/tool_executor.py`：模型能做什么，以及护栏怎么把失败变成可回灌的文本。
4. `mini_pico/providers.py`：控制循环对「模型」的唯一要求。
5. `mini_pico/context_manager.py`：每轮 Prompt 是怎么拼出来的。
6. `mini_pico/runtime.py`：门面与文本协议解析。
7. `mini_pico/agent_loop.py`：把上面这些接起来，并在两种情况下停下。
8. `mini_pico/cli.py`：参数到运行对象的翻译。
9. `tests/`：`test_contract.py` 锁住公开形状，另外两个锁住循环与工具行为。

## 质量门禁

`pyproject.toml` 与主项目保持同一套工程约定：hatchling 构建、`requires-python = ">=3.12,<3.13"`、相同的 ruff 规则集（`E, F, I, N, W` 加若干安全规则、`line-length = 120`、`target-version = "py312"`）、一致的 dev 依赖版本与 pytest 配置（`pythonpath`、marker 白名单与默认排除）。这个目录里的检查是：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

marker 只声明这个例子真正可能需要的两个：`real_llm`（要替换成真实模型端点时）与 `external_runtime`（依赖 Python 环境之外的可执行文件时，例如 `search` 走本机 ripgrep 那条分支）。主项目的 `e2e`、`performance` 等标记在这里没有对应用例，因此不照搬。

## 边界：不要用于生产

这个例子不能安全地承担真实工作，缺口是设计的一部分而不是待办事项：

- 没有会话持久化与恢复，历史只活在实例的一个列表里，进程退出即丢失。
- 没有上下文预算与分段收缩，快照与历史用固定条数/字符数上限顶上。
- 没有记忆、checkpoint、子 Agent 委派，也没有多 Provider。
- 审批只有 `auto` 与 `never` 两档，没有交互式确认；高风险工具在 `auto` 下直接落盘。
- 工件不做脱敏，写入也不是原子替换，`report.json` 里可能有你没打算留下的内容。
- 没有 Shell 工具，因此也没有主项目那套环境变量白名单。
- 测试只覆盖控制流与工具行为，不是生产级测试矩阵。

要用在真实仓库里，请安装主项目 `pico`；把它和这个目录并排读，是后者存在的唯一理由。
