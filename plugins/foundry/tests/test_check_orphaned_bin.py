"""Tests for check_orphaned_bin — orphaned bin/ script detector (Check 32d)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from check_orphaned_bin import OrphanFinding, find_orphans, is_referenced, iter_bin_scripts, main


# ---------------------------------------------------------------------------
# iter_bin_scripts
# ---------------------------------------------------------------------------


def _make_plugin(base: Path, plugin: str, scripts: list[str]) -> Path:
    plugin_dir = base / plugin / "bin"
    plugin_dir.mkdir(parents=True)
    for name in scripts:
        (plugin_dir / name).write_text("# script")
    return base / plugin


class TestIterBinScripts:
    def test_returns_py_and_sh(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_plugin(Path(d), "myplugin", ["foo.py", "bar.sh"])
            result = iter_bin_scripts(Path(d))
            names = [(r[0], r[1]) for r in result]
            assert names == [("myplugin", "bar.sh"), ("myplugin", "foo.py")]

    def test_skips_underscore_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_plugin(Path(d), "myplugin", ["_private.py", "public.py"])
            result = iter_bin_scripts(Path(d))
            names = [r[1] for r in result]
            assert "_private.py" not in names
            assert "public.py" in names

    def test_skips_non_script_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_plugin(Path(d), "myplugin", ["script.py", "readme.md", "data.json"])
            result = iter_bin_scripts(Path(d))
            names = [r[1] for r in result]
            assert names == ["script.py"]

    def test_multiple_plugins_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_plugin(Path(d), "zebra", ["z.py"])
            _make_plugin(Path(d), "alpha", ["a.py"])
            result = iter_bin_scripts(Path(d))
            plugins = [r[0] for r in result]
            assert plugins == ["alpha", "zebra"]

    def test_no_bin_dir_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "myplugin").mkdir()  # no bin/ subdir
            result = iter_bin_scripts(Path(d))
            assert result == []

    def test_full_path_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_plugin(Path(d), "myplugin", ["foo.py"])
            result = iter_bin_scripts(Path(d))
            assert result[0][2].endswith("myplugin/bin/foo.py")


# ---------------------------------------------------------------------------
# is_referenced
# ---------------------------------------------------------------------------


class TestIsReferenced:
    def test_found_in_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "skills").mkdir()
            (p / "skills" / "SKILL.md").write_text("run bin/foo.py here")
            assert is_referenced("foo.py", p) is True

    def test_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "skills").mkdir()
            (p / "skills" / "SKILL.md").write_text("nothing relevant")
            assert is_referenced("foo.py", p) is False

    def test_found_nested_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "skills" / "modes").mkdir(parents=True)
            (p / "skills" / "modes" / "efficiency.md").write_text("calls check_orphaned_bin.py")
            assert is_referenced("check_orphaned_bin.py", p) is True

    def test_non_md_files_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            p.mkdir(exist_ok=True)
            (p / "notes.txt").write_text("references foo.py")
            assert is_referenced("foo.py", p) is False

    def test_substring_match(self) -> None:
        """Full caller pattern ${CLAUDE_PLUGIN_ROOT}/bin/foo.py contains basename."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "skills").mkdir()
            (p / "skills" / "SKILL.md").write_text('python3 "${CLAUDE_PLUGIN_ROOT}/bin/foo.py"')
            assert is_referenced("foo.py", p) is True


# ---------------------------------------------------------------------------
# find_orphans
# ---------------------------------------------------------------------------


class TestFindOrphans:
    def test_referenced_script_not_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            _make_plugin(p, "myplugin", ["foo.py"])
            (p / "myplugin" / "skills").mkdir()
            (p / "myplugin" / "skills" / "SKILL.md").write_text("calls foo.py")
            assert find_orphans(p) == []

    def test_unreferenced_script_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            _make_plugin(p, "myplugin", ["orphan.py"])
            (p / "myplugin" / "skills").mkdir()
            (p / "myplugin" / "skills" / "SKILL.md").write_text("nothing here")
            orphans = find_orphans(p)
            assert len(orphans) == 1
            assert orphans[0].script == "orphan.py"
            assert orphans[0].plugin == "myplugin"

    def test_private_module_not_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            _make_plugin(p, "myplugin", ["_helper.py"])
            orphans = find_orphans(p)
            assert orphans == []

    def test_orphan_finding_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            _make_plugin(p, "myplugin", ["mycheck.py"])
            orphans = find_orphans(p)
            o = orphans[0]
            assert isinstance(o, OrphanFinding)
            assert o.plugin == "myplugin"
            assert o.script == "mycheck.py"
            assert "mycheck.py" in o.script_path

    def test_cross_plugin_caller_not_orphan(self) -> None:
        """Script in plugin A referenced by plugin B's SKILL.md is not an orphan."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            _make_plugin(p, "foundry", ["find-polluter.py"])
            (p / "develop" / "skills").mkdir(parents=True)
            (p / "develop" / "skills" / "SKILL.md").write_text('python "$_FOUNDRY_BIN/find-polluter.py" <test>')
            assert find_orphans(p) == []


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


class TestMain:
    def test_exit_0_all_referenced(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        with tempfile.TemporaryDirectory() as d:
            monkeypatch.chdir(d)
            p = Path(d)
            _make_plugin(p, "myplugin", ["foo.py"])
            (p / "myplugin" / "skills").mkdir()
            (p / "myplugin" / "skills" / "SKILL.md").write_text("calls foo.py")
            rc = main(["--plugins-dir", str(p)])
            assert rc == 0
            out = capsys.readouterr().out
            assert "✓" in out

    def test_exit_1_orphans_found(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        with tempfile.TemporaryDirectory() as d:
            monkeypatch.chdir(d)
            p = Path(d)
            _make_plugin(p, "myplugin", ["orphan.py"])
            rc = main(["--plugins-dir", str(p)])
            assert rc == 1
            out = capsys.readouterr().out
            assert "⚠ 32d" in out
            assert "orphan.py" in out

    def test_exit_1_output_includes_hint(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            monkeypatch.chdir(d)
            p = Path(d)
            _make_plugin(p, "myplugin", ["orphan.py"])
            main(["--plugins-dir", str(p)])
            out = capsys.readouterr().out
            assert "hint" in out

    def test_exit_2_bad_dir(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["--plugins-dir", "/nonexistent/path/does/not/exist"])
        assert rc == 2

    def test_default_plugins_dir_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tempfile.mkdtemp())
        rc = main([])
        assert rc == 2
