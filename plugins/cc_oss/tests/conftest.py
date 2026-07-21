"""Auto-load all bin/ Python scripts as importable modules.

Registers each ``plugins/cc_oss/bin/<name>.py`` under the alias
``<name>`` with hyphens replaced by underscores, so tests can
``from parse_resolve_args import parse_resolve_args`` directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_BIN_DIR = Path(__file__).parent.parent / "bin"


@pytest.fixture(autouse=True)
def _no_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip session-scoping env vars so TMPDIR sentinel tests are deterministic.

    Without this, a test run from inside a live Claude Code session inherits
    ``CLAUDE_CODE_SESSION_ID`` from the ambient shell, making CSID-suffixed
    filenames unpredictable across environments. Absent both vars, bin/
    scripts fall back to the literal ``"shared"`` token.
    """
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CSID", raising=False)


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
