"""Token-pressure policy and per-session scheduling for memory consolidation."""

from __future__ import annotations

import asyncio
import weakref
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from pico.observability.tracing import semconv, trace
from pico.shared.tokenization import estimate_message_tokens, estimate_prompt_tokens_chain

if TYPE_CHECKING:
    from pico.integrations.llm.contracts import LLMProvider
    from pico.runtime.sessions.service import Session, SessionManager


from pico.capabilities.memory.consolidation.store import MemoryStore


class MemoryConsolidator:
    """拥有 Consolidation Policy、Per-session Locking 与 Session Offset Updates。

    Consolidator 连接 `MemoryStore`、LLM Provider、Session Manager、Context Builder 与 Tool Definitions。
    当 Normal Prompt 达到 Context Window 时，它在 User-turn Boundary 选择 Old Chunk，先 Annotate 到
    Episodes，再推进 `session.last_consolidated` 并持久化 Session；至少一个 Chunk 成功后才触发 Hot-tag
    Profile Refresh。

    每个 Session Key 使用共享 Async Lock，避免同进程重复归并。它拥有“何时归并、归并到哪里”的状态，
    Store 拥有文件内容，Session Manager 拥有 Offset Durability。Annotation 成功与 Prompt 已缩到目标值
    分属不同证据。
    """

    _MAX_CONSOLIDATION_ROUNDS = 5

    # 自上次刷新后，某标签累积足够多的新事件时，触发用户资料分节刷新。
    # 低于阈值时事件仍会累积，但 user.md 保持不变。
    _REFRESH_HOT_TAG_THRESHOLD = 5

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        now_fn: Callable[[], datetime] | None = None,
        *,
        enable_foresight: bool = False,
    ):
        self.store = MemoryStore(workspace, now_fn=now_fn)
        self.provider = provider
        self.model = model
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        # 为 True 时，annotate() 会让 LLM 与事件一起生成预见预测，并持久化到
        # user.md 的 ## Foresight。默认关闭。
        self.enable_foresight = enable_foresight
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """返回一个 Session 共用的 Consolidation `asyncio.Lock`。

        Locks 存在 WeakValueDictionary 中；有活跃持有者/引用时同 Key 复用，完全不用后可被 GC，避免长期
        Session ID 无界积累。该锁只协调当前 Process，不替代 `MemoryStore` 的 Cross-process File Lock。
        """
        lock = self._locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_key] = lock
        return lock

    async def consolidate_messages(self, messages: list[dict[str, object]]) -> bool:
        """Light Path：把 Selected Message Chunk Annotate 进 ``episodes.md``。

        这里 **不** Rewrite Profile；所有 Annotation Rounds 结束后再由 :meth:`maybe_refresh_hot_tags` 处理，
        让 LLM 每次只看到一个 Tag 的 Relevant Context。返回值直接反映 `MemoryStore.annotate` Pipeline 是否
        成功，不表示一定写入了 Episode。
        """
        return await self.store.annotate(
            messages,
            self.provider,
            self.model,
            enable_foresight=self.enable_foresight,
        )

    async def maybe_refresh_hot_tags(self) -> int:
        """刷新自 Last Refresh 后 Backing Tag 已 Heated Up 的 Profile Sections。

        使用 Class 固定 Threshold 调用 Store Heavy Path，返回成功处理的 Section 数。它应在 Annotation
        Batch 后调用，而非每条 Message 都触发昂贵 LLM Rewrite。
        """
        return await self.store.maybe_refresh_hot_tags(
            self.provider,
            self.model,
            threshold=self._REFRESH_HOT_TAG_THRESHOLD,
        )

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """选择能移除足够 Old Prompt Tokens 的 User-turn Boundary。

        从 ``session.last_consolidated`` 开始累加 `estimate_message_tokens`，只在下一条 User Message 之前
        形成 Safe Boundary，避免把一个 User/Assistant/Tool Interaction 从中间切开。返回
        ``(end_index, removed_tokens)``；没有可用 Boundary、起点在尾部或请求移除量非正时返回 `None`。
        """
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """估算 Normal Session History View 的 Current Prompt Size。

        方法使用真实 `session.get_history`、Context Message Builder、Channel/Chat ID 与 Tool Definitions
        组装 ``[token-probe]`` Request，再通过 Provider Counter → Tiktoken Chain 返回 ``(tokens, source)``。
        该估算比单条求和更接近实际 Prompt，但仍不是 Provider Usage Receipt。
        """
        history = session.get_history(max_messages=0)
        channel, chat_id = session.key.split(":", 1) if ":" in session.key else (None, None)
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_unconsolidated(self, session: Session) -> bool:
        """为 ``/new``-style Session Rollover 归档完整 Unconsolidated Tail。

         在 Per-session Lock 内 Snapshot ``last_consolidated:`` Tail，Annotate 到 ``episodes.md``，成功后运行
        一轮 Hot-tag Section Refresh，使 Profile 有机会反映刚关闭 Session。空 Tail 返回 `True`；失败时不
         伪装归档完成。方法本身不推进 Session Offset，因为 Rollover 管理后续 Session Lifecycle。
        """
        lock = self.get_lock(session.key)
        async with lock:
            snapshot = session.messages[session.last_consolidated :]
            if not snapshot:
                return True
            ok = await self.consolidate_messages(snapshot)
            if ok:
                await self.maybe_refresh_hot_tags()
            return ok

    @trace.instrument("memory.consolidate", extract=semconv.memory_consolidate)
    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        """循环 Archive Old Messages，直到 Prompt Fits Within Half Context Window 或无法继续。

        空 Session/无效 Window 直接返回。只有 Initial Estimate 达到或超过完整 Context Window 才启动，目标
        是 Window 的一半；每轮最多 `_MAX_CONSOLIDATION_ROUNDS`，选择 Safe User Boundary、Annotate Chunk、
        推进并保存 `last_consolidated`，再重新估算。任一步失败、无 Boundary 或 Estimate 无效都会停止，
        不删除原 Messages。

        至少成功 Annotate 一个 Chunk 后，整次调用最多执行一次 Hot-tag Refresh。方法无返回值，Caller
        需要通过 Session Offset、Episodes/Profile 文件与日志区分“触发过”“持久化过”和“已达到目标”。
        """
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            target = self.context_window_tokens // 2
            estimated, source = self.estimate_session_prompt_tokens(session)
            if estimated <= 0:
                return
            if estimated < self.context_window_tokens:
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                )
                return

            chunks_annotated = 0
            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    break

                boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    break

                end_idx = boundary[0]
                chunk = session.messages[session.last_consolidated : end_idx]
                if not chunk:
                    break

                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )
                if not await self.consolidate_messages(chunk):
                    break
                chunks_annotated += 1
                session.last_consolidated = end_idx
                self.sessions.save(session)

                estimated, source = self.estimate_session_prompt_tokens(session)
                if estimated <= 0:
                    break

            # 只要至少标注了一个块，就让活跃标签有机会刷新对应的用户资料分节。
            # 无论触发多少轮标注，每次 ``maybe_consolidate_by_tokens`` 调用最多执行一次。
            if chunks_annotated:
                await self.maybe_refresh_hot_tags()
