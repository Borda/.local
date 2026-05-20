"""Tests for ``bin/fetch_gh_data_group1.sh``.

The script performs Group 1 parallel ``gh`` API data fetches for the
oss:gh-scraper agent. Required flags: ``--repo`` and ``--output-dir``.
All actual data fetching is integration-only (real gh API). Unit tests
cover argument parsing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "fetch_gh_data_group1.sh"


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


def test_missing_repo(tmp_path: Path):
    """No ``--repo`` → exit 1 "--repo required"."""
    result = sh("--output-dir", str(tmp_path))
    assert result.returncode == 1
    assert "--repo required" in result.stderr


def test_missing_output_dir(tmp_path: Path):
    """``--repo`` but no ``--output-dir`` → exit 1 "--output-dir required"."""
    result = sh("--repo", "owner/repo")
    assert result.returncode == 1
    assert "--output-dir required" in result.stderr


def test_unknown_arg(tmp_path: Path):
    """Unrecognized flag → exit 1 "unknown arg"."""
    result = sh("--unknown")
    assert result.returncode == 1
    assert "unknown arg" in result.stderr


def test_no_args_fails():
    """No args at all → exit 1 (required flag missing)."""
    result = sh()
    assert result.returncode == 1
    assert "--repo required" in result.stderr
