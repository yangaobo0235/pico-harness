"""Tests for pico.runtime.workspace.snapshot."""

from pathlib import Path

from pico.runtime.workspace.snapshot import WorkspaceContext, is_ignored


def build(tmp_path: Path) -> WorkspaceContext:
    """Collect a snapshot for a directory that is deliberately not a Git repository."""
    return WorkspaceContext.build(tmp_path, repo_root_override=tmp_path)


def test_snapshot_falls_back_when_git_is_unavailable(tmp_path: Path) -> None:
    """Outside a repository the snapshot still renders, with placeholders instead of facts."""
    (tmp_path / "README.md").write_text("project readme\n", encoding="utf-8")

    snapshot = build(tmp_path)

    assert snapshot.branch == "-"
    assert snapshot.status == "clean"
    assert snapshot.recent_commits == []
    assert snapshot.repo_root == str(tmp_path.resolve())


def test_snapshot_reads_project_docs_relative_to_the_repo_root(tmp_path: Path) -> None:
    """Doc keys are repo-relative so one file seen from two bases is not listed twice."""
    nested = tmp_path / "sub"
    nested.mkdir()
    (tmp_path / "README.md").write_text("root readme\n", encoding="utf-8")
    (nested / "README.md").write_text("nested readme\n", encoding="utf-8")

    snapshot = WorkspaceContext.build(nested, repo_root_override=tmp_path)

    assert sorted(snapshot.project_docs) == sorted(
        [str(Path("README.md")), str(Path("sub") / "README.md")],
    )


def test_snapshot_text_marks_absent_sections_as_none(tmp_path: Path) -> None:
    """Empty collections print `- none`, so the model reads absence rather than silence."""
    snapshot = build(tmp_path)

    text = snapshot.text()

    assert "- recent_commits:\n- none" in text
    assert "- project_docs:\n- none" in text


def test_fingerprint_is_stable_and_changes_with_a_doc_edit(tmp_path: Path) -> None:
    """The fingerprint is what decides whether a cached prompt prefix can be reused."""
    (tmp_path / "README.md").write_text("first\n", encoding="utf-8")

    before = build(tmp_path).fingerprint()
    same_again = build(tmp_path).fingerprint()
    (tmp_path / "README.md").write_text("second\n", encoding="utf-8")
    after = build(tmp_path).fingerprint()

    assert before == same_again
    assert before != after


def test_is_ignored_checks_any_path_segment() -> None:
    """A single ignored segment hides the whole subtree, including nested caches."""
    assert is_ignored((".git", "objects"))
    assert is_ignored(("src", "__pycache__", "mod.pyc"))
    assert not is_ignored(("src", "pico"))
