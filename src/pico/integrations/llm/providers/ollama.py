"""本地 Ollama 后端：`TRANSPORT_OLLAMA` 对应的 ``/api/generate`` 单次调用。

`OllamaModelClient` 把 prompt 拼成 Ollama 自己的补全请求（``stream``/``raw``/``think`` 全关，
采样参数放进 ``options``），一次 POST 拿回 ``response`` 字段。它是这一层里唯一不接
prompt cache 的远端后端：`supports_prompt_cache` 恒为 ``False``，`last_completion_metadata`
每次调用都重置成空字典，因此 runtime 传下来的缓存参数被忽略。

这里只处理 Ollama 这一种 transport，不判断该用哪个后端（`pico.config.providers` 的
`ProviderProfile` 决定，装配在 `pico.bootstrap.providers`）。刻意不重试、也不接
`http.client.RemoteDisconnected`：本地进程没起来是这条链路最常见的故障，快速失败并给出
``ollama serve`` 提示比退避三次更有用；把连接重置伪装成网络错误也会掩盖真实原因。
"""

import json
import urllib.error
import urllib.request
from typing import Any

from pico.integrations.llm.requests import (
    OLLAMA_BACKEND_LABEL,
    backend_error_message,
    build_json_request,
    decode_error_body,
    http_failure_message,
)


class OllamaModelClient:
    """向本机 Ollama 服务发起一次补全请求的客户端。

    ``model`` 是 Ollama 的本地模型标签（形如 ``qwen3.5:4b``）；``host`` 是服务地址，
    构造时 ``rstrip("/")``，因此传 ``http://127.0.0.1:11434/`` 与不带斜杠等价，端点固定在
    ``/api/generate``。``temperature``、``top_p`` 与 ``timeout`` 都是必填：本客户端不预设默认值，
    避免适配层悄悄替用户决定采样强度或等待时长。

    所有参数在构造时定型，`complete` 不改变它们；一次调用的失败以 `RuntimeError` 抛出，
    消息里带上原始 HTTP 状态或服务不可达时的 host 与 model。
    """

    def __init__(self, model: str, host: str, temperature: float, top_p: float, timeout: float):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.last_completion_metadata: dict[str, Any] = {}

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: Any) -> str:
        """发一次 ``/api/generate`` 请求，返回响应里的 ``response`` 字段。

        输入是整段 prompt 与输出预算；``max_new_tokens`` 落到 ``options.num_predict``，
        是否真的被后端遵守由服务决定。``**kwargs`` 里的 ``prompt_cache_key`` 与
        ``prompt_cache_retention`` 被忽略（见类文档说明）。响应里带非空 ``error`` 字段时抛
        `RuntimeError`，这是 Ollama 在 200 之后仍然失败的少数情况；``response`` 缺失时返回
        空串而不是报错，保持与既有上层解析行为的兼容。JSON 解析失败按原样抛出，
        本地服务的畸形响应不该被伪装成一次空回答。
        """
        # Ollama 当前不支持我们这里接入的 prompt cache 语义，
        # 所以 runtime 传下来的缓存参数会被忽略。
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "raw": False,
            "think": False,
            "options": {
                "num_predict": max_new_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        request = build_json_request(self.host + "/api/generate", payload, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = decode_error_body(exc)
            raise RuntimeError(http_failure_message(OLLAMA_BACKEND_LABEL, exc.code, body)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not reach Ollama.\n"
                "Make sure `ollama serve` is running and the model is available.\n"
                f"Host: {self.host}\n"
                f"Model: {self.model}"
            ) from exc

        if data.get("error"):
            raise RuntimeError(backend_error_message(OLLAMA_BACKEND_LABEL, data["error"]))
        return data.get("response", "")
