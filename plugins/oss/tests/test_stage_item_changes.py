"""Tests for ``bin/stage_item_changes.py``.

``subprocess.run`` and module-level ``which`` are monkeypatched — no real
``git`` invocations. The shared helper ``_patch_git`` dispatches on git
subcommand so each test can configure only the response it cares about.
"""

from __future__ import annotations

from typing import Any

import pytest

import stage_item_changes as sic


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _patch_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stash_list_out: str = "",
    pop_rc: int = 0,
    diff_out: str = "",
    ls_out: str = "",
) -> list[list[str]]:
    """Register subprocess.run fake dispatching on git subcommand; return recorded commands."""
    recorded: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        recorded.append(list(cmd))
        if cmd[1] == "stash":
            if cmd[2] == "list":
                return _FakeCompleted(stdout=stash_list_out)
            return _FakeCompleted(returncode=pop_rc)
        if cmd[1] == "diff":
            return _FakeCompleted(stdout=diff_out)
        if cmd[1] == "ls-files":
            return _FakeCompleted(stdout=ls_out)
        return _FakeCompleted()

    monkeypatch.setattr(sic.subprocess, "run", _fake_run)
    monkeypatch.setattr(sic, "which", lambda _: "/fake/git")
    return recorded


def test_missing_item_id_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """No item_id argument → exit 1 with error on stderr before any git call."""
    rc = sic.main([])
    assert rc == 1
    assert "item_id required" in capsys.readouterr().err


def test_no_stash_match_skips_pop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stash list has no matching label → stash pop never called, exit 0."""
    recorded = _patch_git(monkeypatch, stash_list_out="stash@{0}: unrelated entry\n")
    rc = sic.main(["AI5"])
    assert rc == 0
    pop_calls = [c for c in recorded if c[1] == "stash" and c[2] == "pop"]
    assert pop_calls == []


def test_matching_stash_pop_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stash list contains matching label → stash pop invoked once, exit 0."""
    recorded = _patch_git(monkeypatch, stash_list_out="stash@{0}: resolve-pre-item-AI5\n")
    rc = sic.main(["AI5"])
    assert rc == 0
    pop_calls = [c for c in recorded if c[1] == "stash" and c[2] == "pop"]
    assert len(pop_calls) == 1


def test_stash_pop_failure_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Stash pop returns non-zero → exit 1 with conflict message on stderr."""
    _patch_git(monkeypatch, stash_list_out="stash@{0}: resolve-pre-item-AI7\n", pop_rc=1)
    rc = sic.main(["AI7"])
    assert rc == 1
    assert "stash pop conflict" in capsys.readouterr().err


def test_changed_files_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Files from ``git diff HEAD`` are passed to ``git add``."""
    recorded = _patch_git(monkeypatch, diff_out="src/foo.py\n")
    sic.main(["item1"])
    add_cmds = [c for c in recorded if c[1] == "add"]
    assert any("src/foo.py" in c for c in add_cmds)


def test_changed_files_include_nested_spaces_deleted_and_extensionless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tracked diff output is staged exactly, regardless of path shape or extension."""
    changed = "src/pkg/foo.py\ndocs/file with spaces.md\ndeleted.txt\nMakefile\n"
    recorded = _patch_git(monkeypatch, diff_out=changed)
    sic.main(["item1"])
    add_cmds = [c for c in recorded if c[1] == "add"]
    assert [
        "/fake/git",
        "add",
        "--",
        "src/pkg/foo.py",
        "docs/file with spaces.md",
        "deleted.txt",
        "Makefile",
    ] in add_cmds


def test_untracked_source_files_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Untracked files with source extension are passed to ``git add``."""
    recorded = _patch_git(monkeypatch, ls_out="new_script.py\n")
    sic.main(["item1"])
    add_cmds = [c for c in recorded if c[1] == "add"]
    assert any("new_script.py" in c for c in add_cmds)


def test_untracked_nonsource_files_not_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Untracked files without a recognised source extension are not staged."""
    recorded = _patch_git(monkeypatch, ls_out="image.png\nnotes.pdf\n")
    sic.main(["item1"])
    add_cmds = [c for c in recorded if c[1] == "add"]
    staged = [f for cmd in add_cmds for f in cmd[3:]]
    assert "image.png" not in staged
    assert "notes.pdf" not in staged


def test_untracked_filter_stages_source_doc_config_and_dotfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only recognised source/config extensions from untracked output are staged."""
    untracked = "\n".join(
        [
            "nested/module.py",
            "docs/file with spaces.md",
            "config/settings.toml",
            ".pre-commit-config.yaml",
            "Makefile",
            "build/output.pyc",
            "image.png",
        ]
    )
    recorded = _patch_git(monkeypatch, ls_out=untracked)
    sic.main(["item1"])
    add_cmds = [c for c in recorded if c[1] == "add"]
    staged = [f for cmd in add_cmds for f in cmd[3:]]
    assert staged == ["nested/module.py", "docs/file with spaces.md", "config/settings.toml", ".pre-commit-config.yaml"]


def test_git_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``which`` returns None → FileNotFoundError propagates."""
    monkeypatch.setattr(sic, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="git"):
        sic.main(["item1"])
