#!/usr/bin/env python
"""dev_run_dir.py — create ``.developments/<UTC-timestamp>/`` run directory.

With ``--sentinel <name>``, also touches ``<sentinel-dir>/<name>-<ts>``.
Sentinel name is sanitized to ``[a-zA-Z0-9_-]+`` to prevent path traversal.

Sentinel dir mirrors JS getSentinelDir(): ``/tmp`` on POSIX,
``tempfile.gettempdir()`` on Windows — matches commit-guard.js and task-log.js.

Usage:
    python dev_run_dir.py [--sentinel <name>]

Output:
    Relative path of the created run directory.

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
    """Create run dir and optional sentinel; print path; return exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Always 0.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = Path(".developments") / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    if len(args) >= 2 and args[0] == "--sentinel" and args[1]:
        sentinel_name = _SAFE_NAME_RE.sub("", args[1])
        if sentinel_name:
            (_sentinel_dir() / f"{sentinel_name}-{ts}").touch()

    sys.stdout.write(str(run_dir) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
