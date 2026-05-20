"""Tests for ``bin/release_setup.sh``.

The script resolves the skill directory, git repo root, branch slug,
current UTC date, and last-stable-tag baseline. Emits KEY=value lines
on stdout (for caller ``eval``). Heavy git usage → marked integration.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")

SCRIPT = Path(__file__).parent.parent / "bin" / "release_setup.sh"


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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one initial commit on main."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_emits_key_value_pairs(git_repo: Path):
    """Output contains ``SKILL_DIR=``, ``REPO_ROOT=``, ``BRANCH=``, ``DATE=``, ``LAST_TAG=``."""
    result = sh(cwd=str(git_repo))
    assert result.returncode == 0
    for key in ("SKILL_DIR=", "REPO_ROOT=", "BRANCH=", "DATE=", "LAST_TAG="):
        assert key in result.stdout
