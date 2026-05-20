"""Shared fixtures for codemap bin integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

_BIN_DIR = Path(__file__).parent.parent / "bin"
# bin/ on sys.path so test files can import bin/ Python modules directly.
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))


@pytest.fixture(scope="session")
def scan_index() -> Path:
    """Path to the scan-index bin script."""
    return _BIN_DIR / "scan-index"


@pytest.fixture(scope="session")
def scan_query() -> Path:
    """Path to the scan-query bin script."""
    return _BIN_DIR / "scan-query"


@pytest.fixture(scope="session")
def gamma_src() -> str:
    """Source for gamma module — leaf, no imports."""
    return """\
def func_gamma(x):
    return x + 1
"""


@pytest.fixture(scope="session")
def beta_src() -> str:
    """Source for beta module — imports gamma."""
    return """\
import gamma

def func_beta(x):
    return gamma.func_gamma(x) * 2
"""


@pytest.fixture(scope="session")
def alpha_src() -> str:
    """Source for alpha module — imports beta and gamma."""
    return """\
import beta
import gamma

def func_alpha(x):
    return beta.func_beta(x) + gamma.func_gamma(x)
"""


@pytest.fixture(scope="session")
def delta_src() -> str:
    """Source for delta module — imports alpha."""
    return """\
import alpha

def func_delta(x):
    return alpha.func_alpha(x)
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory, gamma_src, beta_src, alpha_src, delta_src, scan_index):
    """Build fixture project, scan once, return (root, index_path)."""
    root = tmp_path_factory.mktemp("proj")
    (root / "gamma.py").write_text(gamma_src)
    (root / "beta.py").write_text(beta_src)
    (root / "alpha.py").write_text(alpha_src)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "delta.py").write_text(delta_src)

    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(root)],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr

    index_path = root / ".cache" / "scan" / f"{root.name}.json"
    assert index_path.exists(), "scan-index did not produce index file"
    return root, index_path


@pytest.fixture(scope="module")
def query(project, scan_query) -> Callable[..., dict]:
    """Return callable that runs scan-query against the module-scoped project."""
    root, index_path = project

    def _query(*args: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(scan_query), "--index", str(index_path), *args],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        assert result.returncode == 0, result.stderr + result.stdout
        return json.loads(result.stdout)

    return _query
