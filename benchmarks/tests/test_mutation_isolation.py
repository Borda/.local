"""Tests for provider-neutral mutable-cell lifecycle behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from _bench_common.mutation_isolation import IsolatedMutationCell, MutationCleanupError
except ModuleNotFoundError:
    from benchmarks._bench_common.mutation_isolation import IsolatedMutationCell, MutationCleanupError


@pytest.mark.parametrize("failure", [None, RuntimeError("model failure"), TimeoutError("cell timeout")])
def test_isolated_cell_restores_baseline_after_success_error_and_timeout(
    tmp_path: Path, failure: Exception | None
) -> None:
    """Success, action errors, and timeouts all restore the disposable baseline."""
    created: list[Path] = []
    restored: list[Path] = []

    def _create() -> Path:
        """Create and record a uniquely numbered disposable cell directory."""
        worktree = tmp_path / f"cell-{len(created)}"
        worktree.mkdir()
        created.append(worktree)
        return worktree

    def _restore(worktree: Path) -> None:
        """Record the worktree handed to the restoration callback."""
        restored.append(worktree)

    cell = IsolatedMutationCell(_create, _restore)
    if failure is None:
        assert cell.run(lambda worktree: worktree.name) == "cell-0"
    else:
        with pytest.raises(type(failure), match=str(failure)):
            cell.run(lambda _worktree: (_ for _ in ()).throw(failure))

    assert restored == created
    assert cell.last_evidence.restored is True


def test_retry_and_test_or_scorer_failure_each_receive_a_fresh_baseline(tmp_path: Path) -> None:
    """Retries and downstream failures cannot reuse a mutated previous cell."""
    created: list[Path] = []
    restored: list[Path] = []

    def _create() -> Path:
        """Create and record a uniquely numbered disposable cell directory."""
        worktree = tmp_path / f"cell-{len(created)}"
        worktree.mkdir()
        created.append(worktree)
        return worktree

    cell = IsolatedMutationCell(_create, restored.append)
    for error in (AssertionError("target test failed"), ValueError("scorer failed")):
        with pytest.raises(type(error), match=str(error)):
            cell.run(lambda _worktree, failure=error: (_ for _ in ()).throw(failure))

    assert created == restored
    assert created[0] != created[1]


def test_cleanup_failure_preserves_action_failure_and_fails_closed(tmp_path: Path) -> None:
    """Cleanup failure must override a tempting action result with evidence."""
    worktree = tmp_path / "cell"
    worktree.mkdir()
    cell = IsolatedMutationCell(lambda: worktree, lambda _worktree: (_ for _ in ()).throw(OSError("locked")))

    with pytest.raises(MutationCleanupError, match="model failure"):
        cell.run(lambda _worktree: (_ for _ in ()).throw(RuntimeError("model failure")))

    assert cell.last_evidence.action_error == "RuntimeError: model failure"
    assert cell.last_evidence.cleanup_error == "OSError: locked"
    assert cell.last_evidence.restored is False
