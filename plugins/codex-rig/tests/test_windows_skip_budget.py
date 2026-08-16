"""Freeze the explicit native-Windows skip surface.

Every ``skipif`` under ``tests/`` falls in exactly one of two frozen buckets, so converting a
skip from one shape to the other can never make it disappear from the budget:

* :data:`APPROVED_WINDOWS_SKIPS` — blanket ``sys.platform == "win32"`` markers, stating that a
  whole surface is unavailable on Windows. Legitimate only where the platform genuinely cannot
  represent what the test needs; the count should trend toward zero.
* :data:`APPROVED_CAPABILITY_SKIPS` — probe-gated markers that ask the *host* whether an
  operation works and skip only when it does not. The preferred shape, but frozen too: an
  always-false probe is a blanket skip wearing a disguise, and would otherwise slip past a
  roster that counted only the literal platform test.

The scan stays confined to ``PLUGIN_ROOT / "tests"``. Skip markers elsewhere in the repository
belong to their own plugins and are not this budget's concern.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ANY_SKIPIF = re.compile(r"pytest\.mark\.skipif\(", re.MULTILINE)
WINDOWS_SKIP = re.compile(r"pytest\.mark\.skipif\(\s*sys\.platform == [\"']win32[\"']", re.MULTILINE)
# Each surviving entry was re-audited against what its tests actually need, not against the
# platform label. All six turn on POSIX file modes (exact `0o755`/`0o644` bytes bound into
# package manifests and role-card hashes) or on executable-bit semantics, none of which
# Windows can represent — so the skip states a real capability gap rather than hiding one.
APPROVED_WINDOWS_SKIPS = {
    "test_agent_shim_observe.py": 1,
    "test_build_package.py": 1,
    "test_generate_roles.py": 1,
    "test_installed_cache_scaffold.py": 1,
    "test_manage_role_agents.py": 1,
    "test_session_start_hook.py": 1,
}
# `test_package_identity.py` moved out of the map above: its blanket marker guarded a symlink
# fixture, and symlink creation is a per-host capability the CI runner has, so it now probes.
APPROVED_CAPABILITY_SKIPS = {
    "test_agent_shim_observe.py": 4,
    "test_agent_shim_posix.py": 1,
    "test_app_server_denial_protocol.py": 1,
    "test_codemap_adapter.py": 1,
    "test_global_agents_installer.py": 2,
    "test_installed_cache_scaffold.py": 1,
    "test_package_identity.py": 1,
    "test_plugin_only_release.py": 3,
    "test_sync_setup_dispatch.py": 2,
}


def _skip_counts(pattern: re.Pattern[str]) -> dict[str, int]:
    """Return per-file match counts for *pattern* across this plugin's own test files."""
    counts: dict[str, int] = {}
    for path in sorted((PLUGIN_ROOT / "tests").glob("test_*.py")):
        count = len(pattern.findall(path.read_text(encoding="utf-8")))
        if count:
            counts[path.name] = count
    return counts


def test_windows_skip_surface_is_explicit_and_frozen() -> None:
    """Reject new blanket Windows skips outside the audited POSIX-only surfaces."""
    assert _skip_counts(WINDOWS_SKIP) == APPROVED_WINDOWS_SKIPS


def test_capability_probe_skips_are_explicit_and_frozen() -> None:
    """Freeze probe-gated skips too, so the preferred shape cannot become an untracked one."""
    non_platform = {
        name: count - APPROVED_WINDOWS_SKIPS.get(name, 0) for name, count in _skip_counts(ANY_SKIPIF).items()
    }

    assert {name: count for name, count in non_platform.items() if count} == APPROVED_CAPABILITY_SKIPS


def test_every_skip_marker_lands_in_exactly_one_budget() -> None:
    """No skip may escape both buckets — that gap is what let a converted marker vanish."""
    total = sum(_skip_counts(ANY_SKIPIF).values())

    assert total == sum(APPROVED_WINDOWS_SKIPS.values()) + sum(APPROVED_CAPABILITY_SKIPS.values())


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
    # Count invocations, not the word: a YAML comment mentioning pytest is not a suite run.
    invocations = [line for line in workflow.splitlines() if "pytest" in line and not line.lstrip().startswith("#")]
    assert len(invocations) == 1, invocations
