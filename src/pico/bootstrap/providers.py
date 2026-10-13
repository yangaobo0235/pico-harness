"""按配置创建模型客户端。

这里是“配置事实”到“可调用对象”的唯一转换点：读取 Provider 目录与优先级、决定用哪种 transport，
然后把结果交给 `pico.integrations.llm` 的具体 client。CLI 只负责把用户输入传进来，运行时只
拿到一个已经可以 `complete()` 的对象。

不检查凭证是否有效、不预测额度，也不做失败重试——那些只有在真正发起请求时才由 transport 层
反映。Provider 名称非法时立刻报错，因为把 ``atuo`` 当成默认 provider 继续跑，会让用户以为
自己换了模型。
"""

from typing import Any

from pico.config.loader import provider_env
from pico.config.models.runtime import (
    APPROVAL_ASK,
    APPROVAL_AUTO,
    APPROVAL_NEVER,
    DEFAULT_REQUEST_TIMEOUT_S,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from pico.config.providers import (
    DEFAULT_PROVIDER,
    TRANSPORT_ANTHROPIC_COMPATIBLE,
    TRANSPORT_OLLAMA,
    ProviderProfile,
    provider_profile,
)
from pico.integrations.llm.providers import (
    AnthropicCompatibleModelClient,
    OllamaModelClient,
    OpenAICompatibleModelClient,
)

PROVIDER_ENV_NAME = "PICO_PROVIDER"


def resolve_approval_policy(policy: str | None = None) -> str:
    """校验审批策略取值，``None`` 时使用默认的 ``ask``。

    非法取值直接报错而不是退回默认：审批策略写错意味着用户以为自己收紧或放宽了权限，静默采用
    默认值会让一次本该被拒绝的写入获得放行，或让一次无人值守运行卡在提示上。
    """
    if policy is None:
        return APPROVAL_ASK
    if policy not in (APPROVAL_ASK, APPROVAL_AUTO, APPROVAL_NEVER):
        raise ValueError(f"unknown approval policy: {policy}")
    return policy


#: 本地 Ollama 的服务地址变量，与云端 provider 不同，它不需要凭证。
OLLAMA_HOST_DEFAULT = "http://127.0.0.1:11434"


def resolve_provider(provider: str | None = None) -> ProviderProfile:
    """按 ``显式参数 > PICO_PROVIDER > 默认`` 的顺序选出 Provider。

    返回配置目录里的 `ProviderProfile`，让调用方直接读到 transport 与默认值，而不需要再按
    名称查一次表。未知名称抛出带可选清单的错误。
    """
    return provider_profile(provider or provider_env(PROVIDER_ENV_NAME, default=DEFAULT_PROVIDER))


def resolve_model(profile: ProviderProfile, model: str | None = None) -> str:
    """按 ``显式参数 > Provider 变量 > 代码默认`` 的顺序选出模型名。

    本地 Ollama 不读取模型环境变量：它的模型由本机已拉取的镜像决定，配一个不存在的名字比
    直接采用默认值更容易造成困惑。
    """
    if model:
        return str(model)
    if not profile.model_env_names:
        return profile.default_model
    return provider_env(profile.model_env_names[0], profile.model_env_names[1:], profile.default_model)


def build_model_client(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    host: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_S,
) -> Any:
    """创建一个可以直接 `complete()` 的模型客户端。

    Base URL 与 API key 都按 Provider 目录里的顺序解析，多个兼容网关复用同一把 key 的回退关系
    留在配置层，不在这里重复。API key 只从环境变量读取，永远不接受命令行参数，避免凭证出现在
    进程列表和 shell 历史里。

    返回对象的类型由 transport 决定，调用方只依赖 `ModelClient` 约定。
    """
    profile = resolve_provider(provider)
    resolved_model = resolve_model(profile, model)
    options = dict(profile.extra_request_options)

    if profile.transport == TRANSPORT_OLLAMA:
        return OllamaModelClient(
            model=resolved_model,
            host=host or profile.default_base_url,
            temperature=temperature,
            top_p=top_p,
            timeout=timeout,
        )

    resolved_base_url = base_url or provider_env(
        profile.base_url_env_names[0], profile.base_url_env_names[1:], profile.default_base_url
    )
    api_key = provider_env(profile.api_key_env_names[0], profile.api_key_env_names[1:])

    if profile.transport == TRANSPORT_ANTHROPIC_COMPATIBLE:
        return AnthropicCompatibleModelClient(
            model=resolved_model,
            base_url=resolved_base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            **options,
        )
    return OpenAICompatibleModelClient(
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
    )
