"""Tests for pico.extensions.evaluation.metrics.reporting."""

from pathlib import Path

from pico.extensions.evaluation.metrics.ablations import (
    run_context_ablation_v2,
    run_memory_ablation_v2,
    run_recovery_ablation_v2,
)
from pico.extensions.evaluation.metrics.reporting import write_benchmark_core_report


def test_write_benchmark_core_report_marks_resume_safe_metrics(tmp_path: Path) -> None:
    """The core report separates resume-safe metrics from the ones needing narrative context."""
    run_context_ablation_v2(tmp_path / "artifacts" / "context-ablation-v2.json", repetitions=1)
    run_memory_ablation_v2(tmp_path / "artifacts" / "memory-ablation-v2.json", repetitions=1)
    run_recovery_ablation_v2(tmp_path / "artifacts" / "recovery-ablation-v2.json", repetitions=1)
    harness_artifact_path = tmp_path / "artifacts" / "harness-regression-v2.json"
    harness_artifact_path.write_text(
        '{"summary":{"total_tasks":12,"pass_rate":1.0,"within_budget_rate":1.0,"verifier_pass_rate":1.0},"failure_category_counts":{}}',
        encoding="utf-8",
    )

    report_path = tmp_path / "docs" / "metrics" / "pico-benchmark-core-report.md"
    report_text = write_benchmark_core_report(
        report_path=report_path,
        harness_artifact_path=harness_artifact_path,
        context_artifact_path=tmp_path / "artifacts" / "context-ablation-v2.json",
        memory_artifact_path=tmp_path / "artifacts" / "memory-ablation-v2.json",
        recovery_artifact_path=tmp_path / "artifacts" / "recovery-ablation-v2.json",
    )

    assert report_path.exists()
    assert "可以安全写进简历的指标" in report_text
    assert "只适合放文档/面试展开的指标" in report_text
    assert "resume_success_rate" in report_text
    assert "memory_hit_rate" in report_text
