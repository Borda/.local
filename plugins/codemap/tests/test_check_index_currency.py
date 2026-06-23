"""Tests for ``bin/check-index-currency`` — two-tier codemap index currency check.

Strategy:
- Import the module via importlib (hyphenated filename can't use plain import).
- Mock ``_git_head`` and ``_git_dirty_py_count`` so no git binary required.
- Use ``tmp_path`` for real filesystem fixtures (Tier 2 file-hash path).
- CLI entry-point tested via ``main()`` directly, not subprocess.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import hyphen-named bin script (no .py extension — must use SourceFileLoader)
# ---------------------------------------------------------------------------

_BIN_DIR = Path(__file__).parent.parent / "bin"
_CIC_PATH = _BIN_DIR / "check-index-currency"

_loader = importlib.machinery.SourceFileLoader("check_index_currency", str(_CIC_PATH))
_spec = importlib.util.spec_from_loader("check_index_currency", _loader)
cic = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_loader.exec_module(cic)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_index(path: Path, data: dict[str, Any]) -> None:
    """Write a minimal codemap index JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_index(**extra: Any) -> dict[str, Any]:
    """Return a minimal valid index dict, optionally extended."""
    base: dict[str, Any] = {"scan_version": 3, "modules": [], "scanned_at": "2026-01-01T00:00:00Z"}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# _result helper
# ---------------------------------------------------------------------------


class TestResult:
    """Tests for the ``_result`` helper."""

    def test_current_exit_0(self) -> None:
        """status=current maps to exit code 0."""
        r, code = cic._result("current", "ok")
        assert code == 0
        assert r["status"] == "current"

    def test_stale_exit_1(self) -> None:
        """status=stale maps to exit code 1."""
        _, code = cic._result("stale", "changed")
        assert code == 1

    def test_no_index_exit_2(self) -> None:
        """status=no_index maps to exit code 2."""
        _, code = cic._result("no_index", "missing")
        assert code == 2

    def test_changed_count_default_zero(self) -> None:
        """changed_count defaults to 0."""
        r, _ = cic._result("current", "ok")
        assert r["changed_count"] == 0

    def test_changed_count_passed_through(self) -> None:
        """changed_count is stored in result dict."""
        r, _ = cic._result("stale", "x", 5)
        assert r["changed_count"] == 5


# ---------------------------------------------------------------------------
# _sha256_file helper
# ---------------------------------------------------------------------------


class TestSha256File:
    """Tests for ``_sha256_file``."""

    def test_known_content(self, tmp_path: Path) -> None:
        """SHA-256 of known bytes matches expected digest."""
        import hashlib

        data = b"hello codemap"
        f = tmp_path / "x.py"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert cic._sha256_file(f) == expected

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty file produces expected SHA-256 (known constant)."""
        f = tmp_path / "empty.py"
        f.write_bytes(b"")
        import hashlib

        assert cic._sha256_file(f) == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# _parse_scanned_at helper
# ---------------------------------------------------------------------------


class TestParseScannedAt:
    """Tests for ``_parse_scanned_at``."""

    @pytest.mark.parametrize(
        "value,expected_nonzero",
        [
            pytest.param("2026-01-15T12:30:00Z", True, id="valid-z-suffix"),
            pytest.param("2026-01-15T12:30:00", True, id="valid-no-suffix"),
            pytest.param("2026-01-15T12:30:00.123456Z", True, id="valid-microseconds"),
            pytest.param("", False, id="empty-string"),
            pytest.param("not-a-date", False, id="garbage"),
        ],
    )
    def test_parse(self, value: str, expected_nonzero: bool) -> None:
        """Non-zero returned for valid timestamps; zero for unparsable."""
        result = cic._parse_scanned_at(value)
        assert (result > 0) == expected_nonzero


# ---------------------------------------------------------------------------
# _read_index helper
# ---------------------------------------------------------------------------


class TestReadIndex:
    """Tests for ``_read_index``."""

    def test_valid_json(self, tmp_path: Path) -> None:
        """Valid JSON dict is returned as-is."""
        p = tmp_path / "idx.json"
        p.write_text('{"a": 1}')
        result = cic._read_index(p)
        assert result == {"a": 1}

    def test_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt JSON returns None."""
        p = tmp_path / "idx.json"
        p.write_text("{not json}")
        assert cic._read_index(p) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        """Missing file returns None."""
        assert cic._read_index(tmp_path / "missing.json") is None

    def test_json_list_not_dict(self, tmp_path: Path) -> None:
        """JSON array (not dict) returns None."""
        p = tmp_path / "idx.json"
        p.write_text("[1, 2, 3]")
        assert cic._read_index(p) is None

    def test_oversized_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File exceeding size limit returns None."""
        p = tmp_path / "huge.json"
        p.write_text("{}")
        monkeypatch.setattr(cic, "MAX_INDEX_SIZE", -1)
        assert cic._read_index(p) is None


# ---------------------------------------------------------------------------
# check_currency — no index cases
# ---------------------------------------------------------------------------


class TestCheckCurrencyNoIndex:
    """``check_currency`` when index is absent or unreadable."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Non-existent index path returns no_index."""
        r, code = cic.check_currency(tmp_path / "missing.json", tmp_path)
        assert r["status"] == "no_index"
        assert code == 2

    def test_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt index file returns no_index."""
        p = tmp_path / "bad.json"
        p.write_text("not json")
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "no_index"
        assert code == 2


# ---------------------------------------------------------------------------
# check_currency — Tier 1 (git-based, mocked)
# ---------------------------------------------------------------------------


SHA_A = "a" * 40
SHA_B = "b" * 40


class TestCheckCurrencyTier1:
    """Git-based currency checks with mocked git calls."""

    @pytest.fixture()
    def index_file(self, tmp_path: Path) -> Path:
        """Write minimal index with git_sha=SHA_A."""
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index(git_sha=SHA_A))
        return p

    def test_current_when_sha_matches_no_dirty(
        self, index_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SHA matches HEAD and no dirty .py files → current."""
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_A)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 0)
        r, code = cic.check_currency(index_file, tmp_path)
        assert r["status"] == "current"
        assert code == 0

    def test_stale_when_sha_differs(self, index_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HEAD SHA differs from stored git_sha → stale."""
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_B)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 0)
        r, code = cic.check_currency(index_file, tmp_path)
        assert r["status"] == "stale"
        assert code == 1
        assert "a" * 8 in r["reason"]
        assert "b" * 8 in r["reason"]

    def test_stale_when_dirty_py_files(self, index_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """SHA matches but uncommitted .py changes → stale."""
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_A)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 3)
        r, code = cic.check_currency(index_file, tmp_path)
        assert r["status"] == "stale"
        assert r["changed_count"] == 3

    def test_git_head_none_falls_to_tier2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _git_head returns None, Tier 2 runs (file_shas path)."""
        py = tmp_path / "a.py"
        py.write_text("x = 1")
        sha = cic._sha256_file(py)
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index(file_shas={"a.py": sha}))
        monkeypatch.setattr(cic, "_git_head", lambda root: None)
        r, _ = cic.check_currency(p, tmp_path)
        # Tier 2 ran — result may be current (SHA matches) or stale depending on mtime
        # At minimum, it should not be a Tier 1 error; status should be resolvable
        assert r["status"] in ("current", "stale")

    def test_no_stored_git_sha_falls_to_tier2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Index with no git_sha field triggers Tier 2 regardless of git availability."""
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index())  # no git_sha
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_A)
        # No file_shas either → stale (old format)
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "stale"


# ---------------------------------------------------------------------------
# check_currency — Tier 2 (filesystem-based)
# ---------------------------------------------------------------------------


class TestCheckCurrencyTier2:
    """Filesystem-based currency checks (no git)."""

    @pytest.fixture(autouse=True)
    def _no_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force Tier 2 by making _git_head return None."""
        monkeypatch.setattr(cic, "_git_head", lambda root: None)

    def _write_py(self, root: Path, relpath: str, content: str = "x = 1") -> str:
        """Write a .py file under root and return its MD5."""
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return cic._md5_file(p)

    def test_current_all_match(self, tmp_path: Path) -> None:
        """All .py files match stored file_shas → current."""
        sha = self._write_py(tmp_path, "mod.py")
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index(file_shas={"mod.py": sha}, scanned_at="2025-01-01T00:00:00Z"))
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "current"
        assert code == 0

    def test_stale_new_py_file(self, tmp_path: Path) -> None:
        """New .py file not present in file_shas → stale."""
        # existing.py is in the index; new_module.py is not
        sha_existing = self._write_py(tmp_path, "existing.py")
        self._write_py(tmp_path, "new_module.py")
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index(file_shas={"existing.py": sha_existing}))
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "stale"
        assert r["changed_count"] >= 1

    def test_stale_deleted_py_file(self, tmp_path: Path) -> None:
        """File in file_shas but missing on disk → stale."""
        p = tmp_path / "idx.json"
        _write_index(p, _minimal_index(file_shas={"ghost.py": "abc123"}))
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "stale"
        assert "delete" in r["reason"].lower()

    def test_stale_content_changed(self, tmp_path: Path) -> None:
        """File content changed (SHA differs) with mtime newer than scan → stale."""
        py = tmp_path / "mod.py"
        py.write_text("original")
        old_sha = cic._md5_file(py)
        # Overwrite with different content; mtime will be newer than scanned_at
        py.write_text("changed content here")
        p = tmp_path / "idx.json"
        _write_index(
            p,
            _minimal_index(file_shas={"mod.py": old_sha}, scanned_at="2020-01-01T00:00:00Z"),
        )
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "stale"
        assert r["changed_count"] >= 1

    def test_current_mtime_prefilter(self, tmp_path: Path) -> None:
        """File whose mtime predates scan is not content-checked → current."""

        py = tmp_path / "old.py"
        py.write_text("content A")
        old_sha = cic._md5_file(py)
        # Set mtime to distant past
        past = 0.0  # epoch
        import os

        os.utime(py, (past, past))
        p = tmp_path / "idx.json"
        # scanned_at is well after epoch, so mtime < scanned_at → pre-filter fires
        _write_index(
            p,
            _minimal_index(file_shas={"old.py": old_sha}, scanned_at="2025-06-01T00:00:00Z"),
        )
        r, _ = cic.check_currency(p, tmp_path)
        assert r["status"] == "current"

    def test_stale_no_file_shas_in_index(self, tmp_path: Path) -> None:
        """Index with no file_shas field at all → stale (rebuild required)."""
        self._write_py(tmp_path, "mod.py")
        p = tmp_path / "idx.json"
        _write_index(p, {"scan_version": 2, "modules": []})  # v2, no file_shas
        r, code = cic.check_currency(p, tmp_path)
        assert r["status"] == "stale"
        assert code == 1


# ---------------------------------------------------------------------------
# CLI — main() and --field flag
# ---------------------------------------------------------------------------


class TestCLI:
    """Tests for the ``main()`` CLI entry point."""

    def test_field_status_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """``--field status`` prints only the status value."""
        py = tmp_path / "m.py"
        py.write_text("x = 1")
        sha = cic._md5_file(py)
        idx = tmp_path / "idx.json"
        _write_index(idx, _minimal_index(file_shas={"m.py": sha}, scanned_at="2020-01-01T00:00:00Z"))
        monkeypatch.setattr(cic, "_git_head", lambda root: None)
        import os

        os.utime(py, (0.0, 0.0))  # older than scanned_at
        code = cic.main(["--index-path", str(idx), "--root", str(tmp_path), "--field", "status"])
        out = capsys.readouterr().out.strip()
        assert out == "current"
        assert code == 0

    def test_field_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """``--field reason`` prints the reason string."""
        idx = tmp_path / "idx.json"
        _write_index(idx, _minimal_index(git_sha=SHA_A))
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_B)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 0)
        cic.main(["--index-path", str(idx), "--root", str(tmp_path), "--field", "reason"])
        out = capsys.readouterr().out.strip()
        assert len(out) > 0  # reason is non-empty on stale

    def test_full_json_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Without --field, output is valid JSON with status/reason/changed_count."""
        idx = tmp_path / "idx.json"
        _write_index(idx, _minimal_index(git_sha=SHA_A))
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_A)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 0)
        cic.main(["--index-path", str(idx), "--root", str(tmp_path)])
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert set(data) >= {"status", "reason", "changed_count"}

    def test_missing_index_path_arg(self, capsys: pytest.CaptureFixture) -> None:
        """Missing required --index-path exits non-zero."""
        with pytest.raises(SystemExit) as exc:
            cic.main([])
        assert exc.value.code != 0

    def test_root_auto_detect_via_git_toplevel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Without --root, ``_git_toplevel`` is called to detect project root."""
        py = tmp_path / "m.py"
        py.write_text("x = 1")
        idx = tmp_path / "idx.json"
        _write_index(idx, _minimal_index(git_sha=SHA_A))
        monkeypatch.setattr(cic, "_git_toplevel", lambda: tmp_path)
        monkeypatch.setattr(cic, "_git_head", lambda root: SHA_A)
        monkeypatch.setattr(cic, "_git_dirty_py_count", lambda root: 0)
        # no --root flag; _git_toplevel mock returns tmp_path
        cic.main(["--index-path", str(idx)])
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["status"] == "current"
