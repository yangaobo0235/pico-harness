"""Agent 控制循环：感知、决策、行动、记录。

`AgentLoop` 推进一次 `ask()`：先记录用户请求并建立 `TaskState`，然后每轮重新组装 Prompt、请求
模型、把输出解析成工具调用 / 最终答案 / 需要重问的格式错误，执行工具并把结果回灌进历史与工件，
直到出现最终答案、工具步数耗尽或尝试次数耗尽。两个上限分开统计：`max_steps` 数工具调用，
`max_attempts`（比 `max_steps` 多 3）数所有模型请求，因此“模型反复把 JSON 写错”会很快撞上重试上限，
但不会吃掉工具预算。

这里不拼装 Prompt（`mini_pico.context_manager`）、不解析协议标记（`Pico.parse`）、不校验也不执行
工具（`mini_pico.tool_executor`），更不判断路径能否出工作区（`mini_pico.workspace`）。循环本身不
持有状态——所有事实都写在 `Pico` 与 `TaskState` 上，所以一次运行的中间过程既能被 Trace 观察，
也能在进程被中断后从 ``task_state.json`` 读回。停下时给出的兜底文本属于输出协议，不改写。
"""

import time
from typing import TYPE_CHECKING

from mini_pico.state import TaskState, now
from mini_pico.workspace import clip

if TYPE_CHECKING:
    from mini_pico.runtime import Pico


class AgentLoop:
    """一次请求的迭代推进器，构造时只接运行时门面，自己不保存运行事实。"""

    def __init__(self, agent: "Pico") -> None:
        self.agent = agent

    def run(self, user_message: str) -> str:
        """跑完整个循环并返回最终答案文本。

        成功路径在解析出 `final` 时返回；两个上限都没触发时不会无限循环，因为每轮都必然让
        `attempts` 或 `tool_steps` 增长。撞上上限时返回一句可读的兜底文本并把状态记为
        `stopped`，而不是抛异常——教学示例要让读者看见“停在哪里、为什么停”，而不是一次 Python 堆栈。
        """
        agent = self.agent
        started_at = time.monotonic()
        agent.record({"role": "user", "content": user_message, "created_at": now()})
        task_state = TaskState.create(user_message)
        agent.current_task_state = task_state
        agent.run_store.start_run(task_state)
        agent.emit_trace(task_state, "run_started", {"user_request": clip(user_message, 300)})

        max_attempts = agent.max_steps + 3
        while task_state.tool_steps < agent.max_steps and task_state.attempts < max_attempts:
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            prompt, prompt_metadata = agent.context_manager.build(user_message)
            agent.emit_trace(task_state, "prompt_built", {"prompt_metadata": prompt_metadata})
            agent.emit_trace(
                task_state, "model_requested", {"attempts": task_state.attempts, "tool_steps": task_state.tool_steps}
            )
            raw = agent.model_client.complete(prompt, agent.max_new_tokens)
            kind, payload = agent.parse(raw)
            agent.emit_trace(task_state, "model_parsed", {"kind": kind})

            if kind == "tool":
                name = payload.get("name", "")
                args = payload.get("args", {})
                task_state.record_tool(name)
                result = agent.execute_tool(name, args)
                agent.record(
                    {"role": "tool", "name": name, "args": args, "content": result.content, "created_at": now()}
                )
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "tool_executed",
                    {"name": name, "args": args, "result": clip(result.content, 500), **result.metadata},
                )
                continue

            if kind == "retry":
                agent.record({"role": "assistant", "content": payload, "created_at": now()})
                continue

            final = str(payload or raw).strip()
            task_state.finish_success(final)
            agent.record({"role": "assistant", "content": final, "created_at": now()})
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                "run_finished",
                {
                    "status": task_state.status,
                    "stop_reason": task_state.stop_reason,
                    "final_answer": final,
                    "run_duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            agent.run_store.write_report(task_state, agent.build_report(task_state))
            return final

        if task_state.attempts >= max_attempts:
            final = "Stopped after too many malformed model responses."
            task_state.stop_retry_limit(final)
        else:
            final = "Stopped after reaching the step limit."
            task_state.stop_step_limit(final)
        agent.record({"role": "assistant", "content": final, "created_at": now()})
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            "run_finished",
            {"status": task_state.status, "stop_reason": task_state.stop_reason, "final_answer": final},
        )
        agent.run_store.write_report(task_state, agent.build_report(task_state))
        return final
