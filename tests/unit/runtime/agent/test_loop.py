"""Tests for pico.runtime.agent.loop: the control loop behind a single `ask()`."""

import json
from pathlib import Path

import pytest

from pico.integrations.llm.providers.fake import FakeModelClient
from pico.runtime.agent.agent import Pico
from pico.runtime.agent.loop import AgentLoop
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _build_agent(tmp_path: Path, outputs: list[str], **kwargs) -> Pico:
    """Assemble a run over a scripted model, a throwaway workspace and auto approval."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def test_agent_loop_runs_same_control_flow_as_pico_ask(tmp_path: Path) -> None:
    """Driving `AgentLoop` directly reproduces the facade path and leaves a report artifact."""
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = _build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
            "<final>Done.</final>",
        ],
    )

    answer = AgentLoop(agent).run("Inspect hello.txt")

    assert answer == "Done."
    assert agent.current_task_state.status == "completed"
    assert agent.run_store.report_path(agent.current_task_state.run_id).exists()


def test_pico_ask_delegates_to_agent_loop(tmp_path: Path) -> None:
    """`Pico.ask()` is only a facade: the answer must come from the same loop instance."""
    agent = _build_agent(tmp_path, ["<final>Facade works.</final>"])

    assert agent.ask("Use facade") == "Facade works."


def test_agent_loop_reserves_a_final_answer_after_tool_budget_is_exhausted(tmp_path: Path) -> None:
    """A spent tool budget triggers one extra finalization request instead of a limit stop."""
    (tmp_path / "facts.txt").write_text("one\ntwo\nthree\nfour\nfive\nsix\n", encoding="utf-8")
    tool_outputs = [
        f'<tool>{{"name":"read_file","args":{{"path":"facts.txt","start":{line},"end":{line}}}}}</tool>'
        for line in range(1, 7)
    ]
    agent = _build_agent(
        tmp_path,
        [*tool_outputs, "<final>All six facts were inspected.</final>"],
        max_steps=6,
    )

    answer = agent.ask("Inspect all facts and summarize them")

    assert answer == "All six facts were inspected."
    assert agent.current_task_state.status == "completed"
    assert agent.current_task_state.tool_steps == 6
    assert agent.current_task_state.attempts == 7
    trace_path = agent.run_store.trace_path(agent.current_task_state)
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["event"] == "model_requested" and event.get("purpose") == "finalization" for event in trace_events)


def test_agent_loop_persists_model_failure_before_reraising(tmp_path: Path) -> None:
    """A model exception lands in TaskState and the report first, then propagates unchanged."""

    class FailingModelClient:
        supports_prompt_cache = False
        last_completion_metadata = {
            "stop_reason": "max_tokens",
            "content_block_types": ["thinking"],
        }

        def complete(self, *args, **kwargs):
            raise RuntimeError(
                "Anthropic-compatible response ended before a text block "
                "(stop_reason=max_tokens, content_types=thinking)"
            )

    agent = _build_agent(tmp_path, [])
    agent.model_client = FailingModelClient()

    with pytest.raises(RuntimeError, match="ended before a text block"):
        agent.ask("Inspect the tests")

    state = agent.current_task_state
    assert state.status == "failed"
    assert state.stop_reason == "model_error"
    assert state.attempts == 1
    assert agent.run_store.task_state_path(state).exists()
    assert agent.run_store.report_path(state).exists()
    report = agent.run_store.load_report(state.run_id)
    assert report["stop_reason"] == "model_error"
    assert report["prompt_metadata"]["stop_reason"] == "max_tokens"
