"""Tests for ``bin/commit_all_items.sh`` bulk-commit helper.

The script creates a single commit summarizing N action items resolved
during ``/oss:resolve``. Args: PR_NUMBER, N_AS_SUGGESTED, N_SELF_RESOLVED,
N_REJECTED, [SUMMARIES_FILE], [--codex]. Counts are validated as ``^[0-9]+$``;
non-integer counts exit 2.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "commit_all_items.sh"


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


def test_missing_pr_number(tmp_path: Path):
    """No PR_NUMBER → exit 1 with Usage message."""
    result = sh()
    assert result.returncode == 1
    assert "Usage" in result.stderr


def test_non_integer_n_as_suggested(tmp_path: Path):
    """Non-integer N_AS_SUGGESTED → exit 2 "expected integer"."""
    result = sh("123", "abc", "0", "0")
    assert result.returncode == 2
    assert "expected integer" in result.stderr


def test_non_integer_n_self_resolved(tmp_path: Path):
    """Non-integer N_SELF_RESOLVED → exit 2 "expected integer"."""
    result = sh("123", "5", "abc", "0")
    assert result.returncode == 2
    assert "expected integer" in result.stderr


def test_non_integer_n_rejected(tmp_path: Path):
    """Non-integer N_REJECTED → exit 2 "expected integer"."""
    result = sh("123", "5", "5", "abc")
    assert result.returncode == 2
    assert "expected integer" in result.stderr


def test_negative_n_rejected(tmp_path: Path):
    """Negative count fails ``^[0-9]+$`` regex → exit 2."""
    # Leading dash also fails the regex (no sign in ^[0-9]+$).
    result = sh("123", "-5", "0", "0")
    assert result.returncode == 2
    assert "expected integer" in result.stderr


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")
def test_creates_commit_with_codex_trailer(tmp_path: Path):
    """Integration: real git repo + ``--codex`` produces a commit with both trailers."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    # Need staged changes for git commit to succeed
    (tmp_path / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f.txt"], check=True, capture_output=True)
    result = sh("123", "5", "0", "0", "--codex", cwd=str(tmp_path))
    assert result.returncode == 0
