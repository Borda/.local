#!/usr/bin/env python
"""extract_diff_impact_qnames.py — extract module::fn qnames from codemap-py diff-impact JSON.

Usage::

    codemap-py query diff-impact --diff-file - < pr.diff \\
        | python extract_diff_impact_qnames.py [--cap N]

Reads ``codemap-py query diff-impact``'s JSON output from stdin and extracts the
``changed_symbols`` qname list diff-impact already derived per changed module — no
separate diff-hunk parsing needed here, diff-impact did that internally. Dedupes
preserving first-seen order, caps to ``--cap`` (default 12) to bound the downstream
per-qname ``fn-rdeps``/``fn-blast`` query loop cost on large PRs. Prints one qname per
line to stdout, feeding a plain ``while IFS= read -r`` battery-loop.

diff-impact itself only reports a ``caller_count`` per changed symbol (a number); the
caller-list detail (who actually calls it) is what ``fn-rdeps``/``fn-blast`` add, and
what the FN benchmark series measured the win on — this script is the glue that lets
a caller reuse diff-impact's own qname derivation instead of re-deriving it.

Never fails hard: any read/parse problem (empty stdin, non-JSON, unexpected shape)
yields an empty qname list, exit 0 — matches the fail-open convention of the codemap
fragment this feeds (``2>/dev/null`` throughout, no fatal exits).
"""

from __future__ import annotations

import argparse
import json
import sys


def extract_qnames(diff_impact_json: str, cap: int = 12) -> list[str]:
    """Extract deduplicated, order-preserved changed-symbol qnames, capped.

    Args:
        diff_impact_json: raw JSON string from ``codemap-py query diff-impact``.
        cap: max qnames to return (bounds downstream fn-rdeps/fn-blast query cost).

    Returns:
        ``module::fn`` qname strings, first-seen order, length at most ``cap``.

    Examples:
        >>> payload = '{"changed_modules": [{"changed_symbols": ["a::f", "a::g"]}, {"changed_symbols": ["a::f", "b::h"]}]}'
        >>> extract_qnames(payload, cap=10)
        ['a::f', 'a::g', 'b::h']
        >>> extract_qnames(payload, cap=2)
        ['a::f', 'a::g']
        >>> extract_qnames('{"changed_modules": []}')
        []
        >>> extract_qnames('not json')
        []
        >>> extract_qnames('')
        []
    """
    try:
        data = json.loads(diff_impact_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    modules = data.get("changed_modules", [])
    if not isinstance(modules, list):
        return []
    seen: dict[str, None] = {}
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        for qname in mod.get("changed_symbols", []) or []:
            if isinstance(qname, str) and qname not in seen:
                seen[qname] = None
    return list(seen)[:cap]


def main(argv: list[str]) -> int:
    """Read diff-impact JSON from stdin, print capped qname list, one per line.

    Args:
        argv: raw argv tokens (``sys.argv[1:]``).

    Returns:
        Always ``0`` — fail-open, prints nothing on any parse problem.
    """
    parser = argparse.ArgumentParser(
        prog="extract_diff_impact_qnames.py",
        description="Extract module::fn qnames from codemap-py diff-impact JSON (stdin), one per line.",
    )
    parser.add_argument("--cap", type=int, default=12, help="max qnames to emit (default 12)")
    args = parser.parse_args(argv)
    raw = sys.stdin.read()
    for qname in extract_qnames(raw, cap=args.cap):
        print(qname)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
