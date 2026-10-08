"""State shared by the single interactive onboarding flow."""

from __future__ import annotations

from typing import Any

from rich.console import Console

console = Console()

_TOTAL_STEPS = 4

_BACK = object()

_QMARK = " "

_POINTER = "❯"

_LANG = "en"

_CURATED_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "openrouter",
        "label": "OpenRouter (recommended — one key, many models)",
        "label_zh": "OpenRouter(推荐 · 一个 Key 调用多家模型)",
        "is_oauth": False,
    },
    {"name": "openai", "label": "OpenAI", "label_zh": "OpenAI", "is_oauth": False},
    {"name": "anthropic", "label": "Anthropic", "label_zh": "Anthropic", "is_oauth": False},
    {"name": "gemini", "label": "Gemini", "label_zh": "Gemini", "is_oauth": False},
    {"name": "deepseek", "label": "DeepSeek", "label_zh": "DeepSeek", "is_oauth": False},
    {
        "name": "github_copilot",
        "label": "GitHub Copilot (OAuth)",
        "label_zh": "GitHub Copilot(OAuth 登录)",
        "is_oauth": True,
    },
    {"name": "openai_codex", "label": "Codex (OAuth)", "label_zh": "Codex(OAuth 登录)", "is_oauth": True},
    {
        "name": "custom",
        "label": "Other (OpenAI-compatible endpoint)",
        "label_zh": "其他(OpenAI 兼容端点)",
        "is_oauth": False,
    },
]

_QUESTIONARY_INSTALL_HINT = "[red]Missing dependency:[/red] [#fbe23f]questionary[/#fbe23f] is required for interactive onboarding.\nInstall it with: [#fbe23f]uv add 'questionary>=2.0,<3.0'[/#fbe23f]\nOr re-run with [#fbe23f]--non-interactive[/#fbe23f] plus the relevant flags."

_PROMPT_THEMED = False

_CHANNEL_ORDER = ("feishu", "qq", "wecom")

_CHANNEL_CRED_HELP: dict[str, tuple[str, str]] = {
    "feishu": (
        "Feishu / Lark Open Platform → your app → Credentials for App ID & App Secret.",
        "飞书开放平台 → 你的应用 → 凭证与基础信息 拿 App ID / App Secret。",
    ),
    "wecom": (
        "WeCom admin console → your bot / app for its ID and secret.",
        "企业微信管理后台 → 机器人 / 应用 拿 ID 和 secret。",
    ),
    "qq": ("QQ Open Platform → your bot for App ID & secret.", "QQ 开放平台 → 你的机器人 拿 App ID 和 secret。"),
}
