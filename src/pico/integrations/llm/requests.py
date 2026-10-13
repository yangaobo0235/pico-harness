"""模型后端 HTTP 请求的公共件：把 payload 装成一次可重放的 POST。

`build_json_request` 统一负责 URL、UTF-8 JSON body 与 header 的组装；`http_failure_message`、
`backend_error_message`、`backend_unreachable_message` 固定三类后端在「非 2xx」「响应体带
``error`` 字段」「连不上」时的报错措辞，让同一件事在不同 provider 里长同一个样子；
`MAX_REQUEST_ATTEMPTS` 与 `retry_delay_seconds` 把重试预算集中到一处，便于审计一次模型调用
最多会退避多久。User-Agent 直接引用 `pico.config.identity.USER_AGENT`，避免产品在 HTTP 层写
第二个版本号。

这里不发请求、也不决定重试控制流：`urllib.request.urlopen` 的调用点、状态码分支和
`sleep` 顺序留在各 provider client 里。原因是它们的边界并不一样——Ollama 单次尝试、只把
`urllib.error.URLError` 当网络错误，而两个 compatible 网关重试三次并额外接住
`http.client.RemoteDisconnected`。把这段差异抽成开关会藏掉协议事实，反而更容易被误改。
"""

import json
import urllib.error
import urllib.request
from typing import Any

from pico.config.identity import USER_AGENT

#: OpenAI-compatible 请求的 User-Agent；值来自产品身份，两处永远同步。
OPENAI_COMPATIBLE_USER_AGENT = USER_AGENT

OLLAMA_BACKEND_LABEL = "Ollama"
OPENAI_COMPATIBLE_BACKEND_LABEL = "OpenAI-compatible"
ANTHROPIC_COMPATIBLE_BACKEND_LABEL = "Anthropic-compatible"

#: 远端 5xx 与网络错误时的总尝试次数（含首次），只在两个 compatible 网关上使用。
MAX_REQUEST_ATTEMPTS = 3
#: 线性退避的时间单位：第 n 次失败后等待 ``RETRY_BACKOFF_UNIT_S * (n + 1)`` 秒。
RETRY_BACKOFF_UNIT_S = 0.5


def json_encode_body(payload: dict[str, Any]) -> bytes:
    """把 ``payload`` 序列化成 UTF-8 JSON 字节串，作为 POST 的请求体。

    ``json.dumps`` 保持字典插入顺序，因此 payload 的字段顺序就是线上看到的顺序；无法序列化的
    值直接抛 `TypeError`，让装配现场暴露问题，而不是在 HTTP 层悄悄丢掉一个字段。
    """
    return json.dumps(payload).encode("utf-8")


def build_json_request(url: str, payload: dict[str, Any], headers: dict[str, str]) -> urllib.request.Request:
    """把 ``payload`` 序列化成 UTF-8 JSON，组成发往 ``url`` 的 POST 请求。

    ``headers`` 原样交给 `urllib.request.Request`，各 provider 自己决定要不要带
    ``Authorization`` 或 ``x-api-key``；这里不校验必填 header，也不补默认值，因为「哪个后端
    需要哪种鉴权」属于 transport 事实。请求对象可以被反复发送，重试时不需要重新构造。
    """
    return urllib.request.Request(
        url,
        data=json_encode_body(payload),
        headers=headers,
        method="POST",
    )


def decode_error_body(exc: urllib.error.HTTPError) -> str:
    """读取非 2xx 响应的正文，解码失败时用替换字符兜底。

    ``errors="replace"`` 是刻意的：错误正文可能是截断的多字节内容，报错文本比解码成功更重要，
    不能让二次解码失败盖掉原始 HTTP 状态。
    """
    return exc.read().decode("utf-8", errors="replace")


def retry_delay_seconds(attempt: int) -> float:
    """返回第 ``attempt`` 次尝试失败后的退避秒数（从 0 计数）。

    线性而不是指数增长，因为模型调用的失败大多是网关抖动，指数退避会让一次交互拖到分钟级。
    """
    return RETRY_BACKOFF_UNIT_S * (attempt + 1)


def http_failure_message(backend_label: str, status_code: int, body: str) -> str:
    """拼出「后端返回非 2xx」的报错文本，附带原始状态码与响应正文。

    保留正文而不只报状态码：429 与 400 的修复方式完全不同，正文里的字段名往往是用户唯一
    能读懂的线索。正文长度不做裁剪，因为它只在失败路径上出现。
    """
    return f"{backend_label} request failed with HTTP {status_code}: {body}"


def backend_error_message(backend_label: str, detail: object) -> str:
    """拼出「后端在 2xx 里返回业务错误」或响应无法解析时的报错文本。

    ``detail`` 直接来自响应体（通常是 ``error`` 字段的原值），因此可能是 dict 或字符串；
    这里不尝试结构化它，provider 上层只负责把原因原样转述给 runtime。
    """
    return f"{backend_label} error: {detail}"


def backend_unreachable_message(backend_label: str, base_url: str, model: str) -> str:
    """拼出「连不上远端」的报错文本，把 Base URL 与模型名放在同一段里。

    网络错误本身不带任何配置信息，而这条链路最常见的故障是 Base URL 或模型名配错，
    所以两者都写进消息，用户不需要打开 trace 就能定位。
    """
    return f"Could not reach the {backend_label} backend.\nBase URL: {base_url}\nModel: {model}"
