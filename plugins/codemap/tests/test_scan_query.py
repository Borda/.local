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

from conftest import SCAN_QUERY, query


class TestModuleQueries:
    """Module-level dependency queries: rdeps, deps, path, central, list."""

    def test_rdeps_leaf(self, project):
        """gamma is imported by alpha and beta — rdeps must include both."""
        data = query(project, "rdeps", "gamma")
        importers = set(data["imported_by"])
        assert "alpha" in importers
        assert "beta" in importers

    def test_rdeps_excludes_non_importers(self, project):
        """gamma is NOT imported by delta — must not appear in rdeps."""
        data = query(project, "rdeps", "gamma")
        assert "pkg.delta" not in data["imported_by"]

    def test_deps(self, project):
        """alpha imports both beta and gamma."""
        data = query(project, "deps", "alpha")
        imports = set(data["direct_imports"])
        assert "beta" in imports
        assert "gamma" in imports

    def test_central_top_module(self, project):
        """gamma has rdep_count >= all others (imported by alpha + beta)."""
        data = query(project, "central", "--top", "10")
        names = [entry["name"] for entry in data["central"]]
        assert "gamma" in names
        gamma_rank = names.index("gamma")
        assert gamma_rank < names.index("pkg.delta") if "pkg.delta" in names else True

    def test_path_exists(self, project):
        """pkg.delta → alpha → gamma is a valid 3-hop import path."""
        data = query(project, "path", "pkg.delta", "gamma")
        path = data["path"]
        assert path is not None, "expected a path, got null"
        assert path[0] == "pkg.delta"
        assert path[-1] == "gamma"
        assert len(path) == 3  # delta → alpha → gamma

    def test_path_not_found(self, project):
        """gamma does not import anything — no path gamma → alpha."""
        data = query(project, "path", "gamma", "alpha")
        assert data["path"] is None

    def test_list_contains_all_modules(self, project):
        """list command returns all 5 modules."""
        data = query(project, "list")
        names = {m["name"] for m in data["modules"]}
        assert {"alpha", "beta", "gamma", "pkg", "pkg.delta"}.issubset(names)


class TestSymbolQueries:
    """Symbol-level queries: lookup by name, by module, and by regex."""

    def test_symbol_by_name(self, project):
        """symbol query returns source for func_gamma."""
        data = query(project, "symbol", "func_gamma")
        assert data.get("symbols"), "expected at least one symbol match"
        src = data["symbols"][0]["source"]
        assert "def func_gamma" in src
        assert "return x + 1" in src

    def test_symbols_in_module(self, project):
        """symbols alpha lists func_alpha."""
        data = query(project, "symbols", "alpha")
        names = {s["name"] for s in data["symbols"]}
        assert "func_alpha" in names

    def test_find_symbol_regex(self, project):
        """find-symbol '^func_' matches all four functions."""
        data = query(project, "find-symbol", "^func_")
        names = {m["qualified_name"] for m in data["matches"]}
        assert any("func_gamma" in n for n in names)
        assert any("func_alpha" in n for n in names)
        assert any("func_beta" in n for n in names)
        assert any("func_delta" in n for n in names)


class TestFunctionCallGraph:
    """Function-level call-graph queries (v3 index): fn-deps, fn-rdeps, fn-central, fn-blast."""

    def test_fn_deps(self, project):
        """func_alpha calls func_beta and func_gamma."""
        data = query(project, "fn-deps", "alpha::func_alpha")
        callees = {e["target"] for e in data.get("calls", [])}
        assert any("func_beta" in t for t in callees)
        assert any("func_gamma" in t for t in callees)

    def test_fn_rdeps(self, project):
        """func_gamma is called by func_beta (and transitively func_alpha)."""
        data = query(project, "fn-rdeps", "gamma::func_gamma")
        callers = {e["caller"] for e in data.get("called_by", [])}
        assert any("func_beta" in t for t in callers)

    def test_fn_central_includes_func_gamma(self, project):
        """func_gamma called by multiple functions → appears in fn-central."""
        data = query(project, "fn-central", "--top", "10")
        names = [e["qname"] for e in data.get("fn_central", [])]
        assert any("func_gamma" in n for n in names)

    def test_fn_blast(self, project):
        """fn-blast gamma::func_gamma surfaces callers at depth >= 1."""
        data = query(project, "fn-blast", "gamma::func_gamma")
        blast = data.get("blast_radius", [])
        assert len(blast) >= 1
        callers = {e["caller"] for e in blast}
        assert any("func_beta" in t for t in callers)


def test_rdeps_unknown_module(project):
    """rdeps on a module not in index returns empty imported_by list."""
    data = query(project, "rdeps", "nonexistent.module.xyz")
    assert data.get("imported_by", []) == []


def test_path_same_module(project):
    """path A A should return [A] or null — not crash."""
    root, index_path = project
    result = subprocess.run(
        [
            sys.executable,
            str(SCAN_QUERY),
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
