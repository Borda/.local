"""Behavioral tests for the provider-neutral benchmark batch entrypoint."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BENCHMARKS_DIR / "run-all.sh"
LEGACY_SCRIPT = BENCHMARKS_DIR / "run-all-claude.sh"
ACTIVE_MANIFEST = BENCHMARKS_DIR / "manifests" / "codex-integration.json"
ACTIVE_MANIFEST_SHA = hashlib.sha256(ACTIVE_MANIFEST.read_bytes()).hexdigest()
LOCKED_INDEX_SHA = "b0e4a5c9ae7da6503cf1e831d39c73abac6eb696be849fc0080f61bce6c1f045"
CONFIRMATORY_TASK_IDS = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))["preregistered_cells"][
    "structural_execution_task_ids"
]


def _write_executable(path: Path, body: str) -> None:
    """Create one executable command stub for shell orchestration tests."""
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def batch_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Return an isolated target and command-log environment with no model access."""
    repo = tmp_path / "target"
    (repo / ".git").mkdir(parents=True)
    index_path = repo / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("locked-index", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"
    auth_source = tmp_path / "auth.json"
    auth_source.write_text("fixture", encoding="utf-8")
    auth_source.chmod(0o600)

    _write_executable(
        bin_dir / "git",
        'printf "fixture-head\\n"',
    )
    _write_executable(
        bin_dir / "python3",
        f"""if [ "$1" = "-c" ]; then exec {sys.executable} "$@"; fi
printf "python %s\\n" "$*" >> "$CALL_LOG"
if [ -n "${{FAIL_WHEN_ARGS_CONTAIN:-}}" ] && [[ "$*" == *"$FAIL_WHEN_ARGS_CONTAIN"* ]]; then
  exit 41
fi""",
    )
    _write_executable(bin_dir / "codex", 'printf "codex-cli 0.146.0\\n"')
    _write_executable(
        bin_dir / "shasum",
        f"""if [ "$(sed -n '1p' "$3")" = "locked-index" ]; then
  printf "{LOCKED_INDEX_SHA}  %s\\n" "$3"
elif [ "$3" = "{ACTIVE_MANIFEST}" ]; then
  printf "{ACTIVE_MANIFEST_SHA}  %s\\n" "$3"
else
  printf "%064d  %s\\n" 0 "$3"
fi""",
    )

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CALL_LOG": str(call_log),
        "CODEX_AUTH_SOURCE": str(auth_source),
        "CODEX_RUN_DIR": str(tmp_path / "codex-run"),
        "CODEX_PAID_APPROVAL": ACTIVE_MANIFEST_SHA,
        "CODEX_MAX_WALL_CLOCK_SECONDS": "86400",
        "CODEMAP_BIN": str(bin_dir / "codemap-py"),
        "REPO": str(repo),
    }
    _write_executable(
        bin_dir / "codemap-py",
        'root="${!#}"; mkdir -p "$root/.cache/codemap"; printf "locked-index" > "$root/.cache/codemap/$(basename "$root").json"',
    )
    return env, call_log


def _run_batch(mode: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one batch mode against command stubs and capture its public output."""
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), mode],
        cwd=BENCHMARKS_DIR.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_only_provider_neutral_batch_entrypoint_exists() -> None:
    """Prevent provider-specific run-all scripts from fragmenting orchestration."""
    assert SCRIPT.is_file()
    assert not LEGACY_SCRIPT.exists()
    script = SCRIPT.read_text(encoding="utf-8")
    assert "\ncodex() {" not in script
    assert "command codex --version" in script


def test_batch_entrypoint_accepts_exactly_three_modes(batch_env: tuple[dict[str, str], Path]) -> None:
    """Reject missing, obsolete, or extra modes before any setup command runs."""
    env, call_log = batch_env

    missing = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=BENCHMARKS_DIR.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert missing.returncode == 2
    assert "smoke | claude | codex" in missing.stderr
    for obsolete in ("all", "full", "refresh", "unknown"):
        rejected = _run_batch(obsolete, env)
        assert rejected.returncode == 2
        assert "smoke | claude | codex" in rejected.stderr
    assert not call_log.exists()


def test_smoke_checks_claude_and_codex_without_paid_codex(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Smoke must cover both providers while keeping the Codex probe no-model."""
    env, call_log = batch_env

    completed = _run_batch("smoke", env)

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "run-claude-structural.py" in calls
    assert "run-claude-agentic.py" in calls
    claude_calls = [line for line in calls.splitlines() if "run-claude-" in line]
    assert claude_calls
    assert all("--dry-run" in line for line in claude_calls)
    codex_call = next(line for line in calls.splitlines() if "run-codex-structural.py" in line)
    assert "--dry-run" in codex_call
    assert "--output-path" not in codex_call
    assert "--auth-source" not in codex_call
    assert f"--manifest-path {ACTIVE_MANIFEST}" in codex_call
    assert f"--codemap-bin {env['CODEMAP_BIN']}" in codex_call


@pytest.mark.parametrize(
    ("mode", "failure_pattern", "full_marker"),
    [
        ("smoke", "run-claude-structural.py", "run-codex-structural.py"),
        ("claude", "run-claude-structural.py", "--run-all"),
        ("codex", "--task-id FN-02 --arm all --dry-run", "--repetitions 1"),
    ],
    ids=["both-providers", "claude", "codex"],
)
def test_provider_smoke_failure_prevents_full_dispatch(
    batch_env: tuple[dict[str, str], Path],
    mode: str,
    failure_pattern: str,
    full_marker: str,
) -> None:
    """A failed provider smoke must stop before that mode's full workload."""
    env, call_log = batch_env
    env["FAIL_WHEN_ARGS_CONTAIN"] = failure_pattern

    completed = _run_batch(mode, env)

    assert completed.returncode == 41
    calls = call_log.read_text(encoding="utf-8")
    assert failure_pattern in calls
    assert full_marker not in calls


def test_smoke_rejects_mismatched_locked_index_before_provider_commands(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Prevent any provider preflight after the frozen parity index bytes drift."""
    env, call_log = batch_env
    index_path = Path(env["REPO"]) / ".cache" / "codemap" / "target.json"
    index_path.write_text("stale-index", encoding="utf-8")

    completed = _run_batch("smoke", env)

    assert completed.returncode == 1
    assert "locked parity index SHA-256 mismatch" in completed.stderr
    assert not call_log.exists()


def test_smoke_accepts_git_worktree_metadata_file(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Accept linked Git worktrees whose .git metadata is a file, not a directory."""
    env, call_log = batch_env
    git_metadata = Path(env["REPO"]) / ".git"
    git_metadata.rmdir()
    git_metadata.write_text("gitdir: /fixture/worktrees/target", encoding="utf-8")

    completed = _run_batch("smoke", env)

    assert completed.returncode == 0, completed.stderr
    assert "run-codex-structural.py" in call_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("invalid_input", "expected_error"),
    [
        ("approval", "CODEX_PAID_APPROVAL"),
        ("auth", "CODEX_AUTH_SOURCE"),
        ("run-dir", "CODEX_RUN_DIR"),
        ("wall-clock", "CODEX_MAX_WALL_CLOCK_SECONDS"),
        ("existing-run-dir", "already exists"),
    ],
    ids=["missing-approval", "missing-auth", "missing-run-dir", "missing-wall-clock", "existing-run-dir"],
)
def test_codex_mode_requires_explicit_paid_inputs_before_setup(
    batch_env: tuple[dict[str, str], Path],
    invalid_input: str,
    expected_error: str,
) -> None:
    """Reject incomplete paid authorization before refreshing or invoking tools."""
    env, call_log = batch_env
    if invalid_input == "existing-run-dir":
        Path(env["CODEX_RUN_DIR"]).mkdir()
    else:
        env.pop(
            {
                "approval": "CODEX_PAID_APPROVAL",
                "auth": "CODEX_AUTH_SOURCE",
                "run-dir": "CODEX_RUN_DIR",
                "wall-clock": "CODEX_MAX_WALL_CLOCK_SECONDS",
            }[invalid_input]
        )

    completed = _run_batch("codex", env)

    assert completed.returncode == 2
    assert expected_error in completed.stderr
    assert not call_log.exists()


def test_provider_modes_dispatch_only_the_selected_provider(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Claude and Codex modes must not invoke the other provider's runner."""
    env, call_log = batch_env

    claude = _run_batch("claude", env)
    assert claude.returncode == 0, claude.stderr
    claude_calls = call_log.read_text(encoding="utf-8")
    assert "run-claude-structural.py" in claude_calls
    assert "run-claude-agentic.py" in claude_calls
    assert "run-codex-structural.py" not in claude_calls

    call_log.unlink()
    codex = _run_batch("codex", env)
    assert codex.returncode == 0, codex.stderr
    codex_calls = call_log.read_text(encoding="utf-8")
    assert "run-codex-structural.py" in codex_calls
    paid_call = next(
        line for line in codex_calls.splitlines() if "run-codex-structural.py" in line and "--dry-run" not in line
    )
    assert paid_call.count("--task-id") == len(CONFIRMATORY_TASK_IDS)
    assert all(f"--task-id {task_id}" in paid_call for task_id in CONFIRMATORY_TASK_IDS)
    assert "--repetitions 1" in paid_call
    assert "--reasoning-effort high" in paid_call
    assert "--arm all" in codex_calls
    assert f"--manifest-path {ACTIVE_MANIFEST}" in codex_calls
    assert f"--codemap-bin {env['CODEMAP_BIN']}" in codex_calls
    assert "--max-wall-clock-seconds 86400" in codex_calls
    assert "run-claude-" not in codex_calls
    codex_lines = [line for line in codex_calls.splitlines() if "run-codex-structural.py" in line]
    assert len(codex_lines) == 3
    smoke_call = next(line for line in codex_lines if "--task-id FN-02 --arm all --dry-run" in line)
    full_dry_run = next(line for line in codex_lines if "--dry-run" in line and "--task-id FN-02 --arm all" not in line)
    assert "--repetitions 1" not in smoke_call
    assert full_dry_run.count("--task-id") == len(CONFIRMATORY_TASK_IDS)
    assert "--repetitions 1" in full_dry_run
    assert any(
        "--dry-run" not in line and "--output-path" in line and "--metadata-path" in line for line in codex_lines
    )
    run_dir = Path(env["CODEX_RUN_DIR"])
    assert run_dir.is_dir()
    assert (run_dir / "run.log").is_file()
    checksums = (run_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "run.log" in checksums


def test_codex_mode_reconstructs_a_missing_locked_index_before_dispatch(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A fresh target must build and byte-check the frozen index before any model command."""
    env, call_log = batch_env
    index_path = Path(env["REPO"]) / ".cache" / "codemap" / "target.json"
    index_path.unlink()

    completed = _run_batch("codex", env)

    assert completed.returncode == 0, completed.stderr
    assert index_path.read_text(encoding="utf-8") == "locked-index"
    assert "run-codex-structural.py" in call_log.read_text(encoding="utf-8")
