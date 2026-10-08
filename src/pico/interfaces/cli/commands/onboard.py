"""Onboarding command: one screen or service responsibility."""

from __future__ import annotations

from typing import Optional

import typer

from pico.interfaces.cli.onboarding import wizard


def register(app: typer.Typer) -> None:
    """Attach the ``onboard`` command to ``app``."""

    @app.command()
    def onboard(
        provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider name (skips Step 1's prompt)"),
        api_key: Optional[str] = typer.Option(None, "--api-key", help="API key for the chosen provider"),
        base_url: Optional[str] = typer.Option(None, "--base-url", help="Custom OpenAI-compatible base URL"),
        model: Optional[str] = typer.Option(None, "--model", help="Default model id (e.g. 'openai/gpt-4o-mini')"),
        channel: Optional[str] = typer.Option(None, "--channel", help="Channel to enable in Step 4"),
        skip_sandbox: bool = typer.Option(False, "--skip-sandbox", help="Skip Step 3 (run location)"),
        skip_channel: bool = typer.Option(False, "--skip-channel", help="Skip Step 4 (channel setup)"),
        skip_memory: bool = typer.Option(False, "--skip-memory", help="Disable Memory in Step 2"),
        non_interactive: bool = typer.Option(
            False, "--non-interactive", help="Run without prompts (requires flags for any missing field)"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip all confirm prompts"),
        reset: bool = typer.Option(
            False,
            "--reset",
            help="Re-run the wizard over an existing config (does not erase it; each step keeps current values as defaults)",
        ),
        skip_test: bool = typer.Option(
            False,
            "--skip-test",
            help="Skip the one-shot test message (avoids a billed call; connectivity is still checked)",
        ),
    ) -> None:
        """Four-step setup: provider → Memory + first Turn → sandbox → channel."""
        wizard.run_wizard(
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
