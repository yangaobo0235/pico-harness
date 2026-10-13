"""Tests for scripts.ci.commit_lint: the Conventional Commits rules behind every message gate."""

from pathlib import Path

from scripts.ci.check_commit_file import main as check_commit_file_main
from scripts.ci.check_pr_title import main as check_pr_title_main
from scripts.ci.commit_lint import CommitLintConfig, check_commit_message, check_pr_body, check_pr_title


def test_accepts_valid_conventional_commit_with_scope() -> None:
    """A typed header with an optional scope and a plain subject passes with no errors."""
    result = check_commit_message("docs(readme): sharpen launch positioning")

    assert result.ok
    assert result.errors == []


def test_rejects_missing_conventional_commit_type() -> None:
    """A subject without `<type>: ` fails the header pattern."""
    result = check_commit_message("update README")

    assert not result.ok
    assert "must match <type>(<scope>): <subject>" in result.errors[0]


def test_rejects_cjk_and_full_width_punctuation() -> None:
    """Non-ASCII messages are refused so commit history stays portable across terminals."""
    result = check_commit_message("docs: 更新 README。")

    assert not result.ok
    assert "must be ASCII-only English" in result.errors


def test_rejects_unknown_commit_type() -> None:
    """Only the registered Conventional Commit types are accepted."""
    result = check_commit_message("style: reorder imports")

    assert not result.ok
    assert result.errors[0].startswith("type must be one of:")


def test_accepts_uppercase_subject() -> None:
    """Subject casing is free; only the type prefix is case-sensitive."""
    result = check_commit_message("docs: Update README")

    assert result.ok
    assert result.errors == []


def test_rejects_trailing_period() -> None:
    """A subject must not end in sentence punctuation."""
    result = check_commit_message("docs: Update README.")

    assert not result.ok
    assert result.errors == ["subject must not end with punctuation"]


def test_rejects_subject_over_commit_limit() -> None:
    """Commit subjects stop at the default 72-character limit."""
    subject = "a" * 73
    result = check_commit_message(f"docs: {subject}")

    assert not result.ok
    assert "subject must be 72 characters or fewer" in result.errors


def test_rejects_fixup_and_merge_subjects() -> None:
    """Fixup and merge headers are rejected outright, before any other rule runs."""
    fixup = check_commit_message("fixup! docs: sharpen launch positioning")
    merge = check_commit_message("Merge branch 'main' into feature")

    assert not fixup.ok
    assert not merge.ok
    assert "fixup/squash commits are not allowed" in fixup.errors
    assert "merge commits are not allowed in PR ranges" in merge.errors


def test_subject_limit_is_configurable() -> None:
    """The same header is judged against whatever limit the caller injects."""
    subject = "a" * 30

    assert not check_commit_message(f"docs: {subject}", CommitLintConfig(subject_limit=20)).ok
    assert check_commit_message(f"docs: {subject}", CommitLintConfig(subject_limit=40)).ok


def test_pr_title_allows_longer_subject_limit() -> None:
    """PR titles get the wider default limit instead of the commit one."""
    subject = "add launch-ready readme and contributor checks"

    assert check_pr_title(f"docs: {subject}", CommitLintConfig(pr_title_subject_limit=90)).ok


def test_pr_title_rejects_subject_over_pr_limit() -> None:
    """The PR-title limit is reported in its own message so the fix is unambiguous."""
    subject = "a" * 91
    result = check_pr_title(f"docs: {subject}", CommitLintConfig(pr_title_subject_limit=90))

    assert not result.ok
    assert "subject must be 90 characters or fewer" in result.errors


def test_pr_body_accepts_ascii_markdown() -> None:
    """A plain ASCII squash body passes without header checks."""
    assert check_pr_body("## Summary\n\nPlain ASCII body - fine.\n").ok


def test_pr_body_rejects_em_dash() -> None:
    """A typographic dash in the body breaks the ASCII-only rule."""
    result = check_pr_body("drops the hint only — empty submits still ignored")

    assert not result.ok
    assert "must be ASCII-only English" in result.errors


def test_pr_body_allows_empty() -> None:
    """An empty body is not a failure; the title still carries the convention."""
    assert check_pr_body("").ok


def test_pr_body_does_not_require_a_conventional_header() -> None:
    """Free-form body text is never judged against the commit header pattern."""
    assert check_pr_body("This PR moves the small tests into the layered tree.\n").ok


def test_commit_file_gate_accepts_valid_message(tmp_path: Path) -> None:
    """The commit-msg hook entry point reads the file and exits 0 for a valid message."""
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("docs: add launch notes\n", encoding="utf-8")

    assert check_commit_file_main([str(message_file)]) == 0


def test_commit_file_gate_rejects_invalid_message(tmp_path: Path) -> None:
    """An invalid message file exits 1 and prints each rule it broke."""
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("update README\n", encoding="utf-8")

    assert check_commit_file_main([str(message_file)]) == 1


def test_commit_file_gate_needs_exactly_one_argument() -> None:
    """Called without a message file the gate reports usage instead of guessing."""
    assert check_commit_file_main([]) == 2


def test_pr_title_gate_skips_when_environment_is_unset(monkeypatch) -> None:
    """Outside a PR context the gate is a no-op rather than a false failure."""
    monkeypatch.delenv("PR_TITLE", raising=False)

    assert check_pr_title_main([]) == 0


def test_pr_title_gate_fails_on_invalid_title_and_body(monkeypatch) -> None:
    """Both the title and the body are judged when the environment carries them."""
    monkeypatch.setenv("PR_TITLE", "update README")
    monkeypatch.setenv("PR_BODY", "正文不是 ASCII")

    assert check_pr_title_main([]) == 1


def test_pr_title_gate_passes_on_valid_title(monkeypatch) -> None:
    """A conventional title exits 0 even when no body is provided."""
    monkeypatch.setenv("PR_TITLE", "test(ci): pin the commit lint rules")
    monkeypatch.delenv("PR_BODY", raising=False)

    assert check_pr_title_main([]) == 0
