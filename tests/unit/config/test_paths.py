"""Tests for pico.config.paths: where workspace state lives and which path spellings are visible.

Pico keeps its own state under a hidden ``.pico/`` directory inside the repository, and tool
output plus memory keys are anchored on canonical paths. These cases lock both facts: internal
state never surfaces through `list_files`, and a file summary is keyed by its canonical spelling
rather than the spelling the model happened to write.
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


def test_file_summary_cache_is_invalidated_on_out_of_band_edit_and_path_spelling(tmp_path: Path) -> None:
    """File summaries are keyed by canonical path and dropped on resume once the file changed."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")
    agent = _build_agent(tmp_path, [])

    agent.memory.set_file_summary("./sample.txt", "sample.txt: alpha")
    agent.memory.remember_file("./sample.txt")
    assert agent.memory.to_dict()["file_summaries"]["sample.txt"]["freshness"]

    assert "sample.txt: alpha" in agent.memory.render_memory_text()
    file_path.write_text("beta\n", encoding="utf-8")

    resumed = Pico.from_session(
        model_client=FakeModelClient([]),
        workspace=agent.workspace,
        session_store=agent.session_store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )

    assert "sample.txt: alpha" not in resumed.memory_text()
    resumed.memory.invalidate_file_summary("sample.txt")
    assert "sample.txt" not in resumed.memory.to_dict()["file_summaries"]


def test_list_files_hides_internal_agent_state(tmp_path: Path) -> None:
    """Directory listings keep ``.pico/`` and VCS internals out of the model-visible tree."""
    agent = _build_agent(tmp_path, [])
    (tmp_path / ".pico").mkdir(exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")

    result = agent.run_tool("list_files", {})

    assert ".pico" not in result
    assert ".git" not in result
    assert "[F] hello.txt" in result
