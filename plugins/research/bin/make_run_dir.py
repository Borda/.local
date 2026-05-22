#!/usr/bin/env python
"""make_run_dir.py — create a slug-prefixed UTC-timestamped run directory.

Prints the created directory path to stdout (LF-terminated, no CRLF).

Usage:
    python make_run_dir.py <skill-slug> <base-dir>

Exit codes:
    0 — success
    1 — wrong number of arguments
    2 — invalid skill-slug or base-dir (unsafe characters or path traversal)
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
# Strictly relative — no leading slash, no NUL byte, no ``..``, only the
# alphanumeric/underscore/dot/hyphen/slash subset that matches the project
# artifact tree (``.experiments``, ``.reports/...``, etc.) (CWE-22).
_BASE_RE = re.compile(r"^[a-zA-Z0-9_.][a-zA-Z0-9_./-]*$")


def make_run_dir(skill_slug: str, base_dir: str) -> Path:
    """Create ``<base_dir>/<skill_slug>-<UTC-timestamp>/`` and return its path.

    Args:
        skill_slug: Alphanumeric skill identifier; no path separators.
        base_dir: Parent directory path (created with parents if absent).

    Returns:
        Path of the newly created run directory.
    """
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = Path(base_dir) / f"{skill_slug}-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        0 on success, 1 on argument error, 2 on validation error.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: make_run_dir.py <skill-slug> <base-dir>", file=sys.stderr)
        return 1
    skill_slug, base_dir = args
    if not _SLUG_RE.match(skill_slug):
        print(f"make_run_dir: invalid SKILL_SLUG: {skill_slug!r}", file=sys.stderr)
        return 2
    if not _BASE_RE.match(base_dir) or ".." in base_dir or os.path.isabs(base_dir):
        print(f"make_run_dir: invalid BASE_DIR: {base_dir!r}", file=sys.stderr)
        return 2
    sys.stdout.write(str(make_run_dir(skill_slug, base_dir)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
