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


class TestSymbolStaleAndImports:
    """Per-symbol stale field (M2) and optional --with-imports block (C3)."""

    def test_symbol_stale_false_on_fresh_index(self, query):
        """Symbol from a fresh index reports stale=False."""
        data = query("symbol", "func_gamma")
        assert data["symbols"], "expected at least one symbol match"
        assert data["symbols"][0]["stale"] is False

    def test_symbol_stale_reason_none_on_fresh(self, query):
        """stale_reason is the JSON null (Python None), not the string 'None'."""
        data = query("symbol", "func_gamma")
        assert data["symbols"], "expected at least one symbol match"
        assert data["symbols"][0]["stale_reason"] is None

    def test_symbol_with_imports_flag(self, query):
        """--with-imports populates the imports field for a module that imports another."""
        data = query("symbol", "--with-imports", "func_beta")
        assert data["symbols"], "expected at least one symbol match"
        imports = data["symbols"][0]["imports"]
        assert imports is not None, "imports field should be populated when --with-imports is set"
        assert "import" in imports, f"expected an import statement in imports block, got: {imports!r}"

    def test_symbol_no_imports_flag_default(self, query):
        """Without --with-imports, imports field is JSON null."""
        data = query("symbol", "func_gamma")
        assert data["symbols"], "expected at least one symbol match"
        assert data["symbols"][0]["imports"] is None

    def test_symbol_imports_empty_for_no_import_module(self, query):
        """--with-imports on a module without imports returns an empty string (or None)."""
        data = query("symbol", "--with-imports", "func_gamma")
        assert data["symbols"], "expected at least one symbol match"
        imports = data["symbols"][0]["imports"]
        assert imports in ("", None), f"expected empty import block for gamma, got: {imports!r}"

    def test_symbol_stale_file_deleted(self, tmp_path, scan_index, scan_query):
        """Deleting source file after indexing produces stale=True, reason='file deleted'."""
        import json
        import subprocess

        root = tmp_path
        (root / "myfunc.py").write_text("def myfunc(x):\n    return x\n")
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        (root / "myfunc.py").unlink()
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "myfunc"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"], "expected symbol still in index"
        sym = data["symbols"][0]
        assert sym["stale"] is True
        assert sym["stale_reason"] == "file deleted"

    def test_symbol_stale_line_range_past_eof(self, tmp_path, scan_index, scan_query):
        """Truncating file below indexed end_line produces stale=True, reason='line range past EOF'."""
        import json
        import subprocess

        root = tmp_path / "truncate"
        root.mkdir()
        (root / "big.py").write_text("def bigfunc(x):\n    return x * 2\n")
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        (root / "big.py").write_text("# truncated\n")
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "bigfunc"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        sym = data["symbols"][0]
        assert sym["stale"] is True
        assert sym["stale_reason"] == "line range past EOF"

    def test_symbol_stale_prefix_name_at_indexed_location(self, tmp_path, scan_index, scan_query):
        """Renaming function to prefix-extended name at same lines → stale=True (not false-negative)."""
        import json
        import subprocess

        root = tmp_path / "prefix"
        root.mkdir()
        (root / "helpers.py").write_text("def helper(x):\n    return x\n")
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        (root / "helpers.py").write_text("def helper_v2(x):\n    return x\n")
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "helper"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        sym = data["symbols"][0]
        assert sym["stale"] is True, "helper_v2 at helper's lines must be detected stale"

    def test_with_imports_one_line_docstring(self, tmp_path, scan_index, scan_query):
        """--with-imports extracts imports even when file opens with a one-line module docstring."""
        import json
        import subprocess

        root = tmp_path / "docstring"
        root.mkdir()
        content = '"""Module docs."""\nimport os\nfrom pathlib import Path\n\ndef dsfunc(x):\n    return x\n'
        (root / "ds.py").write_text(content)
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "--with-imports", "dsfunc"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        imports = data["symbols"][0]["imports"]
        assert imports is not None
        assert "import os" in imports, f"expected 'import os', got: {imports!r}"
        assert "pathlib" in imports, f"expected pathlib import, got: {imports!r}"

    def test_with_imports_multiline_parenthesized(self, tmp_path, scan_index, scan_query):
        """--with-imports captures full multi-line parenthesized import block."""
        import json
        import subprocess

        root = tmp_path / "multiline"
        root.mkdir()
        content = (
            "from typing import (\n    Any,\n    Optional,\n)\n\ndef mlfunc(x: Any) -> Optional[int]:\n    return x\n"
        )
        (root / "ml.py").write_text(content)
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "--with-imports", "mlfunc"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        imports = data["symbols"][0]["imports"]
        assert imports is not None
        assert "Any" in imports, f"expected 'Any' in imports, got: {imports!r}"
        assert "Optional" in imports, f"expected 'Optional' in imports, got: {imports!r}"


class TestScanRoot:
    """scan_root stored in index + --root flag for file-path resolution."""

    def test_scan_root_stored_in_index(self, project):
        """scan-index stores absolute scan_root in index JSON."""
        root, index_path = project
        data = json.loads(index_path.read_text())
        assert "scan_root" in data, "scan_root key missing from index"
        assert data["scan_root"] == str(root.resolve())

    def test_symbol_resolves_via_scan_root(self, tmp_path, scan_index, scan_query):
        """scan-query resolves file paths via scan_root even when CWD is different."""
        root = tmp_path / "scan_root_test"
        root.mkdir()
        (root / "rootfunc.py").write_text("def rootfunc(x):\n    return x * 3\n")
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(root)],
            capture_output=True,
            cwd=str(root),
            check=True,
        )
        index_path = root / ".cache" / "codemap" / f"{root.name}.json"
        # Run query from CWD = project root (different from scan root) — relies on scan_root
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), "symbol", "rootfunc"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),  # parent dir — NOT the scan root
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        sym = data["symbols"][0]
        assert sym["stale"] is False, f"expected stale=False via scan_root, got reason={sym['stale_reason']}"
        assert "def rootfunc" in sym["source"]

    def test_root_flag_overrides_scan_root(self, tmp_path, scan_index, scan_query):
        """--root flag takes priority over scan_root stored in index."""
        # Build index in sub-dir A
        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        (dir_a / "afunc.py").write_text("def afunc(x):\n    return x + 10\n")
        subprocess.run(
            [sys.executable, str(scan_index), "--root", str(dir_a)],
            capture_output=True,
            cwd=str(dir_a),
            check=True,
        )
        index_path = dir_a / ".cache" / "codemap" / f"{dir_a.name}.json"
        # Copy file to dir_b with same relative path — --root dir_b overrides scan_root (dir_a)
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()
        (dir_b / "afunc.py").write_text("def afunc(x):\n    return x + 10\n")
        result = subprocess.run(
            [
                sys.executable,
                str(scan_query),
                "--index",
                str(index_path),
                "--root",
                str(dir_b),
                "symbol",
                "afunc",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["symbols"]
        sym = data["symbols"][0]
        assert sym["stale"] is False, f"--root override failed: stale_reason={sym['stale_reason']}"
        assert "def afunc" in sym["source"]


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
