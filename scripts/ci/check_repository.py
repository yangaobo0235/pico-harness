#!/usr/bin/env python3
"""Fail closed when the tracked release tree crosses the publication boundary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterable

ALLOWED_ROOT_DIRECTORIES = {"LICENSES", "apps", "benchmarks", "docs", "examples", "scripts", "src", "tests"}
ALLOWED_ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "LICENSE",
    "CONTRIBUTING.md",
    "Makefile",
    "NOTICES.md",
    "README.md",
    "SECURITY.md",
    "commitlint.config.cjs",
    "eslint.base.mjs",
    "hatch_build.py",
    "package-lock.json",
    "package.json",
    "prettier.config.mjs",
    "pyproject.toml",
    "uv.lock",
}
ALLOWED_GITHUB_FILES = {
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
}
FORBIDDEN_PATHS = {"CONTEXT-MAP.md", "CONTEXT.md", "RELEASING.md", "apps/tui/CONTEXT.md"}
ALLOWED_DOCUMENTATION_SECTIONS = {
    "getting-started",
    "guides",
    "reference",
    "architecture",
    "development",
}
FORBIDDEN_ASSET_SUFFIXES = {
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".wasm",
    ".webp",
}
FORBIDDEN_SECRET_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
FORBIDDEN_BENCHMARK_DIRECTORIES = {"evidence", "logs", "output", "outputs", "private", "raw", "results"}
FORBIDDEN_TEST_MARKERS = {
    "live_feishu",
    "openrouter",
    "private_real",
    "real_channel",
    "real_llm",
    "real_vm",
}
FORBIDDEN_TEXT = {
    "github.com/" + "Hackerismydream/" + "myna": "private repository reference",
    "github.com/" + "Hackerismydream/" + "pico": "development repository reference",
    "raw.githubusercontent.com/" + "Hackerismydream": "development installer reference",
    "MYNA_" + "WHEEL_URL": "unpublished Memory wheel reference",
}
TEXT_SUFFIXES = {
    "",
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def _tracked_paths(root: Path) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to inspect the release tree")
    output = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def _documentation_allowed(path: str) -> bool:
    parts = Path(path).parts
    return len(parts) > 2 and parts[1] in ALLOWED_DOCUMENTATION_SECTIONS


def check_public_tree(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    paths = list(tracked_paths) if tracked_paths is not None else _tracked_paths(root)
    paths = [path for path in paths if (root / path).is_file()]
    findings: list[str] = []

    for relative in sorted(paths):
        path = Path(relative)
        if path.parts[0] == ".github":
            if relative not in ALLOWED_GITHUB_FILES:
                findings.append(f"forbidden GitHub metadata path: {relative}")
                continue
        if relative in FORBIDDEN_PATHS or relative.startswith(("feishu/",)):
            findings.append(f"forbidden path: {relative}")
            continue
        if path.parts[0] == "docs" and not _documentation_allowed(relative):
            findings.append(f"forbidden documentation path: {relative}")
            continue
        if path.parts[0] == "benchmarks" and any(
            part.lower() in FORBIDDEN_BENCHMARK_DIRECTORIES for part in path.parts[1:-1]
        ):
            findings.append(f"forbidden benchmark artifact path: {relative}")
            continue
        if path.parts[0] == "tests" and any(marker in relative.lower() for marker in FORBIDDEN_TEST_MARKERS):
            findings.append(f"forbidden real-environment test path: {relative}")
            continue
        if len(path.parts) == 1:
            if relative not in ALLOWED_ROOT_FILES:
                findings.append(f"unexpected root file: {relative}")
                continue
        elif path.parts[0] != ".github" and path.parts[0] not in ALLOWED_ROOT_DIRECTORIES:
            findings.append(f"unexpected root directory: {path.parts[0]}")
            continue
        if path.suffix.lower() in FORBIDDEN_ASSET_SUFFIXES and not relative.startswith(
            ("apps/", "src/pico/resources/")
        ):
            findings.append(f"forbidden binary or web asset: {relative}")
            continue
        if path.name == ".env" or path.suffix.lower() in FORBIDDEN_SECRET_SUFFIXES:
            findings.append(f"forbidden secret-bearing file: {relative}")
            continue

        source = root / path
        if not source.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if source.stat().st_size > 1024 * 1024:
            findings.append(f"text file exceeds scan limit: {relative}")
            continue
        content = source.read_text(encoding="utf-8", errors="replace")
        for marker, label in FORBIDDEN_TEXT.items():
            if marker.lower() in content.lower():
                findings.append(f"{label}: {relative}")

    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    findings = check_public_tree(root)
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print("public release tree: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
