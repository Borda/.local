#!/usr/bin/env python3
"""Write canonical Codex result JSON with shared confidence checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_items(raw: str) -> list[str]:
    """Parse a JSON array or delimiter-separated list into strings."""
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        return [item.strip() for item in stripped.split("||") if item.strip()]
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    return [item.strip() for item in stripped.split("||") if item.strip()]


def parse_metadata(raw: str) -> dict[str, Any]:
    """Parse mandatory metadata JSON into an object."""
    stripped = raw.strip()
    if not stripped:
        return {}
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid-metadata-json:{exc}") from exc
    if not isinstance(loaded, dict):
        raise SystemExit("invalid-metadata-json:not-object")
    return loaded


def require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    """Return a required list of strings from a metadata object."""
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"invalid-confidence-metadata:{key}")
    return value


def validate_confidence_gap_closures(metadata: dict[str, Any], confidence_gaps: list[str]) -> None:
    """Validate that each active confidence gap has closure evidence or rationale."""
    active_gaps = [gap.strip() for gap in confidence_gaps if gap.strip()]
    if not active_gaps:
        return

    closures = metadata.get("confidence_gap_closures")
    if not isinstance(closures, list):
        raise SystemExit("missing-confidence-gap-closures")

    closed_gaps: set[str] = set()
    for index, closure in enumerate(closures):
        if not isinstance(closure, dict):
            raise SystemExit(f"confidence-gap-closure-not-object:{index}")
        gap = closure.get("gap")
        if not isinstance(gap, str) or not gap.strip():
            raise SystemExit(f"confidence-gap-closure-missing-gap:{index}")
        closure_status = closure.get("status")
        if closure_status not in {"closed", "unresolved", "deferred"}:
            raise SystemExit(f"confidence-gap-closure-invalid-status:{index}")
        evidence = closure.get("evidence") or closure.get("evidence_path")
        rationale = closure.get("rationale")
        if closure_status == "closed" and not (isinstance(evidence, str) and evidence.strip()):
            raise SystemExit(f"confidence-gap-closure-missing-evidence:{index}")
        if closure_status in {"unresolved", "deferred"} and not (isinstance(rationale, str) and rationale.strip()):
            raise SystemExit(f"confidence-gap-closure-missing-rationale:{index}")
        closed_gaps.add(gap.strip())

    missing = sorted(set(active_gaps) - closed_gaps)
    if missing:
        raise SystemExit("confidence-gap-closure-missing:" + ",".join(missing))


def validate_confidence_recovery(
    metadata: dict[str, Any], confidence: float, status: str, checks_failed: list[str]
) -> None:
    """Validate the shared confidence-band recovery contract."""
    recovery = metadata.get("confidence_recovery")
    if not isinstance(recovery, dict):
        raise SystemExit("missing-confidence-recovery")

    initial = recovery.get("initial_confidence")
    final = recovery.get("final_confidence")
    if not isinstance(initial, int | float) or not 0.0 <= float(initial) <= 1.0:
        raise SystemExit("invalid-initial-confidence")
    if not isinstance(final, int | float) or not 0.0 <= float(final) <= 1.0:
        raise SystemExit("invalid-final-confidence")
    if abs(float(final) - confidence) > 0.001:
        raise SystemExit("confidence-recovery-final-mismatch")

    recovery_status = recovery.get("status")
    if recovery_status not in {"fair", "cautious-low", "very-questionable", "not-acceptable-failed"}:
        raise SystemExit("invalid-confidence-recovery-status")

    evidence = require_string_list(recovery, "evidence")
    recovery_actions = require_string_list(recovery, "recovery_actions")
    remaining_limits = require_string_list(recovery, "remaining_limits")
    if not any(item.strip() for item in evidence):
        raise SystemExit("confidence-recovery-evidence-required")
    if not any(item.strip() for item in recovery_actions):
        raise SystemExit("confidence-recovery-actions-required")

    if confidence <= 0.8:
        if status == "pass":
            raise SystemExit("pass-confidence-not-acceptable")
        if "confidence-not-acceptable" not in checks_failed:
            raise SystemExit("missing-confidence-not-acceptable-check")
        if recovery_status != "not-acceptable-failed":
            raise SystemExit("confidence-status-should-fail")
        if not any(item.strip() for item in remaining_limits):
            raise SystemExit("low-confidence-remaining-limits-required")
        return

    if confidence < 0.85:
        if status == "pass":
            raise SystemExit("pass-confidence-very-questionable")
        if "confidence-very-questionable" not in checks_failed:
            raise SystemExit("missing-confidence-very-questionable-check")
        if recovery_status != "very-questionable":
            raise SystemExit("confidence-status-should-be-very-questionable")
        if not any(item.strip() for item in remaining_limits):
            raise SystemExit("very-questionable-remaining-limits-required")
        return

    if confidence < 0.9:
        if recovery_status != "cautious-low":
            raise SystemExit("confidence-status-should-be-cautious-low")
        if not any(item.strip() for item in remaining_limits):
            raise SystemExit("cautious-low-remaining-limits-required")
        return

    if recovery_status != "fair":
        raise SystemExit("confidence-status-should-be-fair")


def validate_confidence_metadata(
    metadata: dict[str, Any], confidence: float, status: str, checks_failed: list[str]
) -> None:
    """Validate all confidence metadata required by the shared result contract."""
    if not metadata:
        raise SystemExit("missing-confidence-metadata")
    confidence_gaps = require_string_list(metadata, "confidence_gaps")
    if confidence < 1.0 and not any(item.strip() for item in confidence_gaps):
        raise SystemExit("confidence-gaps-required")
    validate_confidence_gap_closures(metadata, confidence_gaps)
    validate_confidence_recovery(metadata, confidence, status, checks_failed)


def split_csv(raw: str) -> list[str]:
    """Split a comma-separated argument into non-empty trimmed values."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Build and validate the canonical result payload from parsed arguments."""
    checks_run = split_csv(args.checks_run)
    checks_failed = split_csv(args.checks_failed)
    metadata = parse_metadata(args.metadata)
    validate_confidence_metadata(metadata, args.confidence, args.status, checks_failed)

    return {
        "status": args.status,
        "checks_run": checks_run,
        "checks_failed": checks_failed,
        "findings": {
            "critical": args.critical,
            "high": args.high,
            "medium": args.medium,
            "low": args.low,
        },
        "confidence": args.confidence,
        "artifact_path": args.artifact_path,
        "recommendations": parse_items(args.recommendations),
        "follow_up": parse_items(args.follow_up),
        "metadata": metadata,
    }


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for result writing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--status", required=True, choices=("pass", "fail", "timeout"))
    parser.add_argument("--checks-run", required=True)
    parser.add_argument("--checks-failed", default="")
    parser.add_argument("--critical", type=int, default=0)
    parser.add_argument("--high", type=int, default=0)
    parser.add_argument("--medium", type=int, default=0)
    parser.add_argument("--low", type=int, default=0)
    parser.add_argument("--confidence", required=True, type=float)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--recommendations", default="")
    parser.add_argument("--follow-up", default="")
    parser.add_argument("--metadata", default="")
    return parser.parse_args()


def main() -> int:
    """Write the result JSON and print the output path."""
    args = parse_args()
    if not 0.0 <= args.confidence <= 1.0:
        raise SystemExit("invalid-confidence")
    for field in ("critical", "high", "medium", "low"):
        if getattr(args, field) < 0:
            raise SystemExit(f"invalid-finding-count:{field}")

    payload = build_payload(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
