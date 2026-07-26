#!/usr/bin/env python3
"""Append Claude codemap-py skill starts to session-sharded telemetry."""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:
    """Return the compact UTC timestamp format used by codemap telemetry."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    """Log one codemap-py Skill event, generating a local session ID if needed."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        if payload.get("tool_name") != "Skill":
            return 0
        tool_input = payload.get("tool_input") or {}
        skill = str(tool_input.get("skill", ""))
        if not skill.startswith("codemap-py:"):
            return 0
        project = Path.cwd().name
        session_file = Path(tempfile.gettempdir()) / f"codemap-{project}-session"
        try:
            session = session_file.read_text(encoding="utf-8").strip()
        except OSError:
            session = ""
        if not session:
            session = str(uuid.uuid4())
            try:
                session_file.write_text(session, encoding="utf-8")
            except OSError:
                pass
        safe_session = "".join(char if char.isalnum() or char in "_-" else "-" for char in session)
        log_dir = Path.cwd() / ".cache" / "codemap" / "logs"
        log_file = log_dir / (f"skills_{safe_session}.jsonl" if safe_session else "skills.jsonl")
        record = {
            "ts": iso_now(),
            "layer": "skill",
            "session": session,
            "skill": skill,
            "event": "start",
            "intent": str(tool_input.get("args", ""))[:300],
            "hook_session": payload.get("session_id") or "",
        }
        log_dir.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
