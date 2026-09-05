"""Lifecycle tests for the disposable single-file patch executor."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import re
import sys

import pytest

SUITE_PATH = Path(__file__).resolve().parents[1] / "suites" / "tasks-fix-single.json"
FROZEN_REPO = Path("/private/tmp/codemap-provider-parity-pl-2.6.5")
BENCHMARKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARKS))


def _runner() -> object:
    """Return the private Fix stage without invoking its CLI.

    Example:
        >>> _runner().__name__
        '_bench_codex.stage_fix'
    """
    from _bench_codex import stage_fix

    return stage_fix


_RUNNER = _runner()


build_fix_single_contract = _RUNNER.build_fix_single_contract
execute_fix_single_patch = _RUNNER.execute_fix_single_patch


def _contract() -> object:
    """Return the first deterministic pilot contract.

    Example:
        >>> _contract().task_id
        'FS-01'
    """
    tasks = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    return build_fix_single_contract(next(task for task in tasks if task["id"] == "FS-01"))


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_candidate_patch_is_applied_scored_and_cleaned(tmp_path: Path) -> None:
    """A known behavioral patch proves baseline, path boundary, oracle, and rollback evidence."""
    contract = _contract()
    source_path = FROZEN_REPO / contract.expected_paths[0]
    before = source_path.read_text(encoding="utf-8")
    after = before.replace(
        "        self.patience = patience\n",
        "        if patience < 1:\n"
        '            raise MisconfigurationException(f"patience must be >= 1, got {patience}")\n'
        "        self.patience = patience\n",
        1,
    )
    assert after != before
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{contract.expected_paths[0]}",
            tofile=f"b/{contract.expected_paths[0]}",
        )
    )
    diff = f"diff --git a/{contract.expected_paths[0]} b/{contract.expected_paths[0]}\n{diff}"

    result = execute_fix_single_patch(FROZEN_REPO, contract, diff)

    assert result.baseline_failed is True
    assert result.patch_applied is True
    assert result.changed_paths == contract.expected_paths
    assert result.targeted_test_passed is True
    assert result.recount_recoverable is False
    assert result.recount_oracle_passed is None
    assert result.cleanup_verified is True
    assert result.error is None


def test_dirty_or_wrong_source_is_rejected_before_creating_a_cell(tmp_path: Path) -> None:
    """The executor never mutates a source repository that fails baseline admission."""
    contract = _contract()
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="Git checkout"):
        execute_fix_single_patch(source, contract, "diff --git a/a b/a\n")


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_rejected_patch_still_reports_verified_cleanup() -> None:
    """A failed apply cannot erase the worktree-cleanup evidence from the result."""
    result = execute_fix_single_patch(FROZEN_REPO, _contract(), "diff --git a/a b/a\n")

    assert result.baseline_failed is True
    assert result.patch_applied is False
    assert result.recount_recoverable is False
    assert result.recount_oracle_passed is None
    assert result.cleanup_verified is True


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_hunk_count_error_is_diagnostic_only() -> None:
    """A recount-valid candidate stays primary-ineligible when ordinary apply rejects it."""
    contract = _contract()
    source_path = FROZEN_REPO / contract.expected_paths[0]
    before = source_path.read_text(encoding="utf-8")
    after = before.replace(
        "        self.patience = patience\n",
        "        if patience < 1:\n"
        '            raise MisconfigurationException(f"patience must be >= 1, got {patience}")\n'
        "        self.patience = patience\n",
        1,
    )
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{contract.expected_paths[0]}",
            tofile=f"b/{contract.expected_paths[0]}",
        )
    )
    malformed = re.sub(
        r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@",
        lambda match: f"@@ -{match.group(1)},{int(match.group(2)) + 1} +{match.group(3)},{int(match.group(4)) + 1} @@",
        f"diff --git a/{contract.expected_paths[0]} b/{contract.expected_paths[0]}\n{diff}",
        count=1,
    )

    result = execute_fix_single_patch(FROZEN_REPO, contract, malformed)

    assert result.patch_applied is False
    assert result.targeted_test_passed is False
    assert result.recount_recoverable is True
    assert result.recount_oracle_passed is True
    assert result.cleanup_verified is True
