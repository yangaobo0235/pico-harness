"""Conversation state, resolution results, and session identifiers."""

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def new_chat_id(now: datetime | None = None) -> str:
    """生成 Opaque、Sortable 的 Per-session Chat ID：``YYYYMMDD_HHMMSS_xxxxxx``。

    Timestamp Prefix 使 Value 可按创建时间排序，6-char UUID Suffix 降低同秒 Collision；格式与
    Channel 无关。该值成为 ``channel:chat_id`` Key 的 Chat Segment 与 JSONL Filename Stem，不编码
    User Identity，也不保证全局 Cryptographic Uniqueness。
    """
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class SessionResolution:
    """记录 User-supplied Session ID 解析为 Full Key 的 Outcome。

    ``status`` 只能是 ``"resolved"``、``"ambiguous"``、``"not_found"``。Resolved 时 ``key`` 携带
    ``channel:chat_id``；Ambiguous 时 ``candidates`` 给出全部 Full Keys。No-match 保持 not_found，
    Caller 自己决定 Tail：Agent ``--session`` 可 Mint ``cli:<value>``，Read-only Export 必须 Error，
    Resolver 不替不同 Workflow 猜策略。
    """

    status: str
    key: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass
class Session:
    """保存一段 Conversation 的 Message Fact、Metadata 与 Persistence State。

    Messages 以 JSONL 易读持久化，正常写入为 Append-only，以保持 Ordering 与 LLM Cache Efficiency。
    ``last_consolidated`` 只标明哪些消息已总结进 MEMORY.md/HISTORY.md；Consolidation does NOT 修改
    messages list，也不改变 ``get_history()`` 输出的 Tail Fact。Clear/Undo 是显式 History Rewrite，
    必须经 Manager Fence Concurrent Writer 后落盘。

    pending_clarification 是当前等待偏好答案的 Interaction State，不是普通 History；Storage Epoch、
    Persisted Snapshot 与 Rewrite Flag 属于 Manager 并发控制。Session 本身不执行 I/O，Caller 必须
    调用 SessionManager.save/commit_history_rewrite。
    """

    key: str  # channel:chat_id 格式的键
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # 已归并到文件的消息数量
    # ── 个性化状态 ───────────────────────────────────────────────────────────
    # Agent 提出澄清问题并等待回答时设置。
    # 结构：{"original_message": str, "question": str, "domain": str}
    # 用户回答处理完毕后立即清除。
    pending_clarification: dict | None = field(default=None)
    # 已落盘的消息数量；save() 只追加该索引之后的消息。
    _persisted_count: int = field(default=0, repr=False)
    # 用于区分已保存的空会话和从未持久化的惰性会话。
    _persisted: bool = field(default=False, repr=False, compare=False)
    _storage_epoch: int = field(default=0, repr=False, compare=False)
    _persisted_snapshot: dict[str, Any] | None = field(default=None, repr=False, compare=False)
    _requires_rewrite: bool = field(default=False, repr=False, compare=False)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """用 ``role``、``content`` 与扩展 Field 向 Session 追加一条 Message。

         方法只组装 Dict 并委托 `record`，因此 Timestamp、Append Order 与 updated_at 规则保持单一
        入口。它不立即写 Disk，也不校验 Provider Role Sequence；Persistence 由 Manager 负责。
        """
        self.record({"role": role, "content": content, **kwargs})

    def record(self, msg: dict[str, Any]) -> None:
        """向内存 Tail 追加 Message Dict，并在缺失时 Stamp Wall-clock Timestamp。

        这是 Session Write 的 Single Choke Point：``add_message``、AgentLoop ``_save_turn``、
        Clarification Append 都必须经过这里，确保没有 Unstamped Message。Caller-set ``timestamp``
        保留；Per-message Order 与 Turn Group 直接来自 Append Order 和 ``role`` Boundary，不维护另一套
        received_at/turn_id。

        方法原地接纳 Dict、更新 updated_at，但不 Save；Caller 后续修改同 Dict 会影响 Session，因而
        应把传入对象视为已转移所有权。
        """
        msg.setdefault("timestamp", datetime.now().isoformat())
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """返回供 LLM 使用的 Unconsolidated Message View，并对齐到 User Turn 起点。

         先取 ``messages[last_consolidated:]``，再保留最后 ``max_messages`` 项；若切片从 Assistant/
         Tool 中间开始，丢弃首个 User 之前内容，避免 Orphan Tool Result。输出只保留 Provider 所需
         Role/Content、Tool Pair 与 Reasoning/Thinking Field，移除 Timestamp/Metadata。

         返回新 Dict List，不修改 Append-only Messages。``max_messages=0`` 的 Python Slice 语义会取
        完整 Tail，供 Legacy Context Path 使用；此方法不执行 Token Budget Trimming。
        """
        unconsolidated = self.messages[self.last_consolidated :]
        sliced = unconsolidated[-max_messages:]

        # 丢弃开头的非用户消息，避免产生孤立的 tool_result 块。
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """清空全部 Message，并把 Session Interaction State 重置为 Initial State。

        Messages 变空、last_consolidated 归零、pending_clarification 清除、updated_at 刷新。该操作只
        修改内存对象，不自动删除/改写 JSONL；Caller 必须用 `commit_history_rewrite` Fence Old
        Writer。Metadata/Created_at 保留，Session Identity 不变。
        """
        self.messages = []
        self.last_consolidated = 0
        self.pending_clarification = None
        self.updated_at = datetime.now()

    def undo_last_turn(self, n: int = 1) -> int:
        """从 Unconsolidated Tail 删除最后 ``n`` 个 User-turn Blocks。

        Turn 从 ``role == "user"`` 开始，到下一 User Message 前结束，后续 Assistant/Tool 都继承该
        Block。只允许修改 ``messages[last_consolidated:]``；已经总结进 MEMORY.md 的内容绝不跨越。
        ``n < 1`` 或 Tail 无 User 时返回 0，否则返回实际 Removed Message Count，并清 Waiting
        Clarification。

        这是内存 Rewrite，Persistence 仍是 Caller 责任，应经 ``SessionManager.save`` 的 Rewrite/Fence
        Path，而不是普通 Append。
        """
        if n < 1:
            return 0
        start = self.last_consolidated
        user_starts = [i for i in range(start, len(self.messages)) if self.messages[i].get("role") == "user"]
        if not user_starts:
            return 0
        cut_index = user_starts[-n] if n <= len(user_starts) else user_starts[0]
        removed = len(self.messages) - cut_index
        self.messages = self.messages[:cut_index]
        self.pending_clarification = None
        self.updated_at = datetime.now()
        return removed

    def _persistence_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "messages": self.messages,
                "metadata": self.metadata,
                "last_consolidated": self.last_consolidated,
                "pending_clarification": self.pending_clarification,
            }
        )

    def _mark_persisted(self) -> None:
        self._persisted_snapshot = self._persistence_snapshot()

    def _is_dirty(self) -> bool:
        if self._requires_rewrite:
            return True
        if not self._persisted:
            return bool(
                self.messages or self.metadata or self.last_consolidated or self.pending_clarification is not None
            )
        return self._persisted_snapshot != self._persistence_snapshot()
