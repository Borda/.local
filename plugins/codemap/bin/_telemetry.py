#!/usr/bin/env python3
"""_telemetry.py — shared cli.jsonl logging for codemap core CLI tools.

Used by scan-query and scan-index (the two core CLI entry points). Each
invocation appends one JSON record to ``.cache/codemap/logs/cli_<session>.jsonl``,
falling back to ``cli.jsonl`` when no session id has been seeded. Per-session
filenames keep concurrent sessions from interleaving appends into one file.

The session id is seeded once per Claude Code session by the SessionStart hook
(seed-session.js) into ``$TMPDIR/codemap-<project>-session``; this module reads
it back so CLI records carry the same join key as the skill layer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

LOG_MAX_BYTES = 10 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def session_id() -> str:
    """Return the seeded session id for this project, or ``""`` if none."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
        proj = Path(root).name
    except Exception:  # noqa: BLE001 — git absent / not a repo → fall back to cwd
        proj = Path.cwd().name
    sid_file = Path(os.environ.get("TMPDIR", "/tmp")) / f"codemap-{proj}-session"
    try:
        return sid_file.read_text().strip()
    except OSError:
        return ""


def log_path_for(session: str, log_dir: Path) -> Path:
    """Resolve the per-session log file path (``cli.jsonl`` when session empty)."""
    name = f"cli_{_SAFE.sub('-', session)}.jsonl" if session else "cli.jsonl"
    return log_dir / name


def _rotate(path: Path) -> None:
    for i in range(2, 0, -1):
        src = path.parent / f"{path.name}.{i}"
        if src.exists():
            src.rename(path.parent / f"{path.name}.{i + 1}")
    if path.exists():
        path.rename(path.parent / f"{path.name}.1")


def log_cli(cmd: str, argv: list[str], result: object, t0: float, *, log_dir: Path | None = None) -> None:
    """Append one cli-layer telemetry record. Best-effort — never raises."""
    if os.environ.get("CODEMAP_LOGGING", "true").lower() == "false":
        return
    try:
        log_dir = log_dir or Path(os.environ.get("CODEMAP_LOG_DIR", ".cache/codemap/logs"))
        sid = session_id()
        log_file = log_path_for(sid, log_dir)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > LOG_MAX_BYTES:
            _rotate(log_file)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "layer": "cli",
            "cmd": cmd,
            "session": sid,
            "argv": argv,
            "timing_ms": max(0, int((time.time() - t0) * 1000)),
            "result": result if isinstance(result, dict) else {},
        }
        with log_file.open("a") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 — telemetry must never break the CLI
        pass
