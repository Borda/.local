"""Tests for ``bin/commit_lint_fixes.py``.

``subprocess.run`` and module-level ``which`` are monkeypatched — no real
``git`` invocations. Tests cover the no-op path (empty diff) and the
stage-and-commit path, including commit-failure forwarding.
"""

from __future__ import annotations

from typing import Any
import subprocess

import pytest

import commit_lint_fixes as clf


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_no_changed_files_prints_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty ``git diff HEAD`` → prints no-op message and exits 0."""
    monkeypatch.setattr(
        clf.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout=""),
    )
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    rc = clf.main()
    assert rc == 0
    assert "[lint] no changed files" in capsys.readouterr().out


def test_no_changed_files_no_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty diff → ``git commit`` never invoked."""
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        calls.append(list(cmd))
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    clf.main()
    assert all("commit" not in c for c in calls)


def test_changed_files_stages_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changed file in diff → ``git add`` then ``git commit`` both invoked."""
    call_n = [0]
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        calls.append(list(cmd))
        call_n[0] += 1
        stdout = "foo.py\n" if call_n[0] == 1 else ""
        return _FakeCompleted(returncode=0, stdout=stdout)

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    rc = clf.main()
    assert rc == 0
    subcmds = [c[1] for c in calls]
    assert "add" in subcmds
    assert "commit" in subcmds


def test_changed_files_are_added_before_commit_with_exact_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple changed files, including spaces, are passed as separate git-add args before commit."""
    call_n = [0]
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        calls.append(list(cmd))
        call_n[0] += 1
        stdout = "src/a.py\ndocs/file with spaces.md\n" if call_n[0] == 1 else ""
        return _FakeCompleted(returncode=0, stdout=stdout)

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    rc = clf.main()

    assert rc == 0
    add_index = next(i for i, cmd in enumerate(calls) if cmd[1] == "add")
    commit_index = next(i for i, cmd in enumerate(calls) if cmd[1] == "commit")
    assert add_index < commit_index
    assert calls[add_index] == ["/fake/git", "add", "--", "src/a.py", "docs/file with spaces.md"]
    assert calls[commit_index][:3] == ["/fake/git", "commit", "-m"]


def test_git_add_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """git add check=True failures are not converted into a misleading successful commit."""
    call_n = [0]

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        call_n[0] += 1
        if call_n[0] == 1:
            return _FakeCompleted(returncode=0, stdout="src/a.py\n")
        if cmd[1] == "add":
            raise subprocess.CalledProcessError(returncode=2, cmd=cmd)
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        clf.main()
    assert exc_info.value.returncode == 2


def test_changed_files_commit_message_contains_lint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit message body references lint fix."""
    call_n = [0]
    commit_msgs: list[str] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        call_n[0] += 1
        if call_n[0] == 1:
            return _FakeCompleted(returncode=0, stdout="changed.py\n")
        if "commit" in cmd:
            commit_msgs.append(cmd[cmd.index("-m") + 1])
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    clf.main()
    assert commit_msgs
    assert "lint" in commit_msgs[0].lower()


def test_commit_failure_forwards_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """``git commit`` returning non-zero → ``main`` returns that exit code."""
    call_n = [0]

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        call_n[0] += 1
        if call_n[0] == 1:
            return _FakeCompleted(returncode=0, stdout="bar.py\n")
        if "commit" in cmd:
            return _FakeCompleted(returncode=1, stdout="")
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(clf.subprocess, "run", _fake_run)
    monkeypatch.setattr(clf, "which", lambda _: "/fake/git")
    rc = clf.main()
    assert rc == 1


def test_git_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``which`` returns None → FileNotFoundError propagates."""
    monkeypatch.setattr(clf, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="git"):
        clf.main()
