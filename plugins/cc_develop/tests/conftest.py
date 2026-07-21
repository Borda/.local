"""Pytest fixtures for develop plugin bin/ tests.

Adds ``plugins/cc_develop/bin/`` to ``sys.path`` so test modules can import the script directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))
