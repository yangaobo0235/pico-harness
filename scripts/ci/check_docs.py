"""Validate local Markdown file links without contacting external services."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def check_docs(root: Path = ROOT) -> list[str]:
    pages = list(root.glob("*.md")) + list((root / "docs").rglob("*.md"))
    pages.append(root / "benchmarks" / "README.md")
    findings: list[str] = []
    for page in pages:
        if not page.is_file():
            continue
        content = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.S)
        for match in LINK.finditer(content):
            target = match[1].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith(("#", "//")):
                continue
            path = unquote(parsed.path)
            if path and not (page.parent / path).exists():
                findings.append(f"{page.relative_to(root).as_posix()}: missing link target {path}")
    return findings


def main() -> int:
    findings = check_docs()
    for finding in findings:
        print(finding)
    if not findings:
        print("documentation links: OK")
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
