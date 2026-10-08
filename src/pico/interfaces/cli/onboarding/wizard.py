"""Onboarding wizard: one screen or service responsibility."""

from __future__ import annotations

from typing import Callable, Optional

from rich.panel import Panel

from pico.interfaces.cli.onboarding import channels, configuration, execution, memory, providers, state, ui


def run_wizard(
    *,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    channel: Optional[str] = None,
    skip_sandbox: bool = False,
    skip_channel: bool = False,
    skip_memory: bool = False,
    non_interactive: bool = False,
    yes: bool = False,
    reset: bool = False,
    skip_test: bool = False,
) -> None:
    """Run the 4-step onboarding wizard end-to-end.

    The reusable entry point: the ``onboard`` CLI command and the startup gate
    both call this. Screens form a state machine so a ``0) Back`` choice can
    rewind one step; Ctrl+C exits keeping whatever was already written.

    Internal INFO logs (config writes, etc.) are hushed for the wizard's
    duration so they don't clutter the UI, then restored in ``finally`` —
    display-only; logging elsewhere is unaffected.
    """
    from loguru import logger as _logger

    _logger.disable("pico")
    try:
        _run_wizard_body(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            channel=channel,
            skip_sandbox=skip_sandbox,
            skip_channel=skip_channel,
            skip_memory=skip_memory,
            non_interactive=non_interactive,
            yes=yes,
            reset=reset,
            skip_test=skip_test,
        )
    finally:
        _logger.enable("pico")


def _run_wizard_body(
    *,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    channel: Optional[str] = None,
    skip_sandbox: bool = False,
    skip_channel: bool = False,
    skip_memory: bool = False,
    non_interactive: bool = False,
    yes: bool = False,
    reset: bool = False,
    skip_test: bool = False,
) -> None:
    ui._check_tty_or_die(non_interactive)
    state._LANG = configuration._config_language()
    if not non_interactive:
        ui._pick_language()
    ui._handle_existing_config(reset=reset, yes=yes, non_interactive=non_interactive)
    configuration._bootstrap_empty_config()
    if not non_interactive:
        from pico.config.update import set_language

        set_language(state._LANG)
    state.console.print()
    state.console.print(
        Panel(
            ui._t(
                "[bold #fbe23f]✨ Welcome to the Pico setup wizard[/bold #fbe23f]\n\n[dim]We'll configure, in order:[/dim]\n  [#fbe23f]①[/#fbe23f] LLM      [#fbe23f]②[/#fbe23f] Memory + first reply      [#fbe23f]③[/#fbe23f] Run location      [#fbe23f]④[/#fbe23f] Chat channel\n\n[dim]↑↓ select · Enter confirm · Ctrl+C quit anytime — anything already written is kept.[/dim]",
                "[bold #fbe23f]✨ 欢迎使用 Pico 配置向导[/bold #fbe23f]\n\n[dim]我们将依次配置:[/dim]\n  [#fbe23f]①[/#fbe23f] LLM      [#fbe23f]②[/#fbe23f] 记忆 + 首次回复      [#fbe23f]③[/#fbe23f] 运行位置      [#fbe23f]④[/#fbe23f] 聊天渠道\n\n[dim]↑↓ 选择 · Enter 确认 · 随时 Ctrl+C 退出 — 已写入的配置会保留。[/dim]",
            ),
            border_style="#c8a900",
            padding=(1, 2),
        )
    )
    warnings: list[str] = []
    screens: list[Callable[[], object]] = [
        lambda: providers._step1_provider(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            non_interactive=non_interactive,
            warnings=warnings,
            skip_test=skip_test,
        ),
        lambda: memory._step2_memory(
            skip=skip_memory,
            non_interactive=non_interactive,
            main_model=configuration._load_current_default_model(),
            warnings=warnings,
            skip_test=skip_test,
            yes=yes,
        ),
        lambda: execution._step3_sandbox(skip=skip_sandbox, non_interactive=non_interactive),
        lambda: channels._step4_channel(channel=channel, skip=skip_channel, non_interactive=non_interactive),
    ]
    index = 0
    while index < len(screens):
        result = screens[index]()
        if result is state._BACK:
            if index == 0:
                ui._pick_language()
                from pico.config.update import set_language

                set_language(state._LANG)
            else:
                index -= 1
        else:
            index += 1
    ui._print_next_steps(warnings=warnings)


def ensure_configured_or_onboard(*, non_interactive: bool = False) -> bool:
    """Run the wizard when the required config (provider + model) is missing.

    Returns ``True`` if config was already complete (caller proceeds straight
    to the session), ``False`` if the wizard ran (config is now populated). In
    a non-interactive context with missing config, the wizard's TTY check
    will raise — callers on non-TTY paths must guard before invoking.
    """
    if configuration._is_config_populated():
        return True
    run_wizard(non_interactive=non_interactive)
    return False
