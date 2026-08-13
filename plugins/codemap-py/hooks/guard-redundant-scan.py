#!/usr/bin/env python3
"""Deny redundant import greps after an exhaustive reverse-dependency query.

The sentinel this hook reads is written — and invalidated — by ``record-exhausted.py``;
the two files must derive the same path from the same event, which
``tests/cli_support/test_hooks_py.py`` pins by running both and comparing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

#: Every alternative stays anchored on an actual search tool. The unanchored
#: ``\bimport\b.*-r`` alternative this replaces denied any command pairing the word
#: "import" with a ``-r`` flag — ``python -c "import x" && rm -r tmp`` among them — and
#: added no coverage, since an anchored form of it is a strict subset of the first.
_IMPORT_GREP = re.compile(r"\b(?:grep|rg)\b.*\b(?:import|from)\b")
#: Characters that must never reach a tmp filename (the session id is host-supplied).
_UNSAFE_KEY = re.compile(r"[^A-Za-z0-9_-]")
#: How long a recorded exhaustive caller set may still deny a grep. ``record-exhausted.py``
#: drops the sentinel on every Claude source edit, so this only bounds mutation the hook
#: never saw (a checkout, an external editor, a sibling agent). Matches the 30-minute
#: session TTL ``inject-preamble.py`` uses. An append refreshes the whole file's mtime, so
#: a later exhaustive query restarts the clock for entries recorded earlier — accepted:
#: the edit-driven invalidation, not the clock, is the primary staleness mechanism.
_SENTINEL_TTL_S = 30 * 60


def tmp_dir() -> Path:
    """Return the temp directory the hook sentinels live in."""
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir())


def session_key(session_id: object) -> str:
    """Return the sanitized sentinel key for *session_id*, or a session-scoped fallback.

    Mirrors ``record-exhausted.session_key``: a missing session id must not collapse to one
    machine-global key, or two concurrent projects would deny each other's greps.

    Examples:
        >>> session_key("abc-123")
        'abc-123'
        >>> session_key(None) not in ("", "nosession")
        True
    """
    key = _UNSAFE_KEY.sub("-", str(session_id or "").strip())
    if key:
        return key
    csid = os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "shared"
    return f"{_UNSAFE_KEY.sub('-', Path.cwd().name)}-{_UNSAFE_KEY.sub('-', csid)}"


def sentinel_path(session_id: object) -> Path:
    """Return the shared exhausted-query sentinel path written by record-exhausted."""
    return tmp_dir() / f"codemap-exhausted-{session_key(session_id)}"


def fresh_modules(sentinel: Path) -> list[str]:
    """Return the recorded modules, or none once the sentinel's authority has expired.

    Args:
        sentinel: Path to the exhausted-query sentinel (need not exist).

    Returns:
        Non-empty module names still inside the TTL; an empty list otherwise, which the
        caller treats as "nothing is exhaustive" and allows the grep.
    """
    try:
        recorded_at = sentinel.stat().st_mtime
    except OSError:
        return []
    if time.time() - recorded_at > _SENTINEL_TTL_S:
        return []
    return [line.strip() for line in sentinel.read_text(encoding="utf-8").splitlines() if line.strip()]


def module_matches(module: str, command: str) -> bool:
    """Return whether *module* appears as a full dotted or slashed command token."""
    pieces = [re.escape(part) for part in re.split(r"[./]", module)]
    pattern = rf"(^|[^A-Za-z0-9_]){'[./]'.join(pieces)}([^A-Za-z0-9_]|$)"
    return re.search(pattern, command) is not None


def main() -> int:
    """Emit a Claude deny response only for an already-exhaustive import grep."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        command = str(payload.get("tool_input", {}).get("command", ""))
        if not _IMPORT_GREP.search(command):
            return 0
        modules = fresh_modules(sentinel_path(payload.get("session_id")))
        hit = next((item for item in modules if module_matches(item, command)), None)
        if hit is None:
            return 0
        reason = (
            f"codemap already returned the EXHAUSTIVE caller set for {hit.replace('/', '.')} this session. "
            "Re-grepping is disabled — the import-graph index is authoritative. "
            "Use the codemap result and write your answer."
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    except (OSError, TypeError, ValueError, re.error):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
