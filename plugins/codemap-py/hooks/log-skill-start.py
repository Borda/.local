#!/usr/bin/env python3
"""Append Claude codemap-py skill starts to session-sharded telemetry."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

#: Same sanitizer as ``codemap_py.telemetry`` — the shard names must agree to join.
_UNSAFE_KEY = re.compile(r"[^A-Za-z0-9_-]")


def iso_now() -> str:
    """Return the compact UTC timestamp format used by codemap telemetry."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_name(cwd: Path | None = None) -> str:
    """Return the project key: the basename of the nearest enclosing git root.

    Must agree with ``seed-session.py``, ``log-tool-use.py`` and ``codemap_py.telemetry``:
    all four address one per-project session marker, and keying this hook on ``cwd.name``
    made a session started in a subdirectory mint a *second*, unjoinable session id.

    Args:
        cwd: Directory to resolve from; defaults to the process working directory.

    Returns:
        The git-root basename, or the directory's own basename outside a repository.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     nested = Path(d) / "myproj" / "src"
        ...     nested.mkdir(parents=True)
        ...     (Path(d) / "myproj" / ".git").mkdir()
        ...     project_name(nested)
        'myproj'
    """
    start = (cwd or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate.name
    return start.name


def resolve_session(session_file: Path) -> str:
    """Return the seeded session id, minting and persisting one when none exists."""
    try:
        session = session_file.read_text(encoding="utf-8").strip()
    except OSError:
        session = ""
    if session:
        return session
    session = str(uuid.uuid4())
    try:
        session_file.write_text(session, encoding="utf-8")
    except OSError:
        pass
    return session


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
        tmp_dir = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
        session = resolve_session(tmp_dir / f"codemap-{project_name()}-session")
        safe_session = _UNSAFE_KEY.sub("-", session)
        # CODEMAP_LOG_DIR is honoured here as it is by log-tool-use.py and the cli layer;
        # a shard that ignored the override landed outside the directory debrief reads.
        log_dir = Path(os.environ.get("CODEMAP_LOG_DIR", ".cache/codemap/logs"))
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
