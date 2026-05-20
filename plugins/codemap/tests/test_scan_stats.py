"""Tests for ``bin/scan-stats.py`` — codemap index summary printer."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_BIN = Path(__file__).resolve().parents[1] / "bin"

# scan-stats.py has a hyphen — importlib is required; direct `import` not possible.
_spec = importlib.util.spec_from_file_location("scan_stats", _BIN / "scan-stats.py")
assert _spec and _spec.loader, "scan-stats.py not found in bin/"
scan_stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_stats)  # type: ignore[union-attr]

_resolve_root = scan_stats._resolve_root
_load_index = scan_stats._load_index
main = scan_stats.main


# ---------------------------------------------------------------------------
# _resolve_root
# ---------------------------------------------------------------------------


class TestResolveRoot:
    """_resolve_root: root precedence — SCAN_ARGS → git → cwd."""

    def test_returns_root_from_scan_args(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--root in SCAN_ARGS within cwd is returned verbatim (as absolute path)."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        monkeypatch.chdir(tmp_path)
        result = _resolve_root(f"--root {subdir}", timeout=5)
        assert result == str(subdir)

    def test_traversal_attack_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--root outside cwd triggers sys.exit(2) (directory traversal guard)."""
        monkeypatch.chdir(tmp_path)
        outside = tmp_path.parent / "outside"
        with pytest.raises(SystemExit) as exc_info:
            _resolve_root(f"--root {outside}", timeout=5)
        assert exc_info.value.code == 2

    def test_falls_back_to_git_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SCAN_ARGS has no --root, falls back to git rev-parse output."""
        monkeypatch.chdir(tmp_path)
        fake_root = "/fake/git/root"
        with patch("subprocess.check_output", return_value=fake_root.encode()):
            result = _resolve_root("", timeout=5)
        assert result == fake_root

    def test_falls_back_to_cwd_when_git_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When git rev-parse fails, returns cwd."""
        monkeypatch.chdir(tmp_path)
        with patch("subprocess.check_output", side_effect=Exception("no git")):
            result = _resolve_root("", timeout=5)
        assert result == os.path.abspath(str(tmp_path))


# ---------------------------------------------------------------------------
# _load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    """_load_index: happy path and missing-file exit."""

    def test_returns_parsed_dict(self, tmp_path: Path) -> None:
        """Valid index JSON is parsed and returned as dict."""
        proj = tmp_path.name
        index_dir = tmp_path / ".cache" / "scan"
        index_dir.mkdir(parents=True)
        payload: dict[str, Any] = {"modules": [{"name": "foo", "status": "ok", "symbols": []}]}
        (index_dir / f"{proj}.json").write_text(json.dumps(payload))
        result = _load_index(str(tmp_path))
        assert result == payload

    def test_exits_when_index_missing(self, tmp_path: Path) -> None:
        """Missing index file causes sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            _load_index(str(tmp_path))
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _make_index(tmp_path: Path, modules: list[dict[str, Any]]) -> None:
    """Write a minimal index JSON at the expected path under tmp_path."""
    proj = tmp_path.name
    index_dir = tmp_path / ".cache" / "scan"
    index_dir.mkdir(parents=True)
    (index_dir / f"{proj}.json").write_text(json.dumps({"modules": modules}))


class TestMain:
    """main(): stdout output for typical index shapes."""

    def test_no_modules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty module list prints 'No modules indexed.' and exits 0."""
        _make_index(tmp_path, [])
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCAN_ARGS", "")
        with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "No modules indexed." in out

    def test_ok_modules_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Indexed modules: prints count, symbol total, and top-5 by rdep_count."""
        modules = [
            {"name": "alpha", "status": "ok", "rdep_count": 3, "symbols": [{"calls": []}, {"calls": []}]},
            {"name": "beta", "status": "ok", "rdep_count": 1, "symbols": [{"calls": [{}]}]},
            {"name": "gamma", "status": "degraded", "rdep_count": 0, "symbols": []},
        ]
        _make_index(tmp_path, modules)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCAN_ARGS", "")
        with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
            main()
        out = capsys.readouterr().out
        assert "2 indexed" in out
        assert "1 degraded" in out
        assert "Symbols: 3" in out
        assert "alpha" in out

    def test_calls_line_printed_for_v3_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Calls line is printed when at least one call edge exists."""
        modules = [
            {"name": "mod", "status": "ok", "rdep_count": 0, "symbols": [{"calls": [{"target": "foo"}]}]},
        ]
        _make_index(tmp_path, modules)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCAN_ARGS", "")
        with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
            main()
        out = capsys.readouterr().out
        assert "Calls:" in out

    def test_calls_line_absent_for_empty_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Calls line omitted when no call edges present."""
        modules = [
            {"name": "mod", "status": "ok", "rdep_count": 0, "symbols": [{"calls": []}]},
        ]
        _make_index(tmp_path, modules)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SCAN_ARGS", "")
        with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
            main()
        out = capsys.readouterr().out
        assert "Calls:" not in out
