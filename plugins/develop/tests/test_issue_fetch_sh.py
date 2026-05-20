"""Tests for ``bin/issue-fetch.sh``.

The script strips a leading ``#`` from the issue number and delegates to
``gh issue view <num> --comments``. It performs no input validation; any
real fetch is integration-only (requires ``gh`` auth and network).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parent.parent / "bin" / "issue-fetch.sh"


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


def _make_fake_gh(tmp_path: Path, exit_code: int = 0, stdout_text: str = "") -> Path:
    """Create a fake ``gh`` shim in ``tmp_path/bin/`` that records args and exits."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "gh"
    fake.write_text(
        f'#!/usr/bin/env bash\necho "ARGS=$*" > "{tmp_path}/gh-args.txt"\necho "{stdout_text}"\nexit {exit_code}\n'
    )
    fake.chmod(0o755)
    return fake


def test_strips_leading_hash(tmp_path: Path):
    """Leading ``#`` is removed before invoking gh."""
    _make_fake_gh(tmp_path, exit_code=0, stdout_text="ok")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh("#123", env=env)
    assert result.returncode == 0
    recorded = (tmp_path / "gh-args.txt").read_text()
    assert "ARGS=issue view 123 --comments" in recorded


def test_passes_number_without_hash(tmp_path: Path):
    """Bare numeric arg is forwarded unchanged."""
    _make_fake_gh(tmp_path, exit_code=0, stdout_text="ok")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh("456", env=env)
    assert result.returncode == 0
    recorded = (tmp_path / "gh-args.txt").read_text()
    assert "ARGS=issue view 456 --comments" in recorded


def test_propagates_gh_exit_code(tmp_path: Path):
    """When gh exits non-zero, the script returns that exit code."""
    _make_fake_gh(tmp_path, exit_code=42, stdout_text="boom")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh("789", env=env)
    assert result.returncode == 42


def test_missing_arg_rejected_by_validation(tmp_path: Path):
    """No arg → empty ``ISSUE_NUM`` fails the ``^[0-9]+$`` regex → exit 1; gh not invoked."""
    _make_fake_gh(tmp_path, exit_code=0, stdout_text="")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh(env=env)
    assert result.returncode == 1
    assert "invalid issue number" in result.stderr
    # gh must NOT have been invoked.
    assert not (tmp_path / "gh-args.txt").exists()


def test_non_numeric_arg_rejected(tmp_path: Path):
    """Letters → ``^[0-9]+$`` regex rejects → exit 1; gh not invoked."""
    _make_fake_gh(tmp_path, exit_code=0, stdout_text="")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh("abc", env=env)
    assert result.returncode == 1
    assert "invalid issue number" in result.stderr
    assert not (tmp_path / "gh-args.txt").exists()


def test_mocked_fetch_passes_through_output(tmp_path: Path):
    """Mocked fetch: gh stdout is forwarded and exit 0 is preserved."""
    _make_fake_gh(tmp_path, exit_code=0, stdout_text="Issue title: Fix the bug")
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    result = sh("#1", env=env)
    assert result.returncode == 0
    assert "Fix the bug" in result.stdout
