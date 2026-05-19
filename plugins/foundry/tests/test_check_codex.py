"""Tests for ``bin/check_codex.py``.

Detection paths are I/O-bound (JSON parse, directory glob, ``shutil.which``);
this file covers each branch with ``monkeypatch`` and ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


import check_codex  # noqa: E402


def _no_which(_name: str) -> None:
    """Stand-in for ``shutil.which`` that always returns None."""
    return None


class TestManifestHasCodex:
    """_manifest_has_codex: JSON-key contains-'codex' check."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Missing manifest returns False, no exception."""
        assert check_codex._manifest_has_codex(tmp_path / "absent.json") is False

    def test_codex_key_present(self, tmp_path: Path) -> None:
        """Any top-level key containing 'codex' triggers True."""
        manifest = tmp_path / "installed_plugins.json"
        manifest.write_text(
            json.dumps({"codex@openai-codex": [{"installPath": "/p"}]}),
            encoding="utf-8",
        )
        assert check_codex._manifest_has_codex(manifest) is True

    def test_no_codex_key(self, tmp_path: Path) -> None:
        """No key contains 'codex' — returns False."""
        manifest = tmp_path / "installed_plugins.json"
        manifest.write_text(json.dumps({"foundry@x": [], "develop@x": []}), encoding="utf-8")
        assert check_codex._manifest_has_codex(manifest) is False

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Unparsable JSON returns False, not exception."""
        manifest = tmp_path / "installed_plugins.json"
        manifest.write_text("{not-json", encoding="utf-8")
        assert check_codex._manifest_has_codex(manifest) is False

    def test_unexpected_shape(self, tmp_path: Path) -> None:
        """Top-level array (not object) returns False."""
        manifest = tmp_path / "installed_plugins.json"
        manifest.write_text(json.dumps(["codex"]), encoding="utf-8")
        assert check_codex._manifest_has_codex(manifest) is False


class TestCacheHasCodex:
    """_cache_has_codex: depth-bounded directory glob."""

    def test_missing_dir(self, tmp_path: Path) -> None:
        """Missing cache root returns False, no exception."""
        assert check_codex._cache_has_codex(tmp_path / "absent") is False

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Existing but empty cache returns False."""
        assert check_codex._cache_has_codex(tmp_path) is False

    def test_top_level_match(self, tmp_path: Path) -> None:
        """Direct ``codex*`` child matches."""
        (tmp_path / "codex-plugin-cc").mkdir()
        assert check_codex._cache_has_codex(tmp_path) is True

    def test_nested_match(self, tmp_path: Path) -> None:
        """Match at depth 3 (``borda-ai-rig/codex/0.1.0``) still found."""
        nested = tmp_path / "borda-ai-rig" / "codex" / "0.1.0"
        nested.mkdir(parents=True)
        assert check_codex._cache_has_codex(tmp_path) is True

    def test_no_match(self, tmp_path: Path) -> None:
        """Sibling dirs with unrelated names — no match."""
        (tmp_path / "foundry").mkdir()
        (tmp_path / "develop").mkdir()
        assert check_codex._cache_has_codex(tmp_path) is False

    def test_file_not_dir_skipped(self, tmp_path: Path) -> None:
        """``codex*`` matching a regular file (not dir) does not count."""
        (tmp_path / "codex.txt").write_text("", encoding="utf-8")
        assert check_codex._cache_has_codex(tmp_path) is False


class TestCodexAvailable:
    """codex_available: orchestrates the three-path detection chain."""

    def test_manifest_short_circuits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manifest hit returns True without consulting cache or PATH."""
        manifest = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"codex@x": []}), encoding="utf-8")

        # Ensure cache + which would NOT also report True.
        def boom(_name: str) -> None:  # pragma: no cover — must not run
            raise AssertionError("shutil.which must not run when manifest hits")

        monkeypatch.setattr(check_codex.shutil, "which", boom)
        assert check_codex.codex_available(tmp_path) is True

    def test_cache_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No manifest, but cache dir contains ``codex*`` → True."""
        cache = tmp_path / ".claude" / "plugins" / "cache" / "codex-plugin-cc"
        cache.mkdir(parents=True)
        monkeypatch.setattr(check_codex.shutil, "which", _no_which)
        assert check_codex.codex_available(tmp_path) is True

    def test_path_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No manifest, no cache match → ``shutil.which`` decides."""
        monkeypatch.setattr(check_codex.shutil, "which", lambda _name: "/usr/local/bin/codex")
        assert check_codex.codex_available(tmp_path) is True

    def test_all_negative(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No detection path succeeds → False."""
        monkeypatch.setattr(check_codex.shutil, "which", _no_which)
        assert check_codex.codex_available(tmp_path) is False


class TestMain:
    """main: stdout contract — prints 'true' or 'false', exits 0 always."""

    def test_prints_true(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Available codex → 'true' on stdout, exit 0."""
        monkeypatch.setattr(check_codex.Path, "home", classmethod(lambda _cls: tmp_path))
        monkeypatch.setattr(check_codex.shutil, "which", lambda _name: "/usr/bin/codex")
        rc = check_codex.main([])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "true"

    def test_prints_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No detection path hits → 'false' on stdout, exit 0."""
        monkeypatch.setattr(check_codex.Path, "home", classmethod(lambda _cls: tmp_path))
        monkeypatch.setattr(check_codex.shutil, "which", _no_which)
        rc = check_codex.main([])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "false"
