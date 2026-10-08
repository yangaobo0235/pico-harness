"""Pure parsing, validation and section formatting for persistent memory."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def _ensure_text(value: Any) -> str:
    """把 Tool-call Payload Value 规范为适合 File Storage 的 Text。

    已是字符串时原样返回，其他 JSON-compatible Value 使用 ``json.dumps(..., ensure_ascii=False)``，保留
    中文可读性。无法 JSON Serialize 的对象会抛错，由上层 Annotate Failure Path 捕获；函数不对内容做
    可信度验证或脱敏。
    """
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


_HISTORY_TS_RE = re.compile(r"^\s*\[(\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2})")


_HISTORY_TS_FORMATS = (
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
)


def _parse_history_paragraph_ts_ms(paragraph: str) -> int | None:
    """提取 HISTORY.md Paragraph 开头的 ``[YYYY-MM-DD HH:MM]`` Timestamp。

    同时接受日期与时间之间的 Space 或 ``T``，按 Local-time Interpretation 转成 Epoch Milliseconds。
    Paragraph 没有 Leading Stamp 或格式无法 Parse 时返回 `None`，不猜测文件 Mtime；调用方会丢弃无法
    可靠锚定时间的段落。
    """
    m = _HISTORY_TS_RE.match(paragraph)
    if not m:
        return None
    raw = m.group(1)
    for fmt in _HISTORY_TS_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return int(dt.timestamp() * 1000)
    return None


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    """把 Provider Tool-call Arguments 规范为预期 Dict Shape。

    String 先按 JSON 解析；List 只接受首项为 Dict 的形式；Dict 原样返回，其他结构返回 `None`。该兼容层
    覆盖不同 Provider 对 Function Arguments 的包装差异，不验证 Dict 内业务字段，后续调用点负责检查。
    """
    if isinstance(args, str):
        args = json.loads(args)
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    return args if isinstance(args, dict) else None


_EPISODE_LINE_RE = re.compile(r"^\s*\[(\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2})\]\s+(.*?)\s*$")


_TAG_RE = re.compile(r"#([a-z][a-z0-9-]*)")


def _parse_episode_line(line: str) -> tuple[str, str, list[str]] | None:
    """把 ``episodes.md`` Line 拆成 ``(timestamp, summary, tags)``。

    只接受 ``[YYYY-MM-DD HH:MM] <summary> #tag #tag`` Shape，Timestamp 也兼容 ``T`` Separator。返回的
    Summary 会移除所有 Tag Tokens，Tags 不含前导 ``#``。不匹配返回 `None`，让统计与 Refresh 跳过
    Freeform/Corrupt Line，而不是误归类。
    """
    m = _EPISODE_LINE_RE.match(line)
    if not m:
        return None
    ts, body = m.group(1), m.group(2)
    tags = _TAG_RE.findall(body)
    summary = _TAG_RE.sub("", body).strip()
    return ts, summary, tags


_PROCESS_TAGS: frozenset[str] = frozenset({"question", "habit", "answer"})


_VALID_CONFIDENCE: frozenset[str] = frozenset({"low", "medium", "high"})


_SRC_LINK_RE = re.compile(r"\[src:\s+episodes\.md\s+@\s+\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\]")


_FORESIGHT_DEDUP_STOPWORDS: frozenset[str] = frozenset(
    {
        "user",
        "will",
        "may",
        "might",
        "likely",
        "again",
        "today",
        "tomorrow",
        "next",
        "this",
        "that",
        "the",
        "for",
        "with",
        "from",
        "and",
        "are",
        "has",
        "have",
        "continue",
        "recurring",
        "pattern",
        "habit",
    }
)


_FORESIGHT_TOKEN_RE = re.compile(r"[a-zA-Z]{4,}|[一-鿿]{2,}")


_FORESIGHT_SEMANTIC_DUP_JACCARD: float = 0.6


def _stem_trailing_s(token: str) -> str:
    """执行 Cheap Plural→Singular：移除长度至少 5 且不以 ``ss`` 结尾 Token 的单个 Trailing ``s``。

    可把 ``reminders → reminder``、``meetings → meeting``、``mondays → monday`` 归一化，使 Jaccard
    捕获 Sibling-form Duplicates，而无需引入 Real Stemmer；对当前处理量，`nltk PorterStemmer` 过重。
    函数 **不** 修改 ``boss``、``class``、``-ing`` / ``-ed`` Forms。Occasional Missed Dedup 是相对
    Heavyweight Morphology + Extra Dependency 可接受的 Failure Mode。
    """
    if len(token) >= 5 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _is_process_only_episode(line: str) -> bool:
    """Episode 只有 ``#question`` / ``#habit`` / ``#answer`` Tags 时返回 `True`。

    Prompt 已声明这类 Episode **INVALID**，因为 Process Tags 必须搭配 Content Tag；但 30-day Scale 下 LLM
    仍约 5% 违规。本 Filter 在 Annotate-writeback Boundary 丢弃它们，使其不进入 ``episodes.md``，也不
    错误触发 `refresh_section`。

    Unparseable 或 Untagged Lines 返回 `False`，避免意外 Suppress 无关 Freeform Notes。该函数只判断 Tag
    Class，不评价 Summary 事实是否正确。
    """
    parsed = _parse_episode_line(line)
    if not parsed:
        return False
    _, _, tags = parsed
    if not tags:
        return False
    return {t.lower() for t in tags}.issubset(_PROCESS_TAGS)


def _normalize_confidence(value: str) -> str:
    """值属于 ``{low, medium, high}`` 时原样返回，否则返回 ``?``。

    LLM 偶尔输出 ``strong`` / ``likely`` / ``definite``，违背 Prompt-specified Enum。渲染成 ``?`` 让
    Deviation 在 ``user.md`` 中可见，而不是 Silently Persist Bad Value；函数不会猜测这些词对应哪个等级。
    """
    v = (value or "").strip().lower()
    return v if v in _VALID_CONFIDENCE else "?"


def _foresight_token_set(prediction: str) -> frozenset[str]:
    """把 Foresight Prediction Tokenize，供 Semantic-dedup Comparison。

    提取长度至少 4 的 English Words 与长度至少 2 的 CJK Runs，Lowercase 后移除 ``user will``、
    ``recurring habit`` 等不承载 Topic Content 的 High-frequency Framing Words。剩余 Token 再经
    `_stem_trailing_s`，使 ``reminders``/``reminder``、``meetings``/``meeting`` 等 Plural/Singular
    Siblings Collapse 到同一形式。返回 Frozen Set 只用于近似比较，不是语言学分词结果。
    """
    raw = _FORESIGHT_TOKEN_RE.findall(prediction.lower())
    return frozenset(_stem_trailing_s(t) for t in raw if t not in _FORESIGHT_DEDUP_STOPWORDS)


def _is_semantic_duplicate_foresight(
    new_pred: str,
    existing_preds: list[str],
) -> bool:
    """``new_pred`` 与任一 Existing Prediction 的 Content-token Jaccard 达到 Threshold 时返回 `True`。

    `append_foresight` 中 ``(prediction, src_ts)`` Dedup 只比较 Exact String，会放过同一 Semantic Claim 的
    Reworded Re-emissions，例如 ``User runs every Saturday morning`` 与追加 ``recurring habit`` 的版本。
    本 Jaccard Check 捕获这些改写。Empty Token Set 不判重复；阈值是近似 Trade-off，可能存在少量 False
    Positive/Negative。
    """
    new_tokens = _foresight_token_set(new_pred)
    if not new_tokens:
        return False
    for ex in existing_preds:
        ex_tokens = _foresight_token_set(ex)
        if not ex_tokens:
            continue
        union = new_tokens | ex_tokens
        jaccard = len(new_tokens & ex_tokens) / len(union)
        if jaccard >= _FORESIGHT_SEMANTIC_DUP_JACCARD:
            return True
    return False


def _drop_bullets_without_src(body: str) -> tuple[str, int]:
    """移除缺少 ``[src: episodes.md @ ts]`` Link 的 Profile Bullets。

    Non-bullet Lines，包括 Blank、Headings、Prose，Verbatim 保留。Prompt 要求每条 Profile Bullet 引用
    Source Episode Timestamp，因此没有 Evidence Link 的 Bullet 会在写回边界丢弃。

    Returns ``(cleaned_body, n_dropped)``。该检查验证 Citation Shape，不验证被引用 Episode 是否真的支持
    Claim；后者仍需人工或更强 Evidence Review。
    """
    kept: list[str] = []
    dropped = 0
    for line in body.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            kept.append(line)
            continue
        if _SRC_LINK_RE.search(line):
            kept.append(line)
        else:
            dropped += 1
    return "\n".join(kept), dropped


_FORESIGHT_HEADING = "## Foresight"


_FORESIGHT_BULLET_RE = re.compile(
    r"^-\s+(?P<prediction>.+?)\s+"
    r"\(from\s+(?P<gen_ts>[^,]+),\s+"
    r"window:\s+(?P<window>[^,]+),\s+"
    r"confidence:\s+(?P<confidence>[^,]+),\s+"
    r"src:\s+episodes\.md\s+@\s+(?P<src_ts>.+?)\)\s*$"
)


def _format_foresight_bullet(entry: dict[str, Any], generation_ts: str) -> str:
    """把 Foresight Dict 渲染成一条 ``user.md`` Bullet Line。

    Prediction、Window、Confidence、Source Timestamp 与 `generation_ts` 都进入固定单行格式。Missing/Blank
    Fields 用 ``?`` 替代，使 Partial LLM Output 仍能写成可人工 Review 的 Record；非法 Confidence 也经
    `_normalize_confidence` 显式标记，而不是伪造有效值。
    """
    pred = (entry.get("prediction") or "").strip() or "?"
    window = (entry.get("window") or "").strip() or "?"
    # 强制限定为 {low|medium|high}，枚举外的值渲染为 '?'。
    confidence = _normalize_confidence(entry.get("confidence") or "")
    src_ts = (entry.get("src_ts") or "").strip() or "?"
    return f"- {pred} (from {generation_ts}, window: {window}, confidence: {confidence}, src: episodes.md @ {src_ts})"


_RELEVANCE_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


def _tokenize_for_relevance(text: str) -> set[str]:
    """返回 Lowercased、长度至少 2 的 Alphanumeric/CJK Runs Set。

    这是 Proper Tokenization 的 Lightweight Stand-in：Chinese Run 会成为一个 Multi-char Token，例如三字
    Phrase 是 One Token；English 按 Whitespace + Punctuation 分割。它服务 Profile Section Lexical
    Relevance，不理解同义词、词形或语义。
    """
    return {t.lower() for t in _RELEVANCE_TOKEN_RE.findall(text)}


def _parse_user_md_sections(content: str) -> dict[str, str]:
    """把 ``content`` 中每个 H2 Section 解析为 ``{H2_heading_line: body}``。

    First H2 之前的 H1 Preamble 被 Drop；Body 是 Heading 后到 Next H2 或 EOF 之间的文本，移除首尾 Blank
    Lines。Dict Insertion Order 与 Source File 一致，供后续自然渲染。重复 H2 Heading 会由后出现者覆盖，
    当前格式约定要求 Heading 唯一。
    """
    lines = content.splitlines()
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip("\n")
            current = line.strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip("\n")
    return sections


def _score_section_relevance(query: str, heading: str, body: str) -> float:
    """计算 Lexical-overlap Relevance，即 Query Vocabulary 在 Heading/Body 中的重合量。

    Heading Hit 权重为 Body 的 3x，因为 Section Titles 短且 Intentional；例如询问 ``Projects`` 应可靠拉取
    ``## Projects``。空 Query Tokens 返回 0。分数只用于 Profile Section Selection，不是 Memory Fact 的
    真实性或任务相关性概率。
    """
    q_tokens = _tokenize_for_relevance(query)
    if not q_tokens:
        return 0.0
    heading_hits = len(q_tokens & _tokenize_for_relevance(heading))
    body_hits = len(q_tokens & _tokenize_for_relevance(body))
    return heading_hits * 3.0 + body_hits


def _splice_h2_section_at_end(content: str, heading: str, new_body: str) -> str:
    """类似 ``_splice_h2_section``，但保证 Named Section 位于 File **End**。

    Section 不存在时像 Fallback Path 一样 Append；已在任意位置存在时，先移除原 Section Range，再用
    `new_body` 追加到末尾。H1 Preamble 与其他 H2 顺序保持不变。

    `append_foresight` 用它让 Auto-managed ``## Foresight`` Pillar 始终位于 ``user.md`` 底部，不受
    `refresh_section` 后续追加 ``## Projects`` / ``## Habits`` 等影响。
    """
    lines = content.splitlines()
    target = heading.strip()

    h_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == target:
            h_idx = i
            break

    if h_idx is not None:
        # 查找下一个 H2 边界或 EOF，以确定当前分节范围。
        next_h2 = None
        for i in range(h_idx + 1, len(lines)):
            if lines[i].startswith("## "):
                next_h2 = i
                break
        if next_h2 is not None:
            lines = lines[:h_idx] + lines[next_h2:]
        else:
            lines = lines[:h_idx]

    content_without = "\n".join(lines).rstrip("\n")
    body = new_body.strip("\n")
    if not content_without:
        return f"{target}\n\n{body}\n"
    return f"{content_without}\n\n{target}\n\n{body}\n"


def _ensure_foresight_at_end(content: str) -> str:
    """``## Foresight`` 存在但不是 Last H2 时，把它移动到末尾。

    操作 Idempotent：Foresight Absent 或 Already Last 时原样返回 `content`。`refresh_section` Writer 在任何
    Non-Foresight H2 Splice 后调用，使 Auto-managed Pillar 不会被新 Append 的 ``## Projects`` /
    ``## Habits`` 视觉掩埋。移动只改变 Section Position，不改写其 Body。
    """
    sections = _parse_user_md_sections(content)
    if _FORESIGHT_HEADING not in sections:
        return content
    h2_order = list(sections.keys())
    if h2_order[-1] == _FORESIGHT_HEADING:
        return content
    body = sections[_FORESIGHT_HEADING]
    return _splice_h2_section_at_end(content, _FORESIGHT_HEADING, body)


def _splice_h2_section(content: str, heading: str, new_body: str) -> str:
    """复制 ``content``，并把 ``heading`` 标识的 H2 Body 替换成 ``new_body``。

    Body 范围从 Heading 下一行到 Next H2 之前；若它是 Last H2 则到 EOF。H1 Preamble 与其他 H2 Sections
    Byte-for-byte 保留。Heading 不存在时，把 ``heading`` + ``new_body`` 作为 Fresh Section Append 到文件
    末尾。函数只处理 Exact H2 Line，不把 ``###`` 等更深 Heading 当边界。
    """
    lines = content.splitlines()
    target = heading.strip()

    h_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == target:
            h_idx = i
            break

    if h_idx is None:
        sep = "\n\n" if content and not content.endswith("\n\n") else ""
        return content.rstrip("\n") + sep + "\n" + target + "\n\n" + new_body.strip("\n") + "\n"

    # 查找下一个 H2：以 "## " 开头、但不是 "### " 等更深层级的行。
    next_h2 = None
    for i in range(h_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            next_h2 = i
            break

    before = lines[: h_idx + 1]
    after = lines[next_h2:] if next_h2 is not None else []
    body_lines = new_body.strip("\n").splitlines()

    pieces = list(before) + [""] + body_lines + [""]
    if after:
        pieces.extend(after)
    return "\n".join(pieces).rstrip("\n") + "\n"
