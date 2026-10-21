"""Service stop signals must drain async resources rather than kill Python."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pico.interfaces.cli.commands.gateway import _run_with_shutdown_signals


async def test_repeated_stop_drains_cleanup_and_restores_handler(monkeypatch) -> None:
    handlers = {}
    original = signal.getsignal(signal.SIGTERM)
    events = []

    def install(sig, handler):
        previous = handlers.get(sig, original)
        handlers[sig] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)

    async def run():
        try:
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            await asyncio.Event().wait()
        finally:
            events.append("cleanup start")
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            await asyncio.sleep(0)
            events.append("cleanup end")

    await _run_with_shutdown_signals(run)
    assert events == ["cleanup start", "cleanup end"]
    assert handlers[signal.SIGTERM] == original


async def test_external_cancellation_is_not_suppressed() -> None:
    ready = asyncio.Event()
    closed = asyncio.Event()

    async def run():
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    task = asyncio.create_task(_run_with_shutdown_signals(run))
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_service_failure_is_not_suppressed() -> None:
    original = signal.getsignal(signal.SIGTERM)

    async def run():
        raise RuntimeError("service failed")

    with pytest.raises(RuntimeError, match="service failed"):
        await _run_with_shutdown_signals(run)
    assert signal.getsignal(signal.SIGTERM) == original


def test_real_process_stop_runs_async_cleanup(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    closed = tmp_path / "closed"
    code = """
import asyncio, sys
from pathlib import Path
from pico.interfaces.cli.commands.gateway import _run_with_shutdown_signals
async def run():
    Path(sys.argv[1]).write_text('ready')
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(0.02)
        Path(sys.argv[2]).write_text('closed')
asyncio.run(_run_with_shutdown_signals(run))
"""
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[4] / "src")}
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(ready), str(closed)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            **options,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.exists(), (tmp_path / "stderr.log").read_text(encoding="utf-8")
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            assert process.wait(timeout=10) == 0
            assert closed.read_text() == "closed"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
