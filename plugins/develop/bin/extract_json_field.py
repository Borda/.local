#!/usr/bin/env python
"""extract_json_field.py — recover a JSON object from text and print a field.

Replaces the inline ``python -c`` fallback used by ``develop:plan`` when ``jq``
is unavailable or the agent response wraps JSON in prose. Two operations,
selected by the ``<field>`` argument:

* ``<field> == "."`` or ``<field> == "_object"`` — print the recovered JSON
  object as a compact one-line string (matches the prior inline-code contract).
* Any other ``<field>`` — extract that top-level key's value. Strings print raw
  (no surrounding quotes); non-strings print as JSON (e.g. ``true``, ``42``,
  ``[1,2]``).

Recovery strategy mirrors the prior inline code: scan every ``{`` position in
the input text from right to left and return the first balanced object that
parses cleanly. This tolerates prose preamble before the JSON, trailing prose
after it, and reasoning blocks that contain stray ``{`` characters.

Usage:
    python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/extract_json_field.py" \\
        <field> [<json-or-text>]

When the second argument is omitted (or is ``-``), the text is read from stdin.

Exit codes:
    0  Success — value printed to stdout.
    1  No balanced JSON object could be recovered from the input.
    2  Object recovered but the requested field is absent.
    3  Usage error (no field argument).
"""

from __future__ import annotations

import json
import sys
from typing import Any

_WHOLE_OBJECT_ALIASES = frozenset({".", "_object", ""})


def recover_json_object(text: str) -> dict[str, Any] | None:
    """Return the outermost balanced JSON object embedded in ``text``.

    Scans every ``{`` position from left to right (prefers the outermost,
    i.e. largest, object) and at each position tries progressively shorter
    truncations of the tail until :func:`json.loads` accepts a balanced
    object. This tolerates prose preamble before the JSON, trailing prose
    after it, and reasoning blocks that contain stray ``{`` characters
    before the real object.

    Pure function — no I/O, deterministic.

    Args:
        text: Raw text possibly containing a JSON object plus surrounding
            prose, reasoning, or whitespace.

    Returns:
        The parsed object as a ``dict``, or ``None`` if no balanced JSON
        object could be recovered.

    Examples:
        >>> recover_json_object('{"a":"sw","ok":true}')
        {'a': 'sw', 'ok': True}
        >>> recover_json_object('thinking... here it is: {"verdict":"PASS"}')
        {'verdict': 'PASS'}
        >>> recover_json_object('prose with { stray brace and {"ok":false}')
        {'ok': False}
        >>> recover_json_object('no json here at all') is None
        True
        >>> recover_json_object('') is None
        True
        >>> recover_json_object('{"nested":{"k":1}} trailing prose')
        {'nested': {'k': 1}}
        >>> recover_json_object('  {"ok": true}\\n\\nthen extra prose')
        {'ok': True}
    """
    open_positions = [i for i, ch in enumerate(text) if ch == "{"]
    for start in open_positions:
        candidate = text[start:]
        # json.loads only accepts trailing whitespace; truncate from the right
        # past each '}' so prose following the object does not poison the parse.
        for end in range(len(candidate), 0, -1):
            if candidate[end - 1] != "}":
                continue
            try:
                parsed = json.loads(candidate[:end])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
            break  # parsed but wasn't an object — try the next '{'
    return None


def format_field(value: Any) -> str:
    """Format a JSON value for stdout.

    Strings print raw (no surrounding quotes) so shells can capture them
    cleanly; every other type prints as compact JSON.

    Args:
        value: Any JSON-decoded value.

    Returns:
        The stdout representation (no trailing newline).

    Examples:
        >>> format_field("PASS")
        'PASS'
        >>> format_field(True)
        'true'
        >>> format_field(42)
        '42'
        >>> format_field([1, 2, 3])
        '[1, 2, 3]'
        >>> format_field({"k": "v"})
        '{"k": "v"}'
        >>> format_field(None)
        'null'
    """
    if isinstance(value, str):
        return value
    return json.dumps(value)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if no object recovered, 2 if field absent, 3 on usage error.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        print(
            "Usage: extract_json_field.py <field> [<json-or-text>]",
            file=sys.stderr,
        )
        return 3

    field = args[0]
    if len(args) >= 2 and args[1] != "-":
        text = args[1]
    else:
        text = sys.stdin.read()

    obj = recover_json_object(text)
    if obj is None:
        print("! extract_json_field: no balanced JSON object found", file=sys.stderr)
        return 1

    if field in _WHOLE_OBJECT_ALIASES:
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        return 0

    if field not in obj:
        print(f"! extract_json_field: field {field!r} not present in recovered object", file=sys.stderr)
        return 2

    sys.stdout.write(format_field(obj[field]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
