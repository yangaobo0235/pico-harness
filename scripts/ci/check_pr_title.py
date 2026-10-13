"""Validate the PR title carried by the PR_TITLE environment variable."""

from __future__ import annotations

import os
import sys

from scripts.ci.commit_lint import check_pr_body, check_pr_title

TITLE_ENV = "PR_TITLE"
BODY_ENV = "PR_BODY"


def main(argv: list[str] | None = None) -> int:
    title = os.environ.get(TITLE_ENV, "").strip()
    if not title:
        print(f"{TITLE_ENV} is not set; skipping PR title check")
        return 0

    failed = False
    result = check_pr_title(title)
    if not result.ok:
        failed = True
        print(f"Invalid PR title: {title}", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)

    body = os.environ.get(BODY_ENV)
    if body is not None:
        body_result = check_pr_body(body)
        if not body_result.ok:
            failed = True
            print("Invalid PR body:", file=sys.stderr)
            for error in body_result.errors:
                print(f"- {error}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
