"""Agent 运行时门面：把装配好的能力粘合成一次可请求的 `ask()`。

`Pico` 是教学示例的中心对象：它持有模型客户端、工作区与运行工件存储，维护会话历史这个列表，
并把循环需要的动作摆在同一处——`record` 写历史、`execute_tool` 走执行护栏、`run_tool` 只要纯文本、
`emit_trace` 落一条事件、`parse` 判定模型输出的协议归属、`build_report` 汇总收尾报告。
构造即完成装配，第一次 `ask()` 不需要惰性创建任何东西。

它不推进迭代（`mini_pico.agent_loop`）、不拼装 Prompt（`mini_pico.context_manager`）、不做工具
护栏与参数规则（`mini_pico.tool_executor` 与 `mini_pico.tools`）、也不决定状态字段含义
（`mini_pico.state`）。`parse` 留在这个模块是有意的取舍：教学版想让“文本协议如何落到控制流”停在
一个读者不会走丢的位置，主项目则把它单独下沉成 `runtime.agent.prompts`，并同时支持 JSON 体与
XML 风格两种工具写法。这里也没有会话持久化、记忆、checkpoint 与子 Agent——历史只活在这个实例的
列表里，一次运行一份。
"""

import json
import re
from typing import Any

from mini_pico.agent_loop import AgentLoop
from mini_pico.context_manager import ContextManager
from mini_pico.state import RunStore, TaskState
from mini_pico.tool_executor import ToolExecutionResult, ToolExecutor
from mini_pico.workspace import Workspace


class Pico:
    """一次运行的 Agent 运行时，实例化即完成装配。

    构造参数就是这次运行的全部边界：模型客户端、工作区、工件存储、审批策略、步数预算与单步输出
    预算。``max_steps`` 限制工具调用次数，``max_new_tokens`` 传给模型的 `complete`，
    两者互相独立，因此“反复输出格式错误”消耗的是尝试次数而不是工具预算。

    `history` 与 `current_task_state` 是运行过程中可变的事实，供上下文渲染与报告读取；
    子 Agent 是另一个实例，而不是同一实例的嵌套调用栈。
    """

    def __init__(
        self,
        model_client: Any,
        workspace: Workspace,
        run_store: RunStore,
        approval_policy: str = "auto",
        max_steps: int = 4,
        max_new_tokens: int = 512,
    ) -> None:
        self.model_client = model_client
        self.workspace = workspace
        self.run_store = run_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.history: list[dict[str, Any]] = []
        self.tool_executor = ToolExecutor(workspace, approval_policy=approval_policy)
        self.context_manager = ContextManager(self)
        self.current_task_state: TaskState | None = None

    def ask(self, user_message: str) -> str:
        """跑完一次请求并返回最终答案文本。

        门面只负责把循环接起来，因此测试可以直接调用 `AgentLoop(self).run(...)` 做同样的事。
        循环内部已经处理了步数与重试上限，本方法不抛“预算耗尽”这类业务异常。
        """
        return AgentLoop(self).run(user_message)

    def record(self, item: dict[str, Any]) -> None:
        """把一条历史追加进会话列表。

        这里做一份浅拷贝，因此调用方后续复用同一个字典不会反过来改写已经落地的历史——
        历史是“已经发生过的事实”，不是活动引用。
        """
        self.history.append(dict(item))

    def execute_tool(self, name: str, args: dict[str, Any] | None) -> ToolExecutionResult:
        """经执行护栏调用一次工具，返回带元数据的结果对象。

        ``args`` 为 ``None`` 时按空字典处理，让“只有工具名、没有参数”落到各工具自己的必填校验，
        而不是在门面这里抛类型错误。
        """
        return self.tool_executor.execute(name, args or {})

    def run_tool(self, name: str, args: dict[str, Any] | None) -> str:
        """只要工具输出的纯文本，把结果对象折成字符串给直接调用方使用。"""
        return self.execute_tool(name, args).content

    def emit_trace(self, task_state: TaskState, event_type: str, payload: dict[str, Any] | None) -> None:
        """写一条运行事件到 ``trace.jsonl``。

        每条事件都带上 `run_id`，因此多个运行同时存在时也能按行归属；``payload`` 为 ``None`` 时
        按空载荷处理，事件类型本身仍然是完整的一条记录。
        """
        event = {"event": event_type, "run_id": task_state.run_id, **dict(payload or {})}
        self.run_store.append_trace(task_state, event)

    @staticmethod
    def parse(raw: object) -> tuple[str, Any]:
        """把一次模型输出解析成 ``(kind, payload)``。

        判定顺序是工具优先：文本里出现 ``<tool>`` 就按工具调用处理，因为模型常在调用前后附带解释
        文本，那部分不该被当成答案。JSON 解析失败、``<final>`` 内容为空、两者都没有，三种情况都返回
        ``("retry", 提示文本)``，把格式问题交回给模型自己修正，而不是由平台猜测意图；
        正常时返回 ``("tool", 参数字典)`` 或 ``("final", 答案字符串)``。
        """
        text = str(raw or "")
        tool_match = re.search(r"<tool>(.*?)</tool>", text, re.DOTALL)
        if tool_match:
            try:
                payload = json.loads(tool_match.group(1).strip())
            except json.JSONDecodeError as exc:
                return "retry", f"model returned malformed tool JSON: {exc}"
            return "tool", payload
        final_match = re.search(r"<final>(.*?)</final>", text, re.DOTALL)
        if final_match:
            final = final_match.group(1).strip()
            if final:
                return "final", final
            return "retry", "model returned an empty final answer"
        return "retry", "model returned neither <tool> nor <final>"

    def build_report(self, task_state: TaskState) -> dict[str, Any]:
        """汇总一次运行的收尾报告：状态快照、历史条数与工作区根路径。"""
        return {
            "task_state": task_state.to_dict(),
            "history_items": len(self.history),
            "workspace_root": str(self.workspace.root),
        }
