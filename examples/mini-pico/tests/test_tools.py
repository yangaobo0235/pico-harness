"""Tests for mini_pico.tools and mini_pico.tool_executor."""

from mini_pico.tool_executor import ToolExecutor
from mini_pico.tools import TOOL_SPECS, tool_signature
from mini_pico.workspace import Workspace, clip


def test_tools_read_search_list_and_reject_path_escape(tmp_path):
    """Read-only tools answer from the workspace, and a path climbing out is refused before any read."""
    (tmp_path / "README.md").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("beta note\n", encoding="utf-8")
    executor = ToolExecutor(Workspace.build(tmp_path))

    assert "# README.md" in executor.execute("read_file", {"path": "README.md"}).content
    assert "notes.txt:1:beta note" in executor.execute("search", {"pattern": "beta", "path": "."}).content
    assert "[F] README.md" in executor.execute("list_files", {"path": "."}).content
    escaped = executor.execute("read_file", {"path": "../outside.txt"})
    assert escaped.metadata["tool_status"] == "rejected"
    assert "path escapes workspace" in escaped.content


def test_risky_tools_write_patch_and_respect_approval_policy(tmp_path):
    """Write and patch report the affected path, and `never` refuses them without touching the file."""
    workspace = Workspace.build(tmp_path)
    executor = ToolExecutor(workspace)

    write = executor.execute("write_file", {"path": "sample.txt", "content": "alpha beta\n"})
    assert write.metadata["workspace_changed"] is True
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "alpha beta\n"

    patch = executor.execute("patch_file", {"path": "sample.txt", "old_text": "beta", "new_text": "gamma"})
    assert patch.metadata["workspace_changed"] is True
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "alpha gamma\n"

    denied = ToolExecutor(workspace, approval_policy="never").execute(
        "write_file", {"path": "blocked.txt", "content": "nope"}
    )
    assert denied.metadata["tool_status"] == "rejected"
    assert "approval denied" in denied.content
    assert not (tmp_path / "blocked.txt").exists()


def test_tool_catalog_is_the_prompt_surface(tmp_path):
    """Catalog order, risk flags and schema text are what the model reads, so they stay verbatim."""
    assert list(TOOL_SPECS) == ["list_files", "read_file", "search", "write_file", "patch_file"]
    assert [name for name, spec in TOOL_SPECS.items() if spec.risky] == ["write_file", "patch_file"]
    lines = tool_signature().splitlines()
    assert lines[0] == '- list_files (read-only) {"path": "str=."}: List files in the workspace.'
    assert lines[-1] == (
        '- patch_file (risky) {"path": "str", "old_text": "str", "new_text": "str"}: '
        "Replace one exact text block in a file."
    )
    assert len(lines) == len(TOOL_SPECS)


def test_bad_arguments_are_reported_as_the_tool_own_rule(tmp_path):
    """Validation failures come back as readable text, never as a Python traceback."""
    (tmp_path / "notes.txt").write_text("dup dup\n", encoding="utf-8")
    executor = ToolExecutor(Workspace.build(tmp_path))

    missing_key = executor.execute("read_file", {})
    assert missing_key.metadata["tool_status"] == "rejected"
    assert missing_key.metadata["tool_error_code"] == "invalid_arguments"
    assert missing_key.content.startswith("error: invalid arguments for read_file")

    bad_range = executor.execute("read_file", {"path": "notes.txt", "start": 0})
    assert "invalid line range" in bad_range.content

    ambiguous = executor.execute("patch_file", {"path": "notes.txt", "old_text": "dup", "new_text": "x"})
    assert "old_text must occur exactly once, found 2" in ambiguous.content
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "dup dup\n"

    empty_pattern = executor.execute("search", {"pattern": "   "})
    assert "pattern must not be empty" in empty_pattern.content


def test_metadata_keys_are_a_fixed_vocabulary(tmp_path):
    """Every branch returns the same metadata keys, so trace events stay diffable across runs."""
    executor = ToolExecutor(Workspace.build(tmp_path))
    expected = ["affected_paths", "read_only", "tool_error_code", "tool_name", "tool_status", "workspace_changed"]
    cases = [
        ("nope", {}),
        ("read_file", {"path": "missing.txt"}),
        ("write_file", {"path": "w.txt", "content": "x"}),
        ("list_files", {"path": "."}),
    ]
    for name, args in cases:
        assert sorted(executor.execute(name, args).metadata) == expected


def test_clip_keeps_the_truncated_length_visible():
    """Truncation says how much was dropped instead of just ending the text."""
    assert clip("short") == "short"
    assert clip("abcdef", 3) == "abc\n...[truncated 3 chars]"
    assert clip(12345, 3) == "123\n...[truncated 2 chars]"
    assert len(clip("y" * 5000)) < 4100
