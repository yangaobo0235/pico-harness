"""模型 Provider 适配层的稳定入口：四个 client 加一份形状约定。

上层需要的东西只有这些：`FakeModelClient`、`OllamaModelClient`、`OpenAICompatibleModelClient`、
`AnthropicCompatibleModelClient`，以及 `ModelClient` 这个用于类型标注的协议。
`requests`、`responses`、`sse` 与 `providers` 子模块的切分属于实现细节，需要复用其中某个函数时
从子模块显式导入，免得这个包变成什么都往里塞的命名空间。

这里不解析配置、不装配 Agent、不决定用哪个后端（`pico.config.providers` 与
`pico.bootstrap.providers` 负责），也不判断一次模型回答是否算任务完成。
"""

from pico.integrations.llm.contracts import ModelClient
from pico.integrations.llm.providers import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    OllamaModelClient,
    OpenAICompatibleModelClient,
)

__all__ = [
    "AnthropicCompatibleModelClient",
    "FakeModelClient",
    "ModelClient",
    "OllamaModelClient",
    "OpenAICompatibleModelClient",
]
