"""Contract test: log-tool-use.py appends one tools.jsonl record per Grep/Read/Glob call.

The PostToolUse hook (`log-tool-use.js`) is the raw grep/read-volume signal codemap's
index-hygiene fixes aim to reduce. It must:

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
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).parent.parent.parent / "hooks" / "log-tool-use.py"


def _run(payload: dict, cwd: Path, *, logging: str | None = None) -> subprocess.CompletedProcess:
    """Feed one PostToolUse event through the hook with cwd + env isolated to a tmp dir."""
    env = {**os.environ}
    # Force the log dir under cwd; unset any inherited override so tests are hermetic.
    env.pop("CODEMAP_LOG_DIR", None)
    # conftest's autouse _telemetry_off exports CODEMAP_LOGGING=false suite-wide;
    # this helper's default must re-enable it or every write-asserting case goes dark.
    env["CODEMAP_LOGGING"] = logging if logging is not None else "true"
    return subprocess.run(
        [sys.executable, str(_HOOK)],
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
    env["CODEMAP_LOGGING"] = "true"  # conftest autouse gate exports false suite-wide
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
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
    """A tool outside the matched set must write nothing (defence-in-depth vs matcher)."""
    _run({"tool_name": "Edit", "tool_input": {"file_path": "/x.py"}}, tmp_path)
    assert _read_records(tmp_path) == []


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("ls -la src/", id="non-search-command"),
        pytest.param("scan-query rdeps pkg.mod | grep imported_by", id="scan-query-wrapper"),
    ],
)
def test_bash_non_search_ignored(tmp_path: Path, command: str) -> None:
    """Bash commands that are not manual search volume must write nothing."""
    _run({"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path)
    assert _read_records(tmp_path) == []


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("rg 'def login' src/", id="rg-direct"),
        pytest.param("cat f.py | grep import", id="grep-after-pipe"),
    ],
)
def test_bash_search_logged_with_command_target(tmp_path: Path, command: str) -> None:
    """Search-shaped Bash commands are logged as tool=Bash with the command as target."""
    _run({"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path)
    records = _read_records(tmp_path)
    assert len(records) == 1
    assert records[0]["tool"] == "Bash"
    assert records[0]["target"] == command


def test_records_carry_plugin_version(tmp_path: Path) -> None:
    """Every record stamps the plugin version `v` for before/after release comparison."""
    _run({"tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}}, tmp_path)
    (record,) = _read_records(tmp_path)
    assert record["v"] not in ("", "?")


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


class TestReadRedundancyNudge:
    """3rd Read of the same non-test .py file prints one structural-query hint."""

    _PAYLOAD = {"tool_name": "Read", "tool_input": {"file_path": "/proj/src/core.py"}}

    def test_hint_fires_exactly_on_third_read(self, tmp_path: Path) -> None:
        """Reads 1–2 stay silent, read 3 hints, read 4 stays silent again."""
        outs = [_run(self._PAYLOAD, tmp_path).stdout for _ in range(4)]
        assert outs[0] == "" and outs[1] == ""
        assert "[codemap] core.py read 3x" in outs[2]
        assert outs[3] == ""

    def test_no_hint_for_test_files(self, tmp_path: Path) -> None:
        """Repeated Reads of test files never nudge — re-reading tests is normal."""
        payload = {"tool_name": "Read", "tool_input": {"file_path": "/proj/tests/test_core.py"}}
        outs = [_run(payload, tmp_path).stdout for _ in range(4)]
        assert all(o == "" for o in outs)
