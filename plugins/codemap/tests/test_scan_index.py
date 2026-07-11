"""Integration tests for scan-index bin script.

Verifies index creation, incremental update behaviour, dynamic import extraction,
and config-file reference scanning.

Fixture layout:
    gamma.py          — leaf module, no imports; defines func_gamma
    beta.py           — imports gamma; defines func_beta calling func_gamma
    alpha.py          — imports beta, gamma; defines func_alpha calling func_beta
    pkg/__init__.py   — empty
    pkg/delta.py      — imports alpha; defines func_delta calling func_alpha
"""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_scan_index():
    """Load scan-index (no .py extension) via SourceFileLoader."""
    bin_path = Path(__file__).resolve().parent.parent / "bin" / "scan-index"
    loader = importlib.machinery.SourceFileLoader("scan_index_mod", str(bin_path))
    spec = importlib.util.spec_from_loader("scan_index_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scan_index_mod"] = mod  # required so dataclass __module__ lookup succeeds
    loader.exec_module(mod)
    return mod


_scan_index_mod = _load_scan_index()
extract_dynamic_imports = _scan_index_mod.extract_dynamic_imports
scan_config_refs = _scan_index_mod.scan_config_refs
_classify_entity = _scan_index_mod._classify_entity
_load_exclusions = _scan_index_mod._load_exclusions
_iter_python_files = _scan_index_mod._iter_python_files
_dedup_modules = _scan_index_mod._dedup_modules
_dedup_key = _scan_index_mod._dedup_key
_parse_file = _scan_index_mod._parse_file


def test_creates_index(tmp_path, gamma_src, beta_src, alpha_src, delta_src, scan_index):
    """scan-index writes .cache/codemap/<name>.json containing all modules."""
    (tmp_path / "gamma.py").write_text(gamma_src)
    (tmp_path / "beta.py").write_text(beta_src)
    (tmp_path / "alpha.py").write_text(alpha_src)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "delta.py").write_text(delta_src)

    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr

    index_path = tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text())
    names = {m["name"] for m in index["modules"]}
    assert {"alpha", "beta", "gamma", "pkg", "pkg.delta"}.issubset(names)


def test_incremental_picks_up_new_file(tmp_path, scan_index):
    """Adding a file after initial scan; --incremental indexes it."""
    (tmp_path / "base.py").write_text("def f(): pass\n")
    subprocess.run(
        [sys.executable, str(scan_index), "--root", str(tmp_path)],
        capture_output=True,
        cwd=str(tmp_path),
        check=True,
    )

    (tmp_path / "new_mod.py").write_text("import base\n")
    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(tmp_path), "--incremental"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr

    index_path = tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json"
    index = json.loads(index_path.read_text())
    names = {m["name"] for m in index["modules"]}
    assert "new_mod" in names


class TestExtractDynamicImports:
    """Unit tests for extract_dynamic_imports — AST-based dynamic import detection."""

    def test_importlib_string_literal(self):
        """importlib.import_module with a string constant is captured."""
        src = 'import importlib\nimportlib.import_module("my.pkg")'
        result = extract_dynamic_imports(ast.parse(src))
        assert result == [{"literal": "my.pkg", "line": 2}]

    def test_dunder_import_string_literal(self):
        """__import__ with a string constant is captured."""
        result = extract_dynamic_imports(ast.parse("__import__('os.path')"))
        assert result == [{"literal": "os.path", "line": 1}]

    def test_dynamic_expression_skipped(self):
        """importlib.import_module(name) — non-literal arg — must be ignored."""
        src = "importlib.import_module(name)"
        assert extract_dynamic_imports(ast.parse(src)) == []

    def test_multiple_calls_collected(self):
        """Multiple dynamic imports across same file all returned."""
        src = 'import importlib\nimportlib.import_module("pkg.a")\nimportlib.import_module("pkg.b")\n'
        result = extract_dynamic_imports(ast.parse(src))
        literals = [r["literal"] for r in result]
        assert literals == ["pkg.a", "pkg.b"]

    def test_no_dynamic_imports_returns_empty(self):
        """Plain file with no dynamic imports returns empty list."""
        src = "import os\nimport sys\n"
        assert extract_dynamic_imports(ast.parse(src)) == []


class TestClassifyEntity:
    """Unit tests for _classify_entity — entity_type + package derivation."""

    @pytest.mark.parametrize(
        "path_str, name, expected_type, expected_pkg",
        [
            pytest.param("tests/test_foo.py", "tests.test_foo", "test", "tests", id="tests-dir"),
            pytest.param("test_bar.py", "test_bar", "pkg", "test_bar", id="root-test-file"),
            pytest.param("src/pkg/conftest.py", "pkg.conftest", "test", "pkg", id="conftest"),
            pytest.param("docs/conf.py", "docs.conf", "docs", "docs", id="docs-dir"),
            pytest.param("doc/api.py", "doc.api", "docs", "doc", id="doc-singular"),
            pytest.param("examples/demo.py", "examples.demo", "example", "examples", id="examples-dir"),
            pytest.param("example/usage.py", "example.usage", "example", "example", id="example-singular"),
            pytest.param("mypackage/core.py", "mypackage.core", "pkg", "mypackage", id="pkg-module"),
            pytest.param("mypackage/sub/mod.py", "mypackage.sub.mod", "pkg", "mypackage", id="pkg-submodule"),
            pytest.param("standalone.py", "standalone", "pkg", "standalone", id="root-script"),
            pytest.param("src/mypackage/core.py", "src.mypackage.core", "pkg", "mypackage", id="src-layout-strip"),
            pytest.param("src/pkg/conftest.py", "src.pkg.conftest", "test", "pkg", id="src-layout-test-strip"),
        ],
    )
    def test_classification(self, path_str, name, expected_type, expected_pkg):
        """_classify_entity returns correct (entity_type, package) for each path pattern."""
        result = _classify_entity(Path(path_str), name)
        assert result == (expected_type, expected_pkg)


class TestScanConfigRefs:
    """Unit tests for scan_config_refs — config file module-path reference scanner."""

    def test_pyproject_match(self, tmp_path: Path):
        """Module name in pyproject.toml is detected."""
        (tmp_path / "pyproject.toml").write_text('[tool.mypy]\nmodule = "mypackage.utils"\n')
        refs = scan_config_refs(tmp_path, {"mypackage.utils"})
        assert "mypackage.utils" in refs
        assert refs["mypackage.utils"][0]["file"] == "pyproject.toml"

    def test_setup_cfg_match(self, tmp_path: Path):
        """Module name in setup.cfg is detected."""
        (tmp_path / "setup.cfg").write_text("[options]\npackages = mypackage.core\n")
        refs = scan_config_refs(tmp_path, {"mypackage.core"})
        assert "mypackage.core" in refs

    def test_yaml_match(self, tmp_path: Path):
        """Module name in a YAML file at project root is detected."""
        (tmp_path / "conf.yaml").write_text("defaults:\n  - module: mypackage.model\n")
        refs = scan_config_refs(tmp_path, {"mypackage.model"})
        assert "mypackage.model" in refs

    def test_unknown_module_not_returned(self, tmp_path: Path):
        """String matching no known module name is not included."""
        (tmp_path / "pyproject.toml").write_text('name = "something.random"\n')
        refs = scan_config_refs(tmp_path, {"mypackage.utils"})
        assert refs == {}

    def test_context_truncated_to_120(self, tmp_path: Path):
        """context field is at most 120 characters."""
        long_line = "x = " + "mypackage.utils" + " # " + "a" * 200
        (tmp_path / "setup.cfg").write_text(long_line + "\n")
        refs = scan_config_refs(tmp_path, {"mypackage.utils"})
        assert all(len(r["context"]) <= 120 for r in refs.get("mypackage.utils", []))

    def test_no_config_files_returns_empty(self, tmp_path: Path):
        """Directory with no config files returns empty dict."""
        assert scan_config_refs(tmp_path, {"mypackage.utils"}) == {}


class TestLoadExclusions:
    """Loading extra dir-name/glob exclusions from pyproject.toml and .codemapignore."""

    def test_pyproject_exclude_dirs_and_globs(self, tmp_path: Path):
        """[tool.codemap] exclude splits bare names into dirs and glob entries into globs."""
        (tmp_path / "pyproject.toml").write_text('[tool.codemap]\nexclude = ["vendor", "gen/*.py"]\n')
        ex = _load_exclusions(tmp_path)
        assert ex.dirs == frozenset({"vendor"})
        assert ex.globs == ("gen/*.py",)
        assert ex.sources == {"vendor": "pyproject.toml", "gen/*.py": "pyproject.toml"}

    def test_codemapignore_strips_comments_and_slashes(self, tmp_path: Path):
        """.codemapignore drops comments/blanks and trailing slashes on dir names."""
        (tmp_path / ".codemapignore").write_text("# header\nvendored/\n\n  build_out/*.py  \n")
        ex = _load_exclusions(tmp_path)
        assert ex.dirs == frozenset({"vendored"})
        assert ex.globs == ("build_out/*.py",)

    def test_both_sources_merge(self, tmp_path: Path):
        """Entries from both files merge; provenance records the first-seen origin."""
        (tmp_path / "pyproject.toml").write_text('[tool.codemap]\nexclude = ["a"]\n')
        (tmp_path / ".codemapignore").write_text("b\n")
        ex = _load_exclusions(tmp_path)
        assert ex.dirs == frozenset({"a", "b"})
        assert ex.sources == {"a": "pyproject.toml", "b": ".codemapignore"}

    def test_no_config_returns_empty(self, tmp_path: Path):
        """Absent config files yield empty exclusions."""
        ex = _load_exclusions(tmp_path)
        assert ex.dirs == frozenset()
        assert ex.globs == ()


class TestIterPythonFilesExclusions:
    """_iter_python_files honours SKIP_DIRS additions and configured exclusions."""

    def test_prunes_worktree_copy_and_vendored_entry(self, tmp_path: Path):
        """A .claude/worktrees copy and a .codemapignore-named dir are both pruned; meta counts them."""
        (tmp_path / "app.py").write_text("x = 1\n")
        worktree = tmp_path / ".claude" / "worktrees" / "agent-x"
        worktree.mkdir(parents=True)
        (worktree / "app.py").write_text("x = 1\n")
        vendored = tmp_path / "pytorch-lightning-master"
        vendored.mkdir()
        (vendored / "trainer.py").write_text("y = 2\n")
        (tmp_path / ".codemapignore").write_text("pytorch-lightning-master\n")

        ex = _load_exclusions(tmp_path)
        files, counts = _iter_python_files(tmp_path, ex)

        rels = {p.relative_to(tmp_path).as_posix() for p in files}
        assert rels == {"app.py"}
        assert not any(".claude" in r for r in rels)
        assert counts["pytorch-lightning-master"] == 1

    def test_glob_exclusion_skips_matching_files(self, tmp_path: Path):
        """A glob entry removes matching files while leaving siblings indexed."""
        (tmp_path / "keep.py").write_text("a = 1\n")
        gen = tmp_path / "gen"
        gen.mkdir()
        (gen / "auto.py").write_text("b = 2\n")
        (tmp_path / "pyproject.toml").write_text('[tool.codemap]\nexclude = ["gen/*.py"]\n')

        ex = _load_exclusions(tmp_path)
        files, counts = _iter_python_files(tmp_path, ex)

        rels = {p.relative_to(tmp_path).as_posix() for p in files}
        assert rels == {"keep.py"}
        assert counts["gen/*.py"] == 1


class TestDedupKey:
    """_dedup_key ranks candidate paths: under-src > shortest > lexicographic."""

    def test_under_src_root_wins(self):
        """A path under the source root outranks one outside it regardless of length."""
        assert _dedup_key("src/m.py", "src") < _dedup_key("a/b/c/m.py", "src")

    def test_shortest_path_wins_when_src_tied(self):
        """With no src root, fewer path components wins."""
        assert _dedup_key("m.py", "") < _dedup_key("pkg/m.py", "")

    def test_lexicographic_tiebreak(self):
        """Equal depth and src status falls back to lexicographic order."""
        assert _dedup_key("a/m.py", "") < _dedup_key("b/m.py", "")


class TestDedupModules:
    """_dedup_modules produces a deterministic winner and records collisions."""

    def test_deterministic_winner_across_shuffles(self):
        """Same qualname at two paths yields the same winner regardless of input order."""
        entries = [
            {"name": "pkg.mod", "path": "copy/pkg/mod.py"},
            {"name": "pkg.mod", "path": "src/pkg/mod.py"},
        ]
        winners = set()
        for order in (entries, list(reversed(entries)), entries, list(reversed(entries)), entries):
            kept, collisions = _dedup_modules(list(order), "src")
            assert len(kept) == 1
            winners.add(kept[0]["path"])
            assert collisions == [{"name": "pkg.mod", "kept": "src/pkg/mod.py", "dropped": ["copy/pkg/mod.py"]}]
        assert winners == {"src/pkg/mod.py"}

    def test_no_collision_keeps_all(self):
        """Distinct names are all kept with an empty collision list."""
        entries = [{"name": "a", "path": "a.py"}, {"name": "b", "path": "b.py"}]
        kept, collisions = _dedup_modules(entries, "")
        assert {m["name"] for m in kept} == {"a", "b"}
        assert collisions == []


class TestScanExclusionMeta:
    """End-to-end: a real scan writes excluded_roots and collisions into the index meta."""

    def test_excluded_roots_and_collisions_in_index(self, tmp_path: Path, scan_index):
        """Scanning a polluted tree prunes the worktree copy and records both meta keys."""
        (tmp_path / "app.py").write_text("VALUE = 1\n")
        worktree = tmp_path / ".claude" / "worktrees" / "agent-x"
        worktree.mkdir(parents=True)
        (worktree / "app.py").write_text("VALUE = 99\n")
        vendored = tmp_path / "vendor_copy"
        vendored.mkdir()
        (vendored / "app.py").write_text("VALUE = 7\n")
        (tmp_path / ".codemapignore").write_text("vendor_copy\n")

        result = subprocess.run(
            [sys.executable, str(scan_index), "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr

        index_path = tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json"
        index = json.loads(index_path.read_text())
        paths = {m["path"] for m in index["modules"]}
        assert paths == {"app.py"}
        patterns = {r["pattern"] for r in index["excluded_roots"]}
        assert "vendor_copy" in patterns
        assert index["collisions"] == []

    def test_collision_recorded_and_deterministic(self, tmp_path: Path, scan_index):
        """Two package trees sharing a top-level name collide; the winner is stable across runs.

        The canonical ``pkg`` tree and a whole-tree copy under ``wt/`` both resolve to the
        dotted name ``pkg.mod``. Only one survives; the collision record names both, and the
        winner is identical on every run regardless of filesystem walk order (acceptance).
        """
        for parent in ("pkg", "wt/pkg"):
            (tmp_path / parent).mkdir(parents=True)
            (tmp_path / parent / "__init__.py").write_text("")
        (tmp_path / "pkg" / "mod.py").write_text("Z = 1\n")
        (tmp_path / "wt" / "pkg" / "mod.py").write_text("Z = 2\n")

        winners = set()
        collision = None
        for _ in range(5):
            result = subprocess.run(
                [sys.executable, str(scan_index), "--root", str(tmp_path)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            assert result.returncode == 0, result.stderr
            index = json.loads((tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json").read_text())
            collision = next((c for c in index["collisions"] if c["name"] == "pkg.mod"), None)
            assert collision is not None
            winners.add(collision["kept"])

        assert len(winners) == 1
        assert set(collision["dropped"]) | {collision["kept"]} == {"pkg/mod.py", "wt/pkg/mod.py"}


class TestEncodingDegradation:
    """A file whose bytes are not valid UTF-8 must be marked degraded, not silently indexed."""

    def test_invalid_utf8_parse_file_returns_encoding_degraded(self, tmp_path: Path):
        """_parse_file returns a degraded entry with an 'encoding' reason for non-UTF-8 bytes."""
        bad = tmp_path / "bad.py"
        bad.write_bytes(b"x = '\xff\xfe not utf8'\n")

        entry = _parse_file(bad, tmp_path, tmp_path)

        assert entry["status"] == "degraded"
        assert entry["reason"].startswith("encoding:")
        assert "symbols" not in entry  # corrupted source never parsed into symbols

    def test_invalid_utf8_not_silently_indexed(self, tmp_path: Path, scan_index):
        """End-to-end: an invalid-UTF-8 module lands as degraded in the index, not status ok."""
        (tmp_path / "good.py").write_text("y = 1\n")
        (tmp_path / "bad.py").write_bytes(b"x = '\xff\xfe'\n")

        result = subprocess.run(
            [sys.executable, str(scan_index), "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr

        index = json.loads((tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json").read_text())
        bad = next(m for m in index["modules"] if m["path"] == "bad.py")
        assert bad["status"] == "degraded"
        assert bad["reason"].startswith("encoding:")


class TestFileTooLargeDegradation:
    """An oversized file is marked degraded with a 'reason' key so the print loop never KeyErrors."""

    def test_too_large_uses_reason_key(self, tmp_path: Path, monkeypatch):
        """_parse_file over the size cap returns a degraded entry keyed on 'reason', not 'error'."""
        monkeypatch.setattr(_scan_index_mod, "_MAX_FILE_SIZE_BYTES", 8)
        big = tmp_path / "big.py"
        big.write_text("x = 1234567890\n")  # >8 bytes on disk

        entry = _parse_file(big, tmp_path, tmp_path)

        assert entry["status"] == "degraded"
        assert "error" not in entry  # contract unified on 'reason'
        assert entry["reason"].startswith("file too large")

    def test_all_degraded_reasons_printable(self, tmp_path: Path, monkeypatch):
        """Every degraded branch of _parse_file exposes 'reason' — the key the print loop reads."""
        monkeypatch.setattr(_scan_index_mod, "_MAX_FILE_SIZE_BYTES", 8)
        too_large = tmp_path / "big.py"
        too_large.write_text("x = 1234567890\n")
        bad_utf8 = tmp_path / "bad.py"
        bad_utf8.write_bytes(b"x = '\xff\xfe'\n")
        bad_syntax = tmp_path / "broken.py"
        bad_syntax.write_text("def (:\n")

        entries = [_parse_file(p, tmp_path, tmp_path) for p in (too_large, bad_utf8, bad_syntax)]

        assert all(e["status"] == "degraded" for e in entries)
        assert all("reason" in e for e in entries)  # print loop does m['reason'] — must never KeyError


class TestAtomicIndexWrite:
    """Index write goes through a temp file so a kill mid-write leaves the prior index readable."""

    def test_no_stale_tmp_and_index_valid_after_write(self, tmp_path: Path, scan_index):
        """A completed run leaves a parseable index and no leftover .json.tmp sidecar."""
        (tmp_path / "gamma.py").write_text("g = 1\n")

        result = subprocess.run(
            [sys.executable, str(scan_index), "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr

        cache_dir = tmp_path / ".cache" / "codemap"
        index_path = cache_dir / f"{tmp_path.name}.json"
        json.loads(index_path.read_text())  # final index is complete/parseable
        assert not (cache_dir / f"{tmp_path.name}.json.tmp").exists()  # os.replace consumed the tmp

    def test_rerun_preserves_readable_index(self, tmp_path: Path, scan_index):
        """Re-running over an existing index yields a still-parseable index (replace is atomic)."""
        (tmp_path / "gamma.py").write_text("g = 1\n")
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, str(scan_index), "--root", str(tmp_path)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            assert result.returncode == 0, result.stderr

        index = json.loads((tmp_path / ".cache" / "codemap" / f"{tmp_path.name}.json").read_text())
        assert any(m["name"] == "gamma" for m in index["modules"])

    def test_concurrent_writers_leave_valid_index(self, tmp_path: Path, scan_index):
        """Two writers racing on the same root must not corrupt the index (PID-qualified temp).

        The bg refresh, post-commit hook, and self-heal all invoke scan-index
        uncoordinated. A shared fixed ".json.tmp" would let two "w" opens interleave
        into corrupt bytes; the PID-qualified temp gives each writer its own file so
        every os.replace promotes a complete index. Whichever writer wins, the final
        file must parse and no PID-suffixed temp may leak.
        """
        (tmp_path / "gamma.py").write_text("g = 1\n")

        procs = [
            subprocess.Popen(
                [sys.executable, str(scan_index), "--root", str(tmp_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(tmp_path),
            )
            for _ in range(2)
        ]
        for proc in procs:
            _, stderr = proc.communicate(timeout=60)
            assert proc.returncode == 0, stderr

        cache_dir = tmp_path / ".cache" / "codemap"
        index = json.loads((cache_dir / f"{tmp_path.name}.json").read_text())  # never corrupt/truncated
        assert any(m["name"] == "gamma" for m in index["modules"])
        assert not list(cache_dir.glob(f"{tmp_path.name}.json.*.tmp"))  # no PID-suffixed temp leaked
