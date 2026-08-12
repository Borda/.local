"""Regression checks for session-local review-report remediation."""

from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CODE_REMEDIATE_SKILL = PLUGIN_ROOT / "skills" / "code-remediate" / "SKILL.md"
README = PLUGIN_ROOT / "README.md"


def test_session_review_shortcut_reuses_local_review_without_pr_refresh() -> None:
    """Keep session-local remediation independent from fresh PR collection.

    A user who has just completed code review may deliberately remediate its
    artifact before checking online comments again. The shortcut must therefore
    select that assessed artifact in report mode and state its fail-closed
    boundary.
    """
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "$code-remediate review" in skill
    assert "`mode=report`" in skill
    assert "latest assessed `code-review` result created in the current session" in skill
    assert "Do not collect PR evidence or fetch online review comments." in skill
    assert "For `mode=report`, normalize only the review report" in skill
    assert "If no assessed current-session review result is available, fail" in skill
    assert "Reject `review_status=unavailable` and `review_status=closed`" in skill
    assert "$codex-rig:code-remediate review" in readme
