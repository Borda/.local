#!/usr/bin/env python3
"""Parse oss:resolve $ARGUMENTS, emit shell variable assignments for eval.

Usage (Claude Code plugin — ``CLAUDE_PLUGIN_ROOT`` set automatically)::

    eval "$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.py" "$ARGUMENTS")"

Emits four shell-quoted variable assignments:

- ``PR_NUMBER`` — extracted PR number (bare digits or ``#N``); empty otherwise
- ``PR_URL`` — full GitHub PR URL; empty otherwise
- ``MODE`` — one of ``pr``, ``pr+report``, ``report``, ``comment-dispatch``
- ``ARGUMENTS`` — original input; leading ``#`` stripped only for ``comment-dispatch``

Match order (PR/URL/report tried before any string mutation, so prompts like
``#42 looks wrong`` still route to comment-dispatch rather than misroute):

1. PR number (with optional leading ``#`` and optional trailing ``report``)
2. GitHub PR URL (with optional trailing ``report``)
3. Bare ``report``
4. Otherwise comment-dispatch (strip exactly one leading ``#``)
"""

from __future__ import annotations

import re
import shlex
import sys
from typing import Final

_PR_NUMBER_RE: Final = re.compile(r"^\s*#?(\d+)(\s+report)?\s*$")
_PR_URL_RE: Final = re.compile(r"^\s*(https://github\.com/\S+?)(\s+report)?\s*$")
_BARE_REPORT_RE: Final = re.compile(r"^\s*report\s*$")


def parse_resolve_args(arguments: str) -> dict[str, str]:
    """Parse oss:resolve arguments into a dict of shell-variable values.

    >>> parse_resolve_args("42") == {
    ...     "PR_NUMBER": "42", "PR_URL": "", "MODE": "pr", "ARGUMENTS": "42",
    ... }
    True
    >>> parse_resolve_args("#42 report") == {
    ...     "PR_NUMBER": "42", "PR_URL": "", "MODE": "pr+report", "ARGUMENTS": "#42 report",
    ... }
    True
    >>> parse_resolve_args("https://github.com/owner/repo/pull/7") == {
    ...     "PR_NUMBER": "", "PR_URL": "https://github.com/owner/repo/pull/7",
    ...     "MODE": "pr", "ARGUMENTS": "https://github.com/owner/repo/pull/7",
    ... }
    True
    >>> parse_resolve_args("#42 looks wrong") == {
    ...     "PR_NUMBER": "", "PR_URL": "", "MODE": "comment-dispatch",
    ...     "ARGUMENTS": "42 looks wrong",
    ... }
    True
    """
    pr_number = ""
    pr_url = ""
    mode = ""
    out_args = arguments

    m = _PR_NUMBER_RE.match(arguments)
    if m:
        pr_number = m.group(1)
        mode = "pr+report" if m.group(2) else "pr"
    else:
        m = _PR_URL_RE.match(arguments)
        if m:
            pr_url = m.group(1)
            mode = "pr+report" if m.group(2) else "pr"
        elif _BARE_REPORT_RE.match(arguments):
            mode = "report"
        else:
            # Only now strip a single leading '#'; comment dispatch may carry it
            # as a Markdown header anchor.
            if out_args.startswith("#"):
                out_args = out_args[1:]
            mode = "comment-dispatch"

    return {
        "PR_NUMBER": pr_number,
        "PR_URL": pr_url,
        "MODE": mode,
        "ARGUMENTS": out_args,
    }


def _emit(parsed: dict[str, str]) -> str:
    """Render parsed dict as newline-separated ``VAR=value`` shell assignments."""
    return "\n".join(f"{key}={shlex.quote(value)}" for key, value in parsed.items())


def main(argv: list[str]) -> int:
    arguments = " ".join(argv)
    parsed = parse_resolve_args(arguments)
    print(_emit(parsed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
