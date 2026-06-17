"""Tests for bin/detect_codemap.py — codemap availability detection.

Covers: missing --prefix exit 2, --force-off, scan-query present/absent,
index present/absent, --strict mode errors, option overrides, env vars,
and _resolve_proj() helper.
"""

from __future__ import annotations

import subprocess
import unittest.mock as mock
from pathlib import Path

import pytest

import detect_codemap  # type: ignore[import-not-found]


class TestMain:
    """main() entry-point behaviour."""

    def test_missing_prefix_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No --prefix → exit 2, usage message on stderr."""
        rc = detect_codemap.main([])
        assert rc == 2
        assert "Usage" in capsys.readouterr().err

    def test_force_off_writes_false_and_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--force-off → writes 'false', exits 0 regardless of codemap state."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value=None):
            rc = detect_codemap.main(["--prefix", "test", "--force-off"])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "false\n"

    def test_scan_query_present_index_present_writes_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """scan-query on PATH + index file exists → writes 'true', exits 0."""
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()
        (idx_dir / "myproj.json").write_text("{}")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "myproj", "--idx-dir", str(idx_dir)])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "true\n"

    def test_scan_query_present_index_absent_writes_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """scan-query on PATH but no index file → writes 'false', exits 0."""
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "myproj", "--idx-dir", str(idx_dir)])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "false\n"

    def test_scan_query_absent_writes_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """scan-query not on PATH → writes 'false', exits 0."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value=None):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "myproj", "--idx-dir", str(tmp_path / "idx")])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "false\n"

    def test_strict_no_scan_query_exits_1_with_install_hint(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--strict + scan-query absent → exit 1, install hint on stderr."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value=None):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "proj", "--idx-dir", str(tmp_path), "--strict"])
        assert rc == 1
        assert "claude plugin install codemap@borda-ai-rig" in capsys.readouterr().err

    def test_strict_scan_query_no_index_exits_1_with_build_hint(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--strict + scan-query present + no index → exit 1, build-index hint on stderr."""
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "proj", "--idx-dir", str(idx_dir), "--strict"])
        assert rc == 1
        assert "/codemap:scan-codebase" in capsys.readouterr().err

    def test_proj_override_used_as_index_slug(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--proj overrides git-derived slug; index looked up as <proj>.json."""
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()
        (idx_dir / "custom-proj.json").write_text("{}")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "custom-proj", "--idx-dir", str(idx_dir)])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "true\n"

    def test_idx_dir_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--idx-dir overrides default .cache/codemap lookup path."""
        custom_idx = tmp_path / "custom-index"
        custom_idx.mkdir()
        (custom_idx / "proj.json").write_text("{}")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "proj", "--idx-dir", str(custom_idx)])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "true\n"

    def test_codemap_index_dir_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEMAP_INDEX_DIR env var sets default index dir when --idx-dir absent."""
        idx_dir = tmp_path / "env-idx"
        idx_dir.mkdir()
        (idx_dir / "envproj.json").write_text("{}")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("CODEMAP_INDEX_DIR", str(idx_dir))
        with mock.patch("detect_codemap.shutil.which", return_value="/usr/bin/scan-query"):
            rc = detect_codemap.main(["--prefix", "test", "--proj", "envproj"])
        assert rc == 0
        assert (tmp_path / "test-codemap-enabled").read_text() == "true\n"

    def test_tmpdir_env_var_controls_output_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TMPDIR env var controls where the output file is written."""
        out_dir = tmp_path / "mytmp"
        out_dir.mkdir()
        monkeypatch.setenv("TMPDIR", str(out_dir))
        with mock.patch("detect_codemap.shutil.which", return_value=None):
            rc = detect_codemap.main(["--prefix", "myprefix", "--proj", "proj", "--idx-dir", str(tmp_path)])
        assert rc == 0
        assert (out_dir / "myprefix-codemap-enabled").exists()


class TestResolveProj:
    """_resolve_proj() helper — git-based slug derivation."""

    def test_git_success_returns_sanitized_basename(self) -> None:
        """git rev-parse success → basename of toplevel, sanitized."""
        mock_result = mock.Mock(returncode=0, stdout="/home/user/my-project\n")
        with mock.patch("detect_codemap.subprocess.run", return_value=mock_result):
            proj = detect_codemap._resolve_proj(None)
        assert proj == "my-project"

    def test_git_nonzero_exit_returns_default(self) -> None:
        """git rev-parse non-zero exit → 'default'."""
        mock_result = mock.Mock(returncode=128, stdout="")
        with mock.patch("detect_codemap.subprocess.run", return_value=mock_result):
            proj = detect_codemap._resolve_proj(None)
        assert proj == "default"

    def test_git_timeout_returns_default(self) -> None:
        """subprocess.run raising TimeoutExpired → 'default'."""
        with mock.patch(
            "detect_codemap.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 5),
        ):
            proj = detect_codemap._resolve_proj(None)
        assert proj == "default"

    def test_proj_override_returned_directly_without_git(self) -> None:
        """proj_override bypasses git entirely and is returned as-is."""
        with mock.patch("detect_codemap.subprocess.run") as mock_run:
            proj = detect_codemap._resolve_proj("explicit-proj")
        mock_run.assert_not_called()
        assert proj == "explicit-proj"

    def test_special_chars_stripped_from_basename(self) -> None:
        """Non-alphanumeric/dot/dash/underscore chars stripped from git basename."""
        mock_result = mock.Mock(returncode=0, stdout="/tmp/my repo with spaces\n")
        with mock.patch("detect_codemap.subprocess.run", return_value=mock_result):
            proj = detect_codemap._resolve_proj(None)
        assert proj == "myrepowithspaces"

    def test_empty_basename_after_sanitize_returns_default(self) -> None:
        """Basename all-special chars → empty after sanitize → 'default' fallback."""
        mock_result = mock.Mock(returncode=0, stdout="/tmp/!!!\n")
        with mock.patch("detect_codemap.subprocess.run", return_value=mock_result):
            proj = detect_codemap._resolve_proj(None)
        assert proj == "default"
