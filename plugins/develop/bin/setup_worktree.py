#!/usr/bin/env python
"""setup_worktree.py — create ``.temp/develop/<UTC-timestamp>/`` run directory.

Team-mode subagent handoff directory per artifact-lifecycle.md. Differs from
``dev_run_dir.py`` which creates ``.developments/<ts>/`` for skill checkpoints.

With ``--sentinel <name>``, also touches ``<sentinel-dir>/<name>-<ts>``.
Sentinel name is sanitized to ``[a-zA-Z0-9_-]+`` to prevent path traversal.

Sentinel dir mirrors JS getSentinelDir(): ``/tmp`` on POSIX,
``tempfile.gettempdir()`` on Windows.

Usage:
    python setup_worktree.py [--sentinel <name>]

Output (two lines):
    Line 1: UTC timestamp (e.g. ``2026-05-22T10-00-00Z``)
    Line 2: Run directory path (e.g. ``.temp/develop/2026-05-22T10-00-00Z``)

Exit codes:
    0 — always (matches bash behaviour)
"""

from __future__ import annotations

import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sentinel_dir() -> Path:
    """Return ``/tmp`` on POSIX or ``tempfile.gettempdir()`` on Windows.

    Mirrors JS ``getSentinelDir()`` so sentinel paths match hook expectations
    on all platforms while preserving the existing ``/tmp`` path on POSIX.
    """
    return Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")


def main(argv: list[str] | None = None) -> int:
    """Create run dir and optional sentinel; print ts + path; return exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Always 0.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = Path(".temp") / "develop" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    if len(args) >= 2 and args[0] == "--sentinel" and args[1]:
        sentinel_name = _SAFE_NAME_RE.sub("", args[1])
        if sentinel_name:
            (_sentinel_dir() / f"{sentinel_name}-{ts}").touch()

    sys.stdout.write(f"{ts}\n{run_dir.as_posix()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
