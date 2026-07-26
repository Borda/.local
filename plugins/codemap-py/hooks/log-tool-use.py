#!/usr/bin/env python3
"""Append low-cost Claude search/read telemetry and one repeated-read nudge."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_LOG_MAX_BYTES = 10 * 1024 * 1024
_BASH_SEARCH = re.compile(r"(^|[|;&(]\s*)(rg|grep|egrep|fgrep)\s")


def iso_now() -> str:
    """Return the compact UTC timestamp format used by codemap telemetry."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def plugin_version() -> str:
    """Return the package version without failing telemetry when the manifest is absent."""
    try:
        manifest = Path(__file__).parents[1] / ".claude-plugin" / "plugin.json"
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "?")
    except (OSError, TypeError, ValueError):
        return "?"


def session_id() -> str:
    """Return the session marker seeded once per project, without running git."""
    marker = Path(tempfile.gettempdir()) / f"codemap-{Path.cwd().name}-session"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def rotate(log_file: Path) -> None:
    """Rotate the bounded telemetry file, retaining two prior generations."""
    for generation in (2, 1):
        source = Path(f"{log_file}.{generation}")
        if source.exists():
            source.replace(Path(f"{log_file}.{generation + 1}"))
    if log_file.exists():
        log_file.replace(Path(f"{log_file}.1"))


def target_for(tool_name: str, tool_input: dict) -> str:
    """Return the one telemetry target field appropriate for the Claude tool."""
    if tool_name == "Read":
        return str(tool_input.get("file_path", ""))
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))[:200]
    return str(tool_input.get("pattern") or tool_input.get("path") or "")


def maybe_nudge_repeated_read(record: dict, log_file: Path) -> None:
    """Print one hint when a non-test Python source file is read for the third time."""
    if record["tool"] != "Read" or not record["target"].endswith(".py"):
        return
    if re.search(r"/tests?/", record["target"]):
        return
    escaped_target = json.dumps(record["target"])
    try:
        count = sum(
            '"Read"' in line and escaped_target in line for line in log_file.read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return
    if count == 3:
        base = Path(record["target"]).stem
        print(
            f"[codemap] {base}.py read 3x this session — structural queries may be cheaper: "
            "scan-query symbol --with-imports <name>, rdeps <module>, fn-rdeps <module::fn>"
        )


def main() -> int:
    """Record one matched tool use, respecting the opt-out and fail-open contracts."""
    if os.environ.get("CODEMAP_LOGGING", "true").lower() == "false":
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        tool_name = str(payload.get("tool_name", ""))
        if tool_name not in {"Grep", "Read", "Glob", "Bash"}:
            return 0
        tool_input = payload.get("tool_input") or {}
        if tool_name == "Bash":
            command = str(tool_input.get("command", ""))
            if not _BASH_SEARCH.search(command) or "scan-query" in command:
                return 0
        session = session_id()
        safe_session = "".join(char if char.isalnum() or char in "_-" else "-" for char in session)
        record = {
            "ts": iso_now(),
            "layer": "tool",
            "v": plugin_version(),
            "tool": tool_name,
            "session": session,
            "target": target_for(tool_name, tool_input),
        }
        log_dir = Path(os.environ.get("CODEMAP_LOG_DIR", ".cache/codemap/logs"))
        log_file = log_dir / (f"tools_{safe_session}.jsonl" if safe_session else "tools.jsonl")
        log_dir.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > _LOG_MAX_BYTES:
            rotate(log_file)
        with log_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        maybe_nudge_repeated_read(record, log_file)
    except (OSError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
