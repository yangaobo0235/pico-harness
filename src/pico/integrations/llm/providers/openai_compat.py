"""OpenAI-compatible 后端：``TRANSPORT_OPENAI_COMPATIBLE`` 对应的 ``/responses`` 调用。

`OpenAICompatibleModelClient` 把 prompt 包成 Responses API 的单轮输入，POST 到带 ``/v1`` 的
Base URL，并同时接住两种返回形状：普通 JSON 与 SSE 事件流。它是稳定前缀缓存真正落到
provider API 的地方——只有 `supports_prompt_cache` 为真时才把 ``prompt_cache_key`` 与
``prompt_cache_retention`` 写进请求体，并把这次调用的 usage 与 cache 事实写进
`last_completion_metadata`。

这里只认 OpenAI 一家的报文形状：Anthropic-compatible 与 Ollama 在同目录另有实现，选哪个由
`pico.config.providers` 的 `ProviderProfile.transport` 决定、由 `pico.bootstrap.providers` 装配。
本模块也不解释模型文本的协议含义（``<final>``、工具调用等），文本原样返回给 runtime。
5xx 与网络错误各重试三次，其余状态码立即失败：兼容网关的 4xx 多是配置问题，重试只是拖长
一次必然失败的交互。
"""

import json
import time
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from typing import Any

from pico.integrations.llm.requests import (
    MAX_REQUEST_ATTEMPTS,
    OPENAI_COMPATIBLE_BACKEND_LABEL,
    OPENAI_COMPATIBLE_USER_AGENT,
    backend_error_message,
    backend_unreachable_message,
    build_json_request,
    decode_error_body,
    http_failure_message,
    retry_delay_seconds,
)
from pico.integrations.llm.responses import (
    extract_openai_text,
    extract_usage_cache_details,
    normalize_versioned_base_url,
)
from pico.integrations.llm.sse import extract_openai_response_from_sse

#: 已确认实现 prompt cache 语义的宿主标记；其余兼容网关一律不发缓存参数，
#: 免得传一个「看起来统一、其实没意义」的伪字段。
PROMPT_CACHE_HOST_MARKERS = ("openai.com", "right.codes")


class OpenAICompatibleModelClient:
    """向 OpenAI-compatible ``/responses`` 端点发起单轮补全的客户端。

    ``base_url`` 经 `normalize_versioned_base_url` 归一化，末尾总是带 ``/v1``，请求再拼上
    ``/responses``；``api_key`` 为空时不发 ``Authorization``（本地网关常常无需鉴权）。
    ``temperature`` 为 ``None`` 时该字段整个不出现在请求体里，而不是写成 0——这两件事在
    后端语义上完全不同。``timeout`` 是单次尝试的等待上限，重试预算见模块说明。

    `supports_prompt_cache` 在构造时按 Base URL 判定一次并固定下来：判定依据只是宿主名，
    自建代理若不在 `PROMPT_CACHE_HOST_MARKERS` 里就不会启用缓存，这是有意的保守默认。
    """

    def __init__(self, model: str, base_url: str, api_key: str | None, temperature: float | None, timeout: float):
        self.model = model
        self.base_url = normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        # 当前只在明确支持 prompt cache 语义的后端上启用这条链路，
        # 避免对不支持的后端传一个“看起来统一、其实没意义”的伪参数。
        self.supports_prompt_cache = any(host in self.base_url for host in PROMPT_CACHE_HOST_MARKERS)
        self.last_completion_metadata: dict[str, Any] = {}

    def complete(
        self,
        prompt: str,
        max_new_tokens: int,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> str:
        """发起一次调用，返回模型文本，并把 usage 与 cache 事实记进 `last_completion_metadata`。

        输入是完整 prompt、``max_new_tokens``（落到 ``max_output_tokens``）与两个可选缓存参数；
        只有 `supports_prompt_cache` 为真且参数非空时才写进请求体。runtime 传下来的
        ``prompt_cache_key`` 是「稳定前缀」的签名而不是整段 prompt 的签名，因此动态 history
        每轮变化不会让缓存失效。

        返回前按响应形状分两条路：事件流走 `extract_openai_response_from_sse`，抽不到文本就抛
        ``could not extract text from event stream response``；JSON 走 `extract_openai_text`，
        非 JSON 内容或响应体带 ``error`` 字段都抛 `RuntimeError`。元数据在两条路上的写入时机
        不同：JSON 分支总是写（后端没报 usage 时字段为 ``None``），SSE 分支只有拿到非空响应
        对象才写，否则保留调用开始时的空字典——半截流里没有可信的 token 数，宁可留空也不
        编一个 0。
        """
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "max_output_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        # runtime 传入的是“稳定前缀”的签名，而不是整段 prompt 的签名。
        # 这样缓存复用针对的是稳定段，不会因为动态 history 每轮变化而失效。
        if self.supports_prompt_cache and prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if self.supports_prompt_cache and prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": OPENAI_COMPATIBLE_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = build_json_request(self.base_url + "/responses", payload, headers)
        attempts = MAX_REQUEST_ATTEMPTS
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                    response_headers = getattr(response, "headers", {}) or {}
                    content_type = response_headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as exc:
                body = decode_error_body(exc)
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(retry_delay_seconds(attempt))
                    continue
                raise RuntimeError(http_failure_message(OPENAI_COMPATIBLE_BACKEND_LABEL, exc.code, body)) from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                if attempt < attempts - 1:
                    time.sleep(retry_delay_seconds(attempt))
                    continue
                raise RuntimeError(
                    backend_unreachable_message(OPENAI_COMPATIBLE_BACKEND_LABEL, self.base_url, self.model)
                ) from exc

        # 有些兼容后端返回普通 JSON，有些返回 SSE。
        # 这里两种都接住，并尽量统一抽取文本和 usage/cache 元数据。
        # 判断同时看 Content-Type 与正文首行：部分网关用 JSON 头发送事件流，只靠前者会漏。
        if content_type.startswith("text/event-stream") or body_text.lstrip().startswith("data:"):
            text, response_data = extract_openai_response_from_sse(body_text)
            if isinstance(response_data, dict) and response_data:
                # 这些元数据会一路传回 runtime，进入 trace 和 report，
                # 用来观察 prompt cache 是否真的命中。
                self.last_completion_metadata = {
                    "prompt_cache_supported": self.supports_prompt_cache,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    **extract_usage_cache_details(response_data),
                }
            if text:
                return text
            raise RuntimeError(
                backend_error_message(
                    OPENAI_COMPATIBLE_BACKEND_LABEL,
                    "could not extract text from event stream response",
                )
            )

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                backend_error_message(
                    OPENAI_COMPATIBLE_BACKEND_LABEL,
                    "backend returned non-JSON content that could not be parsed",
                )
            ) from exc
        if data.get("error"):
            raise RuntimeError(backend_error_message(OPENAI_COMPATIBLE_BACKEND_LABEL, data["error"]))
        self.last_completion_metadata = {
            "prompt_cache_supported": self.supports_prompt_cache,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            **extract_usage_cache_details(data),
        }
        return extract_openai_text(data)
