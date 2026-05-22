"""Tests for ``bin/release_setup.py``.

All git subprocess calls are monkeypatched via a sequential fake that
returns pre-configured ``(returncode, stdout)`` pairs in call order.
No real ``git`` invocations occur. The stable-branch path (3 git calls)
and fallback path (8 calls) are both covered.
"""

from __future__ import annotations

import shlex
from typing import Any

import pytest

import release_setup as rs


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _patch_git_sequence(monkeypatch: pytest.MonkeyPatch, *outcomes: tuple[int, str]) -> list[list[str]]:
    """Register a sequential subprocess.run fake; return recorded command lists."""
    call_n = [0]
    recorded: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        recorded.append(list(cmd))
        idx = call_n[0]
        call_n[0] += 1
        rc, out = outcomes[idx] if idx < len(outcomes) else (0, "")
        return _FakeCompleted(returncode=rc, stdout=out)

    monkeypatch.setattr(rs.subprocess, "run", _fake_run)
    monkeypatch.setattr(rs, "which", lambda _: "/fake/git")
    return recorded


def test_stable_branch_all_keys_emitted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Stable branch (BRANCH_TAG found) → all 7 keys present in stdout, exit 0."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),  # rev-parse --show-toplevel
        (0, "main"),  # branch --show-current
        (0, "v1.0.0"),  # describe --first-parent → branch tag
    )
    rc = rs.main()
    assert rc == 0
    out = capsys.readouterr().out
    for key in (
        "SKILL_DIR=",
        "REPO_ROOT=",
        "BRANCH=",
        "DATE=",
        "LAST_TAG=",
        "CHERRY_PICK_SUBJECTS=",
        "SOURCE_TAG_REF=",
    ):
        assert key in out


def test_stable_branch_last_tag_value(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Stable branch → LAST_TAG equals the first-parent describe result."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),
        (0, "main"),
        (0, "v2.3.1"),
    )
    rs.main()
    out = capsys.readouterr().out
    assert f"LAST_TAG={shlex.quote('v2.3.1')}" in out
    assert f"SOURCE_TAG_REF={shlex.quote('')}" in out


def test_branch_slash_replaced_with_hyphen(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Branch name containing '/' → slashes replaced with '-' in BRANCH output."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),
        (0, "feature/my-thing"),
        (0, "v1.0.0"),
    )
    rs.main()
    out = capsys.readouterr().out
    assert f"BRANCH={shlex.quote('feature-my-thing')}" in out


def test_fallback_path_emits_source_and_cherry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fallback path (no first-parent tag) → LAST_TAG from common ancestor, SOURCE_TAG_REF set."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),  # rev-parse
        (0, "main"),  # branch
        (1, ""),  # describe --first-parent → no branch tag
        (0, "v0.9.0"),  # describe → source tag
        (0, "abc123"),  # rev-list -n1 refs/tags/v0.9.0
        (0, "def456"),  # merge-base
        (0, "v0.8.0"),  # describe def456 → last tag
        (0, "cp1\ncp2"),  # git log v0.8.0..v0.9.0
    )
    rc = rs.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert f"LAST_TAG={shlex.quote('v0.8.0')}" in out
    assert f"SOURCE_TAG_REF={shlex.quote('v0.9.0')}" in out


def test_fallback_path_stderr_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Fallback path → 'Stable-branch mode' banner on stderr."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),
        (0, "main"),
        (1, ""),
        (0, "v0.9.0"),
        (0, "abc123"),
        (0, "def456"),
        (0, "v0.8.0"),
        (0, ""),
    )
    rs.main()
    captured = capsys.readouterr()
    assert "Stable-branch mode" in captured.err


def test_no_tags_uses_initial_commit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """No stable tags found → 'No stable tags found' on stderr, still exits 0."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/repo"),  # rev-parse
        (0, "main"),  # branch
        (1, ""),  # describe --first-parent → empty
        (1, ""),  # describe → no source tag
        (0, "abc0123"),  # rev-list --max-parents=0 → first commit
        (1, ""),  # rev-list -n1 refs/tags/abc0123 → fail
        (0, "def456"),  # merge-base
        (1, ""),  # describe def456 → no tag
        (0, ""),  # git log
    )
    rc = rs.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "No stable tags found" in captured.err


def test_output_lines_are_key_equals_quoted_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every stdout line matches ``KEY='value'`` bash-eval-safe format."""
    _patch_git_sequence(
        monkeypatch,
        (0, "/my/repo"),
        (0, "main"),
        (0, "v1.0.0"),
    )
    rs.main()
    out = capsys.readouterr().out
    import re

    key_re = re.compile(r"^[A-Z_]+=")
    for line in out.splitlines():
        assert key_re.match(line), f"line not KEY=value format: {line!r}"


def test_git_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``which`` returns None → FileNotFoundError propagates."""
    monkeypatch.setattr(rs, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="git"):
        rs.main()
