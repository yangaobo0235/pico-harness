"""Agent execution with explicit ownership of execution state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from pico.capabilities.tools.invocations import ToolExecution, ToolExecutionContext, ToolInvocation
from pico.contracts.turns import Origin
from pico.observability.usage.pricing import resolve_context_window
from pico.runtime.agent.recovery import POST_TOOL_NUDGE, RecoveryAction, classify_empty_response

if TYPE_CHECKING:
    from pico.runtime.scheduling.runner import Drain, TurnOutcome
from pico.runtime.agent.failures import _is_hard_tool_failure, _is_tool_failure, _loop_break_nudge
from pico.runtime.agent.models import TurnOutcome
from pico.runtime.agent.prompts import _MAX_ITER_STATIC_FALLBACK, _MAX_ITER_SYNTHESIS_PROMPT


async def synthesize_final_answer(
    self,
    messages: list[dict],
    model: str | None,
    fallback_models: list[str] | None,
    session_key: str = "",
    on_token_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """迭代预算耗尽后，用一次禁用 Tool 的 LLM 调用生成本轮收尾回复。

    与直接返回固定道歉不同，方法把 `_MAX_ITER_SYNTHESIS_PROMPT` 追加为 User 消息，请模型
    只根据已经收集的材料总结完成项、部分结果和未完成项。调用明确传入 ``tools=None``，
    因而模型不能在预算悬崖边再发起 Tool call 或 ``ask_user``。响应出错、为空或自身抛出
    异常时返回 `_MAX_ITER_STATIC_FALLBACK`，保证 Turn 不会静默结束。

    调用方若连接了 streaming callbacks，合成回复也必须走 `_llm_call_stream` 并继续流出；
    否则 `run_turn` 在已有增量后会抑制结尾 ``Text``，非流式生成的收尾就会被出口丢弃。
    未连接回调时使用 Provider 的 `chat_with_retry`。成功响应仍经 CallEfficiency 记录和
    `_strip_think` 清理，返回值是最终可交付文本，不包含新增 Tool 结果。
    """
    synth_messages = messages + [{"role": "user", "content": _MAX_ITER_SYNTHESIS_PROMPT}]
    try:
        if on_token_delta is not None or on_reasoning_delta is not None:
            response = await self._llm_call_stream(
                messages=synth_messages,
                tools=None,
                model=model,
                on_token_delta=on_token_delta,
                on_reasoning_delta=on_reasoning_delta,
            )
        else:
            response = await self.provider.chat_with_retry(
                messages=synth_messages,
                tools=None,
                model=model,
                fallback_models=fallback_models,
            )
        if response.call_record is None:
            response.call_record = self.call_efficiency.record(
                response,
                requested_model=model or self.model,
                session_key=session_key,
                cache_policy=response.cache_policy,
            )
        text = self._strip_think(response.content)
        if response.finish_reason != "error" and text:
            return text
        logger.warning(
            "Max-iter synthesis returned no usable content (finish_reason={})",
            response.finish_reason,
        )
    except Exception as exc:
        logger.warning("Max-iter synthesis call failed: {}", exc)
    fallback = _MAX_ITER_STATIC_FALLBACK.format(n=self.max_iterations)
    # 流式成功路径已通过 ``on_token_delta`` 交付文本，此回退路径则没有。因此也要将它推入流；
    # 否则一旦已有内容流出，run_turn 边界会抑制结尾 ``Text``，导致流式出口丢失回退文本。
    if on_token_delta is not None:
        await on_token_delta(fallback)
    return fallback


async def execute_model_loop(
    self,
    initial_messages: list[dict],
    on_progress: Callable[..., Awaitable[None]] | None = None,
    session_key: str | None = None,
    model: str | None = None,
    fallback_models: list[str] | None = None,
    injected_skill_ids: list[str] | None = None,
    on_token_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_event: Callable[[str, dict], Awaitable[None]] | None = None,
    usage_sink: dict[str, Any] | None = None,
    drain: Drain | None = None,
    origin: Origin | None = None,
) -> tuple[str | None, list[str], list[dict], TurnOutcome]:
    """执行一次有预算的模型—Tool 迭代，并返回回复、证据与明确终态。

    `initial_messages` 是已经由 Context Engine 组装的模型窗口。每轮先读取 Tool
    definitions 和策略变换后的调用参数，再请求 LLM；若响应含 Tool call，就执行并把结果
    追加回消息，进入下一轮；若得到可用正文则结束。Provider error、空响应恢复耗尽或最大
    迭代数到达都会走各自的显式终止路径，不会被伪装成普通完成。

    连接 ``drain`` 时，每次迭代顶部都会拉取 BusyPolicy.INJECT 在 Turn 中途注入的用户
    消息，并在下一次 LLM 调用前合并为 User turn。``session_key`` 把 Usage、
    CallEfficiency 与 Checkpoint evidence 归属到 Host 对话；省略时使用空字符串，而不是
    猜测另一个会话。流式文本、推理和 Tool 事件分别经对应回调交付。

    返回四元组依次是最终文本或 ``None``、本轮使用的 Tool 名列表、清理过合成恢复脚手架
    的消息历史，以及本模块的 `TurnOutcome`。其中 ``status`` 区分 ``completed``、
    ``interrupted``、``error``；达到上限时还会尝试一次 tools-disabled 收尾，但有回复不
    会把“尚未完成”的 interrupted 事实改写成 completed。
    """
    messages = initial_messages
    iteration = 0
    final_content = None
    tools_used: list[str] = []
    session_key = session_key or ""
    effective_model = model or self.model

    # 记录 Turn 是正常退出还是因迭代上限中断。下游只读取 ``status``，
    # 用于标记影子 Git 提交并写入 ``TurnOutcome``。
    status = "completed"
    error_category: str | None = None

    # 上下文溢出恢复：限制紧急收缩次数，避免省略后仍溢出的 Turn 永久循环。
    compress_retries = 0
    # 工具失败循环打断：跨迭代跟踪同一工具的连续硬失败；
    # 每个新连续段提示一次，并按 Turn 限制总数。
    loop_fail_tool: str | None = None
    loop_fail_streak = 0
    loop_nudges = 0
    # 空响应恢复状态属于当前 Turn。AgentLoop 是跨会话共享的长生命周期单例，
    # 实例级计数器会跨 Turn 泄漏；此处重置可为每个 Turn 提供干净预算。
    prev_had_tool_calls = False
    post_tool_nudges = 0
    prefill_retries = 0
    empty_retries = 0

    while iteration < self.max_iterations:
        iteration += 1
        logger.info(
            "Iteration {}/{} model={}",
            iteration,
            self.max_iterations,
            effective_model,
        )

        # 在本次迭代的 LLM 调用前合并所有通过 BusyPolicy.INJECT 注入的用户消息。
        # 携带媒体的注入会在文本中保留文件路径，避免内容静默丢失。
        if drain is not None:
            for inj in drain():
                inj_text = inj.text or ""
                inj_paths = [m.path for m in inj.media]
                if inj_paths:
                    prefix = inj_text + "\n" if inj_text else ""
                    inj_text = f"{prefix}[injected message; attached files: {', '.join(inj_paths)}]"
                if inj_text:
                    messages.append({"role": "user", "content": inj_text})
                    logger.info("inject: merged a mid-turn user message")

        tool_defs = self.tools.get_definitions()

        # 先运行历史策略，使工具过滤先于缓存规划。
        call_messages, call_tools, call_model = await self.strategies.before_llm_call(
            messages,
            tool_defs,
            effective_model,
        )
        if on_token_delta is not None or on_reasoning_delta is not None:
            response = await self._llm_call_stream(
                messages=call_messages,
                tools=call_tools,
                model=call_model,
                on_token_delta=on_token_delta,
                on_reasoning_delta=on_reasoning_delta,
            )
        else:
            response = await self.provider.chat_with_retry(
                messages=call_messages,
                tools=call_tools,
                model=call_model,
                fallback_models=fallback_models,
            )
        call_record = response.call_record
        if call_record is None:
            call_record = self.call_efficiency.record(
                response,
                requested_model=call_model,
                session_key=session_key,
                cache_policy=response.cache_policy,
            )
            response.call_record = call_record
        usage_snapshot = call_record.to_legacy_snapshot()
        await self.strategies.after_llm_call(
            {
                "content": response.content,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
            },
            usage_snapshot,
        )
        # tui-chat L2-A 线路：流式调用方（turn.* 处理器）可能需要用最后一次迭代用量
        # 按 CAP-CHAT-1 形状填充 `message.complete.payload.usage`。应使用线上合约 UsageSnapshot
        # 的 prompt_tokens、completion_tokens 和 total_tokens，而非带模型、缓存和成本字段的
        # Agent 内部快照。
        if usage_sink is not None and response.usage:
            prompt_tokens = int(response.usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(response.usage.get("completion_tokens", 0) or 0)
            # LiteLLM 信息滞后时，从模型提供商表获取真实窗口；否则使用配置默认值。
            context_max = (
                resolve_context_window(
                    call_record.accounting_model,
                    allow_litellm_import=False,
                )
                or self.context_window_tokens
            )
            context_used = prompt_tokens + completion_tokens
            usage_sink.clear()
            usage_sink["prompt_tokens"] = prompt_tokens
            usage_sink["completion_tokens"] = completion_tokens
            usage_sink["total_tokens"] = int(response.usage.get("total_tokens", 0) or 0)
            if usage_snapshot.estimated_cost_usd is not None:
                usage_sink["cost_usd"] = usage_snapshot.estimated_cost_usd
            else:
                usage_sink.pop("cost_usd", None)
            usage_sink["context_max"] = context_max
            usage_sink["context_used"] = context_used
            usage_sink["context_percent"] = round(100 * context_used / context_max) if context_max else 0

            # 上下文窗口溢出恢复：结构化分类器标记 should_compress。更小窗口无济于事，
            # 但省略大量累积工具输出有效。就地收缩并重试当前迭代，而不暴露为致命错误；
            # 重试次数受限。
        cls_ = response.error_classification
        if (
            response.finish_reason == "error"
            and cls_ is not None
            and cls_.should_compress
            and compress_retries < self._MAX_COMPRESS_RETRIES
        ):
            shrunk, elided = self._emergency_shrink(messages)
            if elided > 0:
                messages = shrunk
                compress_retries += 1
                iteration -= 1  # 溢出的调用没有执行工作，不计入迭代次数
                logger.warning(
                    "Context overflow; elided {} old tool result(s), retrying ({}/{})",
                    elided,
                    compress_retries,
                    self._MAX_COMPRESS_RETRIES,
                )
                continue

        if response.has_tool_calls:
            if on_progress:
                thought = self._strip_think(response.content)
                if thought:
                    await on_progress(thought)
                await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

            tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
            messages = self.context.add_assistant_message(
                messages,
                response.content,
                tool_call_dicts,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            )

            invocations: list[ToolInvocation] = []
            for tool_call in response.tool_calls:
                tools_used.append(tool_call.name)
                args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                invocations.append(
                    ToolInvocation(
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        context=ToolExecutionContext(
                            call_id=tool_call.id,
                            session_key=session_key,
                            iteration=iteration,
                            origin=origin.value if origin is not None else None,
                        ),
                    )
                )

            async def _tool_started(invocation: ToolInvocation) -> None:
                if on_tool_event is not None:
                    nested = invocation.context.parent_call_id is not None
                    await on_tool_event(
                        "start",
                        {
                            "tool_call_id": (
                                invocation.context.parent_call_id if nested else invocation.context.call_id
                            ),
                            "name": "tool_call" if nested else invocation.name,
                            "arguments": (
                                {"name": invocation.name, "arguments": invocation.arguments}
                                if nested
                                else invocation.arguments
                            ),
                            "target_call_id": invocation.context.call_id if nested else None,
                            "target_name": invocation.name if nested else None,
                            "target_arguments": invocation.arguments if nested else None,
                        },
                    )

            async def _tool_completed(execution: ToolExecution) -> None:
                invocation = execution.invocation
                result = execution.result
                result_str = str(result)
                preview = result_str.replace("\n", " ")[:200]
                logger.info(
                    "Tool result: {} duration={}ms result={}",
                    invocation.name,
                    int(execution.duration_ms),
                    preview,
                )
                if on_tool_event is not None:
                    nested = invocation.context.parent_call_id is not None
                    await on_tool_event(
                        "complete",
                        {
                            "tool_call_id": (
                                invocation.context.parent_call_id if nested else invocation.context.call_id
                            ),
                            "name": "tool_call" if nested else invocation.name,
                            "result_preview": preview,
                            "truncated": len(result_str) > 200,
                            "failed": _is_tool_failure(result),
                            "target_call_id": invocation.context.call_id if nested else None,
                            "target_name": invocation.name if nested else None,
                            "target_arguments": invocation.arguments if nested else None,
                            "duration_ms": execution.duration_ms,
                        },
                    )

            executions = await self.tools.execute_many(
                invocations,
                on_start=_tool_started,
                on_complete=_tool_completed,
            )

            for tool_call, execution in zip(response.tool_calls, executions, strict=True):
                result = execution.result
                messages = self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
                # 跟踪同一工具的连续确定性失败；排除可通过重试清除的短暂错误。
                if _is_hard_tool_failure(result):
                    if tool_call.name == loop_fail_tool:
                        loop_fail_streak += 1
                    else:
                        loop_fail_tool, loop_fail_streak = tool_call.name, 1
                else:
                    loop_fail_tool, loop_fail_streak = None, 0

            # 失败循环打断：同一工具连续确定性失败 `threshold` 次后，
            # 向最后一个工具结果附加改变方法的提示，让模型停止重复无效调用。
            if (
                loop_fail_streak >= self._LOOP_BREAK_THRESHOLD
                and loop_nudges < self._LOOP_BREAK_MAX
                and messages
                and messages[-1].get("role") == "tool"
            ):
                loop_nudges += 1
                messages[-1]["content"] = (
                    str(messages[-1].get("content", "")) + "\n\n" + _loop_break_nudge(loop_fail_tool, loop_fail_streak)
                )
                loop_fail_streak = 0  # 每轮新的连续失败只触发一次
            prev_had_tool_calls = True
        else:
            clean = self._strip_think(response.content)
            # 不将错误响应持久化到会话历史，因为它们可能污染上下文，导致永久 400 循环。
            if response.finish_reason == "error":
                logger.error("LLM returned error: {}", (clean or "")[:200])
                final_content = clean or "Sorry, I encountered an error calling the AI model."
                status = "error"
                classification = response.error_classification
                if classification is None:
                    classifier = getattr(self.provider, "classify_error", None)
                    classification = classifier(content=clean) if classifier is not None else None
                error_category = classification.category if classification is not None else "unknown"
                break

            # 空响应恢复：如果不处理，空的 Assistant Turn 会在此退出，暴露“无回复可给”的无效结果。
            # 放弃前先尝试恢复。合成脚手架用 ``_recovery_synthetic`` 标记，并在持久化和提取前移除，
            # 避免污染未来上下文。
            action = classify_empty_response(
                response,
                clean,
                prev_had_tool_calls=prev_had_tool_calls,
                nudges_done=post_tool_nudges,
                prefill_retries=prefill_retries,
                empty_retries=empty_retries,
                limits=self._recovery_limits,
            )
            if action is RecoveryAction.PREFILL:
                prefill_retries += 1
                logger.warning(
                    "empty-recovery: thinking-only prefill {}/{}",
                    prefill_retries,
                    self._recovery_limits.thinking_prefill_max_retries,
                )
                # 将模型自身未删减的推理回填，使其继续生成正文。消息标记为合成，
                # 在持久化和提取前丢弃；提供商的键白名单会从线上请求中移除推理字段。
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                messages[-1]["_recovery_synthetic"] = True
                prev_had_tool_calls = False
                continue
            if action is RecoveryAction.NUDGE:
                post_tool_nudges += 1
                logger.warning("empty-recovery: post-tool empty nudge")
                # 空 Assistant 消息必须位于工具结果和提示之间，因为多数 API 会对裸的
                # tool → user 序列返回 400。
                messages = self.context.add_assistant_message(messages, "(empty)")
                messages[-1]["_recovery_synthetic"] = True
                messages.append({"role": "user", "content": POST_TOOL_NUDGE, "_recovery_synthetic": True})
                prev_had_tool_calls = False
                continue
            if action is RecoveryAction.RETRY:
                empty_retries += 1
                logger.warning(
                    "empty-recovery: plain empty retry {}/{}",
                    empty_retries,
                    self._recovery_limits.empty_content_max_retries,
                )
                prev_had_tool_calls = False
                continue

            messages = self.context.add_assistant_message(
                messages,
                clean,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            )
            final_content = clean
            break

    if final_content is None and iteration >= self.max_iterations:
        logger.warning("Max iterations ({}) reached; synthesizing final answer", self.max_iterations)
        # 耗尽包含两个彼此独立的事实，并非二选一：
        #   1. 本轮尚未完成——将其标记为 ``interrupted``，让影子 Git 检查点提交带上
        #      对应标签，并让下一轮的恢复提示展示提交 SHA 和已编辑文件以便续作。
        #   2. 用户现在仍应得到有用的回复——因此无论是否存在检查点，都尽力生成收尾
        #      （调用一次禁用工具的模型，总结已完成和待完成事项），而不是返回固定道歉。
        #      如果生成失败，辅助方法内部会回退到静态消息，确保本轮不会静默结束。
        status = "interrupted"
        final_content = await self._synthesize_final_on_exhaustion(
            messages,
            effective_model,
            fallback_models,
            session_key,
            on_token_delta=on_token_delta,
            on_reasoning_delta=on_reasoning_delta,
        )
        # 像普通最终回复一样，把收尾内容持久化到历史中。下游持久化只读取返回的
        # ``messages`` 列表；若不这样做，生成的答案虽会经由流到达用户，却不会进入
        # 对话，下一轮（尤其是中断恢复轮）便看不到本次总结。生成提示本身只保留在
        # 辅助方法内部，因此这里只落下回复。
        if final_content:
            messages = self.context.add_assistant_message(messages, final_content)

    # 持久化和返回前移除临时的空响应恢复脚手架。Pico 会用
    # ``_recovery_synthetic`` 标记合成的推动/预填消息，必须移除以免持久化。
    if any(m.get("_recovery_synthetic") for m in messages):
        messages = [m for m in messages if not m.get("_recovery_synthetic")]

    outcome = TurnOutcome(
        status=status,
        error_category=error_category,
    )
    if self._checkpoint is not None:
        # 每轮快照：一次提交覆盖本轮全部编辑，正常退出和中断退出均如此
        # （与 Claude Code/Cursor 的粒度一致）。这里只尽力而为，commit_turn 从不抛错。
        label = f"turn {session_key or 'anon'} [{status}]"
        cid, changed = await self._checkpoint.commit_turn(label)
        outcome.checkpoint_id = cid
        if status == "interrupted":
            outcome.edited_files = changed

    return final_content, tools_used, messages, outcome
