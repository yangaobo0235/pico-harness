"""Agent turn runner with explicit ownership of execution state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from pico.capabilities.memory.consolidation.store import MemoryStore
from pico.capabilities.tools.builtin.ask_user import AskUserTool
from pico.capabilities.tools.builtin.message import MessageTool
from pico.contracts.messages import Media
from pico.contracts.turns import Origin
from pico.observability.tracing import semconv, trace
from pico.runtime.context.instructions import ContextBuilder
from pico.runtime.sessions.service import Session
from pico.shared.persisted_payload import sanitize_persisted_payload

if TYPE_CHECKING:
    from pico.contracts.turns import TurnRequest
    from pico.runtime.scheduling.runner import Drain, Emit, TurnOutcome
from pico.runtime.agent.models import ProviderTurnError, TurnOutcome
from pico.runtime.agent.prompts import _SKIP_USER_INBOUND_ORIGINS


def set_tool_context(
    self, channel: str, chat_id: str, message_id: str | None = None, session_key: str | None = None
) -> None:
    """把当前消息的路由上下文写入需要感知出口的 Tool。

    ``channel``、``chat_id`` 和可选 ``message_id`` 交给 message Tool，使它能把回复送回
    原会话；spawn Tool 还需要 ``session_key`` 关联父子 Turn，未提供时退化为
    ``{channel}:{chat_id}``；cron Tool 只接收通道与聊天标识。没有 `set_context` 的工具
    会被跳过。方法只更新当前注册表中的 message、spawn、cron 三类，不向所有 Tool
    强加路由协议。
    """
    for name in ("message", "spawn", "cron"):
        if tool := self.tools.get(name):
            if not hasattr(tool, "set_context"):
                continue
            if name == "message":
                tool.set_context(channel, chat_id, message_id)
            elif name == "spawn":
                tool.set_context(channel, chat_id, session_key or f"{channel}:{chat_id}")
            else:
                tool.set_context(channel, chat_id)


@trace.instrument("session.turn", seed=semconv.turn_seed, on_open=semconv.turn_open, extract=semconv.turn)
async def process_message(
    self,
    req: TurnRequest,
    session_key: str | None = None,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    on_token_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_event: Callable[[str, dict], Awaitable[None]] | None = None,
    usage_sink: dict[str, Any] | None = None,
    origin: Origin | None = None,
    drain: Drain | None = None,
    context_metadata_sink: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]] | None:
    """处理一个 `TurnRequest`，完成会话、上下文、迭代和事后流水线并返回回复。

    方法从 ``req.source`` 取得 channel、sender、chat 与 extras，解析当前 Session，运行允许
    的入站 Hook 和个性化前置步骤，再调用 Context Engine 组装消息并进入
    `_run_agent_loop`。循环结束后，它保存本轮消息、执行 Engine/Memory/Backend 的事后
    工作，并根据请求 ``origin`` 维持用户输入与 CRON、SUBAGENT 等系统来源的边界。

    有待交付回复时返回 ``(reply_content, media_paths)``；返回 ``None`` 表示 silent turn，
    例如 message Tool 已直接发送，或 Hook 短路选择了 None。这里的 silent 只说明本方法
    不再返回第二份内容，不代表用户一定没有收到消息。``origin`` 是 Spine
    `TurnRequest` 的来源事实，不能从文本内容反推。Provider 无法完成 Turn 时异常继续
    传播给 `run_turn` 和 Lane，而不是转换成成功字符串。
    """
    from pico.runtime.hooks import AgentHookContext

    channel = req.source.channel
    sender_id = req.source.sender_id
    chat_id = req.source.chat_id
    content = req.text
    metadata = dict(req.source.extras)
    turn_media = list(req.media)
    msg_session_key = req.conversation or f"{channel}:{chat_id}"

    # AgentHook 的 ``before_user_inbound`` 链。
    #
    # 观察型钩子和短路型钩子共用同一条有序链。来源不是用户输入时跳过本阶段。
    skip_user_inbound = origin in _SKIP_USER_INBOUND_ORIGINS
    if len(self.hooks) > 0 and not skip_user_inbound:
        _hook_ctx = AgentHookContext(
            session_key=msg_session_key,
            turn_request=req,
        )
        _decision = await self.hooks.before_user_inbound(_hook_ctx)
        if _decision.short_circuit_result is not None:
            return _decision.short_circuit_result

    preview = content[:80] + "..." if len(content) > 80 else content
    logger.info("Processing message from {}:{}: {}", channel, sender_id, preview)

    key = session_key or msg_session_key
    session = self.sessions.get_or_create(key)

    # 斜杠命令
    cmd = content.strip().lower()
    if cmd == "/new":
        try:
            if not await self.memory_consolidator.archive_unconsolidated(session):
                return (
                    "Memory archival failed, session not cleared. Please try again.",
                    [],
                )
        except Exception:
            logger.exception("/new archival failed for {}", session.key)
            return (
                "Memory archival failed, session not cleared. Please try again.",
                [],
            )

        session.clear()
        self.sessions.save(session)
        self.sessions.invalidate(session.key)
        return ("New session started.", [])
    if cmd == "/help":
        lines = [
            "✦ Pico commands:",
            "/new — Start a new conversation",
            "/stop — Stop the current task",
            "/restart — Restart the bot",
            "/help — Show available commands",
        ]
        return ("\n".join(lines), [])
    if not self.context_engine.owns_compaction:
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

    # ── 个性化流程（全局开关：self.enable_personalization）────────────────
    # 子智能体结果回注时跳过：其内容是系统生成的通知而非用户输入；个性化处理会污染
    # 用户画像，或针对通知触发澄清。此处仅 SUBAGENT 跳过（不是更宽泛的用户输入集合）：
    # Cron 轮次目前仍会进入并保留该流程。
    if self.enable_personalization and origin is not Origin.SUBAGENT:
        from datetime import datetime as _dt

        from pico.runtime.personalization import Personalizer

        _personalizer = Personalizer(MemoryStore(self.state), self.provider, self.model)

        # ── 步骤 2 完成阶段：用户正在回答待处理的澄清问题 ──
        if session.pending_clarification:
            _pending = session.pending_clarification

            # 判断用户是在回答上一个问题，还是发起新请求。新请求通常包含动作动词，
            # 且与原请求无关；重新分类以作判断：若仍需澄清，就按新请求处理。
            _recent = session.get_history(max_messages=4)
            _recheck = await _personalizer.classify(content, history=_recent)
            _is_new_request = _recheck.get("needs_clarification", False)

            if _is_new_request:
                # 用户发起了新请求；丢弃旧的待处理状态并重新分类。
                session.pending_clarification = None
                self.sessions.save(session)
                logger.info("Personalization: new request detected, discarding old pending_clarification")

                _question = await _personalizer.generate_question(
                    content,
                    _recheck.get("domain", ""),
                )
                if _question:
                    _ts = _dt.now().isoformat()
                    session.record({"role": "user", "content": content, "timestamp": _ts})
                    session.record({"role": "assistant", "content": _question, "timestamp": _ts})
                    session.pending_clarification = {
                        "original_message": content,
                        "question": _question,
                        "domain": _recheck.get("domain", ""),
                    }
                    self.sessions.save(session)
                    logger.info(
                        "Personalization: asked clarification for new request, session {}",
                        session.key,
                    )
                    return (_question, [])
                    # 问题生成失败时清除待处理状态，并按正常流程继续。
                session.pending_clarification = None

            else:
                # 用户正在回答上一个问题；提取偏好并恢复原任务。
                session.pending_clarification = None

                # 后台提取偏好并写入 MEMORY.md，不阻塞响应。
                async def _extract():
                    await _personalizer.extract_and_store_preference(
                        original_message=_pending["original_message"],
                        question=_pending["question"],
                        answer=content,
                    )

                self._start_personalization_task(_extract)
                # 正常继续：LLM 通过对话历史理解任务。

        else:
            # ── 步骤 1：分类请求——判断是否需要澄清 ──
            _recent = session.get_history(max_messages=4)
            _classification = await _personalizer.classify(content, history=_recent)

            if _classification.get("needs_clarification"):
                # ── 步骤 2：行动前交互——生成并返回澄清问题 ──
                _question = await _personalizer.generate_question(
                    content,
                    _classification.get("domain", ""),
                )

                if _question:
                    # 将原请求和澄清问题写入历史，保持对话连贯。
                    _ts = _dt.now().isoformat()
                    session.record({"role": "user", "content": content, "timestamp": _ts})
                    session.record({"role": "assistant", "content": _question, "timestamp": _ts})

                    # 保存待处理状态，让下一条消息可以恢复流程。
                    session.pending_clarification = {
                        "original_message": content,
                        "question": _question,
                        "domain": _classification.get("domain", ""),
                    }
                    self.sessions.save(session)

                    logger.info("Personalization: asked clarification for session {}", session.key)
                    return (_question, [])
                    # generate_question 失败：静默跳过并继续
        # ── 个性化流程结束 ────────────────────────────────────────────────

    self._set_tool_context(channel, chat_id, metadata.get("message_id"), session_key=key)
    if message_tool := self.tools.get("message"):
        if isinstance(message_tool, MessageTool):
            message_tool.start_turn()
        # ask_user 使用真实 conversation_id（即通道/门控键）作为键；该标识感知话题
        # （req.conversation），而非仅使用 channel:chat_id。
    if (ask_tool := self.tools.get("ask_user")) and isinstance(ask_tool, AskUserTool):
        ask_tool.set_context(key)

    context_messages = self._context_messages_for_session(session)
    # SkillForge：选择器选出前 K 个。参见上方系统消息分支中的说明——返回空列表时
    # 回退到完整目录。B-3 阶段统一经由 ``_select_skills_for_turn`` 路由，使新的
    # ``default`` 引擎可在此直接结束选择。
    selected_skills = await self._select_skills_for_turn(
        content,
        context_messages,
    )
    context_metadata = context_metadata_sink if context_metadata_sink is not None else {}
    initial_messages = await self._assemble_context_messages(
        session=session,
        session_key=key,
        current_message=content,
        media=turn_media if turn_media else None,
        channel=channel,
        chat_id=chat_id,
        selected_skills=selected_skills or None,
        metadata_sink=context_metadata,
    )
    injected_skill_ids = list(
        context_metadata.get("injected_skill_ids") or self._collect_injected_skill_ids(selected_skills)
    )

    # ── 模型路由（EcoClaw 风格）──────────────────────────────────────────
    routed_model: str | None = None
    fallback_models: list[str] = []
    if self.router is not None:
        routed_model, fallback_models = await self.router.select_model_chain(content)
        if routed_model and routed_model != self.model:
            logger.info("Router: {} → {}", self.model, routed_model)
        if fallback_models:
            logger.info("Router fallback chain: {}", fallback_models)

    turn_start_idx = len(initial_messages) - 1
    final_content, _, all_msgs, outcome = await self._run_agent_loop(
        initial_messages,
        on_progress=on_progress,
        session_key=key,
        model=routed_model,
        fallback_models=fallback_models,
        injected_skill_ids=injected_skill_ids,
        on_token_delta=on_token_delta,
        on_reasoning_delta=on_reasoning_delta,
        on_tool_event=on_tool_event,
        usage_sink=usage_sink,
        drain=drain,
        origin=origin,
    )
    self._stash_recovery(key, outcome)
    if outcome.status == "error":
        raise ProviderTurnError(outcome.error_category or "unknown")

    if final_content is None:
        final_content = "I've completed processing but have no response to give."

        # AgentHook 的 ``after_send`` 是通用出站阶段，适用于所有来源。
    if len(self.hooks) > 0:
        from pico.runtime.hooks import AgentHookContext

        _send_ctx = AgentHookContext(
            session_key=key,
            outbound_content=final_content,
        )
        _send_decision = await self.hooks.after_send(_send_ctx)
        if _send_decision.modified_content is not None:
            final_content = _send_decision.modified_content
            for message in reversed(all_msgs[turn_start_idx:]):
                if message.get("role") == "assistant" and not message.get("tool_calls"):
                    message["content"] = final_content
                    break

    turn_artifact_messages = self._save_turn(
        session,
        all_msgs,
        turn_start_idx,
        origin,
    )
    self.sessions.save(session)
    await self.context_engine.after_turn(
        key,
        {
            "final_content": final_content,
            "messages": turn_artifact_messages,
            "context": context_metadata,
        },
    )
    await self._dispatch_backend_store(
        key,
        turn_artifact_messages,
    )
    if not self.context_engine.owns_compaction:
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        # ── 步骤 4：行动后学习（后台、非阻塞）──────────────────────────────
        # 子智能体结果回注时跳过（参见上方轮次前流程）：其内容是系统生成的通知，
        # 不是可供学习的用户输入。
    if self.enable_personalization and origin is not Origin.SUBAGENT:
        from pico.runtime.personalization import Personalizer

        _p4 = Personalizer(MemoryStore(self.state), self.provider, self.model)

        async def _post_learn():
            await _p4.post_learn(content, final_content)

        self._start_personalization_task(_post_learn)
        # ── 步骤 4 结束 ────────────────────────────────────────────────────

    if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt.sent_in_turn:
        # 防御性指纹。过去智能体通过 message 工具回复并静默返回 None 时不会留下
        # 痕迹，导致随机出现的无效轮次无法通过 grep 发现。记录原本要返回的响应，
        # 为后续调查留下与下方 "Response to ..." 并行的线索。
        if final_content:
            preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
            logger.info(
                "MessageTool sent in turn for {}:{}: {}",
                channel,
                sender_id,
                preview,
            )
        return None

    preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
    logger.info("Response to {}:{}: {}", channel, sender_id, preview)
    return (final_content, [])


def save_turn(
    self,
    session: Session,
    messages: list[dict],
    skip: int,
    origin: Origin | None = None,
) -> list[dict]:
    """把本轮新增消息清理后追加到 Session，并返回实际持久化的切片。

    ``messages[skip:]`` 是相对组装窗口新增的部分。SUBAGENT 来源的首条系统回注、带
    `_recovery_synthetic` 的空响应恢复脚手架，以及没有正文和 Tool call 的 Assistant
    空消息都不会落盘。Tool 正文超过 `_TOOL_RESULT_MAX_CHARS` 时截断，避免单次外部输出
    无限膨胀历史；该截断只影响 Session 副本，不修改调用方的原消息。

    User 消息会剥离 `ContextBuilder._RUNTIME_CONTEXT_TAG` 前缀，多模态 data:image 只记录
    ``[image]`` 占位，随后统一经过 `sanitize_persisted_payload`。每条记录补入时间戳并
    调用 `session.record`，最后更新 `session.updated_at`。返回列表精确表示后续 Backend
    可以消费的持久化事实，而不是原始运行时消息全集。
    """
    persisted: list[dict] = []
    for index, m in enumerate(messages[skip:]):
        entry = dict(m)
        role, content = entry.get("role"), entry.get("content")
        if origin is Origin.SUBAGENT and index == 0 and role == "user":
            continue
        if entry.get("_recovery_synthetic"):
            continue  # #1a 合成恢复推动消息——绝不持久化脚手架
        if role == "assistant" and not content and not entry.get("tool_calls"):
            continue  # 跳过空助手消息——它们会污染会话上下文
        if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
            entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
        elif role == "user":
            if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                # 去除运行时上下文前缀，只保留用户文本。
                parts = content.split("\n\n", 1)
                if len(parts) > 1 and parts[1].strip():
                    entry["content"] = parts[1]
                else:
                    continue
            if isinstance(content, list):
                filtered = []
                for c in content:
                    if (
                        c.get("type") == "text"
                        and isinstance(c.get("text"), str)
                        and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
                    ):
                        continue  # 从多模态消息中去除运行时上下文
                    if c.get("type") == "image_url" and c.get("image_url", {}).get("url", "").startswith("data:image/"):
                        filtered.append({"type": "text", "text": "[image]"})
                    else:
                        filtered.append(c)
                if not filtered:
                    continue
                entry["content"] = filtered
        entry = sanitize_persisted_payload(entry)
        entry.setdefault("timestamp", self._now_fn().isoformat())
        session.record(entry)
        persisted.append(entry)
    session.updated_at = self._now_fn()
    return persisted


async def run_turn(
    self,
    req: TurnRequest,
    emit: Emit,
    drain: Drain,
    *,
    stream: bool = True,
    usage_sink: dict[str, Any] | None = None,
    text_sink: dict[str, Any] | None = None,
) -> TurnOutcome:
    """作为 Spine 原生入口消费 `TurnRequest`，经单一 ``emit`` 扇出事件并返回 TurnOutcome。

    这个边界把旧实现的字符串返回值和五类 callback 收拢为一条可观察事件流。名称使用
    ``run_turn`` 而不是 ``run``，因为后者只负责 executor、debug server、MCP 拉起后的
    runtime keep-alive；Spine runner 包装本方法以满足 `TurnRunner` protocol，真实请求也
    从这里进入 `_process_message`。

    ``stream`` 是 canon Q2-D assembly switch。TUI 等 streaming outlet 传 ``True`` 时，
    回复以 StreamDelta 发送并在边界处 dissolves（b2 — no trailing Text）；REPL 等非流式
    出口传 ``False`` 时只发送一个 Text。它同时控制 LLM callbacks 与 message-tool routing，
    确保整份回复只走一种交付方式。媒体独立发为 MediaOut，Tool、Reasoning、Notice 和
    Usage 也都使用同一个 ``emit``。

    ``usage_sink`` 允许调用方观察包含 cost / context 的完整 Token 账目，比三字段
    TurnOutcome.usage 更丰富；TUI 用它填充 message.complete，REPL 可省略并读取返回值。
    ``text_sink`` 是回复文本的同类观察副本：最终内容写入 ``text_sink["text"]``，但仍只
    经 emit 交付一次，Cron Host 可在 Turn 后据此广播。``drain`` 则把
    BusyPolicy.INJECT 的中途消息传入每次迭代顶部。

    Sandbox init 等异常不会在这里转成错误字符串，而是继续传播，让 Lane 产生
    TurnFailed；这保留了 Spine 的失败事实。正常返回的 `TurnOutcome` 汇总 Usage、是否
    显式回复、Tool 次数与失败数、Memory 命中、Skill 注入和 Context 回退证据，不包含
    第二份用户回复。
    """
    from pico.capabilities.tools.builtin.cron import CronTool
    from pico.contracts.events import (
        MediaOut,
        Notice,
        NoticeKind,
        Reasoning,
        StreamDelta,
        Text,
        ToolEvent,
        ToolPhase,
        Usage,
    )
    from pico.runtime.scheduling.runner import TurnOutcome

    cid = req.conversation or f"{req.source.channel}:{req.source.chat_id}"

    streamed = False
    tool_calls = 0
    tool_failures = 0
    context_metadata: dict[str, Any] = {}

    async def on_token(text: str) -> None:
        nonlocal streamed
        if not text:
            return
        streamed = True
        await emit(StreamDelta(delta=text))

    async def on_reasoning(text: str) -> None:
        if text:
            await emit(Reasoning(content=text))

    async def on_tool(phase: str, info: dict[str, Any]) -> None:
        nonlocal tool_calls, tool_failures
        if phase == "start":
            tool_calls += 1
            if info["name"] != "message":
                await emit(
                    ToolEvent(
                        phase=ToolPhase.START,
                        tool_call_id=info["tool_call_id"],
                        name=info["name"],
                        arguments=info["arguments"],
                        target_call_id=info.get("target_call_id"),
                        target_name=info.get("target_name"),
                        target_arguments=info.get("target_arguments"),
                    )
                )
        else:
            if info["failed"]:
                tool_failures += 1
            if info["name"] != "message" or info["failed"]:
                await emit(
                    ToolEvent(
                        phase=ToolPhase.COMPLETE,
                        tool_call_id=info["tool_call_id"],
                        name=info["name"],
                        result_preview=info["result_preview"],
                        truncated=info["truncated"],
                        failed=info["failed"],
                        target_call_id=info.get("target_call_id"),
                        target_name=info.get("target_name"),
                        target_arguments=info.get("target_arguments"),
                        duration_ms=info.get("duration_ms"),
                    )
                )

    async def on_progress(text: str, tool_hint: bool = False) -> None:
        # 保留进度与工具提示的区别，让出口像总线路径一样，分别通过配置开关
        # （send_progress 与 send_tool_hints）控制：工具提示文本使用
        # NoticeKind.TOOL_HINT，进度使用 PROGRESS。不渲染两者的出口仍会吞掉这两类通知。
        if text:
            await emit(
                Notice(
                    kind=NoticeKind.TOOL_HINT if tool_hint else NoticeKind.PROGRESS,
                    detail=text,
                )
            )

    async def _emit_media(paths: list[str]) -> None:
        await emit(MediaOut(media=tuple(Media(path=p, mime="application/octet-stream", kind="file") for p in paths)))

    # 将 message 工具的回复路由到令牌流，使工具驱动的回复像主响应一样流式输出；
    # 此时 _process_message 返回 None，因此下方边界不会再次发出内容。回调属于当前轮次
    # （MessageTool 中的 ContextVar），并发轮次无法覆盖本轮路由，无需保存和恢复。
    message_tool = self.tools.get("message")
    if isinstance(message_tool, MessageTool):

        async def _route_to_stream(content: str, media: list[str]) -> None:
            # message 工具的回复可以附带媒体；需独立发出以免丢失（工具回复会让
            # _process_message 返回 None，下方边界看不到它）。内容与主回复遵循同一流式开关：
            # 流式时使用 StreamDelta，否则使用单个 Text；不然非流式出口会吞掉增量。
            if media:
                await _emit_media(media)
            if text_sink is not None and content:
                text_sink["text"] = content
            if stream:
                await on_token(content)
            elif content:
                await emit(Text(content=content))

        message_tool.set_send_callback(_route_to_stream)

    # CRON 轮次不得让智能体在运行途中调度新的 cron 任务。CronTool 通过 ContextVar
    # 防护；需在此处、即实际运行本轮的通道任务中设置，才能传播到工具。cron 回调在
    # 另一个任务中设置该值，无法传到本任务。
    cron_tool = self.tools.get("cron")
    cron_token = None
    if req.origin is Origin.CRON and isinstance(cron_tool, CronTool):
        cron_token = cron_tool.set_cron_context(True)

    if usage_sink is None:
        usage_sink = {}
    try:
        await self._start_executor()
        await self._connect_mcp()
        out = await self._process_message(
            req,
            session_key=cid,
            on_progress=on_progress,
            on_token_delta=on_token if stream else None,
            on_reasoning_delta=on_reasoning if stream else None,
            on_tool_event=on_tool,
            usage_sink=usage_sink,
            origin=req.origin,
            drain=drain,
            context_metadata_sink=context_metadata,
        )
    except Exception:
        await self.close_executor()
        raise
    finally:
        if cron_token is not None and isinstance(cron_tool, CronTool):
            cron_tool.reset_cron_context(cron_token)

    # 单一的返回到发出边界（N-UNIFORM）。MediaOut 独立于流，并先于 Text
    # （G-MEDIA-2(a)：当前顺序为媒体优先）。
    if out is not None:
        reply_content, reply_media = out
        if reply_media:
            await _emit_media(reply_media)
        if not streamed and reply_content:
            await emit(Text(content=reply_content))
        if text_sink is not None and reply_content:
            text_sink["text"] = reply_content

    usage = Usage(
        prompt_tokens=int(usage_sink.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage_sink.get("completion_tokens", 0) or 0),
        total_tokens=int(usage_sink.get("total_tokens", 0) or 0),
    )
    # message 工具回复虽会让 _process_message 返回 None，但确实已回复，
    # 因此也计作显式回复。
    replied_via_tool = isinstance(message_tool, MessageTool) and message_tool.sent_in_turn
    return TurnOutcome(
        usage=usage,
        explicit_reply=out is not None or replied_via_tool,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        memory_hits=int(context_metadata.get("memory_hits", 0) or 0),
        injected_skill_ids=tuple(context_metadata.get("injected_skill_ids") or ()),
        context_path=context_metadata.get("path"),
        context_fallback_reason=context_metadata.get("fallback_reason"),
        skill_source_failures=tuple(context_metadata.get("skill_source_failures") or ()),
    )
