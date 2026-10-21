from pathlib import Path

import pytest

from pico.application import sessions
from pico.runtime.sessions.service import SessionManager


def test_missing_export_does_not_create_a_session(tmp_path: Path):
    manager = SessionManager(tmp_path)
    assert sessions.export_session(manager, "missing").status == "not_found"
    assert manager.list_sessions() == []


def test_ambiguous_export_never_writes_an_arbitrary_candidate(tmp_path: Path):
    manager = SessionManager(tmp_path)
    for channel in ("cli", "feishu"):
        session = manager.get_or_create(f"{channel}:same")
        session.add_message("user", "hello")
        manager.save(session)
    output = tmp_path / "export.json"
    result = sessions.export_session(manager, "same", output=output)
    assert result.status == "ambiguous"
    assert set(result.candidates) == {"cli:same", "feishu:same"}
    assert not output.exists()


def test_export_reports_io_and_verification_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("cli:example")
    session.add_message("user", "hello")
    manager.save(session)
    destination = tmp_path / "export.json"
    monkeypatch.setattr(sessions, "verify_export", lambda path: False)
    result = sessions.export_session(manager, "cli:example", output=destination)
    assert result.status == "verification_failed"
    assert result.path == destination

    def fail(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(sessions, "write_portable_export", fail)
    result = sessions.export_session(manager, "cli:example", output=destination)
    assert result.status == "write_failed"
    assert isinstance(result.error, PermissionError)
    assert result.destination == destination
