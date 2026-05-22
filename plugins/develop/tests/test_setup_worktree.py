"""Tests for ``bin/setup_worktree.py`` — team-mode subagent handoff dir creator.

Covers:
* Two-line output: timestamp on line 1, ``.temp/develop/<ts>`` on line 2
* Directory created on disk
* ``--sentinel <name>`` touches sentinel in platform temp dir
* Sentinel name sanitization (path traversal stripped)
* Windows-portability invariants: ``sys.stdout.reconfigure`` present,
  ``_sentinel_dir()`` defined for platform-conditional sentinel path
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

import setup_worktree

SCRIPT = Path(setup_worktree.__file__)
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


class TestPortabilityInvariants:
    """Source-level Windows-portability checks."""

    def test_stdout_reconfigure_present(self) -> None:
        """``sys.stdout.reconfigure(...)`` must be called in ``main()``."""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "sys.stdout.reconfigure" in src

    def test_sentinel_dir_function_defined(self) -> None:
        """``_sentinel_dir()`` helper must exist — proves platform-conditional logic."""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "_sentinel_dir" in src

    def test_shebang_env_python(self) -> None:
        """Shebang must be ``#!/usr/bin/env python`` (not ``python3``)."""
        first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "#!/usr/bin/env python"

    def test_no_utcnow(self) -> None:
        """``datetime.utcnow()`` deprecated in 3.12 — must not appear in source."""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "utcnow" not in src


class TestRunDirCreation:
    """Tests for ``.temp/develop/<ts>/`` creation and two-line output."""

    def test_creates_run_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``main()`` creates ``.temp/develop/<ts>/`` under CWD."""
        monkeypatch.chdir(tmp_path)
        rc = setup_worktree.main([])
        assert rc == 0
        assert (tmp_path / ".temp" / "develop").is_dir()

    def test_output_two_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Output is exactly two non-empty lines."""
        monkeypatch.chdir(tmp_path)
        setup_worktree.main([])
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 2

    def test_line1_is_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Line 1 matches ``YYYY-MM-DDTHH-MM-SSZ`` UTC timestamp pattern."""
        monkeypatch.chdir(tmp_path)
        setup_worktree.main([])
        ts = capsys.readouterr().out.strip().splitlines()[0]
        assert TIMESTAMP_RE.match(ts)

    def test_line2_is_run_dir_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Line 2 is ``.temp/develop/<ts>`` matching the timestamp on line 1."""
        monkeypatch.chdir(tmp_path)
        setup_worktree.main([])
        ts, run_dir = capsys.readouterr().out.strip().splitlines()
        assert run_dir == f".temp/develop/{ts}"
        assert (tmp_path / run_dir).is_dir()

    def test_output_has_no_crlf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """stdout must not contain CRLF (Windows text-mode regression guard)."""
        monkeypatch.chdir(tmp_path)
        setup_worktree.main([])
        out = capsys.readouterr().out
        assert "\r" not in out


class TestSentinelFlag:
    """Tests for ``--sentinel <name>`` behaviour."""

    def test_sentinel_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--sentinel <name>`` touches sentinel in platform temp dir."""
        monkeypatch.chdir(tmp_path)
        sentinel_name = f"swt-py-test-{os.getpid()}"
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        try:
            rc = setup_worktree.main(["--sentinel", sentinel_name])
            assert rc == 0
            ts = capsys.readouterr().out.strip().splitlines()[0]
            assert (sentinel_base / f"{sentinel_name}-{ts}").exists()
        finally:
            for stale in sentinel_base.glob(f"{sentinel_name}-*"):
                stale.unlink(missing_ok=True)

    def test_sentinel_name_sanitized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``../evil`` stripped to ``evil`` — no path traversal via sentinel name."""
        monkeypatch.chdir(tmp_path)
        pid = os.getpid()
        raw_name = f"../evil-{pid}"
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", raw_name)
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        try:
            rc = setup_worktree.main(["--sentinel", raw_name])
            assert rc == 0
            ts = capsys.readouterr().out.strip().splitlines()[0]
            assert (sentinel_base / f"{sanitized}-{ts}").exists()
            assert not (sentinel_base / f"{raw_name}-{ts}").exists()
        finally:
            for stale in sentinel_base.glob(f"{sanitized}-*"):
                stale.unlink(missing_ok=True)
