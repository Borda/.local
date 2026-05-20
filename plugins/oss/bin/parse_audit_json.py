#!/usr/bin/env python3
"""parse_audit_json.py — summarize pip-audit JSON output as deps/vulns counts.

Usage:
    pip-audit --format=json | python "${CLAUDE_PLUGIN_ROOT}/bin/parse_audit_json.py"

Reads a pip-audit JSON document from stdin and prints a single-line summary of
the form ``N deps, M vulns``.  Extracted from run_audit_checks.sh inline
``python -c`` block (F-09 in security audit 2026-05-19) to satisfy the
project Check 23e policy prohibiting inline ``python -c`` snippets.

Exit codes:
    0  on success
    1  on stdin read error or JSON parse error
"""

from __future__ import annotations

import json
import sys
from typing import Any


def summarize(payload: dict[str, Any]) -> str:
    """Render a pip-audit JSON payload as a ``N deps, M vulns`` summary line.

    Args:
        payload: Parsed pip-audit JSON; expects a top-level ``dependencies``
            list, each entry containing a ``vulns`` list.

    Returns:
        Single-line summary string.

    Examples:
        >>> summarize({"dependencies": []})
        '0 deps, 0 vulns'
        >>> summarize({"dependencies": [{"vulns": []}, {"vulns": [{}, {}]}]})
        '2 deps, 2 vulns'
        >>> summarize({"dependencies": [{"vulns": [{}]}]})
        '1 deps, 1 vulns'
    """
    deps = payload.get("dependencies", [])
    n_deps = len(deps)
    n_vulns = sum(len(dep.get("vulns", [])) for dep in deps)
    return f"{n_deps} deps, {n_vulns} vulns"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — read JSON from stdin, print summary.

    Args:
        argv: Argument list override for testing. Unused; pip-audit JSON
            arrives via stdin.

    Returns:
        Exit code: 0 on success, 1 on parse error.

    Examples:
        No doctest — requires stdin; covered by pytest with monkeypatch.
    """
    _ = sys.argv[1:] if argv is None else argv  # no positional args used
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"parse_audit_json: invalid JSON on stdin: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"parse_audit_json: stdin read error: {e}", file=sys.stderr)
        return 1

    print(summarize(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
