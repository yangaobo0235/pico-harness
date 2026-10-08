"""Onboarding ui: one screen or service responsibility."""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

import typer
from rich.panel import Panel

from pico.interfaces.cli.onboarding import configuration, providers, state


def _t(en: str, zh: str) -> str:
    """Return ``zh`` when the user picked Chinese, else ``en``."""
    return zh if state._LANG == "zh" else en


def _theme_questionary(questionary: Any) -> None:
    """Give every ``select`` a consistent pointer and drop questionary's own
    "(Use arrow keys)" hint — the step header already prints the controls.

    Display-only and applied once: we wrap ``questionary.select`` so callers
    that don't pass ``pointer`` / ``instruction`` inherit the unified look,
    while any explicit value still wins (``setdefault``).
    """
    if state._PROMPT_THEMED:
        return
    import functools

    _orig_select = questionary.select

    @functools.wraps(_orig_select)
    def _themed_select(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("pointer", state._POINTER)
        kwargs.setdefault("instruction", " ")
        return _orig_select(*args, **kwargs)

    questionary.select = _themed_select
    state._PROMPT_THEMED = True


def _require_questionary() -> Any:
    """Lazy-import :mod:`questionary` so missing-package errors stay scoped here."""
    try:
        import questionary
    except ModuleNotFoundError:
        state.console.print(state._QUESTIONARY_INSTALL_HINT)
        raise typer.Exit(1)
    _theme_questionary(questionary)
    return questionary


def _pick_language() -> None:
    """First screen: choose the wizard's language. Updates module-level ``_LANG``.

    Persistence happens later (after bootstrap created the config file), via
    ``set_language`` in :func:`_run_wizard_body`.
    """
    questionary = _require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    state.console.print()
    state.console.print(
        Panel(
            "[bold white]Let's set up Pico — first, choose your language.[/bold white]\n[dim]开始配置 Pico — 请先选择语言。[/dim]",
            title="[bold #fbe23f]Pico setup[/bold #fbe23f]",
            title_align="left",
            border_style="#c8a900",
            padding=(1, 2),
        )
    )
    state.console.print("  [dim]↑↓ select · Enter confirm · Ctrl+C quit[/dim]")
    state.console.print()
    picked = questionary.select(
        "Language / 语言",
        choices=[questionary.Choice("English", value="en"), questionary.Choice("中文(简体)", value="zh")],
        default=state._LANG,
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if picked is None:
        raise typer.Exit(1)
    state._LANG = picked


def _step_header(n: int, title: str) -> None:
    dots = " ".join(
        ("[#fbe23f]●[/#fbe23f]" if i <= n else "[grey37]○[/grey37]" for i in range(1, state._TOTAL_STEPS + 1))
    )
    state.console.print()
    state.console.print(
        Panel(
            f"[bold white]{title}[/bold white]",
            title=f"[bold #fbe23f]{_t('Step', '步骤')} {n}/{state._TOTAL_STEPS}[/bold #fbe23f]",
            title_align="left",
            subtitle=dots,
            subtitle_align="right",
            border_style="#c8a900",
            padding=(0, 2),
        )
    )
    state.console.print()


def _check_tty_or_die(non_interactive: bool) -> None:
    """Bail when stdout isn't a TTY and the user didn't opt into headless mode."""
    if non_interactive:
        return
    if not sys.stdout.isatty():
        state.console.print(
            "[red]Non-interactive terminal detected.[/red]\nRe-run with: [#fbe23f]pico onboard --non-interactive --provider <name> --api-key <key>[/#fbe23f]"
        )
        raise typer.Exit(2)


def _handle_existing_config(*, reset: bool, yes: bool, non_interactive: bool) -> None:
    """Guard against silently overwriting an existing config in non-interactive
    runs.

    Interactive runs always fall through into the structured wizard: every step
    defaults to "Keep current" for already-set values, so pressing Enter all the
    way through is equivalent to skipping, and changing any value reconfigures
    just that one. No separate skip/redo/quit screen — it would drop the wizard's
    welcome banner and step framing.
    """
    if reset:
        return
    if not configuration._is_config_populated():
        return
    if non_interactive:
        if yes:
            state.console.print("[dim]Existing config detected; --yes set, proceeding with overwrite.[/dim]")
            return
        state.console.print(
            "[red]Existing config detected.[/red] Pass [#fbe23f]--reset[/#fbe23f] (or [#fbe23f]--yes[/#fbe23f]) to overwrite, or edit in place with [#fbe23f]pico provider set[/#fbe23f] / [#fbe23f]pico channels enable[/#fbe23f]."
        )
        raise typer.Exit(2)


def _back_placeholder(allow_back: bool) -> Any:
    """A faint in-field placeholder telling the user an empty submit rewinds.

    Rendered greyed inside the input (via prompt_toolkit's ``placeholder``),
    it disappears the moment they type and leaves nothing behind once the
    prompt is answered. Returns ``None`` when back isn't offered.
    """
    if not allow_back:
        return None
    return [("fg:#6c6c6c italic", _t("empty ↵ to go back", "留空回车返回上一步"))]


def _field_placeholder(allow_back: bool, required: bool) -> Any:
    """In-field hint for a channel credential prompt.

    First field: empty submit rewinds to the channel picker (back). Later
    optional fields: empty submit skips them. Required later fields get no
    hint — an empty submit there silently drops a value the channel needs.
    """
    if allow_back:
        return _back_placeholder(True)
    if not required:
        return [("fg:#6c6c6c italic", _t("empty ↵ to skip", "留空回车跳过"))]
    return None


def _collect_fields(prompts: list[Callable[[], Any]]) -> Optional[list[Any]]:
    """Run text-prompt callables in order with empty-submit = back.

    Each callable prompts one field and returns its value, or ``_BACK`` (an
    empty submit) to rewind one field. Backing out of the first field returns
    ``None`` so the caller can rewind to the preceding screen. Returns the list
    of collected values on success.
    """
    values: list[Any] = []
    i = 0
    while i < len(prompts):
        value = prompts[i]()
        if value is state._BACK:
            if i == 0:
                return None
            values.pop()
            i -= 1
            continue
        if i < len(values):
            values[i] = value
        else:
            values.append(value)
        i += 1
    return values


def _failure_choice(options: list[tuple[str, str]], *, non_interactive: bool) -> str:
    """Render a numbered failure submenu, return the chosen value.

    ``options`` is a list of ``(label, value)``. In non-interactive mode the
    last option (always "continue anyway") is auto-chosen so headless runs
    never block.
    """
    if non_interactive:
        return options[-1][1]
    questionary = _require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    chosen = questionary.select(
        _t("What would you like to do?", "想做什么?"),
        choices=[questionary.Choice(label, value=value) for label, value in options],
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if chosen is None:
        raise typer.Exit(1)
    return chosen


def _print_next_steps(*, warnings: list[str]) -> None:
    from rich.table import Table

    state.console.print()
    if warnings:
        state.console.print(
            Panel(
                _t(
                    "[bold yellow]⚠ Setup finished with warnings[/bold yellow]",
                    "[bold yellow]⚠ 配置完成,但有警告[/bold yellow]",
                )
                + "\n\n"
                + _t("[dim]These items didn't pass a connectivity test:[/dim] ", "[dim]以下项目未通过连通测试:[/dim] ")
                + f"{', '.join(warnings)}\n"
                + _t(
                    "[dim]Fix them before relying on the related features (re-run [/dim][#fbe23f]pico onboard[/#fbe23f][dim] to reconfigure).[/dim]",
                    "[dim]在依赖相关功能前请先修复(重新运行 [/dim][#fbe23f]pico onboard[/#fbe23f][dim] 重新配置)。[/dim]",
                ),
                border_style="yellow",
                padding=(1, 2),
            )
        )
    else:
        state.console.print(
            Panel(
                _t("[bold green]🎉 Setup complete![/bold green]", "[bold green]🎉 配置完成![/bold green]"),
                border_style="green",
                padding=(0, 2),
            )
        )
    provs = (
        ", ".join((providers._provider_label(n).split(" (")[0] for n in configuration._configured_providers())) or "—"
    )
    run_loc = (
        _t("Host (direct)", "本机直接运行")
        if configuration._current_sandbox_backend() == "none"
        else _t("Sandbox (boxlite)", "沙箱(boxlite)")
    )
    chans = ", ".join(configuration._enabled_channels()) or _t("none", "无")
    mem = _t("Myna", "Myna") if configuration._memory_enabled() else _t("disabled", "已关闭")
    recap = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    recap.add_column(style="dim", no_wrap=True)
    recap.add_column()
    recap.add_row(_t("Provider", "服务商"), provs)
    recap.add_row(_t("Default model", "默认模型"), configuration._load_current_default_model() or "—")
    recap.add_row(_t("Run location", "运行位置"), run_loc)
    recap.add_row(_t("Channels", "聊天渠道"), chans)
    recap.add_row(_t("Memory", "长期记忆"), mem)
    state.console.print(
        Panel(
            recap,
            title=f"[bold]{_t('Your setup', '你的配置')}[/bold]",
            title_align="left",
            border_style="#8a6d00",
            padding=(1, 2),
        )
    )
    table = Table(show_header=False, box=None, padding=(0, 3, 0, 0))
    table.add_column(style="#fbe23f", no_wrap=True)
    table.add_column(style="dim")
    table.add_row("pico", _t("launch the native TUI (default)", "启动原生 TUI(默认)"))
    table.add_row("pico gateway", _t("run the gateway (serve channels)", "运行网关(对接渠道)"))
    table.add_row('pico run -m "hello, world"', _t("ask a one-shot question", "一次性提问"))
    table.add_row("pico channels list", _t("see connected chat channels", "查看已接入的渠道"))
    table.add_row("pico provider list", _t("check your provider config", "检查当前服务商配置"))
    state.console.print(
        Panel(
            table,
            title=f"[bold]{_t('Get started', '开始使用')}[/bold]",
            title_align="left",
            border_style="#c8a900",
            padding=(1, 2),
        )
    )
