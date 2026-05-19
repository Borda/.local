#!/usr/bin/env python
"""health_sentinel.py — health-monitoring sentinel helper.

Two subcommands mirror the original ``health-sentinel.sh`` interface:

* ``start <skill-id>`` — create ``/tmp/foundry-<skill-id>-check-<ts>``;
  print two eval-able lines::

      LAUNCH_AT=<ts>
      SENTINEL=<path>

  The two lines are intended to be consumed via
  ``eval "$(python3 health_sentinel.py start audit)"`` in bash.

* ``check <sentinel> <run-dir>`` — exit 0 if any file under ``<run-dir>``
  is newer than ``<sentinel>``'s mtime; exit 1 otherwise.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/health_sentinel.py" start <skill-id>
    python "${CLAUDE_PLUGIN_ROOT}/bin/health_sentinel.py" check <sentinel> <run-dir>

Exit codes:
    0  Success — sentinel created, OR new files since sentinel mtime
    1  Stalled — no new files since sentinel mtime, sentinel missing, or run-dir absent
    2  Bad args (argparse)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def create_sentinel(skill_id: str, tmp_dir: Path | None = None, now: int | None = None) -> tuple[int, Path]:
    """Create sentinel file and return ``(launch_at, sentinel_path)``.

    Args:
        skill_id: Skill identifier used in the sentinel filename.
        tmp_dir: Override directory (defaults to ``/tmp``); tests inject ``tmp_path``.
        now: Override timestamp (defaults to ``int(time.time())``).

    Returns:
        Tuple of ``(launch_at_epoch_seconds, sentinel_path)``.
    """
    if tmp_dir is None:
        tmp_dir = Path("/tmp")
    if now is None:
        now = int(time.time())
    sentinel = tmp_dir / f"foundry-{skill_id}-check-{now}"
    sentinel.touch()
    return now, sentinel


def has_new_files(sentinel: Path, run_dir: Path) -> bool:
    """Return True if any file under ``run_dir`` is newer than ``sentinel``'s mtime.

    Args:
        sentinel: Sentinel file whose mtime defines the cutoff.
        run_dir: Directory tree to scan recursively for newer files.

    Returns:
        False if sentinel is missing, run_dir is not a directory, or no newer
        files exist; True otherwise.
    """
    if not sentinel.exists() or not run_dir.is_dir():
        return False
    cutoff = sentinel.stat().st_mtime
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime > cutoff:
                return True
        except OSError:
            # Race: file disappeared between rglob and stat; ignore.
            continue
    return False


def _cmd_start(skill_id: str) -> int:
    """Handle ``start`` subcommand. Returns exit code."""
    launch_at, sentinel = create_sentinel(skill_id)
    print(f"LAUNCH_AT={launch_at}\nSENTINEL={sentinel}")
    return 0


def _cmd_check(sentinel: str, run_dir: str) -> int:
    """Handle ``check`` subcommand. Returns exit code (0 alive, 1 stalled)."""
    return 0 if has_new_files(Path(sentinel), Path(run_dir)) else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = argparse.ArgumentParser(
        description="Health-monitoring sentinel helper.",
        add_help=True,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    start_parser = subparsers.add_parser("start", help="Create sentinel and print eval-able env lines.")
    start_parser.add_argument("skill_id", help="Skill identifier used in the sentinel filename.")

    check_parser = subparsers.add_parser("check", help="Check whether new files appeared since sentinel.")
    check_parser.add_argument("sentinel", help="Path to sentinel file from a prior `start`.")
    check_parser.add_argument("run_dir", help="Run directory to scan for newer files.")

    args = parser.parse_args(argv)

    if args.mode == "start":
        return _cmd_start(args.skill_id)
    if args.mode == "check":
        return _cmd_check(args.sentinel, args.run_dir)
    # argparse(required=True) guarantees one of the above; unreachable.
    return 2


if __name__ == "__main__":
    sys.exit(main())
