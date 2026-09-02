"""Regression checks for assessed code-review snapshot reconciliation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SUGGESTIONS = {
    "accept-as-is": "approve",
    "minor-changes": "minor changes",
    "needs-more-work": "needs work",
    "reject": "reject",
    "not-aligned": "not aligned",
}


def _load_validator() -> ModuleType:
    """Load the hyphenated shared artifact validator for focused checks."""
    path = PLUGIN_ROOT / "shared" / "validate-artifacts.py"
    specification = importlib.util.spec_from_file_location("codex_rig_review_handoff_validator", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _result(recommendation: str) -> dict[str, object]:
    """Return one assessed PR result with a structured decision."""
    return {
        "metadata": {
            "scope": "pr",
            "review_decision": {
                "recommendation": recommendation,
                "summary": "The review decision is evidence-backed.",
                "rationale": "The inspected diff and gates determine this outcome.",
            },
        },
        "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    }


def _handoff(suggestion: str) -> dict[str, object]:
    """Return one compact assessed PR snapshot with the supplied suggestion."""
    rows = [
        ("PR", "[#1399 — Pack targets](https://github.com/example/project/pull/1399)"),
        ("Author", "@contributor"),
        ("CI", "passing"),
        ("Type", "perf"),
        ("Suggestion", suggestion),
    ]
    return {
        "branch": "assessed",
        "tables": [
            {
                "heading": "PR Snapshot",
                "columns": ["Field", "Value"],
                "rows": [
                    {"id": f"PR-{index}", "cells": [field, value], "source_ids": [f"source-{index}"]}
                    for index, (field, value) in enumerate(rows, start=1)
                ],
            }
        ],
    }


@pytest.mark.parametrize("malformed_fields", [("PR", "Author", "CI", "Type"), ("PR", "Author", "CI", "Type", "State")])
def test_review_snapshot_rejects_missing_or_replaced_suggestion(malformed_fields: tuple[str, ...]) -> None:
    """Prevent a complete-looking PR summary from omitting its review outcome."""
    handoff = _handoff("needs work")
    snapshot = handoff["tables"][0]
    snapshot["rows"] = [
        {"id": f"PR-{index}", "cells": [field, "value"], "source_ids": [f"source-{index}"]}
        for index, field in enumerate(malformed_fields, start=1)
    ]

    with pytest.raises(SystemExit, match="code-review-final-handoff-pr-snapshot-fields-mismatch"):
        VALIDATOR._validate_code_review_final_handoff(_result("needs-more-work"), handoff)


@pytest.mark.parametrize(("recommendation", "suggestion"), SUGGESTIONS.items())
def test_review_snapshot_suggestion_is_bound_to_structured_decision(recommendation: str, suggestion: str) -> None:
    """Keep every user-facing suggestion synchronized with the validated decision."""
    handoff = _handoff(suggestion)

    VALIDATOR._validate_code_review_final_handoff(_result(recommendation), handoff)

    handoff["tables"][0]["rows"][-1]["cells"][1] = "approve" if suggestion != "approve" else "needs work"
    with pytest.raises(SystemExit, match="code-review-final-handoff-pr-snapshot-suggestion-mismatch"):
        VALIDATOR._validate_code_review_final_handoff(_result(recommendation), handoff)
