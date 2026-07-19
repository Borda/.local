#!/usr/bin/env python3
"""Report Codex Rig shim health at session start without lifecycle writes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MAX_INPUT_BYTES = 65_536
MAX_OUTPUT_BYTES = 1_048_576


def _response(message: str | None = None) -> str:
    """Encode one non-blocking SessionStart response."""
    value: dict[str, object] = {"continue": True, "suppressOutput": False}
    if message:
        value["systemMessage"] = message
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _input() -> dict[str, object]:
    """Read and validate the bounded SessionStart envelope."""
    payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("hook input is oversized")
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get("hook_event_name") != "SessionStart":
        raise ValueError("SessionStart hook input required")
    return value


def _plugin_root() -> Path:
    """Bind the hook to the exact installed plugin root supplied by Codex."""
    configured = os.environ.get("PLUGIN_ROOT")
    if not configured:
        raise ValueError("PLUGIN_ROOT is unavailable")
    root = Path(configured).resolve(strict=True)
    script = Path(__file__).resolve(strict=True)
    if script != root / "hooks" / "session_start.py":
        raise ValueError("hook is outside the active plugin root")
    return root


def main() -> int:
    """Run the packaged doctor and surface only actionable degraded health."""
    try:
        _input()
        root = _plugin_root()
        manager = root / "scripts" / "manage_role_agents.py"
        completed = subprocess.run(
            [sys.executable, str(manager), "doctor"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
        )
        if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
            raise ValueError("doctor output is oversized")
        result = json.loads(completed.stdout)
        classification = result.get("classification") if isinstance(result, dict) else None
        if completed.returncode != 0 or classification not in {"healthy", "degraded", "blocked"}:
            raise ValueError("doctor did not return a valid diagnostic")
        message = None
        if classification != "healthy":
            message = f"Codex Rig shim health: {classification}. Run $agent-shims status for details."
        print(_response(message))
        return 0
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as error:
        print(_response(f"Codex Rig shim health check unavailable: {error}. Run $agent-shims doctor."))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
