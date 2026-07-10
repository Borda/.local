#!/usr/bin/env python3
"""build_triage_batch.py — turn thread-extracted identifiers into a scan-query batch spec.

consumers: analyse/modes/codemap-signals.md

Reads a candidate file (one identifier per line, written by oss:analyse thread
triage) and emits a JSON array of scan-query batch queries: dotted module-shaped
identifiers map to ``rdeps`` (with ``--exclude-tests``); bare symbol names map to
an anchored ``find-symbol`` lookup. The resulting file is fed to
``scan-query batch`` for a one-process existence check that flags stale symbols.
Prints the number of queries written to stdout so the caller can skip the
``scan-query`` call when the batch is empty — no second inline interpreter call.

Usage:
    N=$(python build_triage_batch.py CANDIDATE_FILE OUT_FILE)

Exit codes:
    0  on success (OUT_FILE written, even when empty → ``[]``)
    1  on missing argument or I/O error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def build_queries(identifiers: list[str]) -> list[dict[str, object]]:
    """Map extracted identifiers to scan-query batch entries.

    A dotted identifier whose first segment is a valid Python name is treated as a
    module and existence-checked with ``rdeps``; anything else is treated as a bare
    symbol and checked with an anchored ``find-symbol`` regex.

    Args:
        identifiers: Candidate module/symbol names extracted from a thread.

    Returns:
        List of ``{"cmd", "args"}`` dicts suitable for ``scan-query batch``.

    Examples:
        >>> build_queries(["a.b.c", "MyClass"])
        [{'cmd': 'rdeps', 'args': ['a.b.c', '--exclude-tests']}, {'cmd': 'find-symbol', 'args': ['^MyClass$', '--limit', '1']}]
        >>> build_queries(["  ", "x"])
        [{'cmd': 'find-symbol', 'args': ['^x$', '--limit', '1']}]
    """
    queries: list[dict[str, object]] = []
    for raw in identifiers:
        ident = raw.strip()
        if not ident:
            continue
        if "." in ident and ident.split(".")[0].isidentifier():
            queries.append({"cmd": "rdeps", "args": [ident, "--exclude-tests"]})
        else:
            queries.append({"cmd": "find-symbol", "args": [f"^{ident}$", "--limit", "1"]})
    return queries


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("Usage: build_triage_batch.py CANDIDATE_FILE OUT_FILE", file=sys.stderr)
        return 1
    cand_path, out_path = Path(args[0]), Path(args[1])
    try:
        lines = cand_path.read_text().splitlines()
    except OSError as exc:
        print(f"! build_triage_batch: cannot read {cand_path}: {exc}", file=sys.stderr)
        return 1
    queries = build_queries(lines)
    try:
        out_path.write_text(json.dumps(queries))
    except OSError as exc:
        print(f"! build_triage_batch: cannot write {out_path}: {exc}", file=sys.stderr)
        return 1
    print(len(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
