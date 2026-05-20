"""Tests for ``bin/commit_action_item.sh`` sentinel-aware commit helper.

The script stages explicit files, touches the Gate 1 commit-auth sentinel,
runs ``git commit -F <message-file>``, and cleans the sentinel on exit.

Unit tests cover argument validation (no git required). Integration tests
(real git repo + commit) are gated by ``RUN_INTEGRATION=1``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "commit_action_item.sh"


def sh(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run the script under test and capture stdout/stderr."""
    e = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
    )


def test_missing_message_file_arg(tmp_path: Path):
    """No args → "--message-file required" stderr, exit 1."""
    result = sh()
    assert result.returncode == 1
    assert "--message-file required" in result.stderr


def test_message_file_not_found():
    """``--message-file`` points to non-existent path → exit 1 "not found"."""
    result = sh("--message-file", "/nonexistent/msg.txt")
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_missing_files_arg(tmp_path: Path):
    """``--message-file`` valid but no ``--files`` → exit 1 "--files requires"."""
    msg = tmp_path / "msg.txt"
    msg.write_text("test commit\n")
    result = sh("--message-file", str(msg))
    assert result.returncode == 1
    assert "--files requires" in result.stderr


def test_unknown_arg(tmp_path: Path):
    """Unrecognized flag → exit 1 "unknown arg"."""
    result = sh("--unknown-arg")
    assert result.returncode == 1
    assert "unknown arg" in result.stderr


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")
def test_creates_commit(tmp_path: Path):
    """Integration: stages a real file and commits."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    target = tmp_path / "file.txt"
    target.write_text("hello\n")
    msg = tmp_path / "msg.txt"
    msg.write_text("test commit\n")
    result = sh("--message-file", str(msg), "--files", str(target), cwd=str(tmp_path))
    assert result.returncode == 0
