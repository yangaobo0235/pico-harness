"""Tests for pico.extensions.evaluation.engine: the frozen benchmark harness."""

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from pico.extensions.evaluation.artifacts import _current_locale
from pico.extensions.evaluation.benchmark import load_benchmark, summarize_rows
from pico.extensions.evaluation.engine import (
    BenchmarkEvaluator,
    run_fixed_benchmark,
    run_harness_regression_v2,
)

#: 冻结任务卡里的 verifier 以 `python3 -c '...'` 形式书写，只在 POSIX shell 语义下成立。
#: Windows 上 `python3` 是失效的商店别名，cmd.exe 也不把单引号当引号，因此这里探测真实能力
#: 而不是按平台名猜测：环境不具备条件只说明该范围未验证，不能据此判断评测已经通过。
POSIX_VERIFIERS_RUN = (
    subprocess.run(
        "python3 -c 'print(1)'",
        shell=True,
        capture_output=True,
        text=True,
    ).returncode
    == 0
)

POSIX_VERIFIER_REASON = "benchmark verifier cards assume a POSIX shell; this platform cannot run them verbatim"


def test_load_benchmark_validates_fixed_schema() -> None:
    """The shipped benchmark parses with schema v1, twelve tasks and a stable category mix."""
    benchmark = load_benchmark(Path("benchmarks/coding_tasks.json"))

    assert benchmark["schema_version"] == 1
    assert len(benchmark["tasks"]) == 12
    assert Counter(task["category"] for task in benchmark["tasks"]) == {
        "documentation": 2,
        "text-edit": 2,
        "tool-boundary": 3,
        "recovery": 3,
        "durable-contract": 2,
    }
    for task in benchmark["tasks"]:
        assert {
            "id",
            "prompt",
            "fixture_repo",
            "allowed_tools",
            "step_budget",
            "expected_artifact",
            "verifier",
            "category",
        } <= set(task)
        assert isinstance(task["allowed_tools"], list)
        assert task["step_budget"] > 0


def test_load_benchmark_rejects_missing_required_task_fields(tmp_path: Path) -> None:
    """A task without the required keys fails at load instead of surfacing mid-run."""
    benchmark_path = tmp_path / "bad-benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tasks": [
                    {
                        "id": "broken",
                        "prompt": "Missing required task keys.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="required"):
        load_benchmark(benchmark_path)


def test_run_fixed_benchmark_uses_fresh_fixture_copy_and_fresh_run_directory(tmp_path: Path) -> None:
    """Each task runs against a copied fixture and its own run directory, leaving the source fixture alone."""
    artifact_path = tmp_path / "benchmark-v1.json"
    evaluator = BenchmarkEvaluator(
        benchmark_path=Path("benchmarks/coding_tasks.json"),
        artifact_path=artifact_path,
        workspace_root=tmp_path / "workspaces",
    )

    original_fixture = Path("tests/fixtures/bench_repo_patch/sample.txt").read_text(encoding="utf-8")
    artifact = evaluator.run()

    row = next(item for item in artifact["rows"] if item["id"] == "sample_beta_locked")
    copied_fixture = (tmp_path / "workspaces" / row["fixture_copy_relpath"]).resolve()
    run_dir = (tmp_path / "workspaces" / row["run_dir_relpath"]).resolve()

    assert artifact_path.exists()
    assert copied_fixture.exists()
    assert run_dir.exists()
    assert not row["fixture_copy_relpath"].startswith("/")
    assert not row["run_dir_relpath"].startswith("/")
    assert row["initial_history_empty"] is True
    assert row["initial_memory_empty"] is True
    assert row["initial_task_summary_empty"] is True
    assert Path("tests/fixtures/bench_repo_patch/sample.txt").read_text(encoding="utf-8") == original_fixture
    assert "beta-locked" in (copied_fixture / "sample.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(not POSIX_VERIFIERS_RUN, reason=POSIX_VERIFIER_REASON)
def test_run_fixed_benchmark_reports_metadata_and_success_definition(tmp_path: Path) -> None:
    """The artifact pins the reproducibility envelope and the per-row definition of success."""
    artifact_path = tmp_path / "benchmark-v1.json"
    artifact = run_fixed_benchmark(
        benchmark_path=Path("benchmarks/coding_tasks.json"),
        artifact_path=artifact_path,
        workspace_root=tmp_path / "workspaces",
    )

    assert artifact_path.exists()
    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert persisted == artifact

    assert artifact["schema_version"] == 1
    assert artifact["summary"] == {
        "total_tasks": 12,
        "passed": 12,
        "failed": 0,
        "pass_rate": 1.0,
        "within_budget": 12,
        "verifier_passes": 12,
        "within_budget_rate": 1.0,
        "verifier_pass_rate": 1.0,
        "failure_category_counts": {},
    }
    assert artifact["failure_category_counts"] == {}

    reproducibility = artifact["reproducibility"]
    assert reproducibility["model_name"] == "FakeModelClient"
    assert reproducibility["model_version"] == "scripted-deterministic"
    assert reproducibility["fixture_snapshot_id"].startswith("sha256:")
    assert reproducibility["decoding"] == {
        "temperature": 0.0,
        "top_p": 1.0,
        "max_new_tokens": 64,
    }
    assert reproducibility["timezone"] == "Asia/Shanghai"
    # `locale` 只说明这份工件是在什么 locale 下采集的，取值随平台变化（Linux 上常见
    # `C.UTF-8`，Windows 上是 `English_United States.1252` 这类名字），因此断言它确实记录了
    # 当前 locale，而不是锁死某个具体名字。
    assert reproducibility["locale"] == _current_locale()
    assert reproducibility["locale"]

    for row in artifact["rows"]:
        assert not row["fixture_copy_relpath"].startswith("/")
        assert not row["run_dir_relpath"].startswith("/")
        assert not row["task_state_relpath"].startswith("/")
        assert not row["report_relpath"].startswith("/")
        assert row["status"] == "pass"
        assert row["passed"] is True
        assert row["within_budget"] is True
        assert row["verifier_passed"] is True
        assert row["expected_artifact_exists"] is True
        assert row["non_failure_stop_reason"] is True
        assert row["stop_reason"] == "final_answer_returned"


def test_run_fixed_benchmark_covers_recovery_and_durable_contract_rows(tmp_path: Path) -> None:
    """Recovery and durable-contract tasks leave the trace and rejection evidence the rows claim."""
    artifact = run_fixed_benchmark(
        benchmark_path=Path("benchmarks/coding_tasks.json"),
        artifact_path=tmp_path / "benchmark-v1.json",
        workspace_root=tmp_path / "workspaces",
    )

    context_row = next(item for item in artifact["rows"] if item["id"] == "context_reduction_checkpoint")
    durable_row = next(item for item in artifact["rows"] if item["id"] == "durable_promotion_reject")

    trace_path = (tmp_path / "workspaces" / context_row["run_dir_relpath"] / "trace.jsonl").resolve()
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert any(
        event.get("event") == "checkpoint_created" and event.get("trigger") == "context_reduction"
        for event in trace_events
    )
    assert durable_row["report"]["durable_rejections"] == [
        "dependency-facts:secret_shaped",
        "key-decisions:transient_task_state",
    ]


@pytest.mark.skipif(not POSIX_VERIFIERS_RUN, reason=POSIX_VERIFIER_REASON)
def test_run_harness_regression_v2_writes_named_artifact(tmp_path: Path) -> None:
    """The regression track writes its own artifact with the same all-green baseline."""
    artifact_path = tmp_path / "artifacts" / "harness-regression-v2.json"

    artifact = run_harness_regression_v2(
        benchmark_path=Path("benchmarks/coding_tasks.json"),
        artifact_path=artifact_path,
        workspace_root=tmp_path / "workspaces",
    )

    assert artifact_path.exists()
    assert artifact["summary"]["total_tasks"] == 12
    assert artifact["summary"]["pass_rate"] == 1.0
    assert artifact["summary"]["within_budget_rate"] == 1.0
    assert artifact["summary"]["verifier_pass_rate"] == 1.0


@pytest.mark.skipif(not POSIX_VERIFIERS_RUN, reason=POSIX_VERIFIER_REASON)
def test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace() -> None:
    """Even when the workspace root is the repo, row paths resolve against the fixture copy."""
    evaluator = BenchmarkEvaluator(
        benchmark_path=Path("benchmarks/coding_tasks.json"),
        artifact_path=Path("docs/review-pack/benchmark-v1.json"),
        workspace_root=Path("."),
    )

    task = next(item for item in evaluator.load()["tasks"] if item["id"] == "readme_intro_locked")
    row = evaluator.run_task(task)

    assert row["status"] == "pass"
    fixture_copy = Path(row["fixture_copy_relpath"])
    readme_path = fixture_copy / "README.md"
    assert "This fixture is a locked benchmark workspace." in readme_path.read_text(encoding="utf-8")


def test_summarize_rows_counts_failure_categories() -> None:
    """Summarisation counts passes, budget and verifier rates and groups failures by category."""
    summary = summarize_rows(
        [
            {
                "status": "pass",
                "within_budget": True,
                "verifier_passed": True,
                "expected_artifact_exists": True,
                "non_failure_stop_reason": True,
            },
            {
                "status": "fail",
                "within_budget": False,
                "verifier_passed": False,
                "expected_artifact_exists": False,
                "non_failure_stop_reason": False,
                "failure_category": "verifier_failed",
            },
            {
                "status": "fail",
                "within_budget": False,
                "verifier_passed": True,
                "expected_artifact_exists": True,
                "non_failure_stop_reason": False,
                "failure_category": "budget_exceeded",
            },
        ]
    )

    assert summary["total_tasks"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 2
    assert summary["pass_rate"] == pytest.approx(1 / 3)
    assert summary["within_budget"] == 1
    assert summary["verifier_passes"] == 2
    assert summary["failure_category_counts"] == {
        "budget_exceeded": 1,
        "verifier_failed": 1,
    }
