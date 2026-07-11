#!/usr/bin/env python
"""stage_item_changes.py — pop stash for a review item then stage changed files.

Pops any pre-item stash for ``item_id``, then stages all changed tracked and
source-extension untracked files. Extracted from oss:resolve action-item-dispatch
Phase 2 staging block (AI7).

Usage:
    stage_item_changes.py <item_id>

Exit codes:
    0 — staged successfully
    1 — missing item_id, invalid item_id format, or stash-pop conflict
    2 — bad/missing required argument (argparse default)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

_ITEM_ID_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]+$")

_SOURCE_EXTS: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
        ".ini",
        ".json",
        ".txt",
        ".sh",
        ".js",
        ".ts",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
    }
)


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


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``stage_item_changes.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 on success; 1 on missing item_id or stash-pop conflict.

    Examples:
        No doctest — requires subprocess; covered by pytest with monkeypatch.
    """
    parser = argparse.ArgumentParser(
        prog="stage_item_changes.py",
        description="Pop the pre-item stash for an item then stage changed files.",
    )
    # nargs="?" preserves the legacy exit-1 (not argparse's exit-2) on a missing
    # item_id: argparse accepts zero positionals, and the manual check below emits
    # the original "item_id required" message and returns 1.
    parser.add_argument("item_id", nargs="?", default="", help="Review item identifier ([A-Za-z0-9_-]).")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    if not args.item_id:
        print("stage_item_changes: item_id required", file=sys.stderr)
        return 1
    item_id = args.item_id
    # Reject control characters and any token outside the [A-Za-z0-9_-] alphabet —
    # the value is interpolated into the stash label below and a crafted
    # item_id containing newlines or shell metacharacters could otherwise
    # cause the stash-match logic to point at the wrong entry (F-130 follow-up).
    if not _ITEM_ID_RE.match(item_id):
        print(f"stage_item_changes: invalid item_id format: {item_id!r}", file=sys.stderr)
        return 1
    git = _resolve("git")
    stash_label = f"resolve-pre-item-{item_id}"
    stash_proc = subprocess.run(  # noqa: S603
        [git, "stash", "list", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    # Match stash entries by exact (rstripped) line equality on the label suffix.
    # The previous substring match (``stash_label in stash_proc.stdout``) let a
    # crafted item_id smuggle a newline so an unrelated stash entry was treated
    # as ours; require an exact line-level match instead (F-130).
    stash_lines = [line.rstrip() for line in stash_proc.stdout.splitlines()]
    matched_line = next(
        (line for line in stash_lines if line.endswith(stash_label) or stash_label in line.split(": ")),
        None,
    )
    if matched_line is not None:
        # Pop the matched entry by its ``stash@{N}`` ref, not a bare ``stash pop``
        # (which always pops ``stash@{0}``). If another stash was pushed after ours
        # — nested resolve or a user stash — the newest is no longer ours, so a bare
        # pop would apply the wrong entry and stage the wrong files.
        stash_ref = matched_line.split(": ", 1)[0]
        pop = subprocess.run([git, "stash", "pop", stash_ref], check=False, timeout=3)  # noqa: S603
        if pop.returncode != 0:
            print(
                f"⚠ stash pop conflict — resolve conflicts in {stash_ref} before item #{item_id}",
                file=sys.stderr,
            )
            return 1
    changed_proc = subprocess.run(  # noqa: S603
        [git, "diff", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    changed = [f for f in changed_proc.stdout.splitlines() if f.strip()]
    if changed:
        subprocess.run([git, "add", "--"] + changed, check=False, timeout=3)  # noqa: S603
    untracked_proc = subprocess.run(  # noqa: S603
        [git, "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    untracked = [f for f in untracked_proc.stdout.splitlines() if f.strip() and Path(f).suffix in _SOURCE_EXTS]
    if untracked:
        subprocess.run([git, "add", "--"] + untracked, check=False, timeout=3)  # noqa: S603
    return 0


if __name__ == "__main__":
    sys.exit(main())
