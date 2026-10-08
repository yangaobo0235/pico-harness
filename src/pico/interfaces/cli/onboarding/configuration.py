"""Onboarding configuration: one screen or service responsibility."""

from __future__ import annotations

from typing import Any, Optional

import typer

from pico.interfaces.cli.onboarding import state, ui


def _config_language() -> str:
    """Read the saved UI language from the on-disk config ('en' / 'zh').

    A missing / empty config (fresh install) defaults to 'en'; a malformed one
    raises ConfigReadError (surfaced by the CLI entrypoint) rather than being
    silently read as empty.
    """
    data = _load_raw_config()
    lang = data.get("language")
    return lang if lang in ("en", "zh") else "en"


def _load_raw_config() -> dict[str, Any]:
    """Return the parsed on-disk config, or ``{}`` if absent/empty.

    A present-but-unparseable config raises ConfigReadError (surfaced cleanly by
    the CLI entrypoint) instead of being silently treated as empty -- which
    would let onboard misread state and write over a config whose only fault is
    a syntax typo.
    """
    from pico.config.loader import get_config_path, read_raw_or_raise

    return read_raw_or_raise(get_config_path()) or {}


def _configured_providers() -> list[str]:
    """Names of providers that currently have an api_key set on disk."""
    data = _load_raw_config()
    providers = data.get("providers") or {}
    return [name for name, p in providers.items() if isinstance(p, dict) and p.get("apiKey")]


def _is_config_populated() -> bool:
    """True iff at least one provider has a key AND a default model is set.

    "Populated" for the startup gate means the required step (Step 1) is
    satisfied: a provider key plus ``agents.defaults.model``. Either alone is
    not enough to talk to a model.
    """
    data = _load_raw_config()
    providers = data.get("providers") or {}
    has_provider = any((isinstance(p, dict) and p.get("apiKey") for p in providers.values()))
    model = (data.get("agents", {}) or {}).get("defaults", {}).get("model")
    return bool(has_provider and model)


def _bootstrap_empty_config() -> None:
    """Make sure ``~/.pico/config.json`` + workspace dir exist before we patch.

    We seed the user-facing extension defaults (memory / plugins / skillForge),
    including ``memory.backend = "myna"``. Step 4 keeps that selection or
    writes ``None`` when the user explicitly disables Memory.

    Seeding runs on EVERY onboard, not just a brand-new config: the writer is
    ``setdefault``-based (non-clobbering), so it backfills these blocks into a
    pre-existing config that predates them without touching any value the user
    already set. The base ``Config()`` is only written when the file is absent —
    overwriting an existing file there would clobber it.
    """
    from pico.bootstrap.workspace import sync_workspace_templates
    from pico.config.loader import get_config_path, load_config, save_config
    from pico.config.paths import get_workspace_path

    path = get_config_path()
    if not path.exists():
        save_config(load_config())
    _init_extension_block_defaults()
    workspace = get_workspace_path()
    workspace.mkdir(parents=True, exist_ok=True)
    sync_workspace_templates(workspace)


def _load_current_default_model() -> Optional[str]:
    """Read ``agents.defaults.model`` from the on-disk config, if it exists."""
    data = _load_raw_config()
    return data.get("agents", {}).get("defaults", {}).get("model") or None


def _write_provider_fields(provider: str, fields: dict[str, Any]) -> None:
    """Thin wrapper that surfaces ops-library errors with friendly hints."""
    from pydantic import ValidationError

    from pico.config.update_providers import set_provider_fields

    try:
        set_provider_fields(provider, fields)
    except KeyError as exc:
        state.console.print(f"  [red]✗[/red] {exc}")
        raise typer.Exit(1)
    except RuntimeError as exc:
        state.console.print(f"  [red]✗[/red] {exc}")
        raise typer.Exit(1)
    except ValidationError as exc:
        state.console.print(ui._t(f"  [red]✗ Validation failed:[/red]\n{exc}", f"  [red]✗ 校验失败:[/red]\n{exc}"))
        raise typer.Exit(1)


def _persist_default_model(model: Optional[str]) -> None:
    """Patch ``agents.defaults.model`` if we picked one."""
    if not model:
        return
    from pico.config.update import set_default_model

    set_default_model(model)


def _current_sandbox_backend() -> str:
    """Read ``tools.sandbox.backend`` from disk; defaults to ``none``."""
    data = _load_raw_config()
    return ((data.get("tools") or {}).get("sandbox") or {}).get("backend") or "none"


def _persist_sandbox_backend(backend: str) -> None:
    """Patch ``sandbox.backend`` on the on-disk config via the ops layer."""
    from pico.config.update import set_sandbox_backend

    set_sandbox_backend(backend)


def _enabled_channels() -> list[str]:
    """Names of channels currently enabled on disk."""
    data = _load_raw_config()
    channels = data.get("channels") or {}
    return [name for name, c in channels.items() if isinstance(c, dict) and c.get("enabled")]


def _enable_channel(channel: str, fields: dict[str, Any]) -> None:
    """Thin wrapper for ``enable_channel`` that surfaces ops errors with hints."""
    from pydantic import ValidationError

    from pico.config.update_channels import enable_channel

    try:
        enable_channel(channel, fields)
    except KeyError as exc:
        state.console.print(f"  [red]✗[/red] {exc}")
        raise typer.Exit(1)
    except ValidationError as exc:
        state.console.print(ui._t(f"  [red]✗ Validation failed:[/red]\n{exc}", f"  [red]✗ 校验失败:[/red]\n{exc}"))
        raise typer.Exit(1)


def _set_memory_backend(backend: Optional[str]) -> None:
    """Set ``memory.backend`` through the config operations layer."""
    from pico.config.update import set_memory_backend

    set_memory_backend(backend)


def _init_extension_block_defaults() -> None:
    """Seed the memory / plugins / skillForge extension defaults via the ops layer."""
    from pico.config.update import init_extension_block_defaults

    init_extension_block_defaults()


def _memory_enabled() -> bool:
    """Return whether the configured Runtime selects Myna Memory."""
    data = _load_raw_config()
    return (data.get("memory") or {}).get("backend") == "myna"


def _default_provider_name() -> str:
    from pico.config.loader import load_config

    return load_config().get_provider_name() or "auto"
