"""Tests for ``bin/commit_action_item.py``.

``subprocess.run`` and ``which`` monkeypatched — no real git invocations.
Tests cover arg validation, empty-stage short-circuit, sentinel lifecycle,
successful commit path, and the pure ``_slug`` function.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

import commit_action_item as cai


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def test_missing_message_file_arg_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No args → exit 1 with '--message-file required' on stderr."""
    rc = cai.main([])
    assert rc == 1
    assert "--message-file required" in capsys.readouterr().err


def test_message_file_not_found_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--message-file`` points to non-existent path → exit 1 'not found'."""
    rc = cai.main(["--message-file", str(tmp_path / "nonexistent.txt")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_missing_files_arg_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Valid ``--message-file`` but no ``--files`` → exit 1 '--files requires'."""
    msg = tmp_path / "msg.txt"
    msg.write_text("commit msg\n")
    rc = cai.main(["--message-file", str(msg)])
    assert rc == 1
    assert "--files requires" in capsys.readouterr().err


def test_unknown_arg_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Unrecognized flag → exit 1 with 'unknown arg' on stderr."""
    rc = cai.main(["--unknown"])
    assert rc == 1
    assert "unknown arg" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Commit path (subprocess mocked)
# ---------------------------------------------------------------------------


def _make_git_mock(
    *,
    empty_stage: bool = False,
    commit_rc: int = 0,
    calls: list[list[str]] | None = None,
) -> Any:
    """Return a fake ``subprocess.run`` for git operations."""

    def _fake_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        if calls is not None:
            calls.append(list(cmd))
        binary = Path(cmd[0]).name
        subcmd = cmd[1] if len(cmd) > 1 else ""
        if binary == "git" and subcmd == "rev-parse":
            return _FakeCompleted(returncode=0, stdout="/repo/my-project\n")
        if binary == "git" and subcmd == "branch":
            return _FakeCompleted(returncode=0, stdout="main\n")
        if binary == "git" and subcmd == "add":
            return _FakeCompleted(returncode=0)
        if binary == "git" and subcmd == "diff":
            # returncode 0 = no diff = empty stage; non-zero = has staged changes
            return _FakeCompleted(returncode=0 if empty_stage else 1)
        if binary == "git" and subcmd == "commit":
            return _FakeCompleted(returncode=commit_rc)
        return _FakeCompleted(returncode=0)

    return _fake_run


def test_empty_stage_exits_0(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Staging area empty after add → exit 0, 'staging area empty' in stderr."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock(empty_stage=True))
    rc = cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    assert rc == 0
    assert "staging area empty" in capsys.readouterr().err


def test_empty_stage_no_commit_called(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty staging area → git commit never invoked."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    calls: list[list[str]] = []
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock(empty_stage=True, calls=calls))
    cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    commit_calls = [c for c in calls if "commit" in c]
    assert not commit_calls


def test_successful_commit_exits_0(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Staged changes + commit rc 0 → exit 0."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock())
    rc = cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    assert rc == 0


def test_commit_failure_forwards_returncode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """git commit exits non-zero → that exit code forwarded."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock(commit_rc=1))
    rc = cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    assert rc == 1


def test_commit_called_with_message_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Commit invoked with ``-F <msg_file>``."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    calls: list[list[str]] = []
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock(calls=calls))
    cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    commit_calls = [c for c in calls if "commit" in c]
    assert len(commit_calls) == 1
    assert "-F" in commit_calls[0]
    assert str(msg) in commit_calls[0]


def test_sentinel_created_before_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sentinel file exists at the time git commit is called."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    sentinel_seen: list[bool] = []
    fake_tmpdir = tmp_path / "tmp"
    fake_tmpdir.mkdir()

    def _fake_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        binary = Path(cmd[0]).name
        subcmd = cmd[1] if len(cmd) > 1 else ""
        if binary == "git" and subcmd == "rev-parse":
            return _FakeCompleted(returncode=0, stdout="/repo/my-project\n")
        if binary == "git" and subcmd == "branch":
            return _FakeCompleted(returncode=0, stdout="main\n")
        if binary == "git" and subcmd == "commit":
            # Check sentinel files in fake tmpdir
            sentinel_seen.append(any(f.name.startswith("claude-commit-auth-") for f in fake_tmpdir.iterdir()))
        return _FakeCompleted(returncode=0 if subcmd != "diff" else 1)

    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _fake_run)
    # SEC-M7: commit_action_item now prefers TMPDIR / XDG_RUNTIME_DIR over
    # tempfile.gettempdir() — set TMPDIR so the sentinel lands in our fake dir.
    monkeypatch.setenv("TMPDIR", str(fake_tmpdir))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmpdir))
    cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])
    assert sentinel_seen == [True]


def test_git_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``which`` returns None for git → FileNotFoundError raised."""
    msg = tmp_path / "msg.txt"
    msg.write_text("msg\n")
    monkeypatch.setattr(cai, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="git"):
        cai.main(["--message-file", str(msg), "--files", str(tmp_path / "f.py")])


# ---------------------------------------------------------------------------
# _slug — pure function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("main", "main"),
        ("My/Repo Name", "my-repo-name"),
        ("feature/add-thing!", "feature-add-thing"),
        ("UPPER-CASE", "upper-case"),
        ("trailing-", "trailing"),
        ("multi---dashes", "multi-dashes"),
    ],
)
def test_slug(text: str, expected: str) -> None:
    """``_slug`` lowercases, replaces non-alnum runs, strips trailing hyphens."""
    assert cai._slug(text) == expected


# ---------------------------------------------------------------------------
# build_each_message — pure function (each-mode template)
# ---------------------------------------------------------------------------


def test_build_each_message_structure() -> None:
    """``each`` message has subject, attribution block, challenge line, Claude trailer."""
    fields = cai.EachMessageFields(
        summary="Fix off-by-one",
        item_id="7",
        author="octocat",
        pr="42",
        comment="The loop bound is wrong and should be len(x) - 1 not len(x) here in the inner pass",
        challenge="evidence=VALID suggestion=REJECT resolution=self-resolved",
    )
    msg = cai.build_each_message(fields)
    assert msg.splitlines()[0] == "Fix off-by-one"
    assert "[resolve #7] Review by @octocat (PR #42):" in msg
    assert "Challenge: evidence=VALID suggestion=REJECT resolution=self-resolved" in msg
    assert "Co-authored-by: claude[bot]" in msg
    assert "Co-authored-by: OpenAI Codex" not in msg


def test_build_each_message_truncates_comment_to_72_chars() -> None:
    """Comment body is truncated to the first 72 chars."""
    long_comment = "x" * 200
    msg = cai.build_each_message(cai.EachMessageFields("s", "1", "a", "9", long_comment, "evidence=VALID"))
    assert '"' + "x" * 72 + '..."' in msg
    assert "x" * 73 not in msg


def test_build_each_message_codex_trailer_opt_in() -> None:
    """``include_codex=True`` appends the Codex co-author trailer."""
    msg = cai.build_each_message(cai.EachMessageFields("s", "1", "a", "9", "c", "evidence=VALID", include_codex=True))
    assert "Co-authored-by: OpenAI Codex <codex@openai.com>" in msg


def test_build_mode_and_message_file_conflict_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """``--build`` with ``--message-file`` → exit 1 with conflict message."""
    rc = cai.main(["--build", "--message-file", "m.txt", "--files", "a.py"])
    assert rc == 1
    assert "not both" in capsys.readouterr().err


def test_build_mode_commits_rendered_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--build`` renders a temp message file and commits it via ``-F``."""
    calls: list[list[str]] = []
    monkeypatch.setattr(cai, "which", lambda _: "/fake/git")
    monkeypatch.setattr(cai.subprocess, "run", _make_git_mock(calls=calls))
    rc = cai.main(
        [
            "--build",
            "--summary",
            "Fix typo",
            "--item-id",
            "3",
            "--author",
            "octocat",
            "--pr",
            "42",
            "--comment",
            "fix the typo",
            "--challenge",
            "evidence=VALID",
            "--files",
            "a.py",
        ]
    )
    assert rc == 0
    commit_calls = [c for c in calls if "commit" in c]
    assert len(commit_calls) == 1
    assert "-F" in commit_calls[0]
