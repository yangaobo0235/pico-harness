"""Tokenization operations."""

import json
from typing import Any

import tiktoken


def _message_token_parts(message: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        parts.append(reasoning)
    if message.get("thinking_blocks"):
        parts.append(json.dumps(message["thinking_blocks"], ensure_ascii=False))
    return parts


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """使用 Tiktoken 估算完整 Prompt Tokens。

    函数收集 Messages 中 Text、Tool Calls、Reasoning、Thinking Blocks 与 Tools Schema，序列化后用
    ``cl100k_base`` 编码。空 Payload 返回 0；Tiktoken 失败时按每 4 Characters 约一个 Token 回退，
    非空输入至少返回 1。结果适合预算门禁的近似值，不是任意模型的 Provider-billed Exact Usage。
    """
    parts: list[str] = []
    for msg in messages:
        parts.extend(_message_token_parts(msg))

    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False))

    payload = "\n".join(parts)
    if not payload:
        return 0
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(payload)))
    except Exception:
        return max(1, len(payload) // 4)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """估算一条 Persisted Message 对 Prompt 贡献的 Tokens。

    使用与完整 Prompt 相同的字段提取与 ``cl100k_base`` 编码，异常时按字符数回退。即使 Message 没有
    可计数 Payload 也返回 1，给结构开销保留最低预算；该数值用于裁剪近似，不等于 Provider 对单条
    消息的独立账单。
    """
    payload = "\n".join(_message_token_parts(message))
    if not payload:
        return 1
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(payload)))
    except Exception:
        return max(1, len(payload) // 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """先使用 Provider Counter 估算 Prompt Tokens，再回退到 Tiktoken。

    如果 Provider 暴露 Callable `estimate_prompt_tokens` 且返回正数，结果为 ``(tokens, source)``；
    Counter 异常或无效值不会阻断调用。随后使用本地 `estimate_prompt_tokens`，成功时 Source 为
    ``tiktoken``，仍无结果才返回 ``(0, "none")``。Source 让上层区分估算证据来源，而不是只看到一个
    无上下文数字。
    """
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass

    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return estimated, "tiktoken"
    return 0, "none"
