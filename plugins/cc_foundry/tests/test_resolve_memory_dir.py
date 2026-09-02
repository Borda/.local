"""Tests for ``bin/resolve_memory_dir.py``.

Pure ``slugify`` covered by doctest in the source module; this file exercises git-bound behaviour via ``monkeypatch``
and the CLI surface via ``capsys``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest


import resolve_memory_dir  # noqa: E402


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_run(monkeypatch: pytest.MonkeyPatch, responder: Any) -> None:
    monkeypatch.setattr(resolve_memory_dir.subprocess, "run", responder)


class TestSlugify:
    """Slugify: canonical lowercase + non-alnum squeeze + trailing strip."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("MyProject", "myproject"),
            ("foo_bar", "foo-bar"),
            ("foo/bar/baz", "foo-bar-baz"),
            ("foo--bar", "foo-bar"),
            ("trailing-", "trailing"),
            ("trailing---", "trailing"),
            ("/abs/path/Borda.local", "-abs-path-borda-local"),
            ("UPPER_CASE!@#mix", "upper-case-mix"),
            ("", ""),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str) -> None:
        """All edge cases map to the documented canonical slug."""
        assert resolve_memory_dir.slugify(raw) == expected


class TestResolveMemoryDir:
    """resolve_memory_dir: combines git fallback + slug + HOME."""

    def test_explicit_project_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit arg bypasses git lookup entirely."""

        def boom(*_: Any, **__: Any) -> _FakeCompleted:  # pragma: no cover
            raise AssertionError("subprocess.run must not be called when project given")

        _patch_run(monkeypatch, boom)
        monkeypatch.setenv("HOME", "/home/test")
        result = resolve_memory_dir.resolve_memory_dir("/some/Project")
        assert Path(result).as_posix() == "/home/test/.claude/projects/-some-project/memory"

    def test_git_fallback_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty arg → git rev-parse provides the root."""

        def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
            return _FakeCompleted(stdout="/Users/x/Project\n", returncode=0)

        _patch_run(monkeypatch, fake_run)
        monkeypatch.setenv("HOME", "/home/test")
        result = resolve_memory_dir.resolve_memory_dir(None)
        assert Path(result).as_posix() == "/home/test/.claude/projects/-users-x-project/memory"

    def test_git_fallback_no_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Git fails (non-zero) → None."""

        def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
            return _FakeCompleted(stdout="", stderr="fatal: not a git repository\n", returncode=128)

        _patch_run(monkeypatch, fake_run)
        assert resolve_memory_dir.resolve_memory_dir(None) is None

    def test_git_missing_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Git not on PATH → FileNotFoundError swallowed, returns None."""

        def fake_run(*_: Any, **__: Any) -> _FakeCompleted:
            raise FileNotFoundError("git")

        _patch_run(monkeypatch, fake_run)
        assert resolve_memory_dir.resolve_memory_dir(None) is None

    def test_empty_string_arg_falls_back_to_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty-string arg treated the same as None — git fallback engaged."""
        calls = {"n": 0}

        def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
            calls["n"] += 1
            return _FakeCompleted(stdout="/repo\n", returncode=0)

        _patch_run(monkeypatch, fake_run)
        monkeypatch.setenv("HOME", "/h")
        result = resolve_memory_dir.resolve_memory_dir("")
        assert Path(result).as_posix() == "/h/.claude/projects/-repo/memory"
        assert calls["n"] == 1


class TestMain:
    """Main: CLI surface — stdout + exit codes."""

    def test_no_arg_with_git(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No CLI arg + git repo → prints resolved path, exit 0."""

        def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
            return _FakeCompleted(stdout="/Users/x/Repo\n", returncode=0)

        _patch_run(monkeypatch, fake_run)
        monkeypatch.setenv("HOME", "/h")
        rc = resolve_memory_dir.main([])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert Path(out).as_posix() == "/h/.claude/projects/-users-x-repo/memory"

    def test_explicit_arg(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Explicit project root prints corresponding memory path, exit 0."""
        monkeypatch.setenv("HOME", "/h")
        rc = resolve_memory_dir.main(["/some/Project"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert Path(out).as_posix() == "/h/.claude/projects/-some-project/memory"

    def test_exit_1_when_no_git_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No arg + git failure → exit 1, no stdout."""

        def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
            return _FakeCompleted(stdout="", returncode=128)

        _patch_run(monkeypatch, fake_run)
        rc = resolve_memory_dir.main([])
        assert rc == 1
        assert capsys.readouterr().out == ""

    def test_home_expansion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """HOME env var honoured — proves ``os.path.expanduser`` integration."""
        monkeypatch.setenv("HOME", "/custom/home")
        rc = resolve_memory_dir.main(["/x"])
        assert rc == 0
        assert Path(capsys.readouterr().out.strip()).as_posix().startswith("/custom/home/.claude/projects/")
