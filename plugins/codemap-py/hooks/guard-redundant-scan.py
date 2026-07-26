#!/usr/bin/env python3
"""Deny redundant import greps after an exhaustive reverse-dependency query."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

_IMPORT_GREP = re.compile(r"\b(grep|rg)\b.*\bimport\b|\b(grep|rg)\b.*\bfrom\b|\bimport\b.*-r")


def sentinel_path(session_id: object) -> Path:
    """Return the shared exhausted-query sentinel path written by record-exhausted."""
    key = str(session_id or "").strip() or "nosession"
    return Path(tempfile.gettempdir()) / f"codemap-exhausted-{key}"


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
        modules = sentinel_path(payload.get("session_id")).read_text(encoding="utf-8").splitlines()
        hit = next((item.strip() for item in modules if item.strip() and module_matches(item.strip(), command)), None)
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
