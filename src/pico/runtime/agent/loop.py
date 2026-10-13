"""Agent 控制循环：感知、决策、行动、记录。

`AgentLoop` 推进一次 `ask()`：每一轮重新组装 Prompt、请求模型、把输出解析成工具调用或最终
答案、执行工具并回写历史与工件，直到出现最终答案、预算耗尽或模型请求失败。循环本身不持有
状态——所有事实都写在 `Pico` 与 `TaskState` 上，因此一次运行的中间过程既能被 Trace 观察，也能
在进程被中断后从会话文件里读回。

这里不做工具校验、不判断审批、也不拼装 Prompt；那些分别属于执行层、安全层和上下文层。循环
只负责“按顺序把这些能力接起来，并在合适的时候停下来”。
"""

import time
from typing import Any

from pico.contracts.events import (
    CHECKPOINT_CREATED,
    MODEL_FAILED,
    MODEL_PARSED,
    MODEL_REQUESTED,
    PROMPT_BUILT,
    RUN_FINISHED,
    RUN_STARTED,
    RUNTIME_IDENTITY_MISMATCH,
    TOOL_EXECUTED,
)
from pico.contracts.messages import assistant_message, tool_message, user_message
from pico.contracts.turns import TaskState, new_run_id, new_task_id
from pico.runtime.agent import prompts
from pico.runtime.agent.checkpoints import (
    CHECKPOINT_NONE_STATUS,
    CHECKPOINT_PARTIAL_STALE_STATUS,
    CHECKPOINT_WORKSPACE_MISMATCH_STATUS,
)
from pico.shared.clock import now
from pico.shared.text import clip

#: 达到工具预算后追加到 Prompt 尾部的收尾指令：只允许给出结论，不允许再发起动作。
FINALIZATION_NOTICE = (
    "\n\nRuntime notice: the tool budget is exhausted. Do not call another tool. "
    "Use the evidence already present in the tool history and return exactly one "
    "non-empty <final>...</final> answer."
)

#: 两种“没能得到答案”的收尾文本，直接作为回答交给用户。
RETRY_LIMIT_ANSWER = "Stopped after too many malformed model responses without a valid tool call or final answer."
STEP_LIMIT_ANSWER = "Stopped after reaching the step limit without a final answer."

PURPOSE_ACTION = "action"
PURPOSE_FINALIZATION = "finalization"


class AgentLoop:
    """按一次请求推进控制循环。

    循环实例是一次性的：`run()` 返回后它就不再持有意义，状态已经全部落在 `Pico` 与运行工件里。
    把循环从门面拆出来，是为了让“迭代策略”和“装配现场”可以各自演进，也让测试能够单独驱动
    一轮循环而不必重建整个运行时。
    """

    def __init__(self, agent: Any):
        self.agent = agent

    def run(self, user_message_text: str) -> str:
        """推进一次请求并返回最终答案文本。

        先把任务摘要与用户请求写进会话，再建立 `TaskState` 和运行目录；随后进入
        「组装 Prompt → 请求模型 → 解析 → 执行工具或收尾」的循环。工具预算用完时不会直接失败，
        而是再请求一次模型、明确要求只给结论，这一步称为 finalization。

        返回的文本要么来自模型的 `<final>` 答案，要么是预算耗尽时的说明文本；模型请求异常会
        在记录工件之后向上抛出，由入口决定怎么呈现。
        """
        agent = self.agent
        run_started_at = time.monotonic()
        agent.memory.set_task_summary(user_message_text)
        agent.record(user_message(user_message_text, now()))

        task_state = TaskState.create(run_id=new_run_id(), task_id=new_task_id(), user_request=user_message_text)
        task_state.resume_status = agent.resume_state.get("status", CHECKPOINT_NONE_STATUS)
        agent.current_task_state = task_state
        agent.current_run_dir = agent.run_store.start_run(task_state)
        agent.emit_trace(
            task_state,
            RUN_STARTED,
            {
                "task_id": task_state.task_id,
                "user_request": clip(user_message_text, 300),
            },
        )

        tool_steps = 0
        attempts = 0
        max_attempts = agent.max_attempts()

        while tool_steps < agent.max_steps and attempts < max_attempts:
            attempts += 1
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            prompt_started_at = time.monotonic()
            prompt, prompt_metadata = agent._build_prompt_and_metadata(user_message_text)
            agent.emit_trace(
                task_state,
                PROMPT_BUILT,
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                },
            )
            self._record_freshness(task_state, user_message_text, prompt_metadata)

            raw, kind, payload = self._request_model(
                task_state,
                user_message_text,
                prompt,
                prompt_metadata,
                run_started_at,
                purpose=PURPOSE_ACTION,
            )

            if kind == prompts.KIND_TOOL:
                tool_steps += 1
                self._run_tool_step(task_state, user_message_text, payload)
                continue

            if kind == prompts.KIND_RETRY:
                agent.record(assistant_message(payload, now()))
                agent.run_store.write_task_state(task_state)
                continue

            final = (payload or raw).strip()
            return self._finish_success(task_state, user_message_text, final, run_started_at)

        return self._stop_without_answer(
            task_state, user_message_text, run_started_at, tool_steps=tool_steps, attempts=attempts
        )

    def _record_freshness(self, task_state: TaskState, user_message_text: str, prompt_metadata: dict[str, Any]) -> None:
        """把 Prompt 组装阶段发现的失配记成 checkpoint 或身份不匹配事件。

        新鲜度过期与 runtime 身份变化都不该终止本次请求，但必须留下记录：下一次恢复时
        “为什么上一轮的现场不算数”只能从这些事件里回答。上下文收缩同样会记一次 checkpoint，
        因为它改变了模型这一轮实际看到的内容。
        """
        agent = self.agent
        resume_status = prompt_metadata.get("resume_status")
        if resume_status == CHECKPOINT_PARTIAL_STALE_STATUS:
            checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="freshness_mismatch")
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                CHECKPOINT_CREATED,
                {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "freshness_mismatch"},
            )
        elif resume_status == CHECKPOINT_WORKSPACE_MISMATCH_STATUS:
            agent.emit_trace(
                task_state,
                RUNTIME_IDENTITY_MISMATCH,
                {"fields": list(prompt_metadata.get("runtime_identity_mismatch_fields", []))},
            )
            checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="workspace_mismatch")
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                CHECKPOINT_CREATED,
                {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "workspace_mismatch"},
            )
        if prompt_metadata.get("budget_reductions"):
            checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="context_reduction")
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                CHECKPOINT_CREATED,
                {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "context_reduction"},
            )

    def _request_model(
        self,
        task_state: TaskState,
        user_message_text: str,
        prompt: str,
        prompt_metadata: dict[str, Any],
        run_started_at: float,
        *,
        purpose: str,
    ) -> tuple[str, str, Any]:
        """请求一次模型输出，记录请求与解析两个事件，并返回 ``(raw, kind, payload)``。

        ``purpose`` 区分普通动作与收尾请求，它进入 Trace，使“这次请求是为了继续干活还是为了
        给个结论”在复盘时可以分辨。缓存键只在模型客户端声明支持 prompt 缓存时携带。

        模型抛错时先把完成元数据、状态、checkpoint、失败事件和报告全部落盘，再向上抛出原异常：
        失败的运行也要留下完整现场。
        """
        agent = self.agent
        agent.emit_trace(
            task_state,
            MODEL_REQUESTED,
            {
                "attempts": task_state.attempts,
                "tool_steps": task_state.tool_steps,
                "prompt_cache_key": prompt_metadata.get("prompt_cache_key"),
                "purpose": purpose,
            },
        )
        prompt_cache_key = None
        prompt_cache_retention = None
        if getattr(agent.model_client, "supports_prompt_cache", False):
            prompt_cache_key = prompt_metadata.get("prompt_cache_key")
            prompt_cache_retention = "in_memory"
        model_started_at = time.monotonic()
        try:
            raw = agent.model_client.complete(
                prompt,
                agent.max_new_tokens,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
            )
        except Exception as exc:
            completion_metadata = dict(getattr(agent.model_client, "last_completion_metadata", {}) or {})
            if completion_metadata:
                prompt_metadata.update(completion_metadata)
            agent.last_completion_metadata = completion_metadata
            agent.last_prompt_metadata = prompt_metadata
            self._persist_model_failure(task_state, user_message_text, exc, run_started_at, prompt_metadata)
            raise
        completion_metadata = dict(getattr(agent.model_client, "last_completion_metadata", {}) or {})
        if completion_metadata:
            prompt_metadata.update(completion_metadata)
        agent.last_completion_metadata = completion_metadata
        agent.last_prompt_metadata = prompt_metadata
        kind, payload = prompts.parse(raw)
        agent.emit_trace(
            task_state,
            MODEL_PARSED,
            {
                "kind": kind,
                "completion_metadata": completion_metadata,
                "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                "purpose": purpose,
            },
        )
        return raw, kind, payload

    def _run_tool_step(self, task_state: TaskState, user_message_text: str, payload: dict[str, Any]) -> None:
        """执行模型提出的一次工具调用，并把结果写回历史与 Trace。

        工具结果以文本形式进历史（完整内容不裁剪，裁剪发生在执行层），执行前后的快照差异通过
        元数据一起记录；随后总是补一条 checkpoint，因为“世界可能刚刚被改过”正是下一次恢复
        最需要知道的事实。
        """
        agent = self.agent
        name = payload.get("name", "")
        args = payload.get("args", {})
        task_state.record_tool(name)
        tool_started_at = time.monotonic()
        result = agent.execute_tool(name, args)
        agent.record(tool_message(name, args, result.content, now()))
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            TOOL_EXECUTED,
            {
                "name": name,
                "args": args,
                "result": clip(result.content, 500),
                "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                **dict(result.metadata or {}),
            },
        )
        checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="tool_executed")
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            CHECKPOINT_CREATED,
            {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "tool_executed"},
        )

    def _finish_success(self, task_state: TaskState, user_message_text: str, final: str, run_started_at: float) -> str:
        """记录最终答案、晋升长期记忆、写 checkpoint 与报告后结束。

        晋升发生在写报告之前，这样报告里的 ``durable_promotions`` 才是本轮的真实结果；答案
        先进历史再改状态，避免中断时出现“状态已完成但历史没有答案”的错配。
        """
        agent = self.agent
        agent.record(assistant_message(final, now()))
        task_state.finish_success(final)
        agent.promote_durable_memory(user_message_text, final)
        checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="run_finished")
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            CHECKPOINT_CREATED,
            {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "run_finished"},
        )
        agent.emit_trace(
            task_state,
            RUN_FINISHED,
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
        return final

    def _persist_model_failure(
        self,
        task_state: TaskState,
        user_message_text: str,
        exc: Exception,
        run_started_at: float,
        prompt_metadata: dict[str, Any],
    ) -> None:
        """把一次模型请求失败写成终态与报告。

        异常文本先脱敏再落盘；状态记为失败，仍然补一条 checkpoint，让下一次恢复知道任务
        停在哪里。这里不吞掉异常，调用方需要看到原始错误类型。
        """
        agent = self.agent
        error_text = agent.redact_text(str(exc))
        final = f"Model request failed: {error_text}"
        task_state.stop_model_error(final)
        agent.run_store.write_task_state(task_state)
        checkpoint = agent.create_checkpoint(task_state, user_message_text, trigger="model_error")
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            MODEL_FAILED,
            {
                "error": error_text,
                "completion_metadata": dict(agent.last_completion_metadata),
            },
        )
        agent.emit_trace(
            task_state,
            RUN_FINISHED,
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.last_prompt_metadata = dict(prompt_metadata)
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))

    def _stop_without_answer(
        self, task_state: TaskState, user_message_text: str, run_started_at: float, *, tool_steps: int, attempts: int
    ) -> str:
        """预算耗尽时收尾：先试一次 finalization 请求，再决定以哪种停止原因结束。

        工具预算用完而模型还没给答案时，再给它一次“只许总结”的机会，这一步消耗一次 attempt
        但不消耗工具预算。仍然拿不到答案就返回说明文本，并把停止原因区分成步数预算与重试上限
        ——两者的复盘方向完全不同。
        """
        agent = self.agent
        if tool_steps >= agent.max_steps:
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            prompt_started_at = time.monotonic()
            prompt, prompt_metadata = agent._build_prompt_and_metadata(user_message_text)
            prompt += FINALIZATION_NOTICE
            prompt_metadata["finalization"] = True
            agent.emit_trace(
                task_state,
                PROMPT_BUILT,
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                    "purpose": PURPOSE_FINALIZATION,
                },
            )
            raw, kind, payload = self._request_model(
                task_state,
                user_message_text,
                prompt,
                prompt_metadata,
                run_started_at,
                purpose=PURPOSE_FINALIZATION,
            )
            if kind == prompts.KIND_FINAL:
                final = (payload or raw).strip()
                return self._finish_success(task_state, user_message_text, final, run_started_at)

        if attempts >= agent.max_attempts() and tool_steps < agent.max_steps:
            final = RETRY_LIMIT_ANSWER
            task_state.stop_retry_limit(final)
        else:
            final = STEP_LIMIT_ANSWER
            task_state.stop_step_limit(final)
        agent.record(assistant_message(final, now()))
        agent.promote_durable_memory(user_message_text, final)
        agent.run_store.write_task_state(task_state)
        checkpoint = agent.create_checkpoint(
            task_state, user_message_text, trigger=task_state.stop_reason or "run_stopped"
        )
        agent.emit_trace(
            task_state,
            CHECKPOINT_CREATED,
            {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": task_state.stop_reason or "run_stopped"},
        )
        agent.emit_trace(
            task_state,
            RUN_FINISHED,
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
        return final
