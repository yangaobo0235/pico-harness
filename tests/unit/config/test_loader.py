"""Tests for pico.config.loader: project `.env` values consumed during assembly.

`load_project_env` runs inside `pico.bootstrap.container.build_runtime`, so these cases lock the
precedence between a project `.env`, the shell environment and explicit CLI flags.
"""

import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from pico.bootstrap.container import build_runtime
from pico.config.models.runtime import APPROVAL_ASK
from pico.interfaces.cli.app import build_arg_parser


def _runtime_from_args(args: Namespace):
    """Assemble a runtime from parsed CLI args the way `pico.interfaces.cli.app.main` does."""
    return build_runtime(
        cwd=args.cwd,
        resume=args.resume,
        approval_policy=args.approval or APPROVAL_ASK,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=args.secret_env_names,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        host=args.host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout if args.provider == "ollama" else args.openai_timeout,
    )


def test_build_agent_uses_project_env_provider_when_cli_omitted(tmp_path: Path) -> None:
    """A `PICO_PROVIDER` from the project `.env` is honored when no `--provider` was passed."""
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "PICO_PROVIDER=openai",
                "PICO_OPENAI_API_BASE=https://www.right.codes/codex/v1",
                "PICO_OPENAI_API_KEY=sk-project-openai",
                "PICO_OPENAI_MODEL=gpt-5.4",
                "PICO_DEEPSEEK_API_KEY=sk-project-deepseek",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path)])

    with patch.dict(os.environ, {}, clear=True):
        with (
            patch(
                "pico.bootstrap.providers.OllamaModelClient",
                side_effect=AssertionError("ollama client should not be used"),
            ),
            patch(
                "pico.bootstrap.providers.AnthropicCompatibleModelClient",
                side_effect=AssertionError("deepseek client should not be used"),
            ),
            patch("pico.bootstrap.providers.OpenAICompatibleModelClient") as mock_openai,
        ):
            fake_client = mock_openai.return_value
            agent = _runtime_from_args(args)

    mock_openai.assert_called_once()
    assert mock_openai.call_args.kwargs["model"] == "gpt-5.4"
    assert mock_openai.call_args.kwargs["base_url"] == "https://www.right.codes/codex/v1"
    assert mock_openai.call_args.kwargs["api_key"] == "sk-project-openai"
    assert agent.model_client is fake_client


def test_build_agent_prefers_cli_provider_over_project_env_provider(tmp_path: Path) -> None:
    """An explicit `--provider` beats the `PICO_PROVIDER` declared in the project `.env`."""
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "PICO_PROVIDER=openai",
                "PICO_OPENAI_API_KEY=sk-project-openai",
                "PICO_DEEPSEEK_API_BASE=https://api.deepseek.com/anthropic",
                "PICO_DEEPSEEK_API_KEY=sk-project-deepseek",
                "PICO_DEEPSEEK_MODEL=deepseek-v4-pro",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "deepseek"])

    with patch.dict(os.environ, {}, clear=True):
        with (
            patch(
                "pico.bootstrap.providers.OllamaModelClient",
                side_effect=AssertionError("ollama client should not be used"),
            ),
            patch(
                "pico.bootstrap.providers.OpenAICompatibleModelClient",
                side_effect=AssertionError("openai client should not be used"),
            ),
            patch("pico.bootstrap.providers.AnthropicCompatibleModelClient") as mock_anthropic,
        ):
            fake_client = mock_anthropic.return_value
            agent = _runtime_from_args(args)

    mock_anthropic.assert_called_once()
    assert mock_anthropic.call_args.kwargs["model"] == "deepseek-v4-pro"
    assert mock_anthropic.call_args.kwargs["base_url"] == "https://api.deepseek.com/anthropic"
    assert mock_anthropic.call_args.kwargs["api_key"] == "sk-project-deepseek"
    assert agent.model_client is fake_client
