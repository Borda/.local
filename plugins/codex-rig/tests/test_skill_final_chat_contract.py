"""Regression checks for concise, outcome-coupled skill handoffs."""

from __future__ import annotations

from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PLUGIN_ROOT / "skills"
QUALITY_GATES = PLUGIN_ROOT / "shared" / "quality-gates.md"


def _output_contract(text: str) -> str:
    """Return the explicit Output Contract section, not an earlier prose mention."""
    return text.split("\n## Output Contract\n", maxsplit=1)[1]


@pytest.mark.parametrize(
    ("skill", "result_schema"),
    [
        ("agent-shims", "Action | Outcome | Verification | Remaining limit"),
        ("audit", "Item | Severity / impact | Decision | Evidence | Next action"),
        ("calibrate", "Check / metric | Result | Evidence | Next action"),
        ("change-analysis", "Finding | Impact | Decision | Evidence | Next action"),
        ("implement", "Surface | Outcome | Verification | Remaining limit"),
        ("investigate", "Hypothesis | Evidence | Disposition | Next action"),
        ("kaggle", "Artifact | Mode | Verification | Runtime limit"),
        ("manage", "Surface | Outcome | Verification | Remaining limit"),
        ("optimize", "Iteration | Baseline | After | Delta | Guard | Decision"),
        ("release", "Change | SemVer impact | Status / blocker | Evidence"),
        ("research", "Recommendation | Evidence | Decision | Caveat / next check"),
        ("sync", "Surface | Outcome | Verification | Remaining limit"),
    ],
)
def test_skill_final_chat_names_its_primary_result(skill: str, result_schema: str) -> None:
    """Prevent artifact-complete runs whose final chat omits the actual outcome."""
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    output_contract = _output_contract(text)
    assert "Final chat" in output_contract
    assert result_schema in output_contract


def test_shared_final_chat_frame_keeps_artifacts_supplemental() -> None:
    """Require the common outcome-first frame used by every native skill."""
    contract = QUALITY_GATES.read_text(encoding="utf-8")
    assert "## Final Chat Contract" in contract
    assert all(
        heading in contract
        for heading in (
            "Outcome",
            "Results",
            "Verification",
            "Remaining",
            "Recommendations / next steps",
            "Confidence",
            "Artifact",
        )
    )
    assert "never a substitute for the outcome" in contract


@pytest.mark.parametrize(
    "skill",
    [
        "agent-shims",
        "audit",
        "calibrate",
        "change-analysis",
        "code-remediate",
        "code-review",
        "implement",
        "investigate",
        "kaggle",
        "manage",
        "optimize",
        "release",
        "research",
        "sync",
    ],
)
def test_complex_final_chat_contracts_use_structure_not_dense_prose(skill: str) -> None:
    """Keep branch-heavy output instructions scannable without hard-wrapping prose."""
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    output_contract = _output_contract(text)
    assert "Next steps" in output_contract
    dense_lines = [line for line in output_contract.splitlines() if len(line) > 600]
    assert dense_lines == []
