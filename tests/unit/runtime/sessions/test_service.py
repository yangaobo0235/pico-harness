"""Tests for pico.runtime.sessions.service: session persistence and latest-session lookup."""

import json
from pathlib import Path

from pico.runtime.sessions.service import SessionStore


def test_session_store_saves_loads_and_finds_latest_session(tmp_path: Path) -> None:
    """Sessions round-trip through their own file and `latest()` points at the most recent one."""
    store = SessionStore(tmp_path / ".pico" / "sessions")
    first = {"id": "session_001", "history": [{"role": "user", "content": "first"}]}
    second = {"id": "session_002", "history": [{"role": "user", "content": "second"}]}

    first_path = store.save(first)
    second_path = store.save(second)

    assert first_path == store.path("session_001")
    assert json.loads(first_path.read_text(encoding="utf-8"))["id"] == "session_001"
    assert store.load("session_002") == second
    assert store.latest() == second_path.stem


def test_session_store_latest_is_none_when_empty(tmp_path: Path) -> None:
    """An empty store reports no latest session rather than inventing an identifier."""
    store = SessionStore(tmp_path / ".pico" / "sessions")

    assert store.latest() is None
