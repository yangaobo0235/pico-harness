"""Onboarding verification: one screen or service responsibility."""

from __future__ import annotations

import subprocess
import sys
import time

from pico.interfaces.cli.services import DEFAULT_PROBE_MESSAGE


def run_first_turn(*, message: str = DEFAULT_PROBE_MESSAGE, timeout_s: int = 120) -> tuple[str, int | None, float]:
    """Execute the onboarding message through the public Runtime path."""
    from pico.config.loader import get_config_path

    command = [
        sys.executable,
        "-m",
        "pico.interfaces.cli.app",
        "run",
        "-m",
        message,
        "--no-markdown",
        "--no-logs",
        "--config",
        str(get_config_path()),
    ]
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail[-2000:] or f"Runtime Turn exited {completed.returncode}")
    return (completed.stdout.strip() or "Runtime Turn completed.", None, elapsed)
