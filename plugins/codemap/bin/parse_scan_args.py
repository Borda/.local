#!/usr/bin/env python
"""parse_scan_args.py — extract ``--root`` and ``--incremental`` flags from a single $ARGUMENTS string.

Usage:
    python3 "${CLAUDE_PLUGIN_ROOT}/bin/parse_scan_args.py" "$ARGUMENTS" [--nul-output <file>] [--print-root]

Output (default):
    Shell-quoted argument tokens suitable for ``eval``:

        eval "SCAN_ARGS=( $(python3 parse_scan_args.py "$ARGUMENTS") )"

Output (--nul-output <file>):
    Writes each argument token NUL-delimited to <file>. No stdout.
    Caller reads safely with: while IFS= read -r -d '' arg; do ...; done < <file>

Output (--print-root):
    Prints just the resolved --root value (or '.' when absent) on stdout.

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


def _extract_root(arguments: str) -> str | None:
    """Return the raw --root value from arguments, or None when absent.

    Args:
        arguments: Raw $ARGUMENTS string from the caller.

    Returns:
        The unquoted root path string, or ``None`` when ``--root`` is absent.

    Examples:
        >>> _extract_root("--root /abs/path")
        '/abs/path'
        >>> _extract_root("--root '/abs path/with spaces'")
        '/abs path/with spaces'
        >>> _extract_root("--incremental")
        >>> _extract_root("")
    """
    match = _ROOT_RE.search(arguments)
    if match is None:
        return None
    return next(group for group in match.groups() if group is not None)


def parse_scan_args(arguments: str) -> list[str]:
    """Parse the $ARGUMENTS string for ``--root`` and ``--incremental`` flags.

    Args:
        arguments: Raw $ARGUMENTS string from the caller.

    Returns:
        List of argument tokens (unquoted strings). Empty when neither flag is
        present. The ``--root`` value is the resolved path string; callers that
        need shell-safe output must apply :func:`shlex.quote` themselves.

    Examples:
        >>> parse_scan_args("--root /abs/path")
        ['--root', '/abs/path']
        >>> parse_scan_args("--root '/abs path/with spaces' --incremental")
        ['--root', '/abs path/with spaces', '--incremental']
        >>> parse_scan_args('--root "/abs/path"')
        ['--root', '/abs/path']
        >>> parse_scan_args("--incremental")
        ['--incremental']
        >>> parse_scan_args("")
        []
        >>> parse_scan_args("--incremental --root /tmp/x")
        ['--root', '/tmp/x', '--incremental']
    """
    tokens: list[str] = []

    root_val = _extract_root(arguments)
    if root_val is not None:
        tokens.extend(["--root", root_val])

    if "--incremental" in arguments:
        tokens.append("--incremental")

    return tokens


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: read $ARGUMENTS, emit arg tokens, return 0.

    Flags (after the positional $ARGUMENTS):
        --nul-output <file>  Write tokens NUL-delimited to <file>; no stdout.
        --print-root         Print only the resolved --root value (or '.').

    Args:
        argv: Optional argv override for testing. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (always 0).

    Examples:
        >>> import os, tempfile
        >>> with tempfile.NamedTemporaryFile(delete=False) as f:
        ...     path = f.name
        >>> main(["--root /tmp/x --incremental", "--nul-output", path])
        0
        >>> open(path, "rb").read() == b"--root\\x00/tmp/x\\x00--incremental\\x00"
        True
        >>> os.unlink(path)
        >>> main(["--root /tmp/x", "--print-root"])
        /tmp/x
        0
    """
    args = sys.argv[1:] if argv is None else argv

    # First positional arg = raw $ARGUMENTS string.
    arguments = args[0] if args else ""
    rest = args[1:]

    # Parse optional flags from rest.
    nul_output: str | None = None
    print_root: bool = False
    i = 0
    while i < len(rest):
        if rest[i] == "--nul-output":
            i += 1
            if i < len(rest):
                nul_output = rest[i]
            i += 1
        elif rest[i] == "--print-root":
            print_root = True
            i += 1
        else:
            i += 1

    tokens = parse_scan_args(arguments)

    if print_root:
        root_val = _extract_root(arguments)
        print(root_val if root_val is not None else ".")
        return 0

    if nul_output is not None:
        with open(nul_output, "wb") as fh:
            for token in tokens:
                fh.write(token.encode() + b"\x00")
        return 0

    # Default: print shell-quoted tokens on stdout (legacy eval-safe form).
    quoted_tokens: list[str] = []
    it = iter(tokens)
    for token in it:
        if token == "--root":
            root_val = next(it, "")
            quoted_tokens.append(f"--root {shlex.quote(root_val)}")
        else:
            quoted_tokens.append(shlex.quote(token))
    print(" ".join(quoted_tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
