"""Acceptance checks for deterministic plugin package generation."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PLUGIN_ROOT / "scripts" / "build_package.py"


def load_builder(path: Path = BUILD_SCRIPT) -> ModuleType:
    """Load one package builder directly from its file path."""
    specification = importlib.util.spec_from_file_location("codex_rig_build_package", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def run_builder(plugin_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run an isolated package builder with bytecode writes disabled."""
    return subprocess.run(
        [sys.executable, str(plugin_root / "scripts" / "build_package.py"), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def copied_plugin(tmp_path: Path) -> Path:
    """Copy only installed-package bytes into a source-independent fixture."""
    destination = tmp_path / "installed-plugin"
    shutil.copytree(PLUGIN_ROOT, destination, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    assert not (tmp_path / ".codex").exists()
    return destination


def test_generation_is_deterministic_and_current() -> None:
    """Prevent nondeterministic fields or a stale committed package manifest."""
    builder = load_builder()

    first = builder.encode_manifest(builder.build_manifest())
    second = builder.encode_manifest(builder.build_manifest())

    assert first == second == (PLUGIN_ROOT / "package-manifest.json").read_bytes()
    assert b"/Users/" not in first
    assert b"/home/" not in first


def test_manifest_binds_the_pure_role_generator() -> None:
    """Prevent installed managers from importing unbound generator bytes."""
    builder = load_builder()
    manifest = builder.build_manifest()
    generator = PLUGIN_ROOT / "scripts" / "generate_roles.py"

    assert manifest["generator"] == {
        "version": 1,
        "path": "scripts/generate_roles.py",
        "sha256": builder.sha256(generator.read_bytes()),
    }
    record = next(item for item in manifest["files"] if item["path"] == "scripts/generate_roles.py")
    assert record == {
        "path": "scripts/generate_roles.py",
        "sha256": manifest["generator"]["sha256"],
        "mode": "0644",
    }


def test_generation_checks_source_independent_installed_copy(tmp_path: Path) -> None:
    """Prove manifest validation does not require the repository source tree."""
    installed = copied_plugin(tmp_path)

    result = run_builder(installed, "--check")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Package manifest is current.\n"


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda root: (root / "roles" / "challenger" / "ROLE.md").unlink(), "missing canonical role card"),
        (lambda root: (root / "skills" / "analyse" / "SKILL.md").unlink(), "missing workflow skill"),
    ],
    ids=["missing-role", "missing-skill"],
)
def test_generation_rejects_incomplete_public_roster(
    tmp_path: Path, mutator: Callable[[Path], None], expected: str
) -> None:
    """Prevent incomplete installed packages from receiving a fresh manifest."""
    installed = copied_plugin(tmp_path)
    mutator(installed)

    result = run_builder(installed)

    assert result.returncode == 2
    assert expected in result.stderr


def test_generation_rejects_symlinked_payload(tmp_path: Path) -> None:
    """Prevent a generated manifest from blessing a payload symlink."""
    installed = copied_plugin(tmp_path)
    target = installed / "roles" / "challenger" / "ROLE.md"
    target.unlink()
    target.symlink_to(installed / "roles" / "curator" / "ROLE.md")

    result = run_builder(installed)

    assert result.returncode == 2
    assert "symlink payload forbidden" in result.stderr
