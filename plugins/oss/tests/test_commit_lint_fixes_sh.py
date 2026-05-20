"""Tests for ``bin/commit_lint_fixes.sh``.

The script stages all tracked changed files and commits with a standard
``lint: auto-fix violations after resolve cycle`` message. No-ops cleanly
(``[lint] no changed files to commit``, exit 0) on a clean tree.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "commit_lint_fixes.sh"


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
def clean_git_repo(tmp_path: Path) -> Path:
    """Create an empty git repo with one initial commit on a clean tree."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_no_changes_clean_tree(clean_git_repo: Path):
    """Clean tree → exit 0, "[lint] no changed files to commit" on stdout."""
    result = sh(cwd=str(clean_git_repo))
    assert result.returncode == 0
    assert "[lint] no changed files" in result.stdout


def test_runs_outside_git_repo_gracefully(tmp_path: Path):
    """Outside a git repo: ``git diff`` is silenced with ``|| true`` → exit 0 nominal."""
    # git diff fails outside repo, but `|| true` swallows. CHANGED is empty → no-op branch.
    result = sh(cwd=str(tmp_path))
    assert result.returncode == 0
    assert "[lint] no changed files" in result.stdout


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")
def test_commits_changed_file(clean_git_repo: Path):
    """Integration: dirty tracked file → script stages and commits."""
    target = clean_git_repo / "tracked.py"
    target.write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(clean_git_repo), "add", str(target)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(clean_git_repo), "commit", "-m", "add tracked"],
        check=True,
        capture_output=True,
    )
    # Now modify the tracked file
    target.write_text("x = 2\n")
    result = sh(cwd=str(clean_git_repo))
    assert result.returncode == 0
