"""Pytest path fixture for develop plugin ``bin/`` modules.

Mirrors ``tests/conftest.py``: adds ``plugins/develop/bin/`` to ``sys.path`` so that
``--doctest-modules`` collection of ``bin/*.py`` files can resolve sibling imports
(e.g. ``build_codemap_batch`` → ``codemap_scan``). Direct script execution never
needs this — Python puts the script's own directory on ``sys.path`` — and the
``tests/`` conftest does not apply to collection under ``bin/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))
