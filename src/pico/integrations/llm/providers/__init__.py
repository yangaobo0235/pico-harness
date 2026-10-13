"""Provider 客户端集合：一个后端一个 client，transport 适配只在这里发生。

`FakeModelClient` 用脚本输出喂给控制循环；`OllamaModelClient` 打本地 ``/api/generate``；
`OpenAICompatibleModelClient` 打 ``/responses``，同时接住 JSON 与 SSE；
`AnthropicCompatibleModelClient` 打 ``/messages``，并透传 ``thinking`` 开关。URL 组装、header、
鉴权形式、状态码与异常归一化、响应抽取以及 `last_completion_metadata` 的写入时机，全部在
这一层完成：上层只拿到文本和一份与 transport 无关的元数据字典。

选哪个 client 不属于这里——`pico.config.providers` 的 `ProviderProfile.transport` 给出事实，
`pico.bootstrap.providers` 负责装配；本包也不反查配置目录。`contracts.ModelClient` 只是形状
约定，这里没有注册表也没有 isinstance 检查，新增后端不会被本层拦下，也不会让缓存的
Prompt 前缀失效。测试替身与真实后端在这里是同一种东西：能 ``complete()`` 的对象。
"""

from pico.integrations.llm.providers.anthropic_compat import AnthropicCompatibleModelClient
from pico.integrations.llm.providers.fake import FakeModelClient
from pico.integrations.llm.providers.ollama import OllamaModelClient
from pico.integrations.llm.providers.openai_compat import OpenAICompatibleModelClient

__all__ = [
    "AnthropicCompatibleModelClient",
    "FakeModelClient",
    "OllamaModelClient",
    "OpenAICompatibleModelClient",
]
