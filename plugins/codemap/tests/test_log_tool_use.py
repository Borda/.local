"""Contract test: log-tool-use.js appends one tools.jsonl record per Grep/Read/Glob call.

The PostToolUse hook (`log-tool-use.js`) is the raw grep/read-volume signal codemap's
Phase-1 fixes aim to reduce. It must:

- write one JSON line to `tools_<session>.jsonl` for each Grep/Read/Glob call, carrying
  `tool` + the right `target` field (Grep/Glob pattern-or-path, Read file_path);
- join on the same session key as the cli shard (`tools_<session>.jsonl` when a session
  tmpfile is seeded, unsuffixed `tools.jsonl` otherwise);
- never read `tool_response` — parsing search/read output is the exact cost the hook must
  not pay (accept criterion + <5ms budget), so a hostile non-JSON tool_response must not
  change behaviour;
- honour `CODEMAP_LOGGING=false` (mirrors `_telemetry.py`'s env gate) and fail open.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HOOK = Path(__file__).parent.parent / "hooks" / "log-tool-use.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


def _run(payload: dict, cwd: Path, *, logging: str | None = None) -> subprocess.CompletedProcess:
    """Feed one PostToolUse event through the hook with cwd + env isolated to a tmp dir."""
    env = {**os.environ}
    # Force the log dir under cwd; unset any inherited override so tests are hermetic.
    env.pop("CODEMAP_LOG_DIR", None)
    if logging is not None:
        env["CODEMAP_LOGGING"] = logging
    return subprocess.run(
        ["node", str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


def _read_records(cwd: Path) -> list[dict]:
    """Return all records across every tools*.jsonl shard under the cwd log dir."""
    log_dir = cwd / ".cache" / "codemap" / "logs"
    records: list[dict] = []
    for shard in sorted(log_dir.glob("tools*.jsonl")):
        records += [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    return records


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected_target"),
    [
        pytest.param("Grep", {"pattern": "def login", "path": "src/"}, "def login", id="grep-pattern"),
        pytest.param("Glob", {"pattern": "**/*.py"}, "**/*.py", id="glob-pattern"),
        pytest.param("Read", {"file_path": "/repo/src/auth.py"}, "/repo/src/auth.py", id="read-file-path"),
    ],
)
def test_appends_record_per_tool(tool: str, tool_input: dict, expected_target: str, tmp_path: Path) -> None:
    """Each Grep/Read/Glob call writes one line carrying its tool name and target field."""
    result = _run({"tool_name": tool, "tool_input": tool_input}, tmp_path)

    assert result.returncode == 0, result.stderr
    records = _read_records(tmp_path)
    assert len(records) == 1
    assert records[0]["tool"] == tool
    assert records[0]["target"] == expected_target
    assert records[0]["layer"] == "tool"


def test_session_shard_uses_seeded_session_id(tmp_path: Path) -> None:
    """A seeded session tmpfile routes records to tools_<session>.jsonl, matching the cli shard key."""
    # seed-session.js writes codemap-<project>-session into TMPDIR; project = cwd basename here.
    session = "abc-123"
    (tmp_path / f"codemap-{tmp_path.name}-session").write_text(session)
    env = {**os.environ, "TMPDIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path)}
    env.pop("CODEMAP_LOG_DIR", None)
    result = subprocess.run(
        ["node", str(_HOOK)],
        input=json.dumps({"tool_name": "Grep", "tool_input": {"pattern": "x"}}),
        text=True,
        capture_output=True,
        cwd=str(tmp_path),
        env=env,
    )

    assert result.returncode == 0, result.stderr
    shard = tmp_path / ".cache" / "codemap" / "logs" / f"tools_{session}.jsonl"
    assert shard.exists(), "record not routed to the seeded per-session shard"
    assert json.loads(shard.read_text().strip())["session"] == session


def test_non_search_tool_ignored(tmp_path: Path) -> None:
    """A tool outside the Grep/Read/Glob matcher must write nothing (defence-in-depth vs matcher)."""
    _run({"tool_name": "Bash", "tool_input": {"command": "ls"}}, tmp_path)
    assert _read_records(tmp_path) == []


def test_tool_response_never_parsed(tmp_path: Path) -> None:
    """A non-JSON, oversized tool_response must not affect the append — the hook never reads it."""
    payload = {
        "tool_name": "Grep",
        "tool_input": {"pattern": "def login"},
        "tool_response": "\x00not-json{{{" + "x" * 100000,
    }
    result = _run(payload, tmp_path)

    assert result.returncode == 0, result.stderr
    records = _read_records(tmp_path)
    assert len(records) == 1
    assert records[0]["target"] == "def login"


def test_logging_disabled_suppresses_record(tmp_path: Path) -> None:
    """CODEMAP_LOGGING=false is honoured — no shard is written."""
    result = _run({"tool_name": "Grep", "tool_input": {"pattern": "x"}}, tmp_path, logging="false")

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".cache" / "codemap" / "logs").exists()


def test_codemap_hook_reads_stdin_by_fd_for_windows() -> None:
    """The tool-use hook must not use POSIX-only /dev/stdin (Windows portability)."""
    assert "/dev/stdin" not in _HOOK.read_text(encoding="utf-8")
