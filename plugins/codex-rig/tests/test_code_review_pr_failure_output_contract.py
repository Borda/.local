"""Regression checks for terminal PR-evidence collection failures."""

from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CODE_REVIEW_SKILL = PLUGIN_ROOT / "skills" / "code-review" / "SKILL.md"


def _terminal_failure_gate() -> str:
    """Return the PR collection-failure contract without later review guidance."""
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8")
    start = skill.index("**Terminal review-unavailable output gate:**")
    end = skill.index("\n\nFor retryable `github-network`", start)
    return skill[start:end]


def test_terminal_pr_collection_failure_is_review_unavailable_not_merge_decision() -> None:
    """Keep a failed evidence collection separate from a PR review outcome.

    A T0 failure means no source review occurred. The user therefore needs an
    operational recovery table, not a ``needs-more-work`` recommendation or a
    merge-block findings table.
    """
    skill = CODE_REVIEW_SKILL.read_text(encoding="utf-8")
    terminal_gate = _terminal_failure_gate()
    normalized = terminal_gate.lower()

    assert "t0 pr collection failure" in normalized
    assert "`pr review availability: unavailable`" in normalized
    assert "`merge decision: not made`" in normalized
    assert "## PR Evidence Collection Recovery" in terminal_gate
    assert "| Operational area | Recovery action | Evidence | Status |" in terminal_gate
    assert "one `PR evidence collection` row" in terminal_gate
    assert "Do not emit `needs-more-work`" in terminal_gate
    assert "`Review Findings and Merge Blocks` is never used" in terminal_gate
    assert "`review_status=unavailable`" in terminal_gate
    assert "`collection_failure=" in terminal_gate
    assert "For retryable `github-network`, `github-rate-limit`, or `command-timeout`" in skill
    assert "suggest filing a Codex Rig bug" in skill
