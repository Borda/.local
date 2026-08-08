#!/usr/bin/env python3
"""detect-complexity.py — decide whether a judge program warrants the architect / Codex passes.

Prints "true" when the program names more than one scope file, declares
`agent_strategy: arch`, or mentions a cross-domain keyword; "false" otherwise.
A missing or unreadable program is a "simple" program, not an error — the judge steps
treat false as "skip the extra pass", which is the safe default when scope is unknown.

Usage: COMPLEX=$(python detect-complexity.py <program-path>)
Exit codes: 0 = verdict printed · 2 = missing <program-path> argument
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# [ \t\r\f\v], not \s: grep matches within a line, where POSIX [[:space:]] cannot include the
# newline that Python's \s would. \S is safe as-is for the same reason.
_WS = r"[ \t\r\f\v]"
_SCOPE_RE = re.compile(rf"^{_WS}*[-*]?{_WS}*\S+\.(py|ts|js|cpp|go|rs){_WS}*$")
_STRATEGY_RE = re.compile(rf"^.*agent_strategy:{_WS}*")
_CROSS_DOMAIN_RE = re.compile(
    r"cross.domain|multi.system|distributed|multiple.*component|pipeline.*stage",
    re.IGNORECASE,
)


def _lines(program: Path) -> list[str]:
    """Program lines without terminators; empty list when the file is missing or unreadable."""
    try:
        return program.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _strategy(lines: list[str]) -> str:
    """Value of the first `agent_strategy:` line, mirroring grep -m1 | sed | tr -d '\\r\\n'."""
    for line in lines:
        if "agent_strategy:" in line:
            # Greedy `.*` matches through the LAST occurrence on the line, as sed does.
            return _STRATEGY_RE.sub("", line).replace("\r", "").replace("\n", "")
    return ""


def main(argv: list[str]) -> int:
    program = argv[1] if len(argv) > 1 else ""
    if not program:
        print("detect-complexity: missing <program-path> argument", file=sys.stderr)
        return 2

    lines = _lines(Path(program))
    scope_count = sum(1 for line in lines if _SCOPE_RE.search(line))
    is_complex = scope_count > 1 or _strategy(lines) == "arch" or any(_CROSS_DOMAIN_RE.search(line) for line in lines)

    print("true" if is_complex else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
