#!/usr/bin/env python3
"""Validate common Codex skill artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

COMMON_RESULT_FIELDS = {
    "status",
    "checks_run",
    "checks_failed",
    "findings",
    "confidence",
    "artifact_path",
}
EXPECTED_GATE_IDS = {"lint", "format", "types", "tests", "review"}
FAILING_GATE_STATUSES = {"fail", "missing-command", "timeout"}
VALID_GATE_STATUSES = {"pass", "fail", "missing-command", "not-applicable", "timeout"}

UNRESOLVED_REASON_GROUPS = {
    "local-code-or-doc",
    "process-gate",
    "independent-review",
    "environment-blocked",
    "external-ci",
    "user-deferred",
    "already-closed",
    "other",
}

UNRESOLVED_NEXT_OWNERS = {
    "codex",
    "user",
    "maintainer",
    "ci",
    "environment",
    "external-reviewer",
}

CODE_REMEDIATE_TRIAGE_STATUSES = {
    "valid",
    "resolved",
    "duplicate",
    "stale",
    "out-of-scope",
    "already-fixed",
    "already-applied",
    "needs-clarification",
}

CODE_REMEDIATE_RESOLUTION_STATUSES = {
    "implemented",
    "resolved",
    "rejected",
    "stale",
    "not-applicable",
    "duplicate",
    "already-fixed",
    "already-applied",
    "needs-clarification",
    "unresolved",
}

CODE_REMEDIATE_FINAL_TABLE_REQUIRED_COLUMNS = {
    "input item",
    "item name",
    "item type",
    "triage status",
    "resolution",
    "owner/status",
    "resolved how",
    "evidence",
}

SKILL_REQUIREMENTS: dict[str, dict[str, object]] = {
    "analyse": {"files": {}},
    "audit": {"files": {}},
    "calibrate": {"files": {}},
    "research": {"files": {}},
    "code-review": {"files": {}},
    "sync": {"files": {}},
    "develop": {
        "files": {
            "development-notes.md": ["Scope", "Acceptance Criteria", "Evidence", "Specialist Policy", "Gates"],
            "confidence-calibration.md": [
                "Initial Confidence",
                "Objective Evidence",
                "Confidence Gaps",
                "Recovery Actions",
                "Recomputed Confidence",
                "Remaining Limits",
            ],
        },
    },
    "code-remediate": {
        "files": {
            "action-items.md": ["Review Item Resolution Table"],
            "resolution-scope.md": ["Resolution Scope Selection"],
            "closure-log.md": ["Closure Evidence"],
            "unresolved.txt": [],
        },
    },
    "investigate": {
        "files": {
            "symptom.md": [],
            "hypotheses.md": ["Falsification"],
            "root-cause.md": ["Evidence", "Falsification", "Rejected Alternatives", "Confidence"],
        },
    },
    "kaggle": {
        "files": {
            "profile.md": [
                "Normalized Inputs",
                "Grounded Facts",
                "Model Decision",
                "Verification",
                "Residual Limits",
            ],
        },
    },
    "manage": {
        "files": {
            "ownership.md": ["Intent", "Owned Files", "Verification", "Residual Limits"],
        },
    },
    "optimize": {
        "files": {
            "hypothesis.md": [],
            "comparison.md": ["baseline", "after", "delta", "guard", "confidence"],
            "experiments.jsonl": [],
        },
        "jsonl": ["experiments.jsonl"],
    },
    "release": {
        "files": {
            "change-table.md": [],
            "release-readiness.md": ["SemVer", "Migration", "Checks", "Blockers"],
        },
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"expected-json-object:{path}")
    return payload


def _require_result_shape(result: dict[str, Any]) -> None:
    missing = sorted(COMMON_RESULT_FIELDS - set(result))
    if missing:
        raise SystemExit("result-missing-fields:" + ",".join(missing))
    if result["status"] not in {"pass", "fail", "timeout"}:
        raise SystemExit(f"invalid-status:{result['status']!r}")
    if not isinstance(result["checks_run"], list):
        raise SystemExit("invalid-checks-run")
    if not isinstance(result["checks_failed"], list):
        raise SystemExit("invalid-checks-failed")
    findings = result["findings"]
    if not isinstance(findings, dict):
        raise SystemExit("invalid-findings")
    for key in ("critical", "high", "medium", "low"):
        if not isinstance(findings.get(key), int) or findings[key] < 0:
            raise SystemExit(f"invalid-finding-count:{key}")
    confidence = result["confidence"]
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise SystemExit("invalid-confidence")
    if result["status"] == "pass" and result["checks_failed"]:
        raise SystemExit("pass-with-failed-checks")
    if result["status"] == "pass" and findings["critical"] > 0:
        raise SystemExit("pass-with-critical-findings")


def _require_file_sections(path: Path, sections: list[str]) -> None:
    if not path.exists():
        raise SystemExit(f"missing-artifact:{path}")
    text = path.read_text(encoding="utf-8")
    for section in sections:
        if section.lower() not in text.lower():
            raise SystemExit(f"missing-artifact-section:{path.name}:{section}")


def _validate_jsonl(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"missing-jsonl:{path}")
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SystemExit(f"jsonl-row-not-object:{path}:{index}")


def _validate_gates(out_dir: Path) -> dict[str, Any]:
    gates_path = out_dir / "gates.json"
    if not gates_path.exists():
        raise SystemExit("missing-gates-json")
    gates = _load_json(gates_path)
    checks = gates.get("checks")
    if not isinstance(checks, list):
        raise SystemExit("gates-missing-check-details")
    seen_ids: set[str] = set()
    failing_ids: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise SystemExit(f"gate-check-not-object:{index}")
        for key in ("id", "status", "command_path", "stdout", "stderr", "duration_seconds"):
            if key not in check:
                raise SystemExit(f"gate-check-missing-field:{index}:{key}")
        check_id = check["id"]
        if not isinstance(check_id, str) or check_id not in EXPECTED_GATE_IDS:
            raise SystemExit(f"gate-check-invalid-id:{index}:{check_id!r}")
        if check_id in seen_ids:
            raise SystemExit(f"gate-check-duplicate-id:{check_id}")
        seen_ids.add(check_id)
        if check["status"] not in VALID_GATE_STATUSES:
            raise SystemExit(f"gate-check-invalid-status:{index}:{check['status']!r}")
        if not isinstance(check.get("exit_code"), int):
            raise SystemExit(f"gate-check-invalid-exit-code:{index}")
        if check["status"] in {"missing-command", "not-applicable", "timeout"}:
            reason = check.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise SystemExit(f"gate-check-missing-reason:{index}")
        if check["status"] in FAILING_GATE_STATUSES:
            failing_ids.append(check_id)
        expected_exit_codes = {"pass": 0, "missing-command": 127, "not-applicable": 0, "timeout": 124}
        expected_exit = expected_exit_codes.get(check["status"])
        if expected_exit is not None and check["exit_code"] != expected_exit:
            raise SystemExit(f"gate-check-exit-status-mismatch:{index}")
        if check["status"] == "fail" and check["exit_code"] in {0, 124, 127}:
            raise SystemExit(f"gate-check-invalid-fail-exit-code:{index}")
        for key in ("command_path", "stdout", "stderr"):
            path = Path(str(check[key]))
            if not path.is_absolute() and not path.exists():
                path = out_dir / path
            resolved = path.resolve()
            if not resolved.is_relative_to(out_dir.resolve()):
                raise SystemExit(f"gate-check-log-outside-output:{index}:{key}")
            if path.is_symlink() or not resolved.is_file():
                raise SystemExit(f"gate-check-missing-log:{index}:{key}")
    if seen_ids != EXPECTED_GATE_IDS:
        raise SystemExit("gate-check-id-set-mismatch")
    expected_status = (
        "timeout" if any(check["status"] == "timeout" for check in checks) else "fail" if failing_ids else "pass"
    )
    if gates.get("status") != expected_status:
        raise SystemExit("gates-status-mismatch")
    if gates.get("checks_failed") != failing_ids:
        raise SystemExit("gates-failed-list-mismatch")
    return gates


def _reconcile_result_with_gates(result: dict[str, Any], gates: dict[str, Any]) -> None:
    """Require result status and check fields to include gate outcomes."""
    if set(result["checks_run"]) != EXPECTED_GATE_IDS:
        raise SystemExit("result-checks-run-gate-mismatch")
    gate_failures = set(gates["checks_failed"])
    if not gate_failures.issubset(set(result["checks_failed"])):
        raise SystemExit("result-checks-failed-gate-mismatch")
    if gates["status"] == "fail" and result["status"] == "pass":
        raise SystemExit("result-pass-with-failed-gates")
    if gates["status"] == "timeout" and result["status"] != "timeout":
        raise SystemExit("result-status-timeout-mismatch")


def _validate_confidence_gaps(result: dict[str, Any], skill: str) -> None:
    """Validate confidence gap metadata whenever a confidence score is reported."""
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit(f"{skill}-missing-metadata")
    confidence_gaps = metadata.get("confidence_gaps")
    if not isinstance(confidence_gaps, list) or not all(isinstance(item, str) for item in confidence_gaps):
        raise SystemExit(f"{skill}-invalid-confidence-gaps")
    if float(result["confidence"]) < 1.0 and not any(item.strip() for item in confidence_gaps):
        raise SystemExit(f"{skill}-confidence-gaps-required")
    _validate_confidence_gap_closures(metadata, confidence_gaps, skill)


def _validate_confidence_gap_closures(metadata: dict[str, Any], confidence_gaps: list[str], skill: str) -> None:
    """Validate that every confidence gap is closed or explicitly carried forward."""
    active_gaps = [gap.strip() for gap in confidence_gaps if gap.strip()]
    if not active_gaps:
        return

    closures = metadata.get("confidence_gap_closures")
    if not isinstance(closures, list):
        raise SystemExit(f"{skill}-missing-confidence-gap-closures")

    closed_gaps: set[str] = set()
    for index, closure in enumerate(closures):
        if not isinstance(closure, dict):
            raise SystemExit(f"{skill}-confidence-gap-closure-not-object:{index}")
        gap = closure.get("gap")
        if not isinstance(gap, str) or not gap.strip():
            raise SystemExit(f"{skill}-confidence-gap-closure-missing-gap:{index}")
        status = closure.get("status")
        if status not in {"closed", "unresolved", "deferred"}:
            raise SystemExit(f"{skill}-confidence-gap-closure-invalid-status:{index}")
        evidence = closure.get("evidence") or closure.get("evidence_path")
        rationale = closure.get("rationale")
        if status == "closed" and not (isinstance(evidence, str) and evidence.strip()):
            raise SystemExit(f"{skill}-confidence-gap-closure-missing-evidence:{index}")
        if status in {"unresolved", "deferred"} and not (isinstance(rationale, str) and rationale.strip()):
            raise SystemExit(f"{skill}-confidence-gap-closure-missing-rationale:{index}")
        closed_gaps.add(gap.strip())

    missing = sorted(set(active_gaps) - closed_gaps)
    if missing:
        raise SystemExit(f"{skill}-confidence-gap-closure-missing:{','.join(missing)}")


def _require_non_empty_string_list(payload: dict[str, Any], key: str, context: str) -> list[str]:
    """Return a required non-empty list of non-blank strings from a metadata object."""
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise SystemExit(f"{context}-invalid-{key}")
    return value


def _validate_confidence_recovery(result: dict[str, Any], skill: str) -> None:
    """Validate evidence-backed confidence recovery metadata for a skill result."""
    confidence = float(result["confidence"])
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit(f"{skill}-missing-confidence-recovery-metadata")
    recovery = metadata.get("confidence_recovery")
    if not isinstance(recovery, dict):
        raise SystemExit(f"{skill}-missing-confidence-recovery-metadata")

    initial = recovery.get("initial_confidence")
    final = recovery.get("final_confidence")
    if not isinstance(initial, int | float) or not 0.0 <= float(initial) <= 1.0:
        raise SystemExit(f"{skill}-invalid-initial-confidence")
    if not isinstance(final, int | float) or not 0.0 <= float(final) <= 1.0:
        raise SystemExit(f"{skill}-invalid-final-confidence")
    if abs(float(final) - confidence) > 0.001:
        raise SystemExit(f"{skill}-confidence-recovery-final-mismatch")

    status = recovery.get("status")
    if status not in {"fair", "cautious-low", "very-questionable", "not-acceptable-failed"}:
        raise SystemExit(f"{skill}-invalid-confidence-recovery-status")

    _require_non_empty_string_list(recovery, "evidence", skill)
    recovery_actions = _require_non_empty_string_list(recovery, "recovery_actions", skill)
    remaining_limits = recovery.get("remaining_limits")
    if not isinstance(remaining_limits, list) or not all(isinstance(item, str) for item in remaining_limits):
        raise SystemExit(f"{skill}-invalid-remaining-limits")

    if confidence <= 0.8:
        if result["status"] == "pass":
            raise SystemExit(f"{skill}-pass-confidence-not-acceptable")
        if "confidence-not-acceptable" not in result["checks_failed"]:
            raise SystemExit(f"{skill}-missing-confidence-not-acceptable-check")
        if status != "not-acceptable-failed":
            raise SystemExit(f"{skill}-confidence-status-should-fail")
        if not recovery_actions or not remaining_limits:
            raise SystemExit(f"{skill}-low-confidence-recovery-missing")
    elif confidence < 0.85:
        if result["status"] == "pass":
            raise SystemExit(f"{skill}-pass-confidence-very-questionable")
        if "confidence-very-questionable" not in result["checks_failed"]:
            raise SystemExit(f"{skill}-missing-confidence-very-questionable-check")
        if status != "very-questionable":
            raise SystemExit(f"{skill}-confidence-status-should-be-very-questionable")
        if not recovery_actions or not remaining_limits:
            raise SystemExit(f"{skill}-very-questionable-confidence-evidence-missing")
    elif confidence < 0.9:
        if status != "cautious-low":
            raise SystemExit(f"{skill}-confidence-status-should-be-cautious-low")
        if not recovery_actions or not remaining_limits:
            raise SystemExit(f"{skill}-cautious-low-confidence-evidence-missing")
    elif status != "fair":
        raise SystemExit(f"{skill}-confidence-status-should-be-fair")


def _validate_code_remediate_report_intake(result: dict[str, Any], out_dir: Path) -> None:
    """Validate source-aware review report intake metadata for code-remediation artifacts."""
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SystemExit("code-remediate-missing-metadata")
    intake = metadata.get("review_report_intake")
    if not isinstance(intake, dict):
        raise SystemExit("code-remediate-missing-review-report-intake")

    requested_report = intake.get("requested_report")
    if not isinstance(requested_report, bool):
        raise SystemExit("code-remediate-invalid-review-report-requested")
    for key in (
        "report_items_total",
        "review_gate_items_total",
        "review_gate_items_selectable",
        "report_items_marked_out_of_scope",
    ):
        value = intake.get(key)
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"code-remediate-invalid-review-report-intake:{key}")

    if not requested_report:
        return

    report_items_total = intake["report_items_total"]
    review_gate_items_total = intake["review_gate_items_total"]
    review_gate_items_selectable = intake["review_gate_items_selectable"]
    if report_items_total < review_gate_items_total:
        raise SystemExit("code-remediate-review-gates-exceed-report-items")
    if review_gate_items_total > 0 and review_gate_items_selectable == 0:
        raise SystemExit("code-remediate-review-gates-not-selectable")

    action_text = (out_dir / "action-items.md").read_text(encoding="utf-8").lower()
    scope_text = (out_dir / "resolution-scope.md").read_text(encoding="utf-8").lower()
    if "review report intake" not in action_text:
        raise SystemExit("code-remediate-review-report-intake-section-missing")
    if review_gate_items_total > 0 and not any(
        token in action_text for token in ("checks_failed", "follow_up", "review-gate", "review gate")
    ):
        raise SystemExit("code-remediate-review-gate-items-missing")
    if review_gate_items_total > 0 and "review-gate" not in scope_text and "review gate" not in scope_text:
        raise SystemExit("code-remediate-review-gate-scope-missing")


def _validate_code_remediate_scope_selection(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate user-confirmed code-remediation scope selection metadata."""
    resolution_scope = metadata.get("resolution_scope")
    if not isinstance(resolution_scope, dict):
        raise SystemExit("code-remediate-missing-resolution-scope-metadata")

    selection_source = resolution_scope.get("selection_source")
    if selection_source not in {"explicit-input", "user-prompt", "none-selectable"}:
        raise SystemExit("code-remediate-invalid-selection-source")
    prompt_presented = resolution_scope.get("prompt_presented")
    if not isinstance(prompt_presented, bool):
        raise SystemExit("code-remediate-invalid-prompt-presented")
    selection_confirmed = resolution_scope.get("selection_confirmed_by_user")
    if not isinstance(selection_confirmed, bool):
        raise SystemExit("code-remediate-invalid-selection-confirmation")

    selected_indexes = resolution_scope.get("selected_indexes")
    deferred_indexes = resolution_scope.get("deferred_indexes")
    selected_groups = resolution_scope.get("selected_severity_groups")
    if not isinstance(selected_indexes, list) or not all(isinstance(item, int) for item in selected_indexes):
        raise SystemExit("code-remediate-invalid-selected-indexes")
    if not isinstance(deferred_indexes, list) or not all(isinstance(item, int) for item in deferred_indexes):
        raise SystemExit("code-remediate-invalid-deferred-indexes")
    if not isinstance(selected_groups, list) or not all(isinstance(item, str) for item in selected_groups):
        raise SystemExit("code-remediate-invalid-selected-severity-groups")

    scope_text = (out_dir / "resolution-scope.md").read_text(encoding="utf-8").lower()
    has_selectable = "none-selectable" not in scope_text and "selectable: 0" not in scope_text
    if has_selectable and selection_source == "none-selectable":
        raise SystemExit("code-remediate-selection-source-incorrectly-none-selectable")
    if has_selectable and selection_source == "user-prompt" and not (prompt_presented and selection_confirmed):
        raise SystemExit("code-remediate-user-prompt-not-confirmed")
    if has_selectable and selection_source == "explicit-input" and not selection_confirmed:
        raise SystemExit("code-remediate-explicit-selection-not-confirmed")
    if has_selectable and selection_source not in {"explicit-input", "user-prompt"}:
        raise SystemExit("code-remediate-selection-required")


def _validate_code_remediate_workplan(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate selected-item grouping and specialist assignment metadata."""
    resolution_scope = metadata.get("resolution_scope")
    if not isinstance(resolution_scope, dict):
        raise SystemExit("code-remediate-missing-resolution-scope-metadata")
    selected_indexes = resolution_scope.get("selected_indexes")
    if not isinstance(selected_indexes, list) or not all(isinstance(item, int) for item in selected_indexes):
        raise SystemExit("code-remediate-invalid-selected-indexes")

    workplan = metadata.get("resolution_workplan")
    if not isinstance(workplan, dict):
        raise SystemExit("code-remediate-missing-resolution-workplan")

    for key in (
        "groups_total",
        "parent_owned_groups",
        "specialist_owned_groups",
        "verifier_groups",
        "unassigned_selected_items",
    ):
        value = workplan.get(key)
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"code-remediate-invalid-resolution-workplan:{key}")

    workplan_path_value = workplan.get("workplan_path")
    if not isinstance(workplan_path_value, str) or not workplan_path_value.strip():
        raise SystemExit("code-remediate-invalid-resolution-workplan:workplan_path")

    if not selected_indexes:
        return

    if workplan["groups_total"] <= 0:
        raise SystemExit("code-remediate-selected-items-without-workplan-groups")
    if workplan["unassigned_selected_items"] != 0:
        raise SystemExit("code-remediate-selected-items-unassigned-in-workplan")
    if workplan["parent_owned_groups"] + workplan["specialist_owned_groups"] != workplan["groups_total"]:
        raise SystemExit("code-remediate-workplan-owner-count-mismatch")
    if workplan["verifier_groups"] > workplan["groups_total"]:
        raise SystemExit("code-remediate-workplan-verifier-count-exceeds-groups")

    workplan_path = out_dir / "resolution-workplan.md"
    declared_path = Path(workplan_path_value)
    if declared_path.name != "resolution-workplan.md":
        raise SystemExit("code-remediate-workplan-path-name-invalid")
    _require_file_sections(
        workplan_path,
        ["Selected Finding Groups", "Specialist Assignments", "Execution Order", "Ungrouped Items"],
    )

    workplan_text = workplan_path.read_text(encoding="utf-8").lower()
    for required_text in ("primary", "verifier", "context", "closure"):
        if required_text not in workplan_text:
            raise SystemExit(f"code-remediate-workplan-missing-{required_text}")


def _count_out_of_scope_items(action_text: str) -> int:
    """Count concrete out-of-scope rows in a code-remediation action ledger."""
    count = 0
    for line in action_text.lower().splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and "out-of-scope" in stripped and "---" not in stripped:
            count += 1
        elif stripped.startswith("- triage status:") and "out-of-scope" in stripped:
            count += 1
    return count


def _validate_code_remediate_out_of_scope_confirmation(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate user confirmation metadata for every out-of-scope code-remediation item."""
    confirmation = metadata.get("out_of_scope_confirmation")
    if not isinstance(confirmation, dict):
        raise SystemExit("code-remediate-missing-out-of-scope-confirmation")
    count = confirmation.get("count")
    all_confirmed = confirmation.get("all_confirmed_by_user")
    items = confirmation.get("items")
    if not isinstance(count, int) or count < 0:
        raise SystemExit("code-remediate-invalid-out-of-scope-count")
    if not isinstance(all_confirmed, bool):
        raise SystemExit("code-remediate-invalid-out-of-scope-confirmed")
    if not isinstance(items, list):
        raise SystemExit("code-remediate-invalid-out-of-scope-items")
    if count != len(items):
        raise SystemExit("code-remediate-out-of-scope-count-mismatch")

    action_text = (out_dir / "action-items.md").read_text(encoding="utf-8")
    observed_count = _count_out_of_scope_items(action_text)
    if observed_count > count:
        raise SystemExit("code-remediate-out-of-scope-items-not-recorded")
    if count == 0:
        if not all_confirmed:
            raise SystemExit("code-remediate-zero-out-of-scope-not-confirmed")
        return
    if not all_confirmed:
        raise SystemExit("code-remediate-out-of-scope-not-confirmed")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SystemExit(f"code-remediate-out-of-scope-item-not-object:{index}")
        for key in ("item_id", "source", "rationale", "evidence_path"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"code-remediate-out-of-scope-item-missing-{key}:{index}")
        if item.get("user_confirmed") is not True:
            raise SystemExit(f"code-remediate-out-of-scope-item-not-confirmed:{index}")


def _validate_code_remediate_pr_relevance(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate PR relevance triage for report and PR-review items."""
    relevance = metadata.get("pr_relevance")
    if not isinstance(relevance, dict):
        raise SystemExit("code-remediate-missing-pr-relevance")
    evaluated = relevance.get("evaluated")
    if not isinstance(evaluated, bool):
        raise SystemExit("code-remediate-invalid-pr-relevance-evaluated")

    for key in (
        "connected_open_items_total",
        "connected_selectable_items_total",
        "connected_required_followup_total",
        "connected_items_marked_out_of_scope",
    ):
        value = relevance.get(key)
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"code-remediate-invalid-pr-relevance:{key}")

    is_pr_mode = metadata.get("mode") == "pr" or (out_dir / "pr").exists()
    if is_pr_mode and not evaluated:
        raise SystemExit("code-remediate-pr-relevance-not-evaluated")
    if not evaluated:
        return

    connected_open = relevance["connected_open_items_total"]
    connected_selectable = relevance["connected_selectable_items_total"]
    connected_followup = relevance["connected_required_followup_total"]
    connected_out_of_scope = relevance["connected_items_marked_out_of_scope"]
    if connected_out_of_scope > 0:
        raise SystemExit("code-remediate-connected-item-marked-out-of-scope")
    if connected_open > 0 and connected_selectable + connected_followup < connected_open:
        raise SystemExit("code-remediate-connected-items-not-selectable-or-followup")

    action_text = (out_dir / "action-items.md").read_text(encoding="utf-8").lower()
    scope_text = (out_dir / "resolution-scope.md").read_text(encoding="utf-8").lower()
    if "pr relevance summary" not in action_text or "pr relevance summary" not in scope_text:
        raise SystemExit("code-remediate-pr-relevance-summary-missing")
    if connected_open > 0 and not any(
        relation in action_text for relation in ("direct-diff", "pr-intent", "adjacent", "unknown")
    ):
        raise SystemExit("code-remediate-connected-relation-missing")


def _validate_status_counts(
    counts: Any,
    allowed_statuses: set[str],
    expected_total: int,
    error_prefix: str,
) -> None:
    """Validate table status-count metadata covers every final table row."""
    if not isinstance(counts, dict):
        raise SystemExit(f"{error_prefix}-not-object")
    missing = sorted(allowed_statuses - set(counts))
    if missing:
        raise SystemExit(f"{error_prefix}-missing:" + ",".join(missing))
    unexpected = sorted(set(counts) - allowed_statuses)
    if unexpected:
        raise SystemExit(f"{error_prefix}-unexpected:" + ",".join(unexpected))

    total = 0
    for status, value in counts.items():
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"{error_prefix}-invalid:{status}")
        total += value
    if total != expected_total:
        raise SystemExit(f"{error_prefix}-total-mismatch")


def _validate_code_remediate_final_resolution_table(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate the final code-remediation table covers every ingested entry."""
    table = metadata.get("final_resolution_table")
    if not isinstance(table, dict):
        raise SystemExit("code-remediate-missing-final-resolution-table")

    count_keys = (
        "ingested_entries_total",
        "table_rows_total",
        "omitted_entries_total",
        "selectable_rows_total",
        "nonselectable_rows_total",
    )
    counts = {}
    for key in count_keys:
        value = table.get(key)
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"code-remediate-invalid-final-resolution-table:{key}")
        counts[key] = value

    if counts["omitted_entries_total"] != 0:
        raise SystemExit("code-remediate-final-table-omitted-entries")
    if counts["ingested_entries_total"] != counts["table_rows_total"]:
        raise SystemExit("code-remediate-final-table-row-count-mismatch")
    if counts["selectable_rows_total"] + counts["nonselectable_rows_total"] != counts["table_rows_total"]:
        raise SystemExit("code-remediate-final-table-selectable-count-mismatch")

    _validate_status_counts(
        table.get("triage_status_counts"),
        CODE_REMEDIATE_TRIAGE_STATUSES,
        counts["table_rows_total"],
        "code-remediate-triage-status-counts",
    )
    _validate_status_counts(
        table.get("resolution_status_counts"),
        CODE_REMEDIATE_RESOLUTION_STATUSES,
        counts["table_rows_total"],
        "code-remediate-resolution-status-counts",
    )

    required_columns = table.get("required_columns")
    if not isinstance(required_columns, list) or not all(isinstance(item, str) for item in required_columns):
        raise SystemExit("code-remediate-final-table-required-columns-invalid")
    normalized_columns = {item.strip().lower() for item in required_columns}
    missing_columns = sorted(CODE_REMEDIATE_FINAL_TABLE_REQUIRED_COLUMNS - normalized_columns)
    if missing_columns:
        raise SystemExit("code-remediate-final-table-required-columns-missing:" + ",".join(missing_columns))

    if counts["table_rows_total"] == 0:
        return

    action_text = (out_dir / "action-items.md").read_text(encoding="utf-8").lower()
    _require_file_sections(
        out_dir / "action-items.md",
        ["Review Item Resolution Table", "Final Resolution Summary", "Final Resolution Table Completeness"],
    )
    for required_column in sorted(CODE_REMEDIATE_FINAL_TABLE_REQUIRED_COLUMNS):
        if required_column not in action_text:
            raise SystemExit(f"code-remediate-final-table-column-missing:{required_column}")
    for required_text in (
        "ingested entries",
        "table rows",
        "omitted entries",
        "triage status counts",
        "resolution status counts",
    ):
        if required_text not in action_text:
            raise SystemExit(f"code-remediate-final-table-missing-{required_text.replace(' ', '-')}")


def _validate_code_remediate_unresolved_summary(metadata: dict[str, Any], out_dir: Path) -> None:
    """Validate selected unresolved work is actionable and not overclaimed."""
    summary = metadata.get("unresolved_summary")
    if not isinstance(summary, dict):
        raise SystemExit("code-remediate-missing-unresolved-summary")

    count_keys = (
        "selected_items_total",
        "selected_items_resolved",
        "selected_items_unresolved",
        "local_actionable_items_unresolved",
        "process_gate_items_unresolved",
        "environment_blocked_items",
        "external_owner_items",
        "user_deferred_items",
    )
    counts = {}
    for key in count_keys:
        value = summary.get(key)
        if not isinstance(value, int) or value < 0:
            raise SystemExit(f"code-remediate-invalid-unresolved-summary:{key}")
        counts[key] = value

    if counts["selected_items_resolved"] + counts["selected_items_unresolved"] != counts["selected_items_total"]:
        raise SystemExit("code-remediate-unresolved-summary-total-mismatch")
    if not isinstance(summary.get("all_local_actionable_items_closed"), bool):
        raise SystemExit("code-remediate-invalid-local-actionable-closed")
    if summary["all_local_actionable_items_closed"] and counts["local_actionable_items_unresolved"] > 0:
        raise SystemExit("code-remediate-local-actionable-contradiction")

    reason_groups = summary.get("unresolved_reason_groups")
    if not isinstance(reason_groups, list):
        raise SystemExit("code-remediate-invalid-unresolved-reason-groups")
    if counts["selected_items_unresolved"] > 0 and not reason_groups:
        raise SystemExit("code-remediate-unresolved-reason-groups-missing")

    grouped_count = 0
    for index, group in enumerate(reason_groups):
        if not isinstance(group, dict):
            raise SystemExit(f"code-remediate-unresolved-reason-group-not-object:{index}")
        reason = group.get("reason")
        if reason not in UNRESOLVED_REASON_GROUPS:
            raise SystemExit(f"code-remediate-invalid-unresolved-reason:{index}")
        count = group.get("count")
        if not isinstance(count, int) or count <= 0:
            raise SystemExit(f"code-remediate-invalid-unresolved-reason-count:{index}")
        grouped_count += count
        owner = group.get("owner")
        if owner not in UNRESOLVED_NEXT_OWNERS:
            raise SystemExit(f"code-remediate-invalid-unresolved-owner:{index}")
        for key in ("next_action", "evidence_path"):
            value = group.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"code-remediate-unresolved-reason-missing-{key}:{index}")

    if grouped_count != counts["selected_items_unresolved"]:
        raise SystemExit("code-remediate-unresolved-reason-count-mismatch")
    if counts["selected_items_unresolved"] == 0:
        return

    _require_file_sections(
        out_dir / "unresolved.txt",
        ["Unresolved Work Summary", "Why Selected Items Remain Unresolved", "Next Action"],
    )
    unresolved_text = (out_dir / "unresolved.txt").read_text(encoding="utf-8").lower()
    for required_text in ("closure class", "next owner", "attempted evidence"):
        if required_text not in unresolved_text:
            raise SystemExit(f"code-remediate-unresolved-summary-missing-{required_text.replace(' ', '-')}")


def _validate_code_remediate_pr_identity(
    routing: dict[str, Any],
    remote_selection: dict[str, Any],
    target_branch: dict[str, Any],
    checkout: dict[str, Any],
) -> None:
    """Reconcile authoritative PR remote, base OID, and checkout head evidence."""
    if routing.get("base_identity_source") != "pr_url":
        raise SystemExit("code-remediate-pr-routing-base-identity-not-authoritative")
    expected_identity = remote_selection.get("expected")
    if not isinstance(expected_identity, dict):
        raise SystemExit("code-remediate-pr-remote-selection-expected-missing")
    if expected_identity.get("host") != routing.get("base_host"):
        raise SystemExit("code-remediate-pr-remote-selection-host-mismatch")
    if expected_identity.get("repository") != routing.get("base_repo"):
        raise SystemExit("code-remediate-pr-remote-selection-repository-mismatch")
    if target_branch.get("remote") != remote_selection.get("remote"):
        raise SystemExit("code-remediate-pr-target-branch-remote-mismatch")
    if target_branch.get("remote_url") != remote_selection.get("remote_url"):
        raise SystemExit("code-remediate-pr-target-branch-remote-url-mismatch")
    expected_base = target_branch.get("expected_base_oid")
    local_base = target_branch.get("local_head")
    if not expected_base or expected_base != routing.get("base_oid"):
        raise SystemExit("code-remediate-pr-target-branch-expected-oid-missing")
    if not local_base or local_base != expected_base or target_branch.get("base_matches_pr_metadata") is not True:
        raise SystemExit("code-remediate-pr-target-branch-oid-mismatch")
    if checkout.get("pr_url") != routing.get("pr_url"):
        raise SystemExit("code-remediate-pr-local-checkout-url-mismatch")
    if not checkout.get("expected_head") or checkout.get("expected_head") != routing.get("head_oid"):
        raise SystemExit("code-remediate-pr-local-checkout-expected-head-missing")
    if checkout.get("local_head") != checkout.get("expected_head"):
        raise SystemExit("code-remediate-pr-local-checkout-oid-mismatch")


def _validate_code_remediate_merge_resolution(
    metadata: dict[str, Any], pr_dir: Path, target_branch: dict[str, Any]
) -> None:
    """Require intent-first target-merge completion before PR finding remediation."""
    path = pr_dir / "merge-resolution.json"
    resolution = _load_json(path)
    required = {
        "schema_version",
        "conflicts_detected",
        "status",
        "authorization",
        "base_remote_ref",
        "target_oid",
        "pre_merge_head",
        "post_merge_head",
        "merge_commit",
        "resolved_paths",
        "unmerged_paths",
        "evidence",
    }
    missing = sorted(required - resolution.keys())
    if missing:
        raise SystemExit("code-remediate-merge-resolution-missing:" + ",".join(missing))
    if resolution.get("schema_version") != 1:
        raise SystemExit("code-remediate-merge-resolution-schema-invalid")
    if resolution.get("target_oid") != target_branch.get("local_head"):
        raise SystemExit("code-remediate-merge-resolution-target-oid-mismatch")
    if resolution.get("unmerged_paths") != []:
        raise SystemExit("code-remediate-merge-conflicts-still-unresolved")
    if not isinstance(resolution.get("evidence"), list) or not resolution["evidence"]:
        raise SystemExit("code-remediate-merge-resolution-evidence-missing")

    conflicts = resolution.get("conflicts_detected")
    status = resolution.get("status")
    authorization = resolution.get("authorization")
    pre_head = resolution.get("pre_merge_head")
    post_head = resolution.get("post_merge_head")
    if conflicts is False:
        if status != "not-needed" or authorization != "not-required":
            raise SystemExit("code-remediate-conflict-free-merge-resolution-invalid")
        if pre_head != post_head or resolution.get("merge_commit") not in (None, ""):
            raise SystemExit("code-remediate-unneeded-target-merge-recorded")
        if resolution.get("resolved_paths") != []:
            raise SystemExit("code-remediate-conflict-free-resolved-paths-invalid")
    elif conflicts is True:
        if status != "completed":
            raise SystemExit("code-remediate-target-merge-not-completed")
        if authorization not in {"explicit-input", "user-confirmed"}:
            raise SystemExit("code-remediate-target-merge-authorization-required")
        if not isinstance(pre_head, str) or not isinstance(post_head, str) or pre_head == post_head:
            raise SystemExit("code-remediate-target-merge-head-evidence-invalid")
        if resolution.get("merge_commit") != post_head:
            raise SystemExit("code-remediate-target-merge-commit-missing")
        if not isinstance(resolution.get("resolved_paths"), list) or not resolution["resolved_paths"]:
            raise SystemExit("code-remediate-target-merge-resolved-paths-missing")
    else:
        raise SystemExit("code-remediate-merge-conflict-decision-invalid")

    summary = metadata.get("merge_resolution")
    if not isinstance(summary, dict):
        raise SystemExit("code-remediate-merge-resolution-metadata-missing")
    summary_path = summary.get("artifact_path")
    if not isinstance(summary_path, str) or Path(summary_path).resolve() != path.resolve():
        raise SystemExit("code-remediate-merge-resolution-path-mismatch")
    expected_summary = {
        "authorization": authorization,
        "conflicts_detected": conflicts,
        "status": status,
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        raise SystemExit("code-remediate-merge-resolution-metadata-mismatch")


def validate(skill: str, out_dir: Path, result_path: Path) -> None:
    result = _load_json(result_path)
    _require_result_shape(result)
    _validate_confidence_gaps(result, skill)
    gates = _validate_gates(out_dir)
    _reconcile_result_with_gates(result, gates)

    requirement = SKILL_REQUIREMENTS.get(skill)
    if requirement is None:
        raise SystemExit(f"unsupported-skill:{skill}")
    files = requirement.get("files", {})
    if not isinstance(files, dict):
        raise SystemExit(f"invalid-requirement:{skill}")
    for filename, sections in files.items():
        if not isinstance(sections, list):
            raise SystemExit(f"invalid-sections:{skill}:{filename}")
        _require_file_sections(out_dir / str(filename), [str(section) for section in sections])
    jsonl_files = requirement.get("jsonl", [])
    if not isinstance(jsonl_files, list):
        raise SystemExit(f"invalid-jsonl-requirement:{skill}")
    for filename in jsonl_files:
        _validate_jsonl(out_dir / str(filename))
    _validate_confidence_recovery(result, skill)
    if skill == "code-remediate":
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            raise SystemExit("code-remediate-missing-metadata")
        resolution_scope = metadata.get("resolution_scope")
        if not isinstance(resolution_scope, dict):
            raise SystemExit("code-remediate-missing-resolution-scope-metadata")
        _validate_code_remediate_scope_selection(metadata, out_dir)
        _validate_code_remediate_workplan(metadata, out_dir)
        _validate_code_remediate_out_of_scope_confirmation(metadata, out_dir)
        _validate_code_remediate_report_intake(result, out_dir)
        _validate_code_remediate_final_resolution_table(metadata, out_dir)
        _validate_code_remediate_pr_relevance(metadata, out_dir)
        _validate_code_remediate_unresolved_summary(metadata, out_dir)
        scope_text = (out_dir / "resolution-scope.md").read_text(encoding="utf-8").lower()
        for required_text in ("selectable", "selected", "deferred"):
            if required_text not in scope_text:
                raise SystemExit(f"code-remediate-scope-missing-{required_text}")
        pr_dir = out_dir / "pr"
        if metadata.get("mode") == "pr" or pr_dir.exists():
            for filename in (
                "pr.json",
                "pr-routing.json",
                "remote-selection.json",
                "target-branch.json",
                "pr-head-fetch.json",
                "local-checkout.json",
                "comments.json",
                "reviews.json",
                "review-threads.json",
                "unresolved-review-threads.json",
                "online-review-summary.json",
                "merge-base.txt",
                "merge-tree.txt",
                "merge-resolution.json",
            ):
                if not (pr_dir / filename).exists():
                    raise SystemExit(f"missing-code-remediate-pr-artifact:{filename}")
            routing = _load_json(pr_dir / "pr-routing.json")
            remote_selection = _load_json(pr_dir / "remote-selection.json")
            target_branch = _load_json(pr_dir / "target-branch.json")
            checkout = _load_json(pr_dir / "local-checkout.json")
            if routing.get("local_checkout_required") is not True:
                raise SystemExit("code-remediate-pr-routing-local-checkout-not-required")
            if "--force" in str(routing.get("local_checkout_command", "")):
                raise SystemExit("code-remediate-pr-routing-force-checkout-forbidden")
            if "force_policy" not in routing:
                raise SystemExit("code-remediate-pr-routing-force-policy-missing")
            if target_branch.get("status") != "fetched":
                raise SystemExit("code-remediate-pr-target-branch-not-fetched")
            if checkout.get("status") != "checked-out":
                raise SystemExit("code-remediate-pr-local-checkout-not-checked-out")
            if "--force" in str(checkout.get("command", "")):
                raise SystemExit("code-remediate-pr-local-checkout-force-forbidden")
            if "force_policy" not in checkout:
                raise SystemExit("code-remediate-pr-local-checkout-force-policy-missing")
            if checkout.get("head_matches_pr") is not True:
                raise SystemExit("code-remediate-pr-local-checkout-head-mismatch")
            _validate_code_remediate_pr_identity(routing, remote_selection, target_branch, checkout)
            _validate_code_remediate_merge_resolution(metadata, pr_dir, target_branch)
            if (pr_dir / "head-files").exists():
                raise SystemExit("code-remediate-pr-raw-head-file-snapshots-forbidden")
            _require_file_sections(
                out_dir / "merge-prestage.md",
                [
                    "PR And Target Refresh",
                    "Clean PR Implementation Context",
                    "Target Branch Context",
                    "Conflict Risk",
                    "Resolution Strategy",
                    "Merge Execution",
                ],
            )
            action_text = (out_dir / "action-items.md").read_text(encoding="utf-8").lower()
            required = (
                "valid",
                "resolved",
                "duplicate",
                "stale",
                "out-of-scope",
                "already-fixed",
                "already-applied",
                "needs-clarification",
            )
            if not any(status in action_text for status in required):
                raise SystemExit("code-remediate-pr-triage-status-missing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill", required=True, choices=sorted(SKILL_REQUIREMENTS), help="Skill contract to validate."
    )
    parser.add_argument("--out", required=True, type=Path, help="Skill artifact directory.")
    parser.add_argument("--result", required=True, type=Path, help="Candidate result JSON to validate.")
    args = parser.parse_args()

    validate(args.skill, args.out, args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
