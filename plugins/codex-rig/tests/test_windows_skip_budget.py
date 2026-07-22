"""Freeze the explicit native-Windows skip surface."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SKIP = re.compile(r"pytest\.mark\.skipif\(\s*sys\.platform == [\"']win32[\"']", re.MULTILINE)
APPROVED_WINDOWS_SKIPS = {
    "test_agent_shim_observe.py": 1,
    "test_build_package.py": 1,
    "test_generate_roles.py": 1,
    "test_installed_cache_scaffold.py": 1,
    "test_manage_role_agents.py": 1,
    "test_package_identity.py": 1,
    "test_session_start_hook.py": 1,
}


def test_windows_skip_surface_is_explicit_and_frozen() -> None:
    """Reject new blanket Windows skips outside the audited POSIX-only surfaces."""
    observed: dict[str, int] = {}
    for path in sorted((PLUGIN_ROOT / "tests").glob("test_*.py")):
        count = len(WINDOWS_SKIP.findall(path.read_text(encoding="utf-8")))
        if count:
            observed[path.name] = count

    assert observed == APPROVED_WINDOWS_SKIPS


def test_native_windows_acceptance_files_have_no_windows_skip() -> None:
    """Keep portable package, manager, hook, sync, and workflow checks runnable in CI."""
    required = (
        "test_collection_policy.py",
        "test_create_run.py",
        "test_global_agents_installer.py",
        "test_manage_role_agents_windows.py",
        "test_plugin_only_release.py",
        "test_portable_workflow_helpers.py",
        "test_session_start_hook.py",
        "test_sync_codex.py",
    )
    for filename in required:
        text = (PLUGIN_ROOT / "tests" / filename).read_text(encoding="utf-8")
        if filename == "test_session_start_hook.py":
            assert len(WINDOWS_SKIP.findall(text)) == 1
        else:
            assert WINDOWS_SKIP.search(text) is None, filename


def test_package_identity_text_forces_lf_checkout() -> None:
    """Keep exact package hashes stable across Windows Git checkouts."""
    repository = PLUGIN_ROOT.parents[1]
    paths = (
        "plugins/codex-rig/LICENSE",
        "plugins/codex-rig/NOTICE",
        "plugins/codex-rig/runtime/calibration/behavioral-observations.jsonl",
        "plugins/codex-rig/tests/requirements.txt",
    )

    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        f"{path}: {attribute}: {value}" for path in paths for attribute, value in (("text", "set"), ("eol", "lf"))
    ]


def test_ci_runs_full_suite_once_and_explicit_native_windows_entrypoints() -> None:
    """Avoid duplicate Windows tests while retaining native entrypoint acceptance."""
    workflow = (PLUGIN_ROOT.parents[1] / ".github" / "workflows" / "ci-tests.yml").read_text(encoding="utf-8")
    for required in (
        "pytest -W error::DeprecationWarning",
        "if: runner.os == 'Windows'",
        "scripts/build_package.py --check",
        "scripts/validate_package.py",
        "shared/collect_pr.py --help",
        '"sync.sh"',
    ):
        assert required in workflow
    assert workflow.count("pytest ") == 1
