#!/usr/bin/env python
"""Extract a diagnosis path from skill arguments and validate its project containment.

Scans the single argument string for either form of the flag. Prints the resolved
path spelling to stdout (empty string when flag absent). Reject malformed quoting,
paths outside the current project, and paths that do not name a regular file with
exit 1 and a ``! BREAKING`` diagnostic. Parsing is pure; the CLI checks the filesystem.

The single positional is an opaque ``$ARGUMENTS`` blob whose internal ``--diagnosis``
token is consumed by :func:`parse_diagnosis`, never by argparse's own matcher — argparse
is present only to supply ``-h/--help``.

Usage:
    diagnosis_parse.py "$ARGUMENTS"

Exit codes:
    0 — flag absent, OR flag present and file exists (path printed to stdout).
    1 — malformed quoting, path outside project, or path not a regular file.
    2 — invalid help-mode arguments (argparse default).
"""

from __future__ import annotations

import argparse
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

    Raises:
        ValueError: If shell-style quoting is malformed.

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
        >>> parse_diagnosis('--diagnosis "notes/my diagnosis.md"')
        'notes/my diagnosis.md'
        >>> parse_diagnosis('--diagnosis=old.md --diagnosis=new.md')
        'new.md'
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
    """Print a validated diagnosis path or a diagnostic for invalid arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        0 when the flag is absent or resolves to a regular file inside the current project;
        1 for malformed quoting, an out-of-project path, or a missing/non-regular file.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    raw = list(sys.argv[1:] if argv is None else argv)

    # Handle -h/--help via argparse, then treat argv[0] as the opaque blob. The blob may
    # itself be a bare ``--``-prefixed token (e.g. ``--diagnosis``), which argparse would
    # otherwise reject as an unknown option — so it is NOT fed through parse_args.
    if raw and raw[0] in {"-h", "--help"}:
        parser = argparse.ArgumentParser(
            prog="diagnosis_parse.py",
            description="Parse --diagnosis <path> from an $ARGUMENTS blob.",
        )
        parser.add_argument("arguments", nargs="?", default="", help="Raw $ARGUMENTS blob (parsed internally).")
        parser.parse_args(raw)  # exits 0 after printing help

    arguments = raw[0] if raw else ""

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
