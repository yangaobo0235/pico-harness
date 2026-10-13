"""Tests for pico.runtime.agent.checkpoints: resume identity and checkpoint validation."""

from pathlib import Path

from pico.integrations.llm.providers.fake import FakeModelClient
from pico.runtime.agent.agent import Pico
from pico.runtime.agent.checkpoints import (
    CHECKPOINT_FULL_VALID_STATUS,
    CHECKPOINT_NONE_STATUS,
    CHECKPOINT_SCHEMA_MISMATCH_STATUS,
    CHECKPOINT_SCHEMA_VERSION,
    current_runtime_identity,
    evaluate_resume_state,
)
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def _build_agent(tmp_path: Path, outputs: list[str] | None = None, **kwargs) -> Pico:
    """Assemble a run whose approval policy defaults to auto but stays overridable via kwargs."""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=FakeModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def test_current_runtime_identity_captures_execution_contract(tmp_path: Path) -> None:
    """The runtime identity carries every field that makes a checkpoint safe to reuse."""
    agent = _build_agent(tmp_path, max_steps=9, max_new_tokens=1024, read_only=True)

    identity = current_runtime_identity(agent)

    assert identity["session_id"] == agent.session["id"]
    assert identity["cwd"] == str(tmp_path)
    assert identity["read_only"] is True
    assert identity["max_steps"] == 9
    assert identity["max_new_tokens"] == 1024
    assert identity["workspace_fingerprint"] == agent.workspace.fingerprint()
    assert identity["tool_signature"] == agent.tool_signature()


def test_evaluate_resume_state_distinguishes_no_checkpoint_full_valid_and_schema_mismatch(tmp_path: Path) -> None:
    """Missing, usable and schema-mismatched checkpoints resolve to three distinct statuses."""
    agent = _build_agent(tmp_path)

    assert evaluate_resume_state(agent)["status"] == CHECKPOINT_NONE_STATUS

    identity = current_runtime_identity(agent)
    agent.session["checkpoints"] = {
        "current_id": "ckpt_valid",
        "items": {
            "ckpt_valid": {
                "checkpoint_id": "ckpt_valid",
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "key_files": [],
                "runtime_identity": identity,
            }
        },
    }
    assert evaluate_resume_state(agent)["status"] == CHECKPOINT_FULL_VALID_STATUS

    agent.session["checkpoints"]["items"]["ckpt_valid"]["schema_version"] = "old"
    assert evaluate_resume_state(agent)["status"] == CHECKPOINT_SCHEMA_MISMATCH_STATUS
