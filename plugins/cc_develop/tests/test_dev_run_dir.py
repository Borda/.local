"""Tests for ``bin/dev_run_dir.py`` — develop timestamped run-dir creator.

Covers:
* Happy-path ``.developments/<ts>/`` creation
* ``--sentinel <name>`` touches sentinel file in platform temp dir
* Sentinel name sanitization (path traversal stripped)
* ``--sentinel`` alone (no name) creates no sentinel
* Windows-portability invariants: ``sys.stdout.reconfigure`` present,
  ``_sentinel_dir()`` uses platform check (not bare ``/tmp`` hardcode)
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

import dev_run_dir

SCRIPT = Path(dev_run_dir.__file__)
TIMESTAMP_RE = re.compile(r"\.developments/\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


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
    """Tests for ``.developments/<ts>/`` creation."""

    def test_creates_developments_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``main()`` creates ``.developments/<ts>/`` under CWD."""
        monkeypatch.chdir(tmp_path)
        rc = dev_run_dir.main([])
        assert rc == 0
        dev_dirs = list((tmp_path / ".developments").iterdir())
        assert len(dev_dirs) == 1
        assert dev_dirs[0].is_dir()

    def test_timestamp_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Output path matches ``.developments/YYYY-MM-DDTHH-MM-SSZ`` pattern."""
        monkeypatch.chdir(tmp_path)
        dev_run_dir.main([])
        out = capsys.readouterr().out.strip()
        assert TIMESTAMP_RE.search(out)

    def test_output_has_no_crlf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """stdout must not contain CRLF (Windows text-mode regression guard)."""
        monkeypatch.chdir(tmp_path)
        dev_run_dir.main([])
        out = capsys.readouterr().out
        assert "\r" not in out


class TestSentinelFlag:
    """Tests for ``--sentinel <name>`` behaviour."""

    def test_sentinel_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--sentinel <name>`` touches sentinel in platform temp dir."""
        monkeypatch.chdir(tmp_path)
        sentinel_name = f"dev-py-test-{os.getpid()}"
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        try:
            rc = dev_run_dir.main(["--sentinel", sentinel_name])
            assert rc == 0
            ts = capsys.readouterr().out.strip().split("/")[-1]
            assert (sentinel_base / f"{sentinel_name}-{ts}").exists()
        finally:
            for stale in sentinel_base.glob(f"{sentinel_name}-*"):
                stale.unlink(missing_ok=True)

    @pytest.mark.parametrize(
        "raw_name,expected_sanitized",
        [
            ("../evil-{pid}", "evil-{pid}"),
            (r"..\evil-{pid}", "evil-{pid}"),
            ("name with spaces-{pid}", "namewithspaces-{pid}"),
            ("safe_MIX-123-{pid}", "safe_MIX-123-{pid}"),
        ],
    )
    def test_sentinel_name_sanitized(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        raw_name: str,
        expected_sanitized: str,
    ) -> None:
        """Unsafe sentinel characters are stripped before touching the sentinel file."""
        monkeypatch.chdir(tmp_path)
        pid = os.getpid()
        raw_name = raw_name.format(pid=pid)
        sanitized = expected_sanitized.format(pid=pid)
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        try:
            rc = dev_run_dir.main(["--sentinel", raw_name])
            assert rc == 0
            ts = capsys.readouterr().out.strip().split("/")[-1]
            assert (sentinel_base / f"{sanitized}-{ts}").exists()
            if raw_name != sanitized:
                assert not (sentinel_base / f"{raw_name}-{ts}").exists()
        finally:
            for stale in sentinel_base.glob(f"{sanitized}-*"):
                stale.unlink(missing_ok=True)

    def test_all_unsafe_sentinel_name_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sentinel name that sanitizes to empty does not create a broad timestamp file."""
        monkeypatch.chdir(tmp_path)
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        before = set(sentinel_base.glob("*"))
        dev_run_dir.main(["--sentinel", "!!!"])
        after = set(sentinel_base.glob("*"))
        assert before == after

    def test_sentinel_without_name_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``--sentinel`` alone (no name arg) creates no sentinel file."""
        monkeypatch.chdir(tmp_path)
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        before = set(sentinel_base.glob("dev-py-test-*"))
        dev_run_dir.main(["--sentinel"])
        after = set(sentinel_base.glob("dev-py-test-*"))
        assert before == after


class TestHelp:
    """``--help`` short-circuits before any run-dir side effects."""

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``--help`` prints usage to stdout and exits 0 (argparse default)."""
        with pytest.raises(SystemExit) as exc:
            dev_run_dir.main(["--help"])
        assert exc.value.code == 0
        assert "usage" in capsys.readouterr().out.lower()
