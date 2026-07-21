"""Pytest path fixture for Codex Rig executable modules.

Mirrors ``plugins/cc_develop/conftest.py``: adds directories containing executable
modules to ``sys.path`` so ``--doctest-modules`` can resolve sibling imports.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_WINDOWS_UNSUPPORTED_PATHS = (
    "scripts/_agent_shim_posix.py",
    "scripts/_agent_shim_transaction.py",
    "tests/test_agent_shim_posix.py",
    "tests/test_agent_shim_transaction.py",
)


def _unsupported_collection_paths(platform: str) -> tuple[str, ...]:
    """Return exact lifecycle files that cannot run on the selected platform."""
    return _WINDOWS_UNSUPPORTED_PATHS if platform == "win32" else ()


collect_ignore = list(_unsupported_collection_paths(sys.platform))

_PLUGIN_DIR = Path(__file__).resolve().parent
for _MODULE_DIR in (_PLUGIN_DIR / "scripts", _PLUGIN_DIR / "runtime" / "calibration"):
    if str(_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(_MODULE_DIR))

_CANONICAL_SCRIPT_MODULES = (
    "generate_roles",
    "_agent_shim_approval",
    "_agent_shim_journal",
    "_agent_shim_lifecycle",
    "_agent_shim_observe",
    "_agent_shim_plan",
    "_agent_shim_posix",
    "_agent_shim_transaction",
    "manage_role_agents",
)


@pytest.fixture(autouse=True)
def isolate_canonical_script_modules() -> Iterator[None]:
    """Keep test-loaded script classes isolated from doctest collection modules."""
    saved = {name: sys.modules[name] for name in _CANONICAL_SCRIPT_MODULES if name in sys.modules}
    for name in _CANONICAL_SCRIPT_MODULES:
        sys.modules.pop(name, None)

    try:
        yield
    finally:
        for name in _CANONICAL_SCRIPT_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
