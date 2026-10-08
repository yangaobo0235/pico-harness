"""Shared pytest fixtures.

Autouse fixtures live here so every test sees them without explicit
declaration.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmp_path_factory, request):
    """Keep nested benchmark paths below Windows' legacy path-length limit."""
    if os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="pt-", ignore_cleanup_errors=True) as directory:
            yield Path(directory)
    else:
        suffix = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
        yield tmp_path_factory.mktemp(f"t-{suffix}")


@pytest.fixture
def require_symlinks(tmp_path):
    """Probe actual symlink permissions rather than assuming them from the OS."""
    target = tmp_path / "symlink-probe-target"
    link = tmp_path / "symlink-probe-link"
    target.write_text("probe", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable in this environment: {exc}")
    finally:
        if link.is_symlink():
            link.unlink()
        target.unlink(missing_ok=True)


_OPT_IN_MARKERS = (
    "real_llm",
    "llm_judge",
    "real_vm",
    "real_channel",
    "external_runtime",
    "e2e",
)
_EXTERNAL_ENV_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "CLOUDSDK_",
    "DASHSCOPE_",
    "DEEPSEEK_",
    "DOCKER_",
    "FEISHU_",
    "GCP_",
    "GEMINI_",
    "GH_",
    "GITHUB_",
    "GOOGLE_",
    "GROQ_",
    "HF_",
    "HOSTED_VLLM_",
    "HUGGINGFACE_",
    "JINA_",
    "LARK_",
    "LITELLM_",
    "MINIMAX_",
    "MISTRAL_",
    "MOONSHOT_",
    "NANOBOT_",
    "OLLAMA_",
    "OPENAI_",
    "OPENROUTER_",
    "PICO_",
    "SERPER_",
    "SSH_",
    "ZAI_",
    "ZHIPUAI_",
)
_SENSITIVE_ENV_PARTS = (
    "ACCESS_KEY",
    "API_KEY",
    "APP_ID",
    "APP_SECRET",
    "CREDENTIAL",
    "NETRC",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_NETWORK_ENV_NAMES = {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}


def _is_external_environment(name: str) -> bool:
    upper = name.upper()
    return (
        upper in _NETWORK_ENV_NAMES
        or upper.endswith("_AUTH")
        or upper.startswith(_EXTERNAL_ENV_PREFIXES)
        or any(part in upper for part in _SENSITIVE_ENV_PARTS)
    )


@pytest.fixture(autouse=True)
def _isolate_retained_home(
    request: pytest.FixtureRequest,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    if any(request.node.get_closest_marker(name) for name in _OPT_IN_MARKERS):
        yield
        return

    from pico.config import loader

    for name in tuple(os.environ):
        if _is_external_environment(name):
            monkeypatch.delenv(name, raising=False)

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr(loader, "_current_config_path", None)
    yield


@pytest.fixture(autouse=True)
def _restore_loguru_enabled_state():
    """Undo any ``loguru.logger.disable("pico")`` left over from a
    prior test.

    ``src/pico/interfaces/cli/commands/run.py`` toggles ``logger.disable("pico")``
    based on a ``--no-logs`` flag. The disable is process-global on
    loguru's singleton logger, so once a CliRunner-based test exercises
    that branch the flag persists for the rest of the pytest session,
    silently dropping every ``pico.*`` log emission and breaking
    any later test that asserts on loguru output via a sink.
    """
    from loguru import logger

    yield
    logger.enable("pico")


@pytest.fixture(autouse=True)
def _no_openrouter_network(tmp_path):
    """Keep the OpenRouter catalog fetch off the network and off the real disk.

    The cross-provider pricing/context fallback fetches OpenRouter's /models for
    any LiteLLM-miss model, so an un-mocked test would hit the network. Default
    to an empty catalog; tests that exercise the catalog restore the real fetch
    and mock the transport. The disk cache path is also redirected to a temp
    file so the real ~/.pico/cache/ is never read or written.
    """
    from pico.integrations.llm.strategies import model_catalog_cache, pricing

    original_fetch = pricing._fetch_openrouter_models
    original_path = model_catalog_cache._CACHE_PATH
    pricing._fetch_openrouter_models = lambda: {}
    model_catalog_cache._CACHE_PATH = tmp_path / "model-catalog.json"
    try:
        yield
    finally:
        pricing._fetch_openrouter_models = original_fetch
        model_catalog_cache._CACHE_PATH = original_path
        pricing._OPENROUTER_CACHE.clear()
        pricing._OPENROUTER_CACHE_TIME = 0.0
