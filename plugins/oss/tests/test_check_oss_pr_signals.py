"""Tests for ``bin/check_oss_pr_signals.py``.

Subprocess and ``shutil.which`` are monkeypatched throughout — no real ``gh``
or ``git`` invocation. Tests cover argv validation, the four signal checks,
and JSON output routing (stdout vs ``--output-file``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import check_oss_pr_signals as cops  # type: ignore[import-not-found]


# --------------------------------------------------------------------------- #
# Fake subprocess scaffolding
# --------------------------------------------------------------------------- #


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``which`` + ``subprocess.run``.

    Returns a dict with:
        - ``responses``: ``dict[str, str]`` mapping command-key prefix → stdout.
        - ``calls``: list of recorded argv lists.

    Command-key prefix is the first 3 tokens after the binary basename
    (e.g. ``"gh:pr:diff:--"`` for ``gh pr diff <N> -- pyproject.toml ...``).
    Unknown keys return empty stdout.
    """
    state: dict[str, Any] = {"responses": {}, "calls": []}

    def _fake_which(cmd: str) -> str:
        return f"/fake/{cmd}"

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        state["calls"].append(list(cmd))
        # Look up a response by progressively shorter prefix
        basename = Path(cmd[0]).name
        # Build candidate keys from longest to shortest using non-flag tokens
        non_flag = [t for t in cmd[1:] if not t.startswith("--") and not t.startswith(":")]
        for take in range(min(4, len(non_flag)), 0, -1):
            key = ":".join([basename] + non_flag[:take])
            if key in state["responses"]:
                return _FakeCompleted(returncode=0, stdout=state["responses"][key])
        # Default empty
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(cops, "which", _fake_which)
    monkeypatch.setattr(cops.subprocess, "run", _fake_run)
    return state


# --------------------------------------------------------------------------- #
# argv / validation
# --------------------------------------------------------------------------- #


class TestMainArgValidation:
    """argv plumbing — required flags, numeric check, missing tools."""

    def test_missing_clean_args_exits_2(self) -> None:
        """argparse exits 2 when --clean-args missing."""
        with pytest.raises(SystemExit) as exc:
            cops.main([])
        assert exc.value.code == 2

    def test_non_numeric_clean_args_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Non-numeric PR identifier rejected before any subprocess."""
        rc = cops.main(["--clean-args", "abc; rm -rf /"])
        assert rc == 1
        assert "numeric PR number" in capsys.readouterr().err

    def test_gh_missing_exits_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``which`` returning None for gh → exit 2."""
        monkeypatch.setattr(cops, "which", lambda cmd: None if cmd == "gh" else "/fake/git")
        rc = cops.main(["--clean-args", "42"])
        assert rc == 2
        assert "gh" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Pure helpers — already doctested; add edge cases
# --------------------------------------------------------------------------- #


class TestGrepSecrets:
    """Edge cases beyond the docstring examples."""

    def test_short_value_skipped(self) -> None:
        """7-char value below the 8-char threshold → not flagged."""
        assert cops._grep_secrets("+password = 'short12'") == []

    def test_dedupes_repeats(self) -> None:
        """Same line repeated → appears once."""
        diff = "+token=abcdef12345\n+token=abcdef12345\n"
        assert cops._grep_secrets(diff) == ["+token=abcdef12345"]

    def test_case_insensitive_match(self) -> None:
        """Uppercase keyword still matches."""
        assert cops._grep_secrets("+PASSWORD = 'longenoughval'") == ["+PASSWORD = 'longenoughval'"]


class TestExtractRemovedExports:
    """Boundary cases — diff headers, mixed +/- blocks."""

    def test_ignores_added_lines(self) -> None:
        """Lines starting with ``+`` are skipped."""
        assert cops._extract_removed_exports("+only_added") == []

    def test_ignores_diff_headers(self) -> None:
        """``---`` and ``+++`` headers do not contribute symbols."""
        diff = "--- a/src/x/__init__.py\n+++ b/src/x/__init__.py\n-Removed\n"
        assert cops._extract_removed_exports(diff) == ["Removed"]


# --------------------------------------------------------------------------- #
# End-to-end: collect_signals via fake subprocess
# --------------------------------------------------------------------------- #


class TestCollectSignals:
    """Wire up collect_signals against the fake subprocess fixture."""

    def test_happy_path_aggregates_all_signals(self, fake_subprocess: dict[str, Any]) -> None:
        """All four checks contribute to the resulting dataclass."""
        fake_subprocess["responses"] = {
            "gh:pr:diff:42:pyproject.toml": "+numpy>=2.0\n",
            "gh:pr:diff:42:*.py": "+password = 'longenough12'\n+x = 1\n",
            "gh:pr:diff:42": "-OldExport\n+NewExport\n",
            "git:show:v1.0.0": "OldExport = None\n",
            "git:describe": "",
        }
        signals = cops.collect_signals(
            clean_args="42",
            latest_tag="v1.0.0",
            timeout=5,
            gh="/fake/gh",
            git="/fake/git",
        )
        assert "+numpy>=2.0" in signals.deps_diff
        assert any("password" in line for line in signals.secret_matches)
        assert "OldExport" in signals.removed_exports
        assert signals.latest_tag == "v1.0.0"
        assert any("DEPRECATION_NEEDED" in f for f in signals.deprecation_findings)

    def test_no_latest_tag_emits_no_release_tag_finding(self, fake_subprocess: dict[str, Any]) -> None:
        """Empty ``latest_tag`` + git describe empty → NO_RELEASE_TAG marker."""
        signals = cops.collect_signals(
            clean_args="42",
            latest_tag="",
            timeout=5,
            gh="/fake/gh",
            git="/fake/git",
        )
        assert signals.latest_tag == ""
        assert signals.deprecation_findings == [
            "NO_RELEASE_TAG: cannot determine release history — skip deprecation check"
        ]

    def test_unreleased_removal_when_symbol_absent_from_tag(
        self,
        fake_subprocess: dict[str, Any],
    ) -> None:
        """Removed symbol not present at the latest tag → UNRELEASED_REMOVAL."""
        fake_subprocess["responses"] = {
            "gh:pr:diff:42": "-NewlyAddedThenRemoved\n",
            # git show returns text NOT containing the symbol
            "git:show:v0.5.0": "Unrelated = 1\n",
        }
        signals = cops.collect_signals(
            clean_args="42",
            latest_tag="v0.5.0",
            timeout=5,
            gh="/fake/gh",
            git="/fake/git",
        )
        assert any("UNRELEASED_REMOVAL: NewlyAddedThenRemoved" in f for f in signals.deprecation_findings)


# --------------------------------------------------------------------------- #
# Output routing
# --------------------------------------------------------------------------- #


class TestOutputRouting:
    """Stdout vs --output-file paths."""

    def test_stdout_default(
        self,
        fake_subprocess: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No --output-file → JSON to stdout, exit 0."""
        rc = cops.main(["--clean-args", "42", "--latest-tag", "v1"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "deps_diff" in data
        assert data["latest_tag"] == "v1"

    def test_output_file_write(
        self,
        fake_subprocess: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """--output-file path → JSON written to disk."""
        out_path = tmp_path / "signals.json"
        rc = cops.main(["--clean-args", "42", "--output-file", str(out_path)])
        assert rc == 0
        data = json.loads(out_path.read_text())
        assert set(data.keys()) >= {
            "deps_diff",
            "secret_matches",
            "removed_exports",
            "deprecation_findings",
            "latest_tag",
            "changelog_diff",
        }


# --------------------------------------------------------------------------- #
# Subprocess timeout handling
# --------------------------------------------------------------------------- #


class TestTimeoutResilience:
    """Timeouts return empty strings rather than propagating."""

    def test_timeout_yields_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``subprocess.TimeoutExpired`` → empty stdout, no raise."""

        def _raise_timeout(*_args: Any, **_kwargs: Any) -> _FakeCompleted:
            raise subprocess.TimeoutExpired(cmd=["fake"], timeout=1)

        monkeypatch.setattr(cops.subprocess, "run", _raise_timeout)
        assert cops._run(["/fake/gh", "pr", "diff", "1"], timeout=1) == ""
