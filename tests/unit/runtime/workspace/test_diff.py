"""Tests for pico.runtime.workspace.diff."""

from pathlib import Path

from pico.runtime.workspace.diff import capture_snapshot, diff_snapshots


def test_capture_snapshot_skips_ignored_subtrees(tmp_path: Path) -> None:
    """Version control, caches and Pico's own state are not source changes."""
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "app.pyc").write_bytes(b"\x00")
    state = tmp_path / ".pico" / "sessions"
    state.mkdir(parents=True)
    (state / "session.json").write_text("{}", encoding="utf-8")

    snapshot = capture_snapshot(tmp_path)

    assert list(snapshot) == ["app.py"]


def test_capture_snapshot_records_directories_as_paths_only(tmp_path: Path) -> None:
    """Directories themselves carry no content, so they never appear as changed."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("value = 1\n", encoding="utf-8")

    snapshot = capture_snapshot(tmp_path)

    assert list(snapshot) == ["pkg/mod.py"]


def test_diff_reports_created_modified_and_deleted_in_path_order(tmp_path: Path) -> None:
    """The summary names the change class per path, sorted so two runs compare directly."""
    (tmp_path / "keep.py").write_text("one\n", encoding="utf-8")
    (tmp_path / "gone.py").write_text("two\n", encoding="utf-8")
    before = capture_snapshot(tmp_path)
    (tmp_path / "gone.py").unlink()
    (tmp_path / "keep.py").write_text("changed\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("three\n", encoding="utf-8")

    paths, summaries = diff_snapshots(before, capture_snapshot(tmp_path))

    assert paths == ["gone.py", "keep.py", "new.py"]
    assert summaries == ["deleted:gone.py", "modified:keep.py", "created:new.py"]


def test_diff_is_empty_when_only_mtime_changed(tmp_path: Path) -> None:
    """Digests compare content, so touching a file without editing it is not a change."""
    target = tmp_path / "keep.py"
    target.write_text("same\n", encoding="utf-8")
    before = capture_snapshot(tmp_path)
    target.touch()

    assert diff_snapshots(before, capture_snapshot(tmp_path)) == ([], [])
