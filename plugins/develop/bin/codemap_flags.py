#!/usr/bin/env python
"""codemap_flags.py — resolve CODEMAP_ENABLED value from a raw argument string.

Usage:
    python codemap_flags.py "$ARGUMENTS"

Output: exactly one of ``off`` | ``strict`` | ``auto`` (LF-terminated).
``--no-codemap`` → ``off``; ``--codemap`` (without ``--no-``) → ``strict``; else → ``auto``.

Exit codes:
    0 — always (mirrors bash behaviour)
"""

from __future__ import annotations

import sys


def resolve_codemap_flag(args_string: str) -> str:
    """Resolve CODEMAP_ENABLED from a raw argument string.

    Precedence: ``--no-codemap`` > ``--codemap`` > default ``auto``.
    Substring match; flag may appear anywhere in the string.

    Args:
        args_string: Raw argument string passed to the skill invocation.

    Returns:
        ``"off"``, ``"strict"``, or ``"auto"``.
    """
    if "--no-codemap" in args_string:
        return "off"
    if "--codemap" in args_string:
        return "strict"
    return "auto"


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Always 0.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = argv if argv is not None else sys.argv[1:]
    args_string = args[0] if args else ""
    sys.stdout.write(resolve_codemap_flag(args_string) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
