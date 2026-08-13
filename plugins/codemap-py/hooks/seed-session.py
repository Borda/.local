#!/usr/bin/env python3
"""Seed Claude's per-project session marker without blocking a session start."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def project_name(cwd: Path | None = None) -> str:
    """Return the project key: the basename of the nearest enclosing git root.

    This hook writes the marker every other layer reads, so its keying is the one the
    readers (``log-tool-use.py``, ``log-skill-start.py``, ``codemap_py.telemetry``) must
    reproduce. The root is found by walking for ``.git`` rather than by shelling out to
    ``git rev-parse``, which is both cheaper and identical in result — except that it
    keeps working when git is absent from ``PATH``. ``.git`` is matched as a file too,
    which is how linked worktrees mark their root.

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


def main() -> int:
    """Persist a non-empty hook session ID, failing open on every error."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return 0
        tmp_dir = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
        (tmp_dir / f"codemap-{project_name()}-session").write_text(session_id, encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
