"""Onboarding memory: one screen or service responsibility."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from pico.interfaces.cli.onboarding import configuration, providers, state, ui


def _disable_memory_after_setup_problem(message: str, *, non_interactive: bool) -> bool:
    state.console.print(
        ui._t(f"  [red]✗ Myna is not ready:[/red] {message}", f"  [red]✗ Myna 尚未就绪:[/red] {message}")
    )
    if non_interactive:
        state.console.print(
            ui._t(
                "  [dim]Install a compatible myna-memory distribution, or re-run with --skip-memory.[/dim]",
                "  [dim]请安装兼容的 myna-memory distribution,或使用 --skip-memory 重新运行。[/dim]",
            )
        )
        raise typer.Exit(2)
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    action = questionary.select(
        ui._t("Memory cannot start. What next?", "记忆无法启动,接下来怎么做?"),
        choices=[
            questionary.Choice(ui._t("Continue without Memory", "关闭记忆并继续"), value="disable"),
            questionary.Choice(ui._t("Exit and install/fix Myna", "退出并安装或修复 Myna"), value="exit"),
        ],
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if action != "disable":
        raise typer.Exit(2)
    configuration._set_memory_backend(None)
    state.console.print(
        ui._t(
            "  [yellow]○ Memory disabled explicitly; Local Skills still work.[/yellow]",
            "  [yellow]○ 已明确关闭记忆;本地技能仍可使用。[/yellow]",
        )
    )
    return False


def _prepare_myna(*, non_interactive: bool, yes: bool) -> bool:
    """Validate the installed Myna plugin and apply its consent-bound setup."""
    configuration._set_memory_backend("myna")
    from pico.bootstrap.plugins import inspect_memory_backend
    from pico.config.models.features import load_pico_config

    status = inspect_memory_backend(load_pico_config())
    if status.state != "available":
        return _disable_memory_after_setup_problem(
            status.error or "plugin unavailable", non_interactive=non_interactive
        )
    try:
        from myna.integrations.pico import descriptor

        integration = descriptor()
        if getattr(integration, "protocol", None) != "myna.pico-app-integration.v1":
            raise RuntimeError("unsupported Myna setup protocol")
        preview = integration.preview_setup(Path.cwd())
    except Exception as exc:
        return _disable_memory_after_setup_problem(str(exc), non_interactive=non_interactive)
    if not isinstance(preview, dict):
        return _disable_memory_after_setup_problem("invalid setup preview", non_interactive=non_interactive)
    setup_state = preview.get("state")
    if setup_state == "ready":
        state.console.print(
            ui._t(
                f"  [green]✓ Myna ready[/green] [dim]({preview.get('repo_key', 'repository')})[/dim]",
                f"  [green]✓ Myna 已就绪[/green] [dim]({preview.get('repo_key', '当前仓库')})[/dim]",
            )
        )
        return True
    if setup_state != "setup_required":
        return _disable_memory_after_setup_problem("invalid setup preview", non_interactive=non_interactive)
    raw_creates = preview.get("creates") or []
    creates = (
        raw_creates if isinstance(raw_creates, list) and all((isinstance(path, str) for path in raw_creates)) else []
    )
    raw_retrieval = preview.get("retrieval") or {}
    if not isinstance(raw_retrieval, dict):
        return _disable_memory_after_setup_problem("invalid setup preview", non_interactive=non_interactive)
    retrieval = raw_retrieval.get("profile", "unknown")
    state.console.print(
        ui._t(
            "  [dim]Myna will bind only this Git repository. It will not import history or install hooks.[/dim]",
            "  [dim]Myna 只会绑定当前 Git 仓库,不会导入历史或安装 Hook。[/dim]",
        )
    )
    state.console.print(f"  [dim]Workspace:[/dim] {preview.get('workspace')}")
    state.console.print(f"  [dim]Retrieval:[/dim] {retrieval}")
    for path in creates:
        state.console.print(f"  [dim]Create:[/dim] {path}")
    approved = yes
    if not non_interactive and (not yes):
        questionary = ui._require_questionary()
        from pico.interfaces.cli.rendering.styles import PICO_STYLE

        approved = bool(
            questionary.confirm(
                ui._t("Initialize Myna for this repository?", "为当前仓库初始化 Myna?"),
                default=True,
                style=PICO_STYLE,
                qmark=state._QMARK,
            ).ask()
        )
    if not approved:
        if non_interactive:
            state.console.print(
                ui._t(
                    "  [red]Myna setup needs --yes, or use --skip-memory.[/red]",
                    "  [red]Myna 初始化需要 --yes,或使用 --skip-memory。[/red]",
                )
            )
            raise typer.Exit(2)
        configuration._set_memory_backend(None)
        state.console.print(ui._t("  [dim]Memory disabled.[/dim]", "  [dim]已关闭记忆。[/dim]"))
        return False
    token = preview.get("consent_token")
    if not isinstance(token, str) or not token:
        return _disable_memory_after_setup_problem("setup consent is missing", non_interactive=non_interactive)
    try:
        receipt = integration.apply_setup(token)
    except Exception as exc:
        return _disable_memory_after_setup_problem(str(exc), non_interactive=non_interactive)
    if not isinstance(receipt, dict) or receipt.get("state") != "initialized":
        return _disable_memory_after_setup_problem("initialization did not complete", non_interactive=non_interactive)
    state.console.print(
        ui._t(
            f"  [green]✓ Myna initialized[/green] [dim]({receipt.get('repo_key', 'repository')})[/dim]",
            f"  [green]✓ Myna 初始化完成[/green] [dim]({receipt.get('repo_key', '当前仓库')})[/dim]",
        )
    )
    return True


def _step2_memory(
    *,
    skip: bool,
    non_interactive: bool,
    main_model: Optional[str],
    warnings: list[str],
    skip_test: bool = False,
    yes: bool = False,
) -> object:
    """Prepare Memory, then prove the configured Runtime with one real Turn."""
    del main_model
    ui._step_header(2, ui._t("Prepare Memory and meet your agent", "准备记忆并完成首次对话"))
    if skip:
        configuration._set_memory_backend(None)
        state.console.print(
            ui._t(
                "  [dim]Memory disabled explicitly; Local Skills remain available.[/dim]",
                "  [dim]已明确关闭记忆；本地技能仍然可用。[/dim]",
            )
        )
    else:
        _prepare_myna(non_interactive=non_interactive, yes=yes)
    if skip_test:
        state.console.print(
            ui._t(
                "  [dim]First Turn skipped via --skip-test; run pico doctor --probe later.[/dim]",
                "  [dim]已通过 --skip-test 跳过首次 Turn;稍后可运行 pico doctor --probe。[/dim]",
            )
        )
        return None
    result = providers._run_test_probe(
        configuration._default_provider_name(), non_interactive=non_interactive, warnings=warnings
    )
    if result in {"repick", "rekey", "switch"}:
        return state._BACK
    return None
