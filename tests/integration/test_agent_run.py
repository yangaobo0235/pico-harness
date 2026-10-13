"""Tests for a pico run as a whole: control loop, artifacts, redaction and durable memory.

Each case starts from `Pico.ask()` and inspects what landed on disk under ``.pico/runs`` and
``.pico/memory`` — the trace, task state and report are produced by several layers together, so
they are asserted from the integration side instead of per module.
"""

import json
import os
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


def test_successful_run_persists_run_artifacts_and_stop_reason(tmp_path: Path) -> None:
    """A finished request leaves one run directory with state, trace and report agreeing on the stop reason."""
    (tmp_path / "hello.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    agent = _build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>',
            "<final>Finished.</final>",
        ],
    )

    assert agent.ask("Do the thing") == "Finished."

    runs_root = tmp_path / ".pico" / "runs"
    run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1

    run_dir = run_dirs[0]
    task_state = json.loads((run_dir / "task_state.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    trace_lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()

    assert task_state["task_id"] != task_state["run_id"]
    assert run_dir.name == task_state["run_id"]
    assert (run_dir / "task_state.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.json").exists()
    assert task_state["stop_reason"] == "final_answer_returned"
    assert task_state["final_answer"] == "Finished."
    assert report["stop_reason"] == "final_answer_returned"
    assert report["task_state"]["stop_reason"] == "final_answer_returned"
    assert report["run_id"] == task_state["run_id"]
    trace_events = [json.loads(line)["event"] for line in trace_lines]
    assert trace_events[0] == "run_started"
    assert trace_events[-1] == "run_finished"
    assert trace_events.count("prompt_built") == 2
    assert "tool_executed" in trace_events


def test_trace_and_report_redact_secret_env_values(tmp_path: Path) -> None:
    """Secret values reaching a tool call are masked in the trace and the report."""
    secret = "sk-test-secret-123"
    # 只声明追加一个敏感变量，不清空整个环境：`shell=True` 需要平台 shell 变量
    # （Windows 上是 COMSPEC），清空后命令连不上 shell，与脱敏行为无关。
    with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False):
        agent = _build_agent(
            tmp_path,
            [
                '<tool>{"name":"run_shell","args":{"command":"echo sk-test-secret-123","timeout":20}}</tool>',
                "<final>Masked.</final>",
            ],
        )

        assert agent.ask("Mask the secret") == "Masked."

    runs_root = tmp_path / ".pico" / "runs"
    run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1

    run_dir = run_dirs[0]
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    report_text = (run_dir / "report.json").read_text(encoding="utf-8")
    trace_events = [json.loads(line) for line in trace_text.splitlines()]

    assert secret not in trace_text
    assert secret not in report_text

    prompt_events = [event for event in trace_events if event["event"] == "prompt_built"]
    assert prompt_events
    assert prompt_events[0]["prompt_metadata"]["secret_env_count"] >= 1
    assert "OPENAI_API_KEY" in prompt_events[0]["prompt_metadata"]["secret_env_names"]

    tool_events = [event for event in trace_events if event["event"] == "tool_executed"]
    assert tool_events
    assert "<redacted>" in tool_events[0]["args"]["command"]
    assert "<redacted>" in tool_events[0]["result"]


def test_prompt_budget_metadata_records_budget_decisions(tmp_path: Path) -> None:
    """The `prompt_built` event reports which notes and turns survived the section budgets."""
    agent = _build_agent(tmp_path, ["<final>Done.</final>"])
    agent.memory.append_note(
        "alpha episodic note " + ("A" * 120), tags=("recall",), created_at="2026-04-07T10:00:00+00:00"
    )
    agent.memory.append_note("beta episodic recall note " + ("B" * 120), created_at="2026-04-07T10:01:00+00:00")
    agent.memory.append_note(
        "gamma episodic note " + ("C" * 120), tags=("recall",), created_at="2026-04-07T10:02:00+00:00"
    )

    for index in range(4):
        agent.record(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"history-{index}-" + ("A" * 240),
                "created_at": f"2026-04-07T10:0{index}:00+00:00",
            }
        )

    agent.context_manager.total_budget = 1000
    agent.context_manager.section_budgets = {
        "prefix": 80,
        "memory": 80,
        "relevant_memory": 80,
        "history": 80,
    }

    assert agent.ask("recall") == "Done."

    trace_events = [
        json.loads(line)
        for line in (agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines())
    ]
    prompt_events = [event for event in trace_events if event["event"] == "prompt_built"]
    assert prompt_events
    metadata = prompt_events[0]["prompt_metadata"]
    relevant_section = agent.model_client.prompts[0].split("Relevant memory:\n", 1)[1].split("\n\nTranscript:", 1)[0]

    assert metadata["relevant_memory"]["selected_count"] == 3
    assert len(metadata["relevant_memory"]["rendered_notes"]) == 3
    assert len([line for line in relevant_section.splitlines() if line.startswith("- ")]) == 3
    assert "alpha episodic" in relevant_section
    assert "beta episodic" in relevant_section
    assert "gamma episodic" in relevant_section
    assert metadata["current_request"]["text"] == "recall"
    assert metadata["current_request"]["rendered_chars"] == len("recall")


def test_agent_creates_checkpoint_when_context_reduction_happens_and_artifacts_only_reference_it(
    tmp_path: Path,
) -> None:
    """Context reduction writes a checkpoint, and the artifacts carry only its identifier."""
    agent = _build_agent(tmp_path, ["<final>Done after checkpoint.</final>"])
    for index in range(10):
        agent.record(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"history-{index}-" + ("A" * 260),
                "created_at": f"2026-04-07T10:{index:02d}:00+00:00",
            }
        )
    agent.memory.append_note(
        "checkpoint note " + ("B" * 220), tags=("checkpoint",), created_at="2026-04-07T11:00:00+00:00"
    )
    agent.context_manager.total_budget = 900
    agent.context_manager.section_budgets = {
        "prefix": 120,
        "memory": 120,
        "relevant_memory": 120,
        "history": 160,
    }

    assert agent.ask("Resume the long task") == "Done after checkpoint."

    checkpoint_state = agent.session["checkpoints"]
    checkpoint = checkpoint_state["items"][checkpoint_state["current_id"]]
    assert checkpoint["checkpoint_id"] == checkpoint_state["current_id"]
    assert checkpoint["schema_version"] == "phase1-v1"
    assert checkpoint["current_goal"] == "Resume the long task"
    assert checkpoint["key_files"] == []
    assert checkpoint["current_blocker"] == ""
    assert checkpoint["next_step"]

    task_state = json.loads(agent.run_store.task_state_path(agent.current_task_state).read_text(encoding="utf-8"))
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    trace_events = [
        json.loads(line)
        for line in agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines()
    ]

    assert task_state["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert report["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert report["task_state"]["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert "current_goal" not in task_state
    assert "current_goal" not in report
    checkpoint_events = [event for event in trace_events if event["event"] == "checkpoint_created"]
    assert checkpoint_events
    assert checkpoint_events[-1]["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert "current_goal" not in checkpoint_events[-1]


def test_write_file_trace_records_minimum_tool_contract_fields(tmp_path: Path) -> None:
    """The `tool_executed` event carries risk, status, affected paths and diff summary."""
    agent = _build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"notes.txt","content":"hello\\n"}}</tool>',
            "<final>Done.</final>",
        ],
    )

    assert agent.ask("Create notes.txt") == "Done."

    trace_events = [
        json.loads(line)
        for line in agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines()
    ]
    tool_event = [event for event in trace_events if event["event"] == "tool_executed"][-1]

    assert tool_event["name"] == "write_file"
    assert tool_event["risk_level"] == "high"
    assert tool_event["read_only"] is False
    assert tool_event["tool_status"] == "ok"
    assert tool_event["affected_paths"] == ["notes.txt"]
    assert tool_event["workspace_changed"] is True
    assert tool_event["diff_summary"] == ["created:notes.txt"]


def test_freshness_mismatch_creates_checkpoint_before_model_completion(tmp_path: Path) -> None:
    """A changed key file triggers the checkpoint before the model is asked for the next step."""
    file_path = tmp_path / "runtime.py"
    file_path.write_text("alpha\n", encoding="utf-8")
    agent = _build_agent(tmp_path, ["<final>Resumed.</final>"])
    agent.memory.set_file_summary("runtime.py", "runtime.py: alpha")
    freshness = agent.memory.to_dict()["file_summaries"]["runtime.py"]["freshness"]
    agent.session["checkpoints"] = {
        "current_id": "ckpt_freshness",
        "items": {
            "ckpt_freshness": {
                "checkpoint_id": "ckpt_freshness",
                "parent_checkpoint_id": "",
                "schema_version": "phase1-v1",
                "created_at": "2026-04-14T09:00:00+00:00",
                "current_goal": "Handle freshness mismatch",
                "completed": [],
                "excluded": [],
                "current_blocker": "",
                "next_step": "Re-read runtime.py",
                "key_files": [{"path": "runtime.py", "freshness": freshness}],
                "freshness": {"runtime.py": freshness},
                "summary": "runtime.py changed",
                "runtime_identity": {"workspace_fingerprint": agent.workspace.fingerprint()},
            }
        },
    }
    agent.session_store.save(agent.session)
    file_path.write_text("beta\n", encoding="utf-8")

    assert agent.ask("Continue the task") == "Resumed."

    trace_events = [
        json.loads(line)
        for line in agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines()
    ]
    checkpoint_events = [event for event in trace_events if event["event"] == "checkpoint_created"]

    assert checkpoint_events
    assert checkpoint_events[0]["trigger"] == "freshness_mismatch"


def test_explicit_memory_promotion_persists_durable_memory_topics(tmp_path: Path) -> None:
    """Explicitly requested durable facts are written to topic files and listed in the report."""
    agent = _build_agent(
        tmp_path,
        [
            "<final>Project convention: Use constrained tools instead of guessing.\n"
            "Project convention: Preserve local agent state under .pico/.\n"
            "Decision: Keep durable memory topic-based and lightweight.</final>",
        ],
    )

    answer = agent.ask(
        "Capture the stable facts you already discovered as durable memory. Respond with exactly the long-term facts."
    )

    assert "Project convention:" in answer

    index_path = tmp_path / ".pico" / "memory" / "MEMORY.md"
    conventions_path = tmp_path / ".pico" / "memory" / "topics" / "project-conventions.md"
    decisions_path = tmp_path / ".pico" / "memory" / "topics" / "key-decisions.md"
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))

    assert index_path.exists()
    assert conventions_path.exists()
    assert decisions_path.exists()
    assert "project-conventions" in index_path.read_text(encoding="utf-8")
    assert "Use constrained tools instead of guessing." in conventions_path.read_text(encoding="utf-8")
    assert "Keep durable memory topic-based and lightweight." in decisions_path.read_text(encoding="utf-8")
    assert report["durable_promotions"] == [
        "project-conventions: Use constrained tools instead of guessing.",
        "project-conventions: Preserve local agent state under .pico/.",
        "key-decisions: Keep durable memory topic-based and lightweight.",
    ]


def test_explicit_memory_promotion_supports_chinese_intent_and_labels(tmp_path: Path) -> None:
    """Durable promotion recognizes the Chinese request intent and the Chinese fact labels."""
    agent = _build_agent(
        tmp_path,
        [
            "<final>项目约定：优先使用受约束工具，不要靠猜。\n决策：持久记忆保持轻量、按 topic 管理。</final>",
        ],
    )

    answer = agent.ask("请把下面这些稳定事实记住，作为长期记忆保存下来。")

    assert "项目约定：" in answer

    conventions_path = tmp_path / ".pico" / "memory" / "topics" / "project-conventions.md"
    decisions_path = tmp_path / ".pico" / "memory" / "topics" / "key-decisions.md"

    assert "优先使用受约束工具，不要靠猜。" in conventions_path.read_text(encoding="utf-8")
    assert "持久记忆保持轻量、按 topic 管理。" in decisions_path.read_text(encoding="utf-8")


def test_explicit_memory_promotion_rejects_secret_shaped_and_transient_lines(tmp_path: Path) -> None:
    """Secret-shaped, task-state and noisy lines are rejected from promotion and reported as such."""
    agent = _build_agent(
        tmp_path,
        [
            "<final>Project convention: Use constrained tools instead of guessing.\n"
            "Dependency: API key is sk-live-secret-abc.\n"
            "Decision: Current goal is fix flaky tests.\n"
            "Dependency: stdout: FAIL test_one FAIL test_two FAIL test_three.</final>",
        ],
    )

    agent.ask("Capture these stable facts into durable memory.")

    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    conventions_path = tmp_path / ".pico" / "memory" / "topics" / "project-conventions.md"
    dependency_path = tmp_path / ".pico" / "memory" / "topics" / "dependency-facts.md"

    assert report["durable_promotions"] == [
        "project-conventions: Use constrained tools instead of guessing.",
    ]
    assert report["durable_rejections"] == [
        "dependency-facts:secret_shaped",
        "key-decisions:transient_task_state",
        "dependency-facts:noisy_output",
    ]
    assert "Use constrained tools instead of guessing." in conventions_path.read_text(encoding="utf-8")
    assert not dependency_path.exists()


def test_explicit_memory_promotion_supersedes_matching_durable_fact(tmp_path: Path) -> None:
    """A newer version of the same topic fact replaces the stored one and is reported as superseded."""
    agent = _build_agent(
        tmp_path,
        [
            "<final>Dependency: Python runtime is 3.11.</final>",
            "<final>Dependency: Python runtime is 3.12.</final>",
        ],
    )

    assert (
        agent.ask("Capture this stable dependency fact into durable memory.") == "Dependency: Python runtime is 3.11."
    )
    assert agent.ask("Save the updated dependency fact into durable memory.") == "Dependency: Python runtime is 3.12."

    dependency_path = tmp_path / ".pico" / "memory" / "topics" / "dependency-facts.md"
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    text = dependency_path.read_text(encoding="utf-8")

    assert "Python runtime is 3.12." in text
    assert "Python runtime is 3.11." not in text
    assert report["durable_superseded"] == [
        "dependency-facts: Python runtime is 3.11. -> Python runtime is 3.12.",
    ]


def test_explicit_memory_promotion_dedupes_duplicate_durable_note(tmp_path: Path) -> None:
    """Repeating the same durable fact does not append a second copy to the topic file."""
    agent = _build_agent(
        tmp_path,
        [
            "<final>Project convention: Use constrained tools instead of guessing.</final>",
            "<final>Project convention: Use constrained tools instead of guessing.</final>",
        ],
    )

    agent.ask("Capture the stable fact into durable memory.")
    agent.ask("Capture the stable fact into durable memory again.")

    conventions_path = tmp_path / ".pico" / "memory" / "topics" / "project-conventions.md"
    text = conventions_path.read_text(encoding="utf-8")

    assert text.count("Use constrained tools instead of guessing.") == 1


def test_reviewer_skeleton_docs_exist() -> None:
    """The review pack and architecture docs describing runs and artifacts are still present."""
    review_pack = Path("docs/review-pack/README.md")
    architecture = Path("docs/architecture/overview.md")

    assert review_pack.exists()
    assert architecture.exists()

    review_text = review_pack.read_text(encoding="utf-8")
    assert "项目定位" in review_text
    assert "架构地图" in review_text
    assert "评测证据" in review_text
    assert "一次运行的工件清单" in review_text
    for artifact in ("task_state.json", "trace.jsonl", "report.json"):
        assert artifact in review_text

    architecture_text = architecture.read_text(encoding="utf-8")
    assert "架构与代码归属" in architecture_text
    assert "依赖边界" in architecture_text
    assert "TaskState" in architecture_text
