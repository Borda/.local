"""Regression checks for session-local review-report remediation."""

from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CODE_REMEDIATE_SKILL = PLUGIN_ROOT / "skills" / "code-remediate" / "SKILL.md"


def test_session_review_shortcut_reuses_local_review_without_pr_refresh() -> None:
    """Keep session-local remediation independent from fresh PR collection.

    A user who has just completed code review may deliberately remediate its
    artifact before checking online comments again. The shortcut must therefore
    select that assessed artifact in report mode and state its fail-closed
    boundary.
    """
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    assert "$code-remediate review" in skill
    assert "`mode=report`" in skill
    assert "latest assessed `code-review` result created in the current session" in skill
    assert "Do not collect PR evidence or fetch online review comments." in skill
    assert "For `mode=report`, normalize only the review report" in skill
    assert "If no assessed current-session review result is available, fail" in skill
    assert "Reject `review_status=unavailable` and `review_status=closed`" in skill


def test_final_summary_includes_all_ingested_items_with_outcomes() -> None:
    """Keep the final chat recap usable without reopening its artifact.

    A user needs to see the disposition of every review item, including rows
    skipped by their selection rather than only the unresolved work.
    """
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    assert "Final Outcome Table" in skill
    assert "every ingested item" in skill
    assert "Implemented —" in skill
    assert "Rejected —" in skill
    assert "Skipped / unselected —" in skill
    assert "Already closed —" in skill
    assert "Unresolved —" in skill


def test_grouped_outcomes_preserve_report_and_online_source_bodies() -> None:
    """Keep grouped duplicate findings auditable without reopening raw PR artifacts."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    assert "Item | Severity | Finding | Sources | Outcome | Evidence / next action" in skill
    assert "category `report|online`" in skill
    assert "complete body without truncation" in skill
    assert "grouped rows must show all contributing sources" in skill
    assert "omitted_source_records_total" in skill


def test_work_buckets_bound_parallel_remediation_overhead() -> None:
    """Keep remediation fan-out disjoint, bounded, and user-approved."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    assert "Work Bucket Plan" in skill
    assert "at most five selected items" in skill
    assert "non-overlapping" in skill
    assert "five or fewer selected items" in skill
    assert "Do not spawn one specialist per finding" in skill
    assert "user confirms that exact digest before parallel dispatch" in skill
    assert "approved_plan_sha256" in skill


def test_scope_selection_question_has_one_rendering_owner() -> None:
    """Prevent the scope question appearing in prose and its interactive control."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    scope_contract = skill.split("### Terminal Scope Context Contract", maxsplit=1)[1].split(
        "Record in `<run-directory>/resolution-scope.md`", maxsplit=1
    )[0]

    assert scope_contract.count("Which findings should I remediate?") == 1
    assert "The scope-selection control is the sole owner of this question and its choices." in scope_contract
    assert "must not contain the selection question or its choices" in scope_contract
    assert "ask once in plain text instead of opening the control" in scope_contract


def test_parallel_approval_question_has_one_rendering_owner() -> None:
    """Prevent plan approval appearing in prose and its interactive control."""
    skill = CODE_REMEDIATE_SKILL.read_text(encoding="utf-8")
    workplan_contract = skill.split("### 06: Build And Approve The Work Bucket Plan", maxsplit=1)[1].split(
        "### 07: Apply Fixes In Selected Scope", maxsplit=1
    )[0]

    assert workplan_contract.count("Approve these parallel work buckets?") == 1
    assert "The approval control is the sole owner of this question and its choices." in workplan_contract
    assert "must not contain the approval question or its choices" in workplan_contract
    assert "ask once in plain text instead of opening the control" in workplan_contract
