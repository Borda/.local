#!/usr/bin/env python3
"""Find the newest compatible local code-review artifact for a pull-request target.

## Purpose

Let remediation locate an assessed prior review report that matches the canonical PR URL rather than guessing from
timestamps alone. This prevents code-remediate from applying findings from a different pull request, a review that never
reached an assessed verdict, or a terminal close disposition.

## Scope

It scans local report directories and JSON identity files; it does not query GitHub, validate findings beyond
classifying terminal results, or change report content. Matching accepts a PR number, ``#number``, or exact normalized
URL and checks both ``pr.json`` identity and result metadata.

## Usage

Run ``python find-review-report.py --target <pr-url-or-number>`` to select an assessed report. Alternatively, run the
same script with ``--result <path>`` to reject a supplied unavailable, closed, or unpromoted candidate result. The
target search covers canonical ``pr-<number>/run-<NNN>`` directories, timestamped flat reports, and, for the default
current root, the legacy ``.reports/codex/review`` root.

## Used by

The ``code-remediate #<PR> +review`` workflow and review-report lookup tests use this selector. Remediation is the
consumer of the assessed/unavailable distinction because it must rerun code-review when no trustworthy prior assessment
exists.

## Outputs

It prints one matching assessed local review-artifact path, choosing the numerically highest PR-scoped run before any
compatible timestamped artifact across canonical and legacy report roots. Compatibility requires PR scope and a
recognized ``metadata.review_decision.recommendation`` in addition to PR identity.

## Failure

Absent PR identity, malformed report JSON, a current terminal close, a newer unpromoted candidate, only unavailable
diagnostics, or no matching artifact returns a non-zero status so remediation cannot consume unassessed findings.
Terminal messages distinguish unavailable, closed, unpromoted, missing, and invalid candidates.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple


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
    """Classify a result as assessed, unavailable, closed, or invalid for remediation intake."""
    try:
        payload: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("scope") != "pr":
        return "invalid"
    if metadata.get("review_status") == "unavailable":
        return "unavailable"
    if metadata.get("review_status") == "closed":
        return "closed"
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
    if result_path.name == CANDIDATE_RESULT_NAME:
        raise LookupError(f"matching-review-candidate-unpromoted:{result_path}")
    kind = review_result_kind(result_path)
    if kind == "unavailable":
        raise LookupError("matching-review-unavailable-rerun-code-review")
    if kind == "closed":
        raise LookupError("matching-review-closed-not-remediable")
    if kind != "assessed":
        raise LookupError("invalid-review-report-rerun-code-review")
    return result_path


CURRENT_REPORTS_DIR = Path(".reports/codex/code-review")
LEGACY_REPORTS_DIR = Path(".reports/codex/review")
CANDIDATE_RESULT_NAME = "result.candidate.json"
PR_DIRECTORY_PATTERN = re.compile(r"pr-([1-9][0-9]*)")
RUN_DIRECTORY_PATTERN = re.compile(r"run-([0-9]{3,})")


class ReviewArtifact(NamedTuple):
    """Bind a review result path to its topology-aware ordering identity."""

    path: Path
    order: tuple[int, str | int]
    pull_number: str | None


def _review_artifacts(reports_dir: Path) -> list[ReviewArtifact]:
    """Enumerate canonical nested and legacy flat artifacts without recursive discovery."""
    artifacts: list[ReviewArtifact] = []
    for report_dir in reports_dir.glob("*"):
        if not report_dir.is_dir():
            continue
        pr_match = PR_DIRECTORY_PATTERN.fullmatch(report_dir.name)
        if pr_match is not None:
            pull_number = pr_match.group(1)
            for run_dir in report_dir.glob("run-*"):
                run_match = RUN_DIRECTORY_PATTERN.fullmatch(run_dir.name)
                if run_match is None or int(run_match.group(1)) < 1 or not run_dir.is_dir():
                    continue
                order = (1, int(run_match.group(1)))
                for result_name in ("result.json", CANDIDATE_RESULT_NAME):
                    result_path = run_dir / result_name
                    if result_path.is_file():
                        artifacts.append(ReviewArtifact(result_path, order, pull_number))
            continue
        if report_dir.name.startswith("pr-"):
            continue
        order = (0, report_dir.name)
        for result_name in ("result.json", CANDIDATE_RESULT_NAME):
            result_path = report_dir / result_name
            if result_path.is_file():
                artifacts.append(ReviewArtifact(result_path, order, None))
    return artifacts


def _artifact_matches_target(artifact: ReviewArtifact, target: str, *, allow_target_file: bool = False) -> bool:
    """Match stored PR identity, optionally accepting terminal target-only diagnostics."""
    identity = _read_pr_identity(artifact.path.parent / "pr.json")
    if identity is not None:
        number, url = identity
        if artifact.pull_number is not None and artifact.pull_number != number:
            return False
        return _matches_target(target, number, url)
    if not allow_target_file:
        return False
    target_path = artifact.path.parent / "pr-target.txt"
    stored_target = target_path.read_text(encoding="utf-8").strip() if target_path.is_file() else ""
    return _matches_target(target, stored_target, stored_target)


def find_latest_review_report(target: str, reports_dirs: list[Path]) -> Path:
    """Return the newest code-review result across current and legacy roots."""
    normalized_target = target.strip().rstrip("/")
    matches: list[ReviewArtifact] = []
    candidate_matches: list[ReviewArtifact] = []
    promoted_matches: list[ReviewArtifact] = []
    unavailable_matches = False
    invalid_matches = False
    closed_matches: list[ReviewArtifact] = []

    for reports_dir in reports_dirs:
        artifacts = _review_artifacts(reports_dir)
        for artifact in artifacts:
            result_path = artifact.path
            if result_path.name == CANDIDATE_RESULT_NAME:
                if _artifact_matches_target(artifact, normalized_target, allow_target_file=True):
                    candidate_matches.append(artifact)
                continue
            kind = review_result_kind(result_path)
            if kind == "unavailable":
                if _artifact_matches_target(artifact, normalized_target, allow_target_file=True):
                    unavailable_matches = True
                    promoted_matches.append(artifact)
                continue
            if not _artifact_matches_target(artifact, normalized_target):
                continue
            promoted_matches.append(artifact)
            if kind == "closed":
                closed_matches.append(artifact)
                continue
            if kind != "assessed":
                invalid_matches = True
                continue
            matches.append(artifact)

    matches.sort(key=lambda artifact: artifact.order, reverse=True)
    closed_matches.sort(key=lambda artifact: artifact.order, reverse=True)
    candidate_matches.sort(key=lambda artifact: artifact.order, reverse=True)
    promoted_matches.sort(key=lambda artifact: artifact.order, reverse=True)
    if candidate_matches and (not promoted_matches or candidate_matches[0].order > promoted_matches[0].order):
        raise LookupError(f"matching-review-candidate-unpromoted:{candidate_matches[0].path}")
    if closed_matches and (not matches or closed_matches[0].order > matches[0].order):
        raise LookupError("matching-review-closed-not-remediable")
    if not matches:
        if unavailable_matches:
            raise LookupError("matching-review-unavailable-rerun-code-review")
        if invalid_matches:
            raise LookupError("invalid-review-report-rerun-code-review")
        raise LookupError("missing-matching-review-report")
    return matches[0].path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the newest Codex code-review result matching a PR target.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--target", help="PR number, #number, or PR URL.")
    source.add_argument("--result", type=Path, help="Explicit result path that must be an assessed review.")
    parser.add_argument(
        "--reports-dir",
        default=CURRENT_REPORTS_DIR,
        type=Path,
        help="Directory containing PR-scoped runs or legacy timestamped code-review reports.",
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
