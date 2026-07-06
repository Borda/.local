#!/usr/bin/env python3
"""Validate review-skill artifacts for multi-axis specialist evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SECTIONS = (
    "Decision Summary",
    "Scope",
    "Risk Tier",
    "Files Inspected",
    "Specialist Passes",
    "Specialist Manifest",
    "Findings",
    "No-Finding Residual Risks",
    "Confidence Gaps",
)
REQUIRED_ROLES = {"qa-specialist", "challenger"}
VALID_RECOMMENDATIONS = {"accept-as-is", "minor-changes", "needs-more-work", "reject", "not-aligned"}
ALL_MANIFEST_ROLES = {
    "qa-specialist",
    "challenger",
    "solution-architect",
    "security-auditor",
    "data-steward",
    "cicd-steward",
    "linting-expert",
    "doc-scribe",
    "oss-shepherd",
    "squeezer",
    "scientist",
    "web-explorer",
}
INDEPENDENT_PASS_TIERS = {"BROAD", "HIGH_RISK"}
VALID_MODES = {"spawned", "substituted", "not_triggered"}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return payload


def _resolve_path(out_dir: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise SystemExit("missing output path")
    path = Path(raw_path)
    if path.is_absolute() or path.exists():
        return path
    return out_dir / path


def _require_notes_sections(notes_path: Path) -> None:
    text = notes_path.read_text(encoding="utf-8")
    missing = []
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text and f"# {section}" not in text:
            missing.append(section)
    if missing:
        raise SystemExit("missing-review-note-sections:" + ",".join(missing))


def _validate_review_decision(metadata: dict[str, Any]) -> None:
    decision = metadata.get("review_decision")
    if not isinstance(decision, dict):
        raise SystemExit("result-missing-review-decision")
    recommendation = decision.get("recommendation")
    if recommendation not in VALID_RECOMMENDATIONS:
        raise SystemExit(f"invalid-review-recommendation:{recommendation!r}")
    for key in ("summary", "rationale"):
        value = decision.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"review-decision-missing-{key}")


def _manifest_passes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    passes = manifest.get("passes", manifest.get("specialist_passes"))
    if not isinstance(passes, list):
        raise SystemExit("manifest-missing-passes")
    normalized = []
    for index, item in enumerate(passes):
        if not isinstance(item, dict):
            raise SystemExit(f"manifest-pass-not-object:{index}")
        normalized.append(item)
    return normalized


def _validate_manifest_entries(out_dir: Path, passes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_role: dict[str, dict[str, Any]] = {}
    for item in passes:
        role = item.get("role")
        axis = item.get("axis")
        mode = item.get("mode")
        trigger = item.get("trigger")
        confidence = item.get("confidence")
        blocking_findings = item.get("blocking_findings")
        if not isinstance(role, str) or role not in ALL_MANIFEST_ROLES:
            raise SystemExit(f"manifest-invalid-role:{role!r}")
        if role in by_role:
            raise SystemExit(f"manifest-duplicate-role:{role}")
        if not isinstance(axis, str) or not axis.strip():
            raise SystemExit(f"manifest-missing-axis:{role}")
        if mode not in VALID_MODES:
            raise SystemExit(f"manifest-invalid-mode:{role}:{mode!r}")
        if not isinstance(trigger, str) or not trigger.strip():
            raise SystemExit(f"manifest-missing-trigger:{role}")
        if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
            raise SystemExit(f"manifest-invalid-confidence:{role}")
        if not isinstance(blocking_findings, int) or blocking_findings < 0:
            raise SystemExit(f"manifest-invalid-blocking-findings:{role}")
        if mode in {"spawned", "substituted"}:
            output_path = _resolve_path(out_dir, item.get("output_path"))
            if not output_path.exists():
                raise SystemExit(f"manifest-missing-output:{role}:{output_path}")
        by_role[role] = item

    missing_roles = sorted(ALL_MANIFEST_ROLES - set(by_role))
    if missing_roles:
        raise SystemExit("manifest-missing-roles:" + ",".join(missing_roles))
    return by_role


def _validate_result(out_dir: Path, result_path: Path) -> None:
    result = _load_json(result_path)
    status = result.get("status")
    if status not in {"pass", "fail", "timeout"}:
        raise SystemExit(f"invalid-status:{status!r}")

    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit("result-missing-metadata")

    scope = metadata.get("scope", metadata.get("review_scope"))
    if scope not in {"working-tree", "path", "commit", "pr"}:
        raise SystemExit(f"invalid-review-scope:{scope!r}")

    risk_tier = metadata.get("risk_tier")
    if risk_tier not in {"TRIVIAL", "LOCAL", "BROAD", "HIGH_RISK"}:
        raise SystemExit(f"invalid-risk-tier:{risk_tier!r}")

    notes_path = out_dir / "review-notes.md"
    _require_notes_sections(notes_path)
    _validate_review_decision(metadata)
    if scope == "pr":
        notes_text = notes_path.read_text(encoding="utf-8")
        if "Online Review Triage" not in notes_text:
            raise SystemExit("missing-pr-online-review-triage")
        for filename in (
            "pr.json",
            "pr-routing.json",
            "target-branch.json",
            "local-checkout.json",
            "comments.json",
            "reviews.json",
            "review-threads.json",
            "unresolved-review-threads.json",
            "online-review-summary.json",
            "diff.patch",
        ):
            if not (out_dir / filename).exists():
                raise SystemExit(f"missing-pr-artifact:{filename}")
        routing = _load_json(out_dir / "pr-routing.json")
        target_branch = _load_json(out_dir / "target-branch.json")
        checkout = _load_json(out_dir / "local-checkout.json")
        if routing.get("local_checkout_required") is not True:
            raise SystemExit("pr-routing-local-checkout-not-required")
        if "--force" in str(routing.get("local_checkout_command", "")):
            raise SystemExit("pr-routing-force-checkout-forbidden")
        if "force_policy" not in routing:
            raise SystemExit("pr-routing-force-policy-missing")
        if target_branch.get("status") != "fetched":
            raise SystemExit("pr-target-branch-not-fetched")
        if not target_branch.get("local_head"):
            raise SystemExit("pr-target-branch-head-missing")
        if checkout.get("status") != "checked-out":
            raise SystemExit("pr-local-checkout-not-checked-out")
        if "--force" in str(checkout.get("command", "")):
            raise SystemExit("pr-local-checkout-force-forbidden")
        if "force_policy" not in checkout:
            raise SystemExit("pr-local-checkout-force-policy-missing")
        if checkout.get("head_matches_pr") is not True:
            raise SystemExit("pr-local-checkout-head-mismatch")
        if (out_dir / "head-files").exists():
            raise SystemExit("pr-raw-head-file-snapshots-forbidden")

    if risk_tier == "TRIVIAL":
        return

    manifest_path = _resolve_path(out_dir, metadata.get("specialist_manifest"))
    manifest = _load_json(manifest_path)
    passes = _manifest_passes(manifest)
    by_role = _validate_manifest_entries(out_dir, passes)

    metadata_passes = metadata.get("specialist_passes")
    if not isinstance(metadata_passes, list):
        raise SystemExit("metadata-missing-specialist-passes")
    metadata_by_role = {}
    for index, item in enumerate(metadata_passes):
        if not isinstance(item, dict):
            raise SystemExit(f"metadata-specialist-pass-not-object:{index}")
        role = item.get("role")
        if not isinstance(role, str):
            raise SystemExit(f"metadata-specialist-pass-missing-role:{index}")
        metadata_by_role[role] = item
    if set(metadata_by_role) != set(by_role):
        raise SystemExit("metadata-specialist-pass-role-mismatch")
    for role, item in by_role.items():
        metadata_item = metadata_by_role[role]
        for key in ("axis", "trigger", "mode", "output_path", "confidence", "blocking_findings"):
            if metadata_item.get(key) != item.get(key):
                raise SystemExit(f"metadata-specialist-pass-mismatch:{role}:{key}")

    missing_required = sorted(role for role in REQUIRED_ROLES if by_role[role]["mode"] == "not_triggered")
    if missing_required:
        raise SystemExit("required-specialist-not-triggered:" + ",".join(missing_required))

    substituted_roles = sorted(role for role in REQUIRED_ROLES if by_role[role]["mode"] == "substituted")
    required_independent = not substituted_roles
    if risk_tier in INDEPENDENT_PASS_TIERS and status == "pass" and not required_independent:
        raise SystemExit("independent-review-required-for-pass:" + ",".join(substituted_roles))

    fanout_substituted = any(item["mode"] == "substituted" for item in passes)
    if metadata.get("fanout_substituted") is not fanout_substituted:
        raise SystemExit("metadata-fanout-substituted-mismatch")

    independence_satisfied = bool(required_independent)
    if metadata.get("independence_satisfied") is not independence_satisfied:
        raise SystemExit("metadata-independence-satisfied-mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Review output directory.")
    parser.add_argument("--result", required=True, type=Path, help="Candidate result.json path.")
    args = parser.parse_args()

    _validate_result(args.out, args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
