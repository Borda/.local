"""Run one mutable benchmark cell with evidence-preserving cleanup.

The lifecycle is provider-neutral. Callers supply creation, action, and
restoration mechanics; this boundary guarantees that cleanup is attempted on
every ordinary exit and that a cleanup failure cannot be mistaken for a valid
measurement.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar


ResultT = TypeVar("ResultT")


class MutationCleanupError(RuntimeError):
    """Raised when a cell's frozen baseline cannot be restored."""


@dataclass
class MutationEvidence:
    """Lifecycle evidence retained even when action or cleanup fails."""

    worktree: Path | None = None
    action_error: str | None = None
    cleanup_error: str | None = None
    restored: bool = False


class IsolatedMutationCell:
    """Coordinate create/action/restore operations for one disposable cell."""

    def __init__(self, create: Callable[[], Path], restore: Callable[[Path], None]) -> None:
        """Store the concrete worktree lifecycle owned by a benchmark runner."""
        self._create = create
        self._restore = restore
        self.last_evidence = MutationEvidence()

    def run(self, action: Callable[[Path], ResultT]) -> ResultT:
        """Run one action and fail closed if its disposable baseline is not restored."""
        worktree = self._create()
        evidence = MutationEvidence(worktree=worktree)
        self.last_evidence = evidence
        try:
            return action(worktree)
        except Exception as exc:
            evidence.action_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                self._restore(worktree)
            except Exception as cleanup_error:
                evidence.cleanup_error = f"{type(cleanup_error).__name__}: {cleanup_error}"
                message = "mutable cell cleanup failed"
                if evidence.action_error:
                    message = f"{message} after {evidence.action_error}"
                raise MutationCleanupError(message) from cleanup_error
            evidence.restored = True
