"""Agent streaming with explicit ownership of execution state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pico.integrations.llm.contracts import ErrorClassification, LLMResponse, ToolCallRequest
from pico.observability.tracing import semconv, trace

if TYPE_CHECKING:
    pass


@trace.instrument("llm.call", extract=semconv.llm_call_stream)
async def call_model_stream(
    self,
    messages: list[dict],
    tools: list[dict] | None,
    model: str | None,
    on_token_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
) -> LLMResponse:
    """通过 ``provider.chat_stream`` 接收增量，并重组为完整 `LLMResponse`。

    按 design.md §D3，Turn 调用方连接 ``on_token_delta`` 或推理回调时，AgentLoop 会走
    本方法而不是 ``chat_with_retry``。每个非空内容片段立即触发对应回调，同时累积文本、
    reasoning、usage、finish reason、模型和错误分类；Tool call 片段交给
    `_merge_tool_call_fragments` 按 ``index`` 汇合，最终对象与普通 ``chat()`` 返回形状兼容。

    v0.1 first-cut 合并边界仍然保留：同一位置只表示一个 Tool call，片段按顺序抵达，
    ``id`` / ``function.name`` 通常在该位置首片段出现，``function.arguments`` 由各片段
    JSON 字符串直接连接。Multi-tool 的 index 已区分，但更一般的 out-of-order 修复仍是
    v0.2 ask，不能把当前实现解释成任意乱序协议重组器。

    v0.1 stream mode 对临时错误不重试。已经向用户流出部分内容后，重头调用会重复输出，
    从 offset 恢复又依赖具体 Provider；在没有明确协议前选择传播错误，而不是制造看似
    完整但重复的回复。
    """
    content_buf: list[str] = []
    reasoning_buf: list[str] = []
    tool_call_slots: list[dict[str, Any]] = []
    final_usage: dict[str, Any] | None = None
    final_finish_reason: str | None = None
    final_error_classification: ErrorClassification | None = None
    actual_model: str | None = None
    cache_policy: str | None = None
    call_record = None

    async for delta in self.provider.chat_stream(
        messages=messages,
        tools=tools,
        model=model,
    ):
        delta_finish_reason = getattr(delta, "finish_reason", None)
        if delta_finish_reason is not None:
            final_finish_reason = delta_finish_reason
        delta_error_classification = getattr(delta, "error_classification", None)
        if delta_error_classification is not None:
            final_error_classification = delta_error_classification
        delta_model = getattr(delta, "model", None)
        if delta_model:
            actual_model = delta_model
        delta_cache_policy = getattr(delta, "cache_policy", None)
        if delta_cache_policy:
            cache_policy = delta_cache_policy
        delta_call_record = getattr(delta, "call_record", None)
        if delta_call_record is not None:
            call_record = delta_call_record
        is_error_delta = delta_finish_reason == "error"
        reasoning_delta = getattr(delta, "reasoning_content", None)
        if reasoning_delta:
            reasoning_buf.append(reasoning_delta)
            if on_reasoning_delta is not None and not is_error_delta:
                await on_reasoning_delta(reasoning_delta)
        if delta.content:
            content_buf.append(delta.content)
            if on_token_delta is not None and not is_error_delta:
                await on_token_delta(delta.content)
        if delta.tool_call_delta:
            _merge_tool_call_fragments(
                tool_call_slots,
                delta.tool_call_delta,
            )
        if delta.usage is not None:
            final_usage = delta.usage

    tool_calls = _finalize_tool_calls(tool_call_slots)
    finish_reason = final_finish_reason or ("tool_calls" if tool_calls else "stop")

    return LLMResponse(
        content="".join(content_buf),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=final_usage or {},
        reasoning_content="".join(reasoning_buf) or None,
        error_classification=final_error_classification,
        model=actual_model or model,
        cache_policy=cache_policy,
        call_record=call_record,
    )


def _merge_tool_call_fragments(
    slots: list[dict[str, Any]],
    delta: dict[str, Any],
) -> None:
    """把一次 chat_stream ``tool_call_delta`` 合并进按位置保存的累积槽。

    每个 slot 使用 ``{id, function: {name, arguments_buf: [str]}}`` 形状。按照
    OpenAI/LiteLLM Provider chunk 语义，片段携带 ``index``；对应 ``id`` 与
    ``function.name`` 通常只在该 index 的首片段出现，``function.arguments`` 则是分段到达的
    JSON string。方法只在槽中尚无 id/name 时写入它们，并按抵达顺序追加参数片段。

    ``index`` 决定扩展和选择哪个 slot，因此并行 multi-tool stream 不会全部塌缩进
    ``slots[0]``。缺少 ``index`` 时默认为 0，以兼容 single-tool case。delta 没有 Tool call
    时直接返回；本函数只累积，不解析最终 JSON，也不构造 `ToolCallRequest`。
    """
    incoming = delta.get("tool_calls") or []
    if not incoming:
        return
    for tc in incoming:
        idx = int(tc.get("index", 0) or 0)
        while len(slots) <= idx:
            slots.append({"id": None, "function": {"name": None, "arguments_buf": []}})
        slot = slots[idx]
        if tc.get("id") and not slot["id"]:
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name") and not slot["function"]["name"]:
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments_buf"].append(fn["arguments"])


def _finalize_tool_calls(slots: list[dict[str, Any]]) -> list[ToolCallRequest]:
    """把流式累积槽转换为可交给执行器的 `ToolCallRequest` 列表。

    没有 ``function.name`` 的不完整槽会被跳过。其余槽按原顺序连接
    ``arguments_buf``，非空时尝试作为 JSON 解析，空参数得到空字典；JSON 不完整或非法时不
    丢弃调用，而以 ``{"_raw_arguments": args_text}`` 保存原始文本，交由后续参数校验给出
    可解释失败。缺失 id 使用空字符串。返回值只完成协议形状归一化，不执行 Tool。
    """
    result: list[ToolCallRequest] = []
    for slot in slots:
        name = slot["function"]["name"]
        if not name:
            continue
        args_text = "".join(slot["function"]["arguments_buf"])
        try:
            args = json.loads(args_text) if args_text else {}
        except json.JSONDecodeError:
            args = {"_raw_arguments": args_text}
        result.append(
            ToolCallRequest(
                id=slot["id"] or "",
                name=name,
                arguments=args,
            )
        )
    return result
