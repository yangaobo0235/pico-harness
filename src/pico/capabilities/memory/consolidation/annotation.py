"""Model annotation and profile refresh over a persistent MemoryStore."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pico.integrations.llm.contracts import LLMProvider


from pico.capabilities.memory.consolidation.formatting import (
    _FORESIGHT_HEADING,
    _drop_bullets_without_src,
    _ensure_text,
    _is_process_only_episode,
    _normalize_save_memory_args,
)
from pico.capabilities.memory.consolidation.tool_schemas import _REFRESH_SECTION_TOOL, _build_annotate_tool


async def annotate(
    self, messages: list[dict], provider: LLMProvider, model: str, *, enable_foresight: bool = False
) -> bool:
    """Light Path：只 Annotate 当前 Conversation Chunk。

    Produces 两类可选结果：带 ``#tags`` 的 Single-line ``episodes.md`` Entries；以及仅在
    ``enable_foresight=True`` 时写入 ``user.md ## Foresight`` 的 ``foresight_hint``。方法 **不**修改
    User Profile Sections；Tag 积累足够 New Events 后，Heavy Path ``maybe_refresh_hot_tags`` 才调用
    ``refresh_section``。

    默认 ``enable_foresight=False`` 会从 Tool Schema 完全移除 Prediction Slot。空 Messages 直接成功；
    LLM 未调用 Tool、Arguments 结构错误或 Provider Exception 返回 `False`。Process-only Episodes 在
    写回边界丢弃。返回 `True` 表示 Annotation Pipeline 完成，不保证写入了非空 Episode。
    """
    if not messages:
        return True
    now_str = self._now_fn().strftime("%Y-%m-%d %H:%M (%A)")
    if enable_foresight:
        slot_lines = '- episode_summary: ARRAY of single-line entries "[YYYY-MM-DD HH:MM] <summary, <=100 chars> #tag1 #tag2".\n- foresight_hint: ARRAY of predictions; [] when no deferred / recurring signal.'
        example_tail = '\nforesight_hint:\n  - {{"prediction": "User will revisit WebSocket leak fix after load test next week", "window": "5-7 days", "confidence": "medium", "src_ts": "2024-11-08 14:20"}}\n  - {{"prediction": "User runs every Saturday morning (recurring habit, 3+ observations)", "window": "recurring weekly", "confidence": "high", "src_ts": "2024-11-09 10:00"}}\n  - {{"prediction": "Q4 retrospective scheduled for next Friday", "window": "5 days", "confidence": "high", "src_ts": "2024-11-09 14:00"}}\n(Again: FORMAT examples from an unrelated domain. Produce predictions only for the conversation above.)\n'
        sys_line = "You are a conversation annotator. Call annotate_conversation exactly once with both slots filled (foresight_hint may be [])."
    else:
        slot_lines = (
            '- episode_summary: ARRAY of single-line entries "[YYYY-MM-DD HH:MM] <summary, <=100 chars> #tag1 #tag2".'
        )
        example_tail = ""
        sys_line = (
            "You are a conversation annotator. Call annotate_conversation exactly once with episode_summary filled."
        )
    recent_tags = self.recent_project_tags(days=14, limit=12)
    if recent_tags:
        tag_history_lines = "\n".join((f"  - #{tag} ({n}x in last 14 days)" for tag, n in recent_tags))
        tag_history_block = (
            "\n## Project tags you've recently used — REUSE these slugs when describing the same project; do NOT invent new variants:\n"
            + tag_history_lines
            + "\n"
        )
    else:
        tag_history_block = ""
    prompt = f"""Annotate this conversation chunk. Call annotate_conversation with:\n\n{slot_lines}\n\n## Critical rules\n\n1. **Each episode summary must include specific identifiers** — file\n   names, function names, PR numbers, percentages, durations. Avoid\n   vague verbs like "worked on" / "discussed" / "planned"; describe the\n   concrete artifact, decision, or finding.\n2. **Reuse project slugs across calls**. If a project slug already\n   exists in the "tags you've recently used" list below, use it\n   verbatim. Splitting one project into multiple slugs\n   (#project-clawtrack-release / -cli / -docs) destroys the tag-based\n   refresh trigger — pick ONE stable slug per project.\n3. **Tag the WORK, not the codebase**: `#project-<work-slug>` where the\n   slug names the topic. Use `#project-auth-refactor` not\n   `#project-backend-api`.\n4. **Process tags can't stand alone**. `#question`, `#habit`, `#answer`\n   describe HOW the user is talking, not WHAT about. Every episode\n   needs at least one CONTENT tag (a `#project-*` or one of {{#perf,\n   #bug, #decision, #blocker, #deferred, #pivot, #pr, #review, #rfc,\n   #design, #infra, #sql, #ml}}) IN ADDITION to any process tag.\n5. **Avoid the generic #task tag**.\n{tag_history_block}\n## Current Time\n{now_str}\n\n## Conversation to Annotate\n{self._format_messages(messages)}\n\n## Output shape example\nThe examples below are from an UNRELATED domain (websocket / DB / feature-flag work). They demonstrate the FORMAT only. DO NOT copy any of their text or topics — generate entries that describe the actual conversation above.\n\nepisode_summary:\n  - "[2024-11-08 14:20] Identified memory leak in WebSocketManager.broadcast(); ~200MB growth/hour under load #project-ws-stability #perf #bug"\n  - "[2024-11-09 10:00] Migrated user_sessions from MyISAM to InnoDB (~12M rows, 4h offline window) #project-db-migration #infra #decision"\n  - "[2024-11-11 16:30] Feature flag 'dark-mode-v2' ramped 10%->50% after 24h of steady metrics #project-feature-flag-rollout #pr #decision"\n{example_tail}"""
    try:
        response = await provider.chat_with_retry(
            messages=[{"role": "system", "content": sys_line}, {"role": "user", "content": prompt}],
            tools=_build_annotate_tool(enable_foresight=enable_foresight),
            model=model,
            tool_choice="required",
        )
        if not response.has_tool_calls:
            logger.warning("annotate: LLM did not call annotate_conversation")
            return False
        args = _normalize_save_memory_args(response.tool_calls[0].arguments)
        if args is None:
            logger.warning("annotate: unexpected tool arguments")
            return False
        episodes = args.get("episode_summary") or []
        if isinstance(episodes, str):
            episodes = [episodes]
        n_written = 0
        n_dropped_process_only = 0
        for ep in episodes:
            line = _ensure_text(ep).strip()
            if not line:
                continue
            if _is_process_only_episode(line):
                n_dropped_process_only += 1
                continue
            self.append_history(line)
            n_written += 1
        if n_dropped_process_only:
            logger.info("annotate: dropped {} process-only episode(s)", n_dropped_process_only)
        if enable_foresight:
            foresights = args.get("foresight_hint") or []
            if foresights:
                written = await asyncio.to_thread(self.append_foresight, foresights)
                logger.info(
                    "annotate: {} foresight hint(s) emitted → user.md ## Foresight ({} written, {} deduped/skipped)",
                    len(foresights),
                    written,
                    len(foresights) - written,
                )
        logger.info("annotate done for {} messages -> {} episode(s)", len(messages), n_written)
        return True
    except Exception:
        logger.exception("annotate failed")
        return False


async def refresh_section(self, tag: str, provider: LLMProvider, model: str, max_episodes: int = 50) -> bool:
    """Heavy Path：依据 ``tag`` 的 Recent Episodes 重写 ``user.md`` 中 **ONE H2 Section**。

    LLM 根据 Current Profile 与最多 `max_episodes` 条相关事件，选择 Existing Target H2，确无匹配时才
    Create One，并输出 ``{section_heading, section_body}``。Prompt 强制把 Profile 当 Current Snapshot
    而非 Diary，要求 UPDATE/CONSOLIDATE/REMOVE 优先于 APPEND，且每条 Bullet 带
    ``[src: episodes.md @ ts]`` Evidence Link。Splicer 只替换该 Section Body，其他 Sections 保持
    Byte-identical。

    无 Relevant Episodes 返回 `True` 且不调用模型；Tool Call/Args/Heading 无效或异常返回 `False`。
    缺 Citation Bullets 在边界丢弃，Concurrent Profile Modification 会由 CAS Skip。返回成功表示刷新
    流程接受，不等于 LLM 生成的 Profile Claim 已人工验证。
    """
    relevant = self._episodes_for_tag(tag, max_episodes)
    if not relevant:
        logger.debug("refresh_section({}): no matching episodes", tag)
        return True
    current_profile = self.read_long_term()
    now_str = self._now_fn().strftime("%Y-%m-%d %H:%M (%A)")
    episodes_block = "\n".join(relevant)
    prompt = f"""Update ONE H2 section of user.md based on the recent\n#{tag} episodes below. user.md is a PROFILE SNAPSHOT (current state per\ntopic), NOT an event log — episodes.md already keeps the event log.\n\n<principles>\n1. Explicit Evidence Required — only place a fact in user.md if you can\n   cite an episode timestamp. No speculation, no inference from titles.\n2. Quality Over Quantity — 5 accurate bullets > 15 noisy ones.\n   An empty section is OK.\n3. Inertia — existing bullets are correct unless a NEW episode\n   contradicts them. UPDATE bullets in place rather than rewrite.\n4. Reject Events — one-off events, emotional states ("anxiety",\n   "frustration"), and transient process work ("in middle of debugging X")\n   do NOT belong in user.md — they're already in episodes.md.\n5. Profile Snapshot, Not Diary — every bullet answers "what is true\n   about this user right now?", not "what happened on day X?".\n6. Abstraction, Not Enumeration — a profile bullet captures a PATTERN,\n   not a list of instances. When N episodes share a theme, write ONE\n   bullet describing the abstraction; do NOT comma-list the instances\n   inside the bullet.\n   ✓ "Spends commute/break time on child-related research"\n   ✗ "Researches English materials, breakfast recipes, sunscreen,\n      dental care, vaccines, parent-child games, homework, time\n      management"\n   The 9-item enumeration above defeats the snapshot — each instance\n   already lives in episodes.md; user.md only needs the theme.\n</principles>\n\n<section_schemas>\nEach H2 section follows a semi-structured convention. Use **Field**:\nprefix for required slots; bullets without prefix are ad-hoc additions.\n\n## Identity (≤ 5 bullets — stable role/personal facts)\n  - **Name**: ...\n  - **Role**: ...\n  - **Stack**: ...\n  - **Location**: ...\n  - **Key relations**: <name + role, e.g. "周晓棠 (girlfriend)">\n\n## Preferences (≤ 5 bullets — working style / tools / quiet hours)\n  - **Communication**: terse | verbose | mixed; emoji-friendly Y/N\n  - **Tools**: <comma-separated preferences>\n  - **Quiet hours**: <when not to interrupt>\n  - ad-hoc preference bullets allowed\n\n## Projects → ### <project-name> (each H3 has 4-6 bullets)\n  - **Type**: work | side project | learning | personal\n  - **Status**: <one-line current state>\n  - **Recent work**: <2-3 descriptive items, NOT per-day events>\n  - **Next**: <upcoming actions>\n  - Optional: **Stack**, **Stakeholders**, **Deadline**\n\n## Habits (≤ 6 bullets — recurring patterns, ≥ 2 observations to qualify)\n  - **<pattern>** (confirmed by N obs; freq: weekly | daily | sporadic)\n    Example: "Saturday morning run (confirmed by 4+ obs; freq: weekly)"\n\n## Notes (≤ 8 bullets — important specific facts)\n  - <birthday / deadline / preferred X / similar facts>\n\n## Foresight — AUTO-MANAGED by a different path. DO NOT TARGET; do NOT\nrewrite its contents.\n</section_schemas>\n\n<triage_each_episode>\nBefore deciding what to write, classify each new episode:\n\nKEEP (write into user.md) if it represents:\n  - identity / role / relationship fact → ## Identity\n  - working preference confirmed → ## Preferences\n  - project state change (status, deliverable, decision) → ## Projects\n  - recurring pattern with ≥ 2 observations → ## Habits\n  - dated commitment / deadline / specific fact → ## Notes\n\nREJECT (stays in episodes.md only, do NOT add to user.md) if it's:\n  - one-off event ("ran today", "had lunch", "PR merged" — the PR-merged\n    detail goes in episodes.md; the project's Status field captures the\n    end state, not the per-event)\n  - emotional state ("anxious", "frustrated", "excited")\n  - transient process ("in middle of debugging X", "testing Y")\n  - in-progress detail that resolves soon\n  - already covered by an existing bullet without new info\n  - just a question the user asked\n</triage_each_episode>\n\n<update_protocol>\nFor each episode that PASSES triage, follow this order STRICTLY:\n\n1. UPDATE first — find an existing bullet on the same subject; refine it\n   in place to reflect the latest evidence.\n   Example: existing "**Status**: pre-release testing"\n            + new "PR #1287 merged: v1.0 released"\n            → "**Status**: v1.0 released (5/15), gathering feedback"\n\n2. CONSOLIDATE second — merge related bullets in the same section.\n   Example: "**Recent work**: CLI bug" + new "doc generation broken"\n            → "**Recent work**: CLI bug + doc generation broken"\n\n   ANTI-PATTERN — DO NOT enumerate. When N episodes share a THEME but\n   each adds a different specific instance, do NOT comma-list every\n   instance inside the bullet.\n   Existing "Researches child topics" + new episode "researched vaccines":\n     ✗ bad:  "Researches child topics including English, breakfast,\n              vaccines, dental care, sunscreen, ..."\n     ✓ good: leave the bullet UNCHANGED — the theme is already captured;\n             the specific vaccine instance lives in episodes.md.\n   Apply this whenever you find yourself reaching for "including", "such\n   as", "e.g.", or a comma-list of nouns inside one bullet.\n\n3. REMOVE third — drop bullets obsoleted by new evidence.\n   Example: "**Status**: pre-release anxiety" → DROP once "released" lands.\n\n4. APPEND last — only if truly new topic AND under the section cap.\n\nAfter processing, respect section caps (see <section_schemas>).\nIf you'd exceed a cap, CONSOLIDATE harder.\n</update_protocol>\n\n## Current Time\n{now_str}\n\n## Current user.md (UPDATE/CONSOLIDATE/REJECT — don't just append)\n{current_profile or "(empty)"}\n\n## Recent episodes tagged #{tag} ({len(relevant)} entries — fold into\nthe matching section after triage)\n{episodes_block}\n\n## Output\nsection_heading: the H2 line you're updating (verbatim; for project\n   work use `## Projects` — the H3 sub-section goes inside section_body).\nsection_body: full new content for that H2, every bullet ending with\n   `[src: episodes.md @ <ts>]`. Use the LATEST relevant ts when merging.\n"""
    try:
        response = await provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You maintain a structured user profile in user.md, NOT an event log. Follow the <principles>, <section_schemas>, <triage_each_episode>, and <update_protocol> blocks in the user message. Prefer UPDATE over APPEND; respect per-section size caps; reject events / emotions / transient process work that already lives in episodes.md.",
                },
                {"role": "user", "content": prompt},
            ],
            tools=_REFRESH_SECTION_TOOL,
            model=model,
            tool_choice="required",
        )
        if not response.has_tool_calls:
            logger.warning("refresh_section({}): LLM did not call tool", tag)
            return False
        args = _normalize_save_memory_args(response.tool_calls[0].arguments)
        if args is None or "section_heading" not in args or "section_body" not in args:
            logger.warning("refresh_section({}): unexpected tool args", tag)
            return False
        heading = _ensure_text(args["section_heading"]).strip()
        body = _ensure_text(args["section_body"])
        if not heading.startswith("## "):
            logger.warning("refresh_section({}): bad heading {!r}", tag, heading)
            return False
        if heading != _FORESIGHT_HEADING:
            body, n_src_dropped = _drop_bullets_without_src(body)
            if n_src_dropped:
                logger.warning(
                    "refresh_section({}): dropped {} bullet(s) missing [src:] link in section {!r}",
                    tag,
                    n_src_dropped,
                    heading,
                )
        n_bullets = sum((1 for ln in body.splitlines() if ln.lstrip().startswith("-")))
        if n_bullets > 15:
            logger.warning(
                "refresh_section({}): LLM produced {} bullets (>15) for section {!r} — schema cap violated, profile may be diary-style. Check episodes.md / prompt drift.",
                tag,
                n_bullets,
                heading,
            )
        await asyncio.to_thread(self._splice_section_and_write, heading, body, current_profile)
        logger.info(
            "refresh_section({}): section {!r} updated using {} episode(s) -> {} bullets",
            tag,
            heading,
            len(relevant),
            n_bullets,
        )
        return True
    except Exception:
        logger.exception("refresh_section({}) failed", tag)
        return False


async def maybe_refresh_hot_tags(self, provider: LLMProvider, model: str, threshold: int = 5) -> int:
    """扫描 ``episodes.md``，刷新 New-episode Delta 达到 ``threshold`` 的 Tags。

    Refreshes 按 Hottest First Serial 执行，避免同一 ``user.md`` 上内部 Race。每个 Tag 只有
    `refresh_section` 成功后才推进 Offset；失败不推进，使下轮可 Retry。返回实际成功处理的 Section
    Count；Count 不表示生成了多少新事实，也不保证各 Tag 映射到不同 H2。
    """
    hot = self.hot_tags(threshold)
    if not hot:
        return 0
    offsets = self.read_tag_offsets()
    refreshed = 0
    for tag, current_count, _prev in hot:
        ok = await self.refresh_section(tag, provider, model)
        if ok:
            offsets[tag] = current_count
            self.write_tag_offsets(offsets)
            refreshed += 1
        else:
            logger.warning("maybe_refresh_hot_tags: tag {!r} refresh failed; offset not advanced", tag)
    return refreshed
