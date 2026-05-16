#!/usr/bin/env python3
"""Parse oss:review $ARGUMENTS, emit shell variable assignments for eval.

Usage (Claude Code plugin — ``CLAUDE_PLUGIN_ROOT`` set automatically)::

    eval "$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/parse-review-args.py" "$ARGUMENTS")"

Emits five shell-quoted variable assignments:

- ``REPLY_MODE`` — ``true`` if ``--reply`` present; else ``false``
- ``CHALLENGE_ENABLED`` — ``false`` if ``--no-challenge`` present; else ``true``
- ``CODEMAP_ENABLED`` — ``true`` if ``--codemap`` present; else ``false``
- ``SEMBLE_ENABLED`` — ``true`` if ``--semble`` present; else ``false``
- ``CLEAN_ARGS`` — input with all matched flags removed, leading whitespace
  trimmed, and one leading ``#`` stripped (so both ``123`` and ``#123`` work)
"""

from __future__ import annotations

import shlex
import sys
from typing import Final

_FLAGS: Final[tuple[tuple[str, str, str, str], ...]] = (
    # (token, output_var, value_when_present, default_value)
    ("--reply", "REPLY_MODE", "true", "false"),
    ("--no-challenge", "CHALLENGE_ENABLED", "false", "true"),
    ("--codemap", "CODEMAP_ENABLED", "true", "false"),
    ("--semble", "SEMBLE_ENABLED", "true", "false"),
)


def parse_review_args(args: str) -> dict[str, str]:
    """Parse oss:review arguments into a dict of shell-variable values.

    >>> parse_review_args("123") == {
    ...     "REPLY_MODE": "false", "CHALLENGE_ENABLED": "true",
    ...     "CODEMAP_ENABLED": "false", "SEMBLE_ENABLED": "false",
    ...     "CLEAN_ARGS": "123",
    ... }
    True
    >>> parse_review_args("--reply 123")["REPLY_MODE"]
    'true'
    >>> parse_review_args("--no-challenge --codemap 42")["CHALLENGE_ENABLED"]
    'false'
    >>> parse_review_args("#123")["CLEAN_ARGS"]
    '123'
    """
    remaining = args
    result: dict[str, str] = {}
    for token, var, present_val, default_val in _FLAGS:
        if token in remaining:
            result[var] = present_val
            remaining = remaining.replace(token, "")
        else:
            result[var] = default_val

    # Trim leading whitespace, then strip a single leading '#'.
    remaining = remaining.lstrip()
    if remaining.startswith("#"):
        remaining = remaining[1:]

    result["CLEAN_ARGS"] = remaining
    return result


def _emit(parsed: dict[str, str]) -> str:
    """Render parsed dict as newline-separated ``VAR=value`` shell assignments."""
    order = ("REPLY_MODE", "CHALLENGE_ENABLED", "CODEMAP_ENABLED", "SEMBLE_ENABLED", "CLEAN_ARGS")
    return "\n".join(f"{key}={shlex.quote(parsed[key])}" for key in order)


def main(argv: list[str]) -> int:
    args = " ".join(argv)
    parsed = parse_review_args(args)
    print(_emit(parsed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
