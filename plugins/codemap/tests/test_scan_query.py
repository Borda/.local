"""Integration tests for scan-query bin script.

Uses the shared `project` fixture from conftest.py (scan-index run once,
module-scoped). Tests module-level and symbol-level queries, call-graph
commands, and edge cases.

Fixture layout:
    gamma.py          — leaf module, no imports; defines func_gamma
    beta.py           — imports gamma; defines func_beta calling func_gamma
    alpha.py          — imports beta, gamma; defines func_alpha calling func_beta
    pkg/__init__.py   — empty
    pkg/delta.py      — imports alpha; defines func_delta calling func_alpha
"""

from __future__ import annotations

import json
import subprocess
import sys


class TestModuleQueries:
    """Module-level dependency queries: rdeps, deps, path, central, list."""

    def test_rdeps_leaf(self, query):
        """gamma is imported by alpha and beta — rdeps must include both."""
        data = query("rdeps", "gamma")
        importers = set(data["imported_by"])
        assert "alpha" in importers
        assert "beta" in importers

    def test_rdeps_excludes_non_importers(self, query):
        """gamma is NOT imported by delta — must not appear in rdeps."""
        data = query("rdeps", "gamma")
        assert "pkg.delta" not in data["imported_by"]

    def test_deps(self, query):
        """alpha imports both beta and gamma."""
        data = query("deps", "alpha")
        imports = set(data["direct_imports"])
        assert "beta" in imports
        assert "gamma" in imports

    def test_central_top_module(self, query):
        """gamma has rdep_count >= all others (imported by alpha + beta)."""
        data = query("central", "--top", "10")
        names = [entry["name"] for entry in data["central"]]
        assert "gamma" in names
        gamma_rank = names.index("gamma")
        assert gamma_rank < names.index("pkg.delta") if "pkg.delta" in names else True

    def test_path_exists(self, query):
        """pkg.delta → alpha → gamma is a valid 3-hop import path."""
        data = query("path", "pkg.delta", "gamma")
        path = data["path"]
        assert path is not None, "expected a path, got null"
        assert path[0] == "pkg.delta"
        assert path[-1] == "gamma"
        assert len(path) == 3  # delta → alpha → gamma

    def test_path_not_found(self, query):
        """gamma does not import anything — no path gamma → alpha."""
        data = query("path", "gamma", "alpha")
        assert data["path"] is None

    def test_list_contains_all_modules(self, query):
        """list command returns all 5 modules."""
        data = query("list")
        names = {m["name"] for m in data["modules"]}
        assert {"alpha", "beta", "gamma", "pkg", "pkg.delta"}.issubset(names)


class TestSymbolQueries:
    """Symbol-level queries: lookup by name, by module, and by regex."""

    def test_symbol_by_name(self, query):
        """symbol query returns source for func_gamma."""
        data = query("symbol", "func_gamma")
        assert data.get("symbols"), "expected at least one symbol match"
        src = data["symbols"][0]["source"]
        assert "def func_gamma" in src
        assert "return x + 1" in src

    def test_symbols_in_module(self, query):
        """symbols alpha lists func_alpha."""
        data = query("symbols", "alpha")
        names = {s["name"] for s in data["symbols"]}
        assert "func_alpha" in names

    def test_find_symbol_regex(self, query):
        """find-symbol '^func_' matches all four functions."""
        data = query("find-symbol", "^func_")
        names = {m["qualified_name"] for m in data["matches"]}
        assert any("func_gamma" in n for n in names)
        assert any("func_alpha" in n for n in names)
        assert any("func_beta" in n for n in names)
        assert any("func_delta" in n for n in names)


class TestFunctionCallGraph:
    """Function-level call-graph queries (v3 index): fn-deps, fn-rdeps, fn-central, fn-blast."""

    def test_fn_deps(self, query):
        """func_alpha calls func_beta and func_gamma."""
        data = query("fn-deps", "alpha::func_alpha")
        callees = {e["target"] for e in data.get("calls", [])}
        assert any("func_beta" in t for t in callees)
        assert any("func_gamma" in t for t in callees)

    def test_fn_rdeps(self, query):
        """func_gamma is called by func_beta (and transitively func_alpha)."""
        data = query("fn-rdeps", "gamma::func_gamma")
        callers = {e["caller"] for e in data.get("called_by", [])}
        assert any("func_beta" in t for t in callers)

    def test_fn_central_includes_func_gamma(self, query):
        """func_gamma called by multiple functions → appears in fn-central."""
        data = query("fn-central", "--top", "10")
        names = [e["qname"] for e in data.get("fn_central", [])]
        assert any("func_gamma" in n for n in names)

    def test_fn_blast(self, query):
        """fn-blast gamma::func_gamma surfaces callers at depth >= 1."""
        data = query("fn-blast", "gamma::func_gamma")
        blast = data.get("blast_radius", [])
        assert len(blast) >= 1
        callers = {e["caller"] for e in blast}
        assert any("func_beta" in t for t in callers)


def test_rdeps_unknown_module(query):
    """rdeps on a module not in index returns empty imported_by list."""
    data = query("rdeps", "nonexistent.module.xyz")
    assert data.get("imported_by", []) == []


def test_path_same_module(project, scan_query):
    """path A A should return [A] or null — not crash."""
    root, index_path = project
    result = subprocess.run(
        [
            sys.executable,
            str(scan_query),
            "--index",
            str(index_path),
            "path",
            "gamma",
            "gamma",
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "path" in data


class TestRdepsNewFields:
    """rdeps output includes dynamic_imported_by and config_refs fields."""

    def test_rdeps_has_dynamic_imported_by_key(self, query):
        """rdeps result always carries dynamic_imported_by key, even when empty."""
        data = query("rdeps", "gamma")
        assert "dynamic_imported_by" in data

    def test_rdeps_has_config_refs_key(self, query):
        """rdeps result always carries config_refs key, even when empty."""
        data = query("rdeps", "gamma")
        assert "config_refs" in data

    def test_rdeps_dynamic_imported_by_is_list(self, query):
        """dynamic_imported_by is a list (may be empty for modules with no dynamic callers)."""
        data = query("rdeps", "gamma")
        assert isinstance(data["dynamic_imported_by"], list)

    def test_rdeps_config_refs_is_list(self, query):
        """config_refs is a list (may be empty when no config files reference the module)."""
        data = query("rdeps", "gamma")
        assert isinstance(data["config_refs"], list)
