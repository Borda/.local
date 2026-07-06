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

SKILL_REQUIREMENTS: dict[str, dict[str, object]] = {
    "develop": {
        "files": {
            "development-notes.md": ["Scope", "Acceptance Criteria", "Evidence", "Specialist Policy", "Gates"],
        },
    },
    "resolve": {
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


def _validate_gates(out_dir: Path) -> None:
    gates_path = out_dir / "gates.json"
    if not gates_path.exists():
        return
    gates = _load_json(gates_path)
    checks = gates.get("checks")
    if not isinstance(checks, list):
        raise SystemExit("gates-missing-check-details")
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise SystemExit(f"gate-check-not-object:{index}")
        for key in ("id", "status", "command_path", "stdout", "stderr", "duration_seconds"):
            if key not in check:
                raise SystemExit(f"gate-check-missing-field:{index}:{key}")
        if check["status"] not in {"pass", "fail", "missing-command"}:
            raise SystemExit(f"gate-check-invalid-status:{index}:{check['status']!r}")
        if check["status"] != "missing-command" and not isinstance(check.get("exit_code"), int):
            raise SystemExit(f"gate-check-invalid-exit-code:{index}")
        for key in ("command_path", "stdout", "stderr"):
            if not Path(str(check[key])).exists():
                raise SystemExit(f"gate-check-missing-log:{index}:{key}")


def validate(skill: str, out_dir: Path, result_path: Path) -> None:
    result = _load_json(result_path)
    _require_result_shape(result)
    _validate_gates(out_dir)

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
    if skill == "resolve":
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            raise SystemExit("resolve-missing-metadata")
        resolution_scope = metadata.get("resolution_scope")
        if not isinstance(resolution_scope, dict):
            raise SystemExit("resolve-missing-resolution-scope-metadata")
        scope_text = (out_dir / "resolution-scope.md").read_text(encoding="utf-8").lower()
        for required_text in ("selectable", "selected", "deferred"):
            if required_text not in scope_text:
                raise SystemExit(f"resolve-scope-missing-{required_text}")
        pr_dir = out_dir / "pr"
        if metadata.get("mode") == "pr" or pr_dir.exists():
            for filename in (
                "pr.json",
                "pr-routing.json",
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
            ):
                if not (pr_dir / filename).exists():
                    raise SystemExit(f"missing-resolve-pr-artifact:{filename}")
            routing = _load_json(pr_dir / "pr-routing.json")
            target_branch = _load_json(pr_dir / "target-branch.json")
            checkout = _load_json(pr_dir / "local-checkout.json")
            if routing.get("local_checkout_required") is not True:
                raise SystemExit("resolve-pr-routing-local-checkout-not-required")
            if "--force" in str(routing.get("local_checkout_command", "")):
                raise SystemExit("resolve-pr-routing-force-checkout-forbidden")
            if "force_policy" not in routing:
                raise SystemExit("resolve-pr-routing-force-policy-missing")
            if target_branch.get("status") != "fetched":
                raise SystemExit("resolve-pr-target-branch-not-fetched")
            if not target_branch.get("local_head"):
                raise SystemExit("resolve-pr-target-branch-head-missing")
            if checkout.get("status") != "checked-out":
                raise SystemExit("resolve-pr-local-checkout-not-checked-out")
            if "--force" in str(checkout.get("command", "")):
                raise SystemExit("resolve-pr-local-checkout-force-forbidden")
            if "force_policy" not in checkout:
                raise SystemExit("resolve-pr-local-checkout-force-policy-missing")
            if checkout.get("head_matches_pr") is not True:
                raise SystemExit("resolve-pr-local-checkout-head-mismatch")
            if (pr_dir / "head-files").exists():
                raise SystemExit("resolve-pr-raw-head-file-snapshots-forbidden")
            _require_file_sections(
                out_dir / "merge-prestage.md",
                [
                    "PR And Target Refresh",
                    "Clean PR Implementation Context",
                    "Target Branch Context",
                    "Conflict Risk",
                    "Resolution Strategy",
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
                raise SystemExit("resolve-pr-triage-status-missing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, choices=sorted(SKILL_REQUIREMENTS))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()

    validate(args.skill, args.out, args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
