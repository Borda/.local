#!/usr/bin/env python
"""health_sentinel.py — health-monitoring sentinel helper.

Two subcommands mirror the original ``health-sentinel.sh`` interface:

* ``start <skill-id>`` — create ``<tmpdir>/foundry-<skill-id>-check-<ts>``;
  print two eval-able lines::

      LAUNCH_AT=<ts>
      SENTINEL=<path>

  The two lines are intended to be consumed via
  ``eval "$(python health_sentinel.py start audit)"`` in bash.

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
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

# Defensive bound on the recursive scan in `has_new_files`. Hard cap protects
# against a maliciously deep or huge `run_dir` (DoS via traversal); 50_000 files
# is far beyond any realistic foundry skill run dir while still inexpensive.
_MAX_FILES_SCANNED = 50_000


def _allowed_roots() -> list[Path]:
    """Return the list of directories under which ``run_dir`` is allowed to live.

    Currently the project working directory and the system temp directory (the
    same locations skills are documented to write to). Resolved to absolute,
    symlink-free paths so containment checks are robust to ``../`` traversal.

    Returns:
        List of resolved allowed root paths.

    Examples:
        >>> roots = _allowed_roots()
        >>> all(isinstance(r, Path) and r.is_absolute() for r in roots)
        True
    """
    return [
        Path.cwd().resolve(),
        Path(os.environ.get("TMPDIR", tempfile.gettempdir())).resolve(),
    ]


def _validate_run_dir(run_dir: Path) -> Path:
    """Resolve ``run_dir`` and assert it lives under one of the allowed roots.

    Args:
        run_dir: User-supplied run directory path.

    Returns:
        The resolved (absolute, symlink-free) path.

    Raises:
        ValueError: If the resolved path is not under any allowed root.

    Examples:
        >>> from pathlib import Path
        >>> _validate_run_dir(Path.cwd()).is_absolute()
        True
    """
    resolved = run_dir.resolve()
    roots = _allowed_roots()
    if not any(resolved == r or r in resolved.parents for r in roots):
        raise ValueError(
            f"run_dir outside allowed roots (cwd, tmpdir): {resolved}",
        )
    return resolved


def create_sentinel(skill_id: str, tmp_dir: Path | None = None, now: int | None = None) -> tuple[int, Path]:
    """Create sentinel file and return ``(launch_at, sentinel_path)``.

    Args:
        skill_id: Skill identifier used in the sentinel filename.
        tmp_dir: Override directory (defaults to ``tempfile.gettempdir()``); tests inject ``tmp_path``.
        now: Override timestamp (defaults to ``int(time.time())``).

    Returns:
        Tuple of ``(launch_at_epoch_seconds, sentinel_path)``.
    """
    if tmp_dir is None:
        tmp_dir = Path(tempfile.gettempdir())
    if now is None:
        now = int(time.time())
    sentinel = tmp_dir / f"foundry-{skill_id}-check-{now}"
    sentinel.touch()
    return now, sentinel


def has_new_files(sentinel: Path, run_dir: Path) -> bool:
    """Return True if any file under ``run_dir`` is newer than ``sentinel``'s mtime.

    The scan is hard-capped at ``_MAX_FILES_SCANNED`` entries to bound work on
    pathological inputs. ``run_dir`` is validated against the allowed-roots
    list before scanning; out-of-bound paths raise ``ValueError``.

    Args:
        sentinel: Sentinel file whose mtime defines the cutoff.
        run_dir: Directory tree to scan recursively for newer files.

    Returns:
        False if sentinel is missing, ``run_dir`` is not a directory, or no
        newer files exist; True otherwise.

    Raises:
        ValueError: If ``run_dir`` resolves outside the allowed roots.
    """
    if not sentinel.exists() or not run_dir.is_dir():
        return False
    safe_run_dir = _validate_run_dir(run_dir)
    cutoff = sentinel.stat().st_mtime
    scanned = 0
    for path in safe_run_dir.rglob("*"):
        scanned += 1
        if scanned > _MAX_FILES_SCANNED:
            # Defensive: stop walking to bound cost; treat as no signal.
            return False
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
    """Handle ``start`` subcommand. Returns exit code.

    ``LAUNCH_AT`` is emitted as a bare integer; ``SENTINEL`` is shell-quoted
    via ``shlex.quote`` so a downstream ``eval`` cannot trigger word-splitting
    or glob expansion even if the path contains special characters.
    """
    launch_at, sentinel = create_sentinel(skill_id)
    print(f"LAUNCH_AT={launch_at}\nSENTINEL={shlex.quote(sentinel.as_posix())}")
    return 0


def _validate_sentinel(sentinel: Path) -> Path:
    """Resolve sentinel path and assert it lives under an allowed root (tmpdir or cwd).

    Args:
        sentinel: User-supplied sentinel file path.

    Returns:
        The resolved path.

    Raises:
        ValueError: If the resolved path is outside allowed roots.
    """
    resolved = sentinel.resolve()
    roots = _allowed_roots()
    if not any(resolved == r or r in resolved.parents for r in roots):
        raise ValueError(
            f"sentinel path outside allowed roots (cwd, tmpdir): {resolved}",
        )
    return resolved


def _cmd_check(sentinel: str, run_dir: str) -> int:
    """Handle ``check`` subcommand. Returns exit code (0 alive, 1 stalled)."""
    try:
        safe_sentinel = _validate_sentinel(Path(sentinel))
    except ValueError as exc:
        print(f"health_sentinel: {exc}", file=sys.stderr)
        return 1
    return 0 if has_new_files(safe_sentinel, Path(run_dir)) else 1


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
        if not _SAFE_ID.match(args.skill_id):
            print(
                f"health_sentinel: invalid skill_id {args.skill_id!r} — must match [a-zA-Z0-9_-]+",
                file=sys.stderr,
            )
            return 2
        return _cmd_start(args.skill_id)
    if args.mode == "check":
        return _cmd_check(args.sentinel, args.run_dir)
    # argparse(required=True) guarantees one of the above; unreachable.
    return 2


if __name__ == "__main__":
    sys.exit(main())
