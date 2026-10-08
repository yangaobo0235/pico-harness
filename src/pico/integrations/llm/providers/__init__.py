"""重导出 LLM Provider Abstraction 与主要 Concrete Provider。

PEP 562 Lazy Export 让导入 `pico.integrations.llm.providers` 或其 Submodule 时不提前加载 litellm，避免 Provider
SDK 主导 CLI Cold Start。Public Surface 包含 LLMProvider/LLMResponse、LiteLLM、Codex 与 Azure；
未知 Symbol 明确 AttributeError，`__dir__` 仍稳定展示可用名称。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pico.integrations.llm.contracts import LLMProvider, LLMResponse
    from pico.integrations.llm.providers.azure_openai_provider import AzureOpenAIProvider
    from pico.integrations.llm.providers.litellm_provider import LiteLLMProvider
    from pico.integrations.llm.providers.openai_codex_provider import OpenAICodexProvider

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider", "OpenAICodexProvider", "AzureOpenAIProvider"]

# 惰性重新导出（PEP 562）：导入 Provider 子模块时不得提前加载
# ``litellm_provider`` -> litellm，否则会主导 CLI 冷启动耗时。
_LAZY_EXPORTS = {
    "LLMProvider": "pico.integrations.llm.contracts",
    "LLMResponse": "pico.integrations.llm.contracts",
    "LiteLLMProvider": "pico.integrations.llm.providers.litellm_provider",
    "OpenAICodexProvider": "pico.integrations.llm.providers.openai_codex_provider",
    "AzureOpenAIProvider": "pico.integrations.llm.providers.azure_openai_provider",
}


def __getattr__(name: str) -> object:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
