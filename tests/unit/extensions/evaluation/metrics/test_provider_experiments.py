"""Tests for pico.extensions.evaluation.metrics.provider_experiments."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pico.extensions.evaluation.metrics.provider_experiments import _provider_profile


def test_provider_profile_loads_project_env_before_reading_deepseek_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project `.env` values win over leftover legacy `DEEPSEEK_*` process variables."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "PICO_DEEPSEEK_API_KEY=sk-project-deepseek",
                "PICO_DEEPSEEK_MODEL=deepseek-v4-pro",
                "PICO_DEEPSEEK_API_BASE=https://api.deepseek.com/anthropic",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with patch.dict(
        os.environ,
        {
            "DEEPSEEK_API_KEY": "sk-legacy-deepseek",
            "DEEPSEEK_MODEL": "legacy-deepseek-model",
            "DEEPSEEK_API_BASE": "https://legacy.deepseek.example/anthropic",
        },
        clear=True,
    ):
        profile = _provider_profile("deepseek")

    assert profile["status"] == "ready"
    assert profile["api_key"] == "sk-project-deepseek"
    assert profile["model"] == "deepseek-v4-pro"
    assert profile["base_url"] == "https://api.deepseek.com/anthropic"


def test_provider_profile_uses_right_codes_shared_key_for_gpt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gpt profile resolves through the shared right-codes key and pins its default model."""
    monkeypatch.chdir(tmp_path)

    with patch.dict(os.environ, {"PICO_RIGHT_CODES_API_KEY": "sk-right-codes"}, clear=True):
        profile = _provider_profile("gpt")

    assert profile["status"] == "ready"
    assert profile["api_key"] == "sk-right-codes"
    assert profile["model"] == "gpt-5.4"
