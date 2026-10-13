"""Anthropic-compatible 后端：``TRANSPORT_ANTHROPIC_COMPATIBLE`` 对应的 ``/messages`` 调用。

`AnthropicCompatibleModelClient` 把 prompt 包成 Messages API 的单轮用户消息，POST 到带 ``/v1``
的 Base URL，从返回的 ``content`` 块数组里挑出 text 块拼成回答，并把 ``stop_reason``、
内容块类型与 token 用量记进 `last_completion_metadata`。``thinking`` 参数原样透传，
用于 DeepSeek 这类必须显式关闭 provider-native thinking 的网关。

这里不接 prompt cache（`supports_prompt_cache` 恒为 ``False``，缓存参数在 `complete` 开头就被
丢弃），也不解析 SSE：本 transport 只按 JSON 读取响应，``stream`` 字段恒为 ``False``。
SSE 与 usage/cache 的统一口径属于 OpenAI-compatible 路径，把两套形状混在这里会让
「后端到底有没有复用缓存」变成无法判断的问题。鉴权只用 ``x-api-key``，不发 ``Authorization``。
"""

import json
import time
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from typing import Any

from pico.integrations.llm.requests import (
    ANTHROPIC_COMPATIBLE_BACKEND_LABEL,
    MAX_REQUEST_ATTEMPTS,
    backend_error_message,
    backend_unreachable_message,
    build_json_request,
    decode_error_body,
    http_failure_message,
    retry_delay_seconds,
)
from pico.integrations.llm.responses import (
    extract_anthropic_metadata,
    extract_anthropic_text,
    normalize_versioned_base_url,
)

#: 请求头里固定的 Messages API 版本；它属于协议事实，不随产品版本变化。
ANTHROPIC_VERSION = "2023-06-01"

#: 响应里没有任何 text 块时的报错正文里出现的固定前缀。
NO_TEXT_BLOCK_MESSAGE = "Anthropic-compatible response ended before a text block"


class AnthropicCompatibleModelClient:
    """向 Anthropic-compatible ``/messages`` 端点发起单轮补全的客户端。

    ``base_url`` 经 `normalize_versioned_base_url` 归一化后拼 ``/messages``；``api_key`` 无论真假
    都会写成 ``x-api-key`` 头，空值由后端拒绝而不是在本层省略，以免把配置缺失伪装成一次
    正常的 401。``temperature`` 为 ``None`` 时该字段整个不出现在请求体里。

    ``thinking`` 是 provider-native 思考开关（例如 ``{"type": "disabled"}``），构造时复制一份
    存起来：空值与 ``{}`` 都按「不发送该字段」处理，因此想显式关闭必须给出完整的类型对象。
    每次请求再复制一份进 payload，调用方事后修改传入的字典不会影响后续请求。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None,
        temperature: float | None,
        timeout: float,
        thinking: dict[str, Any] | None = None,
    ):
        self.model = model
        self.base_url = normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.thinking = dict(thinking) if thinking else None
        self.supports_prompt_cache = False
        self.last_completion_metadata: dict[str, Any] = {}

    def complete(
        self,
        prompt: str,
        max_new_tokens: int,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> str:
        """发起一次调用，返回拼接后的 text 块文本。

        ``max_new_tokens`` 落到 ``max_tokens``（该协议里它是必填硬上限，不是建议值）。
        ``prompt_cache_key`` 与 ``prompt_cache_retention`` 只为保持接口一致而接收，随即丢弃。

        非 2xx 中的 5xx 与网络错误各重试三次，其余状态码立即失败；``error`` 字段与非 JSON
        正文都转成 `RuntimeError`。当响应里没有任何 text 块时，报错消息带上 ``stop_reason``
        与内容块类型列表——「只想了一下就被 max_tokens 截断」和「后端返回了空数组」需要
        不同的修法，而这两个事实只有元数据能提供。元数据在抛错之前已经写入，
        所以调用失败那一轮 trace 仍然读得到 stop 原因。
        """
        # 为了保持统一接口，runtime 仍然会传缓存参数进来；
        # 这里只是显式丢弃，因为当前 Anthropic-compatible 路径没有接缓存复用。
        del prompt_cache_key, prompt_cache_retention
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.thinking is not None:
            payload["thinking"] = dict(self.thinking)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

        request = build_json_request(self.base_url + "/messages", payload, headers)
        attempts = MAX_REQUEST_ATTEMPTS
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = decode_error_body(exc)
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(retry_delay_seconds(attempt))
                    continue
                raise RuntimeError(http_failure_message(ANTHROPIC_COMPATIBLE_BACKEND_LABEL, exc.code, body)) from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                if attempt < attempts - 1:
                    time.sleep(retry_delay_seconds(attempt))
                    continue
                raise RuntimeError(
                    backend_unreachable_message(ANTHROPIC_COMPATIBLE_BACKEND_LABEL, self.base_url, self.model)
                ) from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                backend_error_message(
                    ANTHROPIC_COMPATIBLE_BACKEND_LABEL,
                    "backend returned non-JSON content that could not be parsed",
                )
            ) from exc
        if data.get("error"):
            raise RuntimeError(backend_error_message(ANTHROPIC_COMPATIBLE_BACKEND_LABEL, data["error"]))
        self.last_completion_metadata = extract_anthropic_metadata(data)
        text = extract_anthropic_text(data)
        if text:
            return text
        stop_reason = self.last_completion_metadata["stop_reason"] or "unknown"
        content_types = ",".join(self.last_completion_metadata["content_block_types"]) or "none"
        raise RuntimeError(f"{NO_TEXT_BLOCK_MESSAGE} (stop_reason={stop_reason}, content_types={content_types})")
