#!/usr/bin/env python
"""parse_deprecate_args.py — extract ``--deprecate`` flag and optional decorator value from $ARGUMENTS.

Writes DEPRECATE and DEPRECATE_DECORATOR to ``${TMPDIR:-/tmp}/codemap-deprecate-{flag,decorator}``
so the caller reads with ``cat`` — avoids the ``eval "$(...)"`` anti-pattern.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/parse_deprecate_args.py" --arguments="$ARGUMENTS"
    DEPRECATE=$(cat "${TMPDIR:-/tmp}/codemap-deprecate-flag" 2>/dev/null || echo "false")
    DEPRECATE_DECORATOR=$(cat "${TMPDIR:-/tmp}/codemap-deprecate-decorator" 2>/dev/null || echo "")

The ``--arguments=`` form (equals sign, no space) is required so that values
beginning with ``--`` (e.g. the literal payload ``--deprecate``) survive
argparse's flag-detection.

Output files (raw values, no shell quoting — safe to read with ``cat``):
    ${TMPDIR:-/tmp}/codemap-deprecate-flag        "true" or "false"
    ${TMPDIR:-/tmp}/codemap-deprecate-decorator   raw decorator string (empty when absent)

Recognises:
    --deprecate                            bare flag → DEPRECATE=true, DEPRECATE_DECORATOR=''
    --deprecate=<value>                    value form → DEPRECATE=true, DEPRECATE_DECORATOR=<value>
    --deprecate='<value with spaces>'      single-quoted value → quotes stripped
    --deprecate="<value with spaces>"      double-quoted value → quotes stripped
    --no-deprecate                         negation → DEPRECATE=false, DEPRECATE_DECORATOR=''

Exit codes:
    0  always (never fails on input).
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from pathlib import Path

# --deprecate=<value> where value is one of:
#   - single-quoted: '...'  (no embedded single quotes)
#   - double-quoted: "..."  (no embedded double quotes)
#   - unquoted: any run of non-whitespace characters
# Anchored on left so we never confuse --no-deprecate or other suffixes.
_DEPRECATE_VALUE_RE = re.compile(
    r"(?:^|\s)--deprecate=(?:'([^']*)'|\"([^\"]*)\"|(\S+))",
)
# Bare --deprecate flag — must NOT be followed by '=' (otherwise the value form matches)
# and must NOT be preceded by '--no-' (otherwise --no-deprecate matches).
_DEPRECATE_BARE_RE = re.compile(
    r"(?:^|\s)--deprecate(?:\s|$)",
)
# --no-deprecate flag — explicit negation; overrides any --deprecate occurrence.
_NO_DEPRECATE_RE = re.compile(
    r"(?:^|\s)--no-deprecate(?:\s|$)",
)


def parse_deprecate_args(arguments: str) -> tuple[bool, str]:
    """Parse the $ARGUMENTS string for ``--deprecate`` / ``--no-deprecate`` flags.

    Args:
        arguments: Raw $ARGUMENTS string from the caller.

    Returns:
        Tuple ``(deprecate, decorator)`` where ``deprecate`` is ``True`` when
        ``--deprecate`` (with or without value) is present, ``False`` when
        ``--no-deprecate`` is present or no flag is present at all; ``decorator``
        is the raw value after ``--deprecate=`` with surrounding quotes stripped,
        or the empty string when the bare flag or no flag was used.

    Behaviour notes:
        * ``--no-deprecate`` always wins over ``--deprecate`` — explicit negation
          takes precedence regardless of order.
        * Only the **first** ``--deprecate=<value>`` occurrence supplies the
          decorator string; later occurrences are ignored.

    Examples:
        >>> parse_deprecate_args("--deprecate")
        (True, '')
        >>> parse_deprecate_args("--deprecate=@deprecated")
        (True, '@deprecated')
        >>> parse_deprecate_args("--deprecate='@deprecated(target=bar)'")
        (True, '@deprecated(target=bar)')
        >>> parse_deprecate_args('--deprecate="@deprecated_class(target=Bar)"')
        (True, '@deprecated_class(target=Bar)')
        >>> parse_deprecate_args("--no-deprecate")
        (False, '')
        >>> parse_deprecate_args("")
        (False, '')
        >>> parse_deprecate_args("--dry-run --since 1.0")
        (False, '')
        >>> parse_deprecate_args("--deprecate --no-deprecate")
        (False, '')
    """
    # Explicit negation wins regardless of any --deprecate presence.
    if _NO_DEPRECATE_RE.search(arguments):
        return False, ""

    value_match = _DEPRECATE_VALUE_RE.search(arguments)
    if value_match is not None:
        # Exactly one of the three capture groups matched.
        decorator = next(group for group in value_match.groups() if group is not None)
        return True, decorator

    if _DEPRECATE_BARE_RE.search(arguments):
        return True, ""

    return False, ""


def format_shell_assignments(deprecate: bool, decorator: str) -> str:
    """Render parsed values as shell assignments suitable for ``eval``.

    Retained as a pure helper for tests and external consumers.
    ``main()`` no longer calls this — it writes raw values to temp files instead.

    Args:
        deprecate: Whether ``--deprecate`` was present (or absent / negated).
        decorator: The decorator value after ``--deprecate=`` (empty when not supplied).

    Returns:
        Two-line string with ``DEPRECATE=`` and ``DEPRECATE_DECORATOR=`` assignments.
        Both values are passed through :func:`shlex.quote` so the caller can safely
        ``eval`` the output even when the decorator contains spaces, quotes, or
        shell metacharacters.

    Examples:
        >>> format_shell_assignments(True, "")
        "DEPRECATE=true\\nDEPRECATE_DECORATOR=''"
        >>> format_shell_assignments(True, "@deprecated(target=bar)")
        "DEPRECATE=true\\nDEPRECATE_DECORATOR='@deprecated(target=bar)'"
        >>> format_shell_assignments(False, "")
        "DEPRECATE=false\\nDEPRECATE_DECORATOR=''"
    """
    deprecate_str = "true" if deprecate else "false"
    return f"DEPRECATE={deprecate_str}\nDEPRECATE_DECORATOR={shlex.quote(decorator)}"


def _write_temp_vars(deprecate: bool, decorator: str) -> None:
    """Write DEPRECATE and DEPRECATE_DECORATOR to temp files for ``cat``-based reads.

    Writes raw (unquoted) values — no shell quoting needed since callers assign
    via ``VAR=$(cat ...)`` rather than ``eval``.

    Args:
        deprecate: Whether ``--deprecate`` flag was present.
        decorator: Raw decorator string (empty when bare flag or absent).
    """
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    Path(tmpdir, "codemap-deprecate-flag").write_text("true" if deprecate else "false", encoding="utf-8")
    Path(tmpdir, "codemap-deprecate-decorator").write_text(decorator, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse ``--arguments`` payload, write to temp files, return 0.

    Args:
        argv: Optional argv override for testing. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (always 0 — never fails on input).
    """
    parser = argparse.ArgumentParser(
        description="Extract --deprecate flag and optional decorator value from $ARGUMENTS.",
    )
    parser.add_argument(
        "--arguments",
        default="",
        help="Raw $ARGUMENTS string from the caller.",
    )
    args = parser.parse_args(argv)
    deprecate, decorator = parse_deprecate_args(args.arguments)
    _write_temp_vars(deprecate, decorator)
    return 0


if __name__ == "__main__":
    sys.exit(main())
