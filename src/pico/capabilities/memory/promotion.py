"""决定哪些结论值得从本轮沉淀成长期记忆。

工作记忆随会话走，长期记忆跨会话留存，因此写入必须比记录更保守。本模块只接受两种信号：
用户在这一轮明确要求“记住/保存/沉淀”，并且模型在最终答案里用了约定的前缀行
（``Project convention:`` / ``决策：`` 等）。两条同时成立才产生一次晋升建议。

晋升仍然要过一遍拒绝理由：含密钥形态的文本、属于当前任务现场的临时状态（目标、卡点、下一步）、
以及带 stdout/stderr/traceback 或过长噪声的内容都不会进入长期记忆。真正落盘由
`pico.capabilities.memory.service.LayeredMemory.promote_durable` 完成，这里不写文件，也不判断
主题之间如何合并。
"""

import re
from typing import Any

from pico.security.redaction import REDACTED_VALUE

#: 用户显式表达“要长期保留”的意图词，中英文各一套。
MEMORY_INTENT_PATTERN = re.compile(r"(?i)\b(capture|remember|save|store|persist|note)\b")
MEMORY_INTENT_ZH_PATTERN = re.compile(r"(记住|保存|记录|沉淀|长期记忆|持久记忆)")

#: 最终答案里可被晋升的行前缀，映射到对应的长期主题。
PROMOTION_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("project-conventions", re.compile(r"(?i)^Project convention:\s*(.+)$")),
    ("key-decisions", re.compile(r"(?i)^Decision:\s*(.+)$")),
    ("dependency-facts", re.compile(r"(?i)^Dependency:\s*(.+)$")),
    ("user-preferences", re.compile(r"(?i)^Preference:\s*(.+)$")),
    ("project-conventions", re.compile(r"^项目约定：\s*(.+)$")),
    ("key-decisions", re.compile(r"^决策：\s*(.+)$")),
    ("dependency-facts", re.compile(r"^依赖：\s*(.+)$")),
    ("user-preferences", re.compile(r"^偏好：\s*(.+)$")),
)

#: 看起来像密钥的文本形态，命中即拒绝晋升。
SECRET_SHAPED_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")

#: 属于“当前任务现场”而不是长期事实的行前缀。
TRANSIENT_PREFIXES = (
    "current goal",
    "current blocker",
    "next step",
    "current phase",
    "key files",
    "freshness",
    "当前目标",
    "当前卡点",
    "下一步",
    "当前阶段",
    "关键文件",
    "已完成",
    "已排除",
)

#: 噪声判定的输出标记与长度阈值。
NOISY_OUTPUT_PATTERN = re.compile(r"(?i)\b(stdout|stderr|traceback|exit_code)\b")
MAX_PROMOTED_NOTE_CHARS = 220

REASON_EMPTY = "empty"
REASON_SECRET_SHAPED = "secret_shaped"
REASON_TRANSIENT_TASK_STATE = "transient_task_state"
REASON_NOISY_OUTPUT = "noisy_output"


def reject_reason(note_text: str) -> str:
    """返回一条候选笔记不应晋升的原因，可以晋升时返回空串。

    四种原因按“先安全、后噪声”的顺序检查：先看是否含占位符或密钥形态，再看是否只是当前任务
    的临时状态，最后看是否夹带命令输出或超过 `MAX_PROMOTED_NOTE_CHARS`。检查是文本级别的启发
    判断，宁可漏掉一条有用的事实，也不把一次性的现场写进长期记忆。
    """
    text = str(note_text or "").strip()
    lowered = text.lower()
    if not text:
        return REASON_EMPTY
    if REDACTED_VALUE in text or SECRET_SHAPED_TEXT_PATTERN.search(text):
        return REASON_SECRET_SHAPED
    if any(lowered.startswith(prefix) for prefix in TRANSIENT_PREFIXES):
        return REASON_TRANSIENT_TASK_STATE
    if NOISY_OUTPUT_PATTERN.search(text) or len(text) > MAX_PROMOTED_NOTE_CHARS:
        return REASON_NOISY_OUTPUT
    return ""


def extract_promotions(user_message: str, final_answer: str) -> tuple[list[tuple[str, str]], list[str]]:
    """从最终答案里抽取可晋升的 ``(主题, 文本)`` 列表与被拒绝原因列表。

    先看用户这一轮是否表达了保留意图；没有表达时直接返回两个空列表，即使答案里出现了约定前缀
    ——晋升是用户请求的结果，不是模型自发的行为。命中前缀的行按第一个匹配的主题归类，同一条
    行只归属一次。

    拒绝记录形如 ``主题:原因``，调用方把它写进报告，用来解释“模型确实给出了候选，但平台没有
    收下”的情况。
    """
    user_text = str(user_message or "")
    if not (MEMORY_INTENT_PATTERN.search(user_text) or MEMORY_INTENT_ZH_PATTERN.search(user_text)):
        return [], []
    promotions: list[tuple[str, str]] = []
    rejections: list[str] = []
    for line in str(final_answer or "").splitlines():
        text = line.strip()
        if not text or REDACTED_VALUE in text:
            continue
        for topic, pattern in PROMOTION_LINE_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue
            note_text = match.group(1).strip()
            if note_text:
                reason = reject_reason(note_text)
                if reason:
                    rejections.append(f"{topic}:{reason}")
                    break
                promotions.append((topic, note_text))
            break
    return promotions, rejections


def promote(agent: Any, user_message: str, final_answer: str) -> tuple[list[Any], list[str], list[Any]]:
    """抽取晋升建议、写入长期记忆，并返回 ``(晋升, 拒绝, 被取代)``。

    会话里的记忆状态在写入后同步回 ``session["memory"]``，因此同一次运行内的后续 Prompt 就能
    读到刚刚沉淀的事实。三个结果都会进入报告，作为“这次运行改动了哪些长期记忆”的记录。
    """
    promotions, rejections = extract_promotions(user_message, final_answer)
    promoted, superseded = agent.memory.promote_durable(promotions)
    agent.session["memory"] = agent.memory.to_dict()
    return promoted, rejections, superseded
