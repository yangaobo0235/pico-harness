#!/usr/bin/env python3
"""Run the large-scale experiment set and write every artifact it produces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.extensions.evaluation.metrics.provider_experiments import run_provider_experiments
from pico.extensions.evaluation.metrics.reporting import (
    collect_resume_metrics,
    render_large_scale_experiment_report,
    render_resume_metrics_markdown,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pico large-scale experiments and write all experiment artifacts.")
    parser.add_argument("--benchmark-artifact", required=True, help="Path to benchmark artifact JSON.")
    parser.add_argument("--runs-root", required=True, help="Path to .pico/runs root.")
    parser.add_argument(
        "--provider-benchmark-path",
        default="benchmarks/coding_tasks.json",
        help="Benchmark task source for provider experiments.",
    )
    parser.add_argument(
        "--provider-workspace-root",
        default="artifacts/provider-workspaces",
        help="Workspace root for provider experiment copies.",
    )
    parser.add_argument(
        "--provider-artifact-root",
        default="artifacts/provider-artifacts",
        help="Artifact root for provider benchmark outputs.",
    )
    parser.add_argument("--experiment-mode", choices=("synthetic", "real"), default="synthetic")
    parser.add_argument("--real-provider", choices=("gpt", "claude", "deepseek"), default="gpt")
    parser.add_argument("--memory-repetitions", type=int, default=3)
    parser.add_argument("--large-memory-repetitions", type=int, default=5)
    parser.add_argument("--context-repetitions", type=int, default=5)
    parser.add_argument("--security-repetitions", type=int, default=3)
    parser.add_argument("--provider-output-json", required=True)
    parser.add_argument("--resume-output-json", required=True)
    parser.add_argument("--resume-output-markdown", required=True)
    parser.add_argument("--memory-output-json", required=True)
    parser.add_argument("--context-output-json", required=True)
    parser.add_argument("--security-output-json", required=True)
    parser.add_argument("--final-report-markdown", required=True)
    return parser


def _write_json(path: str, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    provider_payload = run_provider_experiments(
        benchmark_path=args.provider_benchmark_path,
        workspace_root=args.provider_workspace_root,
        artifact_root=args.provider_artifact_root,
    )
    _write_json(args.provider_output_json, provider_payload)

    metrics = collect_resume_metrics(
        args.benchmark_artifact,
        args.runs_root,
        provider_experiments=args.provider_output_json,
        memory_repetitions=args.memory_repetitions,
        large_memory_repetitions=args.large_memory_repetitions,
        context_repetitions=args.context_repetitions,
        security_repetitions=args.security_repetitions,
        experiment_mode=args.experiment_mode,
        real_provider=args.real_provider,
    )

    _write_json(args.resume_output_json, metrics)
    _write_json(args.memory_output_json, metrics["memory_large_experiment"])
    _write_json(args.context_output_json, metrics["context_experiment"])
    _write_json(args.security_output_json, metrics["security_experiment"])

    resume_md = Path(args.resume_output_markdown)
    resume_md.parent.mkdir(parents=True, exist_ok=True)
    resume_md.write_text(render_resume_metrics_markdown(metrics) + "\n", encoding="utf-8")

    final_report = Path(args.final_report_markdown)
    final_report.parent.mkdir(parents=True, exist_ok=True)
    final_report.write_text(render_large_scale_experiment_report(metrics) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
