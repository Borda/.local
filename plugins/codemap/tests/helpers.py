"""Shared constants and helpers for codemap bin integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).parent.parent / "bin"

SCAN_INDEX = BIN / "scan-index"
SCAN_QUERY = BIN / "scan-query"

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


def query(project_fixture: tuple, *args: str) -> dict:
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
