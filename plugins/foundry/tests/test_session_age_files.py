"""Tests for ``bin/session_age_files.py``.

Pure ``age_days`` covered by doctest; this file exercises filesystem-bound
behaviour using ``tmp_path`` and CLI surface via ``capsys``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


import session_age_files  # noqa: E402


def _touch_with_age(path: Path, age_days: int, now: float) -> None:
    """Create ``path`` and set its mtime to ``now - age_days * 86400``."""
    path.write_text("", encoding="utf-8")
    mtime = now - age_days * 86400
    os.utime(path, (mtime, mtime))


class TestListSessionFiles:
    """list_session_files: directory enumeration + age computation."""

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        """Missing directory yields empty list, not an exception."""
        result = session_age_files.list_session_files(tmp_path / "does-not-exist")
        assert result == []

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Existing directory with no matching files yields empty list."""
        assert session_age_files.list_session_files(tmp_path) == []

    def test_only_matching_glob(self, tmp_path: Path) -> None:
        """Files not matching ``session-open-*.md`` are ignored."""
        now = time.time()
        match = tmp_path / "session-open-foo.md"
        non_match_1 = tmp_path / "session-closed-foo.md"
        non_match_2 = tmp_path / "notes.md"
        for p in (match, non_match_1, non_match_2):
            _touch_with_age(p, 1, now)

        pairs = session_age_files.list_session_files(tmp_path, now=now)
        paths = [p for _, p in pairs]
        assert paths == [match]

    def test_age_computation(self, tmp_path: Path) -> None:
        """Reported ages match mtime differences in whole days (floor)."""
        now = time.time()
        f0 = tmp_path / "session-open-fresh.md"
        f5 = tmp_path / "session-open-week.md"
        f31 = tmp_path / "session-open-stale.md"
        _touch_with_age(f0, 0, now)
        _touch_with_age(f5, 5, now)
        _touch_with_age(f31, 31, now)

        pairs = session_age_files.list_session_files(tmp_path, now=now)
        ages_by_name = {p.name: age for age, p in pairs}
        assert ages_by_name == {
            "session-open-fresh.md": 0,
            "session-open-week.md": 5,
            "session-open-stale.md": 31,
        }


class TestMain:
    """main: CLI surface — stdout format + exit codes."""

    def test_prints_tab_separated_lines(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Output is one ``<age>\\t<path>`` line per file, exit 0."""
        now = time.time()
        target = tmp_path / "session-open-a.md"
        _touch_with_age(target, 3, now)

        rc = session_age_files.main([str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        # Tab separator, age first, then path.
        lines = [ln for ln in out.splitlines() if ln]
        assert len(lines) == 1
        age_str, path_str = lines[0].split("\t", 1)
        assert age_str == "3"
        assert path_str == str(target)

    def test_missing_dir_exit_0_no_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Missing session-dir → exit 0 with no stdout (not an error)."""
        rc = session_age_files.main([str(tmp_path / "nope")])
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_empty_dir_exit_0_no_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Existing empty dir → exit 0 with no stdout."""
        rc = session_age_files.main([str(tmp_path)])
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_no_args_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Missing required arg — argparse exits with code 2."""
        with pytest.raises(SystemExit) as exc:
            session_age_files.main([])
        assert exc.value.code == 2
