"""Make this directory importable so pytest can collect its doctests.

The scripts here are standalone CLIs run as `python debugging/<script>.py`, so they
import their shared helper as a top-level module (`from _usage import ...`) rather than
as a package. Under pytest's `--import-mode=importlib` nothing is added to `sys.path`,
so that import fails at collection time. Inserting this directory keeps both entry
points working: direct CLI execution and `--doctest-modules` collection.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
