"""Tests for a benchmark task executed end to end by the evaluation engine."""

import json
import subprocess
from pathlib import Path

import pytest

from pico.extensions.evaluation.engine import BenchmarkEvaluator
from pico.integrations.llm.providers.fake import FakeModelClient

#: 任务卡里的 verifier 以 POSIX shell 语义书写；这里探测真实能力，而不是按平台名猜测。
#: 环境不具备条件时说明该范围未验证，不能据此认为评测链路已经通过。
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


@pytest.mark.skipif(not POSIX_VERIFIERS_RUN, reason=POSIX_VERIFIER_REASON)
def test_benchmark_evaluator_applies_allowed_tools_to_runtime_prompt(tmp_path: Path) -> None:
    """A task's allowlist must reach the runtime prompt the captured model client actually sees."""
    fixture = tmp_path / "bench_repo_readme"
    fixture.mkdir()
    (fixture / "README.md").write_text("demo\n", encoding="utf-8")
    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    benchmark_path = benchmark_dir / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tasks": [
                    {
                        "id": "prompt_allowlist",
                        "prompt": "Inspect README.",
                        "fixture_repo": "bench_repo_readme",
                        "allowed_tools": ["read_file"],
                        "step_budget": 1,
                        "expected_artifact": "README.md",
                        # 与冻结任务卡同一种写法：外层双引号交给 shell，内层单引号留给 Python，
                        # 这样 cmd.exe 与 POSIX shell 都能把 `-c` 的参数原样送到解释器。
                        "verifier": "python3 -c \"import pathlib; assert pathlib.Path('README.md').exists()\"",
                        "category": "contract",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    captured_clients = []

    class CaptureModelClient(FakeModelClient):
        def __init__(self):
            super().__init__(["<final>Done.</final>"])
            captured_clients.append(self)

    evaluator = BenchmarkEvaluator(
        benchmark_path=benchmark_path,
        artifact_path=tmp_path / "artifact.json",
        workspace_root=tmp_path / "workspaces",
        model_client_factory=lambda task, workspace: CaptureModelClient(),
    )

    row = evaluator.run_task(evaluator.load()["tasks"][0])

    assert row["status"] == "pass"
    assert "- read_file(" in captured_clients[0].prompts[0]
    assert "- run_shell(" not in captured_clients[0].prompts[0]
