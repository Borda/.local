"""Acceptance checks for deterministic cross-skill final handoffs."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FINALIZER = PLUGIN_ROOT / "shared" / "final_handoff.py"
SHARED_VALIDATOR = PLUGIN_ROOT / "shared" / "validate-artifacts.py"
REMEDIATION_COLUMNS = [
    "Item",
    "Severity",
    "Finding",
    "Sources",
    "Outcome",
    "Evidence / next action",
]


def load_finalizer() -> Any:
    """Load the standalone finalizer without requiring a package import."""
    assert FINALIZER.is_file(), FINALIZER
    specification = importlib.util.spec_from_file_location("codex_rig_final_handoff", FINALIZER)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_shared_validator() -> Any:
    """Load the shared artifact validator without requiring a package import."""
    specification = importlib.util.spec_from_file_location("codex_rig_final_validator", SHARED_VALIDATOR)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def handoff_payload() -> dict[str, object]:
    """Return a valid remediation handoff covering two distinct sources."""
    return {
        "schema_version": 1,
        "skill": "code-remediate",
        "branch": "standard",
        "outcome": {"title": "Remediation Summary", "summary": "One item fixed; one remains external."},
        "tables": [
            {
                "heading": "Final Outcome Table",
                "columns": REMEDIATION_COLUMNS,
                "rows": [
                    {
                        "id": "CR-1",
                        "cells": [
                            "CR-1",
                            "high",
                            "Preserve a | boundary",
                            "report [CR-1]",
                            "Implemented — guarded\ninput",
                            "tests passed",
                        ],
                        "source_ids": ["report:CR-1"],
                    },
                    {
                        "id": "CR-2",
                        "cells": [
                            "CR-2",
                            "medium",
                            "Run external CI",
                            "report [CR-2]",
                            "Unresolved — external runner unavailable",
                            "CI owner must rerun",
                        ],
                        "source_ids": ["report:CR-2"],
                    },
                ],
            }
        ],
        "source_records": [
            {"id": "report:CR-1", "evidence": "action-items.md#CR-1"},
            {"id": "report:CR-2", "evidence": "action-items.md#CR-2"},
        ],
        "source_coverage": {
            "source_records_total": 2,
            "represented_source_records_total": 2,
            "omitted_source_records_total": 0,
        },
        "verification": [
            {"check": "lint", "status": "pass", "evidence": "ruff passed"},
            {"check": "format", "status": "pass", "evidence": "format passed"},
            {"check": "types", "status": "not-applicable", "evidence": "no typed target"},
            {"check": "tests", "status": "pass", "evidence": "2 passed"},
            {"check": "review", "status": "pass", "evidence": "diff check passed"},
        ],
        "remaining": [{"row_id": "CR-2", "item": "External CI", "owner": "ci", "next_action": "Rerun CI."}],
        "next_steps": ["CR-2"],
        "confidence": {
            "score": 0.95,
            "band": "fair",
            "limits": ["External CI was not run."],
            "gaps": [{"gap": "External CI was not run.", "status": "unresolved", "rationale": "CI is external."}],
        },
        "artifacts": [
            {"label": "Result", "path": ".reports/codex/code-remediate/run/result.json"},
            {"label": "Ledger", "path": ".reports/codex/code-remediate/run/action-items.md"},
        ],
        "caller_contract": None,
    }


def test_standard_handoff_renders_complete_deterministic_markdown() -> None:
    """Render every required section while escaping table delimiters and newlines."""
    finalizer = load_finalizer()

    rendered = finalizer.render_handoff(handoff_payload())

    assert rendered.startswith("**Outcome**\n\nRemediation Summary: One item fixed; one remains external.\n")
    assert "**Final Outcome Table**" in rendered
    assert "Preserve a \\| boundary" in rendered
    assert "Implemented — guarded<br>input" in rendered
    assert "**Remaining**\n\n- CR-2 — External CI — owner: ci — next: Rerun CI." in rendered
    assert not any(line.startswith("#") for line in rendered.splitlines())
    assert "\x1b[" not in rendered
    assert rendered.endswith("Ledger: .reports/codex/code-remediate/run/action-items.md\n")
    assert finalizer.render_handoff(handoff_payload()) == rendered


def test_handoff_renders_symbol_details_immediately_below_table() -> None:
    """Keep long table text readable through validated under-table references."""
    finalizer = load_finalizer()
    payload = handoff_payload()
    tables = payload["tables"]
    assert isinstance(tables, list)
    table = tables[0]
    table["rows"][0]["cells"][4] = "implemented — [O1]"
    table["details"] = [{"id": "O1", "text": "Guarded multiline input without changing valid requests."}]

    rendered = finalizer.render_handoff(payload)

    table_end = "| CR-2 | medium | Run external CI | report [CR-2] | Unresolved — external runner unavailable | CI owner must rerun |"
    assert f"{table_end}\n\n[O1] Guarded multiline input without changing valid requests." in rendered


def test_handoff_rejects_unreferenced_table_detail() -> None:
    """Reject detail text that has no compact symbol in its owning table."""
    finalizer = load_finalizer()
    payload = handoff_payload()
    tables = payload["tables"]
    assert isinstance(tables, list)
    tables[0]["details"] = [{"id": "O1", "text": "No table cell refers to this detail."}]

    with pytest.raises(finalizer.HandoffError, match="table-detail-unreferenced:O1"):
        finalizer.validate_handoff(payload)


def test_handoff_rejects_an_omitted_source_even_when_counts_are_rewritten() -> None:
    """Reject a table that hides one declared source behind self-consistent aggregate counts."""
    finalizer = load_finalizer()
    payload = handoff_payload()
    tables = payload["tables"]
    assert isinstance(tables, list)
    second_row = tables[0]["rows"].pop()
    assert second_row["id"] == "CR-2"
    coverage = payload["source_coverage"]
    assert isinstance(coverage, dict)
    coverage["represented_source_records_total"] = 1
    coverage["omitted_source_records_total"] = 1

    with pytest.raises(finalizer.HandoffError, match="omitted-source-records"):
        finalizer.validate_handoff(payload)


def test_terminal_code_review_close_forbids_tables() -> None:
    """Preserve the review close branch's plain-prose no-table contract."""
    finalizer = load_finalizer()
    payload = handoff_payload()
    payload["skill"] = "code-review"
    payload["branch"] = "closed"

    with pytest.raises(finalizer.HandoffError, match="terminal-branch-forbids-tables"):
        finalizer.validate_handoff(payload)


def test_caller_contract_renders_exact_requested_bytes() -> None:
    """Keep an explicit strict output contract free of added workflow prose."""
    finalizer = load_finalizer()
    payload = handoff_payload()
    payload["branch"] = "caller-contract"
    payload["tables"] = []
    payload["source_records"] = []
    payload["source_coverage"] = {
        "source_records_total": 0,
        "represented_source_records_total": 0,
        "omitted_source_records_total": 0,
    }
    payload["caller_contract"] = {
        "format": "application/json",
        "evidence": "User explicitly requested JSON only.",
        "output": '{"status":"ok"}\n',
    }

    assert finalizer.render_handoff(payload) == '{"status":"ok"}\n'


def test_cli_render_and_check_bind_exact_file_digests(tmp_path: Path) -> None:
    """Fail closed when a validated final render is changed after generation."""
    handoff = tmp_path / "final-handoff.json"
    final = tmp_path / "final.md"
    validation = tmp_path / "final-handoff.validation.json"
    handoff.write_text(json.dumps(handoff_payload()), encoding="utf-8")

    rendered = subprocess.run(
        [
            sys.executable,
            str(FINALIZER),
            "render",
            "--handoff",
            str(handoff),
            "--out-final",
            str(final),
            "--out-validation",
            str(validation),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    checked = subprocess.run(
        [
            sys.executable,
            str(FINALIZER),
            "check",
            "--handoff",
            str(handoff),
            "--final",
            str(final),
            "--validation",
            str(validation),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr

    final.write_text(final.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    drifted = subprocess.run(
        [
            sys.executable,
            str(FINALIZER),
            "check",
            "--handoff",
            str(handoff),
            "--final",
            str(final),
            "--validation",
            str(validation),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert drifted.returncode != 0
    assert "rendered-final-mismatch" in drifted.stderr


def _write_schema_v2_change_analysis(tmp_path: Path) -> Path:
    """Write one minimal schema-v2 result with a real rendered handoff."""
    checks = []
    verification = []
    for gate_id in ("lint", "format", "types", "tests", "review"):
        for suffix in ("command.txt", "stdout.txt", "stderr.txt"):
            (tmp_path / f"{gate_id}.{suffix}").write_text("", encoding="utf-8")
        checks.append(
            {
                "id": gate_id,
                "status": "pass",
                "exit_code": 0,
                "duration_seconds": 0.0,
                "command_path": f"{gate_id}.command.txt",
                "stdout": f"{gate_id}.stdout.txt",
                "stderr": f"{gate_id}.stderr.txt",
            }
        )
        verification.append({"check": gate_id, "status": "pass", "evidence": f"{gate_id}.stdout.txt"})
    (tmp_path / "gates.json").write_text(
        json.dumps({"status": "pass", "checks_failed": [], "checks": checks}), encoding="utf-8"
    )
    result_path = tmp_path / "result.candidate.json"
    gap = "External production behavior was not exercised."
    handoff = {
        "schema_version": 1,
        "skill": "change-analysis",
        "branch": "standard",
        "outcome": {"title": "Analysis", "summary": "The requested contract is defined."},
        "tables": [
            {
                "heading": "Decision Table",
                "columns": ["Finding", "Impact", "Decision", "Evidence", "Next action"],
                "rows": [
                    {
                        "id": "CA-1",
                        "cells": [
                            "Final output was prose-only",
                            "Rows could disappear",
                            "Add checkpoint",
                            "analysis.md",
                            "Implement",
                        ],
                        "source_ids": ["analysis:CA-1"],
                    }
                ],
            }
        ],
        "source_records": [{"id": "analysis:CA-1", "evidence": "analysis.md"}],
        "source_coverage": {
            "source_records_total": 1,
            "represented_source_records_total": 1,
            "omitted_source_records_total": 0,
        },
        "verification": verification,
        "remaining": [],
        "next_steps": [],
        "confidence": {
            "score": 0.95,
            "band": "fair",
            "limits": [gap],
            "gaps": [{"gap": gap, "status": "unresolved", "rationale": "No production host transcript exists."}],
        },
        "artifacts": [{"label": "Result", "path": str(result_path)}],
        "caller_contract": None,
    }
    handoff_path = tmp_path / "final-handoff.json"
    final_path = tmp_path / "final.md"
    validation_path = tmp_path / "final-handoff.validation.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    finalizer = load_finalizer()
    validation = finalizer.render_files(handoff_path, final_path, validation_path)
    result = {
        "schema_version": 2,
        "status": "pass",
        "checks_run": ["lint", "format", "types", "tests", "review"],
        "checks_failed": [],
        "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "confidence": 0.95,
        "artifact_path": str(result_path),
        "metadata": {
            "confidence_gaps": [gap],
            "confidence_gap_closures": [
                {"gap": gap, "status": "unresolved", "rationale": "No production host transcript exists."}
            ],
            "confidence_recovery": {
                "initial_confidence": 0.9,
                "final_confidence": 0.95,
                "status": "fair",
                "evidence": ["Renderer and validator passed."],
                "recovery_actions": ["Rendered and digest-bound final output."],
                "remaining_limits": [gap],
            },
            "final_handoff": {
                "schema_version": 1,
                "handoff_path": str(handoff_path),
                "handoff_sha256": validation["handoff_sha256"],
                "rendered_path": str(final_path),
                "rendered_sha256": validation["rendered_sha256"],
                "validation_path": str(validation_path),
                "branch": "standard",
            },
        },
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path


def test_schema_v2_result_requires_digest_bound_final_output(tmp_path: Path) -> None:
    """Accept an intact final handoff and reject post-render presentation drift."""
    result_path = _write_schema_v2_change_analysis(tmp_path)
    validator = load_shared_validator()

    validator.validate("change-analysis", tmp_path, result_path)

    (tmp_path / "final.md").write_text("truncated\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="final-handoff-validation-failed:.*rendered-final-mismatch"):
        validator.validate("change-analysis", tmp_path, result_path)


def test_schema_v2_accepts_documented_workspace_relative_handoff_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve template-style run paths relative to the invoking workspace."""
    result_path = _write_schema_v2_change_analysis(tmp_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    binding = result["metadata"]["final_handoff"]
    run_path = Path(tmp_path.name)
    binding["handoff_path"] = str(run_path / "final-handoff.json")
    binding["rendered_path"] = str(run_path / "final.md")
    binding["validation_path"] = str(run_path / "final-handoff.validation.json")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)

    load_shared_validator().validate("change-analysis", tmp_path, result_path)


def test_historical_schema_v1_result_remains_readable_without_final_handoff(tmp_path: Path) -> None:
    """Keep pre-migration artifacts valid while schema-v2 creation fails closed."""
    result_path = _write_schema_v2_change_analysis(tmp_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.pop("schema_version")
    result["metadata"].pop("final_handoff")
    result_path.write_text(json.dumps(result), encoding="utf-8")

    load_shared_validator().validate("change-analysis", tmp_path, result_path)
