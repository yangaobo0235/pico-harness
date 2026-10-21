"""TUI stop signals must reach the child and restore the parent lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from pico.interfaces.cli.tui import launcher


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_signal_mapping_and_handler_restoration(monkeypatch, platform):
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 1, raising=False)
    monkeypatch.setattr(signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(signal, "SIGHUP", 1, raising=False)
    signals = [signal.SIGINT, signal.SIGTERM, signal.SIGBREAK if platform == "win32" else signal.SIGHUP]
    originals = {sig: object() for sig in signals}
    handlers = originals.copy()
    sent = []
    proc = SimpleNamespace(poll=lambda: None, send_signal=sent.append)

    def install(sig, handler):
        previous = handlers[sig]
        handlers[sig] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)
    with launcher._child_lifecycle(proc, True) as stopped:
        for sig in signals:
            handlers[sig](sig, None)
        assert stopped.is_set()
        assert sent == ([signal.CTRL_BREAK_EVENT] * 3 if platform == "win32" else signals)
        proc.poll = lambda: 130
        handlers[signal.SIGINT](signal.SIGINT, None)
        assert len(sent) == 3  # Ignore a late signal after the child exited.
    assert handlers == originals


def test_host_failure_reaps_child_and_restores_handlers():
    originals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    events = []
    proc = SimpleNamespace(poll=lambda: None, kill=lambda: events.append("kill"), wait=lambda: events.append("wait"))
    with pytest.raises(RuntimeError, match="host failed"), launcher._child_lifecycle(proc, True):
        raise RuntimeError("host failed")
    assert events == ["kill", "wait"]
    assert {sig: signal.getsignal(sig) for sig in originals} == originals


def test_failed_spawn_closes_rpc_listener(monkeypatch, tmp_path):
    listener = SimpleNamespace(
        bind=lambda *_: None,
        listen=lambda *_: None,
        getsockname=lambda: ("127.0.0.1", 12345),
        close=lambda: closed.append(True),
    )
    closed = []
    monkeypatch.setattr(launcher.socket, "socket", lambda *_: listener)

    def fail(*args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(OSError, match="spawn failed"):
        launcher._spawn_with_rpc_socket("missing-node", [], tmp_path)
    assert closed == [True]


_PYTHON_CHILD = """
import json, os, signal, socket, sys, time
from pathlib import Path
ready, closed, mode = sys.argv[1:]
def stop(sig, frame):
    Path(closed).write_text('child cleanup')
    sys.exit(130)
signal.signal(getattr(signal, 'SIGBREAK', signal.SIGINT), stop)
signal.signal(signal.SIGTERM, stop)
if mode == 'rpc':
    host, port = os.environ['PICO_RPC_SOCKET'].rsplit(':', 1)
    conn = socket.create_connection((host, int(port)))
    conn.sendall((os.environ['PICO_RPC_TOKEN'] + '\\n').encode())
    conn.sendall(b'{"jsonrpc":"2.0","id":1,"method":"system.hello"}\\n')
    conn.recv(4096)
Path(ready).write_text('ready')
deadline = time.monotonic() + 12
while time.monotonic() < deadline:
    time.sleep(0.02)
sys.exit(99)
"""


def _exercise_stop(monkeypatch, tmp_path, mode, command):
    ready, closed = tmp_path / "ready", tmp_path / "closed"
    host_closed = tmp_path / "host-closed"
    errors = []
    originals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    async def serve(conn, token, timeout, proc_done):
        reader, writer = await asyncio.open_connection(sock=conn)
        try:
            assert (await reader.readline()).decode().strip() == token
            assert json.loads(await reader.readline())["method"] == "system.hello"
            writer.write(b'{"jsonrpc":"2.0","id":1,"result":{}}\n')
            await writer.drain()
            await proc_done.wait()
            return True
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            host_closed.write_text("host cleanup")

    monkeypatch.setattr(launcher, "_run_rpc_server_until_done", serve)

    def interrupt():
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            assert ready.exists(), "child did not become ready"
            # Same callback as an IDE-raised SIGINT, without broadcasting to
            # pytest's console. This raised ValueError on Windows before the fix.
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        except BaseException as exc:
            errors.append(exc)

    interrupter = threading.Thread(target=interrupt, daemon=True)
    interrupter.start()
    executable, args = command(ready, closed, mode)
    run = launcher.run_subprocess if mode == "diagnostic" else launcher.run_subprocess_with_rpc
    result = run(executable, args, tmp_path)
    interrupter.join(timeout=12)
    assert not interrupter.is_alive()
    assert errors == []
    assert result == 130
    assert closed.read_text() == "child cleanup"
    assert host_closed.exists() == (mode == "rpc")
    assert {sig: signal.getsignal(sig) for sig in originals} == originals


@pytest.mark.parametrize("mode", ["diagnostic", "rpc", "rpc-handshake"])
def test_real_child_stop_and_cleanup(monkeypatch, tmp_path, mode):
    _exercise_stop(
        monkeypatch,
        tmp_path,
        mode,
        lambda ready, closed, mode: (sys.executable, ["-c", _PYTHON_CHILD, str(ready), str(closed), mode]),
    )


@pytest.mark.external_runtime
@pytest.mark.parametrize("mode", ["diagnostic", "rpc", "rpc-handshake"])
def test_real_node_stop_and_cleanup(monkeypatch, tmp_path, mode):
    root = Path(__file__).resolve().parents[4]
    node = shutil.which("node")
    tsx = root / "node_modules/tsx/dist/loader.mjs"
    if node is None or not tsx.exists():
        pytest.skip("requires Node and the workspace's npm dependencies")
    graceful = (root / "apps/tui/src/platform/gracefulExit.ts").as_uri()
    child = tmp_path / "child.mjs"
    child.write_text(
        f"""
import {{ setupGracefulExit }} from {json.dumps(graceful)};
import {{ writeFileSync }} from 'node:fs';
import {{ createConnection }} from 'node:net';
const [ready, closed, mode] = process.argv.slice(2);
setupGracefulExit({{ cleanups: [() => writeFileSync(closed, 'child cleanup')] }});
setTimeout(() => process.exit(99), 12000);
if (mode === 'rpc') {{
  const [host, port] = process.env.PICO_RPC_SOCKET.split(':');
  const socket = createConnection({{ host, port: Number(port) }});
  socket.on('connect', () => socket.write(process.env.PICO_RPC_TOKEN + '\\n' +
    JSON.stringify({{jsonrpc:'2.0', id:1, method:'system.hello'}}) + '\\n'));
  socket.once('data', () => writeFileSync(ready, 'ready'));
}} else {{
  writeFileSync(ready, 'ready');
}}
""",
        encoding="utf-8",
    )
    _exercise_stop(
        monkeypatch,
        tmp_path,
        mode,
        lambda ready, closed, mode: (node, ["--import", tsx.as_uri(), str(child), str(ready), str(closed), mode]),
    )


@pytest.mark.external_runtime
def test_node_startup_failure_still_exits_with_error(tmp_path):
    root = Path(__file__).resolve().parents[4]
    node = shutil.which("node")
    tsx = root / "node_modules/tsx/dist/loader.mjs"
    if node is None or not tsx.exists():
        pytest.skip("requires Node and the workspace's npm dependencies")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    entry = (root / "apps/tui/src/entry.tsx").as_uri()
    script = f"Object.defineProperty(process.stdin, 'isTTY', {{value:true}}); await import({json.dumps(entry)});"
    env = {key: value for key, value in os.environ.items() if not key.startswith("PICO_")}
    env.update(PICO_HOME=str(tmp_path), PICO_RPC_SOCKET=f"127.0.0.1:{port}", PICO_RPC_TOKEN="synthetic-startup-only")
    result = subprocess.run(
        [node, "--import", tsx.as_uri(), "--input-type=module", "-e", script],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 1, result.stderr
    assert "RPC startup failed: connect ECONNREFUSED" in result.stderr
