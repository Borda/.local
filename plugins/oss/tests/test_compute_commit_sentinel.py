"""Tests for compute_commit_sentinel.py."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from compute_commit_sentinel import get_sentinel_path, main, to_slug


class TestToSlug:
    def test_lowercase(self) -> None:
        assert to_slug("MyRepo") == "myrepo"

    def test_dots_become_dash(self) -> None:
        assert to_slug("MyRepo.local") == "myrepo-local"

    def test_slash_becomes_dash(self) -> None:
        assert to_slug("feature/my-branch") == "feature-my-branch"

    def test_consecutive_non_alnum_collapsed(self) -> None:
        assert to_slug("UPPER-CASE--extra-") == "upper-case-extra"

    def test_trailing_dash_stripped(self) -> None:
        assert to_slug("foo-") == "foo"

    def test_empty_string(self) -> None:
        assert to_slug("") == ""

    def test_plain_main(self) -> None:
        assert to_slug("main") == "main"

    def test_numeric_preserved(self) -> None:
        assert to_slug("repo123") == "repo123"


class TestGetSentinelPath:
    def _mock_git(self, repo_root: str, branch: str):
        def fake_check_output(cmd, **_kwargs):
            if "--show-toplevel" in cmd:
                return repo_root + "\n"
            if "--show-current" in cmd:
                return branch + "\n"
            raise AssertionError(f"unexpected git command: {cmd}")

        return patch("compute_commit_sentinel.subprocess.check_output", side_effect=fake_check_output)

    def test_basic_path(self) -> None:
        with self._mock_git("/home/user/MyRepo", "main"):
            path = get_sentinel_path()
        assert path == "/tmp/claude-commit-auth-myrepo-main"

    def test_dotted_repo_name(self) -> None:
        with self._mock_git("/projects/borda.local", "feature/add-tests"):
            path = get_sentinel_path()
        assert path == "/tmp/claude-commit-auth-borda-local-feature-add-tests"

    def test_uppercase_branch(self) -> None:
        with self._mock_git("/repo/proj", "HOTFIX/MY-FIX"):
            path = get_sentinel_path()
        assert path == "/tmp/claude-commit-auth-proj-hotfix-my-fix"

    def test_git_failure_raises(self) -> None:
        with patch(
            "compute_commit_sentinel.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                get_sentinel_path()


class TestMain:
    def test_success_prints_path(self, capsys) -> None:
        with patch(
            "compute_commit_sentinel.get_sentinel_path",
            return_value="/tmp/claude-commit-auth-repo-main",
        ):
            rc = main([])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "/tmp/claude-commit-auth-repo-main"

    def test_git_error_returns_1(self, capsys) -> None:
        with patch(
            "compute_commit_sentinel.get_sentinel_path",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            rc = main([])
        assert rc == 1
