"""Messages operations."""

from typing import Any


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """构造 Provider-safe Assistant Message，并按需加入 Reasoning Fields。

    基础结构始终包含 ``role="assistant"`` 与 `content`。非空 `tool_calls`、非 `None` 的
    `reasoning_content`、非空 `thinking_blocks` 才会进入结果，避免向不需要的 Provider 发送空协议
    字段。函数不验证 Tool Call Schema，也不隐藏 Reasoning；调用方仍负责遵守目标 Provider 的数据
    边界。
    """
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg
