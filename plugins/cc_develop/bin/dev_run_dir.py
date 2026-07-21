#!/usr/bin/env python
"""dev_run_dir.py — create ``.developments/<UTC-timestamp>/`` run directory.

With ``--sentinel <name>``, also touches ``<sentinel-dir>/<name>-<ts>``.
Sentinel name is sanitized to ``[a-zA-Z0-9_-]+`` to prevent path traversal.

Sentinel dir mirrors JS getSentinelDir(): ``/tmp`` on POSIX,
``tempfile.gettempdir()`` on Windows — matches commit-guard.js and task-log.js.

Usage:
    python dev_run_dir.py [--sentinel <name>]

Output (stdout):
    Relative path of the created run directory.

Exit codes:
    0 — always (matches bash behaviour)
    2 — bad/missing required argument (argparse default)
"""

from __future__ import annotations

import argparse
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
        ``0`` always; argparse exits ``2`` on bad args.

    No doctest — creates directories and touches sentinel files; covered by pytest.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(
        prog="dev_run_dir.py",
        description="Create a timestamped .developments/ run directory, optionally with a sentinel.",
    )
    # nargs="?" so a bare ``--sentinel`` (no name) is accepted and simply skips the
    # sentinel touch — preserves the legacy bash contract where the name was optional.
    parser.add_argument("--sentinel", nargs="?", default="", help="Sentinel base name (sanitized to [a-zA-Z0-9_-]).")
    args = parser.parse_args(argv)

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = Path(".developments") / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.sentinel:
        sentinel_name = _SAFE_NAME_RE.sub("", args.sentinel)
        if sentinel_name:
            (_sentinel_dir() / f"{sentinel_name}-{ts}").touch()

    sys.stdout.write(run_dir.as_posix() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
