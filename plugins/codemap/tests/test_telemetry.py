"""Tests for ``bin/_telemetry.py`` — shared per-session cli.jsonl logging.

Covers:
* log_path_for — per-session filename, fallback, unsafe-char sanitization
* session_id — reads the seeded tmpfile; empty when absent
* log_cli — writes a per-session record; falls back to cli.jsonl with no session
* CODEMAP_LOGGING=false disables all writes
"""

from __future__ import annotations

import json
from pathlib import Path

import _telemetry as t


def _no_git(monkeypatch) -> None:
    """Force session_id() to use cwd basename (no git lookup)."""

    def _boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(t.subprocess, "check_output", _boom)


def test_log_path_for():
    assert t.log_path_for("abc", Path("/l")).name == "cli_abc.jsonl"
    assert t.log_path_for("", Path("/l")).name == "cli.jsonl"
    assert t.log_path_for("a/b c", Path("/l")).name == "cli_a-b-c.jsonl"


def test_session_and_log_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("CODEMAP_LOGGING", raising=False)
    _no_git(monkeypatch)
    logdir = tmp_path / "logs"

    # No session seeded → empty id → unsuffixed cli.jsonl.
    assert t.session_id() == ""
    t.log_cli("central", ["central"], {"x": 1}, 0.0, log_dir=logdir)
    assert (logdir / "cli.jsonl").exists()

    # Seed a session → per-session filename, session field populated.
    (tmp_path / f"codemap-{tmp_path.name}-session").write_text("sess9")
    assert t.session_id() == "sess9"
    t.log_cli("rdeps", ["rdeps", "m"], {"y": 2}, 0.0, log_dir=logdir)
    rec = json.loads((logdir / "cli_sess9.jsonl").read_text().strip())
    assert rec["cmd"] == "rdeps"
    assert rec["session"] == "sess9"
    assert rec["layer"] == "cli"
    assert rec["result"] == {"y": 2}


def test_logging_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMAP_LOGGING", "false")
    logdir = tmp_path / "logs"
    t.log_cli("x", [], {}, 0.0, log_dir=logdir)
    assert not logdir.exists()


def test_source_tag_from_env(tmp_path, monkeypatch):
    """CODEMAP_TELEMETRY_SOURCE stamps records so debrief can drop scripted load."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("CODEMAP_LOGGING", raising=False)
    monkeypatch.setenv("CODEMAP_TELEMETRY_SOURCE", "bench")
    _no_git(monkeypatch)
    logdir = tmp_path / "logs"
    t.log_cli("central", ["central"], {"x": 1}, 0.0, log_dir=logdir)
    (record,) = [json.loads(line) for line in (logdir / "cli.jsonl").read_text().splitlines()]
    assert record["source"] == "bench"
    assert record["v"] not in ("", "?")


def test_no_source_tag_by_default(tmp_path, monkeypatch):
    """Untagged (organic) records carry no source field at all."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("CODEMAP_LOGGING", raising=False)
    monkeypatch.delenv("CODEMAP_TELEMETRY_SOURCE", raising=False)
    _no_git(monkeypatch)
    logdir = tmp_path / "logs"
    t.log_cli("central", ["central"], {"x": 1}, 0.0, log_dir=logdir)
    (record,) = [json.loads(line) for line in (logdir / "cli.jsonl").read_text().splitlines()]
    assert "source" not in record
