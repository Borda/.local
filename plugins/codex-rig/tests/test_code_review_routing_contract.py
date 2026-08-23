"""Regression checks for deterministic code-review routing artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CODE_REVIEW_SKILL = PLUGIN_ROOT / "skills" / "code-review" / "SKILL.md"
REVIEW_VALIDATOR = PLUGIN_ROOT / "skills" / "code-review" / "validate_artifacts.py"
ROUTING_HELPER = PLUGIN_ROOT / "skills" / "code-review" / "review_routing.py"


def load_validator() -> ModuleType:
    """Load the shipped standalone validator from its installed-package path."""
    specification = importlib.util.spec_from_file_location("code_review_routing_validator", REVIEW_VALIDATOR)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_action_table_parser_accepts_the_canonical_section_and_stops_at_the_next_heading() -> None:
    """Prevent regex overescaping from rejecting a valid remediation table."""
    notes = """# Review

## Review Findings and Merge Blocks

| Finding / area | Required change | Evidence | Status |
| --- | --- | --- | --- |
| Parser | Accept the canonical table. | `review-notes.md` | Required |

## Confidence Calibration

| This | is | not | a finding |
"""

    rows = load_validator()._action_table_rows(notes)

    assert rows == [
        ["Finding / area", "Required change", "Evidence", "Status"],
        ["---", "---", "---", "---"],
        ["Parser", "Accept the canonical table.", "`review-notes.md`", "Required"],
    ]


def test_routing_helper_replaces_manual_mechanical_evidence_idempotently(tmp_path: Path) -> None:
    """Keep file and line arithmetic derived from collected evidence instead of model-authored JSON."""
    validator = load_validator()
    signals = {name: False for name in validator.ROUTING_SIGNALS}
    signals.update({"bug_fix": True, "test_or_error_path": True})
    (tmp_path / "files.txt").write_text("src/widget.py\ntests/test_widget.py\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("", encoding="utf-8")
    (tmp_path / "numstat.txt").write_text(
        "51\t14\tsrc/widget.py\n278\t0\ttests/test_widget.py\n",
        encoding="utf-8",
    )
    routing_path = tmp_path / "review-routing.json"
    routing_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "risk_tier": "LOCAL",
                "mechanical_risk_tier": "TRIVIAL",
                "mechanical_risk_evidence": ["files=2", "changed_lines=329", "unknown_size_rows=0"],
                "signals": signals,
                "signal_evidence": {
                    name: ["Fixture requires this signal."] if value else ["Fixture does not require this signal."]
                    for name, value in signals.items()
                },
                "triggered_roles": ["qa-specialist"],
                "trigger_reasons": {"qa-specialist": ["Bug-fix and test-path evidence require QA."]},
            }
        ),
        encoding="utf-8",
    )

    first = subprocess.run(
        [sys.executable, str(ROUTING_HELPER), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_bytes = routing_path.read_bytes()
    second = subprocess.run(
        [sys.executable, str(ROUTING_HELPER), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert routing_path.read_bytes() == first_bytes

    routing = json.loads(first_bytes)
    assert routing["mechanical_risk_tier"] == "LOCAL"
    assert routing["mechanical_risk_evidence"] == ["files=2", "changed_lines=343", "unknown_size_rows=0"]
    assert routing["signals"] == signals
    assert validator._validate_routing(tmp_path, "LOCAL") == {"qa-specialist"}


def test_skill_requires_deterministic_routing_synchronization_before_specialists() -> None:
    """Keep the producer workflow bound to the same mechanical evidence used by validation."""
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8")
    invocation = "python PLUGIN_ROOT/skills/code-review/review_routing.py --out <run-directory>"

    assert invocation in skill
    manifest_path = "`<run-directory>/specialist-manifest.json`"
    assert skill.index(invocation) < skill.index(manifest_path)


def test_skill_requires_list_valued_routing_evidence_and_reasons() -> None:
    """Prevent a valid-looking string value from stranding a review as an unpromoted candidate."""
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8")

    assert "non-empty JSON `list[str]` value for each true/false decision" in skill
    assert "non-empty JSON `list[str]` value" in skill
    assert "Bare strings are invalid." in skill


def test_manifest_preflight_rejects_spawned_pass_without_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch malformed specialist cardinality before a result candidate exists."""
    validator = load_validator()
    review_input = b"diff --git a/widget.py b/widget.py\n"
    (tmp_path / "diff.patch").write_bytes(review_input)
    specialists = tmp_path / "specialists"
    specialists.mkdir()
    (specialists / "qa-specialist.md").write_text("QA evidence.\n", encoding="utf-8")
    (tmp_path / "review-routing.json").write_text(json.dumps({"risk_tier": "LOCAL"}), encoding="utf-8")
    (tmp_path / "specialist-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "review_run_id": "review-run",
                "parent_thread_id": "parent-thread",
                "review_input_sha256": hashlib.sha256(review_input).hexdigest(),
                "passes": [
                    {
                        "role": "qa-specialist",
                        "axis": "tests",
                        "mode": "spawned",
                        "trigger": "bug fix",
                        "confidence": 0.9,
                        "blocking_findings": 1,
                        "output_path": "specialists/qa-specialist.md",
                        "attempts": [],
                        "selected_attempt": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(validator, "_validate_routing", lambda _out, _tier: {"qa-specialist"})
    monkeypatch.setattr(validator, "_find_rollout", lambda _home, _thread: tmp_path / "rollout.jsonl")
    monkeypatch.setattr(validator, "_read_jsonl", lambda _path: [])

    with pytest.raises(SystemExit, match="manifest-invalid-attempt-count:qa-specialist"):
        validator._validate_manifest_preflight(tmp_path, tmp_path, "parent-thread", tmp_path)


def test_review_validator_exposes_manifest_only_preflight() -> None:
    """Keep the executable preflight available to the code-review workflow."""
    completed = subprocess.run(
        [sys.executable, str(REVIEW_VALIDATOR), "--help"], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0
    assert "--manifest-only" in completed.stdout


def test_skill_rebuilds_a_compact_pr_snapshot_before_reporting_findings() -> None:
    """Keep assessed PR handoffs grounded in current review artifacts, not stale chat context."""
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8")

    assert "`PR Snapshot` for every assessed `scope=pr` review" in skill
    assert "`pr.json`, `pr-routing.json`, and `gates.json`" in skill
    assert "`pr.json.statusCheckRollup`" in skill
    assert "An absent or empty rollup is `unavailable`, never `passing`" in skill
    assert "`fix`, `feat`, `refactor`, `perf`, `docs`, `ci`, `chore`, `test`, or `mixed`" in skill
    assert "`approve`, `minor changes`, `needs work`, `reject`, or `not aligned`" in skill
    assert "before any findings" in skill
