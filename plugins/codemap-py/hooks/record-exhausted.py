#!/usr/bin/env python3
"""Record exhaustive reverse-dependency results for the guard hook's sentinel."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

_QUERY = re.compile(r"\bscan-query\b|\$SQ\b")
_TARGET = re.compile(r"\b(?:fn-)?rdeps\s+[\"']?([A-Za-z0-9_.]+(?:::[A-Za-z0-9_.]+)?)[\"']?")
_COMPLETE = re.compile(r'"(?:query_complete|exhaustive)"\s*:\s*true')


def sentinel_path(session_id: object) -> Path:
    """Return the shared per-session exhausted-query sentinel path."""
    key = str(session_id or "").strip() or "nosession"
    return Path(tempfile.gettempdir()) / f"codemap-exhausted-{key}"


def main() -> int:
    """Append dotted and slashed module names when a query result is exhaustive."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        command = str(payload.get("tool_input", {}).get("command", ""))
        if not _QUERY.search(command):
            return 0
        target = _TARGET.search(command)
        if target is None:
            return 0
        response = payload.get("tool_response", "")
        rendered = response if isinstance(response, str) else json.dumps(response)
        if not _COMPLETE.search(rendered):
            return 0
        dotted = target.group(1).split("::", 1)[0]
        with sentinel_path(payload.get("session_id")).open("a", encoding="utf-8") as stream:
            stream.write(f"{dotted}\n{dotted.replace('.', '/')}\n")
    except (OSError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
