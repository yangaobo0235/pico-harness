"""Tests for pico.capabilities.tools.executor: the guardrails around every tool call.

All model-initiated tool calls pass through `Pico.run_tool`, which validates arguments, applies
the approval policy, blocks repeated identical calls and classifies the resulting status. These
cases lock those gate invariants rather than the individual tool bodies.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from pico.integrations.llm.providers.fake import FakeModelClient
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _build_workspace(tmp_path: Path) -> WorkspaceContext:
    """Create a minimal repository fixture with a README and return its workspace snapshot."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _build_agent(tmp_path: Path, outputs: list[str], **kwargs: Any) -> Pico:
    """Build an agent over the fixture workspace with a scripted model client."""
    workspace = _build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def test_patch_file_replaces_exact_match(tmp_path: Path) -> None:
    """`patch_file` only rewrites on an exact match and reports the patched path."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello world\n", encoding="utf-8")
    agent = _build_agent(tmp_path, [])

    result = agent.run_tool(
        "patch_file",
        {
            "path": "sample.txt",
            "old_text": "world",
            "new_text": "agent",
        },
    )

    assert result == "patched sample.txt"
    assert file_path.read_text(encoding="utf-8") == "hello agent\n"


def test_invalid_risky_tool_does_not_prompt_for_approval(tmp_path: Path) -> None:
    """Argument validation runs before the approval prompt, so a bad call never asks the user."""
    agent = _build_agent(tmp_path, [], approval_policy="ask")

    with patch("builtins.input") as mock_input:
        result = agent.run_tool("write_file", {})

    assert result.startswith("error: invalid arguments for write_file: 'path'")
    assert 'example: <tool name="write_file"' in result
    mock_input.assert_not_called()


def test_repeated_identical_tool_call_is_rejected(tmp_path: Path) -> None:
    """Two identical tool calls already in history block a third identical one."""
    agent = _build_agent(tmp_path, [])
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "1"})
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "2"})

    result = agent.run_tool("list_files", {})

    assert (
        result == "error: repeated identical tool call for list_files; choose a different tool or return a final answer"
    )


def test_run_shell_nonzero_with_workspace_change_is_recorded_as_partial_success(tmp_path: Path) -> None:
    """A failing shell call that still changed files is reported as `partial_success`."""
    agent = _build_agent(tmp_path, [])

    result = agent.run_tool(
        "run_shell",
        {
            "command": "printf 'changed\\n' > README.md && exit 1",
            "timeout": 20,
        },
    )

    assert "exit_code: 1" in result
    assert agent._last_tool_result_metadata["tool_status"] == "partial_success"
    assert agent._last_tool_result_metadata["affected_paths"] == ["README.md"]
    assert agent._last_tool_result_metadata["workspace_changed"] is True
