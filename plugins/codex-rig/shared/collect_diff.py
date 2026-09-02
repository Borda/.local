#!/usr/bin/env python3
"""Collect a scope-aware local Git diff context pack without a shell wrapper.

## Purpose

Produce stable status, patch, file-list, and stat evidence for skill artifacts before review or implementation. Keeping
these views in named files lets later workflow steps cite the exact local tree state used for a review or implementation
decision.

## Scope

It invokes read-only local Git inspection for a working tree, path, or commit; it does not fetch, push, alter branches,
or choose review findings. The ``path`` scope compares ``HEAD`` for one path, while ``commit`` compares the requested
revision and deliberately leaves ``untracked.txt`` empty.

## Usage

Run ``python collect_diff.py --scope <working-tree|path|commit> --out <directory>`` with ``--target`` for ``path`` or
``commit`` scopes. The output directory is created when needed, and the command returns the underlying Git status for
command failures.

## Used by

Codex Rig workflow skills, implement/review artifact setup, and portable-helper acceptance tests use this collector.
Callers treat its files as local evidence and must not infer that an empty patch means the repository was clean unless
``status.txt`` agrees.

## Outputs

It writes ``status.txt``, ``diff.patch``, ``files.txt``, ``diffstat.txt``, ``numstat.txt``, and ``untracked.txt`` under
the requested output directory. Invalid scope or a missing required target additionally writes ``scope-error.txt`` with
a stable reason before returning exit code ``2``.

## Failure

Invalid scope/target or a failed local Git command exits non-zero and leaves the caller with no claim that diff evidence
is complete. Git output files may already exist when a later command fails, so consumers must gate on the exit code
rather than treating partial artifacts as a complete pack.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ARTIFACT_COMMANDS = (
    ("diff.patch", ("diff",)),
    ("files.txt", ("diff", "--name-only")),
    ("diffstat.txt", ("diff", "--stat")),
    ("numstat.txt", ("diff", "--numstat")),
)


def parse_args() -> argparse.Namespace:
    """Parse the stable collect-diff command-line contract."""
    parser = argparse.ArgumentParser(
        prog="collect_diff.py",
        description=(
            "Collect a Git diff context pack with status.txt, diff.patch, files.txt, "
            "diffstat.txt, numstat.txt, and untracked.txt."
        ),
        epilog="Exit 0 means collection succeeded; exit 2 means invalid input.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Required artifact directory.")
    parser.add_argument(
        "--scope",
        default="working-tree",
        help="Collection scope: working-tree, path, or commit.",
    )
    parser.add_argument("--target", default="", help="Path or revision required by path and commit scopes.")
    return parser.parse_args()


def run_git(arguments: tuple[str, ...], output: Path) -> int:
    """Run one Git argv vector and write its stdout bytes unchanged."""
    with output.open("wb") as stream:
        completed = subprocess.run(["git", *arguments], stdout=stream, check=False)
    return completed.returncode


def collect_diff(scope: str, target: str, output: Path) -> int:
    """Collect the requested diff scope into the canonical artifact set."""
    output.mkdir(parents=True, exist_ok=True)
    status = run_git(("status", "--short"), output / "status.txt")
    if status != 0:
        return status

    if scope in {"path", "commit"} and not target:
        (output / "scope-error.txt").write_text("missing-required:--target\n", encoding="utf-8")
        return 2
    if scope not in {"working-tree", "path", "commit"}:
        (output / "scope-error.txt").write_text(f"invalid-scope:{scope}\n", encoding="utf-8")
        return 2

    if scope == "working-tree":
        revision = ("HEAD",)
        path_suffix: tuple[str, ...] = ()
    elif scope == "path":
        revision = ("HEAD",)
        path_suffix = ("--", target)
    else:
        revision = (target,)
        path_suffix = ()

    for filename, prefix in ARTIFACT_COMMANDS:
        result = run_git((*prefix, *revision, *path_suffix), output / filename)
        if result != 0:
            return result

    untracked = output / "untracked.txt"
    if scope == "commit":
        untracked.write_bytes(b"")
        return 0
    suffix = ("--", target) if scope == "path" else ()
    return run_git(("ls-files", "--others", "--exclude-standard", *suffix), untracked)


def main() -> int:
    """Run the command-line diff collector."""
    arguments = parse_args()
    return collect_diff(arguments.scope, arguments.target, arguments.out)


if __name__ == "__main__":
    sys.exit(main())
