"""Acceptance checks for Codex Rig's platform-specific pytest collection policy."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONFTEST_PATH = PLUGIN_ROOT / "conftest.py"
MANAGER_PATH = PLUGIN_ROOT / "scripts" / "manage_role_agents.py"


def load_conftest() -> ModuleType:
    """Load the plugin conftest as an ordinary module for policy checks."""
    specification = importlib.util.spec_from_file_location("codex_rig_collection_policy", CONFTEST_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_windows_ignores_only_unsupported_posix_lifecycle_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep native Windows away from exact POSIX files without hiding portable coverage."""
    monkeypatch.setattr(sys, "platform", "win32")
    module = load_conftest()

    expected = (
        "scripts/_agent_shim_posix.py",
        "scripts/_agent_shim_transaction.py",
        "tests/test_agent_shim_posix.py",
        "tests/test_agent_shim_transaction.py",
    )
    assert module.collect_ignore == list(expected)
    assert module._unsupported_collection_paths("win32") == expected
    assert module._unsupported_collection_paths("darwin") == ()
    assert module._unsupported_collection_paths("linux") == ()


@pytest.mark.parametrize(
    ("action", "expected_code"),
    [("install", 5), ("remove", 5)],
)
def test_windows_manager_blocks_mutation_before_posix_imports_or_writes(
    action: str,
    expected_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep unsupported persistent-shim mutation outside the Windows diagnostic path."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent-home"))
    specification = importlib.util.spec_from_file_location(f"codex_rig_windows_manager_{action}", MANAGER_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, specification.name, module)
    before = tuple(tmp_path.rglob("*"))
    specification.loader.exec_module(module)

    assert module.main([action]) == expected_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == action
    assert payload["classification"] == "platform-blocked"
    assert payload["writes"] == 0
    assert tuple(tmp_path.rglob("*")) == before
