"""Subprocess tests for ``hooks/rtk-rewrite.js``.

The hook is a ``PreToolUse`` gate that rewrites read-heavy Bash commands to
their ``rtk <cmd>`` equivalents and auto-approves them. Its security contract:

* **Read-only rewrite** — only commands the hook can prove read-only are
  rewritten with ``permissionDecision:"allow"``; everything else passes
  through unchanged (empty stdout, exit 0) so the real allow/deny matcher sees
  the original string.
* **No deny bypass** — because a rewrite mutates the command string (and thus
  dodges the settings.json deny list), mutating subcommands on mixed CLIs
  (``git push``, ``gh pr comment``, ``gh api -X POST``, ``docker rm`` …) must
  NEVER be rewritten. They passthrough to real permission checking.
* **No result corruption** — ``diff`` is never rewritten (rtk alters its exit
  status / "identical" summary).

These tests require ``rtk`` to be resolvable on ``PATH``; when it is not, the
hook is a deliberate no-op and the behavioural contract cannot be exercised, so
the suite is skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "rtk-rewrite.js"

pytestmark = [
    pytest.mark.skipif(
        shutil.which("node") is None,
        reason="requires node to execute the hook",
    ),
    pytest.mark.skipif(
        shutil.which("rtk") is None,
        reason="hook is a no-op without rtk on PATH — contract not exercisable",
    ),
]


def _run(command: str) -> dict:
    """Invoke the hook with a Bash tool payload and return parsed stdout (or {})."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["node", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"hook exited {proc.returncode}: {proc.stderr}"
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def _rewritten_to(result: dict) -> str | None:
    """Extract the rewritten command from a hook result, or None on passthrough.

    Examples:
        >>> _rewritten_to({"hookSpecificOutput": {"updatedInput": {"command": "rtk git status"}}})
        'rtk git status'
        >>> _rewritten_to({}) is None
        True
    """
    try:
        return result["hookSpecificOutput"]["updatedInput"]["command"]
    except (KeyError, TypeError):
        return None


# ── Read-only commands are rewritten + auto-allowed ───────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("git status", id="git-status"),
        pytest.param("git diff HEAD", id="git-diff"),
        pytest.param("git log --oneline -5", id="git-log"),
        pytest.param("git show HEAD", id="git-show"),
        pytest.param("gh pr view 42", id="gh-pr-view"),
        pytest.param("gh issue list", id="gh-issue-list"),
        pytest.param("gh api repos/owner/repo", id="gh-api-get"),
        pytest.param("docker ps", id="docker-ps"),
        pytest.param("kubectl get pods", id="kubectl-get"),
        pytest.param("aws ec2 describe-instances", id="aws-describe"),
        pytest.param("aws s3 ls", id="aws-s3-ls"),
        pytest.param("pytest tests/", id="pytest"),
        pytest.param("ruff check .", id="ruff"),
        pytest.param("grep -r foo .", id="grep"),
        pytest.param("ls -la", id="ls"),
    ],
)
def test_readonly_commands_are_rewritten_and_allowed(command: str) -> None:
    """Provably read-only commands get an rtk rewrite with allow decision."""
    result = _run(command)
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _rewritten_to(result) == f"rtk {command}"


# ── Mutating / dangerous commands must NEVER be rewritten (no deny bypass) ─────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("git push origin main", id="git-push"),
        pytest.param("git branch -D feature", id="git-branch-delete"),
        pytest.param("git reset --hard HEAD", id="git-reset-hard"),
        pytest.param("git commit -m x", id="git-commit"),
        pytest.param("gh pr comment 42 --body hi", id="gh-pr-comment"),
        pytest.param("gh pr create --title x", id="gh-pr-create"),
        pytest.param("gh issue close 42", id="gh-issue-close"),
        pytest.param("gh release create v1", id="gh-release-create"),
        pytest.param("gh api -X POST repos/o/r/issues", id="gh-api-post-short"),
        pytest.param("gh api --method DELETE repos/o/r/x", id="gh-api-delete-long"),
        pytest.param("docker rm -f box", id="docker-rm"),
        pytest.param("kubectl delete pod x", id="kubectl-delete"),
        pytest.param("aws s3 rm s3://bucket/key", id="aws-s3-rm"),
    ],
)
def test_mutating_commands_passthrough_unchanged(command: str) -> None:
    """Mutating subcommands are never rewritten; they passthrough to real checks."""
    result = _run(command)
    assert result == {}, f"{command!r} was rewritten — deny bypass risk: {result}"


# ── Compound commands must never be rewritten (chaining deny-bypass) ───────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("git status && git push origin main", id="and-push"),
        pytest.param("git status; git push", id="semicolon-push"),
        pytest.param("git status $(git push)", id="cmd-subst"),
        pytest.param("git diff HEAD `git push`", id="backtick"),
        pytest.param("git status && rm -rf /tmp/x", id="and-rm"),
        pytest.param("gh pr view 42 && gh pr merge 42", id="gh-merge-chain"),
        pytest.param("aws ec2 describe-instances && aws s3 rm s3://b/k", id="aws-rm-chain"),
        pytest.param("pytest tests/ && rm -rf build", id="safe-prefix-chain"),
        pytest.param("git log | tee /tmp/out", id="pipe"),
        pytest.param("git log > /tmp/out", id="redirect"),
    ],
)
def test_compound_commands_are_never_rewritten(command: str) -> None:
    """A read-only prefix followed by any shell operator must passthrough whole."""
    result = _run(command)
    assert result == {}, f"{command!r} was rewritten — chaining bypass: {result}"


# ── git branch create must not be rewritten ───────────────────────────────────


def test_git_branch_create_passthrough() -> None:
    """Create a branch (mutation) — never rewritten."""
    assert _run("git branch newfeature") == {}


# ── find is never rewritten (destructive flags carry no shell metacharacter) ──


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("find . -name '*.py' -delete", id="find-delete"),
        pytest.param("find . -type f -exec rm {} +", id="find-exec-plus"),
        pytest.param("find . -fprintf /etc/target payload", id="find-fprintf"),
        pytest.param("find . -name '*.py'", id="find-read-only"),
    ],
)
def test_find_is_never_rewritten(command: str) -> None:
    """``find`` passes through whole.

    ``-delete``, ``-exec ... {} +`` and ``-fprintf`` mutate the filesystem while carrying no character that
    ``SHELL_META`` catches, so a prefix match would auto-approve them. The read-only spelling passes through too — the
    prefix is excluded outright rather than filtered.
    """
    result = _run(command)
    assert result == {}, f"{command!r} was rewritten — destructive find bypass: {result}"


# ── cargo / next: inspection rewritten, execution passthrough ─────────────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("cargo tree", id="cargo-tree"),
        pytest.param("cargo metadata --no-deps", id="cargo-metadata"),
        pytest.param("next info", id="next-info"),
    ],
)
def test_guarded_build_tool_inspection_is_rewritten(command: str) -> None:
    """Inspection subcommands of cargo/next still earn the rewrite."""
    result = _run(command)
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _rewritten_to(result) == f"rtk {command}"


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("cargo install ripgrep", id="cargo-install"),
        pytest.param("cargo run --release", id="cargo-run"),
        pytest.param("cargo check", id="cargo-check-runs-build-rs"),
        pytest.param("next build", id="next-build"),
        pytest.param("next dev", id="next-dev"),
    ],
)
def test_guarded_build_tool_execution_passthrough(command: str) -> None:
    """Subcommands that execute arbitrary project code are never rewritten.

    ``cargo check`` is included: it runs ``build.rs``, so it executes project code even though it produces no binary.
    """
    result = _run(command)
    assert result == {}, f"{command!r} was rewritten — arbitrary execution: {result}"


# ── Result-corrupting commands are excluded ───────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("diff a.txt b.txt", id="diff"),
        pytest.param("curl -X POST https://api.example.com", id="curl-post"),
        pytest.param("wget --post-data=x https://example.com", id="wget-post"),
        pytest.param("psql -c 'DROP TABLE users'", id="psql-drop"),
    ],
)
def test_excluded_commands_passthrough(command: str) -> None:
    """Diff (result corruption) and curl/wget/psql (unprovable intent) passthrough."""
    result = _run(command)
    assert result == {}, f"{command!r} should passthrough, got: {result}"


# ── Basic hook hygiene ────────────────────────────────────────────────────────


def test_already_prefixed_command_passthrough() -> None:
    """A command already starting with 'rtk ' is left untouched (no double wrap)."""
    assert _run("rtk git status") == {}


def test_non_bash_tool_passthrough() -> None:
    """Non-Bash tool payloads are ignored."""
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    proc = subprocess.run(["node", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
