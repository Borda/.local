#!/usr/bin/env python3
"""Per-call cost profile for a single Claude Code transcript.

Answers three questions a session total cannot:
  1. How much of the spend is context re-sent every turn (cache read)?
  2. How much is cache rebuild (cache write, 12.5x the read rate) and which calls caused it?
  3. How does context grow over the session?

Cache write concentrates in cold starts. On one measured review, two calls -- session
open and a mid-run /clear -- carried 74% of all cache-write tokens. That is why the
guidance is never to /clear mid-run: the rebuild costs write-rate tokens and returns a
context of the same size, whereas /compact pays the same rebuild once and then shrinks
every later turn.

Usage:
    python debugging/turn_profile.py ~/.claude/projects/<slug>/<id>.jsonl
    python debugging/turn_profile.py <file> --top 15 --every 5
"""

from __future__ import annotations

import argparse
import sys

from _usage import PRICES, parse, tier, transcripts


def totals(calls: list) -> tuple[int, int, int]:
    """Sum (cache_read, cache_write, output) over deduplicated calls.

    >>> from _usage import Call
    >>> calls = [
    ...     Call("m1", "opus", {"cache_read_input_tokens": 100, "output_tokens": 5}),
    ...     Call("m2", "opus", {"cache_creation_input_tokens": 40, "output_tokens": 7}),
    ... ]
    >>> totals(calls)
    (100, 40, 12)
    >>> totals([])
    (0, 0, 0)
    """
    return (
        sum(c.cache_read for c in calls),
        sum(c.cache_write for c in calls),
        sum(c.output for c in calls),
    )


def cold_start_share(calls: list) -> float:
    """Fraction of cache-write tokens spent on cold starts (calls with no cache read).

    A cold start is a full context rebuild: session open, or a mid-run ``/clear``.
    On a measured review two such calls carried 74% of all write tokens, which is the
    evidence behind "never ``/clear`` mid-run".

        >>> from _usage import Call
        >>> cold = Call("m1", "opus", {"cache_creation_input_tokens": 180_000})
        >>> warm = Call("m2", "opus", {"cache_creation_input_tokens": 20_000,
        ...                            "cache_read_input_tokens": 150_000})
        >>> round(cold_start_share([cold, warm]), 2)
        0.9
        >>> cold_start_share([warm])
        0.0

    No cache writes at all is reported as zero rather than dividing by zero:

        >>> cold_start_share([])
        0.0
    """
    written = sum(c.cache_write for c in calls)
    if not written:
        return 0.0
    return sum(c.cache_write for c in calls if c.cache_read == 0) / written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="one transcript file")
    parser.add_argument("--top", type=int, default=10, help="how many cache-rebuild calls to list")
    parser.add_argument("--every", type=int, default=10, help="context-growth sampling interval")
    args = parser.parse_args(argv)

    paths = transcripts([args.path])
    if not paths:
        print(f"no transcript at {args.path}", file=sys.stderr)
        return 1
    session = parse(paths[0])
    calls = session.calls
    if not calls:
        print("transcript has no usage rows", file=sys.stderr)
        return 1

    # price at the dominant tier; mixed-model sessions are rare and flagged below
    tiers = {tier(c.model) for c in calls}
    _, p_out, p_cw, p_cr = PRICES[max(tiers, key=lambda t: PRICES[t][1])]

    cr, cw, out = totals(calls)
    cost_cr, cost_cw, cost_out = cr * p_cr / 1e6, cw * p_cw / 1e6, out * p_out / 1e6
    total = cost_cr + cost_cw + cost_out or 1.0

    print(f"{session.path.name}   [{session.project}]   {len(calls)} API calls (deduped by message id)")
    if len(tiers) > 1:
        print(f"  ⚠ mixed model tiers {sorted(tiers)} — priced at the most expensive")
    cmds = ", ".join(f"{k}×{v}" for k, v in session.commands.items() if k.startswith("/"))
    if cmds:
        print(f"  commands: {cmds}")
    print()
    print(f"  cache_read  {cr:>13,}  ${cost_cr:>9,.2f}  {cost_cr / total:5.1%}   avg ctx/call {cr // len(calls):,}")
    print(f"  cache_write {cw:>13,}  ${cost_cw:>9,.2f}  {cost_cw / total:5.1%}")
    print(f"  output      {out:>13,}  ${cost_out:>9,.2f}  {cost_out / total:5.1%}")
    print(f"  {'TOTAL':11s} {'':>13s}  ${total:>9,.2f}")

    print(f"\n  top {args.top} calls by cache_write (rebuilds — {p_cw / p_cr:.1f}x the read rate):")
    ranked = sorted(enumerate(calls), key=lambda kv: -kv[1].cache_write)[: args.top]
    for i, call in ranked:
        share = call.cache_write * p_cw / 1e6
        tools = ",".join(call.tools) or "-"
        print(
            f"    call {i:>4}  cw={call.cache_write:>9,} (${share:>6,.2f})  "
            f"cr={call.cache_read:>10,}  out={call.output:>6,}  {tools[:44]}"
        )
    if cw:
        share = cold_start_share(calls)
        cold = int(round(share * cw))
        print(f"    cold starts (cache_read == 0) account for {cold:,} write tok — {share:.0%} of all rebuilds")

    print(f"\n  context growth (cache_read per call, every {args.every}):")
    for i in range(0, len(calls), args.every):
        marker = "  ← cold start" if calls[i].cache_read == 0 else ""
        print(f"    call {i:>4}  ctx={calls[i].cache_read:>10,}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
