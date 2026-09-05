"""Behavioral tests for the provider-neutral benchmark batch entrypoint."""

from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


# Every test here drives ``run-all.sh`` through ``/bin/bash`` with executable
# shell stubs, so the whole module is POSIX-only — same boundary the shared
# benchmark fixtures draw in conftest.py.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="benchmark harness exercises the POSIX launcher only",
)


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BENCHMARKS_DIR / "run-all.sh"
REAL_GIT = shutil.which("git")
ACTIVE_MANIFEST = BENCHMARKS_DIR / "manifests" / "codex-integration.json"
ACTIVE_MANIFEST_SHA = hashlib.sha256(ACTIVE_MANIFEST.read_bytes()).hexdigest()
AGENTIC_MANIFEST = BENCHMARKS_DIR / "manifests" / "codex-agentic.json"
AGENTIC_MANIFEST_SHA = hashlib.sha256(AGENTIC_MANIFEST.read_bytes()).hexdigest()
AGENTIC_MANIFEST_DATA = json.loads(AGENTIC_MANIFEST.read_text(encoding="utf-8"))
AGENTIC_TOTAL_CELLS = AGENTIC_MANIFEST_DATA["preregistered_scope"]["total_cells"]
AGENTIC_CELL_TIMEOUT = AGENTIC_MANIFEST_DATA["preregistered_scope"]["coordinate_timeout_seconds"]
AGENTIC_SCOPE_SHA = "agentic-default-scope"
AGENTIC_REPEAT_TWO_SCOPE_SHA = "agentic-repeat-two-scope"
AGENTIC_SELECTED_SCOPE_SHA = "agentic-selected-scope"
AGENTIC_SELECTED_TASK_IDS = ("BA-02", "BA-04")
AGENTIC_SELECTED_TOTAL_CELLS = len(AGENTIC_SELECTED_TASK_IDS) * 3
METHODOLOGY_MANIFEST = BENCHMARKS_DIR / "manifests" / "provider-parity-methodology.json"
METHODOLOGY_MANIFEST_DATA = json.loads(METHODOLOGY_MANIFEST.read_text(encoding="utf-8"))
SHARED_STRUCTURAL_TASK_IDS = METHODOLOGY_MANIFEST_DATA["preregistered_cells"]["structural_execution_task_ids"]
CLAUDE_AGENTIC_TOTAL_CELLS = METHODOLOGY_MANIFEST_DATA["agentic_execution_contract"]["default_total_cells_by_provider"][
    "claude"
]
CLAUDE_AGENTIC_SCOPE_SHA = "claude-agentic-default-scope"
CLAUDE_AGENTIC_REPEAT_TWO_SCOPE_SHA = "claude-agentic-repeat-two-scope"
ACTIVE_MANIFEST_DATA = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))
LOCKED_INDEX_SHA = ACTIVE_MANIFEST_DATA["index"]["raw_sha256"]
LOCKED_INDEX_SCAN_VERSION = ACTIVE_MANIFEST_DATA["index"]["scan_version"]
CONFIRMATORY_TASK_IDS = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))["preregistered_cells"][
    "structural_execution_task_ids"
]
DEFAULT_SCOPE_SHA = "d" * 64
SELECTED_SCOPE_SHA = "e" * 64
SELECTED_TASK_IDS = ("DI-01", "GR-01")


def _assert_safe_paid_preflight(calls: list[str], *, agentic: bool) -> None:
    """Assert manifest generation occurs before paid-input admission.

    Every launch rebuilds the five generated manifest records from source before
    paid-input admission. Agentic admission then resolves its immutable scope.
    Neither route may prepare the repository, access auth, or start a model
    runner.

    >>> calls = [
    ...     "build-provider-parity-methodology-manifest.py",
    ...     "build-codex-integration-manifest.py",
    ...     "build-codex-agentic-manifest.py",
    ... ]
    >>> _assert_safe_paid_preflight(calls, agentic=False)
    >>> with pytest.raises(AssertionError):
    ...     _assert_safe_paid_preflight(calls + ["prepare-codex-index.py"], agentic=False)
    """
    expected_checkers = [
        "build-provider-parity-methodology-manifest.py",
        "build-codex-integration-manifest.py",
        "build-codex-agentic-manifest.py",
    ]

    assert len(calls) == len(expected_checkers) + int(agentic)
    for call, checker in zip(calls[: len(expected_checkers)], expected_checkers, strict=True):
        assert checker in call
        assert not call.endswith(" --check")
    if agentic:
        assert "run-codex-agentic.py" in calls[-1]
        assert "--resolve-scope" in calls[-1]
    assert all("--auth-source" not in call for call in calls)
    assert all("prepare-codex-index.py" not in call for call in calls)
    assert all("run-codex-structural.py" not in call for call in calls)
    assert all("run-codex-agentic.py" not in call or "--resolve-scope" in call for call in calls)


def _claude_task_values(call: str) -> list[str]:
    """Decode the task-list argument between the recorded tasks and model options.

    >>> _claude_task_values('runner --tasks ["one", "two"] --model fixture')
    ['one', 'two']
    """
    start = call.index("--tasks ") + len("--tasks ")
    end = call.index(" --model ", start)
    return json.loads(call[start:end])


def _option_value(call: str, option: str) -> str:
    """Return the token following an option in a recorded whitespace-delimited call.

    This fixture parser does not interpret shell quoting or multi-token values.

    >>> _option_value("runner --repeat 2 --model fixture", "--repeat")
    '2'
    """
    tokens = call.split()
    return tokens[tokens.index(option) + 1]


def _write_executable(path: Path, body: str) -> None:
    """Write a Bash stub with a shebang and trailing newline, then mark it executable.

    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     path = Path(directory) / "example"
    ...     _write_executable(path, "exit 0")
    ...     path.read_text(encoding="utf-8").splitlines()
    ['#!/usr/bin/env bash', 'exit 0']
    """
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture(name="batch_env")
def _batch_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Write an isolated target and command stubs, returning an environment that routes execution to them.

    No commands run while this fixture is constructed.
    """
    repo = tmp_path / "target"
    (repo / ".git").mkdir(parents=True)
    index_path = repo / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps({"scan_version": LOCKED_INDEX_SCAN_VERSION, "modules": []}), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"
    auth_source = tmp_path / "auth.json"
    auth_source.write_text("fixture", encoding="utf-8")
    auth_source.chmod(0o600)

    _write_executable(
        bin_dir / "git",
        f'''if [ -n "${{FAIL_ON_GIT_FETCH:-}}" ] && [[ "$*" == *" fetch "* ]]; then exit 42; fi
if [[ "$*" == *"ls-files --stage -- ."* ]]; then exec "{REAL_GIT}" "$@"; fi
printf "fixture-head\\n"''',
    )
    _write_executable(
        bin_dir / "python3",
        f"""if [ "$1" = "-c" ]; then exec {sys.executable} "$@"; fi
printf "python %s\\n" "$*" >> "$CALL_LOG"
if [[ "$*" == *"--resolve-tasks"* ]]; then
  if [[ "$*" == *"INVALID"* ]]; then
    printf "invalid task selector\\n" >&2
    exit 2
  fi
  if [[ "$*" == *"PT-01"* ]]; then
    printf '{{"task_ids":["PT-01"],"total_cells":3,"scope_sha256":"{SELECTED_SCOPE_SHA}"}}\\n'
    exit 0
  fi
  printf '{{"task_ids":["DI-01","GR-01"],"total_cells":6,"scope_sha256":"{SELECTED_SCOPE_SHA}"}}\\n'
  exit 0
fi
if [[ "$*" == *"run-codex-agentic.py"* && "$*" == *"--resolve-scope"* ]]; then
  if [[ "$*" == *"--task-id BA-02,BA-04"* ]]; then
    printf '{{"task_ids":["BA-02","BA-04"],"repetitions":1,"total_cells":{AGENTIC_SELECTED_TOTAL_CELLS},"arms":["A_plain","B_auto","C_strict"],"models":["gpt-5.6-luna"],"coordinate_timeout_seconds":600,"scope_sha256":"{AGENTIC_SELECTED_SCOPE_SHA}"}}\n'
  elif [[ "$*" == *"--repetitions 2"* ]]; then
    printf '{{"task_ids":["BA-01","BA-02","BA-03","BA-04","BA-05","BA-06","BA-07","BA-08","BA-09","BA-10","BA-11","BA-12","BA-13","BA-14","BA-15","BA-16"],"repetitions":2,"total_cells":96,"arms":["A_plain","B_auto","C_strict"],"models":["gpt-5.6-luna"],"coordinate_timeout_seconds":600,"scope_sha256":"{AGENTIC_REPEAT_TWO_SCOPE_SHA}"}}\n'
  else
    printf '{{"task_ids":["BA-01","BA-02","BA-03","BA-04","BA-05","BA-06","BA-07","BA-08","BA-09","BA-10","BA-11","BA-12","BA-13","BA-14","BA-15","BA-16"],"repetitions":1,"total_cells":{AGENTIC_TOTAL_CELLS},"arms":["A_plain","B_auto","C_strict"],"models":["gpt-5.6-luna"],"coordinate_timeout_seconds":600,"scope_sha256":"{AGENTIC_SCOPE_SHA}"}}\n'
  fi
  exit 0
fi
if [[ "$*" == *"run-claude-agentic.py"* && "$*" == *"--resolve-scope"* ]]; then
  if [[ "$*" == *"--repeat 2"* ]]; then
    printf '{{"task_ids":["BA-01","BA-02","BA-03","BA-04","BA-05","BA-06","BA-07","BA-08","BA-09","BA-10","BA-11","BA-12","BA-13","BA-14","BA-15","BA-16"],"repetitions":2,"total_cells":{CLAUDE_AGENTIC_TOTAL_CELLS * 2},"arms":["A_plain","B_auto","C_strict"],"models":["haiku","sonnet","opus"],"coordinate_timeout_seconds":600,"scope_sha256":"{CLAUDE_AGENTIC_REPEAT_TWO_SCOPE_SHA}"}}\n'
  else
    printf '{{"task_ids":["BA-01","BA-02","BA-03","BA-04","BA-05","BA-06","BA-07","BA-08","BA-09","BA-10","BA-11","BA-12","BA-13","BA-14","BA-15","BA-16"],"repetitions":1,"total_cells":{CLAUDE_AGENTIC_TOTAL_CELLS},"arms":["A_plain","B_auto","C_strict"],"models":["haiku","sonnet","opus"],"coordinate_timeout_seconds":600,"scope_sha256":"{CLAUDE_AGENTIC_SCOPE_SHA}"}}\n'
  fi
  exit 0
fi
if [[ "$*" == *"prepare-codex-index.py"* && "$*" == *"--print-contract"* ]]; then
  printf '{{"raw_sha256":"{LOCKED_INDEX_SHA}","scan_version":{LOCKED_INDEX_SCAN_VERSION}}}\\n'
  exit 0
fi
if [[ "$*" == *"prepare-codex-index.py"* && "$*" == *"--verify"* ]]; then
  if grep -q '"scan_version": {LOCKED_INDEX_SCAN_VERSION}' "$3" && grep -q '"modules": \\[\\]' "$3"; then
    printf "verified: %s\\n" "$3"
    exit 0
  fi
  exit 43
fi
if [[ "$*" == *"build-codex-integration-manifest.py"* ]]; then
  if [ -n "${{FAIL_MANIFEST_CHECK:-}}" ]; then
    printf "generated Codex manifest build failed\\n" >&2
    exit 47
  fi
fi
if [[ "$*" == *"build-provider-parity-methodology-manifest.py"* ]]; then
  if [ -n "${{FAIL_METHODOLOGY_CHECK:-}}" ]; then
    printf "generated methodology manifest build failed\n" >&2
    exit 46
  fi
fi
if [[ "$*" == *"build-codex-agentic-manifest.py"* ]]; then
  if [ -n "${{FAIL_AGENTIC_MANIFEST_CHECK:-}}" ]; then
    printf "stale generated Codex agentic manifest\\n" >&2
    exit 48
  fi
fi
if [ -n "${{FAIL_WHEN_ARGS_CONTAIN:-}}" ] && [[ "$*" == *"$FAIL_WHEN_ARGS_CONTAIN"* ]]; then
  exit 41
fi
if [[ "$*" == *"--render-results"* ]]; then
  if [ -n "${{FAIL_RENDER_RESULTS:-}}" ]; then
    exit 43
  fi
  exec {sys.executable} "$@"
fi
if [[ "$*" == *"run-codex-structural.py"* && "$*" != *"--no-legend"* ]]; then
  printf "LEGEND\n  treatments: A_plain=no Codemap, B_direct=direct Codemap required, C_skill=Codemap Skill required\nEND LEGEND\n"
fi
if [[ "$*" == *"run-codex-structural.py"* && "$*" == *"--dry-run"* ]]; then
  printf "PLAN    FN-02  rep=1  A_plain\\n"
  if [[ "$*" == *"--tasks DI,GR"* ]]; then
    printf "SCOPE   {SELECTED_SCOPE_SHA}\\n"
  elif [[ "$*" == *"--tasks PT-01"* ]]; then
    printf "SCOPE   {SELECTED_SCOPE_SHA}\\n"
  elif [[ "$*" != *"--tasks FN-02"* ]]; then
    printf "SCOPE   {DEFAULT_SCOPE_SHA}\\n"
  fi
fi
if [[ "$*" == *"run-codex-agentic.py"* && "$*" == *"--dry-run"* ]]; then
  printf "PROBE   A_plain    codemap=false skill-required=false\\n"
  printf "PLAN    BA-01  rep=1  A_plain\\n"
fi
if [[ "$*" == *"run-codex-agentic.py"* && "$*" == *"--auth-source"* ]]; then
  if [ -n "${{ASSERT_AGENTIC_ADMISSION_FRESH:-}}" ] && [ -e "$CODEX_RUN_DIR/.agentic-console.log" ]; then
    printf "agentic console artifact existed before paid Python admission\\n" >&2
    exit 49
  fi
  printf "LEGEND\\n  treatments: A_plain=no Codemap, B_auto=CLI available and optional, C_strict=installed Codemap Skill with compact query required\\n  metrics:\\n      EREC: expected direct-importer recall\\n      RREC: final-report recall\\n      DEFF: expected dependencies exposed per tool call\\n  status: ✓ completed, ✗ failed\\n  progress: N completed cells / {AGENTIC_TOTAL_CELLS} planned cells\\n  treatment: ✓ assigned arm followed, ✗ assigned arm not followed\\n  codemap-used: ✓ Codemap call observed; ✗ no call observed (A_plain expects none)\\n  input tokens: gross total; cached and fresh details remain in telemetry only\\nEND LEGEND\\n"
  printf "agentic raw\\n" > "$CODEX_RUN_DIR/telemetry.jsonl"
  printf "agentic canonical\\n" > "$CODEX_RUN_DIR/telemetry-canonical.jsonl"
  printf "{{}}\\n" > "$CODEX_RUN_DIR/run-metadata.json"
  printf "agentic checksums\\n" > "$CODEX_RUN_DIR/checksums.sha256"
  printf "SUMMARY  status=completed  persisted_cells={AGENTIC_TOTAL_CELLS}/{AGENTIC_TOTAL_CELLS}\\n" > "$CODEX_RUN_DIR/run.log"
  printf "SUMMARY  status=completed  persisted_cells={AGENTIC_TOTAL_CELLS}/{AGENTIC_TOTAL_CELLS}\\n"
fi
if [[ "$*" == *"--auth-source"* ]]; then
  if [[ "$*" != *"run-codex-agentic.py"* ]]; then
    structural_run_dir="$CODEX_RUN_DIR"
    expect_run_dir=false
    for arg in "$@"; do
      if [ "$expect_run_dir" = true ]; then
        structural_run_dir="$arg"
        break
      fi
      if [ "$arg" = "--run-dir" ]; then
        expect_run_dir=true
      fi
    done
    mkdir -p "$structural_run_dir"
    printf "raw\\n" > "$structural_run_dir/telemetry.jsonl"
    printf "canonical\\n" > "$structural_run_dir/telemetry-canonical.jsonl"
    printf "{{}}\\n" > "$structural_run_dir/run-metadata.json"
    printf "PLAN    FN-02  rep=1  A_plain\\n"
    printf "RESULT  completed  FN-02  rep=1  A_plain  in=1  out=1  time=1s  quality=1.0  compliance:✓\\n"
    printf "ARTIFACTS:\\n - telemetry=%s/telemetry.jsonl\\n - metadata=%s/run-metadata.json\\n" "$structural_run_dir" "$structural_run_dir"
  fi
fi""",
    )
    _write_executable(
        bin_dir / "python3.11",
        """if [[ "$*" == *"version_info"* ]]; then exit 0; fi
if [[ "$*" == *"realpath"* ]]; then printf "%s\\n" "$0"; exit 0; fi
printf "Python 3.11.0\\n""",
    )
    _write_executable(bin_dir / "codex", 'printf "codex-cli 0.146.1\\n"')
    _write_executable(
        bin_dir / "shasum",
        f"""if [[ "$3" == "$REPO/"* && "$(sed -n '1p' "$3")" == *'"scan_version": {LOCKED_INDEX_SCAN_VERSION}'* && "$(sed -n '1p' "$3")" == *'"modules": []'* ]]; then
  printf "{LOCKED_INDEX_SHA}  %s\\n" "$3"
elif [[ "$3" == *"/benchmarks/manifests/codex-integration.json" ]]; then
  printf "{ACTIVE_MANIFEST_SHA}  %s\\n" "$3"
elif [[ "$3" == *"/benchmarks/manifests/codex-agentic.json" ]]; then
  printf "{AGENTIC_MANIFEST_SHA}  %s\\n" "$3"
elif [[ "$3" == "$CODEX_RUN_DIR/"* ]]; then
  exec /usr/bin/shasum -a 256 "$3"
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
        "CODEX_PAID_APPROVAL": DEFAULT_SCOPE_SHA,
        "CODEMAP_BIN": str(bin_dir / "codemap-py"),
        "REPO": str(repo),
    }
    _write_executable(
        bin_dir / "codemap-py",
        f'''root="${{!#}}"; mkdir -p "$root/.cache/codemap"; printf '{{"scan_version": {LOCKED_INDEX_SCAN_VERSION}, "modules": []}}' > "$root/.cache/codemap/$(basename "$root").json"''',
    )
    return env, call_log


def _run_batch(mode: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run one batch mode against command stubs and capture its public output."""
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), mode, *args],
        cwd=BENCHMARKS_DIR.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_batch_tty(mode: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run one batch with stdout and stderr attached to a pseudo-terminal."""
    import pty  # POSIX-only (pty -> tty -> termios); absent on Windows, so import at call time

    master_fd, slave_fd = pty.openpty()
    command = ["/bin/bash", str(SCRIPT), mode, *args]
    process = subprocess.Popen(
        command,
        cwd=BENCHMARKS_DIR.parent,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    output: list[bytes] = []
    try:
        while True:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output.append(chunk)
    finally:
        os.close(master_fd)
    return subprocess.CompletedProcess(command, process.wait(), b"".join(output).decode(), "")


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
    assert "smoke | claude" in missing.stderr
    assert "| codex" in missing.stderr
    for obsolete in ("all", "full", "refresh", "unknown"):
        rejected = _run_batch(obsolete, env)
        assert rejected.returncode == 2
        assert "smoke | claude" in rejected.stderr
        assert "| codex" in rejected.stderr
    rejected = _run_batch("smoke", env, "--dry-run")
    assert rejected.returncode == 2
    rejected = _run_batch("claude", env, "--unknown")
    assert rejected.returncode == 2
    rejected = _run_batch("codex", env, "--unknown")
    assert rejected.returncode == 2
    assert not call_log.exists()


def test_codex_default_dry_run_dispatches_structural_then_agentic_without_paid_inputs(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The selector-free no-model command advertises both Codex study plans in order."""
    env, call_log = batch_env
    for name in (
        "CODEX_PAID_APPROVAL",
        "CODEX_AGENTIC_PAID_APPROVAL",
        "CODEX_AUTH_SOURCE",
        "CODEX_RUN_DIR",
    ):
        env.pop(name, None)

    completed = _run_batch("codex", env, "--dry-run")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    codex_calls = [line for line in calls if "run-codex-structural.py" in line]
    assert len(codex_calls) == 2
    assert all("--dry-run" in line for line in codex_calls)
    full_plan = next(line for line in codex_calls if "--tasks" not in line)
    assert "--task-id" not in full_plan
    assert "--study" not in full_plan
    assert "--paid" not in full_plan
    assert "--paid-approval" not in full_plan
    assert "--max-wall-clock-seconds" not in full_plan
    agentic_calls = [line for line in calls if "run-codex-agentic.py" in line and "--resolve-scope" not in line]
    assert len(agentic_calls) == 1
    agentic_plan = agentic_calls[0]
    assert f"--manifest-path {AGENTIC_MANIFEST}" in agentic_plan
    assert "--repetitions 1" in agentic_plan
    assert "--dry-run" in agentic_plan
    dispatched = [
        line
        for line in calls
        if "run-codex-structural.py" in line or ("run-codex-agentic.py" in line and "--resolve-scope" not in line)
    ]
    assert all("run-codex-structural.py" in line for line in dispatched[: len(codex_calls)])
    assert all("run-codex-agentic.py" in line for line in dispatched[len(codex_calls) :])
    assert all("--auth-source" not in line for line in codex_calls)
    assert all("--auth-source" not in line for line in agentic_calls)
    assert all("--output-path" not in line for line in codex_calls)
    assert all("--output-path" not in line for line in agentic_calls)
    assert all("--render-results" not in line for line in codex_calls)
    assert "PLAN " in completed.stdout
    assert "219 cells" in completed.stdout
    assert completed.stdout.count(f"SCOPE   {DEFAULT_SCOPE_SHA}") == 1
    assert "48 cells" in completed.stdout


def test_codex_accepts_supported_flags_without_an_argument_count_ceiling(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Supported selectors remain composable as the launcher grows new options."""
    env, _ = batch_env

    completed = _run_batch(
        "codex",
        env,
        "--agentic",
        "--tasks=BA-02,BA-04",
        "--repetitions=2",
        "--dry-run",
    )

    assert completed.returncode == 0, completed.stderr


def test_codex_version_is_observed_without_becoming_an_admission_requirement(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """CLI version is provenance only; direct capability checks protect execution."""
    env, _ = batch_env
    codex = Path(env["PATH"].split(":", maxsplit=1)[0]) / "codex"
    _write_executable(codex, 'printf "codex-cli 0.999.0\\n"')

    accepted = _run_batch("codex", env, "--dry-run")

    assert accepted.returncode == 0, accepted.stderr
    assert "Codex CLI: codex-cli 0.999.0" in accepted.stdout

    _write_executable(codex, 'printf "codex-cli 0.1.0\\n"')
    older = _run_batch("codex", env, "--dry-run")

    assert older.returncode == 0, older.stderr
    assert "Codex CLI: codex-cli 0.1.0" in older.stdout


def test_paid_codex_uses_a_fresh_default_run_directory_without_total_timeout(
    batch_env: tuple[dict[str, str], Path],
    tmp_path: Path,
) -> None:
    """Paid launch needs approval and auth, while run naming and total duration stay automatic."""
    env, _ = batch_env
    results_root = tmp_path / "results"
    env["CODEX_RESULTS_ROOT"] = str(results_root)
    env.pop("CODEX_RUN_DIR")

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    run_dirs = list(results_root.glob("codex-integration-*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "benchmark" / "run-metadata.json").is_file()


def test_paid_codex_executes_from_a_run_scoped_source_snapshot(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Workspace edits after launch cannot change benchmark code, manifests, or plugins."""
    env, call_log = batch_env
    expected_launcher = SCRIPT.read_bytes()
    expected_manifest = ACTIVE_MANIFEST.read_bytes()

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    source_root = Path(env["CODEX_RUN_DIR"]) / ".launcher" / "source"
    assert (source_root / "benchmarks" / "run-all.sh").read_bytes() == expected_launcher
    assert (source_root / "benchmarks" / "manifests" / "codex-integration.json").read_bytes() == expected_manifest
    assert (source_root / "plugins" / "codemap-py" / ".codex-plugin" / "plugin.json").is_file()
    mode_map = json.loads(
        (source_root / "benchmarks" / "manifests" / "codemap-package-mode-map.json").read_text(encoding="utf-8")
    )
    assert mode_map["README.md"] is False
    paid_call = next(line for line in call_log.read_text(encoding="utf-8").splitlines() if "--auth-source" in line)
    assert str(source_root / "benchmarks" / "run-codex-structural.py") in paid_call


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_struct_flag_dispatches_only_the_provider_structural_runner(
    batch_env: tuple[dict[str, str], Path],
    provider: str,
) -> None:
    """The explicit structural selector excludes the provider's agentic runner."""
    env, call_log = batch_env

    completed = _run_batch(provider, env, "--struct", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert f"run-{provider}-structural.py" in calls
    assert f"run-{provider}-agentic.py" not in calls
    other_provider = "codex" if provider == "claude" else "claude"
    assert f"run-{other_provider}-" not in calls


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize(
    "selectors",
    [("--struct", "--agentic"), ("--struct", "--struct")],
    ids=["conflicting-selectors", "duplicate-struct"],
)
def test_struct_selector_rejects_conflicts_before_setup(
    batch_env: tuple[dict[str, str], Path],
    provider: str,
    selectors: tuple[str, str],
) -> None:
    """Mode selection must be singular and validated before repository setup."""
    env, call_log = batch_env

    completed = _run_batch(provider, env, *selectors)

    assert completed.returncode == 2
    assert "usage: bash benchmarks/run-all.sh" in completed.stderr
    assert not call_log.exists()


def test_codex_agentic_dry_run_dispatches_the_default_shared_scope_once(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The launcher advertises the 16-task, three-arm, one-repeat dry-run plan.

    Prevents launcher drift where the runner is correct but ``run-all.sh`` still
    dispatches only BA-01 or supplies the retired three-repeat default.
    """
    env, call_log = batch_env
    for name in (
        "CODEX_AGENTIC_PAID_APPROVAL",
        "CODEX_AUTH_SOURCE",
        "CODEX_RUN_DIR",
    ):
        env.pop(name, None)

    completed = _run_batch("codex", env, "--agentic", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    agentic_call = next(line for line in calls if "run-codex-agentic.py" in line and "--dry-run" in line)
    assert f"--manifest-path {AGENTIC_MANIFEST}" in agentic_call
    assert "--task-id" not in agentic_call
    assert "--repetitions 1" in agentic_call
    assert "--scope-sha256" not in agentic_call
    assert "--dry-run" in agentic_call
    assert "--auth-source" not in agentic_call
    assert "--output-path" not in agentic_call
    assert "--metadata-path" not in agentic_call
    assert "run-codex-structural.py" not in "\n".join(calls)
    assert "PROBE   A_plain" in completed.stdout
    assert "48 cells" in completed.stdout
    assert not Path(env.get("CODEX_RUN_DIR", "unused")).exists()


def test_codex_agentic_launcher_resolves_a_positive_repeat_override_before_setup(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A positive override binds the paid plan to its derived 96-cell scope.

    Prevents the launcher from retaining the retired fixed-repeat admission or
    dispatching a larger scope without forwarding its explicit scope identity.
    """
    env, call_log = batch_env

    completed = _run_batch("codex", env, "--agentic", "--dry-run", "--repetitions=2")

    assert completed.returncode == 0, completed.stderr
    agentic_call = next(
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "run-codex-agentic.py" in line and "--dry-run" in line
    )
    assert "--repetitions 2" in agentic_call
    assert f"--scope-sha256 {AGENTIC_REPEAT_TWO_SCOPE_SHA}" in agentic_call
    assert "96 cells" in completed.stdout


def test_claude_agentic_dry_run_dispatches_only_the_default_shared_scope(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The Claude launcher binds the 144-cell dry-run to its resolved scope.

    Prevents the two providers from exposing incompatible agentic flags or from
    retaining Claude's historical full-batch path for the shared suite.
    """
    env, call_log = batch_env

    completed = _run_batch("claude", env, "--agentic", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    claude_agentic_calls = [line for line in calls if "run-claude-agentic.py" in line]
    assert len(claude_agentic_calls) == 2
    resolver_call = next(line for line in claude_agentic_calls if "--resolve-scope" in line)
    plan_call = next(line for line in claude_agentic_calls if "--dry-run" in line)
    assert f"--manifest-path {METHODOLOGY_MANIFEST}" in resolver_call
    assert "--repeat 1" in resolver_call
    assert "--dry-run" not in resolver_call
    assert f"--manifest-path {METHODOLOGY_MANIFEST}" in plan_call
    assert "--repeat 1" in plan_call
    assert "--scope-sha256" not in plan_call
    assert "--dry-run" in plan_call
    assert "--tasks" not in plan_call
    assert "--arm" not in plan_call
    assert "--model" not in plan_call
    assert not any("run-claude-structural.py" in line for line in calls)
    assert not any("run-codex-" in line for line in calls)
    assert f"{CLAUDE_AGENTIC_TOTAL_CELLS} cells" in completed.stdout


def test_claude_agentic_launcher_binds_repeat_override_to_its_exact_scope(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A nondefault Claude repeat forwards its distinct resolved scope hash."""
    env, call_log = batch_env

    completed = _run_batch("claude", env, "--agentic", "--dry-run", "--repetitions=2")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    claude_agentic_calls = [line for line in calls if "run-claude-agentic.py" in line]
    assert len(claude_agentic_calls) == 2
    resolver_call = next(line for line in claude_agentic_calls if "--resolve-scope" in line)
    plan_call = next(line for line in claude_agentic_calls if "--dry-run" in line)
    assert "--repeat 2" in resolver_call
    assert "--repeat 2" in plan_call
    assert f"--scope-sha256 {CLAUDE_AGENTIC_REPEAT_TWO_SCOPE_SHA}" in plan_call
    assert f"{CLAUDE_AGENTIC_TOTAL_CELLS * 2} cells" in completed.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--repetitions=2",),
        ("--agentic", "--agentic"),
        ("--agentic", "--dry-run", "--dry-run"),
        ("--agentic", "--repetitions=0"),
        ("--agentic", "--repetitions=invalid"),
        ("--agentic", "--unknown"),
    ],
    ids=[
        "repeat-without-agentic",
        "duplicate-agentic",
        "duplicate-dry-run",
        "zero-repeat",
        "invalid-repeat",
        "unknown-flag",
    ],
)
def test_claude_agentic_launcher_rejects_invalid_or_duplicate_flags_before_setup(
    batch_env: tuple[dict[str, str], Path],
    args: tuple[str, ...],
) -> None:
    """Claude flag validation is symmetric with Codex and runs before setup."""
    env, call_log = batch_env

    completed = _run_batch("claude", env, *args)

    assert completed.returncode == 2
    assert "usage: bash benchmarks/run-all.sh" in completed.stderr
    assert not call_log.exists()


@pytest.mark.parametrize(
    ("missing", "expected_error"),
    [
        ("approval", "CODEX_AGENTIC_PAID_APPROVAL"),
        ("auth", "CODEX_AUTH_SOURCE"),
    ],
    ids=["missing-approval", "missing-auth"],
)
def test_codex_agentic_rejects_missing_paid_inputs_before_setup(
    batch_env: tuple[dict[str, str], Path],
    missing: str,
    expected_error: str,
) -> None:
    """Every required paid input fails before setup, auth access, or model dispatch."""
    env, call_log = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env.pop(
        {
            "approval": "CODEX_AGENTIC_PAID_APPROVAL",
            "auth": "CODEX_AUTH_SOURCE",
        }[missing]
    )

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 2
    assert expected_error in completed.stderr
    assert "bash benchmarks/run-all.sh codex --agentic --dry-run" in completed.stderr
    assert f"CODEX_AGENTIC_PAID_APPROVAL={AGENTIC_MANIFEST_SHA}" in completed.stderr
    assert "CODEX_AUTH_SOURCE=" in completed.stderr
    assert "CODEX_RUN_DIR only to choose another new path" in completed.stderr
    assert "CODEX_MAX_WALL_CLOCK_SECONDS" not in completed.stderr
    assert "benchmarks/manifests/codex-agentic.md" in completed.stderr
    _assert_safe_paid_preflight(call_log.read_text(encoding="utf-8").splitlines(), agentic=True)


def test_codex_agentic_rejects_reused_run_directory_before_setup(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Agentic evidence cannot overwrite an earlier paid run directory."""
    env, call_log = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    Path(env["CODEX_RUN_DIR"]).mkdir()

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 2
    assert "CODEX_RUN_DIR already exists" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Review the exact no-model shared agentic plan:" in completed.stderr
    assert "bash benchmarks/run-all.sh codex --agentic --dry-run" in completed.stderr
    assert f"Then launch the paid {AGENTIC_TOTAL_CELLS}-cell study with one scope-bound command:" in completed.stderr
    assert f"CODEX_AGENTIC_PAID_APPROVAL={AGENTIC_MANIFEST_SHA}" in completed.stderr
    assert 'CODEX_AUTH_SOURCE="$HOME/.codex/auth.json"' in completed.stderr
    assert "set CODEX_RUN_DIR only to choose another new path" in completed.stderr
    assert "CODEX_MAX_WALL_CLOCK_SECONDS" not in completed.stderr
    assert "bash benchmarks/run-all.sh codex --agentic" in completed.stderr
    assert "benchmarks/manifests/codex-agentic.md" in completed.stderr
    _assert_safe_paid_preflight(call_log.read_text(encoding="utf-8").splitlines(), agentic=True)


def test_paid_codex_agentic_uses_snapshot_and_exact_runner_contract(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The paid default scope passes only the admitted manifest-bound controls."""
    env, call_log = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-agentic-run"))

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    paid_call = next(line for line in calls if "run-codex-agentic.py" in line and "--auth-source" in line)
    launcher_snapshot = Path(env["CODEX_RUN_DIR"]) / ".launcher" / "run-all.sh"
    source_root = launcher_snapshot.parent / "source"
    for flag, value in (
        ("--repo-path", env["REPO"]),
        ("--index-path", f"{env['REPO']}/.cache/codemap/target.json"),
        ("--marketplace-root", str(source_root)),
        ("--codemap-bin", env["CODEMAP_BIN"]),
        ("--manifest-path", str(source_root / "benchmarks/manifests/codex-agentic.json")),
        ("--auth-source", env["CODEX_AUTH_SOURCE"]),
        ("--invocation-launcher-path", str(launcher_snapshot)),
        ("--run-dir", env["CODEX_RUN_DIR"]),
        ("--paid-approval", AGENTIC_MANIFEST_SHA),
    ):
        assert f"{flag} {value}" in paid_call
    assert "--scope-sha256" not in paid_call
    assert "--dry-run" not in paid_call
    assert "run-codex-structural.py" not in paid_call
    assert launcher_snapshot.read_bytes() == SCRIPT.read_bytes()
    run_log = (Path(env["CODEX_RUN_DIR"]) / "run.log").read_text(encoding="utf-8")
    assert "\x1b[" not in run_log
    assert run_log.count("END LEGEND") == 1
    assert sum(line == "LEGEND" for line in run_log.splitlines()) == 1
    assert f"SUMMARY  status=completed  persisted_cells={AGENTIC_TOTAL_CELLS}/{AGENTIC_TOTAL_CELLS}" in run_log
    assert (Path(env["CODEX_RUN_DIR"]) / "checksums.sha256").is_file()
    assert "== CODEX SHARED AGENTIC A/B/C STUDY ==" in completed.stdout
    assert sum(line == "LEGEND" for line in completed.stdout.splitlines()) == 1
    assert sum(line == "END LEGEND" for line in completed.stdout.splitlines()) == 1
    assert "PLAN " not in completed.stdout


def test_paid_codex_agentic_final_checksums_exclude_archived_source_tree(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Publish launcher attestations without rehashing the validated source archive."""
    env, _ = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-agentic-checksum-run"))

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 0, completed.stderr
    entries = (Path(env["CODEX_RUN_DIR"]) / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    assert any(".launcher/run-all.sh" in entry for entry in entries)
    assert any(".launcher/source.sha256" in entry for entry in entries)
    assert not any(".launcher/source/" in entry for entry in entries)


def test_paid_codex_agentic_admits_the_run_directory_before_console_capture(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The wrapper leaves the paid runner's launcher-only directory untouched on admission."""
    env, _ = batch_env
    env["ASSERT_AGENTIC_ADMISSION_FRESH"] = "1"
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-agentic-admission-run"))

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 0, completed.stderr
    assert "agentic console artifact existed before paid Python admission" not in completed.stdout


def test_paid_codex_agentic_failure_preserves_artifacts_and_prints_fresh_command(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A failed paid runner preserves diagnostics and explains the fresh retry contract."""
    env, _ = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-agentic-failed-run"))
    env["FAIL_WHEN_ARGS_CONTAIN"] = "--auth-source"

    completed = _run_batch("codex", env, "--agentic")

    assert completed.returncode == 41
    assert "Preserve the reported artifact for diagnosis" in completed.stderr
    assert "any retry requires a fresh CODEX_RUN_DIR" in completed.stderr
    assert f"CODEX_AGENTIC_PAID_APPROVAL={AGENTIC_MANIFEST_SHA}" in completed.stderr
    assert 'CODEX_AUTH_SOURCE="$HOME/.codex/auth.json"' in completed.stderr
    assert "set CODEX_RUN_DIR only to choose another new path" in completed.stderr
    assert "CODEX_MAX_WALL_CLOCK_SECONDS" not in completed.stderr
    assert "bash benchmarks/run-all.sh codex --agentic" in completed.stderr
    assert (Path(env["CODEX_RUN_DIR"]) / "run.log").is_file()
    assert (Path(env["CODEX_RUN_DIR"]) / "checksums.sha256").is_file()


def test_paid_codex_agentic_tty_output_uses_shared_renderer(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Interactive agentic runs show one colored shared legend, not raw plan output."""
    env, _ = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-agentic-tty-run"))

    completed = _run_batch_tty("codex", env, "--agentic")

    assert completed.returncode == 0, completed.stdout
    assert "Legend" in completed.stdout
    assert "End legend" in completed.stdout
    assert "\x1b[" in completed.stdout
    assert "PLAN " not in completed.stdout
    run_log = (Path(env["CODEX_RUN_DIR"]) / "run.log").read_text(encoding="utf-8")
    assert "\x1b[" not in run_log
    assert run_log.count("END LEGEND") == 1


def test_codex_agentic_selected_dry_run_dispatches_resolved_scope(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Selected agentic tasks resolve and dispatch without paid credentials."""
    env, call_log = batch_env
    for name in (
        "CODEX_AGENTIC_PAID_APPROVAL",
        "CODEX_AUTH_SOURCE",
        "CODEX_RUN_DIR",
    ):
        env.pop(name, None)

    completed = _run_batch("codex", env, "--agentic", "--tasks=BA-02,BA-04", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    resolver = next(line for line in calls if "run-codex-agentic.py" in line and "--resolve-scope" in line)
    dispatched = next(line for line in calls if "run-codex-agentic.py" in line and "--dry-run" in line)
    assert "--task-id BA-02,BA-04" in resolver
    assert "--task-id BA-02,BA-04" in dispatched
    assert f"--scope-sha256 {AGENTIC_SELECTED_SCOPE_SHA}" in dispatched
    assert "--auth-source" not in dispatched
    assert f"{AGENTIC_SELECTED_TOTAL_CELLS} cells" in completed.stdout


def test_codex_tasks_dry_run_dispatches_resolved_scope(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A task selector resolves to an explicit nonpoolable runner scope."""
    env, call_log = batch_env
    for name in (
        "CODEX_PAID_APPROVAL",
        "CODEX_AUTH_SOURCE",
        "CODEX_RUN_DIR",
    ):
        env.pop(name)

    completed = _run_batch("codex", env, "--struct", "--tasks=DI,GR", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    codex_calls = [
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "run-codex-structural.py" in line and "--resolve-tasks" not in line
    ]
    assert len(codex_calls) == 2
    selected = next(line for line in codex_calls if "--tasks DI,GR" in line)
    assert "--dry-run" in selected
    assert "--tasks DI,GR" in selected
    assert "--task-id" not in selected
    assert "--study" not in selected
    assert "--paid" not in selected
    assert "--paid-approval" not in selected
    assert "--max-wall-clock-seconds" not in selected
    assert "--scope-sha256" not in selected
    assert "--auth-source" not in selected
    assert "--output-path" not in selected
    assert "6 cells" in completed.stdout
    assert completed.stdout.count(f"SCOPE   {SELECTED_SCOPE_SHA}") == 1


@pytest.mark.parametrize(
    ("mode", "args"),
    [
        ("smoke", ()),
        ("claude", ("--struct", "--dry-run")),
        ("codex", ("--agentic", "--dry-run")),
        ("codex", ("--struct", "--tasks=DI,GR", "--dry-run")),
    ],
    ids=["smoke", "claude-structural", "codex-agentic", "codex-non-patch-selection"],
)
def test_non_patch_no_model_modes_do_not_prepare_historical_patch_indexes(
    batch_env: tuple[dict[str, str], Path],
    mode: str,
    args: tuple[str, ...],
) -> None:
    """Historical PT indexes stay out of legacy and non-PT no-model paths."""
    env, call_log = batch_env
    env["FAIL_ON_GIT_FETCH"] = "1"
    env["FAIL_WHEN_ARGS_CONTAIN"] = "--prepare-patch-bundle"

    completed = _run_batch(mode, env, *args)

    assert completed.returncode == 0, completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "--prepare-patch-bundle" not in calls


@pytest.mark.parametrize(
    "args",
    [("--struct", "--tasks=PT-01", "--dry-run"), ("--dry-run",)],
    ids=["selected-patch", "unified-codex"],
)
def test_patch_and_unified_codex_dry_runs_prepare_historical_patch_indexes(
    batch_env: tuple[dict[str, str], Path],
    args: tuple[str, ...],
) -> None:
    """PT selections and the unified Codex study require the locked PT bundle."""
    env, call_log = batch_env

    completed = _run_batch("codex", env, *args)

    assert completed.returncode == 0, completed.stderr
    assert "--prepare-patch-bundle" in call_log.read_text(encoding="utf-8")


def test_codex_rejects_removed_diagnostic_switch(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The former asymmetric diagnostic switch is no longer part of the CLI."""
    env, call_log = batch_env

    completed = _run_batch("codex", env, "--diagnostic")

    assert completed.returncode == 2
    assert "--tasks=TASK" in completed.stderr
    assert not call_log.exists()


def test_codex_tasks_reject_invalid_selector_before_setup(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Resolver syntax errors propagate before target/index preparation."""
    env, call_log = batch_env

    completed = _run_batch("codex", env, "--struct", "--tasks=INVALID", "--dry-run")

    assert completed.returncode == 2
    assert "invalid Codex task selection" in completed.stderr
    assert not any("prepare-codex-index.py" in line for line in call_log.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    "args",
    [("--struct", "--tasks=DI,GR", "--dry-run"), ("--dry-run", "--tasks=DI,GR", "--struct")],
)
def test_codex_tasks_accepts_option_ordering(
    batch_env: tuple[dict[str, str], Path],
    args: tuple[str, str, str],
) -> None:
    """Task selection composes with dry-run regardless of option order."""
    env, call_log = batch_env
    completed = _run_batch("codex", env, *args)

    assert completed.returncode == 0, completed.stderr
    selected = next(
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "run-codex-structural.py" in line and "--tasks DI,GR" in line
    )
    assert "--dry-run" in selected
    assert "--scope-sha256" not in selected
    assert "--task-id" not in selected
    assert "--study" not in selected
    assert "--paid" not in selected


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
    assert "--no-legend" not in codex_call
    assert "--tasks FN-02" in codex_call
    assert "--task-id" not in codex_call
    assert "--tasks-path" not in codex_call
    assert "--arm" not in codex_call


@pytest.mark.parametrize(
    ("mode", "args"),
    [
        ("smoke", ()),
        ("codex", ("--dry-run",)),
        ("codex", ("--struct",)),
        ("codex", ("--struct", "--tasks=DI,GR", "--dry-run")),
        ("codex", ("--struct", "--tasks=DI,GR")),
    ],
    ids=["smoke", "codex-dry-run", "codex-struct-paid", "tasks-dry-run", "tasks-paid"],
)
def test_top_level_provider_invocation_emits_one_bounded_legend(
    batch_env: tuple[dict[str, str], Path],
    mode: str,
    args: tuple[str, ...],
) -> None:
    """Launcher suppresses nested runner legends and retains one invocation legend."""
    env, _ = batch_env
    if "--tasks=DI,GR" in args:
        env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-selected-run"))
        env["CODEX_PAID_APPROVAL"] = SELECTED_SCOPE_SHA

    completed = _run_batch(mode, env, *args)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("END LEGEND") == 1
    assert sum(line == "LEGEND" for line in completed.stdout.splitlines()) == 1


@pytest.mark.parametrize(
    ("mode", "failure_pattern", "full_marker"),
    [
        ("smoke", "run-claude-structural.py", "run-codex-structural.py"),
        ("claude", "run-claude-structural.py", "--model haiku --arm A_plain"),
        ("codex", "--tasks FN-02 --dry-run", "--auth-source"),
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
    if mode == "codex":
        env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA

    completed = _run_batch(mode, env)

    assert completed.returncode == 41
    calls = call_log.read_text(encoding="utf-8")
    assert failure_pattern in calls
    assert full_marker not in calls


def test_smoke_rebuilds_mismatched_locked_index_before_provider_commands(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Rebuild an old or malformed index before provider preflights."""
    env, call_log = batch_env
    index_path = Path(env["REPO"]) / ".cache" / "codemap" / "target.json"
    index_path.write_text("stale-index", encoding="utf-8")

    completed = _run_batch("smoke", env)

    assert completed.returncode == 0, completed.stderr
    assert "stale or schema-incompatible" in completed.stdout
    calls = call_log.read_text(encoding="utf-8")
    assert "run-claude-" in calls
    assert "run-codex-structural.py" in calls


def test_smoke_rebuilds_wrong_bytes_with_current_schema_before_provider_commands(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A v12-shaped but wrong graph must not reach either provider."""
    env, call_log = batch_env
    index_path = Path(env["REPO"]) / ".cache" / "codemap" / "target.json"
    index_path.write_text(
        json.dumps({"scan_version": LOCKED_INDEX_SCAN_VERSION, "modules": [{"wrong": True}]}),
        encoding="utf-8",
    )

    completed = _run_batch("smoke", env)

    assert completed.returncode == 0, completed.stderr
    assert "stale or schema-incompatible" in completed.stdout
    calls = call_log.read_text(encoding="utf-8")
    assert "run-claude-" in calls
    assert "run-codex-structural.py" in calls


def test_generated_manifest_build_failure_blocks_provider_preflights(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Reject a generated Codex record failure before either provider can run."""
    env, call_log = batch_env
    env["FAIL_MANIFEST_CHECK"] = "1"

    completed = _run_batch("smoke", env)

    assert completed.returncode == 47
    assert "generated Codex manifest build failed" in completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "build-codex-integration-manifest.py" in calls
    assert "run-claude-" not in calls
    assert "run-codex-structural.py" not in calls


def test_generated_codex_manifest_build_failure_blocks_claude_and_codex_plans(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Every entrypoint builds the complete manifest closure before planning."""
    env, call_log = batch_env
    env["FAIL_MANIFEST_CHECK"] = "1"

    claude = _run_batch("claude", env, "--struct", "--dry-run")

    assert claude.returncode == 47
    assert "generated Codex manifest build failed" in claude.stderr
    claude_calls = call_log.read_text(encoding="utf-8")
    assert "build-provider-parity-methodology-manifest.py" in claude_calls
    assert "build-codex-integration-manifest.py" in claude_calls
    assert "build-codex-agentic-manifest.py" not in claude_calls
    assert "prepare-codex-index.py" not in claude_calls

    call_log.unlink()
    codex = _run_batch("codex", env, "--struct", "--dry-run")

    assert codex.returncode == 47
    assert "generated Codex manifest build failed" in codex.stderr
    codex_calls = call_log.read_text(encoding="utf-8")
    assert "build-codex-integration-manifest.py" in codex_calls
    assert "build-codex-agentic-manifest.py" not in codex_calls


def test_codex_index_preparation_retains_the_dual_lock_cross_check(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Codex keeps its integration-lock comparison against the methodology lock."""
    env, call_log = batch_env

    completed = _run_batch("codex", env, "--struct", "--dry-run")

    assert completed.returncode == 0, completed.stderr
    contract_call = next(
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "prepare-codex-index.py" in line and "--print-contract" in line
    )
    assert f"--manifest-path {ACTIVE_MANIFEST}" in contract_call
    assert f"--methodology-path {METHODOLOGY_MANIFEST}" in contract_call


@pytest.mark.parametrize(
    ("mode", "arguments"),
    [
        pytest.param("claude", ("--struct", "--dry-run"), id="claude-structural"),
        pytest.param("codex", ("--struct", "--dry-run"), id="codex-structural"),
        pytest.param("codex", ("--agentic", "--dry-run"), id="codex-agentic"),
    ],
)
def test_methodology_manifest_build_failure_stops_every_public_study_before_setup(
    batch_env: tuple[dict[str, str], Path],
    mode: str,
    arguments: tuple[str, ...],
) -> None:
    """A failed first checker must not be hidden by later successful commands or shell contexts."""
    env, call_log = batch_env
    env["FAIL_METHODOLOGY_CHECK"] = "1"

    completed = _run_batch(mode, env, *arguments)

    assert completed.returncode == 46
    assert "generated methodology manifest build failed" in completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "build-provider-parity-methodology-manifest.py" in calls
    assert "build-codex-integration-manifest.py" not in calls
    assert "prepare-codex-index.py" not in calls
    assert "run-claude-" not in calls
    assert "run-codex-" not in calls


@pytest.mark.parametrize(
    ("arguments", "approval_variable"),
    [
        pytest.param(("--struct",), "CODEX_PAID_APPROVAL", id="structural"),
        pytest.param(("--agentic",), "CODEX_AGENTIC_PAID_APPROVAL", id="agentic"),
    ],
)
def test_methodology_manifest_build_failure_never_prints_unrunnable_paid_guidance(
    batch_env: tuple[dict[str, str], Path],
    arguments: tuple[str, ...],
    approval_variable: str,
) -> None:
    """Approval guidance is valid only after every manifest it depends on passes validation."""
    env, call_log = batch_env
    env["FAIL_METHODOLOGY_CHECK"] = "1"
    env.pop(approval_variable, None)

    completed = _run_batch("codex", env, *arguments)

    assert completed.returncode == 46
    assert "generated methodology manifest build failed" in completed.stderr
    assert f"{approval_variable}=" not in completed.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "build-provider-parity-methodology-manifest.py" in calls
    assert "run-codex-" not in calls


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
        ("existing-run-dir", "already exists"),
    ],
    ids=["missing-approval", "missing-auth", "existing-run-dir"],
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
            }[invalid_input]
        )

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 2
    assert expected_error in completed.stderr
    _assert_safe_paid_preflight(call_log.read_text(encoding="utf-8").splitlines(), agentic=False)


def test_codex_paid_rejection_prints_actionable_launch_guidance(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A rejected paid launch must explain dry-run and copyable paid-run commands."""
    env, _ = batch_env
    env.pop("CODEX_PAID_APPROVAL")

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 2
    assert "bash benchmarks/run-all.sh codex --struct --dry-run" in completed.stderr
    assert "CODEX_PAID_APPROVAL=<approval-token-printed-above>" in completed.stderr
    assert "CODEX_AUTH_SOURCE=" in completed.stderr
    assert 'CODEX_AUTH_SOURCE="$HOME/.codex/auth.json"' in completed.stderr
    assert str(Path.home()) not in completed.stderr
    assert "set CODEX_RUN_DIR only to choose another new path" in completed.stderr
    assert "CODEX_MAX_WALL_CLOCK_SECONDS" not in completed.stderr
    assert "benchmarks/manifests/codex-integration.md" in completed.stderr
    assert "The command records paid authorization for this exact aggregate scope" in completed.stderr
    assert "use an immutable, user-owned 0600 auth source" in completed.stderr
    assert "Do not run a concurrent Codex session with it" in completed.stderr
    assert "independently authenticated benchmark credential" in completed.stderr
    assert "private sequential refresh can invalidate an unchanged source" in completed.stderr
    assert "reauthenticate after the run if needed" in completed.stderr


@pytest.mark.parametrize(
    "missing_approval",
    ["CODEX_PAID_APPROVAL", "CODEX_AGENTIC_PAID_APPROVAL"],
    ids=["structural-approval", "agentic-approval"],
)
def test_codex_default_paid_rejection_requires_both_scope_approvals_before_dispatch(
    batch_env: tuple[dict[str, str], Path],
    missing_approval: str,
) -> None:
    """Default paid Codex admission is all-or-nothing across its two study scopes."""
    env, call_log = batch_env
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env.pop(missing_approval)

    completed = _run_batch("codex", env)

    assert completed.returncode == 2
    assert "CODEX_PAID_APPROVAL=<approval-token-printed-by-the-unified-dry-run>" in completed.stderr
    assert f"CODEX_AGENTIC_PAID_APPROVAL={AGENTIC_MANIFEST_SHA}" in completed.stderr
    assert "bash benchmarks/run-all.sh codex --dry-run" in completed.stderr
    assert "benchmarks/manifests/codex-integration.md" in completed.stderr
    assert "benchmarks/manifests/codex-agentic.md" in completed.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    assert not any("run-codex-structural.py" in line and "--auth-source" in line for line in calls)
    assert not any("run-codex-agentic.py" in line and "--auth-source" in line for line in calls)


def test_combined_paid_run_defers_exact_aggregate_match_until_structural_preflight(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A syntactically valid stale aggregate approval reaches the no-model structural check only.

    Prevents combined admission from incorrectly comparing the user-provided aggregate
    approval to the manifest hash before the structural preflight derives its scope.
    """
    env, call_log = batch_env
    env["CODEX_PAID_APPROVAL"] = "a" * 64
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-stale-combined-run"))

    completed = _run_batch("codex", env)

    assert completed.returncode == 2
    # Paid study output is intentionally merged into the persisted/rendered stream.
    # The completed preflight exposes the exact replacement approval before the
    # stale value is rejected; direct-runner tests cover the full PAID_COMMAND.
    assert f"CODEX_PAID_APPROVAL={DEFAULT_SCOPE_SHA[:16]}" in completed.stdout
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert any("run-codex-structural.py" in line and "--dry-run" in line for line in calls)
    assert not any("run-codex-structural.py" in line and "--auth-source" in line for line in calls)
    assert not any("run-codex-agentic.py" in line and "--auth-source" in line for line in calls)


def test_explicit_codex_struct_rejection_preserves_selector_in_guidance(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A rejected explicit structural launch prints matching copyable commands."""
    env, _ = batch_env
    env.pop("CODEX_PAID_APPROVAL")

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 2
    assert "bash benchmarks/run-all.sh codex --struct --dry-run" in completed.stderr
    assert "bash benchmarks/run-all.sh codex --struct\n" in completed.stderr


def test_provider_modes_dispatch_only_the_selected_provider(
    batch_env: tuple[dict[str, str], Path],
    tmp_path: Path,
) -> None:
    """Selector-free Codex runs both suites from one frozen source in suite order."""
    env, call_log = batch_env

    claude = _run_batch("claude", env)
    assert claude.returncode == 0, claude.stderr
    claude_calls = call_log.read_text(encoding="utf-8")
    assert "run-claude-structural.py" in claude_calls
    assert "run-claude-agentic.py" in claude_calls
    assert "run-codex-structural.py" not in claude_calls

    call_log.unlink()
    env["CODEX_AGENTIC_PAID_APPROVAL"] = AGENTIC_MANIFEST_SHA
    env["CODEX_RESULTS_ROOT"] = str(tmp_path / "results")
    env.pop("CODEX_RUN_DIR")
    codex = _run_batch("codex", env)
    assert codex.returncode == 0, codex.stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    paid_structural = [line for line in calls if "run-codex-structural.py" in line and "--auth-source" in line]
    paid_agentic = [line for line in calls if "run-codex-agentic.py" in line and "--auth-source" in line]
    assert len(paid_structural) == 1
    assert len(paid_agentic) == 1
    structural_call = paid_structural[0]
    agentic_call = paid_agentic[0]
    assert calls.index(structural_call) < calls.index(agentic_call)
    assert "--tasks" not in structural_call
    assert "--task-id" not in structural_call
    assert "--study" not in structural_call
    assert "--paid" not in structural_call.replace("--paid-approval", "")
    assert "--reasoning-effort high" in structural_call
    assert "--max-wall-clock-seconds" not in "\n".join(calls)
    assert not any("run-claude-" in line for line in calls)

    structural_run_dir = Path(_option_value(structural_call, "--run-dir"))
    agentic_run_dir = Path(_option_value(agentic_call, "--run-dir"))
    assert structural_run_dir != agentic_run_dir
    assert structural_run_dir.is_dir()
    assert agentic_run_dir.is_dir()

    structural_launcher = Path(_option_value(structural_call, "--invocation-launcher-path"))
    agentic_launcher = Path(_option_value(agentic_call, "--invocation-launcher-path"))
    assert structural_launcher != agentic_launcher
    structural_source = structural_launcher.parent / "source"
    agentic_source = agentic_launcher.parent / "source"
    assert _option_value(structural_call, "--manifest-path") == str(
        structural_source / "benchmarks/manifests/codex-integration.json"
    )
    assert _option_value(agentic_call, "--manifest-path") == str(
        agentic_source / "benchmarks/manifests/codex-agentic.json"
    )
    assert (
        structural_source / "benchmarks/manifests/codex-integration.json"
    ).read_bytes() == ACTIVE_MANIFEST.read_bytes()
    assert (agentic_source / "benchmarks/manifests/codex-agentic.json").read_bytes() == AGENTIC_MANIFEST.read_bytes()
    assert (structural_launcher.parent / "source.sha256").read_bytes() == (
        agentic_launcher.parent / "source.sha256"
    ).read_bytes()


def test_paid_claude_structural_dispatches_shared_provider_parity_matrix(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Each model receives the shared tasks and deterministic A/B/C scheduler."""
    env, call_log = batch_env

    completed = _run_batch("claude", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    structural_calls = [
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "run-claude-structural.py" in line and "--tasks" in line and "--dry-run" not in line
    ]
    models = {line.split()[line.split().index("--model") + 1] for line in structural_calls}
    assert models == {"haiku", "sonnet", "opus"}
    assert len(structural_calls) == len(models)
    assert all("--provider-parity" in call for call in structural_calls)
    assert all("--arm" not in call for call in structural_calls)
    assert all(_claude_task_values(call) == SHARED_STRUCTURAL_TASK_IDS for call in structural_calls)
    assert SHARED_STRUCTURAL_TASK_IDS == CONFIRMATORY_TASK_IDS
    assert not any(task_id.startswith("RI-") for task_id in SHARED_STRUCTURAL_TASK_IDS)


def test_paid_codex_tasks_runs_only_resolved_scope(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A paid selected run uses the resolver scope for approval and cells."""
    env, call_log = batch_env
    env["CODEX_PAID_APPROVAL"] = SELECTED_SCOPE_SHA[:16]
    env["CODEX_RUN_DIR"] = str(Path(env["CODEX_RUN_DIR"]).with_name("codex-selected-run"))

    completed = _run_batch("codex", env, "--struct", "--tasks=DI,GR")

    assert completed.returncode == 0, completed.stderr
    codex_calls = [
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if "run-codex-structural.py" in line and "--render-results" not in line and "--resolve-tasks" not in line
    ]
    assert len(codex_calls) == 3
    paid = next(line for line in codex_calls if "--auth-source" in line)
    assert _option_value(paid, "--paid-approval") == SELECTED_SCOPE_SHA[:16]
    assert "--dry-run" not in paid
    assert "--no-legend" in paid
    assert "--tasks DI,GR" in paid
    assert "--task-id" not in paid
    assert "--study" not in paid
    assert "--paid" not in paid.replace("--paid-approval", "")
    assert "--repetitions" not in paid
    assert "--scope-sha256" not in paid
    assert "--max-wall-clock-seconds" not in paid
    assert f"--run-dir {env['CODEX_RUN_DIR']}/benchmark" in paid
    diagnostic_smoke = next(line for line in codex_calls if "--tasks FN-02 --dry-run" in line)
    assert "--no-legend" in diagnostic_smoke
    selected_plan = next(line for line in codex_calls if "--tasks DI,GR" in line and "--dry-run" in line)
    assert "--no-legend" not in selected_plan


def test_paid_codex_checksums_include_canonical_telemetry_sidecar(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Record and verify the canonical telemetry sidecar in the artifact checksum list."""
    env, _ = batch_env

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    run_dir = Path(env["CODEX_RUN_DIR"])
    canonical = run_dir / "benchmark" / "telemetry-canonical.jsonl"
    assert canonical.is_file()
    checksums = (run_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    canonical_line = next(line for line in checksums if "telemetry-canonical.jsonl" in line)
    assert canonical_line.split()[0] == hashlib.sha256(canonical.read_bytes()).hexdigest()


def test_codex_mode_reconstructs_a_missing_locked_index_before_dispatch(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A fresh target must build and byte-check the frozen index before any model command."""
    env, call_log = batch_env
    index_path = Path(env["REPO"]) / ".cache" / "codemap" / "target.json"
    index_path.unlink()

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["scan_version"] == LOCKED_INDEX_SCAN_VERSION
    assert rebuilt["modules"] == []
    assert "run-codex-structural.py" in call_log.read_text(encoding="utf-8")


def test_paid_codex_noninteractive_output_and_artifact_log_remain_plain(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A redirected paid run must retain plain terminal output and a plain tee log."""
    env, _ = batch_env

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 0, completed.stderr
    run_log = (Path(env["CODEX_RUN_DIR"]) / "run.log").read_text(encoding="utf-8")
    assert "\x1b[" not in completed.stdout
    assert "\x1b[" not in run_log
    assert run_log.count("END LEGEND") == 1
    assert sum(line == "LEGEND" for line in run_log.splitlines()) == 1
    script = SCRIPT.read_text(encoding="utf-8")
    assert "PLAN " not in completed.stdout
    assert "PLAN " in run_log
    assert "RESULT  completed" in completed.stdout
    assert "ARTIFACTS:" in completed.stdout
    assert " - telemetry=" in completed.stdout
    assert "RESULT_RENDERER" not in script
    assert "render-codex-results.py" not in script
    assert (
        'tee "$CODEX_RUN_DIR/run.log" | python3 "$ROOT/benchmarks/run-codex-structural.py" --render-results --hide-plan'
    ) in script
    assert "if [ -t 1 ]; then" not in script
    assert 'echo "→ telemetry:' not in script
    assert 'echo "→ metadata:' not in script


def test_paid_codex_tty_output_hides_plan_rows_and_uses_shared_renderer(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """An interactive paid run uses the same renderer while preserving its plan log."""
    env, call_log = batch_env

    completed = _run_batch_tty("codex", env, "--struct")

    assert completed.returncode == 0, completed.stdout
    run_log = (Path(env["CODEX_RUN_DIR"]) / "run.log").read_text(encoding="utf-8")
    assert "PLAN " not in completed.stdout
    assert "PLAN " in run_log
    assert "--render-results --hide-plan" in call_log.read_text(encoding="utf-8")


def test_paid_codex_runner_failure_survives_the_artifact_tee(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """The paid runner's non-zero exit must remain visible after its log pipeline."""
    env, call_log = batch_env
    env["FAIL_WHEN_ARGS_CONTAIN"] = "--auth-source"

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 41
    assert "--auth-source" in call_log.read_text(encoding="utf-8")
    assert (Path(env["CODEX_RUN_DIR"]) / "run.log").is_file()


def test_paid_claude_runner_failure_stops_the_batch(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """Do not reclassify a failed Claude runner as a successful cell outcome."""
    env, call_log = batch_env
    env["FAIL_WHEN_ARGS_CONTAIN"] = "--model haiku --provider-parity"

    completed = _run_batch("claude", env, "--struct")

    assert completed.returncode == 41
    calls = call_log.read_text(encoding="utf-8")
    assert "--model haiku --provider-parity" in calls
    assert "--model sonnet --provider-parity" not in calls


def test_paid_codex_renderer_failure_survives_the_artifact_pipeline(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A failed console renderer must fail the paid pipeline after teeing its log."""
    env, _ = batch_env
    env["FAIL_RENDER_RESULTS"] = "1"

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 43
    assert (Path(env["CODEX_RUN_DIR"]) / "run.log").is_file()


def test_paid_codex_tee_failure_survives_the_artifact_pipeline(
    batch_env: tuple[dict[str, str], Path],
) -> None:
    """A failed tee must fail the paid pipeline even when the renderer exits cleanly."""
    env, _ = batch_env
    tee = Path(env["PATH"].split(":", maxsplit=1)[0]) / "tee"
    _write_executable(tee, "exit 44")

    completed = _run_batch("codex", env, "--struct")

    assert completed.returncode == 44
