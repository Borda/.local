"""Subprocess tests for ``hooks/commit-guard.js``.

The hook does NOT gate ``git commit`` at all — commit authorization is
prompt-discipline only (see ``rules/git-commit.md``), no runtime check.
The hook gates only ``git push``, behind a per-repo / per-branch sentinel
file named ``claude-push-auth-<repo-slug>-<branch-slug>`` under the hook's own
sentinel dir (``/tmp`` on POSIX, ``os.tmpdir()`` on Windows). Each test
spins up a small disposable git repo so the hook can resolve
``git rev-parse --show-toplevel`` and ``git branch --show-current``.

Behavioural areas covered:

* **Commit passthrough** — ``git commit`` always exits 0, sentinel or not;
  the hook never inspects it.
* **Push gating** — force-push is blocked unconditionally on any branch
  (even with a valid sentinel); a regular push requires a fresh push
  sentinel and is never auto-armed by a ``"push"``-mentioning prompt.
* **SessionStart wipe** — clears leftover push sentinels from prior runs.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from _hook_env import hook_tmp_base

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True, timeout=5).returncode != 0,
    reason="requires functional git (XCode CLI tools or equivalent)",
)

# Repo/branch slugs come from the hook's own toSlug() over `git rev-parse` and
# `git branch --show-current`; the git_repo fixture pins them to myrepo/main.
_SENTINEL_NAME = "claude-push-auth-myrepo-main"


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
def push_sentinel() -> Iterator[Path]:
    """Yield the push sentinel path, removing any leftover before AND after each test.

    Resolved through ``hook_tmp_base()`` rather than a module-level ``/tmp`` literal so
    the path follows the hook's own ``getSentinelDir()`` on Windows too. Kept lazy —
    the base is computed inside the fixture, after the module-level git skipif has run.
    """
    path = hook_tmp_base() / _SENTINEL_NAME
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


# ── Payload helpers ──────────────────────────────────────────────────────────


def _bash_commit(cmd: str = "git commit -m 'test'") -> dict:
    """Build a ``PreToolUse(Bash)`` payload for a commit-style command."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }


def _bash_push(cmd: str = "git push") -> dict:
    """Build a ``PreToolUse(Bash)`` payload for a push-style command."""
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


@pytest.mark.usefixtures("push_sentinel")
class TestCommitGuard:
    """commit-guard.js: push-only sentinel gate; commit is prompt-discipline only."""

    def test_commit_always_passes_through(self, git_repo: Path, run_hook) -> None:
        """git commit exits 0 unconditionally — the hook never inspects it, no sentinel involved."""
        result = run_hook("commit-guard.js", _bash_commit(), cwd=git_repo)

        assert result.returncode == 0, result.stderr

    def test_non_push_bash_passes_through(self, git_repo: Path, run_hook) -> None:
        """Non-push Bash command bypasses the gate regardless of sentinel state."""
        result = run_hook("commit-guard.js", _bash_push(cmd="echo hello"), cwd=git_repo)

        assert result.returncode == 0, result.stderr

    def test_session_start_clears_push_sentinel(self, git_repo: Path, run_hook, push_sentinel: Path) -> None:
        """SessionStart wipes any leftover push sentinel from a prior session."""
        push_sentinel.touch()
        assert push_sentinel.exists()

        result = run_hook("commit-guard.js", _session_start(), cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert not push_sentinel.exists()

    def test_force_push_blocked_any_branch(self, git_repo: Path, run_hook) -> None:
        """Force-push with no sentinel → exit 2 with a 'force'/'forbidden' message."""
        result = run_hook("commit-guard.js", _bash_push(cmd="git push --force"), cwd=git_repo)

        assert result.returncode == 2
        assert "force" in result.stderr
        assert "forbidden" in result.stderr

    def test_force_push_blocked_even_with_sentinel(self, git_repo: Path, run_hook, push_sentinel: Path) -> None:
        """A valid push sentinel does NOT bypass the force block — force check runs first → exit 2."""
        push_sentinel.touch()

        result = run_hook("commit-guard.js", _bash_push(cmd="git push --force"), cwd=git_repo)

        assert result.returncode == 2

    def test_push_blocked_without_sentinel(self, git_repo: Path, run_hook) -> None:
        """Plain push with no sentinel → exit 2 and stderr points at AskUserQuestion."""
        result = run_hook("commit-guard.js", _bash_push(), cwd=git_repo)

        assert result.returncode == 2
        assert "AskUserQuestion" in result.stderr

    def test_push_allowed_with_fresh_sentinel(self, git_repo: Path, run_hook, push_sentinel: Path) -> None:
        """Plain push with a fresh push sentinel (< 15-min TTL) → exit 0."""
        push_sentinel.touch()

        result = run_hook("commit-guard.js", _bash_push(), cwd=git_repo)

        assert result.returncode == 0, result.stderr

    def test_push_not_auto_armed_by_prompt(self, git_repo: Path, run_hook, push_sentinel: Path) -> None:
        """UserPromptSubmit mentioning 'push' must NOT auto-arm the push sentinel."""
        result = run_hook("commit-guard.js", _user_prompt("push this"), cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert not push_sentinel.exists()
