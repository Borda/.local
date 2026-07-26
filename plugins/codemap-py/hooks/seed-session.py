#!/usr/bin/env python3
"""Seed Claude's per-project session marker without blocking a session start."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def project_name(cwd: Path) -> str:
    """Return the git-root basename for *cwd*, falling back to its basename."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=2,
            check=True,
        )
        if root := result.stdout.strip():
            return Path(root).name
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd.name


def main() -> int:
    """Persist a non-empty hook session ID, failing open on every error."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return 0
        marker = Path(tempfile.gettempdir()) / f"codemap-{project_name(Path.cwd())}-session"
        marker.write_text(session_id, encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
