#!/usr/bin/env python3
"""Find the newest compatible local code-review artifact for a pull-request target.

## Purpose

Let remediation locate an assessed prior review report that matches the canonical PR URL rather than guessing from timestamps alone. This prevents code-remediate from applying findings from a different pull request or from a review that never reached an assessed verdict.

## Scope

It scans local report directories and JSON identity files; it does not query GitHub, validate findings beyond excluding terminal-unavailable diagnostics, or change report content. Matching accepts a PR number, ``#number``, or exact normalized URL and checks both ``pr.json`` identity and result metadata.

## Usage

Run ``python find-review-report.py --target <pr-url-or-number>`` to select an assessed report, or ``python find-review-report.py --result <path>`` to reject a supplied unavailable diagnostic. The target search covers the requested reports root and, for the default current root, the legacy ``.reports/codex/review`` root as well.

## Used by

The ``code-remediate #<PR> +review`` workflow and review-report lookup tests use this selector. Remediation is the consumer of the assessed/unavailable distinction because it must rerun code-review when no trustworthy prior assessment exists.

## Outputs

It prints one matching assessed local review-artifact path, choosing the newest compatible result across canonical and legacy report roots. Compatibility requires ``metadata.scope == "pr"`` and a recognized ``metadata.review_decision.recommendation`` in addition to PR identity.

## Failure

Absent PR identity, malformed report JSON, only unavailable diagnostics, or no matching artifact returns a non-zero status so remediation cannot consume unassessed findings. Terminal messages distinguish ``matching-review-unavailable-rerun-code-review`` from ``missing-matching-review-report`` and invalid assessed candidates.
"""

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


def _matches_target(target: str, number: str, url: str) -> bool:
    """Return whether a canonical PR identity matches a user target string."""
    return bool(target and (number == target.lstrip("#") or url == target))


def review_result_kind(result_path: Path) -> str:
    """Classify a result as assessed, unavailable, or invalid for remediation intake."""
    try:
        payload: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("scope") != "pr":
        return "invalid"
    if metadata.get("review_status") == "unavailable":
        return "unavailable"
    decision = metadata.get("review_decision")
    if not isinstance(decision, dict) or decision.get("recommendation") not in {
        "accept-as-is",
        "minor-changes",
        "needs-more-work",
        "reject",
        "not-aligned",
    }:
        return "invalid"
    return "assessed"


def require_assessed_review_result(result_path: Path) -> Path:
    """Return a supplied result path unless it is a terminal unavailable-review diagnostic."""
    kind = review_result_kind(result_path)
    if kind == "unavailable":
        raise LookupError("matching-review-unavailable-rerun-code-review")
    if kind != "assessed":
        raise LookupError("invalid-review-report-rerun-code-review")
    return result_path


CURRENT_REPORTS_DIR = Path(".reports/codex/code-review")
LEGACY_REPORTS_DIR = Path(".reports/codex/review")


def find_latest_review_report(target: str, reports_dirs: list[Path]) -> Path:
    """Return the newest code-review result across current and legacy roots."""
    normalized_target = target.strip().rstrip("/")
    matches: list[Path] = []
    unavailable_matches = False
    invalid_matches = False

    for reports_dir in reports_dirs:
        for result_path in reports_dir.glob("*/result.json"):
            kind = review_result_kind(result_path)
            if kind == "unavailable":
                target_path = result_path.parent / "pr-target.txt"
                unavailable_target = target_path.read_text(encoding="utf-8").strip() if target_path.is_file() else ""
                if _matches_target(normalized_target, unavailable_target, unavailable_target):
                    unavailable_matches = True
                continue
            identity = _read_pr_identity(result_path.parent / "pr.json")
            if identity is None:
                continue
            number, url = identity
            if _matches_target(normalized_target, number, url):
                if kind != "assessed":
                    invalid_matches = True
                    continue
                matches.append(result_path)

    matches.sort(key=lambda path: path.parent.name, reverse=True)
    if not matches:
        if unavailable_matches:
            raise LookupError("matching-review-unavailable-rerun-code-review")
        if invalid_matches:
            raise LookupError("invalid-review-report-rerun-code-review")
        raise LookupError("missing-matching-review-report")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the newest Codex code-review result matching a PR target.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--target", help="PR number, #number, or PR URL.")
    source.add_argument("--result", type=Path, help="Explicit result path that must be an assessed review.")
    parser.add_argument(
        "--reports-dir",
        default=CURRENT_REPORTS_DIR,
        type=Path,
        help="Directory containing timestamped Codex code-review reports.",
    )
    args = parser.parse_args(argv)

    try:
        if args.result is not None:
            print(require_assessed_review_result(args.result))
            return 0
        reports_dirs = [args.reports_dir]
        if args.reports_dir == CURRENT_REPORTS_DIR:
            reports_dirs.append(LEGACY_REPORTS_DIR)
        print(find_latest_review_report(args.target, reports_dirs))
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
