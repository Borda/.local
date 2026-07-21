#!/usr/bin/env python3
"""compute_commit_sentinel.py — print the commit-authorization sentinel path for the current repo/branch.

Usage:
    SENTINEL=$(python "${CLAUDE_PLUGIN_ROOT}/bin/compute_commit_sentinel.py")
    touch "$SENTINEL"  # timeout: 3000
    trap 'rm -f "$SENTINEL"' EXIT INT TERM

Sentinel path format: /tmp/claude-commit-auth-<repo-slug>-<branch-slug>

Slug algorithm: lowercase, runs of non-alphanumeric chars → single '-',
trailing '-' stripped — mirrors the ``tr``/``sed`` pipeline documented in
``git-commit.md``.  Extracted from the oss:resolve action-item-dispatch
setup block to enable reuse across resolve steps.

Note: sentinel path is predictable by design for cross-process coordination
with the pre-commit hook (Gate 1, see git-commit.md). On multi-user hosts,
use $XDG_RUNTIME_DIR instead of /tmp for improved isolation (F-07 in
security audit 2026-05-19). TOCTOU risk on single-user workstations
accepted as low-severity.

Exit codes:
    0  on success
    1  if not inside a git repository (git commands fail)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile


def to_slug(value: str) -> str:
    """Convert a string to a filesystem-safe slug.

    Lowercases, collapses runs of non-alphanumeric characters to a single
    ``-``, and strips any trailing ``-``.  Mirrors the shell pipeline::

        tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//'

    Args:
        value: Input string (repo name or branch name).

    Returns:
        Slug string containing only ``[a-z0-9-]`` with no trailing ``-``.

    Examples:
        >>> to_slug("MyRepo.local")
        'myrepo-local'
        >>> to_slug("feature/my-branch")
        'feature-my-branch'
        >>> to_slug("UPPER-CASE--extra-")
        'upper-case-extra'
        >>> to_slug("main")
        'main'
        >>> to_slug("")
        ''
    """
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.rstrip("-")
    return value


def get_sentinel_path() -> str:
    """Compute the commit-authorization sentinel file path for the current git repo and branch.

    Runs ``git rev-parse --show-toplevel`` and ``git branch --show-current``
    to derive repo name and branch, slugifies both, and returns the sentinel path.

    Args:
        None

    Returns:
        Absolute sentinel path string, e.g. ``/tmp/claude-commit-auth-myrepo-main``.

    Raises:
        subprocess.CalledProcessError: if not inside a git repository.

    Examples:
        No doctest — requires live git subprocess; covered by pytest with monkeypatch.
    """
    repo_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    repo_name = repo_root.rsplit("/", 1)[-1]

    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()

    # Prefer per-user temp dirs over `/tmp`. macOS's `/tmp` is world-readable
    # (mode 1777) — the sentinel name leaks branch/repo metadata to other
    # users on shared hosts. Order: TMPDIR (per-user on macOS) →
    # XDG_RUNTIME_DIR (per-user on Linux) → tempfile.gettempdir() fallback.
    base = os.environ.get("TMPDIR") or os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return f"{base.rstrip('/')}/claude-commit-auth-{to_slug(repo_name)}-{to_slug(branch)}"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list override for testing. Defaults to sys.argv[1:].

    Returns:
        Exit code: 0 on success, 1 on git error.

    Examples:
        No doctest — requires live git; covered by pytest.
    """
    _ = sys.argv[1:] if argv is None else argv  # no positional args used
    try:
        print(get_sentinel_path())
        return 0
    except subprocess.CalledProcessError as e:
        print(f"git error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
