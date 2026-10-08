"""Onboarding execution: one screen or service responsibility."""

from __future__ import annotations

from typing import Any

import typer

from pico.interfaces.cli.onboarding import configuration, state, ui


def _probe_boxlite() -> tuple[bool, str]:
    """Probe boxlite availability. Returns ``(ok, reason)``.

    ``reason`` ∈ ``"ok"`` / ``"missing"`` / ``"error"``. The runtime import is
    the same availability gate ``build_executor`` uses for the boxlite backend.
    """
    state.console.print(ui._t("  [dim]⏳ Checking sandbox availability…[/dim]", "  [dim]⏳ 正在检测沙箱可用性…[/dim]"))
    try:
        from importlib import import_module

        import_module("boxlite")
    except ImportError:
        return (False, "missing")
    except Exception:
        return (False, "error")
    return (True, "ok")


def _step3_sandbox(*, skip: bool, non_interactive: bool) -> object:
    """Step 3 — choose run location (host / boxlite sandbox)."""
    ui._step_header(3, ui._t("Choose where Pico runs code / commands", "选择 Pico 运行代码 / 命令的位置"))
    if skip or non_interactive:
        state.console.print(
            ui._t("  [dim]Keeping run location: host (direct).[/dim]", "  [dim]保持运行位置:本机直接运行。[/dim]")
        )
        return None
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    current = configuration._current_sandbox_backend()
    choices: list[Any] = []
    if current != "none":
        choices.append(
            questionary.Choice(ui._t("Keep current: sandbox (boxlite)", "沿用当前:沙箱(boxlite)"), value="keep")
        )
    choices.extend(
        [
            questionary.Choice(
                ui._t(
                    "Host (direct) — simplest, runs right on your machine", "本机直接运行 — 最简单,直接在你的电脑上执行"
                ),
                value="none",
            ),
            questionary.Choice(
                ui._t(
                    "Sandbox isolation (boxlite) — isolated in a lightweight VM, safer (needs platform support)",
                    "沙箱隔离(boxlite)— 用轻量虚拟机隔离,更安全,需环境支持",
                ),
                value="boxlite",
            ),
            questionary.Choice(ui._t("Back", "返回"), value=state._BACK),
        ]
    )
    picked = questionary.select(
        ui._t("Run location:", "运行位置:"), choices=choices, style=PICO_STYLE, qmark=state._QMARK
    ).ask()
    if picked is None:
        raise typer.Exit(1)
    if picked is state._BACK:
        return state._BACK
    if picked == "keep":
        return None
    if picked == "none":
        configuration._persist_sandbox_backend("none")
        state.console.print(
            ui._t("  [green]✓ Running directly on the host.[/green]", "  [green]✓ 将在本机直接运行。[/green]")
        )
        return None
    while True:
        ok, reason = _probe_boxlite()
        if ok:
            configuration._persist_sandbox_backend("boxlite")
            state.console.print(
                ui._t(
                    "  [green]✓ Sandbox available. Using default resources (2 CPU / 2 GB / network); tune in the config file if needed.[/green]",
                    "  [green]✓ 沙箱可用。将使用默认资源(2 CPU / 2 GB / 联网);如需调整可改配置文件。[/green]",
                )
            )
            return None
        if reason == "missing":
            state.console.print(
                ui._t(
                    "  [yellow]✗ Sandbox runtime (boxlite) isn't installed.[/yellow]\n  [dim]Install it, then choose “Retry after install”. Source checkout: uv sync --extra sandbox. Tool install: uv tool install --force 'pico-harness\\[channels,sandbox]'[/dim]",
                    "  [yellow]✗ 未安装沙箱运行时(boxlite)。[/yellow]\n  [dim]先安装,再选「安装后重试」。源码 checkout: uv sync --extra sandbox。工具安装: uv tool install --force 'pico-harness\\[channels,sandbox]'[/dim]",
                )
            )
        else:
            state.console.print(
                ui._t(
                    "  [yellow]✗ Sandbox runtime (boxlite) is installed but failed to start.[/yellow]\n  [dim]Your machine may lack the required virtualization support. Fall back to host, or check the boxlite setup docs.[/dim]",
                    "  [yellow]✗ 沙箱运行时(boxlite)已安装,但启动失败。[/yellow]\n  [dim]可能本机缺少所需的虚拟化支持。可退回本机运行,或查阅 boxlite 安装文档。[/dim]",
                )
            )
        choice = ui._failure_choice(
            [
                (ui._t("Fall back to host", "退回本机运行"), "host"),
                (ui._t("Retry after install", "安装后重试"), "retry"),
                (ui._t("Skip", "跳过"), "skip"),
            ],
            non_interactive=non_interactive,
        )
        if choice == "retry":
            continue
        if choice == "host":
            configuration._persist_sandbox_backend("none")
            state.console.print(
                ui._t("  [green]✓ Running directly on the host.[/green]", "  [green]✓ 将在本机直接运行。[/green]")
            )
        return None
