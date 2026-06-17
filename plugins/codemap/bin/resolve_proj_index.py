#!/usr/bin/env python
"""resolve_proj_index.py — compute project name and codemap index path.

Derives PROJ from the git root basename (or CWD basename when outside a repo).
INDEX path is ``<git-root-or-cwd>/.cache/codemap/<proj>.json`` by default.
Override directory with ``CODEMAP_INDEX_DIR`` env var (e.g. ``~/codemap-cache``).

Usage:
    python resolve_proj_index.py [--check]

Output (no ``--check``):
    Two lines: line 1 = PROJ, line 2 = INDEX path.

Output (``--check``):
    Same two lines plus a third status line:
    ``✓ index: exists`` (exit 0) or ``✗ index: not found`` (exit 1).

Exit codes:
    0 — success
    1 — ``--check`` requested and index file missing
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve(cmd: str) -> str:
    """Return full path to *cmd* via PATH lookup; raises if absent.

    Args:
        cmd: Executable name (e.g. ``"git"``).

    Returns:
        Absolute path string suitable for ``subprocess.run``.

    Raises:
        FileNotFoundError: When *cmd* is not on PATH.
    """
    p = shutil.which(cmd)
    if not p:
        raise FileNotFoundError(f"{cmd!r} not on PATH")
    return p


def compute_proj_index(cwd: Path | None = None) -> tuple[str, Path]:
    """Return ``(proj_name, index_path)`` derived from the git root or CWD.

    Respects ``CODEMAP_INDEX_DIR`` env var — when set, index lives at
    ``$CODEMAP_INDEX_DIR/<proj>.json`` regardless of git root location.

    Args:
        cwd: Working directory for git resolution (defaults to ``Path.cwd()``).

    Returns:
        Tuple of project name string and absolute index ``Path``.
    """
    work_dir = cwd or Path.cwd()
    git_root: Path | None = None
    try:
        # timeout=5 — SEC-L7: bound git subprocess to fail fast on hung repos / FUSE mounts.
        result = subprocess.run(
            [_resolve("git"), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(work_dir),
            check=True,
            timeout=5,
        )
        git_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    base = git_root or work_dir
    proj = base.name
    custom_dir = os.environ.get("CODEMAP_INDEX_DIR")
    if custom_dir:
        # expanduser + resolve: canonicalize path, eliminate symlink traversal.
        # No root whitelist — CODEMAP_INDEX_DIR is explicit user config (trusted).
        index_dir = Path(custom_dir).expanduser().resolve()
    else:
        index_dir = base / ".cache" / "codemap"
    index = index_dir / f"{proj}.json"
    return proj, index


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        0 on success, 1 when ``--check`` is passed and the index is missing.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]
    check = "--check" in args

    proj, index = compute_proj_index()
    sys.stdout.write(f"{proj}\n{index}\n")

    if not check:
        return 0

    if index.is_file():
        sys.stdout.write("✓ index: exists\n")
        return 0

    sys.stdout.write("✗ index: not found\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
