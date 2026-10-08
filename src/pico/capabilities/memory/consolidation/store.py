"""Locked Markdown storage, selection and generation metadata for memory."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

from loguru import logger

from pico.observability.tracing import semconv, trace
from pico.shared.paths import ensure_dir

if TYPE_CHECKING:
    from pico.integrations.llm.contracts import LLMProvider


from pico.capabilities.memory.consolidation.formatting import (
    _FORESIGHT_BULLET_RE,
    _FORESIGHT_HEADING,
    _ensure_foresight_at_end,
    _format_foresight_bullet,
    _is_semantic_duplicate_foresight,
    _parse_episode_line,
    _parse_history_paragraph_ts_ms,
    _parse_user_md_sections,
    _score_section_relevance,
    _splice_h2_section,
    _splice_h2_section_at_end,
)


class MemoryStore:
    """拥有 Two-layer Memory 的 Store：``user.md`` Profile + ``episodes.md`` Grep-searchable Event Log。

    旧名称 ``MEMORY.md`` / ``HISTORY.md`` 的职责分别迁移到 Workspace ``user_memory/profile/user.md`` 与
    ``user_memory/episodic/episodes.md``。Store 负责 Locked Profile Writes、Episode Append、Foresight、Tag
    Offsets、Section Selection 与 LLM Annotation/Refresh；文件路径和写入锁由实例持有。

    生命周期与 Workspace 一致，没有显式 Start/Stop。多进程修改 `user.md` 必须使用 `locked`；Episode
    Append 当前是直接追加。Store 写入成功不代表下次 Context 一定选择该 Section。
    """

    def __init__(
        self,
        workspace: Path,
        now_fn: Callable[[], datetime] | None = None,
    ):
        # 用户资料和事件日志位于 ``user_memory`` 支柱下。``memory_dir`` 是
        # ``memory_file.parent`` 的别名，供需推导同级路径的调用点使用，如下方的锁文件。
        self.memory_file = ensure_dir(workspace / "user_memory" / "profile") / "user.md"
        self.history_file = ensure_dir(workspace / "user_memory" / "episodic") / "episodes.md"
        self.memory_dir = self.memory_file.parent
        # 写入 user.md 的各进程共享同级锁文件。
        self.memory_lock_path = self.memory_file.with_suffix(self.memory_file.suffix + ".lock")

        # ``consolidate`` 用它向归并 LLM 提示词注入 ``Current Time:``。如果没有它，
        # 即使 LLM 看到的会话项已使用伪时钟标记，其摘要段落时间戳仍会回退到墙上时间。
        self._now_fn = now_fn or datetime.now

    @contextmanager
    def locked(self) -> Iterator[None]:
        """持有 Profile File 的 Exclusive Lock，防止 REPL + Gateway Concurrent Writers 互相覆盖。

        通过跨平台的 `portalocker` 保护 ``user.md``，
        Windows 也真实串行化。Usage：

            with memory.locked():
                cur = memory.read_long_term()
                memory.write_long_term(cur + "...")

        Context 只提供互斥，不自动 Read-modify-write；Caller 必须把整个组合操作放在 Block 内。
        """
        yield from self._file_locked(self.memory_lock_path)

    def _file_locked(self, lock_path: Path) -> Iterator[None]:
        # 跨平台建议锁（portalocker）在 Windows 上也能实现真正串行化，取代之前的 win32 空操作；
        # 旧实现会丢失对 user.md 的并发写入。
        from pico.shared.locking import file_lock

        with file_lock(lock_path):
            yield

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    _FORESIGHT_MAX_KEEP_DEFAULT = 20

    def append_foresight(
        self,
        foresights: list[dict[str, Any]],
        *,
        max_keep: int | None = None,
    ) -> int:
        """把 LLM-emitted Foresight Predictions 持久化到 ``user.md`` 的 ``## Foresight``。

        Section 不存在时通过 ``_splice_h2_section`` Fallback 语义创建并置于文件末尾。先按
        ``(prediction text, src_ts)`` 做 Exact Dedup，再以
        Content-token Jaccard 拦截 Reworded Semantic Duplicates。总 Bullet Count 使用 FIFO Cap，默认
        ``max_keep=20``，超出时从前端丢弃 Oldest Entries，使 Section 可扫描。整个 Read-modify-write 在
        Memory Lock 下完成，和 Concurrent Consolidator/Personalizer 安全协调。

        返回 Post-dedupe 实际写入的新 Entry 数；Empty Input 或 All Dupes 返回 0 且不触碰文件。写入的是
        Prediction Evidence，不代表预测已发生；非法/缺失字段会以 ``?`` 可见保留供 Review。
        """
        if not foresights:
            return 0
        cap = max_keep if max_keep is not None else self._FORESIGHT_MAX_KEEP_DEFAULT
        gen_ts = self._now_fn().strftime("%Y-%m-%d %H:%M")

        with self.locked():
            current = self.read_long_term()
            sections = _parse_user_md_sections(current)

            # 原样保留 ## Foresight 分节中的已有条目，避免重写时反复改动格式。
            existing_bullets: list[str] = []
            if _FORESIGHT_HEADING in sections:
                for line in sections[_FORESIGHT_HEADING].splitlines():
                    if line.lstrip().startswith("-"):
                        existing_bullets.append(line.rstrip())

            existing_keys: set[tuple[str, str]] = set()
            existing_predictions: list[str] = []
            for line in existing_bullets:
                m = _FORESIGHT_BULLET_RE.match(line)
                if m:
                    pred_text = m.group("prediction").strip()
                    existing_keys.add((pred_text, m.group("src_ts").strip()))
                    existing_predictions.append(pred_text)

            new_bullets: list[str] = []
            written = 0
            semantic_skipped = 0
            for fs in foresights:
                pred = (fs.get("prediction") or "").strip()
                src_ts = (fs.get("src_ts") or "").strip()
                if not pred:
                    continue
                key = (pred, src_ts)
                if key in existing_keys:
                    continue
                # 语义去重。( prediction, src_ts ) 键只能识别完全相同的字符串；LLM 会对来自不同事件的
                # 同一主张换语重发，这些都会漏过。使用内容词元的 Jaccard 相似度拦截，
                # 也会拦截当前批次内的重复项。
                if _is_semantic_duplicate_foresight(pred, existing_predictions):
                    semantic_skipped += 1
                    continue
                new_bullets.append(_format_foresight_bullet(fs, gen_ts))
                existing_keys.add(key)
                existing_predictions.append(pred)
                written += 1
            if semantic_skipped:
                logger.info(
                    "append_foresight: skipped {} semantic-duplicate prediction(s)",
                    semantic_skipped,
                )

            if written == 0:
                return 0

            all_bullets = existing_bullets + new_bullets
            # FIFO：保留最新的 ``cap`` 项，丢弃最旧项
            if len(all_bullets) > cap:
                all_bullets = all_bullets[-cap:]

            body = "\n".join(all_bullets)
            base = current or "# Long-term Memory\n"
            # 始终置底变体：如果 ## Foresight 已位于文件中部，例如 annotate 早于任何
            # refresh_section 创建 ## Projects，则将其移到底部，使视觉顺序为：
            # 先放稳定的用户资料分节，最后放自动管理的 Foresight。
            new_content = _splice_h2_section_at_end(
                base,
                _FORESIGHT_HEADING,
                body,
            )
            if new_content != current:
                self.write_long_term(new_content)
            return written

    def read_history_since(self, since_ms: int) -> str:
        """返回 Leading Timestamp ``>= since_ms`` 的 HISTORY.md Entries。

        当前文件是 ``episodes.md``，历史接口仍称 HISTORY.md。Entries 按 `append_history` 以 Blank Line
        分段，Consolidator LLM Prompt 要求每段以 ``[YYYY-MM-DD HH:MM]`` 开头。方法按 ``\\n\\n`` Split、解析 Stamp，只
        保留不早于给定 Epoch Milliseconds 的 Paragraph。

        Malformed/Missing Stamp 无法可靠 Anchored in Time，因此 Drop；文件 Missing 或 Read Error 返回
        ``""``。返回内容只经过时间过滤，不保证每条 Episode 的事实质量。
        """
        if not self.history_file.exists():
            return ""
        try:
            raw = self.history_file.read_text(encoding="utf-8")
        except OSError:
            return ""

        kept: list[str] = []
        for paragraph in raw.split("\n\n"):
            stripped = paragraph.strip()
            if not stripped:
                continue
            ts_ms = _parse_history_paragraph_ts_ms(stripped)
            if ts_ms is None or ts_ms < since_ms:
                continue
            kept.append(stripped)
        return "\n\n".join(kept)

    # 共享辅助函数将用户资料和事件记录的修改限制在 MemoryStore 内。

    def read_history_tail(self, lines: int) -> str:
        """返回 HISTORY.md 最后 ``lines`` 条 Non-blank Lines。

        当前文件是 ``episodes.md``。``lines <= 0`` 返回全部 Non-blank Lines，Missing File 或 Read Error
        返回 ``""``。方法原属于已删除的 ``DefaultMemoryEngine`` Facade，现在是 `MemoryStore` Public
        Surface。它按行裁剪，不理解 Paragraph 或 Timestamp Boundaries。
        """
        if not self.history_file.exists():
            return ""
        try:
            raw = self.history_file.read_text(encoding="utf-8")
        except OSError:
            return ""
        non_blank = [line for line in raw.splitlines() if line.strip()]
        if lines <= 0:
            return "\n".join(non_blank)
        return "\n".join(non_blank[-lines:])

    def update_section(
        self,
        heading: str,
        body: str,
        *,
        at_end: bool = True,
    ) -> None:
        """Replace 或 Insert MEMORY.md 中一个 H2 Section。

        当前文件是 ``user.md``。必须在 :meth:`locked` 内调用；方法不自行 Acquire Lock，使 Caller 可以把
        Multiple Updates Group 在同一 Lock：

            with store.locked():
                store.update_section("## Preferences", body)

        ``at_end=True`` 默认使用 :func:`_splice_h2_section_at_end`，保证 Named Section 写后位于 File End；
        ``at_end=False`` 使用 :func:`_splice_h2_section` 保留 Existing Position。方法直接写盘、无返回值，
        不执行 CAS。
        """
        current = self.read_long_term()
        if at_end:
            new = _splice_h2_section_at_end(current, heading, body)
        else:
            new = _splice_h2_section(current, heading, body)
        self.write_long_term(new)

        # 感知分节的读取。

    _SECTION_READ_TOP_K = 2
    _NOTES_HEADING_PREFIX = "## Notes"

    def get_memory_context(
        self,
        current_message: str | None = None,
    ) -> str:
        """返回要嵌入 Agent System Prompt 的 Memory Block。

        ``current_message=None`` 或 Empty 时返回 Full ``user.md`` Dump，适合 Cold-start Session 或无 User
        Query Ping。提供 Message 时，解析 H2 Sections、按 Lexical Overlap 评分，选择默认 Top-K=2，并加入
        ``## Notes`` Catchall；保留的 Sections 按 Original File Order 呈现。

        Section Parsing/Selection 无结果时 Fall Back 到 Full Dump；文件空则返回空字符串。返回 Block 只
        表示选中候选，仍需 Context Assembler 真正放进 Provider Request。
        """
        long_term = self.read_long_term()
        if not long_term:
            return ""
        if not current_message or not current_message.strip():
            return f"## Long-term Memory\n{long_term}"
        sections = _parse_user_md_sections(long_term)
        if not sections:
            return f"## Long-term Memory\n{long_term}"
        selected = self._select_relevant_sections(
            current_message,
            sections,
            top_k=self._SECTION_READ_TOP_K,
        )
        if not selected:
            return f"## Long-term Memory\n{long_term}"
        body = "\n\n".join(f"{heading}\n\n{section_body}".rstrip() for heading, section_body in selected.items())
        return f"## Long-term Memory\n\n{body}\n"

    @classmethod
    def _select_relevant_sections(
        cls,
        query: str,
        sections: dict[str, str],
        top_k: int = 2,
    ) -> dict[str, str]:
        """为每个 Section 打分，保留 Score > 0 的 Top-K，并加入 ``## Notes`` Catchall。

        Score 为 0 的 Sections **NOT Included** as Filler，否则 Tied-zero Content 会 Leak 进 Prompt。Notes
        Heading Prefix 始终保留。Returned Dict 按 Source File Order 重建，确保 Predictable Rendering，而
        不是按 Score 排列。
        """
        scored = [(heading, body, _score_section_relevance(query, heading, body)) for heading, body in sections.items()]
        scored.sort(key=lambda x: x[2], reverse=True)
        keep_keys: set[str] = {h for h, _, score in scored[:top_k] if score > 0}
        for heading in sections:
            if heading.startswith(cls._NOTES_HEADING_PREFIX):
                keep_keys.add(heading)
        return {h: b for h, b in sections.items() if h in keep_keys}

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        lines = []
        for message in messages:
            if not message.get("content"):
                continue
            tools = f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {message['content']}"
            )
        return "\n".join(lines)

    @trace.instrument("memory.extract", extract=semconv.memory_extract)
    async def annotate(
        self, messages: list[dict], provider: LLMProvider, model: str, *, enable_foresight: bool = False
    ):
        """Delegate model annotation work to its owning service."""
        from pico.capabilities.memory.consolidation import annotation

        return await annotation.annotate(self, messages, provider, model, enable_foresight=enable_foresight)

    # -------------------------------------------------------------------
    # 重量路径：由标签频率触发用户资料分节刷新。
    # -------------------------------------------------------------------

    @property
    def _tag_offsets_path(self) -> Path:
        """返回 ``episodes.md`` 旁的 ``.consolidation_offsets.json`` Path。

        文件记录每个 Tag 在 Last Refresh 时的 Episode Count，使下次只根据 Delta 判断是否需要 Profile
        Refresh。Property 只计算路径，不创建或读取文件。
        """
        return self.history_file.parent / ".consolidation_offsets.json"

    def read_tag_offsets(self) -> dict[str, int]:
        """读取 Last Section Refresh 时的 Per-tag Episode Count。

        Missing File 或 Bad JSON 返回 Empty Dict，按 ``never refreshed`` 处理并记录 Parse Warning。有效
        Payload 只保留可转成 Integer 的数值项；返回值是当前 Snapshot，不持有文件锁。
        """
        p = self._tag_offsets_path
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("tag offsets: failed to parse {}; starting fresh", p)
            return {}
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}

    def write_tag_offsets(self, offsets: dict[str, int]) -> None:
        """以 Temp + Rename 原子写入 Tag Offsets File。

        创建父目录，使用 Sorted/Indented JSON 保持可审计，然后替换目标。方法无返回值；OS/Serialization
        Error 向上传播，防止 Refresh 成功后 Offset 悄悄未保存。
        """
        p = self._tag_offsets_path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(offsets, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(p)

    def count_tags(self) -> dict[str, int]:
        """统计整个 ``episodes.md`` 中每个 Tag 的 Total Occurrence Count。

        只处理可由 `_parse_episode_line` 解析的 Event Lines，Freeform/Invalid Lines 跳过；同一 Episode 中
        出现的每个 Tag 各加一。Missing File 返回空 Dict。Count 是 Refresh Trigger Evidence，不代表 Tag
        对应事实仍为当前状态。
        """
        if not self.history_file.exists():
            return {}
        counts: dict[str, int] = {}
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            parsed = _parse_episode_line(line)
            if not parsed:
                continue
            _, _, tags = parsed
            for t in tags:
                counts[t] = counts.get(t, 0) + 1
        return counts

    def recent_project_tags(
        self,
        *,
        days: int = 14,
        limit: int = 12,
    ) -> list[tuple[str, int]]:
        """返回最近 ``days`` 内最多 ``limit`` 个 ``(project-tag, count)`` Pairs，按 Frequency 排序。

        只统计 ``episodes.md`` 中 Parseable、Timestamp 不早于 Cutoff、且以 ``project-`` 开头的 Tags。
        `annotate()` 用结果 Seed Prompt 的 ``slugs you've already used``，促使 LLM 复用旧值，防止同一项目
        被拆成多个 ``#project-*-cli`` / ``-docs`` / ``-release`` Variants。Missing File 返回空列表。
        """
        from datetime import timedelta

        if not self.history_file.exists():
            return []
        cutoff = self._now_fn() - timedelta(days=days)
        counts: dict[str, int] = {}
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            parsed = _parse_episode_line(line)
            if not parsed:
                continue
            ts, _, tags = parsed
            ts_norm = ts.replace("T", " ")
            try:
                dt = datetime.strptime(ts_norm, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if dt < cutoff:
                continue
            for t in tags:
                if t.startswith("project-"):
                    counts[t] = counts.get(t, 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]

    def hot_tags(self, threshold: int) -> list[tuple[str, int, int]]:
        """返回满足 ``current_count - last_offset >= threshold`` 的 Hot Tags。

        结果 Shape 是 ``[(tag, current_count, previous_offset), ...]``，按 Delta Descending 排序，使 Hottest
        Tag First Refresh。Threshold 非正时可能让所有已有 Tag 变 Hot，上层负责提供合理配置。
        """
        counts = self.count_tags()
        offsets = self.read_tag_offsets()
        hot: list[tuple[str, int, int]] = []
        for tag, current in counts.items():
            prev = offsets.get(tag, 0)
            if current - prev >= threshold:
                hot.append((tag, current, prev))
        hot.sort(key=lambda x: x[1] - x[2], reverse=True)
        return hot

    def _episodes_for_tag(
        self,
        tag: str,
        max_episodes: int = 50,
    ) -> list[str]:
        """返回携带给定 Tag 的最近最多 N 条 Episode Lines，并按 Chronological Order 排列。

        方法从 ``episodes.md`` Tail 反向扫描，只接受 Parseable Lines，达到 `max_episodes` 后停止，再反转为
        正序。Missing File 返回空列表。结果是 `refresh_section` 的 Evidence Window，不包含更早事件。
        """
        if not self.history_file.exists():
            return []
        matches: list[str] = []
        for line in reversed(self.history_file.read_text(encoding="utf-8").splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            parsed = _parse_episode_line(stripped)
            if not parsed:
                continue
            _, _, tags = parsed
            if tag in tags:
                matches.append(stripped)
                if len(matches) >= max_episodes:
                    break
        matches.reverse()
        return matches

    async def refresh_section(self, tag: str, provider: LLMProvider, model: str, max_episodes: int = 50):
        """Delegate model annotation work to its owning service."""
        from pico.capabilities.memory.consolidation import annotation

        return await annotation.refresh_section(self, tag, provider, model, max_episodes)

    def _splice_section_and_write(
        self,
        heading: str,
        new_body: str,
        expected_prev: str,
    ) -> bool:
        """执行 CAS Write：仅当 ``user.md`` 仍等于 ``expected_prev`` 时 Splice ``new_body``。

        在 Memory Lock 内重新读取文件；发现 Concurrent Writer 已修改时记录日志、返回 `False`，留待 Next
        Round Retry。匹配时替换 ``heading`` Body，并确保 Auto-managed ``## Foresight`` 仍在文件末尾；
        Content 有变化才写盘。返回 `True` 表示 CAS 条件成立并完成该路径，即使新内容与旧内容相同。
        """
        with self.locked():
            current = self.read_long_term()
            if current != expected_prev:
                logger.info("refresh_section: concurrent modification detected; skipping write (will retry next round)")
                return False
            new_content = _splice_h2_section(current, heading, new_body)
            # 无论 refresh_section 将新分节插入何处，都将自动管理的 ## Foresight 保持在 user.md 底部。
            # 该操作幂等；Foresight 不存在或已位于最后时不执行任何操作。
            new_content = _ensure_foresight_at_end(new_content)
            if new_content != current:
                self.write_long_term(new_content)
            return True

    @trace.instrument("memory.profile_refresh", extract=semconv.memory_profile_refresh)
    async def maybe_refresh_hot_tags(self, provider: LLMProvider, model: str, threshold: int = 5):
        """Delegate model annotation work to its owning service."""
        from pico.capabilities.memory.consolidation import annotation

        return await annotation.maybe_refresh_hot_tags(self, provider, model, threshold)
