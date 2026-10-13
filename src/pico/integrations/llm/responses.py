"""从响应 JSON 里取出文本与元数据：把各家 schema 收敛成上层认得的字段。

`extract_openai_text` 与 `extract_anthropic_text` 负责「哪一段内容才是模型说的话」，
`extract_usage_cache_details` 与 `extract_anthropic_metadata` 负责 token 用量、cache 命中与
结束原因，`normalize_versioned_base_url` 把 Base URL 固定到带 ``/v1`` 的端点形态。归一化放在
这里是因为它和抽取函数回答同一个问题——这份响应该按哪种 schema 解读：端点版本不同，
``output`` 与 ``content`` 的位置就不同，两个 compatible client 因此共用同一条规则。

本模块不发请求、不看状态码，也不决定要不要重试；HTTP 组装与错误措辞属于
`pico.integrations.llm.requests`，SSE 分片的遍历属于 `pico.integrations.llm.sse`。所有函数都
只读取字典、缺失字段返回空串或 ``None``，不补默认 token 数：把「后端没报」写成 ``0`` 会让
trace 与 report 把一次失败的调用读成一次命中缓存的成功调用。
"""

from typing import Any


def normalize_versioned_base_url(base_url: object) -> str:
    """去掉尾部斜杠，并在缺少版本段时补上 ``/v1``，返回归一化后的 Base URL。

    ``base_url`` 允许是非字符串（配置里可能读到 ``Path`` 或数字），统一 ``str()`` 后再判断。
    已以 ``/v1`` 结尾的原样返回，因此 ``https://x/v1`` 与 ``https://x/`` 都变成
    ``https://x/v1``；``https://x/v1/`` 会先被 rstrip 掉斜杠再命中同一分支，不会重复追加。
    这里只识别字面量 ``/v1``：``/v1/chat`` 或 ``/anthropic`` 这类带后缀的路径会被追加
    ``/v1``，因为端点版本由 client 拼在路径最末，本层无法判断后端自定义前缀的含义。
    """
    base = str(base_url).rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def extract_openai_text(data: dict[str, Any]) -> str:
    """从 OpenAI-compatible 响应字典里取第一段可用文本，取不到时返回空串。

    按优先级尝试三种真实出现过的形状：``output_text``（Responses API 的整段结果）、
    ``output[].content[].text``（分块输出）、``choices[0].message.content``（Chat Completions
    兼容形状，字符串与分段列表都接）。返回第一段非空文本而不是全部拼接，因为同一轮里
    多个文本块通常只有第一段是最终回答；末尾返回 ``""`` 而不是抛错，让调用方决定
    「没有文本」是重试、报错还是当作空回答。
    """
    if data.get("output_text"):
        return data["output_text"]

    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict):
                text = content.get("text")
                if text:
                    return text

    choices = data.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        return text

    return ""


def extract_usage_cache_details(data: dict[str, Any]) -> dict[str, Any]:
    """把各家 ``usage`` 字段整理成统一结构，供 trace、report 与缓存观察使用。

    输入 token 同时接受 ``input_tokens`` 与 ``prompt_tokens``，输出同理，cache 明细同时接受
    ``input_tokens_details`` 与 ``prompt_tokens_details``，因为 OpenAI 与兼容网关在同一份响应里
    用过两套命名。输出固定包含 ``input_tokens``、``output_tokens``、``total_tokens``、
    ``cached_tokens``、``cache_hit`` 五个键：前三个在后端没报时保持 ``None``，
    ``cached_tokens`` 则把缺失与 ``null`` 统一成 ``0`` 并转成整数，``cache_hit`` 由它推导。
    没有 usage 段时依然返回这份「全空」结构，调用方因此总是能读到同一组键；
    这里不去算成本、也不判断缓存是否真的复用，那需要跨轮次的观察。
    """
    # 把不同 OpenAI-compatible 返回里的 usage 字段整理成统一结构，
    # 让 runtime/trace/report 不需要关心 provider 细节。
    usage = data.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached_tokens = int(input_details.get("cached_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens"),
        "cached_tokens": cached_tokens,
        "cache_hit": cached_tokens > 0,
    }


def extract_anthropic_text(data: dict[str, Any]) -> str:
    """拼接 Anthropic-compatible 响应里所有 ``type == "text"`` 的内容块，用换行分隔。

    ``thinking``、``tool_use`` 等其他块一律跳过：它们不是给用户看的回答，回放反而会污染
    下一轮 prompt。只有非空字符串才计入，因此空 text 块不会产生多余空行；
    整段没有 text 块时返回空串，由 client 结合 ``stop_reason`` 给出更具体的报错。
    """
    texts: list[str] = []
    for item in data.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts)


def extract_anthropic_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """记录一次 Anthropic-compatible 调用的结束原因、内容块类型与 token 用量。

    输出固定包含四个键：``stop_reason``（缺失时为 ``""``）、``content_block_types``（按出现顺序
    的类型名列表，用于区分「只吐出 thinking 就被截断」和「后端根本没返回块」）、
    ``input_tokens`` 与 ``output_tokens``（``usage`` 缺失时保持 ``None``）。这里刻意不折叠成
    ``cache_hit`` 之类的统一口径：该路径没接 prompt cache，编造字段会让上层误判缓存链路。
    """
    content_block_types: list[str] = []
    for item in data.get("content", []):
        if isinstance(item, dict):
            block_type = str(item.get("type", "")).strip()
            if block_type:
                content_block_types.append(block_type)
    usage = data.get("usage") or {}
    return {
        "stop_reason": str(data.get("stop_reason", "") or ""),
        "content_block_types": content_block_types,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }
