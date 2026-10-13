"""Tests for pico.extensions.evaluation.benchmark: the frozen task card contract."""

from pathlib import Path

import pytest

from pico.extensions.evaluation.benchmark import validate_benchmark


def _task(**overrides: object) -> dict:
    """One valid task card with the given fields replaced, so each case varies one thing."""
    task = {
        "id": "readme_intro",
        "prompt": "Inspect README.",
        "fixture_repo": "bench_repo_readme",
        "allowed_tools": ["read_file"],
        "step_budget": 1,
        "expected_artifact": "README.md",
        "verifier": "python -c 'print(1)'",
        "category": "contract",
    }
    task.update(overrides)
    return task


def _fixture(tmp_path: Path) -> Path:
    """Create the fixture repository a task card points at, without touching the real one."""
    fixture = tmp_path / "bench_repo_readme"
    fixture.mkdir()
    (fixture / "README.md").write_text("demo\n", encoding="utf-8")
    return fixture


def test_validate_benchmark_rejects_unknown_allowed_tool(tmp_path: Path) -> None:
    """Declared tool names are checked against the same legal directory the runtime uses."""
    _fixture(tmp_path)
    benchmark = {"schema_version": 1, "tasks": [_task(allowed_tools=["read_file", "missing_tool"])]}

    with pytest.raises(ValueError, match="unknown allowed_tools entry"):
        validate_benchmark(benchmark, repo_root=tmp_path)


def test_validate_benchmark_rejects_missing_fixture(tmp_path: Path) -> None:
    """A card naming an absent fixture directory fails before any model request is made."""
    benchmark = {"schema_version": 1, "tasks": [_task(fixture_repo="bench_repo_absent")]}

    with pytest.raises(ValueError, match="bench_repo_absent"):
        validate_benchmark(benchmark, repo_root=tmp_path)
