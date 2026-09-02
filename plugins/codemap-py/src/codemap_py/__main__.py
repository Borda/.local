"""Run the Codemap command-line interface as a Python module.

With ``<plugin-root>/src`` on the import path (via ``PYTHONPATH``, an editable
install, or a checkout's ``src/`` as CWD) this reaches the same dispatcher as
``scripts/codemap_py_entry.py`` and every launcher.

Examples:
    Run from a checkout with ``src/`` on ``PYTHONPATH``::

        PYTHONPATH=src python3 -m codemap_py doctor --json
"""

from __future__ import annotations

import sys

from codemap_py.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
