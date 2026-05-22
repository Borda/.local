#!/usr/bin/env python
"""health_monitor_start.py — create research health-monitoring sentinel.

Prints ``LAUNCH_AT`` (epoch seconds) and ``SENTINEL`` (path, forward-slash
separated for bash compatibility) to stdout.

Sentinel dir mirrors JS getSentinelDir(): ``/tmp`` on POSIX,
``tempfile.gettempdir()`` on Windows — matches task-log.js and commit-guard.js.

Usage:
    python health_monitor_start.py <skill-id>

Exit codes:
    0 — success
    1 — missing skill-id argument
    2 — invalid skill-id (unsafe characters)
"""

from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

_SKILL_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sentinel_dir() -> Path:
    """Return ``/tmp`` on POSIX or ``tempfile.gettempdir()`` on Windows.

    Mirrors JS ``getSentinelDir()`` so sentinel paths match hook expectations
    on all platforms while preserving the existing ``/tmp`` path on POSIX.
    """
    return Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")


def main(argv: list[str] | None = None) -> int:
    """Create sentinel file and print LAUNCH_AT + SENTINEL; return exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        0 on success, 1 on missing arg, 2 on validation error.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("health_monitor_start: skill-id required", file=sys.stderr)
        return 1

    skill_id = args[0]
    if not _SKILL_RE.match(skill_id):
        print(f"health_monitor_start: invalid SKILL_ID: {skill_id!r}", file=sys.stderr)
        return 2

    launch_at = int(time.time())
    sentinel = _sentinel_dir() / f"research-{skill_id}-check-{launch_at}"
    sentinel.touch()

    sys.stdout.write(f"LAUNCH_AT={launch_at}\nSENTINEL={sentinel.as_posix()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
