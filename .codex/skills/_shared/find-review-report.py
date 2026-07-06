#!/usr/bin/env python3
"""Find the newest Codex review report for a GitHub PR target."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read_pr_identity(pr_path: Path) -> tuple[str, str] | None:
    try:
        payload: dict[str, Any] = json.loads(pr_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    number = str(payload.get("number", ""))
    url = str(payload.get("url", "")).rstrip("/")
    return number, url


def find_latest_review_report(target: str, reports_dir: Path) -> Path:
    """Return the newest review `result.json` matching a PR number or URL."""
    normalized_target = target.strip().rstrip("/")
    target_number = normalized_target.lstrip("#")
    matches: list[Path] = []

    for result_path in reports_dir.glob("*/result.json"):
        identity = _read_pr_identity(result_path.parent / "pr.json")
        if identity is None:
            continue
        number, url = identity
        if normalized_target and (number == target_number or url == normalized_target):
            matches.append(result_path)

    matches.sort(key=lambda path: path.parent.name, reverse=True)
    if not matches:
        raise LookupError("missing-matching-review-report")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the newest Codex review result path matching a PR target.")
    parser.add_argument("--target", required=True, help="PR number, #number, or PR URL.")
    parser.add_argument(
        "--reports-dir",
        default=".reports/codex/review",
        type=Path,
        help="Directory containing timestamped Codex review reports.",
    )
    args = parser.parse_args(argv)

    try:
        print(find_latest_review_report(args.target, args.reports_dir))
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
