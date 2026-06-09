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


def test_creates_index(tmp_path, gamma_src, beta_src, alpha_src, delta_src, scan_index):
    """scan-index writes .cache/scan/<name>.json containing all modules."""
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

    index_path = tmp_path / ".cache" / "scan" / f"{tmp_path.name}.json"
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

    index_path = tmp_path / ".cache" / "scan" / f"{tmp_path.name}.json"
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
