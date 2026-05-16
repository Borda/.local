"""Auto-load all bin/ Python scripts as importable modules.

Registers each ``plugins/oss/bin/<name>.py`` under the alias
``<name>`` with hyphens replaced by underscores, so tests can
``from parse_resolve_args import parse_resolve_args`` directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BIN_DIR = Path(__file__).parent.parent / "bin"


def _load_bin_modules() -> None:
    for script in sorted(_BIN_DIR.glob("*.py")):
        module_name = script.stem.replace("-", "_")
        if module_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(module_name, script)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]


_load_bin_modules()
