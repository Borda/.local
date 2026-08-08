#!/usr/bin/env python3
"""Reconstruct per-session token spend from Claude Code transcripts.

Splits each session by main-loop vs sidechain and by model tier, then prices it.
Answers "where did this session's money go" at the coarsest useful grain.

Known blind spot: subagent token usage does not appear in the parent transcript --
sessions that spawned agents show zero sidechain rows, so the reported figure is a
main-loop floor. On one measured review the gap was ~55% of the true bill. See
.plans/active/todo_efficiency-audit-remainder.md item 11.

Usage:
    python debugging/session_cost.py ~/.claude/projects/<slug>/<id>.jsonl
    python debugging/session_cost.py ~/.claude/projects/<slug>/     # whole project
"""

from __future__ import annotations

import argparse
import collections
import sys

from _usage import PRICES, Session, parse, tier, transcripts


def bucket(calls: list) -> dict[tuple[str, str], collections.Counter]:
    """Group deduplicated calls into (main|sidechain, price tier) buckets.

    Splitting on both axes matters: a session may run Opus in the main loop and Sonnet
    for a consolidator, and pricing the whole thing at one rate misattributes the spend.

        >>> from _usage import Call
        >>> calls = [
        ...     Call("m1", "claude-opus-5", {"output_tokens": 100, "cache_read_input_tokens": 900}),
        ...     Call("m2", "claude-opus-5", {"output_tokens": 50}),
        ...     Call("m3", "claude-haiku-4-5", {"output_tokens": 7}, sidechain=True),
        ... ]
        >>> got = bucket(calls)
        >>> sorted(got)
        [('main', 'opus'), ('sidechain', 'haiku')]
        >>> got[('main', 'opus')]["out"], got[('main', 'opus')]["cr"]
        (150, 900)
        >>> got[('sidechain', 'haiku')]["out"]
        7
        >>> bucket([])
        {}
    """
    buckets: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    for call in calls:
        key = ("sidechain" if call.sidechain else "main", tier(call.model))
        buckets[key]["in"] += call.usage.get("input_tokens", 0)
        buckets[key]["out"] += call.output
        buckets[key]["cw"] += call.cache_write
        buckets[key]["cr"] += call.cache_read
    return dict(buckets)


def report(session: Session, top_tools: int) -> None:
    """Print one session's cost breakdown to stdout."""
    buckets = bucket(session.calls)
    tools: collections.Counter = collections.Counter()
    for call in session.calls:
        tools.update(call.tools)

    print(f"\n=== {session.path.name}   [{session.project}]")
    cmds = ", ".join(f"{k}×{v}" for k, v in session.commands.items() if k.startswith("/"))
    if cmds:
        print(f"  commands: {cmds}")

    total = 0.0
    for (side, tr), counter in sorted(buckets.items()):
        p_in, p_out, p_cw, p_cr = PRICES[tr]
        line_cost = (
            counter["in"] * p_in + counter["out"] * p_out + counter["cw"] * p_cw + counter["cr"] * p_cr
        ) / 1_000_000
        total += line_cost
        print(
            f"  {side:9s} {tr:7s} in={counter['in']:>8,} out={counter['out']:>9,} "
            f"cache_w={counter['cw']:>11,} cache_r={counter['cr']:>13,}  ${line_cost:>9,.2f}"
        )

    calls = len(session.calls)
    side_calls = sum(1 for c in session.calls if c.sidechain)
    print(f"  API calls: {calls} (main {calls - side_calls}, sidechain {side_calls})   TOTAL ${total:,.2f}")
    if session.agent_count:
        spawned = ", ".join(f"{k}×{v}" for k, v in sorted(session.agents.items(), key=lambda kv: -kv[1]))
        print(f"  agents spawned: {session.agent_count} — {spawned}")
        if not side_calls:
            print("  ⚠ zero sidechain rows — subagent spend is NOT in this file; total is a main-loop floor")
    if top_tools:
        print(f"  top tools: {', '.join(f'{n}={c}' for n, c in tools.most_common(top_tools))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="transcript files, or project dirs to recurse")
    parser.add_argument("--top-tools", type=int, default=6, help="how many tool names to list (0 to skip)")
    parser.add_argument("--min-cost", type=float, default=0.0, help="skip sessions under this USD total")
    args = parser.parse_args(argv)

    shown = 0
    for path in transcripts(args.paths):
        try:
            session = parse(path)
        except OSError as exc:
            print(f"  ! {path}: {exc}", file=sys.stderr)
            continue
        if not session.calls or session.total_cost < args.min_cost:
            continue
        report(session, args.top_tools)
        shown += 1
    if not shown:
        print("no sessions matched", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
