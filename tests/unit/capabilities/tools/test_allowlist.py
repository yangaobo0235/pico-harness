"""Tests for pico.capabilities.tools allowlist enforcement."""

from pathlib import Path

import pytest

from pico.integrations.llm.providers.fake import FakeModelClient
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _build_agent(tmp_path: Path, allowed_tools: list[str] | None = None) -> Pico:
    """Assemble a run with an optional tool allowlist; None exposes every built-in tool."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=FakeModelClient(["<final>Done.</final>"]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        allowed_tools=allowed_tools,
    )


def test_allowed_tools_filter_prompt_and_reject_direct_execution(tmp_path: Path) -> None:
    """The allowlist trims the advertised tool directory and rejects calls that bypass the prompt."""
    agent = _build_agent(tmp_path, allowed_tools=["read_file"])

    prompt = agent.prompt("Read the README")

    assert "- read_file(" in prompt
    assert "- run_shell(" not in prompt
    assert (
        agent.run_tool("run_shell", {"command": "echo hi", "timeout": 20})
        == "error: tool 'run_shell' is not allowed in this run"
    )


def test_allowed_tools_reject_unknown_tool_at_construction(tmp_path: Path) -> None:
    """An unknown tool name fails at construction instead of silently shrinking the tool set."""
    with pytest.raises(ValueError, match="unknown allowed tool"):
        _build_agent(tmp_path, allowed_tools=["read_file", "missing_tool"])
