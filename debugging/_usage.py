#!/usr/bin/env python3
"""Shared transcript parsing for the cost-analysis scripts in this directory.

Claude Code writes one JSONL row per *content block*, so a single assistant message
with three blocks appears three times, each carrying the same ``message.id`` and the
same ``usage`` object. Summing rows therefore triple-counts: an early measurement of
one review session read $61.21 where the true figure was $20.56. Everything here
deduplicates by ``message.id`` before counting, and callers should too.

Prices are public list rates in USD per million tokens. The transcript records tokens
only -- pricing is an assumption layered on top, and effective plan rates may differ.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

# (input, output, cache_write_5m, cache_read) USD per million tokens
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus": (15.0, 75.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku": (1.0, 5.0, 1.25, 0.10),
}

COMMAND_RE = re.compile(r"<command-name>([^<]+)</command-name>")


def tier(model: str) -> str:
    """Map a model id onto its price tier.

    Matches on substring so dated and suffixed ids resolve. An unrecognised id prices
    as the most expensive tier rather than the cheapest -- an overstated cost prompts
    investigation, an understated one hides the problem being measured.

        >>> tier("claude-opus-5[1m]")
        'opus'
        >>> tier("claude-haiku-4-5-20251001")
        'haiku'
        >>> tier("some-unreleased-model")
        'opus'
    """
    for name in PRICES:
        if name in model:
            return name
    return "opus"


def cost(usage: dict, model: str = "opus") -> float:
    """Price one usage object in USD.

    Missing keys count as zero, so partial usage objects price without special casing.

        >>> round(cost({"output_tokens": 1_000_000}), 2)
        75.0
        >>> round(cost({"cache_read_input_tokens": 1_000_000}), 2)
        1.5
        >>> round(cost({"cache_creation_input_tokens": 1_000_000}), 2)
        18.75

    Cache writes cost 12.5x cache reads, which is why a mid-run cache rebuild
    dominates a session total:

        >>> round(cost({"cache_creation_input_tokens": 1}) / cost({"cache_read_input_tokens": 1}), 3)
        12.5

    Tier selection follows the model argument:

        >>> round(cost({"output_tokens": 1_000_000}, "claude-haiku-4-5"), 2)
        5.0
        >>> cost({})
        0.0
    """
    p_in, p_out, p_cw, p_cr = PRICES[tier(model)]
    return (
        usage.get("input_tokens", 0) * p_in
        + usage.get("output_tokens", 0) * p_out
        + usage.get("cache_creation_input_tokens", 0) * p_cw
        + usage.get("cache_read_input_tokens", 0) * p_cr
    ) / 1_000_000


@dataclass
class Call:
    """One deduplicated assistant API call."""

    message_id: str
    model: str
    usage: dict
    tools: list[str] = field(default_factory=list)
    sidechain: bool = False

    @property
    def cache_read(self) -> int:
        """Context size re-sent on this call."""
        return self.usage.get("cache_read_input_tokens", 0)

    @property
    def cache_write(self) -> int:
        return self.usage.get("cache_creation_input_tokens", 0)

    @property
    def output(self) -> int:
        return self.usage.get("output_tokens", 0)


@dataclass
class Session:
    """A parsed transcript: deduplicated calls plus the commands that drove them."""

    path: pathlib.Path
    calls: list[Call]
    commands: dict[str, int]
    agents: dict[str, int]

    @property
    def project(self) -> str:
        return self.path.parent.name.replace("-Users-jirka-Workspace-", "")

    @property
    def total_cost(self) -> float:
        return sum(cost(c.usage, c.model) for c in self.calls)

    @property
    def agent_count(self) -> int:
        return sum(self.agents.values())

    def totals(self) -> tuple[int, int, int]:
        """(cache_read, cache_write, output) summed over deduplicated calls."""
        return (
            sum(c.cache_read for c in self.calls),
            sum(c.cache_write for c in self.calls),
            sum(c.output for c in self.calls),
        )


def parse(path: pathlib.Path) -> Session:
    """Read one transcript, deduplicating usage rows by message id.

    Agent spawns are deduplicated by tool_use id for the same reason: the tool_use
    block is re-emitted on every row belonging to its message.
    """
    calls: dict[str, Call] = {}
    commands: dict[str, int] = {}
    agents: dict[str, int] = {}
    seen_tool_ids: set[str] = set()

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "<command-name>" in line:
                for name in COMMAND_RE.findall(line):
                    commands[name] = commands.get(name, 0) + 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            message = row.get("message") or {}
            blocks = [b for b in (message.get("content") or []) if isinstance(b, dict)]

            for block in blocks:
                if block.get("type") != "tool_use" or block.get("name") != "Agent":
                    continue
                tool_id = block.get("id")
                if tool_id in seen_tool_ids:
                    continue
                seen_tool_ids.add(tool_id)
                kind = (block.get("input") or {}).get("subagent_type", "?")
                agents[kind] = agents.get(kind, 0) + 1

            usage = message.get("usage") or {}
            if not usage:
                continue
            message_id = message.get("id") or f"anon-{len(calls)}"
            if message_id in calls:
                continue
            calls[message_id] = Call(
                message_id=message_id,
                model=message.get("model") or "unknown",
                usage=usage,
                tools=[b.get("name", "?") for b in blocks if b.get("type") == "tool_use"],
                sidechain=bool(row.get("isSidechain")),
            )

    return Session(path=path, calls=list(calls.values()), commands=commands, agents=agents)


def dedupe_usage(rows: list[tuple[str, dict]]) -> dict[str, dict]:
    """Keep the first usage object per message id, discarding repeats.

    This is the single most important step in the whole module. Claude Code emits one
    JSONL row per content block, all sharing a message id and the same usage object,
    so summing rows multiplies the answer by the average block count -- observed as a
    3x inflation ($20.56 read as $61.21) on a real review session.

        >>> rows = [("m1", {"output_tokens": 10}), ("m1", {"output_tokens": 10}),
        ...         ("m2", {"output_tokens": 5})]
        >>> kept = dedupe_usage(rows)
        >>> sorted(kept)
        ['m1', 'm2']
        >>> sum(u["output_tokens"] for u in kept.values())
        15

    Summing the raw rows instead would give 25 -- the bug this guards against.

        >>> dedupe_usage([])
        {}
    """
    kept: dict[str, dict] = {}
    for message_id, usage in rows:
        kept.setdefault(message_id, usage)
    return kept


def transcripts(roots: list[str]) -> list[pathlib.Path]:
    """Expand CLI arguments into transcript paths (files pass through, dirs recurse)."""
    found: list[pathlib.Path] = []
    for root in roots:
        path = pathlib.Path(root).expanduser()
        found.extend(sorted(path.rglob("*.jsonl")) if path.is_dir() else [path])
    return found
