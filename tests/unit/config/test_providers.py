"""Tests for pico.config.providers and the LLM provider clients it selects.

The provider catalog decides which transport, model name, base URL and credential fallback an
assembly uses; `pico.integrations.llm.providers.*` implement those transports. Both sides are
locked here because the old flat `pico.cli` module owned both concerns.
"""

import json
import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from pico.bootstrap.container import build_runtime
from pico.config.models.runtime import APPROVAL_ASK
from pico.integrations.llm.providers.anthropic_compat import AnthropicCompatibleModelClient
from pico.integrations.llm.providers.ollama import OllamaModelClient
from pico.integrations.llm.providers.openai_compat import OpenAICompatibleModelClient
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


def test_ollama_client_posts_expected_payload() -> None:
    """The Ollama transport posts a non-streaming `/api/generate` body with the requested model."""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"response": "<final>ok</final>"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OllamaModelClient(
        model="qwen3.5:4b",
        host="http://127.0.0.1:11434",
        temperature=0.2,
        top_p=0.9,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["timeout"] == 30
    assert captured["body"]["model"] == "qwen3.5:4b"
    assert captured["body"]["prompt"] == "hello"
    assert captured["body"]["stream"] is False


def test_openai_compatible_client_posts_expected_responses_payload() -> None:
    """The OpenAI-compatible transport targets `/responses` with the Responses API body and headers."""
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"output_text": "<final>ok</final>"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "https://right.codes/v1/responses"
    assert captured["timeout"] == 30
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-agent"] == "pico/0.1"
    assert captured["body"] == {
        "model": "right.codes/codex-mini",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "hello",
                    }
                ],
            }
        ],
        "max_output_tokens": 42,
        "stream": False,
        "temperature": 0.2,
    }


def test_openai_compatible_client_sends_prompt_cache_fields_and_records_usage() -> None:
    """Prompt-cache hints are forwarded and the usage block is exposed as completion metadata."""
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": "<final>ok</final>",
                    "usage": {
                        "input_tokens": 2048,
                        "input_tokens_details": {"cached_tokens": 1536},
                        "output_tokens": 32,
                        "total_tokens": 2080,
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete(
            "hello",
            42,
            prompt_cache_key="prefix-hash-123",
            prompt_cache_retention="in_memory",
        )

    assert result == "<final>ok</final>"
    assert captured["body"]["prompt_cache_key"] == "prefix-hash-123"
    assert captured["body"]["prompt_cache_retention"] == "in_memory"
    assert client.last_completion_metadata["prompt_cache_supported"] is True
    assert client.last_completion_metadata["cached_tokens"] == 1536
    assert client.last_completion_metadata["cache_hit"] is True
    assert client.last_completion_metadata["input_tokens"] == 2048


def test_openai_compatible_client_extracts_text_from_event_stream() -> None:
    """A `text/event-stream` body is unwrapped to the completed response's text."""

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                'data: {"type":"response.created","response":{"id":"resp_1","output":[]}}\n'
                'data: {"type":"response.completed","response":{"output":[{"content":[{"text":"<final>stream ok</final>"}]}]}}\n'
                "data: [DONE]\n"
            ).encode("utf-8")

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>stream ok</final>"


def test_openai_compatible_client_extracts_text_from_event_stream_deltas() -> None:
    """Streamed `output_text.delta` events still resolve to the final text payload."""

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                "event: response.output_text.delta\n"
                'data: {"type":"response.output_text.delta","delta":"<final>"}\n'
                "event: response.output_text.delta\n"
                'data: {"type":"response.output_text.delta","delta":"OK"}\n'
                "event: response.output_text.done\n"
                'data: {"type":"response.output_text.done","text":"<final>OK</final>"}\n'
                "data: [DONE]\n"
            ).encode("utf-8")

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>OK</final>"


def test_anthropic_compatible_client_posts_expected_messages_payload() -> None:
    """The Anthropic-compatible transport targets `/messages` with the x-api-key and version headers."""
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "<final>ok</final>",
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = AnthropicCompatibleModelClient(
        model="claude-sonnet-4-5-20250929",
        base_url="https://www.right.codes/claude-aws/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "https://www.right.codes/claude-aws/v1/messages"
    assert captured["timeout"] == 30
    assert captured["headers"]["X-api-key"] == "sk-test"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {
        "model": "claude-sonnet-4-5-20250929",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "hello",
                    }
                ],
            }
        ],
        "max_tokens": 42,
        "stream": False,
        "temperature": 0.2,
    }


def test_anthropic_compatible_client_extracts_first_text_block() -> None:
    """Only the first `type == "text"` content block becomes the completion text."""

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [
                        {"type": "thinking", "thinking": "hidden"},
                        {"type": "text", "text": "<final>ok</final>"},
                    ]
                }
            ).encode("utf-8")

    client = AnthropicCompatibleModelClient(
        model="claude-sonnet-4-5-20250929",
        base_url="https://www.right.codes/claude-aws/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"


def test_anthropic_compatible_client_classifies_thinking_only_truncation() -> None:
    """A `max_tokens` stop with only thinking blocks raises and records the truncation metadata."""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [
                        {"type": "thinking", "thinking": "Inspecting the test failures."},
                    ],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 1000, "output_tokens": 512},
                }
            ).encode("utf-8")

    client = AnthropicCompatibleModelClient(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/anthropic",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        with pytest.raises(RuntimeError, match="ended before a text block"):
            client.complete("inspect tests", 512)

    assert client.last_completion_metadata == {
        "stop_reason": "max_tokens",
        "content_block_types": ["thinking"],
        "input_tokens": 1000,
        "output_tokens": 512,
    }


def test_anthropic_compatible_client_sends_explicit_thinking_mode() -> None:
    """A configured thinking mode is forwarded verbatim in the request body."""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [{"type": "text", "text": "<final>ok</final>"}],
                    "stop_reason": "end_turn",
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = AnthropicCompatibleModelClient(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/anthropic",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
        thinking={"type": "disabled"},
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        assert client.complete("inspect tests", 512) == "<final>ok</final>"

    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_build_agent_uses_openai_provider_and_model_override(tmp_path: Path) -> None:
    """An explicit `--model` wins over the environment and selects the OpenAI-compatible client."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "openai", "--model", "override-model"])

    with patch.dict(
        os.environ,
        {
            "OPENAI_API_BASE": "https://www.right.codes/codex/v1",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "env-model",
        },
        clear=False,
    ):
        with (
            patch(
                "pico.bootstrap.providers.OllamaModelClient",
                side_effect=AssertionError("ollama client should not be used"),
            ),
            patch("pico.bootstrap.providers.OpenAICompatibleModelClient") as mock_openai,
        ):
            fake_client = mock_openai.return_value
            agent = _runtime_from_args(args)

    mock_openai.assert_called_once()
    assert mock_openai.call_args.kwargs["model"] == "override-model"
    assert mock_openai.call_args.kwargs["base_url"] == "https://www.right.codes/codex/v1"
    assert mock_openai.call_args.kwargs["api_key"] == "sk-test"
    assert agent.model_client is fake_client


def test_build_agent_uses_right_codes_shared_key_for_openai_provider(tmp_path: Path) -> None:
    """The shared Right-Codes key is an accepted credential source for the OpenAI provider."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "openai"])

    with patch.dict(os.environ, {"PICO_RIGHT_CODES_API_KEY": "sk-right-codes"}, clear=True):
        with (
            patch(
                "pico.bootstrap.providers.OllamaModelClient",
                side_effect=AssertionError("ollama client should not be used"),
            ),
            patch("pico.bootstrap.providers.OpenAICompatibleModelClient") as mock_openai,
        ):
            fake_client = mock_openai.return_value
            agent = _runtime_from_args(args)

    mock_openai.assert_called_once()
    assert mock_openai.call_args.kwargs["api_key"] == "sk-right-codes"
    assert agent.model_client is fake_client


def test_build_agent_uses_anthropic_provider_and_openai_key_fallback(tmp_path: Path) -> None:
    """The Anthropic profile falls back to `OPENAI_API_KEY` when no Anthropic-side key exists."""
    args = build_arg_parser().parse_args(
        ["--cwd", str(tmp_path), "--provider", "anthropic", "--model", "claude-sonnet-4-5-20250929"]
    )

    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "sk-openai-fallback",
        },
        clear=True,
    ):
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
    assert mock_anthropic.call_args.kwargs["model"] == "claude-sonnet-4-5-20250929"
    assert mock_anthropic.call_args.kwargs["base_url"] == "https://www.right.codes/claude/v1"
    assert mock_anthropic.call_args.kwargs["api_key"] == "sk-openai-fallback"
    assert agent.model_client is fake_client


def test_build_agent_uses_anthropic_default_model_when_env_is_missing(tmp_path: Path) -> None:
    """Without an Anthropic model variable the catalog default model is sent."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "anthropic"])

    with patch.dict(
        os.environ,
        {},
        clear=False,
    ):
        os.environ.pop("ANTHROPIC_MODEL", None)
        with patch("pico.bootstrap.providers.AnthropicCompatibleModelClient") as mock_anthropic:
            _runtime_from_args(args)

    assert mock_anthropic.call_args.kwargs["model"] == "claude-sonnet-4-6"


def test_build_agent_uses_deepseek_provider_and_env_configuration(tmp_path: Path) -> None:
    """Project `.env` DeepSeek values win over legacy variables and thinking stays disabled."""
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "PICO_DEEPSEEK_API_BASE=https://api.deepseek.com/anthropic",
                "PICO_DEEPSEEK_API_KEY=sk-project-deepseek",
                "PICO_DEEPSEEK_MODEL=deepseek-v4-pro",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "deepseek"])

    with patch.dict(
        os.environ,
        {
            "DEEPSEEK_API_BASE": "https://legacy.deepseek.example/anthropic",
            "DEEPSEEK_API_KEY": "sk-legacy-deepseek",
            "DEEPSEEK_MODEL": "legacy-deepseek-model",
            "ANTHROPIC_API_KEY": "sk-anthropic",
            "OPENAI_API_KEY": "sk-openai",
        },
        clear=True,
    ):
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
    assert mock_anthropic.call_args.kwargs["thinking"] == {"type": "disabled"}
    assert agent.model_client is fake_client


def test_build_agent_uses_deepseek_default_model_when_env_is_missing(tmp_path: Path) -> None:
    """With only a DeepSeek key set, the catalog default model and base URL are used."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "deepseek"])

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-deepseek"}, clear=True):
        with patch("pico.bootstrap.providers.AnthropicCompatibleModelClient") as mock_anthropic:
            _runtime_from_args(args)

    assert mock_anthropic.call_args.kwargs["model"] == "deepseek-v4-pro"
    assert mock_anthropic.call_args.kwargs["base_url"] == "https://api.deepseek.com/anthropic"


def test_build_agent_uses_deepseek_provider_by_default(tmp_path: Path) -> None:
    """An omitted `--provider` resolves to DeepSeek and reads its legacy environment names."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path)])

    with patch.dict(
        os.environ,
        {
            "DEEPSEEK_API_BASE": "https://api.deepseek.com/anthropic",
            "DEEPSEEK_API_KEY": "sk-test",
        },
        clear=False,
    ):
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
    assert mock_anthropic.call_args.kwargs["api_key"] == "sk-test"
    assert agent.model_client is fake_client
