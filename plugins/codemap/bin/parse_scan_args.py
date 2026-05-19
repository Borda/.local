#!/usr/bin/env python
"""parse_scan_args.py — extract ``--root`` and ``--incremental`` flags from a single $ARGUMENTS string.

Usage:
    python3 "${CLAUDE_PLUGIN_ROOT}/bin/parse_scan_args.py" "$ARGUMENTS"

Output:
    Shell-quoted argument tokens suitable for ``eval``:

        eval "SCAN_ARGS=( $(python3 parse_scan_args.py "$ARGUMENTS") )"

Example output:
    --root '/abs/path' --incremental

Exit codes:
    0  always (never fails on input).
"""

from __future__ import annotations

import re
import shlex
import sys

# --root <value> where value is one of:
#   - single-quoted: '...'  (no embedded single quotes)
#   - double-quoted: "..."  (no embedded double quotes)
#   - unquoted: any run of non-whitespace characters
# Matches first occurrence anywhere in the string. The three branches mirror
# the original sed pipeline's `t`-branch fallthrough semantics.
_ROOT_RE = re.compile(
    r"--root\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))",
)


def parse_scan_args(arguments: str) -> str:
    """Parse the $ARGUMENTS string for ``--root`` and ``--incremental`` flags.

    Args:
        arguments: Raw $ARGUMENTS string from the caller.

    Returns:
        Space-separated shell-quoted argument tokens. The string is empty when
        neither flag is present. When ``--root`` is present, the value is
        passed through :func:`shlex.quote` so the caller can safely ``eval`` the
        result. ``shlex.quote`` emits the minimal safe form — plain
        alphanumeric paths come back unquoted, paths with spaces or special
        characters are wrapped in single quotes.

    Examples:
        >>> parse_scan_args("--root /abs/path")
        '--root /abs/path'
        >>> parse_scan_args("--root '/abs path/with spaces' --incremental")
        "--root '/abs path/with spaces' --incremental"
        >>> parse_scan_args('--root "/abs/path"')
        '--root /abs/path'
        >>> parse_scan_args("--incremental")
        '--incremental'
        >>> parse_scan_args("")
        ''
        >>> parse_scan_args("--incremental --root /tmp/x")
        '--root /tmp/x --incremental'
    """
    tokens: list[str] = []

    match = _ROOT_RE.search(arguments)
    if match is not None:
        # Exactly one of the three capture groups matched.
        root_val = next(group for group in match.groups() if group is not None)
        tokens.append(f"--root {shlex.quote(root_val)}")

    if "--incremental" in arguments:
        tokens.append("--incremental")

    return " ".join(tokens)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: read $ARGUMENTS, print shell-quoted tokens, return 0.

    Args:
        argv: Optional argv override for testing. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (always 0).
    """
    args = sys.argv[1:] if argv is None else argv
    arguments = args[0] if args else ""
    print(parse_scan_args(arguments))
    return 0


if __name__ == "__main__":
    sys.exit(main())
