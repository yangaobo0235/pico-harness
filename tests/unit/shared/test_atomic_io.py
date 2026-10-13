"""Tests for pico.shared.atomic_io."""

import json
from pathlib import Path

from pico.shared.atomic_io import append_json_line, write_json_atomic


def test_write_json_atomic_creates_missing_parents(tmp_path: Path) -> None:
    """A first write builds the directory chain instead of failing on a missing parent."""
    target = tmp_path / "runs" / "run-1" / "task_state.json"

    write_json_atomic(target, {"status": "running"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "running"}


def test_write_json_atomic_leaves_no_temporary_file(tmp_path: Path) -> None:
    """Replacement consumes the scratch file, so a directory diff stays meaningful."""
    target = tmp_path / "report.json"

    write_json_atomic(target, {"b": 1, "a": 2})

    assert [path.name for path in tmp_path.iterdir()] == ["report.json"]


def test_write_json_atomic_sorts_keys_by_default(tmp_path: Path) -> None:
    """Sorted keys make two runs of the same content byte-comparable."""
    target = tmp_path / "state.json"

    write_json_atomic(target, {"z": 1, "a": 2})

    assert target.read_text(encoding="utf-8").startswith('{\n  "a": 2,\n  "z": 1')


def test_write_json_atomic_can_keep_insertion_order(tmp_path: Path) -> None:
    """Session files keep their order so the history reads chronologically on disk."""
    target = tmp_path / "session.json"

    write_json_atomic(target, {"z": 1, "a": 2}, sort_keys=False)

    assert target.read_text(encoding="utf-8").startswith('{\n  "z": 1,')


def test_append_json_line_stacks_one_record_per_line(tmp_path: Path) -> None:
    """Trace grows by appending, so a crashed run still leaves the earlier lines readable."""
    target = tmp_path / "trace.jsonl"

    append_json_line(target, {"event": "run_started"})
    append_json_line(target, {"event": "run_finished"})

    lines = target.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["run_started", "run_finished"]


def test_append_json_line_stays_ascii(tmp_path: Path) -> None:
    """Non-ASCII payload is escaped, keeping the record safe for byte-window readers."""
    target = tmp_path / "trace.jsonl"

    append_json_line(target, {"note": "缓存未命中"})

    assert "缓存未命中" not in target.read_text(encoding="utf-8")
    assert json.loads(target.read_text(encoding="utf-8"))["note"] == "缓存未命中"
