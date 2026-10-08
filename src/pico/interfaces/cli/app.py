"""Pico CLI entry-point.

This module wires together every top-level command and every subcommand
group. The actual implementations live in per-feature modules:

- Top-level commands (each exposes a ``register(app)`` function):
    - ``run``      → ``src/pico/interfaces/cli/commands/run.py``
    - ``doctor``   → ``src/pico/interfaces/cli/commands/doctor.py``
    - ``evolve``   → ``src/pico/interfaces/cli/commands/evolve.py``
    - ``gateway``  → ``src/pico/interfaces/cli/commands/gateway.py``
    - ``onboard``  → ``src/pico/interfaces/cli/onboarding/wizard.py``
    - ``status``   → ``src/pico/interfaces/cli/commands/status.py``

- Subcommand groups (each exposes a typer ``*_app`` instance):
    - ``channels`` → ``src/pico/interfaces/cli/commands/channels.py``
    - ``cron``     → ``src/pico/interfaces/cli/commands/cron.py``
    - ``provider`` → ``src/pico/interfaces/cli/commands/providers.py``
    - ``sessions`` → ``src/pico/interfaces/cli/commands/sessions.py``
    - ``skills``   → ``src/pico/interfaces/cli/commands/skills.py``

Shared helpers used across multiple command modules live in
``src/pico/interfaces/cli/services.py``.
"""

import os
import sys

# 强制 Windows 控制台使用 UTF-8 编码。
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from rich.console import Console

from pico import __logo__, __version__

app = typer.Typer(
    name="pico",
    help=f"{__logo__} Pico - compact, composable, benchmark-gated Agent Harness with an opt-in evolution path",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} Pico v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
    check: bool = typer.Option(False, "--check", help="Smoke-test the native TUI and exit."),
    dev: bool = typer.Option(False, "--dev", help="Run the native TUI from TypeScript source."),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Force TUI color output: auto | truecolor | 256 | 16 | none.",
    ),
    print_colors: bool = typer.Option(False, "--print-colors", help="Print the resolved TUI color palette and exit."),
    preview_colors: bool = typer.Option(False, "--preview-colors", help="Preview TUI color tokens and exit."),
):
    """Pico - compact, composable, benchmark-gated Agent Harness with an opt-in evolution path.

    Bare ``pico`` runs the startup gate and enters the native TUI.
    """
    if ctx.invoked_subcommand is not None:
        return
    from pico.interfaces.cli.tui.launcher import launch_tui

    launch_tui(
        check=check,
        dev=dev,
        color=color,
        print_colors=print_colors,
        preview_colors=preview_colors,
    )


# ============================================================================
# 顶层命令注册
# ============================================================================

from pico.interfaces.cli.commands import doctor as doctor_commands
from pico.interfaces.cli.commands import evolve as evolve_commands
from pico.interfaces.cli.commands import gateway as gateway_commands
from pico.interfaces.cli.commands import onboard as onboard_commands
from pico.interfaces.cli.commands import plugins as plugin_commands
from pico.interfaces.cli.commands import run as agent_commands
from pico.interfaces.cli.commands import status as status_commands
from pico.interfaces.cli.commands import tracing as tracing_commands

onboard_commands.register(app)
gateway_commands.register(app)
agent_commands.register(app)
status_commands.register(app)
doctor_commands.register(app)
evolve_commands.register(app)
plugin_commands.register(app)
tracing_commands.register(app)


# ============================================================================
# 子命令注册
# ============================================================================

from pico.interfaces.cli.commands.channels import channels_app
from pico.interfaces.cli.commands.cron import cron_app
from pico.interfaces.cli.commands.providers import provider_app
from pico.interfaces.cli.commands.sandbox import sandbox_app
from pico.interfaces.cli.commands.skills import skill_app

app.add_typer(channels_app, name="channels")
app.add_typer(cron_app, name="cron")
app.add_typer(provider_app, name="provider")
app.add_typer(sandbox_app, name="sandbox", hidden=True)
app.add_typer(skill_app, name="skills")

from pico.interfaces.cli.commands.sessions import session_app

app.add_typer(session_app, name="sessions")


def run() -> None:
    """Console-script entry point.

    Runs the Typer app, then hard-exits past CPython interpreter finalization
    when a native runtime that segfaults at finalization is live (lancedb's
    Rust/tokio background thread — see :mod:`pico.bootstrap.shutdown`). Any command that
    builds the agent loop starts that thread, so guarding here covers them all
    at once. CliRunner invokes ``app`` directly and never reaches this wrapper,
    so in-process test hosts keep normal exit semantics.
    """
    from pico.bootstrap.shutdown import flush_and_hard_exit, lancedb_finalization_hazard
    from pico.config.loader import ConfigReadError

    try:
        app()
    except ConfigReadError as exc:
        # 写配置命令（channels/provider/onboard）遇到无法解析的配置。写入层已拒绝操作
        # （文件未改动）；在此统一为所有命令清晰展示一次，而不是输出回溯。
        from rich.console import Console

        Console(stderr=True).print(f"[red]✗[/red] {exc}")
        raise SystemExit(1) from exc
    except SystemExit as exc:
        code = exc.code
        if not isinstance(code, int):
            code = 0 if code is None else 1
        if lancedb_finalization_hazard():
            flush_and_hard_exit(code)
        raise


if __name__ == "__main__":
    run()
