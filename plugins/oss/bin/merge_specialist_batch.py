#!/usr/bin/env python
"""merge_specialist_batch.py — cherry-pick per-item commits from parallel specialist
worktrees onto the current branch, in original item-priority order.

oss:resolve Step 8 Phase 2 dispatches one implementation agent per specialist
(sw-engineer/qa-specialist/doc-scribe/linting-expert), each working in its own
``git worktree`` so concurrent edits never race on a shared working tree. Each
specialist commits its assigned action items individually inside its own
worktree branch. This script brings those commits back onto the real PR branch
one at a time, in the caller-supplied priority order (interleaved across
specialists, not grouped by specialist), so history order matches the
review's severity ranking regardless of which specialist finished first.

For ``--commit-mode`` other than ``each``, each cherry-picked commit is
immediately soft-reset (``git reset --soft HEAD~1``) right after it lands —
the diff stays staged (index) but the commit object is undone. This matches
the "stage first, commit-mode-specific commit later" contract that
action-item-dispatch.md's post-loop COMMIT_MODE=grouped/all/stage sections
already assume — they operate on staged-but-uncommitted changes.

Usage:
    merge_specialist_batch.py --plan <plan.json> --commit-mode <each|grouped|all|stage>
        [--centrality-file <map.json>]

Plan file: JSON array of ``{"item_id": str, "sha": str, "group"?: str,
"module"?: str}`` objects, in the exact order to apply.

With ``--centrality-file`` (a ``{module: score}`` JSON map) the plan is first
reordered so the most foundational worktree groups land first — see
``order_plan``. Groups touch disjoint files (oss:resolve's file-ownership
tiebreak guarantees it), so reordering whole groups never adds a textual
conflict; commit order *within* a group is always preserved.

Exit codes:
    0 — all entries applied cleanly
    1 — cherry-pick conflict on an entry; partial progress reported as JSON
        on stdout, repo left in the conflicted cherry-pick state for the
        caller to resolve (mirrors Step 5 merge-conflict handling), then
        re-invoke with the remaining (unapplied) entries once resolved
    2 — bad/missing required argument (argparse default)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True)
class PlanEntry:
    """One cherry-pick unit — a single action item's commit from a specialist worktree.

    Attributes:
        item_id: Review action-item id (matches ``SELECTED_ITEMS`` entries).
        sha: Commit SHA to cherry-pick, reachable via the specialist worktree's branch.
        group: Worktree-group tag this commit came from (one linear commit chain per
            group). Empty when the caller supplies no grouping — the whole plan is then
            treated as a single group and left in the order given.
        module: Dotted module path this item edits, used to look up a centrality score
            for group ordering. Empty when unknown (non-Python item, or no index).
    """

    item_id: str
    sha: str
    group: str = ""
    module: str = ""


def _resolve(cmd: str) -> str:
    """Resolve a CLI tool to its absolute path.

    Args:
        cmd: Bare executable name (e.g. ``"git"``).

    Returns:
        Absolute path to the executable.

    Raises:
        FileNotFoundError: If ``cmd`` is not present on ``PATH``.

    Examples:
        >>> import shutil
        >>> _resolve("git") == shutil.which("git")
        True
    """
    p = which(cmd)
    if p is None:
        raise FileNotFoundError(f"executable not found on PATH: {cmd}")
    return p


def parse_plan(raw: str) -> list[PlanEntry]:
    """Parse a plan JSON string into ordered ``PlanEntry`` objects.

    Args:
        raw: JSON array text, e.g. ``'[{"item_id":"6","sha":"abc123"}]'``.

    Returns:
        Ordered list of ``PlanEntry``, preserving input order.

    Examples:
        >>> parse_plan('[{"item_id": "3", "sha": "abc"}]')
        [PlanEntry(item_id='3', sha='abc', group='', module='')]
        >>> parse_plan('[{"item_id": "3", "sha": "abc", "group": "sw", "module": "pkg.a"}]')
        [PlanEntry(item_id='3', sha='abc', group='sw', module='pkg.a')]
    """
    return [
        PlanEntry(
            item_id=str(e["item_id"]),
            sha=str(e["sha"]),
            group=str(e.get("group", "")),
            module=str(e.get("module", "")),
        )
        for e in json.loads(raw)
    ]


def order_plan(entries: list[PlanEntry], centrality: dict[str, float]) -> list[PlanEntry]:
    """Reorder the cherry-pick plan so the most foundational worktree chains land first.

    Ordering is done at **group** granularity, never at the individual-commit level: a
    specialist worktree is a linear commit chain whose commits may build on one another,
    so reordering commits *within* a group risks a cherry-pick conflict or a broken
    intermediate state. Whole groups are safe to reorder relative to each other because
    oss:resolve's file-ownership tiebreak guarantees any single file's items all live in
    one group — distinct groups therefore touch disjoint files and can never textually
    conflict across the reordering.

    Each group's sort weight is the maximum centrality of any module it edits (its most
    depended-upon change). Groups are sorted by that weight descending; ties and unscored
    groups keep first-seen order (stable). Within every group the original commit order is
    preserved untouched.

    Args:
        entries: The plan in caller-supplied (priority) order.
        centrality: Map of dotted module path to centrality score. Missing modules score
            ``0.0``. An empty map leaves the plan order unchanged (every group scores 0).

    Returns:
        The reordered plan. Same ``PlanEntry`` objects, regrouped; never mutated.

    Examples:
        >>> plan = [
        ...     PlanEntry("1", "aa", group="docs", module="pkg.readme"),
        ...     PlanEntry("2", "bb", group="sw", module="pkg.core"),
        ...     PlanEntry("3", "cc", group="sw", module="pkg.util"),
        ... ]
        >>> [e.item_id for e in order_plan(plan, {"pkg.core": 9.0, "pkg.readme": 1.0})]
        ['2', '3', '1']
        >>> [e.item_id for e in order_plan(plan, {})]
        ['1', '2', '3']
    """
    groups: dict[str, list[PlanEntry]] = {}
    for e in entries:
        groups.setdefault(e.group, []).append(e)
    ordered_groups = sorted(
        groups,
        key=lambda g: -max((centrality.get(e.module, 0.0) for e in groups[g]), default=0.0),
    )
    return [e for g in ordered_groups for e in groups[g]]


def _conflicted_files(git: str) -> list[str]:
    """List files left with unmerged conflict markers by the current git operation.

    Args:
        git: Absolute path to the ``git`` executable.

    Returns:
        Conflicted file paths (``git diff --diff-filter=U``), empty if none.
    """
    proc = subprocess.run(  # noqa: S603
        [git, "diff", "--name-only", "--diff-filter=U"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    return [f for f in proc.stdout.splitlines() if f.strip()]


def run_plan(entries: list[PlanEntry], commit_mode: str) -> dict[str, object]:
    """Cherry-pick each plan entry in order, soft-resetting when not in ``each`` mode.

    Stops at the first cherry-pick conflict and leaves the repository in that
    conflicted state (matching how Step 5's merge-conflict handling expects to
    find in-progress state) so the caller can resolve it and re-invoke with
    the remaining entries.

    Args:
        entries: Ordered cherry-pick plan.
        commit_mode: One of ``each``, ``grouped``, ``all``, ``stage``. Any
            value other than ``each`` triggers an immediate soft-reset after
            each successful cherry-pick.

    Returns:
        ``{"applied": [item_id, ...], "conflict": {"item_id", "sha", "files"} | None,
        "remaining": [item_id, ...]}``.

    Examples:
        No doctest — requires live git subprocess; covered by pytest with monkeypatch.
    """
    git = _resolve("git")
    applied: list[str] = []
    for i, entry in enumerate(entries):
        pick = subprocess.run([git, "cherry-pick", entry.sha], check=False, timeout=30)  # noqa: S603
        if pick.returncode != 0:
            return {
                "applied": applied,
                "conflict": {
                    "item_id": entry.item_id,
                    "sha": entry.sha,
                    "files": _conflicted_files(git),
                },
                "remaining": [e.item_id for e in entries[i + 1 :]],
            }
        if commit_mode != "each":
            subprocess.run([git, "reset", "--soft", "HEAD~1"], check=False, timeout=3)  # noqa: S603
        applied.append(entry.item_id)
    return {"applied": applied, "conflict": None, "remaining": []}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 — all entries applied; 1 — conflict, partial JSON on stdout.

    Examples:
        No doctest — requires live git; covered by pytest with monkeypatch.
    """
    parser = argparse.ArgumentParser(
        prog="merge_specialist_batch.py",
        description="Cherry-pick per-item commits from parallel specialist worktrees, in priority order.",
    )
    parser.add_argument("--plan", required=True, help="Path to plan JSON file: [{item_id, sha, group?, module?}, ...]")
    parser.add_argument("--commit-mode", required=True, choices=["each", "grouped", "all", "stage"])
    parser.add_argument(
        "--centrality-file",
        default=None,
        help="Optional JSON map {module: score}; reorders whole worktree groups most-central-first.",
    )
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    with open(args.plan, encoding="utf-8") as f:
        entries = parse_plan(f.read())

    if args.centrality_file:
        with open(args.centrality_file, encoding="utf-8") as f:
            centrality = {str(k): float(v) for k, v in json.load(f).items()}
        entries = order_plan(entries, centrality)

    result = run_plan(entries, args.commit_mode)
    print(json.dumps(result))
    return 0 if result["conflict"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
