"""Tests for ``bin/health_monitor_start.py`` — research health-monitoring sentinel.

Covers:
* Happy-path: ``LAUNCH_AT`` + ``SENTINEL`` printed; sentinel file created
* Sentinel path format: ``research-<skill-id>-check-<ts>``
* ``LAUNCH_AT`` value embedded in sentinel path
* Missing skill-id → exit 1
* Invalid skill-id (unsafe chars) → exit 2
* Windows-portability invariants: ``sys.stdout.reconfigure`` present,
  ``_sentinel_dir()`` defined for platform-conditional sentinel path
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

import health_monitor_start

SCRIPT = Path(health_monitor_start.__file__)


def _parse_kv(output: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from stdout into a dict."""
    pairs: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            pairs[key] = value
    return pairs


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


class TestArgparse:
    """argparse-layer behaviour: --help and golden README invocation."""

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``--help`` prints usage and exits 0 (argparse SystemExit)."""
        with pytest.raises(SystemExit) as exc:
            health_monitor_start.main(["--help"])
        assert exc.value.code == 0
        assert "health_monitor_start.py" in capsys.readouterr().out

    def test_golden_readme_invocation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """README shape ``health_monitor_start.py <skill-id>`` → exit 0 with sentinel keys."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "research-run"
        try:
            rc = health_monitor_start.main([skill_id])
            assert rc == 0
            kv = _parse_kv(capsys.readouterr().out)
            assert kv["LAUNCH_AT"].isdigit()
            assert Path(kv["SENTINEL"]).name.startswith(f"research-{skill_id}-check-")
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)


class TestValidation:
    """Argument validation tests."""

    def test_missing_skill_id_exit_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No args → exit 1 with error on stderr."""
        rc = health_monitor_start.main([])
        assert rc == 1
        assert "skill-id" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "skill_id",
        ["bad/id", "bad id", "bad!id", "../evil"],
    )
    def test_invalid_skill_id_exit_two(self, skill_id: str, capsys: pytest.CaptureFixture[str]) -> None:
        """Skill-id with unsafe chars → exit 2 with SKILL_ID error on stderr."""
        rc = health_monitor_start.main([skill_id])
        assert rc == 2
        assert "SKILL_ID" in capsys.readouterr().err


class TestHappyPath:
    """Integration tests for valid invocations."""

    def test_exit_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Valid skill-id → exit 0."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-exitcode"
        try:
            rc = health_monitor_start.main([skill_id])
            assert rc == 0
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)

    def test_emits_launch_at_and_sentinel(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Output contains both ``LAUNCH_AT`` and ``SENTINEL`` keys."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-kv"
        try:
            health_monitor_start.main([skill_id])
            kv = _parse_kv(capsys.readouterr().out)
            assert "LAUNCH_AT" in kv
            assert "SENTINEL" in kv
            assert kv["LAUNCH_AT"].isdigit()
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)

    def test_sentinel_file_created(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Sentinel path printed in stdout exists on disk."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-file"
        try:
            health_monitor_start.main([skill_id])
            kv = _parse_kv(capsys.readouterr().out)
            sentinel = Path(kv["SENTINEL"])
            assert sentinel.exists()
            assert sentinel.name.startswith(f"research-{skill_id}-check-")
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)

    def test_launch_at_matches_sentinel_timestamp(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``LAUNCH_AT`` value appears as trailing ``<ts>`` in sentinel path."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-tsmatch"
        try:
            health_monitor_start.main([skill_id])
            kv = _parse_kv(capsys.readouterr().out)
            m = re.search(r"-check-(\d+)$", kv["SENTINEL"])
            assert m is not None
            assert m.group(1) == kv["LAUNCH_AT"]
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)

    def test_output_has_no_crlf(self, capsys: pytest.CaptureFixture[str]) -> None:
        """stdout must not contain CRLF (Windows text-mode regression guard)."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-crlf"
        try:
            health_monitor_start.main([skill_id])
            out = capsys.readouterr().out
            assert "\r" not in out
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)

    def test_sentinel_path_uses_forward_slashes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SENTINEL value uses forward slashes (bash-compatible even on Windows)."""
        sentinel_base = Path(tempfile.gettempdir()) if sys.platform == "win32" else Path("/tmp")
        skill_id = "test-skill-posix"
        try:
            health_monitor_start.main([skill_id])
            kv = _parse_kv(capsys.readouterr().out)
            assert "\\" not in kv["SENTINEL"]
        finally:
            for stale in sentinel_base.glob(f"research-{skill_id}-check-*"):
                stale.unlink(missing_ok=True)
