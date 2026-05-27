"""Subprocess tests for ``hooks/commit-guard.js``.

The hook gates ``git commit`` Bash calls behind a per-repo / per-branch
sentinel file under ``/tmp/claude-commit-auth-<repo-slug>-<branch-slug>``.
Each test spins up a small disposable git repo so the hook can resolve
``git rev-parse --show-toplevel`` and ``git branch --show-current``.

Three behavioural areas are covered:

* **Sentinel gating** — missing / fresh / expired sentinel maps to
  ``exit 2`` / ``exit 0`` / ``exit 2``.
* **SessionStart wipe** — clears leftover sentinels from prior runs.
* **UserPromptSubmit auto-arm** — explicit ``"commit this"``-style
  prompts pre-create the sentinel so the next ``git commit`` passes
  without an intervening manual ``touch``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


SENTINEL_PATH = Path("/tmp/claude-commit-auth-myrepo-main")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo named ``myrepo`` on branch ``main`` with one commit."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("test", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    return repo


@pytest.fixture
def clean_sentinel() -> Iterator[None]:
    """Remove any leftover sentinel before AND after each test."""
    SENTINEL_PATH.unlink(missing_ok=True)
    yield
    SENTINEL_PATH.unlink(missing_ok=True)


# ── Payload helpers ──────────────────────────────────────────────────────────


def _bash_commit(cmd: str = "git commit -m 'test'") -> dict:
    """Build a ``PreToolUse(Bash)`` payload for a commit-style command."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }


def _session_start() -> dict:
    """Build a ``SessionStart`` payload."""
    return {"hook_event_name": "SessionStart"}


def _user_prompt(prompt_text: str) -> dict:
    """Build a ``UserPromptSubmit`` payload."""
    return {"hook_event_name": "UserPromptSubmit", "user_message": prompt_text}


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
@pytest.mark.usefixtures("clean_sentinel")
class TestCommitGuard:
    """commit-guard.js: sentinel-based git-commit authorisation."""

    def test_blocks_commit_without_sentinel(self, git_repo: Path, run_hook) -> None:
        """No sentinel → hook exits 2 and prints a 'no commit authorization' message."""
        result = run_hook("commit-guard.js", _bash_commit(), cwd=git_repo)

        assert result.returncode == 2
        assert "no commit authorization" in result.stderr

    def test_allows_commit_with_fresh_sentinel(self, git_repo: Path, run_hook) -> None:
        """Fresh sentinel (< 15-min TTL) → hook exits 0."""
        SENTINEL_PATH.touch()

        result = run_hook("commit-guard.js", _bash_commit(), cwd=git_repo)

        assert result.returncode == 0, result.stderr

    def test_blocks_expired_sentinel(self, git_repo: Path, run_hook) -> None:
        """Sentinel with mtime 20 min ago is past the 15-min TTL → exit 2."""
        SENTINEL_PATH.touch()
        old = time.time() - 20 * 60
        os.utime(SENTINEL_PATH, (old, old))

        result = run_hook("commit-guard.js", _bash_commit(), cwd=git_repo)

        assert result.returncode == 2
        assert "expired" in result.stderr

    def test_session_start_clears_sentinel(self, git_repo: Path, run_hook) -> None:
        """SessionStart wipes any leftover sentinel from a prior session."""
        SENTINEL_PATH.touch()
        assert SENTINEL_PATH.exists()

        result = run_hook("commit-guard.js", _session_start(), cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert not SENTINEL_PATH.exists()

    def test_user_prompt_commit_creates_sentinel(self, git_repo: Path, run_hook) -> None:
        """UserPromptSubmit with 'commit this' auto-arms the per-branch sentinel."""
        result = run_hook("commit-guard.js", _user_prompt("commit this"), cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert SENTINEL_PATH.exists()

    def test_non_commit_bash_passes_through(self, git_repo: Path, run_hook) -> None:
        """Non-commit Bash command bypasses the gate regardless of sentinel state."""
        result = run_hook("commit-guard.js", _bash_commit(cmd="echo hello"), cwd=git_repo)

        assert result.returncode == 0, result.stderr
