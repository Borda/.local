"""List open session files with their age in days.

Scans a directory for ``session-open-*.md`` files and prints each as
``<age_days>\\t<path>`` on stdout.  Used by the ``/foundry:session`` skill
to detect stale open sessions.
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path


def age_days(mtime: float, now: float) -> int:
    """Return whole days elapsed since *mtime*.

    Args:
        mtime: File modification time as a POSIX timestamp.
        now: Reference timestamp (typically ``time.time()``).

    Returns:
        Floor of ``(now - mtime) / 86400``.

    Examples:
        >>> age_days(0.0, 86400.0)
        1
        >>> age_days(0.0, 86399.9)
        0
        >>> age_days(0.0, 0.0)
        0
    """
    return math.floor((now - mtime) / 86400)


def list_session_files(
    session_dir: Path,
    *,
    now: float | None = None,
) -> list[tuple[int, Path]]:
    """Return ``(age_days, path)`` pairs for open session files.

    Args:
        session_dir: Directory to scan.  Missing directory yields ``[]``.
        now: Reference timestamp; defaults to ``time.time()``.

    Returns:
        Sorted list of ``(age, path)`` for every ``session-open-*.md``
        file found.

    Examples:
        >>> import tempfile, os, time
        >>> with tempfile.TemporaryDirectory() as d:
        ...     result = list_session_files(__import__('pathlib').Path(d) / 'nope')
        ...     result
        []
    """
    if now is None:
        now = time.time()
    if not session_dir.is_dir():
        return []
    pairs: list[tuple[int, Path]] = []
    for p in sorted(session_dir.glob("session-open-*.md")):
        pairs.append((age_days(p.stat().st_mtime, now), p))
    return pairs


def main(argv: list[str]) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (e.g. ``sys.argv[1:]``).

    Returns:
        Exit code: 0 on success, 2 when required arguments missing.
    """
    parser = argparse.ArgumentParser(description="List open session files with age in days.")
    parser.add_argument("session_dir", help="Directory containing session files.")
    args = parser.parse_args(argv)

    for age, path in list_session_files(Path(args.session_dir)):
        print(f"{age}\t{path}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
