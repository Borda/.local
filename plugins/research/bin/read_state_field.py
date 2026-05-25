#!/usr/bin/env python
"""read_state_field.py — read a dotted-path field from a JSON state file.

Loads ``state.json``-style files and navigates nested keys via a dotted path
(e.g. ``config.metric.direction``). Prints the resolved value to stdout and
returns the supplied default (or empty string) when the field is missing.

Extracted from the ``python -c`` inline block in
``plugins/research/skills/retro/SKILL.md`` (line 93) that reads
``config.metric.direction`` from ``state.json``. Satisfies the Check 23e policy
on inline Python in SKILL.md.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/read_state_field.py" \\
        <state_file> <dotted.field.path> [--default <value>]

Exit codes:
    0   field resolved (or default returned); value printed to stdout
    1   state file missing/unreadable, not valid JSON, or not a JSON object
    2   argument error (missing args, empty dotted-path)

Examples:
    # Read metric direction with sensible default
    python read_state_field.py .experiments/state/run-1/state.json \\
        config.metric.direction --default higher
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def read_field(data: dict[str, Any], dotted_path: str, default: str = "") -> str:
    """Navigate ``data`` along ``dotted_path`` and return the value as a string.

    The path is split on ``.``; each segment is used as a key on the current dict.
    If any segment is missing or the current value is not a dict, ``default`` is
    returned. Non-string terminal values are converted via ``str()`` to match the
    behaviour of the original inline ``print(...)`` block.

    Args:
        data: Parsed JSON object (top-level must be a dict).
        dotted_path: Dot-separated key path (e.g. ``"config.metric.direction"``).
            Must be non-empty.
        default: Fallback string when any segment is missing.

    Returns:
        The resolved value as a string, or ``default`` when the path does not
        fully resolve.

    Raises:
        ValueError: if ``dotted_path`` is empty.

    Examples:
        >>> read_field({"a": {"b": "c"}}, "a.b")
        'c'
        >>> read_field({"a": {"b": "c"}}, "a.missing", default="fallback")
        'fallback'
        >>> read_field({"x": 42}, "x")
        '42'
        >>> read_field({"a": "scalar"}, "a.b", default="d")
        'd'
        >>> read_field({}, "any", default="")
        ''
    """
    if not dotted_path:
        raise ValueError("dotted_path must be a non-empty string")
    cursor: Any = data
    for segment in dotted_path.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            return default
        cursor = cursor[segment]
    return str(cursor)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build the CLI argument parser (separate for testability)."""
    parser = argparse.ArgumentParser(
        prog="read_state_field",
        description="Read a dotted-path field from a JSON state file.",
    )
    parser.add_argument("state_file", help="Path to a state.json file.")
    parser.add_argument("dotted_path", help="Dot-separated key path (e.g. config.metric.direction).")
    parser.add_argument(
        "--default",
        default="",
        metavar="VALUE",
        help="Fallback value when the field is missing (default: empty string).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Reads JSON, navigates the path, prints the value to stdout.

    Args:
        argv: Optional argv list (for testing); defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` on file/parse error, ``2`` on argument error.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not args.dotted_path:
        print("read_state_field: dotted-path must be non-empty", file=sys.stderr)
        return 2

    state_file = Path(args.state_file)
    if not state_file.is_file():
        print(f"read_state_field: not a regular file: {state_file}", file=sys.stderr)
        return 1

    try:
        with state_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"read_state_field: cannot read {state_file}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print(f"read_state_field: top-level JSON in {state_file} is not an object", file=sys.stderr)
        return 1

    try:
        value = read_field(data, args.dotted_path, default=args.default)
    except ValueError as exc:
        print(f"read_state_field: {exc}", file=sys.stderr)
        return 2

    sys.stdout.write(value + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
