#!/usr/bin/env python3
"""join_avoidance.py — join tools.jsonl against cli.jsonl to count guard-chain leaks.

An *avoidance event* is a Grep/Read/Glob tool call (from ``tools_<session>.jsonl``,
written by ``log-tool-use.js``) whose target names a module that codemap had
*already* answered completely (``query_complete: true`` in the matching
``cli_<session>.jsonl`` record) within the preceding window. It means the agent
re-derived by hand what the structural index had already returned exhaustively —
the guard chain (``guard-redundant-scan.js`` + context injection) leaked, so the
grep it was meant to prevent still happened.

A high avoidance rate is a dead-chain signal: either the guard is not firing, the
injected context is not being read, or the model is ignoring both.

The module-match rule is ported from ``guard-redundant-scan.js``: split the module
on ``.`` / ``/`` into segments, escape regex metacharacters, rejoin with the ``[./]``
separator class, and require the match not to be flanked by an identifier character.
This mirrors the guard's word-boundary logic so this offline join counts exactly the
greps the online guard was meant to deny.

Usage:
    python join_avoidance.py --logs .cache/codemap/logs
    python join_avoidance.py --cli cli.jsonl --tools tools.jsonl --window-min 10
    python join_avoidance.py --logs .cache/codemap/logs --json

Exit codes:
    0 — success (including "no avoidance events" and "no logs found")
    2 — bad arguments (neither --logs nor a --cli/--tools pair given)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_WINDOW_MIN = 10
_IDENT = "A-Za-z0-9_"


@dataclass(frozen=True)
class CliAnswer:
    """One complete codemap answer that could later be re-derived by a grep.

    Attributes:
        session: session id joining the cli and tool layers.
        ts: event time (UTC) parsed from the record's ``ts`` field.
        module: dotted module name the command answered.
    """

    session: str
    ts: datetime
    module: str


@dataclass(frozen=True)
class ToolEvent:
    """One Grep/Read/Glob tool call recorded by log-tool-use.js.

    Attributes:
        session: session id joining the cli and tool layers.
        ts: event time (UTC) parsed from the record's ``ts`` field.
        tool: ``"Grep"`` | ``"Read"`` | ``"Glob"``.
        target: the tool's target string (pattern, path, or file_path).
    """

    session: str
    ts: datetime
    tool: str
    target: str


@dataclass(frozen=True)
class AvoidanceEvent:
    """A tool call that re-derived an already-complete codemap answer.

    Attributes:
        session: session the leak happened in.
        module: the module codemap had answered completely.
        tool: the Grep/Read/Glob tool that re-derived it.
        target: the tool call's target string.
        answer_ts: when codemap answered ``module`` completely.
        tool_ts: when the redundant tool call happened.
        gap_seconds: seconds between the answer and the tool call.
    """

    session: str
    module: str
    tool: str
    target: str
    answer_ts: datetime
    tool_ts: datetime
    gap_seconds: float


@dataclass
class Summary:
    """Aggregate avoidance metrics for a debrief report.

    Attributes:
        window_min: the join window in minutes used to produce these counts.
        total_tool_events: every Grep/Read/Glob event considered.
        total_complete_answers: every ``query_complete: true`` cli answer considered.
        avoidance_events: the flagged tool calls (guard-chain leaks).
        per_session: session id → avoidance count.
        per_skill: skill name → avoidance count (only sessions attributable to a skill).
    """

    window_min: int
    total_tool_events: int
    total_complete_answers: int
    avoidance_events: list[AvoidanceEvent] = field(default_factory=list)
    per_session: dict[str, int] = field(default_factory=dict)
    per_skill: dict[str, int] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        """Fraction of tool events that were avoidable (0.0 when no tool events).

        Examples:
            >>> Summary(window_min=10, total_tool_events=0, total_complete_answers=0).rate
            0.0
            >>> s = Summary(window_min=10, total_tool_events=4, total_complete_answers=1)
            >>> s.avoidance_events = [None]  # one flagged event
            >>> s.rate
            0.25
        """
        if not self.total_tool_events:
            return 0.0
        return len(self.avoidance_events) / self.total_tool_events


def _parse_ts(value: object) -> datetime | None:
    """Parse an ISO-8601 ``...Z`` timestamp into an aware UTC datetime.

    Args:
        value: the record's ``ts`` field (expected ``"YYYY-MM-DDTHH:MM:SSZ"``).

    Returns:
        An aware UTC ``datetime``, or ``None`` when the value is missing/unparsable.

    Examples:
        >>> _parse_ts("2026-07-10T01:25:00Z").hour
        1
        >>> _parse_ts("not-a-date") is None
        True
        >>> _parse_ts(None) is None
        True
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _module_from_cli_result(record: dict) -> str:
    """Extract the queried module name from a cli record.

    Prefers the emitted ``result.module`` field; falls back to the last non-flag
    token of ``argv`` (the module positional for rdeps/fn-rdeps/etc.).

    Args:
        record: a parsed ``cli.jsonl`` record.

    Returns:
        The dotted module name, or ``""`` when none can be determined.

    Examples:
        >>> _module_from_cli_result({"result": {"module": "pkg.auth"}})
        'pkg.auth'
        >>> _module_from_cli_result({"argv": ["rdeps", "pkg.auth"]})
        'pkg.auth'
        >>> _module_from_cli_result({"argv": ["central", "--top", "5"]})
        ''
    """
    result = record.get("result")
    if isinstance(result, dict):
        module = result.get("module")
        if isinstance(module, str) and module:
            return module
    argv = record.get("argv")
    if isinstance(argv, list):
        positionals = [a for a in argv[1:] if isinstance(a, str) and not a.startswith("-")]
        # A flag value (e.g. "5" after "--top") is a false positional; a module name
        # carries a "." or "/" separator, so require one rather than trust position.
        for token in reversed(positionals):
            if "." in token or "/" in token:
                return token
    return ""


def _query_complete(record: dict) -> bool:
    """Return whether a cli record reports a complete (exhaustive) answer.

    Checks ``result.index.query_complete`` first, then the legacy
    ``result.index.exhaustive`` alias, then the same two keys at ``result`` top
    level (the compact-diet coverage path emits them under ``index`` but the
    top-level check keeps the join robust to future schema moves).

    Args:
        record: a parsed ``cli.jsonl`` record.

    Returns:
        ``True`` only when a truthy completeness flag is present.

    Examples:
        >>> _query_complete({"result": {"index": {"query_complete": True}}})
        True
        >>> _query_complete({"result": {"index": {"exhaustive": True}}})
        True
        >>> _query_complete({"result": {"index": {"query_complete": False}}})
        False
        >>> _query_complete({"result": {}})
        False
    """
    result = record.get("result")
    if not isinstance(result, dict):
        return False
    for block in (result.get("index"), result):
        if isinstance(block, dict) and (block.get("query_complete") or block.get("exhaustive")):
            return True
    return False


def module_matches(module: str, text: str) -> bool:
    """Return True if *text* references *module* on identifier boundaries.

    Ported from ``guard-redundant-scan.js``: split the module on ``.``/``/``,
    escape regex metacharacters per segment, rejoin with the ``[./]`` class so
    both dotted and slashed forms match, and require the match not to be flanked
    by an identifier character. A plain substring test would falsely match
    ``pkg.auth`` inside ``pkg.auth2`` / ``notpkg.auth`` / ``pkg.authx``.

    Args:
        module: dotted (or slashed) module name codemap answered.
        text: the tool target string to test (grep pattern / path / file_path).

    Returns:
        Whether *text* contains a word-boundary reference to *module*.

    Examples:
        >>> module_matches("pkg.auth", "grep -r 'import pkg.auth' src/")
        True
        >>> module_matches("pkg.auth", "src/pkg/auth.py")
        True
        >>> module_matches("pkg.auth", "pkg.auth2")
        False
        >>> module_matches("pkg.auth", "pkg.other")
        False
        >>> module_matches("", "anything")
        False
    """
    if not module or not text:
        return False
    escaped = "[./]".join(re.escape(seg) for seg in re.split(r"[./]", module))
    try:
        pattern = re.compile(rf"(^|[^{_IDENT}]){escaped}([^{_IDENT}]|$)")
    except re.error:
        return False
    return pattern.search(text) is not None


def parse_cli_records(records: list[dict]) -> list[CliAnswer]:
    """Turn raw cli records into the complete-answer subset used by the join.

    Only records that are complete (``query_complete``/``exhaustive`` truthy),
    carry a resolvable module, and have a parseable timestamp become answers;
    everything else is dropped silently (incomplete answers cannot be avoided).

    Args:
        records: parsed ``cli.jsonl`` records.

    Returns:
        The complete answers, in input order.
    """
    answers: list[CliAnswer] = []
    for record in records:
        if not _query_complete(record):
            continue
        module = _module_from_cli_result(record)
        ts = _parse_ts(record.get("ts"))
        session = record.get("session")
        if module and ts is not None and isinstance(session, str):
            answers.append(CliAnswer(session=session, ts=ts, module=module))
    return answers


def parse_tool_records(records: list[dict]) -> list[ToolEvent]:
    """Turn raw tool records into typed events with parsed timestamps.

    Args:
        records: parsed ``tools.jsonl`` records.

    Returns:
        The well-formed tool events (records missing target/ts/session dropped).
    """
    events: list[ToolEvent] = []
    for record in records:
        target = record.get("target")
        ts = _parse_ts(record.get("ts"))
        session = record.get("session")
        tool = record.get("tool")
        if isinstance(target, str) and target and ts is not None and isinstance(session, str) and isinstance(tool, str):
            events.append(ToolEvent(session=session, ts=ts, tool=tool, target=target))
    return events


def _find_leaked_answer(event: ToolEvent, answers: list[CliAnswer], window_seconds: float) -> CliAnswer | None:
    """Return the most recent complete answer this tool event re-derived, if any.

    An answer leaks when it is in the same session, its module matches the tool
    target on identifier boundaries, and it landed within ``window_seconds``
    *before* the tool call. The most recent qualifying answer is returned so the
    reported gap is the tightest (and the guard's own last-answer semantics match).

    Args:
        event: the Grep/Read/Glob tool call under test.
        answers: complete cli answers to join against.
        window_seconds: max seconds an answer may precede the tool call.

    Returns:
        The leaked :class:`CliAnswer`, or ``None`` when the event was legitimate.
    """
    best: CliAnswer | None = None
    for answer in answers:
        if answer.session != event.session:
            continue
        gap = (event.ts - answer.ts).total_seconds()
        if gap < 0 or gap > window_seconds:
            continue
        if not module_matches(answer.module, event.target):
            continue
        if best is None or answer.ts > best.ts:
            best = answer
    return best


def find_avoidance_events(
    answers: list[CliAnswer],
    events: list[ToolEvent],
    window_min: int = DEFAULT_WINDOW_MIN,
) -> list[AvoidanceEvent]:
    """Join complete answers with tool events, flagging each guard-chain leak.

    Args:
        answers: complete cli answers (from :func:`parse_cli_records`).
        events: tool events (from :func:`parse_tool_records`).
        window_min: how many minutes an answer may precede a tool call and still
            count as re-derived. Defaults to :data:`DEFAULT_WINDOW_MIN`.

    Returns:
        One :class:`AvoidanceEvent` per tool call that re-derived a complete
        answer, in ``events`` order.
    """
    window_seconds = window_min * 60
    flagged: list[AvoidanceEvent] = []
    for event in events:
        answer = _find_leaked_answer(event, answers, window_seconds)
        if answer is None:
            continue
        flagged.append(
            AvoidanceEvent(
                session=event.session,
                module=answer.module,
                tool=event.tool,
                target=event.target,
                answer_ts=answer.ts,
                tool_ts=event.ts,
                gap_seconds=(event.ts - answer.ts).total_seconds(),
            )
        )
    return flagged


def summarize(
    answers: list[CliAnswer],
    events: list[ToolEvent],
    window_min: int = DEFAULT_WINDOW_MIN,
    session_skill: dict[str, str] | None = None,
) -> Summary:
    """Compute the full avoidance summary for a debrief report.

    Args:
        answers: complete cli answers.
        events: tool events.
        window_min: join window in minutes.
        session_skill: optional session id → skill name map (from the skills
            shard) enabling per-skill attribution; sessions absent from the map
            are still counted per session but not per skill.

    Returns:
        A populated :class:`Summary`.
    """
    flagged = find_avoidance_events(answers, events, window_min)
    per_session: dict[str, int] = {}
    per_skill: dict[str, int] = {}
    skill_map = session_skill or {}
    for event in flagged:
        per_session[event.session] = per_session.get(event.session, 0) + 1
        skill = skill_map.get(event.session)
        if skill:
            per_skill[skill] = per_skill.get(skill, 0) + 1
    return Summary(
        window_min=window_min,
        total_tool_events=len(events),
        total_complete_answers=len(answers),
        avoidance_events=flagged,
        per_session=per_session,
        per_skill=per_skill,
    )


def _read_jsonl(path: Path) -> list[dict]:
    """Read one JSONL file, skipping blank and malformed lines.

    Args:
        path: JSONL file to read.

    Returns:
        Parsed records; an unreadable or absent file yields ``[]``.
    """
    records: list[dict] = []
    try:
        text = path.read_text()
    except OSError:
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _collect(paths: list[Path]) -> list[dict]:
    """Read and concatenate records from every path in *paths*."""
    records: list[dict] = []
    for path in paths:
        records += _read_jsonl(path)
    return records


def _shard_paths(log_dir: Path, layer: str) -> list[Path]:
    """Return every per-session shard plus the legacy unsuffixed log for *layer*.

    Args:
        log_dir: the ``.cache/codemap/logs`` directory.
        layer: ``"cli"``, ``"tools"``, or ``"skills"``.

    Returns:
        Sorted matching paths (``<layer>_*.jsonl`` and legacy ``<layer>.jsonl``).
    """
    shards = sorted(log_dir.glob(f"{layer}_*.jsonl"))
    legacy = log_dir / f"{layer}.jsonl"
    if legacy.exists():
        shards.append(legacy)
    return shards


def _session_skill_map(skill_records: list[dict]) -> dict[str, str]:
    """Map each session id to the first skill that started in it.

    Args:
        skill_records: parsed ``skills.jsonl`` records (``session`` + ``skill``).

    Returns:
        session id → skill name; sessions with no skill record are absent.
    """
    mapping: dict[str, str] = {}
    for record in skill_records:
        session = record.get("session")
        skill = record.get("skill")
        if isinstance(session, str) and isinstance(skill, str) and session not in mapping:
            mapping[session] = skill
    return mapping


def _resolve_inputs(args: argparse.Namespace) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Resolve CLI arguments into (cli_records, tool_records, session_skill_map).

    Args:
        args: parsed argparse namespace (``logs`` or ``cli``/``tools`` paths).

    Returns:
        The raw cli records, raw tool records, and the session→skill map.
    """
    if args.logs:
        log_dir = Path(args.logs)
        cli = _collect(_shard_paths(log_dir, "cli"))
        tools = _collect(_shard_paths(log_dir, "tools"))
        skills = _collect(_shard_paths(log_dir, "skills"))
        return cli, tools, _session_skill_map(skills)
    cli = _collect([Path(args.cli)]) if args.cli else []
    tools = _collect([Path(args.tools)]) if args.tools else []
    return cli, tools, {}


def render_text(summary: Summary) -> str:
    """Render a human-readable avoidance summary.

    Args:
        summary: the computed :class:`Summary`.

    Returns:
        A multi-line report string (a single terminal ``print``).

    Examples:
        >>> s = Summary(window_min=10, total_tool_events=0, total_complete_answers=0)
        >>> "no tool events" in render_text(s)
        True
    """
    if not summary.total_tool_events:
        return "avoidance join: no tool events found — nothing to score."
    n = len(summary.avoidance_events)
    lines = [
        f"avoidance join (window {summary.window_min} min)",
        f"  complete answers: {summary.total_complete_answers}",
        f"  tool events:      {summary.total_tool_events}",
        f"  avoidance events: {n}  (rate {summary.rate:.1%})",
    ]
    if summary.per_session:
        lines.append("  per session:")
        for session, count in sorted(summary.per_session.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {session or '<none>'}: {count}")
    if summary.per_skill:
        lines.append("  per skill:")
        for skill, count in sorted(summary.per_skill.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {skill}: {count}")
    return "\n".join(lines)


def render_json(summary: Summary) -> str:
    """Render the avoidance summary as a single-line JSON object.

    Args:
        summary: the computed :class:`Summary`.

    Returns:
        A JSON string with totals, rate, per-session/per-skill counts, and events.
    """
    payload = {
        "window_min": summary.window_min,
        "total_tool_events": summary.total_tool_events,
        "total_complete_answers": summary.total_complete_answers,
        "avoidance_count": len(summary.avoidance_events),
        "rate": round(summary.rate, 4),
        "per_session": summary.per_session,
        "per_skill": summary.per_skill,
        "events": [
            {
                "session": e.session,
                "module": e.module,
                "tool": e.tool,
                "target": e.target,
                "answer_ts": e.answer_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tool_ts": e.tool_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gap_seconds": round(e.gap_seconds, 1),
            }
            for e in summary.avoidance_events
        ],
    }
    return json.dumps(payload, separators=(",", ":"))


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the avoidance-join CLI."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--logs", help="Log dir holding cli_*/tools_*/skills_* shards (default resolution)")
    parser.add_argument("--cli", help="Explicit cli JSONL file (overrides --logs for the cli layer)")
    parser.add_argument("--tools", help="Explicit tools JSONL file (overrides --logs for the tools layer)")
    parser.add_argument(
        "--window-min",
        type=int,
        default=DEFAULT_WINDOW_MIN,
        help=f"Minutes an answer may precede a re-deriving tool call (default {DEFAULT_WINDOW_MIN})",
    )
    parser.add_argument("--json", action="store_true", help="Emit a single-line JSON object instead of text")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the avoidance-join CLI.

    Args:
        argv: override ``sys.argv[1:]`` (mainly for testing).

    Returns:
        ``0`` on success, ``2`` when neither ``--logs`` nor a ``--cli``/``--tools``
        input was given.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.logs and not (args.cli or args.tools):
        print("join_avoidance: give --logs DIR or --cli FILE and/or --tools FILE", file=sys.stderr)
        return 2

    cli_records, tool_records, session_skill = _resolve_inputs(args)
    answers = parse_cli_records(cli_records)
    events = parse_tool_records(tool_records)
    summary = summarize(answers, events, window_min=args.window_min, session_skill=session_skill)
    print(render_json(summary) if args.json else render_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
