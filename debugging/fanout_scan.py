#!/usr/bin/env python3
"""Rank sessions across all projects by agent fan-out and cost.

Use this to find *which* skills actually drive spend before optimising any of them.
Doing that once redirected a whole optimisation pass: /oss:review looked like the
expensive skill, but /oss:resolve had run 102 times to review's 70, and the research
plugin -- which had been slated for the same treatment -- had been invoked once, ever.

Usage:
    python debugging/fanout_scan.py ~/.claude/projects
    python debugging/fanout_scan.py ~/.claude/projects --sort cost --limit 15
    python debugging/fanout_scan.py ~/.claude/projects --commands   # per-skill totals
"""

from __future__ import annotations

import argparse

from _usage import Session, parse, transcripts

SORT_KEYS = {
    "agents": lambda s: -s.agent_count,
    "cost": lambda s: -s.total_cost,
    "calls": lambda s: -len(s.calls),
    "ctx": lambda s: -(sum(c.cache_read for c in s.calls) // max(len(s.calls), 1)),
}


def aggregate_commands(sessions: list[Session]) -> dict[str, dict[str, float]]:
    """Aggregate runs, agent spawns and cost per slash command.

    Built-ins (``/clear``, ``/model``) are dropped -- only ``/plugin:skill`` style
    entries are ranked. A session invoking several commands attributes its whole cost
    and spawn count to *each* of them, so the money column is an upper bound: useful
    for ranking which skill to optimise, never for summing into a grand total.

        >>> class S:  # minimal stand-in for a parsed Session
        ...     def __init__(self, commands, agents, cost):
        ...         self.commands, self._a, self._c = commands, agents, cost
        ...     agent_count = property(lambda self: self._a)
        ...     total_cost = property(lambda self: self._c)
        >>> got = aggregate_commands([
        ...     S({"/oss:review": 1, "/oss:resolve": 2, "/clear": 3}, 11, 20.0),
        ...     S({"/oss:resolve": 1}, 4, 5.0),
        ... ])
        >>> sorted(got)
        ['/oss:resolve', '/oss:review']
        >>> got["/oss:resolve"]["runs"], got["/oss:resolve"]["agents"]
        (3, 15)

    Both sessions' full cost lands on ``/oss:resolve`` because both invoked it:

        >>> got["/oss:resolve"]["cost"]
        25.0
        >>> aggregate_commands([])
        {}
    """
    out: dict[str, dict[str, float]] = {}
    for session in sessions:
        for name, count in session.commands.items():
            if not name.startswith("/") or ":" not in name:
                continue
            row = out.setdefault(name, {"runs": 0, "agents": 0, "cost": 0.0})
            row["runs"] += count
            row["agents"] += session.agent_count
            row["cost"] += session.total_cost
    return out


def print_command_totals(sessions: list[Session]) -> None:
    """Render :func:`aggregate_commands` as a ranked table."""
    totals = aggregate_commands(sessions)
    print(f"\n{'command':28s} {'runs':>6s} {'agents':>8s} {'session $ (upper bound)':>24s}")
    for name, row in sorted(totals.items(), key=lambda kv: -kv[1]["runs"]):
        print(f"{name:28s} {row['runs']:>6} {row['agents']:>8} {row['cost']:>24,.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="project dirs (usually ~/.claude/projects)")
    parser.add_argument("--sort", choices=sorted(SORT_KEYS), default="agents")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--commands", action="store_true", help="also print per-command totals")
    parser.add_argument("--min-agents", type=int, default=0, help="skip sessions below this spawn count")
    args = parser.parse_args(argv)

    sessions: list[Session] = []
    for path in transcripts(args.paths):
        try:
            session = parse(path)
        except OSError:
            continue
        if session.commands and session.agent_count >= args.min_agents:
            sessions.append(session)

    if not sessions:
        print("no sessions with slash commands found")
        return 1

    sessions.sort(key=SORT_KEYS[args.sort])
    header = f"{'project':20s} {'session':10s} {'calls':>6s} {'agents':>7s} {'main $':>9s} {'avg ctx':>9s}  commands"
    print(header)
    for session in sessions[: args.limit]:
        cmds = ",".join(k for k in session.commands if k.startswith("/"))[:38]
        avg_ctx = sum(c.cache_read for c in session.calls) // max(len(session.calls), 1)
        print(
            f"{session.project[:20]:20s} {session.path.stem[:10]:10s} {len(session.calls):>6} "
            f"{session.agent_count:>7} {session.total_cost:>9,.2f} {avg_ctx:>9,}  {cmds}"
        )

    total = sum(s.total_cost for s in sessions)
    print(f"\n{len(sessions)} sessions scanned — main-loop total ${total:,.2f} (subagent spend not in transcripts)")
    if args.commands:
        print_command_totals(sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
