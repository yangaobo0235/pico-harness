"""Tests for pico.extensions.evaluation.metrics.aggregates."""

import json
from pathlib import Path

from pico.config.paths import REPORT_FILE_NAME, TRACE_FILE_NAME
from pico.extensions.evaluation.metrics.aggregates import aggregate_benchmark_artifact, aggregate_run_artifacts


def write_benchmark_artifact(path: Path, payload: dict) -> Path:
    """Write a benchmark artifact the way the engine does, so aggregation reads real shapes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_aggregate_benchmark_artifact_prefers_the_summary_task_count(tmp_path: Path) -> None:
    """`summary.total_tasks` wins over the row count, because the summary is the frozen verdict."""
    artifact = write_benchmark_artifact(
        tmp_path / "benchmark-v1.json",
        {
            "summary": {
                "total_tasks": 12,
                "passed": 11,
                "failed": 1,
                "pass_rate": 11 / 12,
                "within_budget": 12,
                "verifier_passes": 11,
            },
            "rows": [{"tool_steps": 2, "attempts": 3, "category": "contract"}],
        },
    )

    metrics = aggregate_benchmark_artifact(artifact)

    assert metrics["task_count"] == 12
    assert metrics["passed"] == 11
    assert metrics["failed"] == 1
    assert metrics["within_budget"] == 12
    assert metrics["avg_tool_steps"] == 2.0
    assert metrics["avg_attempts"] == 3.0
    assert metrics["category_counts"] == {"contract": 1}


def test_aggregate_benchmark_artifact_falls_back_to_rows_and_yields_zero_means(tmp_path: Path) -> None:
    """Without a summary the row count is the only truth, and an empty run averages to `0.0`."""
    artifact = write_benchmark_artifact(tmp_path / "legacy.json", {"rows": []})

    metrics = aggregate_benchmark_artifact(artifact)

    assert metrics["task_count"] == 0
    assert metrics["avg_tool_steps"] == 0.0
    assert metrics["pass_rate"] == 0.0
    assert metrics["category_counts"] == {}


def test_aggregate_benchmark_artifact_skips_rows_without_a_category(tmp_path: Path) -> None:
    """A blank category is 'not recorded', so it must not appear as a bucket of its own."""
    artifact = write_benchmark_artifact(
        tmp_path / "mixed.json",
        {"summary": {"total_tasks": 2}, "rows": [{"category": "repair"}, {"category": "  "}]},
    )

    assert aggregate_benchmark_artifact(artifact)["category_counts"] == {"repair": 1}


def write_run(tmp_path: Path, run_id: str, report: dict | None = None, events: list[dict] | None = None) -> Path:
    """Create one run directory with the artifacts the runtime would have left behind."""
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    if report is not None:
        (run_dir / REPORT_FILE_NAME).write_text(json.dumps(report), encoding="utf-8")
    if events is not None:
        (run_dir / TRACE_FILE_NAME).write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )
    return run_dir


def test_aggregate_run_artifacts_counts_reports_not_directories(tmp_path: Path) -> None:
    """An empty run directory is not a run, so `run_count` follows the reports present."""
    write_run(tmp_path, "run_empty")
    write_run(
        tmp_path,
        "run_reported",
        report={
            "tool_steps": 4,
            "attempts": 5,
            "stop_reason": "final_answer_returned",
            "prompt_metadata": {"prompt_chars": 900},
        },
    )

    metrics = aggregate_run_artifacts(tmp_path)

    assert metrics["run_count"] == 1
    assert metrics["avg_tool_steps"] == 4.0
    assert metrics["avg_prompt_chars"] == 900.0


def test_aggregate_run_artifacts_falls_back_to_directory_count(tmp_path: Path) -> None:
    """When no report survived, the directory count still shows how many runs were attempted."""
    write_run(tmp_path, "run_a")
    write_run(tmp_path, "run_b")

    assert aggregate_run_artifacts(tmp_path)["run_count"] == 2


def test_aggregate_run_artifacts_reads_tool_and_security_events_from_trace(tmp_path: Path) -> None:
    """Distribution counters come from `tool_executed` lines, keyed only when the field exists."""
    write_run(
        tmp_path,
        "run_1",
        report={"tool_steps": 2, "attempts": 2},
        events=[
            {"event": "run_started", "created_at": "2026-10-13T10:00:00+00:00"},
            {"event": "prompt_built", "duration_ms": 12},
            {"event": "tool_executed", "name": "read_file", "tool_status": "ok", "duration_ms": 3},
            {
                "event": "tool_executed",
                "name": "write_file",
                "tool_status": "rejected",
                "security_event_type": "approval_denied",
                "duration_ms": 1,
            },
            {"event": "run_finished", "created_at": "2026-10-13T10:00:01+00:00", "run_duration_ms": 1000},
        ],
    )

    metrics = aggregate_run_artifacts(tmp_path)

    assert metrics["tool_name_counts"] == {"read_file": 1, "write_file": 1}
    assert metrics["tool_status_counts"] == {"ok": 1, "rejected": 1}
    assert metrics["security_event_counts"] == {"approval_denied": 1}
    assert metrics["avg_run_duration_ms"] == 1000.0
    assert metrics["avg_tool_duration_ms"] == 2.0
    assert metrics["avg_prompt_build_duration_ms"] == 12.0


def test_aggregate_run_artifacts_prefix_reuse_only_counts_explicit_records(tmp_path: Path) -> None:
    """A report missing `prefix_changed` is neither reuse nor miss, so the rate stays undefined-zero."""
    write_run(tmp_path, "run_old", report={"prompt_metadata": {}})
    write_run(tmp_path, "run_reused", report={"prompt_metadata": {"prefix_changed": False}})

    metrics = aggregate_run_artifacts(tmp_path)

    assert metrics["prefix_reuse_rate"] == 1.0


def test_aggregate_run_artifacts_ratios_cache_tokens_over_total_input(tmp_path: Path) -> None:
    """`cached_token_ratio` compares summed tokens, not the average of per-run ratios."""
    write_run(
        tmp_path, "run_a", report={"prompt_metadata": {"cached_tokens": 900, "input_tokens": 1000, "cache_hit": True}}
    )
    write_run(
        tmp_path, "run_b", report={"prompt_metadata": {"cached_tokens": 100, "input_tokens": 1000, "cache_hit": False}}
    )

    metrics = aggregate_run_artifacts(tmp_path)

    assert metrics["cached_token_ratio"] == 0.5
    assert metrics["cache_hit_rate"] == 0.5
    assert metrics["avg_cached_tokens"] == 500.0
