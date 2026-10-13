"""Tests for mini_pico.agent_loop."""

import json

from mini_pico import FakeModelClient, Pico, RunStore, Workspace
from mini_pico.state import TaskState


def test_agent_loop_runs_tool_then_final_and_writes_evidence(tmp_path):
    """One tool step then a final answer: the loop writes state, trace and report in order."""
    (tmp_path / "README.md").write_text("alpha\nbeta\n", encoding="utf-8")
    workspace = Workspace.build(tmp_path)
    run_store = RunStore(tmp_path / ".mini-pico" / "runs")
    agent = Pico(
        model_client=FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>Done.</final>",
            ]
        ),
        workspace=workspace,
        run_store=run_store,
    )

    final = agent.ask("read README")

    assert final == "Done."
    assert len(agent.model_client.prompts) == 2
    assert "Tool result: read_file" in agent.model_client.prompts[1]
    assert "# README.md" in agent.model_client.prompts[1]
    task_state = agent.current_task_state
    run_dir = run_store.run_dir(task_state)
    assert (run_dir / "task_state.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.json").exists()
    events = [json.loads(line)["event"] for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == [
        "run_started",
        "prompt_built",
        "model_requested",
        "model_parsed",
        "tool_executed",
        "prompt_built",
        "model_requested",
        "model_parsed",
        "run_finished",
    ]


def _build_agent(tmp_path, outputs, **kwargs):
    """Assemble an agent over a scratch workspace with a scripted model."""
    (tmp_path / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    run_store = RunStore(tmp_path / ".mini-pico" / "runs")
    agent = Pico(
        model_client=FakeModelClient(outputs),
        workspace=Workspace.build(tmp_path),
        run_store=run_store,
        **kwargs,
    )
    return agent, run_store


def _events(run_store, task_state):
    """Return the recorded trace event names for one run, in write order."""
    lines = (run_store.run_dir(task_state) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_malformed_responses_burn_attempts_and_stop_at_the_retry_limit(tmp_path):
    """Unparseable output costs attempts, not tool steps, and ends in the retry-limit text."""
    agent, run_store = _build_agent(tmp_path, ["chatter"] * 20, max_steps=4)

    final = agent.ask("answer with the protocol")

    assert final == "Stopped after too many malformed model responses."
    task_state = agent.current_task_state
    assert task_state.status == "stopped"
    assert task_state.stop_reason == "retry_limit_reached"
    assert task_state.tool_steps == 0
    assert task_state.attempts == 4 + 3
    assert task_state.final_answer == final
    assert _events(run_store, task_state)[-1] == "run_finished"
    assert [item["content"] for item in agent.history[1:-1]] == ["model returned neither <tool> nor <final>"] * 7
    assert agent.history[-1]["content"] == final


def test_tool_calls_burn_steps_and_stop_at_the_step_limit(tmp_path):
    """Once the tool budget is spent the loop stops, keeping the last known state on disk."""
    tool_call = '<tool>{"name":"list_files","args":{"path":"."}}</tool>'
    agent, run_store = _build_agent(tmp_path, [tool_call] * 10, max_steps=2)

    final = agent.ask("keep listing files")

    assert final == "Stopped after reaching the step limit."
    task_state = agent.current_task_state
    assert task_state.status == "stopped"
    assert task_state.stop_reason == "step_limit_reached"
    assert task_state.tool_steps == 2
    assert task_state.attempts == 2
    assert task_state.last_tool == "list_files"
    persisted = json.loads((run_store.run_dir(task_state) / "task_state.json").read_text(encoding="utf-8"))
    assert persisted == task_state.to_dict()


def test_rejected_tool_call_still_feeds_the_loop_forward(tmp_path):
    """An unknown tool becomes a tool result the model can read, and the run still completes."""
    agent, run_store = _build_agent(
        tmp_path,
        ['<tool>{"name":"nope","args":{}}</tool>', "<final>recovered</final>"],
    )

    final = agent.ask("call a tool that does not exist")

    assert final == "recovered"
    assert agent.history[1]["name"] == "nope"
    assert agent.history[1]["content"] == "error: unknown tool 'nope'"
    assert agent.current_task_state.tool_steps == 1
    assert _events(run_store, agent.current_task_state).count("tool_executed") == 1


def test_task_state_fields_written_by_the_loop_are_a_fixed_vocabulary(tmp_path):
    """`to_dict()` keys and default values are the artifact contract, so they stay spelled as-is."""
    assert [field.name for field in TaskState.__dataclass_fields__.values()] == [
        "run_id",
        "user_request",
        "status",
        "attempts",
        "tool_steps",
        "last_tool",
        "stop_reason",
        "final_answer",
    ]
    state = TaskState.create("demo request")
    assert list(state.to_dict()) == [
        "run_id",
        "user_request",
        "status",
        "attempts",
        "tool_steps",
        "last_tool",
        "stop_reason",
        "final_answer",
    ]
    assert state.to_dict()["status"] == "running"
    assert state.run_id.startswith("run_")

    state.finish_success("answer")
    assert state.status == "completed"
    assert state.stop_reason == "final_answer_returned"
    state.stop_step_limit("step text")
    assert state.stop_reason == "step_limit_reached"
    state.stop_retry_limit("retry text")
    assert state.stop_reason == "retry_limit_reached"
