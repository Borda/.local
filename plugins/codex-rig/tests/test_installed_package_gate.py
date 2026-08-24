"""Executable acceptance contract for the installed Codex Rig package payload."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SAFE_TEST_SELECTION = (
    "tests/test_app_server_denial_protocol.py",
    "tests/test_networked_cli_approval_contract.py",
    "tests/test_code_review_pr_failure_output_contract.py",
    "tests/test_plugin_only_release.py::test_calibration_model_stall_fixture_observations_are_scored",
)


def package_payload_paths() -> tuple[str, ...]:
    """Return the exact shipped payload paths in manifest order."""
    manifest = json.loads((PLUGIN_ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    return tuple(record["path"] for record in manifest["files"])


def copied_package_root(tmp_path: Path) -> Path:
    """Copy only the manifest-declared plugin payload into an isolated cache."""
    manifest = json.loads((PLUGIN_ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    installed_root = tmp_path / "plugins" / "cache" / "borda-ai-rig" / "codex-rig" / manifest["version"]
    installed_root.mkdir(parents=True)
    for relative in package_payload_paths():
        source = PLUGIN_ROOT / relative
        destination = installed_root / relative
        assert source.is_file(), f"manifested payload is absent: {relative}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(PLUGIN_ROOT / "package-manifest.json", installed_root / "package-manifest.json")
    return installed_root


def test_installed_package_runs_the_explicit_package_safe_selection(tmp_path: Path) -> None:
    """Prevent checkout-only tests from being mistaken for installed-package coverage.

    The selected tests cover the denial protocol/client, all seven network approval
    briefs, the complete PR collector boundary, and calibration scoring. A separate
    source-checkout suite retains the valid sync, CI-harness, and Git metadata contracts.
    """
    installed_root = copied_package_root(tmp_path)
    payload_paths = set(package_payload_paths())
    selected_files = {node_id.split("::", 1)[0] for node_id in PACKAGE_SAFE_TEST_SELECTION}

    assert selected_files <= payload_paths
    assert all((installed_root / path).is_file() for path in selected_files)
    for path in (installed_root / "Makefile", installed_root / ".github", installed_root / ".git"):
        assert not path.exists(), f"installed payload must not include checkout context: {path.name}"
    assert not (tmp_path / ".git").exists()

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *PACKAGE_SAFE_TEST_SELECTION],
        cwd=installed_root,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for path in (installed_root / "Makefile", installed_root / ".github", installed_root / ".git"):
        assert not path.exists(), f"test execution created checkout context: {path.name}"
