"""Acceptance checks for the read-only agent-shims manager surface."""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
GENERATOR_PATH = SCRIPTS / "generate_roles.py"
LIFECYCLE_PATH = SCRIPTS / "_agent_shim_lifecycle.py"
JOURNAL_PATH = SCRIPTS / "_agent_shim_journal.py"
OBSERVER_PATH = SCRIPTS / "_agent_shim_observe.py"
MANAGER_PATH = SCRIPTS / "manage_role_agents.py"


def load_module(path: Path, name: str) -> ModuleType:
    """Load the manager with its direct sibling dependencies available."""
    if path == LIFECYCLE_PATH and "generate_roles" not in sys.modules:
        load_module(GENERATOR_PATH, "generate_roles")
    if path == JOURNAL_PATH and "_agent_shim_lifecycle" not in sys.modules:
        load_module(LIFECYCLE_PATH, "_agent_shim_lifecycle")
    if path == OBSERVER_PATH:
        for dependency, module_name in (
            (GENERATOR_PATH, "generate_roles"),
            (LIFECYCLE_PATH, "_agent_shim_lifecycle"),
            (JOURNAL_PATH, "_agent_shim_journal"),
        ):
            if module_name not in sys.modules:
                load_module(dependency, module_name)
    if path == MANAGER_PATH:
        for dependency, module_name in (
            (GENERATOR_PATH, "generate_roles"),
            (OBSERVER_PATH, "_agent_shim_observe"),
        ):
            if module_name not in sys.modules:
                load_module(dependency, module_name)
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    """Capture mutation-relevant bytes and metadata while excluding atime."""
    rows = []
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        rows.append(
            (
                str(path.relative_to(root)),
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_ino,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
                path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None,
            )
        )
    return tuple(rows)


def executable(tmp_path: Path) -> Path:
    """Create one bounded executable used only as Codex identity evidence."""
    path = tmp_path / "codex"
    path.write_bytes(b"#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return path


def test_doctor_validates_package_without_writing_user_state(tmp_path: Path) -> None:
    """Report verified local prerequisites while preserving every home byte."""
    module = load_module(MANAGER_PATH, "codex_rig_manager_doctor")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    codex = executable(tmp_path)
    before = snapshot(tmp_path)

    result = module.diagnose(
        action="doctor",
        codex_home=home,
        plugin_root=PLUGIN_ROOT,
        codex_binary=codex,
        check_active_package=False,
    )

    assert result.classification == "degraded"
    assert result.checks["package"].status == "pass"
    assert result.checks["executables"].status == "pass"
    assert result.checks["active_package"].status == "degraded"
    assert result.state == "absent"
    assert result.targets == "absent"
    assert snapshot(tmp_path) == before


def test_status_reports_corrupt_state_as_blocked_without_mutation(tmp_path: Path) -> None:
    """Expose untrusted state without repair, adoption, or cleanup writes."""
    module = load_module(MANAGER_PATH, "codex_rig_manager_status")
    home = tmp_path / "home"
    state = home / "codex-rig" / "shims"
    state.mkdir(parents=True, mode=0o700)
    state.chmod(0o700)
    (home / "codex-rig").chmod(0o700)
    (home / "agents").mkdir(mode=0o700)
    payload = state / "state.json"
    payload.write_bytes(b"corrupt")
    payload.chmod(0o600)
    codex = executable(tmp_path)
    before = snapshot(tmp_path)

    result = module.diagnose(
        action="status",
        codex_home=home,
        plugin_root=PLUGIN_ROOT,
        codex_binary=codex,
        check_active_package=False,
    )

    assert result.classification == "blocked"
    assert result.state == "corrupt"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [([], 2), (["unknown"], 2), (["doctor", "extra"], 2), (["install"], 5), (["remove"], 5)],
)
def test_public_grammar_rejects_invalid_or_unwired_mutation_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    expected: int,
) -> None:
    """Keep the one-action grammar deterministic with no hidden bypass flags."""
    module = load_module(MANAGER_PATH, f"codex_rig_manager_grammar_{expected}_{len(arguments)}")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("CODEX_HOME", str(home))
    before = snapshot(tmp_path)

    assert module.main(arguments) == expected
    output = capsys.readouterr().out

    assert "classification" in output
    assert snapshot(tmp_path) == before


def test_doctor_refuses_symlinked_home_alias(tmp_path: Path) -> None:
    """Block unresolved home aliases instead of silently changing authority."""
    module = load_module(MANAGER_PATH, "codex_rig_manager_alias")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(home, target_is_directory=True)

    with pytest.raises(ValueError, match="canonical non-symlink"):
        module.diagnose(
            action="doctor",
            codex_home=linked,
            plugin_root=PLUGIN_ROOT,
            codex_binary=executable(tmp_path),
            check_active_package=False,
        )
