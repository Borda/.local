"""Tests for ``bin/pytest-gate.sh``.

The script validates ``PYTEST_CMD`` against an allowlist of three values
(``pytest``, ``uv run pytest``, ``python -m pytest``) and execs pytest
with ``--tb=short`` and ``-v``. Rejected commands exit 2 with stderr
"rejected unsafe PYTEST_CMD" before any process runs.

The happy path is integration-only (actually runs pytest collection).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "pytest-gate.sh"


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


def test_unknown_cmd_rejected():
    """Arbitrary string not in allowlist → exit 2, stderr "rejected"."""
    result = sh("malicious; rm -rf", "tests/")
    assert result.returncode == 2
    assert "rejected" in result.stderr


def test_injection_attempt_rejected():
    """Shell-injection payload not in allowlist → exit 2."""
    result = sh("python3 -c 'os.system(\"echo pwn\")'", "tests/")
    assert result.returncode == 2
    assert "rejected" in result.stderr


def test_partial_match_rejected():
    """``pytest-something`` not exact match → exit 2."""
    result = sh("pytest-something-else", "tests/")
    assert result.returncode == 2
    assert "rejected" in result.stderr


@pytest.mark.parametrize("cmd", ["pytest", "uv run pytest", "python -m pytest"])
def test_allowlist_member_not_rejected(cmd: str, tmp_path: Path):
    """Allowlist members are NOT rejected (exit != 2 — actual pytest may fail with 4/5)."""
    # Pass an empty tmp_path as target so pytest collects nothing (exit 5),
    # but never returns 2 (which is the script-level rejection code).
    result = sh(cmd, str(tmp_path))
    assert result.returncode != 2


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires pytest invocation")
def test_valid_cmd_runs(tmp_path: Path):
    """End-to-end: pytest is exec'd and reports its own exit code."""
    result = sh("pytest", str(tmp_path), "--collect-only")
    # pytest exit code: 0 (passed) or 5 (no tests collected) — never 2.
    assert result.returncode in (0, 5)
