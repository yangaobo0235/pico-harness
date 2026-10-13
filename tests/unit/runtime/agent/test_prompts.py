"""Tests for pico.runtime.agent.prompts: turning raw model text into runtime actions.

The cases drive the control loop, but each one locks a parsing decision: an empty response, a
malformed tool payload, and an XML-style `<tool>` tag with a body element.
"""

from pathlib import Path
from typing import Any

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


def test_agent_retries_after_empty_model_output(tmp_path: Path) -> None:
    """An empty completion is parsed as a retry and the notice names the empty response."""
    agent = _build_agent(
        tmp_path,
        [
            "",
            "<final>Recovered after retry.</final>",
        ],
    )

    answer = agent.ask("Do the task")

    assert answer == "Recovered after retry."
    notices = [item["content"] for item in agent.session["history"] if item["role"] == "assistant"]
    assert any("empty response" in item for item in notices)


def test_agent_retries_after_malformed_tool_payload(tmp_path: Path) -> None:
    """A `<tool>` body whose args are not an object is re-asked with a valid-call notice."""
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = _build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":"bad"}</tool>',
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
            "<final>Recovered after malformed tool output.</final>",
        ],
    )

    answer = agent.ask("Inspect hello.txt")

    assert answer == "Recovered after malformed tool output."
    assert any(item["role"] == "tool" and item["name"] == "read_file" for item in agent.session["history"])
    notices = [item["content"] for item in agent.session["history"] if item["role"] == "assistant"]
    assert any("valid <tool> call" in item for item in notices)


def test_agent_accepts_xml_write_file_tool(tmp_path: Path) -> None:
    """An XML-style tool tag with a `<content>` child writes the file body verbatim."""
    agent = _build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="hello.py"><content>print("hi")\n</content></tool>',
            "<final>Done.</final>",
        ],
    )

    answer = agent.ask("Create hello.py")

    assert answer == "Done."
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == 'print("hi")\n'
