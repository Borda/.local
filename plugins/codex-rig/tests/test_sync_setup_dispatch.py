"""Executable acceptance checks for the sync.sh installed-plugin setup dispatch loop.

This module sits beside ``test_global_agents_installer.py`` instead of extending it: that module owns Codex Rig's
global-instruction installer and only pins sync.sh through static substring assertions, which cannot observe dispatch
order, setup-layout discovery, skip decisions, or failure propagation. Here the real loop is executed.

Extraction approach: sync.sh is sliced between two stable anchors — the ``Initializing installed plugin setup
skills...`` echo and the first unindented ``done`` that closes the for-loop — and that verbatim slice is wrapped in the
same ``set -e`` plus ``if $SYNC_CLAUDE`` context the script gives it. The ``PLUGINS`` and ``EXTERNAL_PLUGINS`` array
assignments are lifted verbatim from sync.sh too, so the managed roster, its order, and the third-party roster all come
from the shipped script rather than from a copy kept here. Only the surroundings the loop reads but does not define
(``MARKETPLACE`` and ``INSTALLED_PLUGINS``) are supplied by the harness, both pointed at throwaway fixtures. Any edit to
the loop's dispatch logic therefore runs in these tests instead of being paraphrased by them.

Isolation: HOME, the plugin registry, every install tree, and the ``claude`` executable are all synthetic and live under
``tmp_path``. The harness never expands ``$HOME``, so the real ``~/.claude`` registry is unreachable from the executed
slice, and the fake ``claude`` shadows any real CLI from the front of PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from _platform import POSIX_BASH


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = PLUGIN_ROOT.parents[1] / "sync.sh"
SETUP_ANCHOR = 'echo "Initializing installed plugin setup skills..."'
INSTALL_ANCHOR = 'echo "Installing plugins..."'
END_SENTINEL = "SETUP-DISPATCH-COMPLETE"
MARKETPLACE = "fake-marketplace"
# Non-empty so the fake CLI's glob cannot degenerate into a match-everything pattern, and absent from any invocation.
NEVER_MATCHED = "::no-failure-requested::"
pytestmark = [
    pytest.mark.skipif(shutil.which("jq") is None, reason="jq is unavailable"),
    pytest.mark.skipif(POSIX_BASH is None, reason="working POSIX Bash is unavailable"),
]

# The fake CLI records argv tab-separated so argument boundaries survive the log, and fails only on an explicit marker.
FAKE_CLAUDE_SOURCE = """#!/usr/bin/env bash
printf '%s\\t' "$@" >> "$FAKE_CLAUDE_LOG"
printf '\\n' >> "$FAKE_CLAUDE_LOG"
case "$*" in
    *"$FAKE_CLAUDE_FAIL_ON"*) exit 7 ;;
esac
exit 0
"""

Record = tuple[str, bool]
"""One registry install record: its ``installedAt`` stamp and whether that install tree ships a setup skill."""

MANAGED_RECORDS: dict[str, tuple[Record, ...]] = {
    # Newest record placed first in array order: only sort_by(.installedAt)|last reaches the tree holding the skill.
    "foundry@fake-marketplace": (("2026-05-01T00:00:00Z", True), ("2024-01-01T00:00:00Z", False)),
    "oss@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
    "develop@fake-marketplace": (("2026-01-01T00:00:00Z", False),),
    # research is absent for the managed marketplace; the foreign-marketplace record is a keying near-miss.
    "research@other-marketplace": (("2026-01-01T00:00:00Z", True),),
    "codemap-py@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
    "bridge@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
    "codex@openai-codex": (("2026-01-01T00:00:00Z", True),),
    "caveman@caveman": (("2026-01-01T00:00:00Z", True),),
    "ponytail@ponytail": (("2026-01-01T00:00:00Z", True),),
    "unrelated@third-party": (("2026-01-01T00:00:00Z", True),),
    # Key a roster regression would probe: EXTERNAL_PLUGINS entries already carry their marketplace, so appending
    # them to the loop composes "<entry>@${MARKETPLACE}". Stocking it makes such a regression dispatch, not skip.
    "codex@openai-codex@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
}

FAILURE_RECORDS: dict[str, tuple[Record, ...]] = {
    "foundry@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
    "oss@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
    "codemap-py@fake-marketplace": (("2026-01-01T00:00:00Z", True),),
}


@dataclass(frozen=True)
class DispatchRun:
    """One executed copy of the sync.sh setup dispatch loop plus everything it was observed to touch."""

    process: subprocess.CompletedProcess[str]
    invocations: tuple[tuple[str, ...], ...]
    transcript: str
    harness: str
    home: Path
    registry: Path
    path_head: str


def read_sync_lines() -> list[str]:
    """Return sync.sh split into lines, so anchors can be matched by exact column-0 content."""
    return SYNC_SCRIPT.read_text(encoding="utf-8").splitlines()


def extract_setup_dispatch(lines: list[str]) -> str:
    """Return the setup-dispatch loop sliced verbatim from sync.sh between its announce echo and closing done."""
    starts = [index for index, line in enumerate(lines) if line.strip() == SETUP_ANCHOR]
    if len(starts) != 1:
        pytest.fail("sync.sh must announce setup dispatch exactly once — the loop was moved or renamed")
    # Exact column-0 match, so a future nested loop's indented `done` cannot truncate the slice.
    ends = [index for index in range(starts[0], len(lines)) if lines[index] == "done"]
    if not ends:
        pytest.fail("sync.sh setup-dispatch loop has no closing `done` at column 0")
    return "\n".join(lines[starts[0] : ends[0] + 1])


def extract_install_dispatch(lines: list[str]) -> str:
    """Return the managed install block through replacement cleanup."""
    starts = [index for index, line in enumerate(lines) if line.strip() == INSTALL_ANCHOR]
    ends = [index for index, line in enumerate(lines) if line.strip() == SETUP_ANCHOR]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        pytest.fail("sync.sh must keep one managed install block before setup dispatch")
    return "\n".join(lines[starts[0] : ends[0]])


def extract_array(lines: list[str], name: str) -> tuple[str, tuple[str, ...]]:
    """Return one sync.sh array assignment verbatim together with its parsed entries."""
    prefix = f"{name}=("
    matches = [line for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        pytest.fail(f"sync.sh must declare exactly one {name} array")
    return matches[0], tuple(matches[0][len(prefix) :].rstrip(")").split())


def build_harness(lines: list[str], registry: Path) -> str:
    """Wrap the extracted loop and sync.sh's own roster arrays in the script's set -e and SYNC_CLAUDE context."""
    plugins_line, _ = extract_array(lines, "PLUGINS")
    external_line, _ = extract_array(lines, "EXTERNAL_PLUGINS")
    return "\n".join(
        (
            "set -e",
            plugins_line,
            external_line,
            f'MARKETPLACE="{MARKETPLACE}"',
            f'INSTALLED_PLUGINS="{registry.as_posix()}"',
            "SYNC_CLAUDE=true",
            "if $SYNC_CLAUDE; then",
            extract_setup_dispatch(lines),
            "fi  # SYNC_CLAUDE",
            f'echo "{END_SENTINEL}"',
            "",
        )
    )


def build_registry(root: Path, records: dict[str, tuple[Record, ...]]) -> Path:
    """Write a fake installed_plugins.json and the install trees its records point at, preserving record order."""
    plugins: dict[str, list[dict[str, str]]] = {}
    for key, entries in records.items():
        rendered: list[dict[str, str]] = []
        for index, (installed_at, ships_setup) in enumerate(entries):
            install_path = root / "installs" / f"{key.replace('@', '-at-')}-{index}"
            install_path.mkdir(parents=True, exist_ok=True)
            if ships_setup:
                setup_root = "claude-skills" if key.startswith("bridge@") else "skills"
                skill = install_path / setup_root / "setup" / "SKILL.md"
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text("# setup\n", encoding="utf-8")
            rendered.append({"installPath": install_path.as_posix(), "installedAt": installed_at})
        plugins[key] = rendered
    registry = root / "installed_plugins.json"
    registry.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
    return registry


def run_setup_dispatch(
    root: Path, posix_bash: str, records: dict[str, tuple[Record, ...]], *, fail_on: str = NEVER_MATCHED
) -> DispatchRun:
    """Execute the extracted dispatch loop against a fake registry, a fake HOME, and a fake claude executable.

    Args:
        root: Throwaway directory owning the registry, install trees, fake HOME, and fake executable.
        posix_bash: POSIX Bash interpreter supplied by the shared fixture.
        records: Registry contents keyed by ``<plugin>@<marketplace>``.
        fail_on: Substring of a claude invocation that makes the fake CLI exit 7; defaults to an unmatchable sentinel.

    Returns:
        The completed process together with the recorded invocations and the isolated paths involved.
    """
    lines = read_sync_lines()
    fake_bin = root / "bin"
    fake_bin.mkdir()
    fake_claude = fake_bin / "claude"
    fake_claude.write_text(FAKE_CLAUDE_SOURCE, encoding="utf-8")
    fake_claude.chmod(0o755)
    log = root / "claude-calls.log"
    home = root / "home"
    home.mkdir()
    registry = build_registry(root, records)
    harness = build_harness(lines, registry)
    harness_path = root / "setup-dispatch.sh"
    harness_path.write_text(harness, encoding="utf-8")

    env = os.environ.copy()
    path = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env.update(
        {
            "FAKE_CLAUDE_FAIL_ON": fail_on,
            "FAKE_CLAUDE_LOG": log.as_posix(),
            "HOME": str(home),
            "PATH": path,
        }
    )
    process = subprocess.run(
        [posix_bash, str(harness_path)],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    transcript = log.read_text(encoding="utf-8") if log.exists() else ""
    invocations = tuple(tuple(line.split("\t")[:-1]) for line in transcript.splitlines())
    return DispatchRun(
        process=process,
        invocations=invocations,
        transcript=transcript,
        harness=harness,
        home=home,
        registry=registry,
        path_head=str(fake_bin),
    )


def run_install_dispatch(root: Path, posix_bash: str, *, fail_on: str = NEVER_MATCHED) -> DispatchRun:
    """Execute the managed install and replacement-cleanup block with a fake Claude CLI."""
    lines = read_sync_lines()
    fake_bin = root / "bin"
    fake_bin.mkdir()
    fake_claude = fake_bin / "claude"
    fake_claude.write_text(FAKE_CLAUDE_SOURCE, encoding="utf-8")
    fake_claude.chmod(0o755)
    log = root / "claude-calls.log"
    home = root / "home"
    home.mkdir()
    registry = build_registry(root, MANAGED_RECORDS)
    plugins_line, _ = extract_array(lines, "PLUGINS")
    harness = "\n".join(
        (
            "set -e",
            plugins_line,
            f'MARKETPLACE="{MARKETPLACE}"',
            "print_claude_plugin_identity() { :; }",
            extract_install_dispatch(lines),
            "",
        )
    )
    harness_path = root / "install-dispatch.sh"
    harness_path.write_text(harness, encoding="utf-8")
    env = os.environ.copy()
    path = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env.update(
        {
            "FAKE_CLAUDE_FAIL_ON": fail_on,
            "FAKE_CLAUDE_LOG": log.as_posix(),
            "HOME": str(home),
            "PATH": path,
        }
    )
    process = subprocess.run(
        [posix_bash, str(harness_path)],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )
    transcript = log.read_text(encoding="utf-8") if log.exists() else ""
    invocations = tuple(tuple(line.split("\t")[:-1]) for line in transcript.splitlines())
    return DispatchRun(process, invocations, transcript, harness, home, registry, str(fake_bin))


def test_managed_plugin_roster_leads_with_foundry() -> None:
    """Pin the dispatch order contract to sync.sh's own PLUGINS array rather than to fixture expectations."""
    _, plugins = extract_array(read_sync_lines(), "PLUGINS")

    assert plugins[0] == "foundry"
    assert len(plugins) == len(set(plugins))


def test_external_plugin_roster_retains_only_caveman() -> None:
    """Keep the retired external Codex rescue plugin out of repository sync."""
    _, external_plugins = extract_array(read_sync_lines(), "EXTERNAL_PLUGINS")

    assert external_plugins == ("caveman@caveman",)


def test_successful_bridge_install_retires_replaced_plugin(tmp_path: Path, posix_bash: str) -> None:
    """Remove the replaced plugin only after the bridge installation succeeds."""
    run = run_install_dispatch(tmp_path, posix_bash)
    bridge_install = ("plugin", "install", "bridge@fake-marketplace")
    retired_uninstall = ("plugin", "uninstall", "codex@openai-codex")

    assert run.process.returncode == 0, run.process.stderr
    assert bridge_install in run.invocations
    assert retired_uninstall in run.invocations
    assert run.invocations.index(bridge_install) < run.invocations.index(retired_uninstall)


def test_failed_bridge_install_preserves_replaced_plugin(tmp_path: Path, posix_bash: str) -> None:
    """Keep the working legacy install when its replacement could not be installed."""
    run = run_install_dispatch(tmp_path, posix_bash, fail_on="bridge@fake-marketplace")

    assert run.process.returncode == 0, run.process.stderr
    assert ("plugin", "install", "bridge@fake-marketplace") in run.invocations
    assert ("plugin", "uninstall", "codex@openai-codex") not in run.invocations


def test_unconditional_purge_entries_run_even_when_the_bridge_install_fails(tmp_path: Path, posix_bash: str) -> None:
    """Purge plugins with no replacement relationship regardless of the bridge outcome.

    Only ``codex@openai-codex`` is conditional, because the bridge is what replaces it.
    Every other retired entry is simply no longer part of the rig, so gating it on an
    unrelated install would leave it installed forever on any machine that hit a network
    blip during that one install.
    """
    run = run_install_dispatch(tmp_path, posix_bash, fail_on="bridge@fake-marketplace")

    assert run.process.returncode == 0, run.process.stderr
    assert ("plugin", "uninstall", "ponytail@ponytail") in run.invocations
    assert ("plugin", "uninstall", "codex@openai-codex") not in run.invocations


def test_a_failed_purge_uninstall_does_not_fail_the_sync(tmp_path: Path, posix_bash: str) -> None:
    """An uninstall that errors must not abort a run whose installs all succeeded.

    The ordinary cause is the plugin already being absent, and nothing downstream depends
    on it having been there. Under ``set -e`` an unguarded uninstall would end the script
    before setup dispatch ever ran.
    """
    run = run_install_dispatch(tmp_path, posix_bash, fail_on="ponytail@ponytail")

    assert run.process.returncode == 0, run.process.stderr
    assert ("plugin", "uninstall", "ponytail@ponytail") in run.invocations
    assert ("plugin", "uninstall", "codex@openai-codex") in run.invocations


def test_setup_dispatch_runs_once_per_installed_managed_plugin_in_roster_order(tmp_path: Path, posix_bash: str) -> None:
    """Prove each installed managed plugin shipping a setup skill is invoked exactly once, in PLUGINS order."""
    run = run_setup_dispatch(tmp_path, posix_bash, MANAGED_RECORDS)

    assert run.process.returncode == 0, run.process.stderr
    assert run.invocations == (
        ("--print", "/foundry:setup --approve"),
        ("--print", "/oss:setup --approve"),
        ("--print", "/codemap-py:setup --approve"),
        ("--print", "/bridge:setup --approve"),
    )
    # The dash in sync.sh's skip lines is U+2013, so match dash-free substrings only.
    assert "develop has no setup skill, skipping" in run.process.stdout
    assert "research not installed, skipping setup" in run.process.stdout
    assert END_SENTINEL in run.process.stdout


def test_setup_dispatch_never_reaches_external_or_foreign_marketplace_plugins(tmp_path: Path, posix_bash: str) -> None:
    """Prove third-party plugins and foreign-marketplace records are never dispatched, even when setup-capable."""
    run = run_setup_dispatch(tmp_path, posix_bash, MANAGED_RECORDS)

    assert "EXTERNAL_PLUGINS=(" in run.harness
    assert run.process.returncode == 0, run.process.stderr
    assert "/codex:setup" not in run.transcript
    assert "caveman" not in run.transcript
    assert "ponytail" not in run.transcript
    assert "unrelated" not in run.transcript
    assert "research" not in run.transcript
    # Third-party names must not even reach a skip line; "research" is exempt because it owns a managed skip line.
    assert "codex@openai-codex" not in run.process.stdout
    assert "caveman" not in run.process.stdout
    assert "ponytail" not in run.process.stdout
    assert "unrelated" not in run.process.stdout


def test_setup_dispatch_stops_at_the_first_failing_setup(tmp_path: Path, posix_bash: str) -> None:
    """Prove a mid-roster setup failure is fatal: earlier plugins ran, later plugins never do."""
    run = run_setup_dispatch(tmp_path, posix_bash, FAILURE_RECORDS, fail_on="/oss:setup")

    assert run.process.returncode == 7
    assert run.invocations == (
        ("--print", "/foundry:setup --approve"),
        ("--print", "/oss:setup --approve"),
    )
    assert "codemap-py" not in run.transcript
    assert END_SENTINEL not in run.process.stdout


def test_setup_dispatch_stays_inside_the_isolated_home_and_registry(tmp_path: Path, posix_bash: str) -> None:
    """Prove the executed slice can reach neither the real plugin registry nor the real home directory."""
    run = run_setup_dispatch(tmp_path, posix_bash, MANAGED_RECORDS)

    assert run.invocations, "the fake claude never ran, so isolation was not exercised"
    assert run.path_head == str(tmp_path / "bin")
    assert "$HOME" not in run.harness
    assert run.registry.as_posix() in run.harness
    assert run.home.parent == tmp_path
    assert list(run.home.iterdir()) == []
    assert run.home != Path.home()
