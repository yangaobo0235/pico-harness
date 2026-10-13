"""Tests for pico.extensions.evaluation.metrics.ablations."""

from pathlib import Path

from pico.extensions.evaluation.metrics.ablations import (
    run_context_ablation_v2,
    run_memory_ablation_v2,
    run_recovery_ablation_v2,
)


def test_run_context_ablation_v2_writes_expected_artifact(tmp_path: Path) -> None:
    """The context ablation emits a twelve-config artifact with the preservation rate summarized."""
    artifact_path = tmp_path / "artifacts" / "context-ablation-v2.json"

    artifact = run_context_ablation_v2(
        artifact_path=artifact_path,
        repetitions=1,
    )

    assert artifact_path.exists()
    assert artifact["artifact_type"] == "context-ablation-v2"
    assert artifact["config_count"] == 12
    assert len(artifact["configs"]) == 12
    assert "current_request_preserved_rate" in artifact["summary"]


def test_run_memory_ablation_v2_writes_expected_artifact(tmp_path: Path) -> None:
    """The memory ablation covers twelve tasks across the three memory variants."""
    artifact_path = tmp_path / "artifacts" / "memory-ablation-v2.json"

    artifact = run_memory_ablation_v2(
        artifact_path=artifact_path,
        repetitions=1,
    )

    assert artifact_path.exists()
    assert artifact["artifact_type"] == "memory-ablation-v2"
    assert artifact["task_count"] == 12
    assert set(artifact["variants"]) == {"memory_on", "memory_off", "memory_irrelevant"}
    assert "memory_hit_rate" in artifact["variants"]["memory_on"]


def test_run_recovery_ablation_v2_writes_expected_artifact(tmp_path: Path) -> None:
    """The recovery ablation contrasts resume on and off over the ten recovery tasks."""
    artifact_path = tmp_path / "artifacts" / "recovery-ablation-v2.json"

    artifact = run_recovery_ablation_v2(
        artifact_path=artifact_path,
        repetitions=1,
    )

    assert artifact_path.exists()
    assert artifact["artifact_type"] == "recovery-ablation-v2"
    assert artifact["task_count"] == 10
    assert set(artifact["variants"]) == {"resume_enabled", "resume_disabled"}
    assert set(artifact["variants"]["resume_enabled"]["summary"]) >= {
        "resume_success_rate",
        "stale_reanchor_rate",
        "workspace_drift_detection_rate",
        "resume_false_accept_rate",
    }
