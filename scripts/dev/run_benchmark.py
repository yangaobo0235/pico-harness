#!/usr/bin/env python3
"""Run the frozen coding-task benchmark with the deterministic scripted model."""

from __future__ import annotations

import argparse

from pico.extensions.evaluation.config import DEFAULT_ARTIFACT_PATH, DEFAULT_HARNESS_REGRESSION_V2_ARTIFACT_PATH
from pico.extensions.evaluation.engine import run_fixed_benchmark, run_harness_regression_v2


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen pico benchmark and print its summary.")
    parser.add_argument("--benchmark-path", default=None, help="Path to benchmark task JSON.")
    parser.add_argument("--artifact-path", default=None, help="Path to write the benchmark artifact JSON.")
    parser.add_argument("--workspace-root", default=None, help="Root for benchmark task workspace copies.")
    parser.add_argument(
        "--regression", action="store_true", help="Run the harness regression track instead of the fixed benchmark."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    options: dict[str, object] = {}
    if args.benchmark_path:
        options["benchmark_path"] = args.benchmark_path
    if args.workspace_root:
        options["workspace_root"] = args.workspace_root

    if args.regression:
        artifact = run_harness_regression_v2(
            artifact_path=args.artifact_path or DEFAULT_HARNESS_REGRESSION_V2_ARTIFACT_PATH, **options
        )
    else:
        artifact = run_fixed_benchmark(artifact_path=args.artifact_path or DEFAULT_ARTIFACT_PATH, **options)

    # 评测返回的是整份工件字典，summary 已经是聚合结果，不再压第二次。
    for key, value in artifact["summary"].items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
