"""描述 Pico 支持的模型后端配置目录。

每个 `ProviderProfile` 声明 transport、默认模型、默认 Base URL，以及按顺序尝试的环境变量名。
“同一把 key 在多个兼容网关之间复用”这类回退顺序属于配置事实，因此写在这里；真正的 HTTP 协议
差异属于 `pico.integrations.llm`，装配哪一个 client 属于 `pico.bootstrap.providers`。

默认 provider 是 ``deepseek``：它的 Anthropic-compatible 端点比本地 Ollama 更少依赖本机模型
环境，也比 OpenAI/Anthropic 代理少一层默认 gateway 假设。其他 provider 保留可用，需要显式
选择或在 `.env` 里改写 ``PICO_PROVIDER``。
"""

from dataclasses import dataclass, field

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_DEEPSEEK = "deepseek"

TRANSPORT_OLLAMA = "ollama"
TRANSPORT_OPENAI_COMPATIBLE = "openai_compatible"
TRANSPORT_ANTHROPIC_COMPATIBLE = "anthropic_compatible"

PROVIDER_CHOICES = (PROVIDER_OLLAMA, PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_DEEPSEEK)
DEFAULT_PROVIDER = PROVIDER_DEEPSEEK

#: 用户没有显式指定额外脱敏项时，仍然默认视为敏感的环境变量。
DEFAULT_SECRET_ENV_NAMES = (
    "PICO_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_TOKEN",
    "PICO_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "PICO_DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY",
    "PICO_RIGHT_CODES_API_KEY",
    "RIGHT_CODES_API_KEY",
    "GITHUB_PAT",
    "GH_PAT",
)

#: 允许用户补充脱敏名单的环境变量，逗号分隔。
SECRET_ENV_NAMES_VAR = "PICO_SECRET_ENV_NAMES"


@dataclass(frozen=True)
class ProviderProfile:
    """一个 Provider 的配置事实，创建后不再改变。

    ``model_env_names``、``base_url_env_names`` 与 ``api_key_env_names`` 都按“先命中先用”的顺序
    排列，第一项是 ``PICO_*`` 形式的当前命名，其后是历史命名。空元数表示该 Provider 不需要这项
    配置，例如本地 Ollama 不需要 API key。``extra_request_options`` 会原样传进 client 构造，
    用于 DeepSeek 必须显式关闭的 provider-native thinking。
    """

    name: str
    transport: str
    default_model: str
    default_base_url: str = ""
    model_env_names: tuple[str, ...] = ()
    base_url_env_names: tuple[str, ...] = ()
    api_key_env_names: tuple[str, ...] = ()
    requires_api_key: bool = True
    extra_request_options: dict = field(default_factory=dict)

    @property
    def primary_model_env(self) -> str:
        """返回当前命名形式的模型变量，供帮助文本与诊断输出引用。"""
        return self.model_env_names[0] if self.model_env_names else ""


PROVIDERS: dict[str, ProviderProfile] = {
    PROVIDER_OLLAMA: ProviderProfile(
        name=PROVIDER_OLLAMA,
        transport=TRANSPORT_OLLAMA,
        default_model="qwen3.5:4b",
        default_base_url="http://127.0.0.1:11434",
        requires_api_key=False,
    ),
    PROVIDER_OPENAI: ProviderProfile(
        name=PROVIDER_OPENAI,
        transport=TRANSPORT_OPENAI_COMPATIBLE,
        default_model="gpt-5.4",
        default_base_url="https://www.right.codes/codex/v1",
        model_env_names=("PICO_OPENAI_MODEL", "OPENAI_MODEL"),
        base_url_env_names=("PICO_OPENAI_API_BASE", "OPENAI_API_BASE"),
        # 共享 key 的网关常常只发一把，因此这里允许 Anthropic 侧变量回退。
        api_key_env_names=(
            "PICO_OPENAI_API_KEY",
            "OPENAI_API_KEY",
            "PICO_RIGHT_CODES_API_KEY",
            "RIGHT_CODES_API_KEY",
            "PICO_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    ),
    PROVIDER_ANTHROPIC: ProviderProfile(
        name=PROVIDER_ANTHROPIC,
        transport=TRANSPORT_ANTHROPIC_COMPATIBLE,
        default_model="claude-sonnet-4-6",
        default_base_url="https://www.right.codes/claude/v1",
        model_env_names=("PICO_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
        base_url_env_names=("PICO_ANTHROPIC_API_BASE", "ANTHROPIC_API_BASE"),
        api_key_env_names=(
            "PICO_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
            "PICO_RIGHT_CODES_API_KEY",
            "RIGHT_CODES_API_KEY",
            "PICO_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ),
    ),
    PROVIDER_DEEPSEEK: ProviderProfile(
        name=PROVIDER_DEEPSEEK,
        transport=TRANSPORT_ANTHROPIC_COMPATIBLE,
        default_model="deepseek-v4-pro",
        default_base_url="https://api.deepseek.com/anthropic",
        model_env_names=("PICO_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
        base_url_env_names=("PICO_DEEPSEEK_API_BASE", "DEEPSEEK_API_BASE"),
        api_key_env_names=("PICO_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        # Pico 目前用文本编码工具调用，不会回放 provider-native thinking block。
        # 在该协议端到端实现之前保持显式关闭，避免思考内容耗尽单步输出预算。
        extra_request_options={"thinking": {"type": "disabled"}},
    ),
}


def provider_profile(name: str) -> ProviderProfile:
    """按名称返回 `ProviderProfile`，未知名称抛出带可选清单的 `ValueError`。

    错误信息里列出全部合法取值，是因为 provider 名称通常来自命令行或 `.env` 的手工输入，
    只说“unknown provider”无法让使用者判断是拼错还是用了旧名字。
    """
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown provider: {name}. expected one of: {', '.join(PROVIDER_CHOICES)}") from None
