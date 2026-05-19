"""Shared fixtures and helpers for codemap bin integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent / "bin"

# Add bin/ to sys.path so new Python scripts can be imported directly in tests.
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))
SCAN_INDEX = BIN / "scan-index"
SCAN_QUERY = BIN / "scan-query"

# ---------------------------------------------------------------------------
# Fixture source files
# ---------------------------------------------------------------------------

GAMMA_SRC = """\
def func_gamma(x):
    return x + 1
"""

BETA_SRC = """\
import gamma

def func_beta(x):
    return gamma.func_gamma(x) * 2
"""

ALPHA_SRC = """\
import beta
import gamma

def func_alpha(x):
    return beta.func_beta(x) + gamma.func_gamma(x)
"""

DELTA_SRC = """\
import alpha

def func_delta(x):
    return alpha.func_alpha(x)
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """Build fixture project, scan once, return (root, index_path)."""
    root = tmp_path_factory.mktemp("proj")
    (root / "gamma.py").write_text(GAMMA_SRC)
    (root / "beta.py").write_text(BETA_SRC)
    (root / "alpha.py").write_text(ALPHA_SRC)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "delta.py").write_text(DELTA_SRC)

    result = subprocess.run(
        [sys.executable, str(SCAN_INDEX), "--root", str(root)],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr

    index_path = root / ".cache" / "scan" / f"{root.name}.json"
    assert index_path.exists(), "scan-index did not produce index file"
    return root, index_path


def query(project_fixture, *args):
    """Run scan-query with --index and return parsed JSON."""
    root, index_path = project_fixture
    result = subprocess.run(
        [sys.executable, str(SCAN_QUERY), "--index", str(index_path), *args],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)
