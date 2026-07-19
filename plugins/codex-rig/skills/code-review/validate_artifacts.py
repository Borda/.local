#!/usr/bin/env python3
"""Validate review-skill artifacts for multi-axis specialist evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    "Confidence Calibration",
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
VALID_MODES = {"spawned", "substituted"}
TRANSIENT_RETRY_ERRORS = {"rate_limited", "timeout", "transport_error"}


def _agent_string_setting(path: Path, key: str) -> str:
    """Read one required top-level quoted string from a managed agent file."""
    match = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"\s*$', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"provenance-role-setting-missing:{path.name}:{key}")
    return match.group(1)


ROUTING_SIGNALS = {
    "behavior_change",
    "bug_fix",
    "test_or_error_path",
    "data_tensor_boundary",
    "high_candidate",
    "unresolved_material_assumption",
    "material_no_finding",
    "explicit_adversarial",
    "axis_solution_architect",
    "axis_security_auditor",
    "axis_data_steward",
    "axis_cicd_steward",
    "axis_linting_expert",
    "axis_doc_scribe",
    "axis_oss_shepherd",
    "axis_squeezer",
    "axis_scientist",
    "axis_web_explorer",
}
CONDITIONAL_SIGNALS = {
    "solution-architect": "axis_solution_architect",
    "security-auditor": "axis_security_auditor",
    "data-steward": "axis_data_steward",
    "cicd-steward": "axis_cicd_steward",
    "linting-expert": "axis_linting_expert",
    "doc-scribe": "axis_doc_scribe",
    "oss-shepherd": "axis_oss_shepherd",
    "squeezer": "axis_squeezer",
    "scientist": "axis_scientist",
    "web-explorer": "axis_web_explorer",
}


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
    if not path.is_absolute() and not path.exists():
        path = out_dir / path
    resolved = path.resolve()
    if not resolved.is_relative_to(out_dir.resolve()):
        raise SystemExit(f"artifact-path-outside-review-output:{raw_path}")
    return resolved


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for an evidence file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read valid object rows from a Codex rollout log."""
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _find_rollout(codex_home: Path, thread_id: str) -> Path:
    """Find the unique rollout log for a Codex thread ID."""
    matches = list((codex_home / "sessions").rglob(f"*{thread_id}*.jsonl"))
    if len(matches) != 1:
        raise SystemExit(f"provenance-rollout-count:{thread_id}:{len(matches)}")
    return matches[0]


def _event_payloads(rows: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    """Select event-message payloads of one type."""
    return [
        row["payload"]
        for row in rows
        if row.get("type") == "event_msg"
        and isinstance(row.get("payload"), dict)
        and row["payload"].get("type") == event_type
    ]


def _path_tokens(path: str) -> set[str]:
    """Split a repository path into exact lowercase risk tokens."""
    return {token for token in re.split(r"[/._-]+", path.lower()) if token}


def _mechanical_risk(out_dir: Path) -> tuple[str, list[str], set[str]]:
    """Derive a minimum review tier and mandatory signals from collected diff facts."""
    paths: set[str] = set()
    for filename in ("files.txt", "untracked.txt"):
        path = out_dir / filename
        if path.exists():
            paths.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    changed_lines = 0
    unknown_size_rows = 0
    numstat = out_dir / "numstat.txt"
    if numstat.exists():
        for line in numstat.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t", 2)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                changed_lines += int(parts[0]) + int(parts[1])
            elif len(parts) >= 2:
                unknown_size_rows += 1

    lower_paths = {path.lower() for path in paths}
    evidence = [f"files={len(paths)}", f"changed_lines={changed_lines}", f"unknown_size_rows={unknown_size_rows}"]
    broad_names = {"pyproject.toml", "package.json", "cargo.toml", "uv.lock", "poetry.lock", "package-lock.json"}
    security_parts = {"auth", "authentication", "credential", "credentials", "security"}
    high_risk_parts = security_parts | {"migration", "migrations"}
    high_paths = sorted(
        path
        for path in lower_paths
        if path.startswith(".github/workflows/")
        or high_risk_parts.intersection(_path_tokens(path))
        or "deserial" in Path(path).name
    )
    config_paths = sorted(
        path
        for path in lower_paths
        if path in broad_names or path.endswith(("config.toml", "config.yaml", "config.yml"))
    )
    if high_paths:
        tier = "HIGH_RISK"
        evidence.append("high_risk_paths=" + ",".join(high_paths))
    elif len(paths) >= 8 or config_paths or unknown_size_rows:
        tier = "BROAD"
        if config_paths:
            evidence.append("config_or_dependency_paths=" + ",".join(config_paths))
    elif len(paths) < 3 and changed_lines < 50:
        tier = "TRIVIAL"
    else:
        tier = "LOCAL"

    mandatory_signals: set[str] = set()
    if any(path.startswith("tests/") or "/tests/" in path for path in lower_paths):
        mandatory_signals.add("test_or_error_path")
    if any(any(marker in path for marker in ("tensor", "dataset", "dataloader", "data/")) for path in lower_paths):
        mandatory_signals.update({"data_tensor_boundary", "axis_data_steward"})
    if any(path.startswith(".github/") for path in lower_paths):
        mandatory_signals.add("axis_cicd_steward")
    if any(path.endswith((".md", ".rst")) or path.startswith("docs/") for path in lower_paths):
        mandatory_signals.add("axis_doc_scribe")
    if high_paths and any(
        security_parts.intersection(_path_tokens(path)) or "deserial" in Path(path).name for path in high_paths
    ):
        mandatory_signals.add("axis_security_auditor")
    return tier, evidence, mandatory_signals


def _validate_routing(out_dir: Path, risk_tier: str) -> set[str]:
    """Derive triggered specialist roles from explicit review-risk signals."""
    routing = _load_json(out_dir / "review-routing.json")
    if routing.get("schema_version") != 1:
        raise SystemExit("review-routing-schema-version")
    if routing.get("risk_tier") != risk_tier:
        raise SystemExit("review-routing-risk-tier-mismatch")
    mechanical_tier, mechanical_evidence, mandatory_signals = _mechanical_risk(out_dir)
    tier_rank = {"TRIVIAL": 0, "LOCAL": 1, "BROAD": 2, "HIGH_RISK": 3}
    if tier_rank[risk_tier] < tier_rank[mechanical_tier]:
        raise SystemExit(f"review-routing-tier-underclassified:{mechanical_tier}:{risk_tier}")
    if routing.get("mechanical_risk_tier") != mechanical_tier:
        raise SystemExit("review-routing-mechanical-tier-mismatch")
    if routing.get("mechanical_risk_evidence") != mechanical_evidence:
        raise SystemExit("review-routing-mechanical-evidence-mismatch")
    signals = routing.get("signals")
    if not isinstance(signals, dict) or set(signals) != ROUTING_SIGNALS:
        raise SystemExit("review-routing-signal-set-mismatch")
    if not all(isinstance(value, bool) for value in signals.values()):
        raise SystemExit("review-routing-signals-not-boolean")
    signal_evidence = routing.get("signal_evidence")
    if not isinstance(signal_evidence, dict) or set(signal_evidence) != ROUTING_SIGNALS:
        raise SystemExit("review-routing-signal-evidence-set-mismatch")
    if not all(
        isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value)
        for value in signal_evidence.values()
    ):
        raise SystemExit("review-routing-signal-evidence-empty")
    missing_mandatory = sorted(signal for signal in mandatory_signals if not signals[signal])
    if missing_mandatory:
        raise SystemExit("review-routing-mechanical-signals-false:" + ",".join(missing_mandatory))

    triggered: set[str] = set()
    if risk_tier in INDEPENDENT_PASS_TIERS:
        triggered.update(REQUIRED_ROLES)
    if risk_tier in {"TRIVIAL", "LOCAL"} and any(
        signals[name] for name in ("behavior_change", "bug_fix", "test_or_error_path", "data_tensor_boundary")
    ):
        triggered.add("qa-specialist")
    if risk_tier in {"TRIVIAL", "LOCAL"} and any(
        signals[name]
        for name in (
            "high_candidate",
            "unresolved_material_assumption",
            "material_no_finding",
            "explicit_adversarial",
        )
    ):
        triggered.add("challenger")
    triggered.update(role for role, signal in CONDITIONAL_SIGNALS.items() if signals[signal])

    declared = routing.get("triggered_roles")
    if not isinstance(declared, list) or declared != sorted(triggered):
        raise SystemExit("review-routing-triggered-role-mismatch")
    reasons = routing.get("trigger_reasons")
    if not isinstance(reasons, dict) or set(reasons) != triggered:
        raise SystemExit("review-routing-trigger-reason-mismatch")
    if not all(isinstance(value, list) and value for value in reasons.values()):
        raise SystemExit("review-routing-trigger-reason-empty")
    return triggered


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


def _validate_confidence_gaps(result: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Validate confidence gap metadata whenever review confidence is reported."""
    confidence_gaps = metadata.get("confidence_gaps")
    if not isinstance(confidence_gaps, list) or not all(isinstance(item, str) for item in confidence_gaps):
        raise SystemExit("review-invalid-confidence-gaps")
    if float(result["confidence"]) < 1.0 and not any(item.strip() for item in confidence_gaps):
        raise SystemExit("review-confidence-gaps-required")
    _validate_confidence_gap_closures(metadata, confidence_gaps)


def _validate_confidence_gap_closures(metadata: dict[str, Any], confidence_gaps: list[str]) -> None:
    """Validate that every review confidence gap has closure evidence or carry-forward state."""
    active_gaps = [gap.strip() for gap in confidence_gaps if gap.strip()]
    if not active_gaps:
        return

    closures = metadata.get("confidence_gap_closures")
    if not isinstance(closures, list):
        raise SystemExit("review-missing-confidence-gap-closures")

    closed_gaps: set[str] = set()
    for index, closure in enumerate(closures):
        if not isinstance(closure, dict):
            raise SystemExit(f"review-confidence-gap-closure-not-object:{index}")
        gap = closure.get("gap")
        if not isinstance(gap, str) or not gap.strip():
            raise SystemExit(f"review-confidence-gap-closure-missing-gap:{index}")
        status = closure.get("status")
        if status not in {"closed", "unresolved", "deferred"}:
            raise SystemExit(f"review-confidence-gap-closure-invalid-status:{index}")
        evidence = closure.get("evidence") or closure.get("evidence_path")
        rationale = closure.get("rationale")
        if status == "closed" and not (isinstance(evidence, str) and evidence.strip()):
            raise SystemExit(f"review-confidence-gap-closure-missing-evidence:{index}")
        if status in {"unresolved", "deferred"} and not (isinstance(rationale, str) and rationale.strip()):
            raise SystemExit(f"review-confidence-gap-closure-missing-rationale:{index}")
        closed_gaps.add(gap.strip())

    missing = sorted(set(active_gaps) - closed_gaps)
    if missing:
        raise SystemExit(f"review-confidence-gap-closure-missing:{','.join(missing)}")


def _require_non_empty_string_list(payload: dict[str, Any], key: str, context: str) -> list[str]:
    """Return a required non-empty list of non-blank strings from a metadata object."""
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise SystemExit(f"{context}-invalid-{key}")
    return value


def _validate_confidence_recovery(result: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Validate evidence-backed confidence recovery metadata for review artifacts."""
    confidence = result.get("confidence")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise SystemExit("invalid-confidence")
    checks_failed = result.get("checks_failed")
    if not isinstance(checks_failed, list):
        raise SystemExit("invalid-checks-failed")

    recovery = metadata.get("confidence_recovery")
    if not isinstance(recovery, dict):
        raise SystemExit("review-missing-confidence-recovery-metadata")

    initial = recovery.get("initial_confidence")
    final = recovery.get("final_confidence")
    if not isinstance(initial, int | float) or not 0.0 <= float(initial) <= 1.0:
        raise SystemExit("review-invalid-initial-confidence")
    if not isinstance(final, int | float) or not 0.0 <= float(final) <= 1.0:
        raise SystemExit("review-invalid-final-confidence")
    if abs(float(final) - float(confidence)) > 0.001:
        raise SystemExit("review-confidence-recovery-final-mismatch")

    status = recovery.get("status")
    if status not in {"fair", "cautious-low", "very-questionable", "not-acceptable-failed"}:
        raise SystemExit("review-invalid-confidence-recovery-status")

    _require_non_empty_string_list(recovery, "evidence", "code-review")
    recovery_actions = _require_non_empty_string_list(recovery, "recovery_actions", "code-review")
    remaining_limits = recovery.get("remaining_limits")
    if not isinstance(remaining_limits, list) or not all(isinstance(item, str) for item in remaining_limits):
        raise SystemExit("review-invalid-remaining-limits")

    confidence_value = float(confidence)
    if confidence_value <= 0.8:
        if result["status"] == "pass":
            raise SystemExit("review-pass-confidence-not-acceptable")
        if "confidence-not-acceptable" not in checks_failed:
            raise SystemExit("review-missing-confidence-not-acceptable-check")
        if status != "not-acceptable-failed":
            raise SystemExit("review-confidence-status-should-fail")
        if not recovery_actions or not remaining_limits:
            raise SystemExit("review-low-confidence-recovery-missing")
    elif confidence_value < 0.85:
        if result["status"] == "pass":
            raise SystemExit("review-pass-confidence-very-questionable")
        if "confidence-very-questionable" not in checks_failed:
            raise SystemExit("review-missing-confidence-very-questionable-check")
        if status != "very-questionable":
            raise SystemExit("review-confidence-status-should-be-very-questionable")
        if not recovery_actions or not remaining_limits:
            raise SystemExit("review-very-questionable-confidence-evidence-missing")
    elif confidence_value < 0.9:
        if status != "cautious-low":
            raise SystemExit("review-confidence-status-should-be-cautious-low")
        if not recovery_actions or not remaining_limits:
            raise SystemExit("review-cautious-low-confidence-evidence-missing")
    elif status != "fair":
        raise SystemExit("review-confidence-status-should-be-fair")


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


def _validate_spawn_attempts(
    out_dir: Path,
    item: dict[str, Any],
    manifest: dict[str, Any],
    codex_home: Path,
    parent_rows: list[dict[str, Any]],
    used_threads: set[str],
    project_root: Path,
) -> None:
    """Bind a spawned specialist output to parent and child rollout evidence."""
    role = str(item["role"])
    attempts = item.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise SystemExit(f"manifest-invalid-attempt-count:{role}")
    if not all(isinstance(attempt, dict) for attempt in attempts):
        raise SystemExit(f"manifest-attempt-not-object:{role}")
    if [attempt.get("attempt") for attempt in attempts] != list(range(1, len(attempts) + 1)):
        raise SystemExit(f"manifest-attempt-sequence:{role}")
    if len(attempts) == 2 and (
        attempts[0].get("status") == "completed" or attempts[0].get("error_type") not in TRANSIENT_RETRY_ERRORS
    ):
        raise SystemExit(f"manifest-invalid-retry:{role}")
    selected = item.get("selected_attempt")
    if not isinstance(selected, int) or selected < 1 or selected > len(attempts):
        raise SystemExit(f"manifest-invalid-selected-attempt:{role}")

    parent_events = _event_payloads(parent_rows, "sub_agent_activity")
    for attempt in attempts:
        thread_id = attempt.get("agent_thread_id")
        event_id = attempt.get("event_id")
        agent_path = attempt.get("agent_path")
        if not all(isinstance(value, str) and value for value in (thread_id, event_id, agent_path)):
            raise SystemExit(f"manifest-attempt-identity-missing:{role}")
        context_path = _resolve_path(out_dir, attempt.get("context_path"))
        context_sha256 = attempt.get("context_sha256")
        if not context_path.exists() or _sha256(context_path) != context_sha256:
            raise SystemExit(f"provenance-context-hash-mismatch:{role}")
        expected_agent_name = f"review_{role.replace('-', '_')}_{context_sha256[:12]}_a{attempt['attempt']}"
        if Path(agent_path).name != expected_agent_name:
            raise SystemExit(f"provenance-agent-path-context-mismatch:{role}:{agent_path}")
        if thread_id in used_threads:
            raise SystemExit(f"manifest-reused-agent-thread:{thread_id}")
        used_threads.add(thread_id)
        matches = [
            event
            for event in parent_events
            if event.get("event_id") == event_id
            and event.get("agent_thread_id") == thread_id
            and event.get("agent_path") == agent_path
            and event.get("kind") == "started"
        ]
        if len(matches) != 1:
            raise SystemExit(f"provenance-parent-spawn-mismatch:{role}:{attempt['attempt']}")

        child_rows = _read_jsonl(_find_rollout(codex_home, thread_id))
        session_rows = [
            row["payload"]
            for row in child_rows
            if row.get("type") == "session_meta"
            and isinstance(row.get("payload"), dict)
            and row["payload"].get("id") == thread_id
        ]
        if len(session_rows) != 1:
            raise SystemExit(f"provenance-child-session-count:{thread_id}")
        session = session_rows[0]
        spawn = session.get("source", {}).get("subagent", {}).get("thread_spawn", {})
        if session.get("id") != thread_id or spawn.get("parent_thread_id") != manifest["parent_thread_id"]:
            raise SystemExit(f"provenance-child-parent-mismatch:{thread_id}")
        session_path = session.get("agent_path") or spawn.get("agent_path")
        if session_path != agent_path:
            raise SystemExit(f"provenance-child-path-mismatch:{role}:{session_path}")
        session_role = session.get("agent_role") or spawn.get("agent_role")
        if session_role is not None and session_role != role:
            raise SystemExit(f"provenance-child-role-mismatch:{role}:{session_role}")

        if attempt.get("status") != "completed":
            if attempt.get("error_type") not in TRANSIENT_RETRY_ERRORS or attempt["attempt"] == selected:
                raise SystemExit(f"manifest-invalid-failed-attempt:{role}:{attempt['attempt']}")
            continue

        turn_id = attempt.get("turn_id")
        contexts = [
            row["payload"]
            for row in child_rows
            if row.get("type") == "turn_context"
            and isinstance(row.get("payload"), dict)
            and row["payload"].get("turn_id") == turn_id
        ]
        if len(contexts) != 1:
            raise SystemExit(f"provenance-turn-context-mismatch:{thread_id}")
        context = contexts[0]
        if context.get("model") != attempt.get("model") or context.get("effort") != attempt.get("effort"):
            raise SystemExit(f"provenance-model-effort-mismatch:{thread_id}")
        config_path = project_root / ".codex" / "agents" / f"{role}.toml"
        if context.get("model") != _agent_string_setting(config_path, "model"):
            raise SystemExit(f"provenance-role-model-policy-mismatch:{role}:{thread_id}")
        if context.get("effort") != _agent_string_setting(config_path, "model_reasoning_effort"):
            raise SystemExit(f"provenance-role-effort-policy-mismatch:{role}:{thread_id}")
        completions = [
            event for event in _event_payloads(child_rows, "task_complete") if event.get("turn_id") == turn_id
        ]
        if len(completions) != 1 or not isinstance(completions[0].get("last_agent_message"), str):
            raise SystemExit(f"provenance-task-complete-mismatch:{thread_id}")

        output_path = _resolve_path(out_dir, attempt.get("output_path"))
        if not output_path.exists() or _sha256(output_path) != attempt.get("output_sha256"):
            raise SystemExit(f"provenance-output-hash-mismatch:{role}")
        message = completions[0]["last_agent_message"].strip()
        if output_path.read_text(encoding="utf-8").strip() != message:
            raise SystemExit(f"provenance-output-message-mismatch:{role}")
        expected_header = (
            f"<!-- codex-review-provenance role={role} run={manifest['review_run_id']} "
            f"input={manifest['review_input_sha256']} context={attempt['context_sha256']} "
            f"attempt={attempt['attempt']} -->"
        )
        if message.splitlines()[0] != expected_header:
            raise SystemExit(f"provenance-output-header-mismatch:{role}")

    if attempts[selected - 1].get("status") != "completed":
        raise SystemExit(f"manifest-selected-attempt-not-completed:{role}")
    canonical_output = _resolve_path(out_dir, item.get("output_path"))
    selected_output = _resolve_path(out_dir, attempts[selected - 1].get("output_path"))
    if canonical_output != selected_output:
        raise SystemExit(f"manifest-selected-output-mismatch:{role}")


def _validate_manifest_entries(
    out_dir: Path,
    manifest: dict[str, Any],
    passes: list[dict[str, Any]],
    triggered_roles: set[str],
    codex_home: Path,
    parent_thread_id: str,
    project_root: Path,
) -> dict[str, dict[str, Any]]:
    if manifest.get("schema_version") != 2:
        raise SystemExit("manifest-schema-version")
    for key in ("review_run_id", "parent_thread_id", "review_input_sha256"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise SystemExit(f"manifest-missing-{key}")
    if manifest["parent_thread_id"] != parent_thread_id:
        raise SystemExit("manifest-parent-thread-mismatch")
    review_input = out_dir / "diff.patch"
    if not review_input.exists() or _sha256(review_input) != manifest["review_input_sha256"]:
        raise SystemExit("manifest-review-input-hash-mismatch")
    parent_rows = _read_jsonl(_find_rollout(codex_home, parent_thread_id))
    used_threads: set[str] = set()
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
        output_path = _resolve_path(out_dir, item.get("output_path"))
        if not output_path.exists():
            raise SystemExit(f"manifest-missing-output:{role}:{output_path}")
        if mode == "spawned":
            _validate_spawn_attempts(out_dir, item, manifest, codex_home, parent_rows, used_threads, project_root)
        elif item.get("attempts") not in (None, []):
            raise SystemExit(f"manifest-substitute-has-attempts:{role}")
        by_role[role] = item

    if set(by_role) != triggered_roles:
        raise SystemExit("manifest-triggered-role-set-mismatch")
    return by_role


def _validate_result(
    out_dir: Path,
    result_path: Path,
    codex_home: Path,
    parent_thread_id: str,
    project_root: Path,
) -> None:
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
    _validate_confidence_gaps(result, metadata)
    _validate_confidence_recovery(result, metadata)
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
            "remote-selection.json",
            "diff.patch",
        ):
            if not (out_dir / filename).exists():
                raise SystemExit(f"missing-pr-artifact:{filename}")
        routing = _load_json(out_dir / "pr-routing.json")
        remote_selection = _load_json(out_dir / "remote-selection.json")
        target_branch = _load_json(out_dir / "target-branch.json")
        checkout = _load_json(out_dir / "local-checkout.json")
        if routing.get("base_identity_source") != "pr_url":
            raise SystemExit("pr-routing-base-identity-not-authoritative")
        expected_identity = remote_selection.get("expected")
        if not isinstance(expected_identity, dict):
            raise SystemExit("pr-remote-selection-expected-missing")
        if expected_identity.get("host") != routing.get("base_host"):
            raise SystemExit("pr-remote-selection-host-mismatch")
        if expected_identity.get("repository") != routing.get("base_repo"):
            raise SystemExit("pr-remote-selection-repository-mismatch")
        if routing.get("local_checkout_required") is not True:
            raise SystemExit("pr-routing-local-checkout-not-required")
        if "--force" in str(routing.get("local_checkout_command", "")):
            raise SystemExit("pr-routing-force-checkout-forbidden")
        if "force_policy" not in routing:
            raise SystemExit("pr-routing-force-policy-missing")
        if target_branch.get("status") != "fetched":
            raise SystemExit("pr-target-branch-not-fetched")
        if target_branch.get("remote") != remote_selection.get("remote"):
            raise SystemExit("pr-target-branch-remote-mismatch")
        if target_branch.get("remote_url") != remote_selection.get("remote_url"):
            raise SystemExit("pr-target-branch-remote-url-mismatch")
        expected_base = target_branch.get("expected_base_oid")
        local_base = target_branch.get("local_head")
        if not expected_base or expected_base != routing.get("base_oid"):
            raise SystemExit("pr-target-branch-expected-oid-missing")
        if not local_base or local_base != expected_base or target_branch.get("base_matches_pr_metadata") is not True:
            raise SystemExit("pr-target-branch-oid-mismatch")
        if checkout.get("status") != "checked-out":
            raise SystemExit("pr-local-checkout-not-checked-out")
        if checkout.get("pr_url") != routing.get("pr_url"):
            raise SystemExit("pr-local-checkout-url-mismatch")
        if "--force" in str(checkout.get("command", "")):
            raise SystemExit("pr-local-checkout-force-forbidden")
        if "force_policy" not in checkout:
            raise SystemExit("pr-local-checkout-force-policy-missing")
        if checkout.get("head_matches_pr") is not True:
            raise SystemExit("pr-local-checkout-head-mismatch")
        if not checkout.get("expected_head") or checkout.get("expected_head") != routing.get("head_oid"):
            raise SystemExit("pr-local-checkout-expected-head-missing")
        if checkout.get("local_head") != checkout.get("expected_head"):
            raise SystemExit("pr-local-checkout-oid-mismatch")
        if (out_dir / "head-files").exists():
            raise SystemExit("pr-raw-head-file-snapshots-forbidden")

    triggered_roles = _validate_routing(out_dir, risk_tier)
    manifest_path = _resolve_path(out_dir, metadata.get("specialist_manifest"))
    manifest = _load_json(manifest_path)
    passes = _manifest_passes(manifest)
    by_role = _validate_manifest_entries(
        out_dir,
        manifest,
        passes,
        triggered_roles,
        codex_home,
        parent_thread_id,
        project_root,
    )
    if metadata.get("review_run_id") != manifest.get("review_run_id"):
        raise SystemExit("metadata-review-run-id-mismatch")
    if metadata.get("review_input_sha256") != manifest.get("review_input_sha256"):
        raise SystemExit("metadata-review-input-hash-mismatch")

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
        for key in (
            "axis",
            "trigger",
            "mode",
            "output_path",
            "confidence",
            "blocking_findings",
            "attempts",
            "selected_attempt",
        ):
            if metadata_item.get(key) != item.get(key):
                raise SystemExit(f"metadata-specialist-pass-mismatch:{role}:{key}")

    triggered_required = REQUIRED_ROLES & triggered_roles
    substituted_roles = sorted(role for role in triggered_required if by_role[role]["mode"] == "substituted")
    independence_required = bool(triggered_required)
    required_independent = independence_required and all(
        by_role[role]["mode"] == "spawned" for role in triggered_required
    )
    if risk_tier in INDEPENDENT_PASS_TIERS and status == "pass" and not required_independent:
        raise SystemExit("independent-review-required-for-pass:" + ",".join(substituted_roles))

    fanout_substituted = any(item["mode"] == "substituted" for item in passes)
    if metadata.get("fanout_substituted") is not fanout_substituted:
        raise SystemExit("metadata-fanout-substituted-mismatch")

    independence_satisfied = bool(required_independent)
    if metadata.get("independence_satisfied") is not independence_satisfied:
        raise SystemExit("metadata-independence-satisfied-mismatch")
    if metadata.get("independence_required") is not independence_required:
        raise SystemExit("metadata-independence-required-mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Review output directory.")
    parser.add_argument("--result", required=True, type=Path, help="Candidate result.json path.")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        help="Codex home containing rollout session logs.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="Project root containing .codex agents.")
    parser.add_argument(
        "--parent-thread-id",
        default=os.environ.get("CODEX_THREAD_ID", ""),
        help="Current parent Codex thread ID.",
    )
    args = parser.parse_args()

    if not args.parent_thread_id:
        raise SystemExit("missing-parent-thread-id")
    _validate_result(args.out, args.result, args.codex_home, args.parent_thread_id, args.project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
