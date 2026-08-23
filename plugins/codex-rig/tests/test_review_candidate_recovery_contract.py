"""Regression checks for review-candidate validation and remediation recovery."""

from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CODE_REVIEW_SKILL = PLUGIN_ROOT / "skills" / "code-review" / "SKILL.md"
CODE_REMEDIATE_SKILL = PLUGIN_ROOT / "skills" / "code-remediate" / "SKILL.md"


def test_code_review_preflights_specialist_manifest_before_candidate() -> None:
    """Prevent malformed spawned-attempt bookkeeping from leaving a candidate."""
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8").lower()

    assert "--manifest-only" in skill
    assert "before writing `result.candidate.json`" in skill
    assert "one or two sequential attempts" in skill
    assert "never invent missing attempt provenance" in skill


def test_remediation_revalidates_same_session_candidate_before_promotion() -> None:
    """Recover a valid candidate without bypassing either review validator."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8").lower()

    assert "matching-review-candidate-unpromoted" in skill
    assert "same parent thread" in skill
    assert "review-specific validator, then the shared validator" in skill
    assert "promote it to `result.json` only after both validators pass" in skill
    assert "never consume `result.candidate.json` directly" in skill


def test_remediation_preserves_exact_candidate_validation_failure() -> None:
    """Replace generic rerun advice with the actionable upstream validator code."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8").lower()

    assert "review-candidate-validation.txt" in skill
    assert "manifest-invalid-attempt-count:<role>" in skill
    assert "return to the code-review manifest preflight checkpoint" in skill
    assert "one evidence-preserving repair" in skill
    assert "never invent missing attempt provenance" in skill
    assert "do not fall back to an older assessed report" in skill
