#!/usr/bin/env python3
"""measure_demo_arms.py — derive measured per-arm cost + capped confidence for the demo A/B.

The demo's plain-vs-codemap A/B previously trusted each arm's *self-reported*
tool counts (the ``b``/``g``/``r``/``sq`` fields the arm agent returned). Self-report
is unverifiable — an arm can under- or over-count. This script replaces it with a
*measured* cost read from the telemetry shards the hooks already write:

- scan-query calls per arm come from ``cli_<session>.jsonl`` (``layer:"cli"`` records,
  written by ``_telemetry.py``); each record's ``cmd`` is one scan-query subcommand.
- Grep/Read/Glob calls and their *target volume* come from ``tools_<session>.jsonl``
  (``layer:"tool"`` records, written by ``log-tool-use.js``); each record's ``target``
  is the grep pattern / read path / glob pattern the call carried.

Each arm runs under its own Claude Code session, so the session id is the join key:
pass ``--plain-session`` and ``--codemap-session`` to attribute records to an arm.
Records whose session matches neither arm are ignored.

Cost is a *token proxy*, not a real token count (the Agent tool never exposes per-arm
token usage — see demo-notes.md caveat): a fixed per-call cost plus the target-string
volume (chars / 4). The constants are deliberately conservative and documented so the
proxy is reproducible across runs.

The report-header confidence is capped by the *correctness signal type* the caller
declares:

- ``ground_truth`` — the arm answers were scored against a pinned ground-truth set
  (psf/requests benchmark). Measured cost + real correctness → cap ``0.9``.
- ``agreement`` — no ground truth; arms only checked for cross-arm agreement, which is
  consistency, never accuracy. Cap ``0.7``.
- ``plumbing`` — telemetry wired but neither ground truth nor agreement available. Cap
  ``0.5``.

The reader helpers (``_read_jsonl``, ``_shard_paths``, ``_collect``) are imported from
``join_avoidance`` so the two telemetry consumers share one JSONL-parsing implementation.

Usage:
    python measure_demo_arms.py --logs .cache/codemap/logs \\
        --plain-session s-plain --codemap-session s-codemap --signal ground_truth
    python measure_demo_arms.py --logs LOGS --plain-session A --codemap-session B \\
        --signal agreement --json

Exit codes:
    0 — success (including "no records for either session")
    2 — bad arguments (missing --logs, a session id, or an unknown --signal)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Put this script's own bin/ dir on sys.path so the sibling join_avoidance import
# resolves whether the module is run directly, imported by a test's conftest, or
# collected standalone by ``pytest --doctest-modules`` (mirrors scan-query's guard).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from join_avoidance import _collect, _shard_paths  # noqa: E402 — needs the sys.path guard above

# Token-proxy constants. A scan-query call is one structural query returning a compact
# answer; a Grep/Read/Glob call fans out over the tree. The per-call weights below are a
# conservative flat proxy for the model's output-token cost of issuing and consuming each
# call; target volume (chars / 4) approximates the tokens spent stating the target.
SQ_CALL_TOKENS = 40
TOOL_CALL_TOKENS = 60
CHARS_PER_TOKEN = 4

# signal type → confidence cap. ground_truth measures real correctness; agreement measures
# only cross-arm consistency; plumbing means telemetry flowed but neither check was possible.
SIGNAL_CAPS: dict[str, float] = {
    "ground_truth": 0.9,
    "agreement": 0.7,
    "plumbing": 0.5,
}


@dataclass(frozen=True)
class ArmCost:
    """Measured cost of one A/B arm, read from the telemetry shards.

    Attributes:
        session: the arm's session id (join key into the shards).
        sq_calls: scan-query subcommand invocations (cli-layer records).
        tool_calls: Grep + Read + Glob invocations (tool-layer records).
        target_chars: total characters across every tool call's ``target`` string.
        tokens: the derived token proxy (see module docstring for the model).
    """

    session: str
    sq_calls: int
    tool_calls: int
    target_chars: int
    tokens: int


def _tokens(sq_calls: int, tool_calls: int, target_chars: int) -> int:
    """Return the token proxy for one arm's measured call counts and target volume.

    Args:
        sq_calls: scan-query subcommand invocations.
        tool_calls: Grep/Read/Glob invocations.
        target_chars: summed length of every tool call's target string.

    Returns:
        The integer token proxy: per-call weights plus target volume (chars / 4).

    Examples:
        >>> _tokens(0, 0, 0)
        0
        >>> _tokens(1, 0, 0)
        40
        >>> _tokens(0, 1, 40)
        70
    """
    return sq_calls * SQ_CALL_TOKENS + tool_calls * TOOL_CALL_TOKENS + target_chars // CHARS_PER_TOKEN


def measure_arm(session: str, cli_records: list[dict], tool_records: list[dict]) -> ArmCost:
    """Measure one arm's cost by filtering the shard records to its session.

    Args:
        session: the arm's session id.
        cli_records: parsed ``cli_*.jsonl`` records (each ``cmd`` = one scan-query call).
        tool_records: parsed ``tools_*.jsonl`` records (each ``target`` = one call target).

    Returns:
        The arm's :class:`ArmCost` (all counts zero when the session has no records).

    Examples:
        >>> cli = [{"layer": "cli", "session": "a", "cmd": "central"}]
        >>> tools = [{"layer": "tool", "session": "a", "tool": "Grep", "target": "import x"}]
        >>> cost = measure_arm("a", cli, tools)
        >>> cost.sq_calls, cost.tool_calls, cost.target_chars
        (1, 1, 8)
        >>> measure_arm("other", cli, tools).tokens
        0
    """
    sq_calls = sum(1 for r in cli_records if r.get("session") == session and r.get("cmd"))
    arm_tools = [r for r in tool_records if r.get("session") == session and r.get("tool")]
    tool_calls = len(arm_tools)
    target_chars = sum(len(str(r.get("target", ""))) for r in arm_tools)
    return ArmCost(
        session=session,
        sq_calls=sq_calls,
        tool_calls=tool_calls,
        target_chars=target_chars,
        tokens=_tokens(sq_calls, tool_calls, target_chars),
    )


def confidence_for(signal: str, both_arms_measured: bool) -> float:
    """Return the capped report-header confidence for a signal type.

    The cap comes from :data:`SIGNAL_CAPS`. When telemetry produced no measured
    records for at least one arm, the run is plumbing-only regardless of the
    declared signal, so it is capped at the ``plumbing`` ceiling.

    Args:
        signal: one of ``"ground_truth"``, ``"agreement"``, ``"plumbing"``.
        both_arms_measured: whether both arms yielded at least one measured call.

    Returns:
        The confidence cap for the effective signal type.

    Examples:
        >>> confidence_for("ground_truth", True)
        0.9
        >>> confidence_for("agreement", True)
        0.7
        >>> confidence_for("ground_truth", False)
        0.5
    """
    if not both_arms_measured:
        return SIGNAL_CAPS["plumbing"]
    return SIGNAL_CAPS[signal]


def _render(plain: ArmCost, codemap: ArmCost, signal: str, confidence: float) -> dict:
    """Assemble the result payload for both render paths.

    Args:
        plain: the plain arm's measured cost.
        codemap: the codemap arm's measured cost.
        signal: the effective signal type label.
        confidence: the capped confidence.

    Returns:
        A JSON-serialisable dict of per-arm costs, signal type, and confidence.
    """
    return {
        "signal_type": signal,
        "confidence": confidence,
        "plain": {
            "session": plain.session,
            "sq_calls": plain.sq_calls,
            "tool_calls": plain.tool_calls,
            "target_chars": plain.target_chars,
            "tokens": plain.tokens,
        },
        "codemap": {
            "session": codemap.session,
            "sq_calls": codemap.sq_calls,
            "tool_calls": codemap.tool_calls,
            "target_chars": codemap.target_chars,
            "tokens": codemap.tokens,
        },
        "token_delta": plain.tokens - codemap.tokens,
    }


def render_text(payload: dict) -> str:
    """Render the measured A/B result as a human-readable block (one ``print``).

    Args:
        payload: the dict from :func:`_render`.

    Returns:
        A multi-line summary naming per-arm measured token totals, the signal-type
        label, and the capped confidence.

    Examples:
        >>> p = {"signal_type": "agreement", "confidence": 0.7,
        ...      "plain": {"tokens": 300, "sq_calls": 0, "tool_calls": 4, "target_chars": 80},
        ...      "codemap": {"tokens": 120, "sq_calls": 2, "tool_calls": 0, "target_chars": 40},
        ...      "token_delta": 180}
        >>> "signal: agreement (measured)" in render_text(p)
        True
    """
    plain, codemap = payload["plain"], payload["codemap"]
    return "\n".join(
        [
            f"demo A/B measured cost — signal: {payload['signal_type']} (measured)",
            f"  plain   arm: {plain['tokens']} tokens "
            f"({plain['sq_calls']} sq, {plain['tool_calls']} tool, {plain['target_chars']} target chars)",
            f"  codemap arm: {codemap['tokens']} tokens "
            f"({codemap['sq_calls']} sq, {codemap['tool_calls']} tool, {codemap['target_chars']} target chars)",
            f"  token delta (plain - codemap): {payload['token_delta']}",
            f"  capped confidence: {payload['confidence']}",
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the measured-A/B CLI."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--logs", required=True, help="Log dir holding cli_*/tools_* shards")
    parser.add_argument("--plain-session", required=True, help="Session id of the plain (no-codemap) arm")
    parser.add_argument("--codemap-session", required=True, help="Session id of the codemap arm")
    parser.add_argument(
        "--signal",
        required=True,
        choices=sorted(SIGNAL_CAPS),
        help="Correctness signal type driving the confidence cap",
    )
    parser.add_argument("--json", action="store_true", help="Emit a single-line JSON object instead of text")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the measured-A/B CLI.

    Args:
        argv: override ``sys.argv[1:]`` (mainly for testing).

    Returns:
        ``0`` on success; ``2`` on a usage error (argparse raises ``SystemExit(2)``
        for missing/invalid arguments).
    """
    args = _build_parser().parse_args(argv)
    log_dir = Path(args.logs)
    cli_records = _collect(_shard_paths(log_dir, "cli"))
    tool_records = _collect(_shard_paths(log_dir, "tools"))

    plain = measure_arm(args.plain_session, cli_records, tool_records)
    codemap = measure_arm(args.codemap_session, cli_records, tool_records)
    both_measured = (plain.sq_calls + plain.tool_calls) > 0 and (codemap.sq_calls + codemap.tool_calls) > 0
    signal = args.signal if both_measured else "plumbing"
    confidence = confidence_for(args.signal, both_measured)

    payload = _render(plain, codemap, signal, confidence)
    print(json.dumps(payload, separators=(",", ":")) if args.json else render_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
