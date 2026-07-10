"""Integration + unit tests for monorepo multi-source-root awareness in scan-index.

Covers ``[tool.codemap] src_roots``: module naming derives from the matching source
root, collision resolution prefers a path under any configured root (with declaration
order as priority), and the effective roots are recorded in the index meta. A no-config
project must behave identically to the single-root detection it always used.

Monorepo fixture layout::

    libs/core/src/pkg_a/__init__.py   (pkg_a)          — first-priority root
    libs/core/src/pkg_a/mod_a.py      (pkg_a.mod_a)
    services/api/src/pkg_b/__init__.py (pkg_b)          — second-priority root
    services/api/src/pkg_b/mod_b.py   (pkg_b.mod_b)
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_scan_index():
    """Load scan-index (no .py extension) via SourceFileLoader for unit-level access."""
    bin_path = Path(__file__).resolve().parent.parent / "bin" / "scan-index"
    loader = importlib.machinery.SourceFileLoader("scan_index_mod", str(bin_path))
    spec = importlib.util.spec_from_loader("scan_index_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scan_index_mod"] = mod  # required so dataclass __module__ lookup succeeds
    loader.exec_module(mod)
    return mod


def _load_exclusions_mod():
    """Load the _exclusions.py bin module for direct access to load_src_roots."""
    bin_path = Path(__file__).resolve().parent.parent / "bin" / "_exclusions.py"
    loader = importlib.machinery.SourceFileLoader("exclusions_mod", str(bin_path))
    spec = importlib.util.spec_from_loader("exclusions_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["exclusions_mod"] = mod
    loader.exec_module(mod)
    return mod


_scan_index_mod = _load_scan_index()
_exclusions_mod = _load_exclusions_mod()

_effective_src_root = _scan_index_mod._effective_src_root
_src_root_rels = _scan_index_mod._src_root_rels
_under_root_rank = _scan_index_mod._under_root_rank
_dedup_key = _scan_index_mod._dedup_key
_dedup_modules = _scan_index_mod._dedup_modules
_resolve_src_roots = _scan_index_mod._resolve_src_roots
load_src_roots = _exclusions_mod.load_src_roots
_parse_codemap_src_roots_toml = _exclusions_mod._parse_codemap_src_roots_toml


_PYPROJECT_TWO_ROOTS = '[tool.codemap]\nsrc_roots = ["libs/core/src", "services/api/src"]\n'


def _materialize_monorepo(root: Path) -> None:
    """Write a two-source-root monorepo tree with a pyproject declaring both roots."""
    (root / "pyproject.toml").write_text(_PYPROJECT_TWO_ROOTS)
    pkg_a = root / "libs" / "core" / "src" / "pkg_a"
    pkg_a.mkdir(parents=True)
    (pkg_a / "__init__.py").write_text("")
    (pkg_a / "mod_a.py").write_text("def a():\n    return 1\n")
    pkg_b = root / "services" / "api" / "src" / "pkg_b"
    pkg_b.mkdir(parents=True)
    (pkg_b / "__init__.py").write_text("")
    (pkg_b / "mod_b.py").write_text("def b():\n    return 2\n")


def _scan_and_load(scan_index: Path, root: Path, *extra: str) -> dict:
    """Run scan-index over *root* and return the parsed index dict."""
    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    assert index_path.exists(), "scan-index did not produce an index file"
    return json.loads(index_path.read_text())


# ── config parsing / loading ─────────────────────────────────────────────────────


class TestParseSrcRootsToml:
    """_parse_codemap_src_roots_toml extracts the ordered src_roots array."""

    def test_multi_line_array_preserves_order(self):
        """A multi-line array yields entries in declaration order."""
        text = '[tool.codemap]\nsrc_roots = [\n  "a/src",\n  "b/src",\n]\n'
        assert _parse_codemap_src_roots_toml(text) == ["a/src", "b/src"]

    def test_absent_key_returns_empty(self):
        """A [tool.codemap] section without src_roots yields no entries."""
        assert _parse_codemap_src_roots_toml('[tool.codemap]\nexclude = ["x"]\n') == []

    def test_wrong_section_ignored(self):
        """src_roots under a different table is not picked up."""
        assert _parse_codemap_src_roots_toml('[tool.other]\nsrc_roots = ["x"]\n') == []


class TestLoadSrcRoots:
    """load_src_roots resolves existing directories in priority order."""

    def test_returns_existing_dirs_in_declaration_order(self, tmp_path: Path):
        """Only directories that exist are returned, ordered as declared."""
        _materialize_monorepo(tmp_path)
        roots = load_src_roots(tmp_path)
        rels = [p.relative_to(tmp_path).as_posix() for p in roots]
        assert rels == ["libs/core/src", "services/api/src"]

    def test_missing_dirs_dropped(self, tmp_path: Path):
        """A declared root that does not exist on disk is skipped."""
        (tmp_path / "pyproject.toml").write_text('[tool.codemap]\nsrc_roots = ["exists/src", "ghost/src"]\n')
        (tmp_path / "exists" / "src").mkdir(parents=True)
        roots = load_src_roots(tmp_path)
        assert [p.relative_to(tmp_path).as_posix() for p in roots] == ["exists/src"]

    def test_escaping_entry_ignored(self, tmp_path: Path):
        """A src_root entry that escapes the project root is dropped."""
        (tmp_path / "pyproject.toml").write_text('[tool.codemap]\nsrc_roots = ["../outside", "in/src"]\n')
        (tmp_path / "in" / "src").mkdir(parents=True)
        roots = load_src_roots(tmp_path)
        assert [p.relative_to(tmp_path).as_posix() for p in roots] == ["in/src"]

    def test_no_pyproject_returns_empty(self, tmp_path: Path):
        """A project without pyproject.toml has no configured roots."""
        assert load_src_roots(tmp_path) == []


# ── pure naming / ranking helpers ─────────────────────────────────────────────────


class TestEffectiveSrcRoot:
    """_effective_src_root maps a file to its first-matching configured root."""

    def test_first_matching_root_by_priority(self, tmp_path: Path):
        """A file under the first root is named relative to that root."""
        r0 = tmp_path / "libs" / "core" / "src"
        r1 = tmp_path / "services" / "api" / "src"
        fp = r0 / "pkg_a" / "mod_a.py"
        assert _effective_src_root(fp, (r0, r1), tmp_path) == r0

    def test_second_root_matches_when_first_does_not(self, tmp_path: Path):
        """A file only under the second root uses the second root."""
        r0 = tmp_path / "libs" / "core" / "src"
        r1 = tmp_path / "services" / "api" / "src"
        fp = r1 / "pkg_b" / "mod_b.py"
        assert _effective_src_root(fp, (r0, r1), tmp_path) == r1

    def test_falls_back_to_default_when_no_root_matches(self, tmp_path: Path):
        """A file under no configured root falls back to the default root."""
        r0 = tmp_path / "libs" / "core" / "src"
        fp = tmp_path / "other" / "stray.py"
        assert _effective_src_root(fp, (r0,), tmp_path) == tmp_path

    def test_no_configured_roots_uses_default(self, tmp_path: Path):
        """With no configured roots every file uses the default (single-root) path."""
        fp = tmp_path / "pkg" / "mod.py"
        assert _effective_src_root(fp, (), tmp_path) == tmp_path


class TestSrcRootRels:
    """_src_root_rels normalises single-string and tuple forms, dropping empties."""

    def test_single_string_wrapped(self):
        """A lone rel string becomes a one-element tuple."""
        assert _src_root_rels("src") == ("src",)

    def test_empty_string_dropped(self):
        """The project-root sentinel carries no ranking signal and is dropped."""
        assert _src_root_rels("") == ()

    def test_tuple_filters_empty_entries(self):
        """Empty entries inside a priority tuple are removed, order preserved."""
        assert _src_root_rels(("libs/core/src", "", "services/api/src")) == (
            "libs/core/src",
            "services/api/src",
        )


class TestUnderRootRank:
    """_under_root_rank ranks a path by the first source root it lies under."""

    def test_first_root_ranks_zero(self):
        """A path under the highest-priority root ranks 0."""
        assert _under_root_rank("libs/core/src/pkg/m.py", ("libs/core/src", "services/api/src")) == 0

    def test_second_root_ranks_one(self):
        """A path under the second root ranks 1 (after the first)."""
        assert _under_root_rank("services/api/src/pkg/m.py", ("libs/core/src", "services/api/src")) == 1

    def test_no_root_ranks_after_all(self):
        """A path under no configured root ranks after every configured root."""
        assert _under_root_rank("stray/m.py", ("libs/core/src", "services/api/src")) == 2

    def test_single_root_matches_legacy_binary_ranking(self):
        """One root reproduces the original under(0)/outside(1) ranking."""
        assert _under_root_rank("src/m.py", ("src",)) == 0
        assert _under_root_rank("copy/m.py", ("src",)) == 1


class TestDedupKeyMultiRoot:
    """_dedup_key ranks candidate paths across multiple priority-ordered roots."""

    def test_earlier_root_beats_later_root(self):
        """A path under the first root outranks one under the second, regardless of length."""
        roots = ("libs/core/src", "services/api/src")
        assert _dedup_key("libs/core/src/deep/nested/m.py", roots) < _dedup_key("services/api/src/m.py", roots)

    def test_any_root_beats_non_root(self):
        """A path under any configured root beats a stray copy under none."""
        roots = ("libs/core/src", "services/api/src")
        assert _dedup_key("services/api/src/pkg/m.py", roots) < _dedup_key("vendor/pkg/m.py", roots)

    def test_legacy_single_string_still_supported(self):
        """The pre-existing single-rel-string call form keeps working."""
        assert _dedup_key("src/m.py", "src") < _dedup_key("copy/m.py", "src")


class TestDedupModulesRootAware:
    """_dedup_modules resolves collisions using multi-root priority."""

    def test_root_path_beats_stray_copy_deterministically(self):
        """A configured-root path always wins over a stray copy across input orders."""
        entries = [
            {"name": "pkg_b.mod_b", "path": "vendor/pkg_b/mod_b.py"},
            {"name": "pkg_b.mod_b", "path": "services/api/src/pkg_b/mod_b.py"},
        ]
        roots = ("libs/core/src", "services/api/src")
        winners = set()
        for order in (entries, list(reversed(entries)), entries):
            kept, collisions = _dedup_modules(list(order), roots)
            assert len(kept) == 1
            winners.add(kept[0]["path"])
            assert collisions == [
                {
                    "name": "pkg_b.mod_b",
                    "kept": "services/api/src/pkg_b/mod_b.py",
                    "dropped": ["vendor/pkg_b/mod_b.py"],
                }
            ]
        assert winners == {"services/api/src/pkg_b/mod_b.py"}

    def test_earlier_root_wins_over_later_root(self):
        """When the same name appears under two roots, the first-listed root wins."""
        entries = [
            {"name": "shared.mod", "path": "services/api/src/shared/mod.py"},
            {"name": "shared.mod", "path": "libs/core/src/shared/mod.py"},
        ]
        roots = ("libs/core/src", "services/api/src")
        kept, collisions = _dedup_modules(entries, roots)
        assert kept[0]["path"] == "libs/core/src/shared/mod.py"
        assert collisions[0]["kept"] == "libs/core/src/shared/mod.py"


# ── end-to-end scan behaviour ─────────────────────────────────────────────────────


class TestMonorepoScan:
    """A real scan of a two-root monorepo names both packages and records the roots."""

    def test_dotted_names_derive_from_each_root(self, tmp_path: Path, scan_index):
        """Modules under each configured root get names relative to that root."""
        _materialize_monorepo(tmp_path)
        index = _scan_and_load(scan_index, tmp_path)
        names = {m["name"] for m in index["modules"]}
        assert {"pkg_a", "pkg_a.mod_a", "pkg_b", "pkg_b.mod_b"}.issubset(names)

    def test_meta_records_effective_roots(self, tmp_path: Path, scan_index):
        """The index meta lists both configured source roots and flags a src layout."""
        _materialize_monorepo(tmp_path)
        index = _scan_and_load(scan_index, tmp_path)
        assert index["src_roots"] == ["libs/core/src", "services/api/src"]
        assert index["src_layout"] is True

    def test_root_path_wins_collision_over_stray_copy(self, tmp_path: Path, scan_index):
        """A stray copy of a package colliding with a root path loses deterministically.

        The stray sits directly at the project root, so single-root fallback names it
        ``pkg_b.mod_b`` — colliding with the real package under ``services/api/src``.
        The configured-root path must win, since it ranks under a source root and the
        stray is under none.
        """
        _materialize_monorepo(tmp_path)
        stray = tmp_path / "pkg_b"
        stray.mkdir()
        (stray / "__init__.py").write_text("")
        (stray / "mod_b.py").write_text("def b():\n    return 99\n")

        index = _scan_and_load(scan_index, tmp_path)
        collision = next((c for c in index["collisions"] if c["name"] == "pkg_b.mod_b"), None)
        assert collision is not None
        assert collision["kept"] == "services/api/src/pkg_b/mod_b.py"
        assert "pkg_b/mod_b.py" in collision["dropped"]
        kept_path = next(m["path"] for m in index["modules"] if m["name"] == "pkg_b.mod_b")
        assert kept_path == "services/api/src/pkg_b/mod_b.py"


class TestNoConfigRegression:
    """A project without src_roots behaves exactly as single-root detection always did."""

    def test_src_root_layout_named_without_config(self, tmp_path: Path, scan_index):
        """A conventional src/ layout with no src_roots names the package under src/."""
        pkg = tmp_path / "src" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("def f():\n    return 0\n")

        index = _scan_and_load(scan_index, tmp_path)
        names = {m["name"] for m in index["modules"]}
        assert {"mypkg", "mypkg.core"}.issubset(names)
        assert index["src_roots"] == ["src"]
        assert index["src_layout"] is True

    def test_flat_repo_has_no_src_layout(self, tmp_path: Path, scan_index):
        """A flat repo (package at root) records no source-root layout."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "mod.py").write_text("def f():\n    return 0\n")

        index = _scan_and_load(scan_index, tmp_path)
        names = {m["name"] for m in index["modules"]}
        assert {"pkg", "pkg.mod"}.issubset(names)
        assert index["src_roots"] == []
        assert index["src_layout"] is False

    def test_resolve_src_roots_collapses_to_single_root(self, tmp_path: Path):
        """Without config, the resolved context uses only the detected default root."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        ctx = _resolve_src_roots(tmp_path)
        assert ctx.configured == ()
        assert ctx.dedup_rels(tmp_path) == ()


class TestMonorepoIncrementalScan:
    """Incremental re-scan preserves multi-root naming for changed files."""

    def test_incremental_names_new_file_under_its_root(self, tmp_path: Path, scan_index):
        """A file added under the second root after the initial scan is named from that root."""
        _materialize_monorepo(tmp_path)
        _scan_and_load(scan_index, tmp_path)

        new_mod = tmp_path / "services" / "api" / "src" / "pkg_b" / "extra.py"
        new_mod.write_text("def c():\n    return 3\n")
        index = _scan_and_load(scan_index, tmp_path, "--incremental")

        names = {m["name"] for m in index["modules"]}
        assert "pkg_b.extra" in names
        assert index["src_roots"] == ["libs/core/src", "services/api/src"]
