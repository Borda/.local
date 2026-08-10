"""Regression coverage for terminal unavailable review-result candidates."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WRITE_RESULT = PLUGIN_ROOT / "shared" / "write-result.py"
REVIEW_VALIDATOR = PLUGIN_ROOT / "skills" / "code-review" / "validate_artifacts.py"
GATE_IDS = ("lint", "format", "types", "tests", "review")
COLLECTION_FAILURE = "github-network:gh-pr-view"
CONFIDENCE_GAP = "PR source evidence was unavailable; no source review or merge decision was made."


def _load_validator() -> object:
    """Load the standalone code-review validator from its shipped location."""
    specification = importlib.util.spec_from_file_location("code_review_validator", REVIEW_VALIDATOR)
    assert specification is not None and specification.loader is not None
    validator = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(validator)
    return validator


def _write_unavailable_pr_evidence(run_dir: Path) -> dict[str, object]:
    """Write the operational evidence required before an unavailable candidate is created."""
    (run_dir / "gates.json").write_text(
        json.dumps({"status": "pass", "checks_failed": [], "checks": [{"id": gate_id} for gate_id in GATE_IDS]}),
        encoding="utf-8",
    )
    (run_dir / "pr-error.txt").write_text(COLLECTION_FAILURE + "\n", encoding="utf-8")
    (run_dir / "pr-target.txt").write_text("123\n", encoding="utf-8")
    (run_dir / "review-notes.md").write_text(
        "# PR Review Availability: unavailable\n\n"
        "Source findings: not assessed\n\n"
        "Merge decision: not made\n\n"
        "## PR Evidence Collection Recovery\n\n"
        "| Operational area | Recovery action | Evidence | Status |\n"
        "| --- | --- | --- | --- |\n"
        "| PR evidence collection | Retry the unchanged collector later; no review or merge decision was made. "
        "| `pr-error.txt`: `github-network:gh-pr-view` | Required verification |\n",
        encoding="utf-8",
    )
    return {
        "scope": "pr",
        "risk_tier": "HIGH_RISK",
        "review_status": "unavailable",
        "collection_failure": {"code": COLLECTION_FAILURE, "artifact": "pr-error.txt"},
        "confidence_gaps": [CONFIDENCE_GAP],
        "confidence_gap_closures": [
            {
                "gap": CONFIDENCE_GAP,
                "status": "unresolved",
                "rationale": "No local checkout or source bundle was produced.",
            }
        ],
        "confidence_recovery": {
            "initial_confidence": 0.9,
            "final_confidence": 0.9,
            "status": "fair",
            "evidence": ["The classified collection failure was retained."],
            "recovery_actions": ["Stopped before source review."],
            "remaining_limits": ["PR correctness was not assessed."],
        },
    }


def test_write_result_unavailable_review_emits_validator_accepted_candidate(tmp_path: Path) -> None:
    """Prevent unavailable PR collection failures from receiving assessed-review result fields."""
    metadata = _write_unavailable_pr_evidence(tmp_path)
    candidate_path = tmp_path / "result.candidate.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(WRITE_RESULT),
            "--out",
            str(candidate_path),
            "--gates",
            str(tmp_path / "gates.json"),
            "--status",
            "fail",
            "--checks-run",
            ",".join(GATE_IDS),
            "--confidence",
            "0.9",
            "--artifact-path",
            str(candidate_path),
            "--metadata",
            json.dumps(metadata),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate["status"] == "fail"
    assert candidate["findings"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert candidate["metadata"]["review_status"] == "unavailable"
    assert candidate["metadata"]["collection_failure"] == {"code": COLLECTION_FAILURE, "artifact": "pr-error.txt"}
    assert "recommendations" not in candidate
    assert "follow_up" not in candidate

    _load_validator()._validate_result(tmp_path, candidate_path, tmp_path, "thread", tmp_path)
