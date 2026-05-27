#!/usr/bin/env python
"""Parse ``--diagnosis <path>`` (or ``--diagnosis=<path>``) from an ``$ARGUMENTS`` string.

Usage:
    diagnosis_parse.py "$ARGUMENTS"

Behaviour:
    Scans the single argument string for either form of the flag. Prints the resolved
    path to stdout (empty string when flag absent). When the flag is given but the path
    does not exist, exits 1 with a ``! BREAKING`` stderr block matching the bash original.
    No subprocess calls — pure string parsing.

Exit codes:
    0 — flag absent, OR flag present and file exists (path printed to stdout).
    1 — flag present but file does not exist.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


def parse_diagnosis(arguments: str) -> str:
    """Extract the diagnosis file path from an arguments string.

    Mirrors the bash original's token-by-token scan: accepts both ``--diagnosis=<path>``
    and ``--diagnosis <path>`` forms; a value beginning with ``--`` is treated as the
    next flag and *not* consumed as a diagnosis value.

    Args:
        arguments: The raw ``$ARGUMENTS`` string from a skill invocation.

    Returns:
        The diagnosis path (possibly empty string if no flag is present or the value
        was preempted by another flag).

    Examples:
        >>> parse_diagnosis("")
        ''
        >>> parse_diagnosis("--mode fix --team")
        ''
        >>> parse_diagnosis("--diagnosis=path/to/diag.md")
        'path/to/diag.md'
        >>> parse_diagnosis("--diagnosis path/to/diag.md")
        'path/to/diag.md'
        >>> parse_diagnosis("--diagnosis --team")
        ''
        >>> parse_diagnosis("--mode fix --diagnosis=foo.md --team")
        'foo.md'
    """
    tokens = shlex.split(arguments)
    diag_file = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--diagnosis="):
            diag_file = tok.split("=", 1)[1]
        elif tok == "--diagnosis" and i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            diag_file = tokens[i + 1]
            i += 1
        i += 1
    return diag_file


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``diagnosis-parse.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        0 when the flag is absent or the resolved file exists; 1 when the file is missing.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)
    arguments = args[0] if args else ""

    try:
        diag_file = parse_diagnosis(arguments)
    except ValueError as e:
        print(f"! BREAKING — malformed argument quoting: {e}", file=sys.stderr)
        return 1

    if diag_file:
        resolved = Path(diag_file).resolve()
        cwd = Path.cwd().resolve()
        try:
            resolved.relative_to(cwd)
        except ValueError:
            # Containment check before existence check — prevents path-existence
            # oracle (e.g. `--diagnosis /etc/passwd` would otherwise report
            # success and echo the absolute path).
            print(
                f"! BREAKING — diagnosis path outside project root: {diag_file}",
                file=sys.stderr,
            )
            print(
                "Fix: pass a diagnosis path under the current project (e.g. .plans/active/debug_*.md)",
                file=sys.stderr,
            )
            return 1
        if not resolved.is_file():
            print(f"! BREAKING — diagnosis file not found: {diag_file}", file=sys.stderr)
            print(
                "Fix: run /develop:debug first to produce a diagnosis file, or omit --diagnosis",
                file=sys.stderr,
            )
            return 1

    print(diag_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
