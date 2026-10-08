"""Construct configured model providers without terminal rendering or CLI exits."""

from __future__ import annotations

from pico.config.models.runtime import Config


def create_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from pico.integrations.llm.contracts import GenerationSettings
    from pico.integrations.llm.providers.azure_openai_provider import AzureOpenAIProvider
    from pico.integrations.llm.providers.openai_codex_provider import OpenAICodexProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=model)
    elif provider_name == "azure_openai":
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    else:
        from pico.integrations.llm.providers.litellm_provider import LiteLLMProvider

        # OpenRouter 会把 qwen3.x-27B 路由到默认启用推理模式的提供商（如 AtlasCloud）：每次对话
        # 补全都会产生约 800 个思维链令牌并耗时约 30 秒，这会严重影响交互使用和大规模基准运行。
        # ``reasoning.enabled=false`` 是 OpenRouter 专用参数，通过 LiteLLM 的 ``extra_body`` 转发。
        extra_body = None
        if provider_name == "openrouter" and "qwen" in (model or "").lower():
            extra_body = {"reasoning": {"enabled": False}}
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
            extra_body=extra_body,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
