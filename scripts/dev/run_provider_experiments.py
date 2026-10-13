#!/usr/bin/env python3
"""Run the provider comparison experiments for the benchmark tasks.

真实模型请求会产生费用，因此这条入口只由维护者按预算手工触发，不进入默认回归。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.extensions.evaluation.metrics.provider_experiments import run_provider_experiments


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GPT, Claude, and DeepSeek provider experiments for pico benchmark tasks."
    )
    parser.add_argument("--benchmark-path", default="benchmarks/coding_tasks.json", help="Path to benchmark task JSON.")
    parser.add_argument(
        "--workspace-root",
        default="artifacts/provider-workspaces",
        help="Workspace root for provider experiment copies.",
    )
    parser.add_argument(
        "--artifact-root",
        default="artifacts/provider-artifacts",
        help="Directory to store provider benchmark artifacts.",
    )
    parser.add_argument("--output-json", required=True, help="Path to output provider experiment JSON.")
    parser.add_argument("--max-new-tokens", type=int, default=64, help="Max output tokens per provider run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    payload = run_provider_experiments(
        benchmark_path=args.benchmark_path,
        workspace_root=args.workspace_root,
        artifact_root=args.artifact_root,
        max_new_tokens=args.max_new_tokens,
    )
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
