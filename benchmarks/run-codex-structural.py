#!/usr/bin/env python3
"""Codex-only runner for the structural provider-parity benchmark.

``structural`` is the clearer name for the former `bench`/real-codebase category;
it is not a third benchmark type. The two model-driven categories are:

  structural — constrained questions from ``tasks-bench.json`` about symbols,
               callers, dependencies, debugging, and change impact
  agentic    — open-ended exploration tasks from ``tasks-agentic.json``

This runner is structural-only. It does not load the agentic suite. Codex
agentic support needs a separate runner after its evaluator and ground-truth
transport contract are defined.

## What this measures

The same locked structural task, target repository, prompt, evaluator, and
600-second retry-inclusive per-coordinate wall-clock budget are used for three within-Codex arms. The
experiment asks whether Codemap availability reduces model input and elapsed
time without lowering task quality:

  A_plain    — Codemap absent; the locked index is inaccessible
  B_direct_required — Codemap's compact CLI query is required
  C_skill_required  — Codemap's installed query skill is required

The task series are identical to ``run-claude-structural.py``:

  SE — symbol extraction          FN — function call graph
  RV — review assistance          CQ — code quality
  BR — development blast radius   DG — debug from trace
  FT — feature scaffolding        RI — real issue
  DI — diff impact                GR — graph reasoning
  MB — module blast radius

This module owns only Codex-native process handling, isolated homes, permission
profiles, JSONL event normalization, and per-cell persistence. Task identity,
arm contracts, and scoring remain in ``provider_parity_contracts.py`` and the
shared Claude structural evaluator registry.

## Arms

Every arm receives the canonical task prompt unchanged plus a separately
fingerprinted arm envelope:

  A_plain
    Uses ``provider-parity-plain``. It has no Codemap plugin or writable path,
    and cannot read the locked index or copied authentication file.

  B_direct_required
    Uses ``provider-parity-codemap``. The direct ``$CODEMAP_BIN`` launcher and
    locked index are available; one successful compact query is required.

  C_skill_required
    Uses the same treatment profile as B with the installed Codemap skill. It
    must use ``$codemap-py:query-code`` and complete one compact query;
    compliance and correctness are recorded separately.

Both treatment profiles extend ``:read-only``, disable network, and inherit no
shell environment. B/C may write only the index-local ``.index-rw`` coordination
directory. The model command cannot read the disposable home's ``auth.json``.

## Metrics

Each task × repetition × arm cell records:

  Headline inputs:
    provider, repetition, elapsed_s, input_tokens, cached_input_tokens, output_tokens,
    fresh_input_tokens, reasoning_output_tokens, quality_score, and correct

  Diagnostics:
    command_calls, Codemap calls/successes/errors, fallback calls, required-arm
    Codemap-use compliance, exact locked-query conformance, endpoint/target/option
    fitness, treatment adherence, extraction failure, contamination, retry count,
    execution index, native item counts, raw Codex events, and provider error
    classification

The runner writes raw cells; it does not declare an advantage. The manifest
analysis compares paired log input-token ratios and quality deltas, then applies
failure, adoption, and compliance guardrails.

## What is NOT measured

  - Agentic exploration from ``tasks-agentic.json``
  - Index construction cost; the locked index is prepared before model timing
  - A general Codemap advantage from one smoke task
  - Cross-provider raw token equality or pooled Claude/Codex results

## Quick start

First run the no-model preflight. It validates the target/index identities,
permission profiles, authentication isolation, direct-launcher and installed-
skill isolation, and the deterministic cell plan:

  python benchmarks/run-codex-structural.py \\
      --repo-path /path/to/pytorch-lightning \\
      --tasks-path benchmarks/suites/tasks-bench.json \\
      --index-path /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \\
      --marketplace-root . \\
      --codemap-bin /path/to/codemap-py \\
      --model gpt-5.6-luna \\
      --task-id FN-02 \\
      --dry-run

After manifest and spend approval, omit ``--dry-run`` and provide a new output
path. This invokes the model and creates the JSONL file exclusively:

  python benchmarks/run-codex-structural.py \\
      --repo-path /path/to/pytorch-lightning \\
      --tasks-path benchmarks/suites/tasks-bench.json \\
      --index-path /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \\
      --marketplace-root . \\
      --codemap-bin /path/to/codemap-py \\
      --auth-source /path/to/codex/auth.json \\
      --model gpt-5.6-luna \\
      --task-id FN-02 \\
      --arm all \\
      --max-wall-clock-seconds 1800 \\
      --output-path benchmarks/results/codex-fn02-post-pilot.jsonl

Use ``--arm A_plain``, ``--arm B_direct_required``, or
``--arm C_skill_required`` for a single arm. ``--arm all`` uses the manifest's
deterministic arm ordering.
``--repetitions N`` executes repetitions 1 through N and records the repetition
on every JSONL row. Repeat ``--task-id`` to select the immutable pilot subset.

## Requirements

  - Python 3.10+ and the benchmark dependency group
  - Codex CLI >=0.138.0; the active permission profiles were validated with 0.145.0
  - A clean target at PyTorch Lightning tag ``2.6.5`` and its locked index
  - A direct Codemap launcher for B and the local plugin marketplace root for C
  - For authenticated execution, a user-owned regular ``auth.json`` with mode
    0600; symlinks and group/other-readable files are rejected

## Failure conditions

The run fails closed before a model call when the manifest, target, task,
prompt, index, plugin, provided authentication, or permission-profile contract
differs from the active manifest. It also rejects dirty targets, symlinked or hard-linked
protected paths, credential/index exposure to A, missing index access for B/C,
or a broad coordination write surface.

During execution, timeouts, non-zero Codex exits, malformed/incomplete native
events, extraction failures, and target/index/coordination mutations remain
visible in the result. Only zero-token retryable transport failures may retry,
at most twice, within the original coordinate's 600-second total budget. Paid
execution also requires an explicit complete-run wall-clock limit. A required arm without a successful compact query is recorded as
``compliance=false`` rather than rewritten as an incorrect task answer.

## Output

``--dry-run`` invokes no model and prints one ``PROBE`` line per selected arm
followed by deterministic task/repetition/arm ``PLAN`` lines. A paid run prints
its telemetry and metadata paths once, appends one normalized JSON object per
completed cell to ``--output-path`` in execution order, atomically refreshes a
``telemetry-canonical.jsonl`` task/repetition/A-B-C sidecar, and prints a
compact fixed-order progress block. Token counts show gross/cached/fresh
input separately in telemetry; the terminal shows gross input only. Interactive terminals color A/B/C rows; redirected logs
remain plain text. The raw file is created before the first cell so an existing
result cannot be overwritten, and each completed cell survives a later failure.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import itertools
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import sys
from rich.console import Console as _Console
from rich.panel import Panel as _Panel

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utilities import fmt_time, fmt_tok  # noqa: E402
from provider_parity_contracts import (  # noqa: E402
    ARM_CONTRACTS,
    EvaluationResult,
    PARITY_TIMEOUT_SECONDS,
    TaskPolicy,
    capability_strata,
    canonical_task_hash,
    canonical_result_rows,
    fresh_input_tokens,
    load_task_policies,
    load_task_suite,
    materialize_task_prompt,
    prompt_hash,
    semantic_suite_hash,
    token_accounting_inconsistent,
    treatment_adherence,
)


PARITY_MANIFEST_PATH = Path(__file__).parent / "manifests" / "codex-integration.json"
CODEX_STRUCTURAL_ARMS = ("A_plain", "B_direct_required", "C_skill_required")
_COUNTERBALANCED_ARM_ORDERS = tuple(itertools.permutations(CODEX_STRUCTURAL_ARMS))
ARMS = CODEX_STRUCTURAL_ARMS
PARITY_CODEX_MODEL = "gpt-5.6-luna"
PARITY_CODEX_REASONING_EFFORT = "high"
_CODEX_BIN = "codex"
_PROVENANCE_KEY = "_codex_provenance"
_NATIVE_ITEM_TELEMETRY_CONTRACT_ID = "canonical-skill-file-locked-query-components-v2"
_PLAIN_PERMISSION_PROFILE = "provider-parity-plain"
_CODEMAP_PERMISSION_PROFILE = "provider-parity-codemap"
_MIN_PERMISSION_PROFILE_VERSION = (0, 138, 0)
_COORDINATION_NAME = ".index-rw"
_REGISTRY_NAME = "registry.lock"
_READERS_NAME = "readers"
_AUTH_MAX_BYTES = 1024 * 1024
_SENSITIVE_EVENT_KEYS = frozenset(
    {"access_token", "refresh_token", "id_token", "authorization", "cookie", "set-cookie"}
)
_DISPLAY_ARM_LABELS = {
    "A_plain": "A_plain",
    "B_direct_required": "B_direct",
    "C_skill_required": "C_skill",
}
_DISPLAY_ARM_TO_CANONICAL = {label: arm for arm, label in _DISPLAY_ARM_LABELS.items()}
_DISPLAY_ARM_COLUMN_WIDTH = max(len(label) for label in _DISPLAY_ARM_LABELS.values())
_ARM_ROW_STYLES = {
    "A_plain": "yellow",
    "B_direct_required": "cyan",
    "C_skill_required": "magenta",
}
_RESULT_ARM = re.compile(r"^\(\d+/\d+\)\s+.*\b(A_plain|B_direct_required|C_skill_required|B_direct|C_skill)\b")
_OUTPUT_LEGEND = (
    "LEGEND\n"
    "  treatments: A_plain=no Codemap, B_direct=direct Codemap required, "
    "C_skill=Codemap Skill required\n"
    "  tasks:\n"
    "      SE: symbol extraction\n"
    "      FN: function-call graph\n"
    "      RV: review assistance\n"
    "      CQ: code quality\n"
    "      BR: blast radius\n"
    "      DG: debug from trace\n"
    "      FT: feature scaffolding\n"
    "      RI: real issue\n"
    "      DI: diff impact\n"
    "      GR: graph reasoning\n"
    "      MB: module blast radius\n"
    "  status: ✓ completed, ✗ failed\n"
    "  quality: continuous [0,1], ? unscoreable\n"
    "  progress: N completed cells / M planned cells\n"
    "  treatment: ✓ assigned arm followed, ✗ assigned arm not followed\n"
    "  codemap-used: ✓ Codemap call observed; ✗ no Codemap call "
    "(expected for A_plain) or required use missed (B/C)\n"
    "  input tokens: gross total; cached and fresh details remain in telemetry only\n"
    "END LEGEND"
)
_console = _Console(highlight=False)


def _format_plan_row(task_id: str, repetition: int, arm: str) -> str:
    """Format one deterministic coordinate as an aligned terminal row."""
    display_arm = _DISPLAY_ARM_LABELS.get(arm, arm)
    return f"PLAN    {task_id:<5}  rep={repetition}  {display_arm}"


def _format_result_row(
    *,
    status: str,
    task_id: str,
    repetition: int,
    arm: str,
    input_tokens: int,
    cached_input_tokens: int,
    fresh_tokens: int | None,
    output_tokens: int,
    elapsed_s: float,
    quality: str,
    adherence: bool,
    codemap_used: bool,
) -> str:
    """Format one result with stable columns and shared human-readable units."""
    del cached_input_tokens, fresh_tokens
    adherence_mark = "✓" if adherence else "✗"
    codemap_used_mark = "✓" if codemap_used else "✗"
    display_arm = _DISPLAY_ARM_LABELS.get(arm, arm)
    return (
        f"{status}  {task_id:<5}  rep={repetition}  {display_arm:<{_DISPLAY_ARM_COLUMN_WIDTH}}"
        f"  in={fmt_tok(input_tokens):>6}"
        f"  out={fmt_tok(output_tokens):>6}  time={fmt_time(elapsed_s):>5}"
        f"  quality={quality:>5}  treatment:{adherence_mark}  codemap-used:{codemap_used_mark}"
    )


def _print_arm_row(row: str, arm: str) -> None:
    """Print a plain log row, adding arm color only on interactive terminals."""
    if _console.is_terminal:
        _console.print(row, style=_ARM_ROW_STYLES[arm], markup=False, soft_wrap=True)
        return
    print(row)


def _print_result_block(rows: Iterable[tuple[str, str]], *, printed_cells: int, planned_cells: int) -> int:
    """Print persisted results in the fixed human A/B/C order for one task block."""
    arm_rank = {arm: index for index, arm in enumerate(CODEX_STRUCTURAL_ARMS)}
    for arm, row in sorted(rows, key=lambda item: arm_rank[item[0]]):
        printed_cells += 1
        _print_arm_row(f"({printed_cells}/{planned_cells}) {row}", arm)
    return printed_cells


def _result_arm(row: str) -> str | None:
    """Return the recognized arm from one result row, if any."""
    match = _RESULT_ARM.search(row)
    return _DISPLAY_ARM_TO_CANONICAL.get(match.group(1), match.group(1)) if match else None


def render_result_rows(
    rows: Iterable[str], output: TextIO, *, force_color: bool = False, hide_plan: bool = False
) -> None:
    """Render result rows, optionally hiding human PLAN rows and coloring terminal output."""
    use_color = force_color or output.isatty()
    if not use_color:
        for row in rows:
            if hide_plan and row.startswith("PLAN "):
                continue
            output.write(row)
        output.flush()
        return

    console = _Console(
        file=output,
        force_terminal=use_color,
        color_system="standard" if use_color else None,
        highlight=False,
        markup=False,
        no_color=not use_color,
    )
    legend_lines: list[str] | None = None

    def flush_legend() -> None:
        """Render one accumulated plain legend section as a titled Rich panel."""
        nonlocal legend_lines
        if legend_lines is None:
            return
        body = "\n".join(line.rstrip("\r\n") for line in legend_lines[1:-1])
        console.print(_Panel(body, title="Legend", subtitle="End legend", border_style="blue"))
        legend_lines = None

    for row in rows:
        if hide_plan and row.startswith("PLAN "):
            continue
        stripped = row.rstrip("\r\n")
        if legend_lines is not None:
            legend_lines.append(row)
            if stripped == "END LEGEND":
                flush_legend()
            continue
        if stripped == "LEGEND":
            legend_lines = [row]
            continue
        arm = _result_arm(row) if use_color else None
        if arm is None:
            output.write(row)
            continue
        console.print(row.rstrip("\n"), style=_ARM_ROW_STYLES[arm], end="\n")
    flush_legend()
    output.flush()


def _is_known_codex_arm(arm: str) -> bool:
    """Return whether an arm belongs to the current Codex experiment design."""
    return arm in CODEX_STRUCTURAL_ARMS


def deterministic_arm_order(
    experiment_revision: str,
    provider: str,
    model: str,
    task_id: str,
    repetition: int,
    *,
    reasoning_effort: str = "",
    task_ordinal: int | None = None,
) -> tuple[str, ...]:
    """Return a revision-bound, position-counterbalanced Codex arm ordering.

    The coordinate remains bound to its experiment/model/effort identity, while
    the locked task ordinal—not a per-task hash—selects one of six arm
    permutations. Across the 55-task suite, every treatment therefore occupies
    each ordinal 18 or 19 times.
    """
    if repetition < 1:
        raise ValueError("repetition must be at least 1")
    coordinates = (
        experiment_revision,
        provider,
        model,
        reasoning_effort,
        task_id,
        str(repetition),
    )
    if any(not coordinate for coordinate in coordinates):
        raise ValueError("arm-order coordinates must be non-empty")
    ordinal = _locked_task_ordinal(task_id) if task_ordinal is None else task_ordinal
    if ordinal < 0:
        raise ValueError("task ordinal must be non-negative")
    phase_payload = "|".join(coordinates[:4]).encode("utf-8")
    phase = int.from_bytes(hashlib.sha256(phase_payload).digest()[:1], "big") % len(_COUNTERBALANCED_ARM_ORDERS)
    return _COUNTERBALANCED_ARM_ORDERS[(ordinal + repetition - 1 + phase) % len(_COUNTERBALANCED_ARM_ORDERS)]


def _locked_task_ordinal(task_id: str, manifest_path: Path = PARITY_MANIFEST_PATH) -> int:
    """Return ``task_id``'s unique ordinal from the manifest's locked execution order."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        task_ids = manifest["preregistered_cells"]["structural_execution_task_ids"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("locked structural task order is unavailable") from exc
    if not isinstance(task_ids, list) or not all(isinstance(item, str) and item for item in task_ids):
        raise ValueError("locked structural task order is malformed")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("locked structural task order contains duplicate task IDs")
    try:
        return task_ids.index(task_id)
    except ValueError as exc:
        raise ValueError(f"task {task_id!r} is absent from the locked structural task order") from exc


def _arm_contract_hash(arm: str) -> str:
    """Return the active known hash or a stable local design hash before relock."""
    if arm == "A_plain" and arm in ARM_CONTRACTS:
        return ARM_CONTRACTS[arm]["contract_sha256"]
    return hashlib.sha256(_arm_envelope(arm).encode("utf-8")).hexdigest()


def _manifest_arm_order(
    experiment_revision: str,
    model: str,
    task_id: str,
    repetition: int,
    reasoning_effort: str,
    *,
    task_ordinal: int | None = None,
) -> tuple[str, ...]:
    """Read the manifest order only when it names the current Codex arm contract exactly."""
    arms = deterministic_arm_order(
        experiment_revision,
        "codex",
        model,
        task_id,
        repetition,
        reasoning_effort=reasoning_effort,
        task_ordinal=task_ordinal,
    )
    if set(arms) != set(CODEX_STRUCTURAL_ARMS) or len(arms) != len(CODEX_STRUCTURAL_ARMS):
        raise ValueError("manifest arm ordering does not match the current Codex A/B/C contract")
    return arms


def _raw_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical task object without adapter-added provenance."""
    raw = dict(task)
    raw.pop(_PROVENANCE_KEY, None)
    return raw


def _raw_task_hash(task: Mapping[str, Any]) -> str:
    """Hash raw task bytes, never a provider projection."""
    return canonical_task_hash(_raw_task(task))


def _repo_sha(repo_path: Path) -> str:
    """Return repository HEAD or ``unknown`` when the fixture has no Git metadata."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def _index_sha(index_path: Path | None) -> str:
    """Fingerprint an index file when one is configured."""
    if index_path is None or not index_path.is_file():
        return "unknown"
    try:
        return hashlib.sha256(index_path.read_bytes()).hexdigest()
    except OSError:
        return "unknown"


@dataclass(frozen=True)
class DiffImpactStageAdmission:
    """Exact, temporary Git state admitted for one staged diff-impact task."""

    repo_sha: str
    statuses: tuple[tuple[str, str], ...]
    file_sha256: tuple[tuple[str, str], ...]


def _git_porcelain_status(repo_path: Path) -> dict[str, str]:
    """Return exact short Git statuses, rejecting malformed or rename records."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("canonical Codex run could not verify worktree cleanliness") from exc
    if proc.returncode != 0:
        raise ValueError("canonical Codex run could not verify worktree cleanliness")
    records = [record for record in proc.stdout.split("\0") if record]
    statuses: dict[str, str] = {}
    for record in records:
        if len(record) < 4 or record[2] != " ":
            raise ValueError("canonical Codex run received malformed Git worktree status")
        status, relative_path = record[:2], record[3:]
        if not relative_path or status[0] in "RC" or status[1] in "RC":
            raise ValueError("canonical Codex run rejects renamed or copied worktree paths")
        if relative_path in statuses:
            raise ValueError("canonical Codex run received duplicate Git worktree status")
        statuses[relative_path] = status
    return statuses


def _stage_relative_path(repo_path: Path, relative_path: str) -> Path:
    """Return one tracked regular stage file, rejecting escaping or linked paths."""
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("canonical Codex DI stage contains an unsafe path")
    path = repo_path / relative
    current = repo_path
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ValueError("canonical Codex DI stage file is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("canonical Codex DI stage rejects symlink paths")
    path_stat = path.lstat()
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        raise ValueError("canonical Codex DI stage requires unlinked regular tracked files")
    try:
        tracked = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "--error-unmatch", "--", relative_path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("canonical Codex DI stage could not verify tracked files") from exc
    if tracked.returncode != 0:
        raise ValueError("canonical Codex DI stage requires tracked files")
    return path


def _capture_diff_impact_stage(repo_path: Path, task: Mapping[str, Any]) -> DiffImpactStageAdmission:
    """Capture the sole staged state that may temporarily replace clean-tree admission."""
    stage = task.get("stage")
    if task.get("type") != "diff_impact" or not isinstance(stage, list) or not stage:
        raise ValueError("canonical Codex DI admission requires a declared diff-impact stage")
    declared_paths: list[str] = []
    for edit in stage:
        if not isinstance(edit, Mapping) or not isinstance(edit.get("file"), str) or not edit["file"]:
            raise ValueError("canonical Codex DI stage contains an invalid file declaration")
        declared_paths.append(edit["file"])
    paths = tuple(dict.fromkeys(declared_paths))
    hashes = tuple(
        (relative_path, hashlib.sha256(_stage_relative_path(repo_path, relative_path).read_bytes()).hexdigest())
        for relative_path in paths
    )
    statuses = _git_porcelain_status(repo_path)
    expected_statuses = {relative_path: " M" for relative_path in paths}
    if statuses != expected_statuses:
        raise ValueError("canonical Codex DI stage does not match its exact staged worktree status")
    return DiffImpactStageAdmission(
        repo_sha=_repo_sha(repo_path),
        statuses=tuple(expected_statuses.items()),
        file_sha256=hashes,
    )


def _validate_diff_impact_stage_admission(repo_path: Path, admission: DiffImpactStageAdmission) -> None:
    """Fail closed unless the current DI state still equals its captured staged bytes."""
    if _repo_sha(repo_path) != admission.repo_sha:
        raise ValueError("canonical Codex DI stage changed the target commit")
    expected_statuses = dict(admission.statuses)
    if _git_porcelain_status(repo_path) != expected_statuses:
        raise ValueError("canonical Codex DI stage has unexpected worktree status")
    for relative_path, expected_hash in admission.file_sha256:
        observed_hash = hashlib.sha256(_stage_relative_path(repo_path, relative_path).read_bytes()).hexdigest()
        if observed_hash != expected_hash:
            raise ValueError("canonical Codex DI stage bytes changed after admission")


def _validate_locked_runtime(
    repo_path: Path,
    index_path: Path | None,
    arm: str,
    manifest_path: Path = PARITY_MANIFEST_PATH,
    diff_impact_stage: DiffImpactStageAdmission | None = None,
) -> None:
    """Fail closed unless the target repository and index match the frozen manifest."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_repo = manifest["target_source"]["commit"]
        expected_index = manifest["index"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity manifest is unavailable or malformed") from exc
    if _repo_sha(repo_path) != expected_repo:
        raise ValueError(f"canonical Codex run requires target commit {expected_repo}")
    if diff_impact_stage is None:
        if _git_porcelain_status(repo_path):
            raise ValueError("canonical Codex run requires a clean target worktree")
    else:
        _validate_diff_impact_stage_admission(repo_path, diff_impact_stage)
    if index_path is None or not index_path.is_file():
        raise ValueError("canonical Codex arm requires the locked index")
    if not index_path.is_relative_to(repo_path):
        raise ValueError("canonical Codemap index must be readable inside the target sandbox")
    expected_index_path = repo_path / ".cache" / "codemap" / f"{repo_path.name}.json"
    if index_path != expected_index_path:
        raise ValueError(f"canonical Codemap index must use the product resolver path {expected_index_path}")
    if hashlib.sha256(index_path.read_bytes()).hexdigest() != expected_index["raw_sha256"]:
        raise ValueError("canonical Codex run requires the locked index bytes")
    metadata = json.loads(index_path.read_text(encoding="utf-8"))
    if (
        metadata.get("git_sha") != expected_index["git_sha"]
        or metadata.get("scan_version") != expected_index["scan_version"]
    ):
        raise ValueError("canonical Codex index metadata does not match the locked manifest")


def build_codex_command(
    repo_path: Path | str,
    model: str,
    prompt: str,
    *,
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
    codex_bin: str = _CODEX_BIN,
) -> list[str]:
    """Build an ephemeral, JSONL Codex command preserving *prompt* as-is.

    The isolated ``CODEX_HOME`` supplied by :class:`CodexRunner` prevents a
    user's global config from changing an arm's tool surface.
    """
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    if not isinstance(model, str) or not model:
        raise ValueError("model must be a non-empty string")
    if not isinstance(reasoning_effort, str) or not reasoning_effort:
        raise ValueError("reasoning_effort must be a non-empty string")
    path = str(Path(repo_path).resolve())
    return [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--strict-config",
        "--cd",
        path,
        "--model",
        model,
        prompt,
    ]


def _validate_codex_stratum(model: str, reasoning_effort: str) -> None:
    """Reject benchmark execution outside the preregistered Luna/high stratum."""
    if model != PARITY_CODEX_MODEL:
        raise ValueError(f"Codex provider parity currently permits only {PARITY_CODEX_MODEL}")
    if reasoning_effort != PARITY_CODEX_REASONING_EFFORT:
        raise ValueError(f"Codex provider-parity reasoning effort must be {PARITY_CODEX_REASONING_EFFORT}")


def _manifest_revision(manifest: Mapping[str, Any]) -> str:
    """Return a non-empty experiment identity from an active manifest."""
    revision = manifest.get("experiment_revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError("provider-parity execution manifest has no experiment revision")
    return revision


def _read_manifest_revision(manifest_path: Path = PARITY_MANIFEST_PATH) -> str:
    """Read the active experiment identity for planning fixture or real tasks."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return _manifest_revision(manifest)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity execution manifest is unavailable or malformed") from exc


def _task_selection_contract(manifest_path: Path) -> dict[str, Any]:
    """Read the locked selector contract, deriving the legacy form when needed.

    The generated manifest will carry ``task_selection``.  The derivation keeps
    older, already-reviewed manifests usable until their next regeneration; it
    uses only their immutable preregistered execution order and fixed controls.
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preregistered = manifest["preregistered_cells"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("task selection contract is unavailable or malformed") from exc
    configured = manifest.get("task_selection")
    contract = configured if isinstance(configured, Mapping) else {}
    execution_ids = contract.get("execution_task_ids", preregistered.get("structural_execution_task_ids"))
    excluded_families = contract.get("excluded_task_families", ["RI"])
    repetitions = contract.get("targeted_repetitions", 3)
    arms = contract.get("arms", list(CODEX_STRUCTURAL_ARMS))
    coordinate_timeout = contract.get("coordinate_timeout_seconds", PARITY_TIMEOUT_SECONDS)
    if (
        not isinstance(execution_ids, list)
        or not execution_ids
        or not all(
            isinstance(task_id, str) and re.fullmatch(r"[A-Z]{2}-[0-9]{2}", task_id) for task_id in execution_ids
        )
        or len(execution_ids) != len(set(execution_ids))
        or not isinstance(excluded_families, list)
        or not all(isinstance(family, str) and re.fullmatch(r"[A-Z]{2}", family) for family in excluded_families)
        or len(excluded_families) != len(set(excluded_families))
        or type(repetitions) is not int
        or repetitions != 3
        or arms != list(CODEX_STRUCTURAL_ARMS)
        or type(coordinate_timeout) is not int
        or coordinate_timeout != PARITY_TIMEOUT_SECONDS
    ):
        raise ValueError("task selection contract is unavailable or malformed")
    return {
        "execution_task_ids": execution_ids,
        "excluded_task_families": excluded_families,
        "targeted_repetitions": repetitions,
        "arms": arms,
        "coordinate_timeout_seconds": coordinate_timeout,
    }


def _selector_tokens(value: str | Sequence[str]) -> list[str]:
    """Split comma-separated selectors while rejecting empty selector tokens."""
    values = [value] if isinstance(value, str) else list(value)
    if not values or not all(isinstance(item, str) for item in values):
        raise ValueError("at least one task selector is required")
    selectors: list[str] = []
    for raw_value in values:
        for token in raw_value.split(","):
            selector = token.strip().upper()
            if not selector:
                raise ValueError("task selectors cannot contain empty tokens")
            if selector not in selectors:
                selectors.append(selector)
    return selectors


def _targeted_scope_sha256(scope: Mapping[str, Any]) -> str:
    """Return the canonical identity of a resolved targeted benchmark scope."""
    payload = {
        key: scope[key]
        for key in (
            "manifest_sha256",
            "task_ids",
            "repetitions",
            "arms",
            "coordinate_timeout_seconds",
            "complete_run_max_wall_clock_seconds",
        )
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_task_selection(manifest_path: Path, selectors: str | Sequence[str]) -> dict[str, Any]:
    """Resolve exact IDs and family selectors into a locked, nonpoolable scope."""
    manifest_path = Path(manifest_path)
    contract = _task_selection_contract(manifest_path)
    normalized = _selector_tokens(selectors)
    task_ids = contract["execution_task_ids"]
    excluded = set(contract["excluded_task_families"])
    selected: set[str] = set()
    known_families = {task_id.split("-", 1)[0] for task_id in task_ids} | excluded
    for selector in normalized:
        family = selector.split("-", 1)[0]
        if family in excluded:
            raise ValueError(f"task family {family!r} is excluded from targeted execution")
        if selector in task_ids:
            selected.add(selector)
            continue
        if re.fullmatch(r"[A-Z]{2}", selector) and selector in known_families:
            selected.update(task_id for task_id in task_ids if task_id.startswith(f"{selector}-"))
            continue
        raise ValueError(f"unknown task selector {selector!r}")
    resolved_ids = [task_id for task_id in task_ids if task_id in selected]
    if not resolved_ids:
        raise ValueError("task selectors resolved to no executable tasks")
    repetitions = contract["targeted_repetitions"]
    arms = contract["arms"]
    coordinate_timeout = contract["coordinate_timeout_seconds"]
    scope = {
        "selectors": normalized,
        "task_ids": resolved_ids,
        "study_mode": "targeted",
        "nonpoolable": True,
        "pooling_eligibility": "ineligible",
        "repetitions": repetitions,
        "arms": arms,
        "coordinate_timeout_seconds": coordinate_timeout,
        "complete_run_max_wall_clock_seconds": len(resolved_ids) * repetitions * len(arms) * coordinate_timeout,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    scope["scope_sha256"] = _targeted_scope_sha256(scope)
    return scope


def _validate_targeted_scope_request(
    scope: Mapping[str, Any],
    *,
    repetitions: int,
    arm: str,
    max_wall_clock_seconds: float | None,
    scope_sha256: str | None,
    dry_run: bool,
) -> None:
    """Require paid targeted invocations to match their reviewed scope exactly."""
    if repetitions != scope["repetitions"]:
        raise ValueError("targeted execution requires the scope repetition count")
    if arm != "all":
        raise ValueError("targeted execution requires --arm all")
    if max_wall_clock_seconds != scope["complete_run_max_wall_clock_seconds"]:
        raise ValueError("targeted execution requires the derived wall-clock ceiling")
    expected_sha = scope["scope_sha256"]
    if scope_sha256 is not None and scope_sha256 != expected_sha:
        raise ValueError("targeted execution scope SHA-256 does not match the resolved scope")
    if not dry_run and scope_sha256 is None:
        raise ValueError("paid targeted execution requires --scope-sha256 from --resolve-tasks")


def _validate_unscoped_paid_task_ids(
    manifest_path: Path,
    task_ids: list[str] | None,
    *,
    targeted: bool,
    dry_run: bool,
) -> None:
    """Allow unscoped paid task IDs only for the exact confirmatory sequence."""
    if dry_run or targeted or task_ids is None:
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        confirmatory_ids = manifest["preregistered_cells"]["structural_execution_task_ids"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("confirmatory task scope is unavailable or malformed") from exc
    if task_ids != confirmatory_ids:
        raise ValueError("paid task subsets require --tasks and its resolved scope SHA-256")


def _validate_execution_manifest(manifest_path: Path = PARITY_MANIFEST_PATH) -> None:
    """Require an active manifest locked to the exact runner implementation."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        revision = _manifest_revision(manifest)
        expected_runner_sha = manifest["implementation_contract"]["artifact_sha256"]["run_codex_structural"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity execution manifest is unavailable or malformed") from exc
    actual_runner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if expected_runner_sha != actual_runner_sha:
        raise ValueError(
            f"paid execution requires a manifest locked to this runner; "
            f"revision {revision!r} records {expected_runner_sha!r}, found {actual_runner_sha!r}"
        )


@dataclass
class CodexParseResult:
    """Normalized Codex stream telemetry plus lossless parsed event records."""

    thread_id: str = ""
    output_text: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    command_calls: int = 0
    codemap_calls: int = 0
    codemap_successful_calls: int = 0
    codemap_compact_successful_calls: int = 0
    codemap_direct_calls: int = 0
    codemap_direct_successful_calls: int = 0
    codemap_direct_compact_successful_calls: int = 0
    codemap_skill_calls: int = 0
    codemap_skill_successful_calls: int = 0
    codemap_skill_compact_successful_calls: int = 0
    successful_query_arguments: list[list[str]] = field(default_factory=list)
    skill_delivery_observed: bool = False
    codemap_errors: int = 0
    fallback_calls: int = 0
    completed: bool = False
    incomplete: bool = False
    error: str = ""
    error_type: str = ""
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    malformed_lines: int = 0
    raw_usage: dict[str, Any] = field(default_factory=dict)
    item_counts: dict[str, int] = field(default_factory=dict)
    tool_elapsed_s: float | None = None
    tool_result_tokens: int | None = None
    retryable: bool = False

    @property
    def success(self) -> bool:
        """Return whether the stream reached a successful terminal event."""
        return self.completed and not self.incomplete and not self.error


def _is_refresh_token_authentication_failure(error: str) -> bool:
    """Identify deterministic OAuth refresh failures that cannot succeed on retry."""
    normalized = error.casefold()
    return (
        "401" in normalized
        and "refresh token" in normalized
        and ("expired" in normalized or "already been used" in normalized or "already used" in normalized)
    )


def _redact_sensitive_text(value: str) -> str:
    """Remove standard credential representations from persisted provider errors."""
    value = re.sub(
        r"(?i)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]*",
        r"\1: <redacted>",
        value,
    )
    value = re.sub(r"(?i)(bearer\s+)[^\s,;\]\}]+", r"\1<redacted>", value)
    return re.sub(
        r'(?i)(["\']?(?:access_token|refresh_token|id_token|authorization|cookie|set-cookie)["\']?\s*[:=]\s*["\'])[^"\']*',
        r"\1<redacted>",
        value,
    )


def _redact_sensitive_event(value: Any) -> Any:
    """Return a telemetry-safe projection without credential-valued fields."""
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if str(key).casefold() in _SENSITIVE_EVENT_KEYS else _redact_sensitive_event(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_event(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _redact_provider_error(value: Any) -> str:
    """Render one provider error without persisting credential values."""
    if isinstance(value, (Mapping, list)):
        return json.dumps(_redact_sensitive_event(value), sort_keys=True, default=str)
    return _redact_sensitive_text(str(value))


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _item_text(item: Mapping[str, Any]) -> str:
    for key in ("text", "content", "message"):
        value = item.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks = [part.get("text", "") for part in value if isinstance(part, Mapping)]
            if chunks:
                return "".join(str(part) for part in chunks)
    return ""


def _command_text(item: Mapping[str, Any]) -> str:
    values = [item.get(key, "") for key in ("command", "cmd", "name", "arguments", "input")]
    return " ".join(value if isinstance(value, str) else json.dumps(value, sort_keys=True) for value in values)


def _unwrap_native_command(command: str) -> str | None:
    """Return a native command after at most one exact Codex zsh wrapper."""
    if not command or "\n" in command or "\r" in command:
        return None
    normalized = command.strip()
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return None
    if parts[:2] != ["/bin/zsh", "-lc"]:
        return normalized
    if len(parts) != 3 or not parts[2] or "\n" in parts[2] or "\r" in parts[2]:
        return None
    return parts[2]


def _native_item_tokens(command: str) -> list[str] | None:
    """Tokenize one dedicated native command while rejecting shell composition."""
    normalized = _unwrap_native_command(command)
    if normalized is None:
        return None
    try:
        lexer = shlex.shlex(normalized, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or any(any(character in ";&|<>()`" for character in token) for token in tokens):
        return None
    return tokens


def _has_unquoted_comment(command: str) -> bool:
    """Return whether a shell comment can hide after an otherwise valid command."""
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "#":
            return True
        index += 1
    return False


def _canonical_query_arguments(command: str) -> list[str] | None:
    """Return query arguments only for the dedicated canonical launcher command."""
    normalized = _unwrap_native_command(command)
    if normalized is None:
        return None
    if _has_unquoted_comment(normalized):
        return None
    tokens = _native_item_tokens(command)
    if (
        tokens is None
        or len(tokens) < 4
        or tokens[0] not in {"$CODEMAP_BIN", "${CODEMAP_BIN}"}
        or tokens[1:3] != ["query", "--compact"]
        or any("$" in token for token in tokens[3:])
    ):
        return None
    arguments = tokens[3:]
    if arguments[0] == "help" or arguments[0].startswith("-"):
        return None
    return arguments


def _records_compact_query_attempt(command: str) -> bool:
    """Return whether a native item records a compact-query attempt for C ordering."""
    return _canonical_query_arguments(command) is not None


def _is_codemap_command(command: str, *, launcher_path: Path | None = None) -> bool:
    """Return whether a command satisfies the prospective canonical query form."""
    del launcher_path
    return _canonical_query_arguments(command) is not None


def _is_compact_codemap_query(command: str, *, launcher_path: Path | None = None) -> bool:
    """Return whether a command satisfies the canonical compact-query form."""
    return _is_codemap_command(command, launcher_path=launcher_path)


def _command_output(item: Mapping[str, Any]) -> str:
    """Return the captured command output used for deterministic evidence checks."""
    value = item.get("aggregated_output", item.get("output", ""))
    return value if isinstance(value, str) else ""


def _query_output_complete(item: Mapping[str, Any]) -> bool:
    """Return whether output contains JSON proving a completed locked-index query."""
    output = _command_output(item)
    decoder = json.JSONDecoder()
    for offset, character in enumerate(output):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(output[offset:])
        except json.JSONDecodeError:
            continue
        index = payload.get("index") if isinstance(payload, Mapping) else None
        if isinstance(index, Mapping) and index.get("query_complete") is True:
            return True
    return False


def _canonical_skill_read(command: str, skill_path: Path | None) -> bool:
    """Return whether a dedicated command uses the runner-owned Skill binding."""
    if skill_path is None:
        return False
    normalized = _unwrap_native_command(command)
    return normalized is not None and normalized.strip() == 'cat "$CODEMAP_SKILL_FILE"'


def _completed_with_explicit_zero_exit(item: Mapping[str, Any]) -> bool:
    """Return whether one native command item completed with explicit exit zero."""
    return item.get("status") == "completed" and type(item.get("exit_code")) is int and item["exit_code"] == 0


def _canonical_query_output(item: Mapping[str, Any]) -> bool:
    """Return whether output is one complete compact-query JSON document."""
    try:
        payload = json.loads(_command_output(item))
    except (TypeError, json.JSONDecodeError):
        return False
    index = payload.get("index") if isinstance(payload, Mapping) else None
    return isinstance(index, Mapping) and index.get("query_complete") is True and index.get("compact") is True


def _exact_skill_read_output(item: Mapping[str, Any], skill_path: Path | None, skill_sha256: str) -> bool:
    """Return whether output exactly proves the currently locked Skill bytes."""
    if skill_path is None or not skill_sha256:
        return False
    try:
        locked_skill_bytes = skill_path.read_bytes()
        output_bytes = _command_output(item).encode("utf-8")
    except (OSError, UnicodeEncodeError):
        return False
    return (
        bool(locked_skill_bytes)
        and hashlib.sha256(locked_skill_bytes).hexdigest() == skill_sha256
        and output_bytes == locked_skill_bytes
    )


def _iter_lines(stream: str | bytes | Iterable[str | bytes]) -> Iterable[str]:
    if isinstance(stream, bytes):
        stream = stream.decode("utf-8", errors="replace")
    if isinstance(stream, str):
        yield from stream.splitlines()
        return
    for line in stream:
        if isinstance(line, bytes):
            yield line.decode("utf-8", errors="replace")
        else:
            yield line


def _append_message_text(current: str, item: Mapping[str, Any]) -> str:
    """Preserve agent-message boundaries when reconstructing one response."""
    addition = _item_text(item)
    if not addition:
        return current
    return f"{current}\n{addition}" if current else addition


def parse_codex_jsonl(
    stream: str | bytes | Iterable[str | bytes],
    *,
    launcher_path: Path | None = None,
    skill_path: Path | None = None,
    skill_sha256: str = "",
) -> CodexParseResult:
    """Parse Codex ``exec --json`` events into provider-neutral telemetry.

    Codex has used both ``item.completed`` events and Claude-compatible
    assistant blocks across CLI versions.  This parser accepts both shapes,
    deduplicates lifecycle events by item ID, and retains every valid parsed
    event in ``raw_events`` for audit/debugging.
    """
    result = CodexParseResult()
    seen_items: set[str] = set()
    pending_items: set[str] = set()
    compact_query_attempt_seen = False
    saw_terminal = False
    saw_authentication_failure = False
    for raw_line in _iter_lines(stream):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            result.malformed_lines += 1
            continue
        if not isinstance(event, dict):
            result.malformed_lines += 1
            continue
        result.raw_events.append(_redact_sensitive_event(event))
        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            result.thread_id = str(event.get("thread_id", ""))

        usage = event.get("usage")
        if isinstance(usage, Mapping):
            result.raw_usage.update(dict(usage))
            result.input_tokens = max(result.input_tokens, _as_int(usage.get("input_tokens")))
            result.cached_input_tokens = max(
                result.cached_input_tokens,
                _as_int(usage.get("cached_input_tokens", usage.get("cache_read_input_tokens"))),
            )
            result.output_tokens = max(result.output_tokens, _as_int(usage.get("output_tokens")))
            result.reasoning_output_tokens = max(
                result.reasoning_output_tokens,
                _as_int(usage.get("reasoning_output_tokens")),
            )

        item = event.get("item")
        if isinstance(item, Mapping):
            item_id = str(item.get("id", ""))
            item_type = str(item.get("type", ""))
            command = _command_text(item)
            if event_type == "item.completed" and item_type:
                result.item_counts[item_type] = result.item_counts.get(item_type, 0) + 1
            if item_type == "agent_message" and event_type in {"", "item.completed"}:
                result.output_text = _append_message_text(result.output_text, item)
            if item_type in {"command_execution", "shell_command", "command"}:
                if event_type == "item.started" and item_id:
                    pending_items.add(item_id)
                if event_type == "item.completed" and item_id not in seen_items:
                    seen_items.add(item_id)
                    pending_items.discard(item_id)
                    result.command_calls += 1
                    duration_ms = item.get("duration_ms", item.get("elapsed_ms"))
                    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
                        elapsed = max(float(duration_ms), 0.0) / 1000.0
                        result.tool_elapsed_s = (result.tool_elapsed_s or 0.0) + elapsed
                    skill_read_verified = (
                        _canonical_skill_read(command, skill_path)
                        and _completed_with_explicit_zero_exit(item)
                        and _exact_skill_read_output(item, skill_path, skill_sha256)
                    )
                    if _canonical_query_arguments(command) is not None and (
                        skill_path is None or result.skill_delivery_observed
                    ):
                        result.codemap_calls += 1
                        delivery = "skill" if result.skill_delivery_observed else "direct"
                        if delivery == "direct":
                            result.codemap_direct_calls += 1
                        else:
                            result.codemap_skill_calls += 1
                        if not _completed_with_explicit_zero_exit(item) or not _canonical_query_output(item):
                            result.codemap_errors += 1
                        else:
                            result.codemap_successful_calls += 1
                            result.codemap_compact_successful_calls += 1
                            query_arguments = _canonical_query_arguments(command)
                            if query_arguments is not None:
                                result.successful_query_arguments.append(query_arguments)
                            if delivery == "direct":
                                result.codemap_direct_successful_calls += 1
                                result.codemap_direct_compact_successful_calls += 1
                            else:
                                result.codemap_skill_successful_calls += 1
                                result.codemap_skill_compact_successful_calls += 1
                    elif result.codemap_errors:
                        result.fallback_calls += 1
                    if skill_read_verified and not compact_query_attempt_seen:
                        result.skill_delivery_observed = True
                    if _records_compact_query_attempt(command):
                        compact_query_attempt_seen = True

        # Compatibility with older/fixture streams that use assistant blocks.
        message = event.get("message")
        if isinstance(message, Mapping):
            for block in message.get("content", []):
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "text":
                    text_item = {"text": str(block.get("text", ""))}
                    result.output_text = _append_message_text(result.output_text, text_item)
                if block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    command = _command_text(block)
                    if name.lower() in {"bash", "shell", "command_execution"}:
                        result.command_calls += 1
                    if _is_codemap_command(name + " " + command, launcher_path=launcher_path):
                        result.codemap_calls += 1
                        if result.skill_delivery_observed:
                            result.codemap_skill_calls += 1
                        else:
                            result.codemap_direct_calls += 1

        if event_type in {"turn.completed", "result", "response.completed"}:
            saw_terminal = True
            status = str(event.get("status", event.get("subtype", "completed"))).lower()
            if status in {"completed", "success", "succeeded", ""}:
                result.completed = True
            else:
                result.incomplete = True
                result.error = result.error or status
                result.error_type = result.error_type or "turn_incomplete"
        if event_type in {"error", "turn.failed", "response.failed"}:
            saw_terminal = True
            result.retryable = True
            result.incomplete = True
            error = event.get("error") or event.get("message") or event.get("detail")
            result.error = _redact_provider_error(error) if error else event_type
            native_error_type = event.get("error_type")
            if isinstance(native_error_type, str) and native_error_type:
                result.error_type = native_error_type
            elif event_type == "turn.failed":
                result.error_type = "turn_failed"
            elif event_type == "response.failed":
                result.error_type = "response_failed"
            else:
                result.error_type = "transport_error"
            if _is_refresh_token_authentication_failure(result.error):
                saw_authentication_failure = True
    if not saw_terminal and not result.error:
        result.incomplete = True
        result.error = "missing terminal event"
        result.error_type = "missing_terminal"
        result.retryable = not result.raw_events
    if pending_items:
        result.completed = False
        result.incomplete = True
        result.error = result.error or "terminal event left command items incomplete"
        result.error_type = result.error_type or "pending_item"
    if result.malformed_lines:
        result.completed = False
        result.incomplete = True
        result.error = result.error or f"malformed JSONL ({result.malformed_lines} line(s))"
        result.error_type = result.error_type or "malformed_stream"
    if saw_authentication_failure or _is_refresh_token_authentication_failure(result.error):
        result.error_type = "authentication_failed"
        result.retryable = False
    return result


@dataclass
class ArmHome:
    """Disposable Codex home and environment for one canonical arm."""

    arm: str
    path: Path
    env: dict[str, str]
    codemap_available: bool
    codemap_verified: bool = False
    auth_provisioned: bool = False
    authenticated: bool = False
    permission_profile: str = ""
    coordination_path: Path | None = None
    codemap_launcher_path: Path | None = None
    codemap_launcher_sha256: str = ""
    codemap_plugin_path: Path | None = None
    codemap_plugin_manifest_sha256: str = ""
    codemap_skill_path: Path | None = None
    codemap_skill_sha256: str = ""
    codex_rig_path: Path | None = None
    codex_rig_manifest_sha256: str = ""
    codex_rig_adapter_path: Path | None = None
    codex_rig_adapter_sha256: str = ""
    codemap_context_path: Path | None = None
    codemap_context_sha256: str = ""
    denied_read_paths: tuple[Path, ...] = ()

    def cleanup(self) -> None:
        """Remove the disposable home after a run."""
        _remove_private_directory(self.path, description="disposable Codex home")

    def __enter__(self) -> "ArmHome":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()


@dataclass(frozen=True)
class _AuthFileIdentity:
    """Stable metadata required for one private credential file."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _auth_identity(metadata: os.stat_result) -> _AuthFileIdentity:
    """Return the immutable metadata tuple used for credential stability checks."""
    return _AuthFileIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _validate_auth_metadata(metadata: os.stat_result, *, description: str) -> None:
    """Reject credentials that cannot safely carry mutable OAuth state."""
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a regular file")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise ValueError(f"{description} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError(f"{description} permissions must be exactly 0600")
    if metadata.st_nlink != 1:
        raise ValueError(f"{description} must not be hard-linked")
    if not 0 < metadata.st_size <= _AUTH_MAX_BYTES:
        raise ValueError(f"{description} size is invalid")


def _read_auth_payload(path: Path, *, description: str) -> tuple[bytes, _AuthFileIdentity]:
    """Read one stable JSON-object credential through a no-follow descriptor."""
    path = Path(path)
    try:
        _assert_safe_path_components(path)
    except ValueError:
        raise ValueError(f"{description} path is unsafe") from None
    try:
        before = path.lstat()
    except OSError:
        raise ValueError(f"{description} is unavailable") from None
    if stat.S_ISLNK(before.st_mode):
        raise ValueError(f"{description} must not be a symlink")
    _validate_auth_metadata(before, description=description)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        _validate_auth_metadata(opened, description=description)
        if _auth_identity(opened) != _auth_identity(before):
            raise ValueError(f"{description} changed while being opened")
        chunks: list[bytes] = []
        remaining = _AUTH_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != opened.st_size or len(payload) > _AUTH_MAX_BYTES:
            raise ValueError(f"{description} changed while being read")
        after_descriptor = os.fstat(descriptor)
    except OSError:
        raise ValueError(f"{description} could not be read securely") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        after = path.lstat()
    except OSError:
        raise ValueError(f"{description} changed while being read") from None
    identity = _auth_identity(before)
    if _auth_identity(after_descriptor) != identity or _auth_identity(after) != identity:
        raise ValueError(f"{description} changed while being read")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} must contain a JSON object") from exc
    if not isinstance(decoded, dict) or not decoded:
        raise ValueError(f"{description} must contain a non-empty JSON object")
    return payload, identity


def _fsync_directory(path: Path) -> None:
    """Durably publish a same-directory credential replacement when supported."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError:
        # The payload has already been fsynced; directory fsync is unavailable
        # on some supported filesystems and must not erase valid state.
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_write_auth_payload(destination: Path, payload: bytes, *, description: str) -> None:
    """Atomically replace one validated credential while retaining prior state on failure."""
    destination = Path(destination)
    parent = destination.parent
    try:
        _assert_safe_path_components(parent)
    except ValueError as exc:
        raise ValueError(f"{description} parent path is unsafe") from exc
    try:
        parent_metadata = parent.lstat()
    except OSError as exc:
        raise ValueError(f"{description} parent is unavailable") from exc
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_IMODE(parent_metadata.st_mode) != 0o700:
        raise ValueError(f"{description} parent must be a private directory")
    if hasattr(os, "getuid") and parent_metadata.st_uid != os.getuid():
        raise ValueError(f"{description} parent must be owned by the current user")
    if not 0 < len(payload) <= _AUTH_MAX_BYTES:
        raise ValueError(f"{description} payload size is invalid")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} payload must be a JSON object") from exc
    if not isinstance(decoded, dict) or not decoded:
        raise ValueError(f"{description} payload must be a non-empty JSON object")
    temporary = parent / f".{destination.name}.{uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("credential write returned no bytes")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, destination)
        _fsync_directory(parent)
    except OSError as exc:
        raise ValueError(f"{description} could not be updated securely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    _read_auth_payload(destination, description=description)


def _remove_private_directory(path: Path, *, description: str, require_private: bool = True) -> None:
    """Remove a private directory and fail if credential-bearing state remains."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    try:
        _assert_safe_path_components(path.parent)
    except ValueError as exc:
        raise RuntimeError(f"{description} parent path is unsafe") from exc
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{description} could not be inspected for cleanup") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{description} is not a private directory")
    if require_private:
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise RuntimeError(f"{description} is not owned by the current user")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RuntimeError(f"{description} permissions must be exactly 0700")
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise RuntimeError(f"{description} could not be removed") from exc
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"{description} remains after cleanup")


class _RunAuthState:
    """Private sequential OAuth state shared only between disposable cell homes."""

    def __init__(self, source: Path) -> None:
        self.source = Path(source)
        payload, self._source_identity = _read_auth_payload(self.source, description="auth source")
        root = Path(tempfile.gettempdir()).resolve(strict=True)
        _assert_safe_path_components(root)
        self.directory = Path(tempfile.mkdtemp(prefix="codex-benchmark-auth-", dir=root))
        self.directory.chmod(0o700)
        self.path = self.directory / "auth.json"
        try:
            _atomic_write_auth_payload(self.path, payload, description="run auth state")
        except BaseException:
            _remove_private_directory(self.directory, description="run auth state")
            raise
        self._closed = False

    def assert_source_unchanged(self) -> None:
        """Fail before a model call when the approved source metadata has drifted."""
        _payload, identity = _read_auth_payload(self.source, description="auth source")
        if identity != self._source_identity:
            raise ValueError("auth source metadata changed during benchmark run")

    def seed_home(self, home: Path) -> None:
        """Copy the current private credential state into one disposable home."""
        if self._closed:
            raise RuntimeError("run auth state is closed")
        payload, _identity = _read_auth_payload(self.path, description="run auth state")
        _atomic_write_auth_payload(Path(home) / "auth.json", payload, description="cell auth state")

    def refresh_from_home(self, home: Path) -> None:
        """Atomically retain a valid credential refresh produced by one cell."""
        if self._closed:
            raise RuntimeError("run auth state is closed")
        payload, _identity = _read_auth_payload(Path(home) / "auth.json", description="cell auth state")
        _atomic_write_auth_payload(self.path, payload, description="run auth state")

    def close(self) -> None:
        """Remove private run credential state exactly once."""
        if self._closed:
            return
        _remove_private_directory(self.directory, description="run auth state")
        self._closed = True


def _copy_auth_source(auth_source: Path, home: Path) -> None:
    """Copy one validated source credential into a disposable Codex home."""
    payload, _identity = _read_auth_payload(Path(auth_source), description="auth source")
    _atomic_write_auth_payload(Path(home) / "auth.json", payload, description="cell auth state")


def _assert_safe_path_components(path: Path) -> None:
    """Reject symlink components in an existing absolute filesystem path."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"permission path contains a symlink: {current}")


def _canonical_index_path(index_path: Path) -> Path:
    """Return one regular, single-link index path with no symlink components."""
    absolute = Path(os.path.abspath(index_path))
    _assert_safe_path_components(absolute)
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        raise ValueError("canonical Codemap index is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("canonical Codemap index must be a regular file")
    if metadata.st_nlink != 1:
        raise ValueError("canonical Codemap index must not be hard-linked")
    return absolute.resolve(strict=True)


def _validate_coordination_root(coordination_root: Path) -> None:
    """Fail unless the coordination root is the clean canonical rwgate skeleton."""
    _assert_safe_path_components(coordination_root)
    try:
        root_metadata = coordination_root.lstat()
    except OSError as exc:
        raise ValueError("Codemap coordination root is unavailable") from exc
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("Codemap coordination root must be a directory")

    allowed = {_READERS_NAME, _REGISTRY_NAME}
    entries = {entry.name for entry in coordination_root.iterdir()}
    if entries != allowed:
        raise ValueError(f"Codemap coordination root has unexpected or live entries: {sorted(entries - allowed)}")

    readers = coordination_root / _READERS_NAME
    registry = coordination_root / _REGISTRY_NAME
    readers_metadata = readers.lstat()
    registry_metadata = registry.lstat()
    if not stat.S_ISDIR(readers_metadata.st_mode) or readers.is_symlink():
        raise ValueError("Codemap readers path must be a real directory")
    if any(readers.iterdir()):
        raise ValueError("Codemap coordination root has live reader tokens")
    if not stat.S_ISREG(registry_metadata.st_mode) or registry.is_symlink():
        raise ValueError("Codemap registry must be a regular file")
    if registry_metadata.st_nlink != 1 or registry.read_bytes() != b"L":
        raise ValueError("Codemap registry identity is invalid")


def _prepare_coordination_root(index_path: Path) -> Path:
    """Create a clean index-local rwgate skeleton before sandboxed execution."""
    canonical_index = _canonical_index_path(index_path)
    coordination_root = canonical_index.parent / _COORDINATION_NAME
    if coordination_root.exists() or coordination_root.is_symlink():
        _validate_coordination_root(coordination_root)
        return coordination_root

    try:
        coordination_root.mkdir(mode=0o700)
        readers = coordination_root / _READERS_NAME
        readers.mkdir(mode=0o700)
        registry = coordination_root / _REGISTRY_NAME
        fd = os.open(
            registry,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(fd, b"L")
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("Codemap coordination root could not be created safely") from exc
    _validate_coordination_root(coordination_root)
    return coordination_root


def _cleanup_coordination_root(coordination_root: Path) -> None:
    """Remove only a validated, idle rwgate skeleton."""
    _validate_coordination_root(coordination_root)
    try:
        (coordination_root / _REGISTRY_NAME).unlink()
        (coordination_root / _READERS_NAME).rmdir()
        coordination_root.rmdir()
    except OSError as exc:
        raise ValueError("Codemap coordination root cleanup failed") from exc


def _shell_environment(home: ArmHome) -> dict[str, str]:
    """Return the explicit non-secret environment allowed in model commands."""
    allowed = {
        "PATH": home.env.get("PATH", os.defpath),
        "HOME": str(home.path),
        "CODEX_HOME": str(home.path),
    }
    for name in (
        "CODEMAP_BIN",
        "CODEMAP_SKILL_FILE",
        "CODEMAP_PYTHON",
        "SCAN_NO_AUTOBUILD",
        "CODEMAP_LOGGING",
        "CODEX_CODEMAP_AVAILABLE",
    ):
        value = home.env.get(name)
        if value is not None:
            allowed[name] = value
    return allowed


def _untrusted_host_agent_roots(
    home: ArmHome,
    arm: str,
    marketplace_root: Path | None = None,
) -> tuple[Path, ...]:
    """Return host tooling roots that a measured model must not inspect."""
    if not _is_known_codex_arm(arm):
        raise ValueError(f"unknown benchmark arm {arm!r}")
    roots = [Path.home() / name for name in (".agents", ".claude", ".codex")]
    if marketplace_root is not None:
        roots.append(marketplace_root)

    home_root = home.path.resolve()
    denied: list[Path] = []
    for candidate in roots:
        root = candidate.expanduser().resolve()
        if home_root == root or home_root.is_relative_to(root):
            raise ValueError("disposable Codex home must be outside denied host tooling roots")
        if root not in denied:
            denied.append(root)
    return tuple(denied)


def _write_permission_config(
    home: ArmHome,
    arm: str,
    index_path: Path | None,
    *,
    marketplace_root: Path | None = None,
) -> Path:
    """Compose permissions ahead of any preserved Codex plugin registration."""
    if not _is_known_codex_arm(arm):
        raise ValueError(f"unknown benchmark arm {arm!r}")
    profile = _PLAIN_PERMISSION_PROFILE if arm == "A_plain" else _CODEMAP_PERMISSION_PROFILE
    auth_path = (home.path / "auth.json").resolve()
    filesystem_rules = [f'{json.dumps(str(auth_path))} = "deny"']
    denied_read_paths = _untrusted_host_agent_roots(home, arm, marketplace_root)
    filesystem_rules.extend(f'{json.dumps(str(path))} = "deny"' for path in denied_read_paths)
    if index_path is None:
        raise ValueError(f"{arm} permission profile requires the locked index")
    canonical_index = _canonical_index_path(index_path)
    coordination_root: Path | None = None
    if arm == "A_plain":
        filesystem_rules.append(f'{json.dumps(str(canonical_index.parent))} = "deny"')
    else:
        coordination_root = canonical_index.parent / _COORDINATION_NAME
        if coordination_root.is_symlink():
            raise ValueError("Codemap coordination root must not be a symlink")
        filesystem_rules.append(f'{json.dumps(str(coordination_root))} = "write"')

    explicit_environment = ", ".join(
        f"{name} = {json.dumps(value)}" for name, value in sorted(_shell_environment(home).items())
    )
    config_text = "\n".join(
        [
            f'default_permissions = "{profile}"',
            "",
            "[shell_environment_policy]",
            'inherit = "none"',
            "ignore_default_excludes = false",
            f"set = {{ {explicit_environment} }}",
            "",
            f"[permissions.{profile}]",
            'description = "Read-only provider parity with isolated Codemap coordination."',
            'extends = ":read-only"',
            "",
            f"[permissions.{profile}.filesystem]",
            *filesystem_rules,
            "",
            f"[permissions.{profile}.network]",
            "enabled = false",
            "",
        ]
    )
    config_path = home.path / "config.toml"
    existing_config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    managed_markers = (
        "default_permissions =",
        "[shell_environment_policy]",
        f"[permissions.{_PLAIN_PERMISSION_PROFILE}]",
        f"[permissions.{_CODEMAP_PERMISSION_PROFILE}]",
    )
    if any(marker in existing_config for marker in managed_markers):
        raise ValueError("disposable Codex home already contains benchmark permission configuration")
    if existing_config.strip():
        config_text = f"{config_text.rstrip()}\n\n{existing_config.lstrip()}"
    config_path.write_text(config_text, encoding="utf-8")
    config_path.chmod(0o600)
    home.permission_profile = profile
    home.coordination_path = coordination_root
    home.denied_read_paths = denied_read_paths
    return config_path


def prepare_arm_home(
    arm: str,
    *,
    root: Path | None = None,
    auth_source: Path | None = None,
    codemap_bin: Path | None = None,
    plugin_installer: Callable[[Path], bool | None] | None = None,
) -> ArmHome:
    """Create an isolated ``CODEX_HOME`` implementing A/B/C availability."""
    if not _is_known_codex_arm(arm):
        raise ValueError(f"unknown benchmark arm {arm!r}")
    if root is None:
        try:
            temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        except OSError as exc:
            raise ValueError("default temporary root is unavailable") from exc
    else:
        temp_root = Path(os.path.abspath(root))
        _assert_safe_path_components(temp_root)
    if not temp_root.is_dir():
        raise ValueError("temporary root must be a real directory")
    home = Path(tempfile.mkdtemp(prefix=f"codex-{arm}-", dir=str(temp_root)))
    try:
        home.chmod(0o700)
        config = home / "config.toml"
        config.touch(mode=0o600)
        config.chmod(0o600)
        if auth_source is not None:
            _copy_auth_source(auth_source, home)
        verified = False
        if arm == "B_direct_required":
            _validated_direct_codemap_launcher(codemap_bin)
            verified = True
        elif arm == "C_skill_required" and plugin_installer is not None:
            verified = bool(plugin_installer(home))
        env = os.environ.copy()
        # Batch admission values belong to the parent orchestrator, not the
        # Codex process or any measured arm environment.
        for variable in (
            "CODEX_PAID_APPROVAL",
            "CODEX_AUTH_SOURCE",
            "CODEX_RUN_DIR",
            "CODEX_MAX_WALL_CLOCK_SECONDS",
        ):
            env.pop(variable, None)
        env.pop("CODEMAP_SKILL_FILE", None)
        env["CODEX_HOME"] = str(home)
        env["CODEX_BENCHMARK_ARM"] = arm
        env["CODEX_CODEMAP_AVAILABLE"] = "1" if verified else "0"
        arm_home = ArmHome(
            arm,
            home,
            env,
            verified,
            verified,
            auth_provisioned=auth_source is not None,
        )
        if arm == "B_direct_required":
            _configure_direct_codemap_launcher(arm_home, codemap_bin)
        return arm_home
    except BaseException:
        _remove_private_directory(home, description="disposable Codex home")
        raise


def probe_arm_home(home: ArmHome | Path, arm: str | None = None) -> dict[str, Any]:
    """Return deterministic isolation evidence, raising on cross-arm mismatch."""
    path = home.path if isinstance(home, ArmHome) else Path(home)
    expected = arm or (home.arm if isinstance(home, ArmHome) else None)
    config = path / "config.toml"
    available = home.codemap_available if isinstance(home, ArmHome) else False
    if expected == "A_plain" and available:
        raise ValueError("A_plain Codex home unexpectedly contains Codemap")
    if expected in {"B_direct_required", "C_skill_required"} and not (
        isinstance(home, ArmHome) and home.codemap_available and home.codemap_verified
    ):
        raise ValueError(f"{expected} Codex home requires verified Codemap delivery")
    if isinstance(home, ArmHome):
        skill_file = home.env.get("CODEMAP_SKILL_FILE")
        if expected == "C_skill_required":
            if home.codemap_skill_path is None or skill_file != str(home.codemap_skill_path.resolve()):
                raise ValueError("C_skill_required requires the exact installed Skill binding")
        elif skill_file is not None:
            raise ValueError(f"{expected} Codex home unexpectedly exposes CODEMAP_SKILL_FILE")
    return {
        "home": str(path),
        "config": str(config),
        "arm": expected,
        "codemap_available": available,
        "codemap_verified": isinstance(home, ArmHome) and home.codemap_verified,
        "auth_provisioned": isinstance(home, ArmHome) and home.auth_provisioned,
        "authenticated": isinstance(home, ArmHome) and home.authenticated,
        "permission_profile": home.permission_profile if isinstance(home, ArmHome) else "",
        "coordination_write_enabled": bool(isinstance(home, ArmHome) and home.coordination_path is not None),
        "codemap_python": (
            home.env.get("CODEMAP_PYTHON")
            if isinstance(home, ArmHome) and expected in {"B_direct_required", "C_skill_required"}
            else None
        ),
        "codemap_launcher_path": (
            str(home.codemap_launcher_path)
            if isinstance(home, ArmHome)
            and expected in {"B_direct_required", "C_skill_required"}
            and home.codemap_launcher_path
            else None
        ),
        "codemap_launcher_sha256": (
            home.codemap_launcher_sha256
            if isinstance(home, ArmHome) and expected in {"B_direct_required", "C_skill_required"}
            else ""
        ),
        "codemap_context_path": (
            str(home.codemap_context_path)
            if isinstance(home, ArmHome) and expected == "C_skill_required" and home.codemap_context_path
            else None
        ),
        "codemap_context_sha256": (
            home.codemap_context_sha256 if isinstance(home, ArmHome) and expected == "C_skill_required" else ""
        ),
        "codemap_skill_path": (
            str(home.codemap_skill_path)
            if isinstance(home, ArmHome) and expected == "C_skill_required" and home.codemap_skill_path
            else None
        ),
        "codemap_skill_sha256": (
            home.codemap_skill_sha256 if isinstance(home, ArmHome) and expected == "C_skill_required" else ""
        ),
        "codemap_skill_file": (
            home.env.get("CODEMAP_SKILL_FILE") if isinstance(home, ArmHome) and expected == "C_skill_required" else None
        ),
        "codex_rig_path": (
            str(home.codex_rig_path)
            if isinstance(home, ArmHome) and expected == "C_skill_required" and home.codex_rig_path
            else None
        ),
        "codex_rig_manifest_sha256": (
            home.codex_rig_manifest_sha256 if isinstance(home, ArmHome) and expected == "C_skill_required" else ""
        ),
        "network_access": False,
        "config_mode": stat.S_IMODE(config.stat().st_mode),
    }


def _invoke_plugin_command(
    command: list[str],
    env: Mapping[str, str],
    command_runner: Callable[..., Any] | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    """Run a no-model Codex plugin command through an injectable seam."""
    runner = command_runner or subprocess.run
    kwargs: dict[str, Any] = {
        "env": dict(env),
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if cwd is not None:
        kwargs["cwd"] = cwd
    try:
        completed = runner(command, **kwargs)
    except TypeError:
        completed = runner(command, dict(env))
    if isinstance(completed, tuple):
        code, stdout, stderr = (list(completed) + ["", ""])[:3]
        return int(code), str(stdout), str(stderr)
    return (
        int(getattr(completed, "returncode", 1)),
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )


def _verify_locked_codemap_python(
    *,
    manifest_path: Path = PARITY_MANIFEST_PATH,
    command_runner: Callable[..., Any] | None = None,
) -> str:
    """Validate and return the manifest-locked treatment Python executable."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runtime = manifest["codex_permission_profiles"]["treatment_runtime"]
        python_path = runtime["environment"]["CODEMAP_PYTHON"]
        required_major_minor = tuple(runtime["required_major_minor"])
        scope = runtime["scope"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity treatment runtime is unavailable or malformed") from exc
    if (
        not isinstance(python_path, str)
        or not Path(python_path).is_absolute()
        or not Path(python_path).is_file()
        or not os.access(python_path, os.X_OK)
    ):
        raise ValueError("locked CODEMAP_PYTHON must be an executable absolute file")
    if required_major_minor != (3, 11) or scope != ["B_direct_required", "C_skill_required"]:
        raise ValueError("provider-parity treatment runtime contract does not match the active manifest")

    code, stdout, stderr = _invoke_plugin_command(
        [python_path, "--version"],
        {},
        command_runner=command_runner,
    )
    version_match = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", f"{stdout}\n{stderr}")
    found_major_minor = tuple(int(part) for part in version_match.groups()) if version_match else ()
    if code != 0 or found_major_minor != required_major_minor:
        required = ".".join(str(part) for part in required_major_minor)
        raise ValueError(f"locked CODEMAP_PYTHON must report Python {required}")
    return python_path


def _verify_permission_profile(
    home: ArmHome,
    repo_path: Path,
    index_path: Path | None = None,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove the selected profile denies secrets/source and permits only coordination."""
    code, stdout, stderr = _invoke_plugin_command(
        [_CODEX_BIN, "--version"],
        home.env,
        command_runner=command_runner,
    )
    version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", f"{stdout}\n{stderr}")
    if code != 0 or version_match is None:
        raise ValueError("Codex permission-profile version probe failed")
    version = tuple(int(part) for part in version_match.groups())
    if version < _MIN_PERMISSION_PROFILE_VERSION:
        raise ValueError(f"Codex permission profiles require >= {'.'.join(map(str, _MIN_PERMISSION_PROFILE_VERSION))}")

    profile = home.permission_profile or (
        _PLAIN_PERMISSION_PROFILE if home.arm == "A_plain" else _CODEMAP_PERMISSION_PROFILE
    )
    # An activated project virtualenv may expose a workspace symlink even when
    # the running interpreter itself lives outside the protected source tree.
    probe_python = str(Path(sys.executable).resolve())
    sandbox_prefix = [
        _CODEX_BIN,
        "sandbox",
        "-P",
        profile,
        "--include-managed-config",
        "-C",
        str(repo_path),
        "--",
        probe_python,
        "-c",
    ]
    code, _stdout, error = _invoke_plugin_command(
        [*sandbox_prefix, "pass"],
        home.env,
        command_runner=command_runner,
    )
    if code != 0:
        raise ValueError(f"Codex permission profile is unsupported or rejected: {error[:200]}")

    source_probe = repo_path / f".codex-parity-deny-{uuid4().hex}"
    write_script = "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'probe')"
    code, _stdout, _stderr = _invoke_plugin_command(
        [*sandbox_prefix, write_script, str(source_probe)],
        home.env,
        command_runner=command_runner,
    )
    if code == 0 or source_probe.exists():
        source_probe.unlink(missing_ok=True)
        raise ValueError("Codex permission profile allowed a source-tree write")

    read_script = "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()"
    auth_path = home.path / "auth.json"
    if auth_path.exists():
        code, probe_stdout, probe_stderr = _invoke_plugin_command(
            [*sandbox_prefix, read_script, str(auth_path)],
            home.env,
            command_runner=command_runner,
        )
        if code == 0:
            raise ValueError("Codex permission profile allowed credential reads")
        auth_bytes = auth_path.read_bytes()
        combined_output = (probe_stdout + probe_stderr).encode("utf-8", errors="replace")
        if auth_bytes and auth_bytes in combined_output:
            raise ValueError("Codex permission probe disclosed credential material")

    enumerate_script = "from pathlib import Path; import sys; next(Path(sys.argv[1]).iterdir(), None)"
    for denied_root in home.denied_read_paths:
        if not denied_root.exists():
            continue
        code, probe_stdout, _probe_stderr = _invoke_plugin_command(
            [*sandbox_prefix, enumerate_script, str(denied_root)],
            home.env,
            command_runner=command_runner,
        )
        if code == 0 or probe_stdout:
            raise ValueError("Codex permission profile allowed host tooling discovery")

    if index_path is not None:
        code, _stdout, error = _invoke_plugin_command(
            [*sandbox_prefix, read_script, str(index_path)],
            home.env,
            command_runner=command_runner,
        )
        if home.arm == "A_plain" and code == 0:
            raise ValueError("A_plain permission profile allowed locked-index reads")
        if home.arm != "A_plain" and code != 0:
            raise ValueError(f"Codemap permission profile denied locked-index reads: {error[:200]}")

    if home.coordination_path is not None:
        coordination_probe = home.coordination_path / f".codex-parity-allow-{uuid4().hex}"
        code, _stdout, error = _invoke_plugin_command(
            [*sandbox_prefix, write_script, str(coordination_probe)],
            home.env,
            command_runner=command_runner,
        )
        if code != 0 or not coordination_probe.is_file():
            raise ValueError(f"Codex permission profile denied coordination writes: {error[:200]}")
        coordination_probe.unlink()
        _validate_coordination_root(home.coordination_path)


def _verify_authentication(
    home: ArmHome,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove the disposable home is authenticated without retaining command output."""
    returncode, _stdout, _stderr = _invoke_plugin_command(
        ["codex", "login", "status"],
        home.env,
        command_runner,
    )
    if returncode != 0:
        raise RuntimeError("disposable Codex home is not authenticated")
    home.authenticated = True


def _enabled_plugin_names(plugin_json: str) -> set[str]:
    """Return normalized enabled names from ``codex plugin list --json``."""
    try:
        payload = json.loads(plugin_json)
    except json.JSONDecodeError:
        return set()
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("plugins", payload.get("installed", []))
    else:
        entries = []
    if not isinstance(entries, list):
        return False
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            names.add(entry.lower())
            continue
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", entry.get("id", ""))).lower()
        if name and bool(entry.get("enabled", entry.get("active", True))):
            names.add(name)
    return names


def _plugin_enabled(plugin_json: str, plugin_name: str) -> bool:
    """Return whether one exact plugin appears enabled in ``codex plugin list --json``."""
    return plugin_name.lower() in _enabled_plugin_names(plugin_json)


def _verify_installed_plugin_pair(
    home: ArmHome,
    *,
    codex_bin: str = _CODEX_BIN,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Require the exact C plugin pair after final permission composition."""
    code, stdout, stderr = _invoke_plugin_command(
        [codex_bin, "plugin", "list", "--json"],
        home.env,
        command_runner,
    )
    if code != 0 or _enabled_plugin_names(stdout) != {"codemap-py", "codex-rig"}:
        raise RuntimeError(f"final Codex plugin registration is invalid: {stderr[:300]}")


def _configure_codemap_launcher(home: ArmHome, install_json: str) -> None:
    """Validate and expose the exact launcher reported by Codex plugin install."""
    try:
        payload = json.loads(install_json)
        raw_installed_path = payload["installedPath"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Codemap plugin install did not report installedPath") from exc
    if not isinstance(raw_installed_path, str) or not raw_installed_path:
        raise RuntimeError("Codemap plugin installedPath must be a non-empty string")

    installed_path = Path(os.path.abspath(raw_installed_path))
    _assert_safe_path_components(installed_path)
    try:
        installed_path = installed_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Codemap plugin installedPath is unavailable") from exc
    home_root = home.path.resolve(strict=True)
    if not installed_path.is_relative_to(home_root):
        raise RuntimeError("Codemap plugin installedPath escaped the disposable CODEX_HOME")

    plugin_manifest = installed_path / ".codex-plugin" / "plugin.json"
    launcher = installed_path / "bin" / "codemap-py"
    query_skill = installed_path / "codex-skills" / "query-code" / "SKILL.md"
    _assert_safe_path_components(plugin_manifest)
    _assert_safe_path_components(launcher)
    _assert_safe_path_components(query_skill)
    try:
        manifest_metadata = plugin_manifest.lstat()
        launcher_metadata = launcher.lstat()
        skill_metadata = query_skill.lstat()
        manifest_payload = json.loads(plugin_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Codemap plugin launcher or manifest is unavailable") from exc
    if (
        not stat.S_ISREG(manifest_metadata.st_mode)
        or plugin_manifest.is_symlink()
        or manifest_metadata.st_nlink != 1
        or manifest_payload.get("name") != "codemap-py"
    ):
        raise RuntimeError("Codemap plugin manifest identity is invalid")
    if (
        not stat.S_ISREG(launcher_metadata.st_mode)
        or launcher.is_symlink()
        or launcher_metadata.st_nlink != 1
        or not os.access(launcher, os.X_OK)
    ):
        raise RuntimeError("Codemap plugin launcher must be a regular executable")
    if not stat.S_ISREG(skill_metadata.st_mode) or query_skill.is_symlink() or skill_metadata.st_nlink != 1:
        raise RuntimeError("Codemap query skill must be a regular file")

    resolved_launcher = launcher.resolve(strict=True)
    if not resolved_launcher.is_relative_to(installed_path):
        raise RuntimeError("Codemap plugin launcher escaped installedPath")
    home.env["CODEMAP_BIN"] = str(resolved_launcher)
    home.codemap_plugin_path = installed_path
    home.codemap_plugin_manifest_sha256 = hashlib.sha256(plugin_manifest.read_bytes()).hexdigest()
    home.codemap_launcher_path = resolved_launcher
    home.codemap_launcher_sha256 = hashlib.sha256(resolved_launcher.read_bytes()).hexdigest()
    home.codemap_skill_path = query_skill.resolve(strict=True)
    home.codemap_skill_sha256 = hashlib.sha256(home.codemap_skill_path.read_bytes()).hexdigest()
    home.env["CODEMAP_SKILL_FILE"] = str(home.codemap_skill_path)


def _configure_codex_rig_plugin(home: ArmHome, install_json: str) -> None:
    """Lock the exact Codex Rig plugin installed for the skill-required arm."""
    try:
        payload = json.loads(install_json)
        raw_installed_path = payload["installedPath"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Codex Rig plugin install did not report installedPath") from exc
    if not isinstance(raw_installed_path, str) or not raw_installed_path:
        raise RuntimeError("Codex Rig plugin installedPath must be a non-empty string")

    installed_path = Path(os.path.abspath(raw_installed_path))
    _assert_safe_path_components(installed_path)
    try:
        installed_path = installed_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Codex Rig plugin installedPath is unavailable") from exc
    home_root = home.path.resolve(strict=True)
    if not installed_path.is_relative_to(home_root):
        raise RuntimeError("Codex Rig plugin installedPath escaped the disposable CODEX_HOME")

    plugin_manifest = installed_path / ".codex-plugin" / "plugin.json"
    adapter = installed_path / "shared" / "codemap_adapter.py"
    _assert_safe_path_components(plugin_manifest)
    _assert_safe_path_components(adapter)
    try:
        manifest_metadata = plugin_manifest.lstat()
        adapter_metadata = adapter.lstat()
        manifest_payload = json.loads(plugin_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Codex Rig plugin manifest is unavailable") from exc
    if (
        not stat.S_ISREG(manifest_metadata.st_mode)
        or plugin_manifest.is_symlink()
        or manifest_metadata.st_nlink != 1
        or manifest_payload.get("name") != "codex-rig"
    ):
        raise RuntimeError("Codex Rig plugin manifest identity is invalid")
    if not stat.S_ISREG(adapter_metadata.st_mode) or adapter.is_symlink() or adapter_metadata.st_nlink != 1:
        raise RuntimeError("Codex Rig adapter must be a regular file")
    home.codex_rig_path = installed_path
    home.codex_rig_manifest_sha256 = hashlib.sha256(plugin_manifest.read_bytes()).hexdigest()
    home.codex_rig_adapter_path = adapter.resolve(strict=True)
    home.codex_rig_adapter_sha256 = hashlib.sha256(home.codex_rig_adapter_path.read_bytes()).hexdigest()


def _verify_treatment_artifact_locks(home: ArmHome, manifest_path: Path) -> None:
    """Require installed treatment files and versions to match the reviewed manifest locks."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hashes = manifest["artifact_sha256"]
        codemap_version = str(manifest["codemap_candidate"]["version"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Codex treatment manifest is missing artifact locks") from exc
    expected_launcher = hashes.get("codemap_runtime_cli") if isinstance(hashes, Mapping) else None
    if not isinstance(expected_launcher, str) or home.codemap_launcher_sha256 != expected_launcher:
        raise ValueError("Codemap launcher does not match the locked runtime artifact")
    if home.arm == "B_direct_required":
        try:
            runtime_lock = manifest["direct_cli_runtime"]
            expected_files = runtime_lock["files"]
            expected_aggregate = runtime_lock["aggregate_sha256"]
            staged_root = home.codemap_launcher_path.parent.parent
        except (AttributeError, KeyError, TypeError) as exc:
            raise ValueError("direct CLI runtime closure lock is missing") from exc
        observed_files = _runtime_file_hashes(staged_root)
        if not isinstance(expected_files, Mapping) or observed_files != dict(expected_files):
            raise ValueError("staged direct CLI runtime does not match the locked file closure")
        if not isinstance(expected_aggregate, str) or _aggregate_file_hashes(observed_files) != expected_aggregate:
            raise ValueError("staged direct CLI runtime aggregate does not match the manifest")
        return
    if home.codemap_skill_path is None or home.env.get("CODEMAP_SKILL_FILE") != str(home.codemap_skill_path.resolve()):
        raise ValueError("installed Codemap Skill binding does not match the locked path")
    try:
        codex_rig_version = str(manifest["codex_rig_candidate"]["version"])
        expected = {
            "codemap_candidate_manifest": home.codemap_plugin_manifest_sha256,
            "codemap_query_skill": home.codemap_skill_sha256,
            "codex_rig_plugin_manifest": home.codex_rig_manifest_sha256,
            "codex_rig_adapter": home.codex_rig_adapter_sha256,
        }
        codemap_manifest = json.loads(
            (home.codemap_plugin_path / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        rig_manifest = json.loads((home.codex_rig_path / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (AttributeError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("installed Codemap/Codex Rig artifact identity is incomplete") from exc
    if codemap_manifest.get("version") != codemap_version or rig_manifest.get("version") != codex_rig_version:
        raise ValueError("installed Codemap/Codex Rig version does not match the treatment manifest")
    for artifact_name, observed_sha256 in expected.items():
        expected_sha256 = hashes.get(artifact_name) if isinstance(hashes, Mapping) else None
        if not isinstance(expected_sha256, str) or observed_sha256 != expected_sha256:
            raise ValueError(f"installed treatment artifact does not match lock: {artifact_name}")


def _admit_installed_skill_pair(
    home: ArmHome,
    repo_path: Path,
    index_path: Path,
    *,
    manifest_path: Path,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Run the installed Codex Rig adapter once and persist verified C admission context."""
    if home.arm != "C_skill_required" or home.codex_rig_adapter_path is None or home.codemap_plugin_path is None:
        raise ValueError("installed-skill admission requires a locked C skill home")
    if home.codemap_launcher_path is None or not home.env.get("CODEMAP_PYTHON"):
        raise ValueError("installed-skill admission requires locked Codemap runtime paths")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        admission = manifest["codex_rig_integration_admission"]
        category = admission["probe_category"]
        target = admission["probe_target"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Codex treatment manifest is missing installed-skill admission controls") from exc
    if category != "analysis" or not isinstance(target, str) or not target:
        raise ValueError("Codex treatment manifest has invalid installed-skill admission controls")
    root = repo_path.resolve(strict=True)
    locked_index = _canonical_index_path(index_path)
    context_path = home.path.resolve(strict=True) / "codemap-context.json"
    command = [
        home.env["CODEMAP_PYTHON"],
        str(home.codex_rig_adapter_path),
        "context",
        "--category",
        category,
        "--target",
        target,
        "--root",
        str(root),
        "--out",
        str(context_path),
    ]
    code, _stdout, stderr = _invoke_plugin_command(
        command,
        _shell_environment(home),
        command_runner,
        cwd=root,
    )
    if code != 0:
        raise RuntimeError(f"installed Codex Rig context admission failed: {stderr[:300]}")
    _assert_safe_path_components(context_path)
    try:
        metadata = context_path.lstat()
        payload = json.loads(context_path.read_text(encoding="utf-8"))
        probe = payload["probe"]
        doctor = probe["doctor"]
        queries = payload["queries"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("installed Codex Rig context admission produced no valid context") from exc
    if not stat.S_ISREG(metadata.st_mode) or context_path.is_symlink() or metadata.st_nlink != 1:
        raise RuntimeError("installed Codex Rig context artifact must be a regular file")
    query_evidence_valid = (
        isinstance(queries, list)
        and bool(queries)
        and all(
            isinstance(query, Mapping)
            and query.get("exit_code") == 0
            and query.get("error") is None
            and query.get("query_complete") is True
            for query in queries
        )
    )
    checks = {
        "protocol": payload.get("protocol_version") == "codemap-py.integration.v1",
        "target": payload.get("target") == target,
        "context_status": payload.get("status") in {"available", "degraded"},
        "probe_status": probe.get("status") == "available",
        "launcher": probe.get("launcher") == str(home.codemap_launcher_path),
        "plugin_root": doctor.get("plugin_root") == str(home.codemap_plugin_path),
        "index_path": doctor.get("index_path") == str(locked_index),
        "queries": query_evidence_valid,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise RuntimeError("installed Codex Rig context admission failed checks: " + ", ".join(failed_checks))
    home.codemap_context_path = context_path.resolve(strict=True)
    home.codemap_context_sha256 = hashlib.sha256(home.codemap_context_path.read_bytes()).hexdigest()


def _admit_staged_direct_cli(
    home: ArmHome,
    repo_path: Path,
    index_path: Path,
    *,
    manifest_path: Path,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Execute one task-shaped compact query through B's staged CLI runtime."""
    if home.arm != "B_direct_required" or home.codemap_launcher_path is None:
        raise ValueError("direct CLI admission requires a locked B runtime")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        admission = manifest["direct_cli_admission"]
        subcommand = admission["probe_subcommand"]
        target = admission["probe_target"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("direct CLI admission contract is missing") from exc
    if subcommand != "fn-rdeps" or not isinstance(target, str) or "::" not in target:
        raise ValueError("direct CLI admission query is not task-shaped")

    index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    profile = home.permission_profile or _CODEMAP_PERMISSION_PROFILE
    command = [
        _CODEX_BIN,
        "sandbox",
        "-P",
        profile,
        "--include-managed-config",
        "-C",
        str(repo_path),
        "--",
        str(home.codemap_launcher_path),
        "query",
        "--compact",
        subcommand,
        target,
    ]
    code, stdout, stderr = _invoke_plugin_command(
        command,
        _shell_environment(home),
        command_runner=command_runner,
    )
    output_item = {"aggregated_output": stdout}
    if code != 0 or not _query_output_complete(output_item):
        detail = stderr.strip() or stdout.strip()
        raise RuntimeError(f"staged direct CLI admission query failed: {detail[:300]}")
    if hashlib.sha256(index_path.read_bytes()).hexdigest() != index_sha256:
        raise RuntimeError("staged direct CLI admission mutated the locked index")


def _validated_direct_codemap_launcher(codemap_bin: Path | None) -> Path:
    """Return a directly supplied regular Codemap launcher without plugin discovery."""
    if codemap_bin is None:
        raise ValueError("B_direct_required requires --codemap-bin")
    launcher = Path(codemap_bin)
    if not launcher.is_absolute():
        raise ValueError("--codemap-bin must be an absolute path")
    _assert_safe_path_components(launcher)
    try:
        metadata = launcher.lstat()
        resolved_launcher = launcher.resolve(strict=True)
    except OSError as exc:
        raise ValueError("--codemap-bin is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or launcher.is_symlink()
        or metadata.st_nlink != 1
        or not os.access(resolved_launcher, os.X_OK)
    ):
        raise ValueError("--codemap-bin must be a regular executable")
    return resolved_launcher


def _direct_runtime_files(source_root: Path) -> dict[str, Path]:
    """Return the exact source files required by the isolated direct CLI."""
    relative_paths = [
        Path("bin/codemap-py"),
        Path("bin/_exclusions.py"),
        Path("scripts/codemap_py_entry.py"),
        *sorted(path.relative_to(source_root) for path in (source_root / "src" / "codemap_py").rglob("*.py")),
    ]
    files: dict[str, Path] = {}
    resolved_root = source_root.resolve(strict=True)
    for relative_path in relative_paths:
        path = source_root / relative_path
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("--codemap-bin runtime bundle is incomplete") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not resolved.is_relative_to(resolved_root):
            raise ValueError("--codemap-bin runtime bundle contains an unsafe path")
        files[relative_path.as_posix()] = resolved
    return files


def _runtime_file_hashes(runtime_root: Path) -> dict[str, str]:
    """Hash the exact files present in a staged direct CLI runtime."""
    return {
        path.relative_to(runtime_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(runtime_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _aggregate_file_hashes(hashes: Mapping[str, str]) -> str:
    """Return a stable aggregate identity for a relative-path hash mapping."""
    payload = "".join(f"{path}\0{sha256}\n" for path, sha256 in sorted(hashes.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _archive_snapshot_file(
    source: Path,
    destination: Path,
    *,
    role: str,
    archive_root: Path,
    source_root: Path | None = None,
    entries: list[dict[str, Any]],
) -> None:
    """Copy one verified non-secret input and append its deterministic identity."""
    _assert_safe_path_components(source)
    metadata = source.lstat()
    resolved = source.resolve(strict=True)
    if source.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"snapshot source must be a regular single-link file: {source}")
    if source_root is not None and not resolved.is_relative_to(source_root.resolve(strict=True)):
        raise ValueError(f"snapshot source escaped its locked root: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise ValueError(f"snapshot source changed while being opened: {source}")
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(source_fd, "rb") as source_handle:
            source_fd = None
            with os.fdopen(destination_fd, "wb") as destination_handle:
                destination_fd = None
                shutil.copyfileobj(source_handle, destination_handle)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ValueError(f"snapshot source could not be copied securely: {source}") from exc
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if destination_fd is not None:
            os.close(destination_fd)
    payload = destination.read_bytes()
    entries.append(
        {
            "role": role,
            "archived_path": destination.relative_to(archive_root).as_posix(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    )


def _archive_snapshot_tree(
    source_root: Path,
    destination_root: Path,
    *,
    role: str,
    entries: list[dict[str, Any]],
) -> None:
    """Archive every regular file in one verified package/runtime tree."""
    root = source_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"snapshot package root must be a real directory: {source_root}")
    for source in sorted(root.rglob("*")):
        if not source.is_file() or source.is_symlink() or "__pycache__" in source.parts or source.suffix == ".pyc":
            continue
        relative = source.relative_to(root)
        _archive_snapshot_file(
            source,
            destination_root / relative,
            role=role,
            archive_root=destination_root.parent.parent,
            source_root=root,
            entries=entries,
        )


def _write_input_snapshot(
    snapshot_root: Path,
    *,
    manifest_path: Path,
    tasks_path: Path,
    runner_path: Path,
    invocation_launcher_path: Path | None = None,
    index_path: Path | None,
    auth_source: Path | None,
    arm_archives: Mapping[str, Mapping[str, Path]],
    arm_files: Mapping[str, Mapping[str, Path]] | None = None,
) -> dict[str, Any]:
    """Write immutable launch inputs without copying credential bytes."""
    if snapshot_root.exists():
        raise FileExistsError(snapshot_root)
    snapshot_root.mkdir(parents=True, mode=0o700)
    entries: list[dict[str, Any]] = []
    shared = snapshot_root / "shared"
    for role, source, relative in (
        ("manifest", manifest_path, Path("manifest.json")),
        ("task_suite", tasks_path, Path("tasks-bench.json")),
        ("runner", runner_path, Path("run-codex-structural.py")),
    ):
        _archive_snapshot_file(source, shared / relative, role=role, archive_root=snapshot_root, entries=entries)
    if invocation_launcher_path is not None:
        _archive_snapshot_file(
            invocation_launcher_path,
            shared / "run-all.sh",
            role="invocation_launcher",
            archive_root=snapshot_root,
            entries=entries,
        )
    if index_path is not None:
        _archive_snapshot_file(
            index_path,
            shared / "locked-index.json",
            role="locked_index",
            archive_root=snapshot_root,
            entries=entries,
        )
    files_by_arm = arm_files or {}
    for arm in sorted(set(arm_archives) | set(files_by_arm)):
        for relative, source in sorted(files_by_arm.get(arm, {}).items()):
            _archive_snapshot_file(
                source,
                snapshot_root / arm / relative,
                role=f"{arm}:{relative}",
                archive_root=snapshot_root,
                entries=entries,
            )
        for package_role, root in sorted(arm_archives.get(arm, {}).items()):
            _archive_snapshot_tree(
                root, snapshot_root / arm / package_role, role=f"{arm}:{package_role}", entries=entries
            )

    auth_metadata: dict[str, Any] | None = {"supplied": True, "archived": False} if auth_source is not None else None

    entries.sort(key=lambda item: (str(item["role"]), str(item["archived_path"])))
    payload = {
        "schema_version": "codex-structural-input-snapshot-v1",
        "files": entries,
        "auth_source": auth_metadata,
    }
    snapshot_path = snapshot_root / "input-snapshot.json"
    serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    snapshot_path.write_bytes(serialized)
    snapshot_path.chmod(0o600)
    payload["path"] = str(snapshot_path.resolve())
    payload["sha256"] = hashlib.sha256(serialized).hexdigest()
    payload["bytes"] = len(serialized)
    return payload


def _validate_invocation_launcher(path: Path, expected_sha256: str) -> None:
    """Require the executing paid launcher to remain the locked regular file."""
    try:
        metadata = path.lstat()
        observed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"invocation launcher is unavailable: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or metadata.st_nlink != 1:
        raise ValueError(f"invocation launcher is not a private regular file: {path}")
    if observed_sha256 != expected_sha256:
        raise ValueError(f"invocation launcher changed: expected {expected_sha256}, observed {observed_sha256}")


def _configure_direct_codemap_launcher(home: ArmHome, codemap_bin: Path | None) -> None:
    """Stage the direct CLI runtime inside B's disposable home and expose it."""
    source_launcher = _validated_direct_codemap_launcher(codemap_bin)
    source_root = source_launcher.parent.parent
    if source_launcher.parent.name != "bin" or source_launcher.name != "codemap-py":
        raise ValueError("--codemap-bin must use the Codemap runtime layout")
    source_files = _direct_runtime_files(source_root)

    # Only the CLI closure is staged: no plugin manifest, skill, marketplace,
    # or Codex Rig bytes enter B's model-visible home.
    staged_root = home.path / "direct-cli"
    staged_launcher = staged_root / "bin" / "codemap-py"
    for relative_path, source in source_files.items():
        destination = staged_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    staged_launcher.chmod(source_launcher.stat().st_mode & 0o777)
    source_hashes = {
        relative_path: hashlib.sha256(source.read_bytes()).hexdigest() for relative_path, source in source_files.items()
    }
    if _runtime_file_hashes(staged_root) != source_hashes:
        raise RuntimeError("staged Codemap runtime differs from its locked source closure")
    home.env["CODEMAP_BIN"] = str(staged_launcher)
    home.codemap_launcher_path = staged_launcher
    home.codemap_launcher_sha256 = hashlib.sha256(staged_launcher.read_bytes()).hexdigest()


def _install_codemap_plugin(
    home: ArmHome,
    marketplace_root: Path | None,
    *,
    codex_bin: str = _CODEX_BIN,
    command_runner: Callable[..., Any] | None = None,
) -> bool:
    """Install and lock Codex Rig plus Codemap via Codex's no-model plugin CLI."""
    if marketplace_root is None:
        return False
    marketplace_root = marketplace_root.resolve()
    marketplace_manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_manifest.is_file():
        raise RuntimeError(
            "Codemap plugin source must be a marketplace root containing .agents/plugins/marketplace.json"
        )
    add_marketplace = [codex_bin, "plugin", "marketplace", "add", str(marketplace_root)]
    add_codex_rig = [codex_bin, "plugin", "add", "codex-rig@borda-ai-rig", "--json"]
    add_plugin = [codex_bin, "plugin", "add", "codemap-py@borda-ai-rig", "--json"]
    list_plugins = [codex_bin, "plugin", "list", "--json"]
    codex_rig_install_json = ""
    install_json = ""
    for command in (add_marketplace, add_plugin, add_codex_rig):
        code, stdout, stderr = _invoke_plugin_command(command, home.env, command_runner)
        if code != 0:
            raise RuntimeError(f"Codemap plugin setup failed ({' '.join(command[1:4])}): {stderr[:300]}")
        if command is add_plugin:
            install_json = stdout
        elif command is add_codex_rig:
            codex_rig_install_json = stdout
    _configure_codex_rig_plugin(home, codex_rig_install_json)
    _configure_codemap_launcher(home, install_json)
    code, stdout, stderr = _invoke_plugin_command(list_plugins, home.env, command_runner)
    if code != 0 or not _plugin_enabled(stdout, "codex-rig") or not _plugin_enabled(stdout, "codemap-py"):
        raise RuntimeError(f"Codemap plugin verification failed: {stderr[:300]}")
    return True


def _verify_plain_plugin_absent(
    home: ArmHome,
    *,
    codex_bin: str = _CODEX_BIN,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove A has no Codemap plugin or Codemap binary exposed on PATH."""
    code, stdout, stderr = _invoke_plugin_command([codex_bin, "plugin", "list", "--json"], home.env, command_runner)
    if code != 0:
        raise RuntimeError(f"A_plain plugin absence probe failed: {stderr[:300]}")
    if _plugin_enabled(stdout, "codemap-py"):
        raise RuntimeError("A_plain Codemap plugin unexpectedly enabled")
    path_dirs = home.env.get("PATH", "").split(os.pathsep)
    if any(
        (Path(directory) / candidate).exists() for directory in path_dirs for candidate in ("codemap-py", "scan-query")
    ):
        raise RuntimeError("A_plain Codemap binary is exposed on PATH")


def load_tasks_with_provenance(tasks_path: Path, manifest_path: Path = PARITY_MANIFEST_PATH) -> list[dict[str, Any]]:
    """Load raw tasks and fail closed on any locked hash or ordering mismatch."""
    raw_tasks = load_task_suite(tasks_path)
    policies = load_task_policies(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    experiment_revision = _manifest_revision(manifest)
    manifest_rows = {task["id"]: task for suite in manifest.get("suites", []) for task in suite.get("tasks", [])}
    task_ids = [task["id"] for task in raw_tasks]
    matching_suites = [
        suite for suite in manifest.get("suites", []) if [row.get("id") for row in suite.get("tasks", [])] == task_ids
    ]
    if len(matching_suites) != 1:
        raise ValueError("ordered task IDs do not match exactly one locked manifest suite")
    for task_ordinal, task in enumerate(raw_tasks):
        row = manifest_rows.get(task["id"])
        if row is None or task["id"] not in policies:
            raise ValueError(f"no locked task policy for {task['id']!r}")
        if canonical_task_hash(task) != row.get("canonical_task_sha256"):
            raise ValueError(f"task hash mismatch for {task['id']!r}")
        if prompt_hash(task) != row.get("prompt_sha256"):
            raise ValueError(f"prompt hash mismatch for {task['id']!r}")
    suite_hash = semantic_suite_hash(raw_tasks)
    raw_hash = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    loaded: list[dict[str, Any]] = []
    for task_ordinal, task in enumerate(raw_tasks):
        policy: TaskPolicy = policies[task["id"]]
        if policy.experiment_revision != experiment_revision:
            raise ValueError(f"task policy revision mismatch for {task['id']!r}")
        item = dict(task)
        item[_PROVENANCE_KEY] = {
            "experiment_revision": experiment_revision,
            "task_hash": canonical_task_hash(task),
            "prompt_hash": prompt_hash(task),
            "suite_hash": suite_hash,
            "suite_raw_hash": raw_hash,
            "task_ordinal": task_ordinal,
            "oracle_class": policy.oracle_class,
            "headline_eligible_v1": policy.headline_eligible_v1,
            "scoreable": policy.scoreable,
        }
        loaded.append(item)
    return loaded


@dataclass
class CodexRun:
    """Normalized provider result carrying shared provenance and native telemetry."""

    arm: str
    task_id: str
    task_type: str
    model: str
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT
    provider: str = "codex"
    capability_strata: tuple[str, ...] = ()
    quality_components: dict[str, float] = field(default_factory=dict)
    repetition: int = 1
    success: bool = False
    experiment_revision: str = ""
    parity_arm: str = ""
    task_hash: str = ""
    prompt_hash: str = ""
    suite_hash: str = ""
    suite_raw_hash: str = ""
    evaluator_id: str = ""
    evaluator_hash: str = ""
    envelope_hash: str = ""
    arm_contract_hash: str = ""
    repo_sha: str = "unknown"
    index_sha: str = "unknown"
    oracle_class: str = "unknown"
    headline_eligible_v1: bool = False
    scoreable: bool = True
    targeted: bool = False
    diagnostic_only: bool = False
    study_mode: str = "confirmatory"
    quality_score: float | None = None
    correct: bool = False
    input_tokens: int = 0
    cached_input_tokens: int = 0
    fresh_input_tokens: int | None = None
    token_accounting_inconsistent: bool = False
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    command_calls: int = 0
    codemap_calls: int = 0
    codemap_successful_calls: int = 0
    codemap_compact_successful_calls: int = 0
    codemap_direct_calls: int = 0
    codemap_direct_successful_calls: int = 0
    codemap_direct_compact_successful_calls: int = 0
    codemap_skill_calls: int = 0
    codemap_skill_successful_calls: int = 0
    codemap_skill_compact_successful_calls: int = 0
    successful_query_arguments: list[list[str]] = field(default_factory=list)
    locked_query_conformance: bool | None = None
    locked_query_fitness: float | None = None
    locked_query_endpoint_fitness: float | None = None
    locked_query_target_fitness: float | None = None
    locked_query_option_fitness: float | None = None
    skill_delivery_observed: bool = False
    codemap_errors: int = 0
    fallback_calls: int = 0
    compliance: bool | None = None
    treatment_adherence: bool = False
    codemap_delivery: str = "none"
    incomplete: bool = False
    extraction_failed: bool = False
    contaminated: bool = False
    error: str = ""
    error_type: str = ""
    output_text: str = ""
    thread_id: str = ""
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    telemetry_contract_id: str = _NATIVE_ITEM_TELEMETRY_CONTRACT_ID
    native_item_counts: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    tool_elapsed_s: float | None = None
    tool_result_tokens: int | None = None
    native_attempt_events: list[list[dict[str, Any]]] = field(default_factory=list)
    retry_count: int = 0
    execution_index: int = -1
    cell_wall_clock_limit_s: float = PARITY_TIMEOUT_SECONDS
    run_wall_clock_limit_s: float | None = None
    turn_budget_enforced: bool = False


@dataclass(frozen=True)
class LockedQueryFitness:
    """Continuous exact-query similarity with independently visible components."""

    overall: float
    endpoint: float
    target: float
    options: float


def _arm_compliance(arm: str, evidence: CodexParseResult | CodexRun) -> bool | None:
    """Evaluate the transport-specific required-use contract for one arm."""
    if arm == "B_direct_required":
        return evidence.codemap_direct_compact_successful_calls > 0
    if arm == "C_skill_required":
        return evidence.skill_delivery_observed and evidence.codemap_skill_compact_successful_calls > 0
    if arm == "A_plain":
        return None
    raise ValueError(f"unknown benchmark arm {arm!r}")


def _locked_query_conformance(task: Mapping[str, Any], arm: str, run: CodexParseResult | CodexRun) -> bool | None:
    """Report whether successful compact queries exactly match the locked contract."""
    if arm == "A_plain":
        return None
    locked = _locked_expected_queries(task)
    if not locked:
        return None
    observed = {
        normalized
        for arguments in run.successful_query_arguments
        if arguments and (normalized := _normalize_locked_query(arguments[0], arguments[1:])) is not None
    }
    if _expected_query_policy(task) == "all_required":
        return all(query in observed for query in locked)
    return any(query in observed for query in locked)


def _locked_query_fitness(
    task: Mapping[str, Any],
    arm: str,
    run: CodexParseResult | CodexRun,
) -> LockedQueryFitness | None:
    """Score exact-query similarity and expose endpoint, target, and option contributions."""
    if arm == "A_plain":
        return None
    locked = _locked_expected_queries(task)
    if not locked:
        return None
    observed = [
        normalized
        for arguments in run.successful_query_arguments
        if arguments and (normalized := _normalize_locked_query(arguments[0], arguments[1:])) is not None
    ]
    if not observed:
        return LockedQueryFitness(0.0, 0.0, 0.0, 0.0)
    best_matches = [_best_locked_query_match(expected_query, observed) for expected_query in locked]
    if _expected_query_policy(task) == "all_required":
        return _mean_locked_query_fitness(best_matches)
    return max(
        best_matches,
        key=lambda match: (match.overall, match.endpoint, match.target, match.options),
    )


def _best_locked_query_match(
    expected_query: tuple[str, ...],
    observed_queries: list[tuple[str, ...]],
) -> LockedQueryFitness:
    """Return the single observed query most similar to one locked query."""
    matches = [_locked_query_pair_fitness(expected_query, actual_query) for actual_query in observed_queries]
    return max(matches, key=lambda match: (match.overall, match.endpoint, match.target, match.options))


def _mean_locked_query_fitness(matches: list[LockedQueryFitness]) -> LockedQueryFitness:
    """Average required-query fitness without mixing independently matched components."""
    count = len(matches)
    return LockedQueryFitness(
        overall=sum(match.overall for match in matches) / count,
        endpoint=sum(match.endpoint for match in matches) / count,
        target=sum(match.target for match in matches) / count,
        options=sum(match.options for match in matches) / count,
    )


_EXPECTED_QUERY_POLICIES = frozenset({"any_match", "all_required"})


def _expected_query_policy(task: Mapping[str, Any]) -> str:
    """Return the task query-match policy, defaulting legacy tasks to any-match."""
    policy = task.get("expected_query_policy", "any_match")
    if not isinstance(policy, str) or policy not in _EXPECTED_QUERY_POLICIES:
        choices = ", ".join(sorted(_EXPECTED_QUERY_POLICIES))
        raise ValueError(f"expected_query_policy must be one of {choices}")
    return policy


def _locked_expected_queries(task: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """Normalize every valid expected query declared by one task."""
    expected = task.get("expected_queries")
    if not isinstance(expected, list) or not expected:
        return []
    locked: list[tuple[str, ...]] = []
    for query in expected:
        if not isinstance(query, Mapping) or not isinstance(query.get("cmd"), str):
            continue
        arguments = query.get("args", [])
        if isinstance(arguments, list) and all(isinstance(value, str) for value in arguments):
            normalized = _normalize_locked_query(str(query["cmd"]), arguments)
            if normalized is not None:
                locked.append(normalized)
    return locked


def _locked_query_pair_fitness(
    expected_query: tuple[str, ...],
    actual_query: tuple[str, ...],
) -> LockedQueryFitness:
    """Measure overall and component similarity for one locked/observed pair."""
    expected_endpoint, expected_targets, expected_options = _split_normalized_query(expected_query)
    actual_endpoint, actual_targets, actual_options = _split_normalized_query(actual_query)
    return LockedQueryFitness(
        overall=_token_set_similarity(expected_query, actual_query),
        endpoint=float(expected_endpoint == actual_endpoint),
        target=_token_set_similarity(expected_targets, actual_targets),
        options=_token_set_similarity(expected_options, actual_options),
    )


def _token_set_similarity(expected: tuple[str, ...], actual: tuple[str, ...]) -> float:
    """Return Jaccard similarity, treating two empty query components as equal."""
    expected_tokens = set(expected)
    actual_tokens = set(actual)
    if not expected_tokens and not actual_tokens:
        return 1.0
    return len(expected_tokens & actual_tokens) / len(expected_tokens | actual_tokens)


_LOCKED_QUERY_BOOLEAN_OPTIONS = frozenset({"--broken", "--exclude-tests", "--with-imports"})
_LOCKED_QUERY_VALUE_OPTIONS = frozenset({"--limit", "--top"})


def _split_normalized_query(query: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Separate a normalized query into endpoint, positional targets, and option groups."""
    endpoint = query[0]
    targets: list[str] = []
    options: list[str] = []
    index = 1
    while index < len(query):
        token = query[index]
        if token in _LOCKED_QUERY_BOOLEAN_OPTIONS:
            options.append(token)
        elif token in _LOCKED_QUERY_VALUE_OPTIONS:
            options.append(f"{token}={query[index + 1]}")
            index += 1
        else:
            targets.append(token)
        index += 1
    return endpoint, tuple(targets), tuple(options)


def _normalize_locked_query(command: str, arguments: list[str]) -> tuple[str, ...] | None:
    """Canonicalize the locked query grammar without weakening task semantics.

    Positional arguments retain their order.  Only the registered boolean
    options may move, and ``--limit``/``--top`` accept one non-negative decimal value.
    Unknown, duplicate, missing-value, and extra option tokens are rejected.
    """
    if not command or not isinstance(command, str):
        return None
    positionals: list[str] = []
    booleans: set[str] = set()
    values: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if not isinstance(argument, str) or not argument:
            return None
        if argument in _LOCKED_QUERY_BOOLEAN_OPTIONS:
            if argument in booleans:
                return None
            booleans.add(argument)
        elif argument in _LOCKED_QUERY_VALUE_OPTIONS:
            if argument in values or index + 1 >= len(arguments):
                return None
            value = arguments[index + 1]
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
                return None
            values[argument] = str(int(value))
            index += 1
        elif argument.startswith("-"):
            return None
        else:
            positionals.append(argument)
        index += 1
    normalized = [command, *positionals, *sorted(booleans)]
    for option, value in sorted(values.items()):
        normalized.extend((option, value))
    return tuple(normalized)


def _pooling_ineligibility_reasons(run: CodexRun) -> tuple[str, ...]:
    """Return run-level admission failures that forbid canonical pooling.

    Unscoreable diagnostic cells are intentionally absent: they are planned
    exclusions, unlike incomplete, contaminated, malformed-token, and
    required-use-invalid results.
    """
    reasons: list[str] = []
    if not run.success:
        reasons.append("unsuccessful")
    if run.incomplete:
        reasons.append("incomplete")
    if run.extraction_failed:
        reasons.append("extraction_failed")
    if run.contaminated:
        reasons.append("contaminated")
    if run.token_accounting_inconsistent:
        reasons.append("token_accounting_inconsistent")
    if run.targeted:
        reasons.append("targeted")
    if run.diagnostic_only:
        reasons.append("diagnostic_only")
    if run.arm in {"B_direct_required", "C_skill_required"} and run.compliance is not True:
        reasons.append("required_use_missing")
    return tuple(reasons)


def _infrastructure_failure_signature(run: CodexRun) -> str | None:
    """Return a recurrence key only for pre-response runner/provider failures."""
    if run.success or not run.incomplete or run.input_tokens or run.output_tokens or run.output_text.strip():
        return None
    if run.error_type == "authentication_failed":
        return "authentication_failed"
    if run.error_type not in {
        "authentication_state_failed",
        "launch_os_error",
        "missing_terminal",
        "non_zero_exit",
        "response_failed",
        "transport_error",
        "turn_failed",
    }:
        return None
    normalized = run.error.casefold()
    http_class = re.search(r"\b([45])\d\d\b", normalized)
    return f"{run.error_type}:http_{http_class.group(1)}xx" if http_class else run.error_type


@lru_cache(maxsize=1)
def _reference_bench_module() -> Any:
    """Load the Claude reference module once to reuse its exact evaluator registry."""
    module_path = Path(__file__).with_name("run-claude-structural.py")
    spec = importlib.util.spec_from_file_location("_codex_shared_bench_reference", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load shared evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _diff_impact_stager(repo_path: Path, task: Mapping[str, Any]) -> Any | None:
    """Return the shared Claude stager for one DI task, or ``None``."""
    if task.get("type") != "diff_impact":
        return None
    stage_spec = task.get("stage")
    if not isinstance(stage_spec, list) or not stage_spec:
        return None
    return _reference_bench_module().DiffImpactStager(repo_path, stage_spec)


def _validate_diff_impact_stage(repo_path: Path, task: Mapping[str, Any]) -> None:
    """Validate every DI anchor without mutating the target tree."""
    stager = _diff_impact_stager(repo_path, task)
    if stager is None:
        return
    stager._assert_clean()
    for edit in stager.stage_spec:
        if not isinstance(edit, Mapping) or not isinstance(edit.get("file"), str):
            raise ValueError(f"invalid DI stage edit for {task.get('id', '<unknown>')}")
        path = repo_path / str(edit["file"])
        if not path.is_file():
            raise ValueError(f"DI stage anchor file is unavailable: {edit['file']}")
        text = path.read_text(encoding="utf-8")
        if "append" in edit:
            continue
        if "find" not in edit or "replace" not in edit or str(edit["find"]) not in text:
            raise ValueError(f"DI stage anchor is stale: {edit['file']}")


def _default_evaluator(task: Mapping[str, Any], output_text: str) -> EvaluationResult:
    """Invoke the exact evaluator registry used by the Claude reference adapter."""
    return _reference_bench_module()._SHARED_EVALUATORS.evaluate(task, output_text)


def _evaluator_identity(task: Mapping[str, Any], evaluator: Callable[..., Any]) -> tuple[str, str]:
    """Return the shared evaluator ID/hash, or deterministic fixture provenance."""
    if evaluator is _default_evaluator:
        return _reference_bench_module()._evaluator_provenance(task)
    identifier = getattr(evaluator, "__name__", evaluator.__class__.__name__)
    try:
        source = inspect.getsource(evaluator)
    except (OSError, TypeError):
        source = identifier
    return identifier, hashlib.sha256((identifier + "\n" + source).encode("utf-8")).hexdigest()


class CodexRunner:
    """Run one canonical Codex cell with injectable process/evaluator seams."""

    def __init__(
        self,
        model: str,
        repo_path: Path,
        *,
        reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
        index_path: Path | None = None,
        timeout: float = PARITY_TIMEOUT_SECONDS,
        marketplace_root: Path | None = None,
        codemap_bin: Path | None = None,
        manifest_path: Path = PARITY_MANIFEST_PATH,
        auth_source: Path | None = None,
        plugin_installer: Callable[[Path], bool | None] | None = None,
        plugin_probe: Callable[[Path], bool] | None = None,
        targeted: bool = False,
        command_runner: Callable[..., Any] | None = None,
        transport: Callable[..., str | bytes | Iterable[str | bytes]] | None = None,
        evaluator: Callable[[Mapping[str, Any], str], EvaluationResult] | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.repo_path = Path(repo_path).resolve()
        self.index_path = _canonical_index_path(Path(index_path)) if index_path else None
        self.timeout = timeout
        self.marketplace_root = marketplace_root.resolve() if marketplace_root else None
        self.codemap_bin = Path(codemap_bin) if codemap_bin else None
        self.manifest_path = Path(manifest_path)
        # Preserve the caller-supplied path so `_copy_auth_source` can reject a
        # symlink instead of silently dereferencing it during normalization.
        self.auth_source = Path(auth_source) if auth_source else None
        self.plugin_installer = plugin_installer
        self.plugin_probe = plugin_probe
        self.targeted = targeted
        self.command_runner = command_runner
        self.transport = transport
        self.evaluator = evaluator or _default_evaluator
        self._auth_state: _RunAuthState | None = None
        self._auth_state_dir: Path | None = None

    def _ensure_auth_state(self) -> _RunAuthState | None:
        """Lazily seed the private credential chain for this runner."""
        if self.auth_source is None:
            return None
        if self._auth_state is None:
            self._auth_state = _RunAuthState(self.auth_source)
            self._auth_state_dir = self._auth_state.directory
        return self._auth_state

    def close(self) -> None:
        """Remove the runner-owned private credential chain."""
        if self._auth_state is not None:
            self._auth_state.close()

    def build_command(self, prompt: str) -> list[str]:
        """Build this runner's canonical Codex command."""
        return build_codex_command(
            self.repo_path,
            self.model,
            prompt,
            reasoning_effort=self.reasoning_effort,
        )

    def _prepare_verified_home(
        self,
        arm: str,
        *,
        diff_impact_stage: DiffImpactStageAdmission | None = None,
    ) -> ArmHome:
        """Create and verify one arm home without invoking a model."""
        _validate_locked_runtime(
            self.repo_path,
            self.index_path,
            arm,
            self.manifest_path,
            diff_impact_stage,
        )
        auth_state = self._ensure_auth_state()
        if auth_state is not None:
            auth_state.assert_source_unchanged()
        home = prepare_arm_home(
            arm,
            auth_source=None,
            codemap_bin=self.codemap_bin,
            plugin_installer=self.plugin_installer,
        )
        try:
            if auth_state is not None:
                auth_state.seed_home(home.path)
                home.auth_provisioned = True
            if arm != "A_plain" and self.index_path is not None:
                home.env["CODEMAP_PYTHON"] = _verify_locked_codemap_python(
                    manifest_path=self.manifest_path,
                    command_runner=self.command_runner,
                )
                home.env["SCAN_NO_AUTOBUILD"] = "1"
                home.env["CODEMAP_LOGGING"] = "false"
                home.env["CODEX_CODEMAP_AVAILABLE"] = "1"
                home.coordination_path = _prepare_coordination_root(self.index_path)
            else:
                for variable in (
                    "CODEMAP_BIN",
                    "CODEMAP_INDEX",
                    "CODEMAP_INDEX_DIR",
                    "CODEMAP_PYTHON",
                    "CODEMAP_SKILL_FILE",
                    "SCAN_NO_AUTOBUILD",
                    "CODEMAP_LOGGING",
                ):
                    home.env.pop(variable, None)
            if arm == "C_skill_required":
                if self.plugin_probe is not None:
                    home.codemap_verified = bool(self.plugin_probe(home.path))
                elif not home.codemap_verified:
                    home.codemap_verified = _install_codemap_plugin(
                        home,
                        self.marketplace_root,
                        command_runner=self.command_runner,
                    )
            if arm != "A_plain":
                if not home.codemap_verified:
                    raise RuntimeError("Codemap delivery is not verified")
                home.codemap_available = True
                _verify_treatment_artifact_locks(home, self.manifest_path)
            if arm == "C_skill_required" and (
                home.codemap_skill_path is None
                or not home.codemap_skill_sha256
                or home.codex_rig_path is None
                or not home.codex_rig_manifest_sha256
            ):
                raise RuntimeError("installed Codemap skill and Codex Rig are not verified")
            if arm == "C_skill_required":
                if self.index_path is None:
                    raise ValueError("C_skill_required admission requires the locked index")
                _admit_installed_skill_pair(
                    home,
                    self.repo_path,
                    self.index_path,
                    manifest_path=self.manifest_path,
                    command_runner=self.command_runner,
                )
            _write_permission_config(
                home,
                arm,
                self.index_path,
                marketplace_root=self.marketplace_root,
            )
            if arm == "C_skill_required":
                _verify_installed_plugin_pair(home, command_runner=self.command_runner)
            _verify_permission_profile(
                home,
                self.repo_path,
                self.index_path,
                command_runner=self.command_runner,
            )
            if arm == "B_direct_required":
                if self.index_path is None:
                    raise ValueError("B_direct_required admission requires the locked index")
                _admit_staged_direct_cli(
                    home,
                    self.repo_path,
                    self.index_path,
                    manifest_path=self.manifest_path,
                    command_runner=self.command_runner,
                )
            if home.auth_provisioned:
                _verify_authentication(home, command_runner=self.command_runner)
                if auth_state is not None:
                    auth_state.refresh_from_home(home.path)
            if arm == "A_plain":
                _verify_plain_plugin_absent(home, command_runner=self.command_runner)
        except BaseException:
            if home.coordination_path is not None:
                with contextlib.suppress(ValueError):
                    _cleanup_coordination_root(home.coordination_path)
            home.cleanup()
            raise
        return home

    def _preflight_expected_queries(
        self,
        home: ArmHome,
        tasks: Iterable[Mapping[str, Any]],
    ) -> None:
        """Run every locked B/C expected query and fail closed on drift."""
        if home.arm == "A_plain":
            return
        if home.codemap_launcher_path is None or self.index_path is None:
            raise RuntimeError(f"{home.arm} query preflight lacks a locked launcher/index")
        before = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        profile = home.permission_profile or _CODEMAP_PERMISSION_PROFILE
        for task in tasks:
            task_id = str(task.get("id", "unknown"))
            expected = task.get("expected_queries")
            if not isinstance(expected, list) or not expected:
                raise RuntimeError(f"{home.arm} task {task_id} has no structured expected_queries")
            for query in expected:
                if not isinstance(query, Mapping) or not isinstance(query.get("cmd"), str):
                    raise RuntimeError(f"{home.arm} task {task_id} has malformed expected query")
                args = query.get("args", [])
                if not isinstance(args, list) or not all(isinstance(value, str) for value in args):
                    raise RuntimeError(f"{home.arm} task {task_id} has malformed expected query args")
                command = [
                    _CODEX_BIN,
                    "sandbox",
                    "-P",
                    profile,
                    "--include-managed-config",
                    "-C",
                    str(self.repo_path),
                    "--",
                    str(home.codemap_launcher_path),
                    "query",
                    "--compact",
                    str(query["cmd"]),
                    *args,
                ]
                code, stdout, stderr = _invoke_plugin_command(
                    command,
                    home.env,
                    self.command_runner,
                    cwd=self.repo_path,
                )
                if code != 0 or not _canonical_query_output({"aggregated_output": stdout}):
                    detail = stderr.strip() or stdout.strip()
                    raise RuntimeError(f"{home.arm} expected query failed for {task_id}: {detail[:300]}")
                after = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
                if after != before:
                    raise RuntimeError(f"{home.arm} expected query mutated the locked index for {task_id}")

    def preflight_expected_queries(self, tasks: Iterable[Mapping[str, Any]], arms: Iterable[str]) -> None:
        """Perform complete no-model structured-query admission for B/C."""
        task_list = list(tasks)
        for arm in arms:
            if arm == "A_plain":
                continue
            home = self._prepare_verified_home(arm)
            try:
                self._preflight_expected_queries(home, task_list)
            finally:
                if home.coordination_path is not None:
                    with contextlib.suppress(ValueError):
                        _cleanup_coordination_root(home.coordination_path)
                home.cleanup()

    def create_input_snapshot(
        self,
        run_dir: Path,
        *,
        tasks_path: Path,
        manifest_path: Path,
        invocation_launcher_path: Path | None = None,
        tasks: Iterable[Mapping[str, Any]],
        arms: Iterable[str],
    ) -> dict[str, Any]:
        """Archive launch inputs and verified B/C package bytes before paid calls."""
        snapshot_root = Path(run_dir) / "inputs"
        if snapshot_root.exists():
            raise FileExistsError(snapshot_root)
        task_list = list(tasks)
        homes: list[ArmHome] = []
        arm_archives: dict[str, dict[str, Path]] = {}
        arm_files: dict[str, dict[str, Path]] = {}
        try:
            for arm in arms:
                home = self._prepare_verified_home(arm)
                homes.append(home)
                arm_files[arm] = {"config.toml": home.path / "config.toml"}
                if arm == "B_direct_required":
                    arm_archives[arm] = {"direct-cli": home.path / "direct-cli"}
                elif arm == "C_skill_required":
                    if home.codemap_plugin_path is None or home.codex_rig_path is None:
                        raise RuntimeError("C_skill_required package roots are not verified")
                    arm_archives[arm] = {
                        "codemap-py": home.codemap_plugin_path,
                        "codex-rig": home.codex_rig_path,
                    }
                    if home.codemap_context_path is not None:
                        arm_files[arm]["codemap-context.json"] = home.codemap_context_path
                self._preflight_expected_queries(home, task_list)
            return _write_input_snapshot(
                snapshot_root,
                manifest_path=manifest_path,
                tasks_path=tasks_path,
                runner_path=Path(__file__),
                invocation_launcher_path=invocation_launcher_path,
                index_path=self.index_path,
                auth_source=self.auth_source,
                arm_archives=arm_archives,
                arm_files=arm_files,
            )
        finally:
            for home in homes:
                if home.coordination_path is not None:
                    with contextlib.suppress(ValueError):
                        _cleanup_coordination_root(home.coordination_path)
                home.cleanup()

    def probe_arm(
        self,
        arm: str,
        *,
        diff_impact_stage: DiffImpactStageAdmission | None = None,
    ) -> dict[str, Any]:
        """Return no-model runtime and plugin-isolation evidence for one arm."""
        if not _is_known_codex_arm(arm):
            raise ValueError(f"unknown benchmark arm {arm!r}")
        if diff_impact_stage is None:
            home = self._prepare_verified_home(arm)
        else:
            home = self._prepare_verified_home(arm, diff_impact_stage=diff_impact_stage)
        try:
            return probe_arm_home(home)
        finally:
            try:
                if home.coordination_path is not None:
                    _cleanup_coordination_root(home.coordination_path)
            finally:
                home.cleanup()

    def preflight_diff_impact_stages(self, tasks: Iterable[Mapping[str, Any]], arms: Iterable[str]) -> None:
        """Exercise DI staging, exact admission, and strict restoration without a model."""
        selected_arms = tuple(arms)
        for task in tasks:
            stager = _diff_impact_stager(self.repo_path, task)
            if stager is None:
                continue
            _validate_locked_runtime(self.repo_path, self.index_path, "A_plain", self.manifest_path)
            entered = False
            try:
                stager.__enter__()
                entered = True
                admission = _capture_diff_impact_stage(self.repo_path, task)
                for arm in selected_arms:
                    home = self._prepare_verified_home(arm, diff_impact_stage=admission)
                    try:
                        _validate_locked_runtime(
                            self.repo_path,
                            self.index_path,
                            arm,
                            self.manifest_path,
                            admission,
                        )
                    finally:
                        try:
                            if home.coordination_path is not None:
                                _cleanup_coordination_root(home.coordination_path)
                        finally:
                            home.cleanup()
            finally:
                try:
                    if entered:
                        stager.__exit__(*sys.exc_info())
                finally:
                    _validate_locked_runtime(self.repo_path, self.index_path, "A_plain", self.manifest_path)

    def run(
        self,
        task: Mapping[str, Any],
        arm: str,
        *,
        repetition: int = 1,
        deadline: float | None = None,
        diff_impact_stage: DiffImpactStageAdmission | None = None,
    ) -> CodexRun:
        """Execute one task cell within a retry-inclusive coordinate deadline."""
        if not _is_known_codex_arm(arm):
            raise ValueError(f"unknown benchmark arm {arm!r}")
        if repetition < 1:
            raise ValueError("repetition must be a positive integer")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task requires a non-empty id")
        is_diff_impact = task.get("type") == "diff_impact"
        if is_diff_impact and diff_impact_stage is None:
            raise ValueError("canonical Codex DI run requires an admitted staged worktree")
        if not is_diff_impact and diff_impact_stage is not None:
            raise ValueError("canonical Codex non-DI run cannot admit a staged worktree")
        prompt = materialize_task_prompt(_raw_task(task))
        envelope = _arm_envelope(arm)
        command_prompt = envelope + "\n\n" + prompt
        metadata = task.get(_PROVENANCE_KEY, {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        run = CodexRun(
            arm,
            task_id,
            str(task.get("type", "unknown")),
            self.model,
            reasoning_effort=self.reasoning_effort,
            repetition=repetition,
            targeted=self.targeted,
            study_mode="targeted" if self.targeted else "confirmatory",
        )
        run.parity_arm = arm
        run.cell_wall_clock_limit_s = self.timeout
        run.capability_strata = capability_strata(_raw_task(task))
        run.arm_contract_hash = _arm_contract_hash(arm)
        raw_hash = _raw_task_hash(task)
        expected_hash = metadata.get("task_hash", task.get("task_hash"))
        raw_prompt_hash = prompt_hash(_raw_task(task))
        expected_prompt_hash = metadata.get("prompt_hash", task.get("prompt_hash"))
        if metadata and metadata.get("task_hash") != raw_hash:
            raise ValueError(f"task hash mismatch for {task_id!r}")
        if metadata and metadata.get("prompt_hash") != raw_prompt_hash:
            raise ValueError(f"prompt hash mismatch for {task_id!r}")
        # ``load_tasks_with_provenance`` already verifies these values against
        # the locked manifest.  Trusting the precomputed fields here avoids
        # hashing an enriched projection (which is not canonical task bytes).
        run.task_hash = str(expected_hash or raw_hash)
        run.prompt_hash = str(expected_prompt_hash or raw_prompt_hash)
        run.suite_hash = str(metadata.get("suite_hash", task.get("suite_hash", "")))
        run.suite_raw_hash = str(metadata.get("suite_raw_hash", task.get("suite_raw_hash", "")))
        run.experiment_revision = str(metadata.get("experiment_revision", task.get("experiment_revision", "")))
        run.oracle_class = str(metadata.get("oracle_class", task.get("oracle_class", "unknown")))
        run.headline_eligible_v1 = bool(metadata.get("headline_eligible_v1", task.get("headline_eligible_v1", False)))
        run.repo_sha = _repo_sha(self.repo_path)
        run.index_sha = _index_sha(self.index_path)
        explicit_evaluator_id = metadata.get("evaluator_id", task.get("evaluator_id"))
        explicit_evaluator_hash = metadata.get("evaluator_hash", task.get("evaluator_hash"))
        if explicit_evaluator_id and explicit_evaluator_hash:
            run.evaluator_id = str(explicit_evaluator_id)
            run.evaluator_hash = str(explicit_evaluator_hash)
        else:
            run.evaluator_id, run.evaluator_hash = _evaluator_identity(_raw_task(task), self.evaluator)
        run.envelope_hash = hashlib.sha256(envelope.encode()).hexdigest()
        run.scoreable = metadata.get("scoreable", task.get("scoreable", True)) is not False
        home: ArmHome | None = None
        if diff_impact_stage is not None:
            _validate_locked_runtime(
                self.repo_path,
                self.index_path,
                arm,
                self.manifest_path,
                diff_impact_stage,
            )
        if self.transport is None:
            if diff_impact_stage is None:
                home = self._prepare_verified_home(arm)
            else:
                home = self._prepare_verified_home(arm, diff_impact_stage=diff_impact_stage)
        started_at = time.monotonic()
        coordinate_deadline = started_at + self.timeout
        if deadline is not None:
            coordinate_deadline = min(coordinate_deadline, deadline)
        attempt_events: list[list[dict[str, Any]]] = []
        parsed = CodexParseResult()
        postflight_error = ""
        auth_state_error = ""
        command = self.build_command(command_prompt)
        try:
            for attempt in range(3):
                remaining_s = coordinate_deadline - time.monotonic()
                if remaining_s <= 0:
                    parsed = CodexParseResult(
                        incomplete=True,
                        error=f"cell wall-clock budget exhausted ({self.timeout}s total)",
                        error_type="cell_timeout",
                    )
                    break
                run.retry_count = attempt
                if self.transport is None:
                    assert home is not None
                    stream = self._subprocess(command, home.env, timeout=remaining_s)
                else:
                    stream = self.transport(command, arm=arm)
                parsed = parse_codex_jsonl(
                    stream,
                    launcher_path=home.codemap_launcher_path if home is not None else None,
                    skill_path=home.codemap_skill_path if home is not None else None,
                    skill_sha256=home.codemap_skill_sha256 if home is not None else "",
                )
                attempt_events.append(parsed.raw_events)
                if home is not None or diff_impact_stage is not None:
                    try:
                        _validate_locked_runtime(
                            self.repo_path,
                            self.index_path,
                            arm,
                            self.manifest_path,
                            diff_impact_stage,
                        )
                        if home is not None and home.coordination_path is not None:
                            _validate_coordination_root(home.coordination_path)
                    except ValueError as exc:
                        postflight_error = str(exc)
                        parsed.completed = False
                        parsed.incomplete = True
                        parsed.error = f"runtime contamination: {postflight_error}"
                        parsed.error_type = "runtime_contamination"
                        parsed.retryable = False
                        break
                zero_token_transport_failure = (
                    parsed.input_tokens == 0
                    and parsed.output_tokens == 0
                    and not parsed.output_text.strip()
                    and parsed.retryable
                )
                if not zero_token_transport_failure or attempt == 2:
                    break
        finally:
            run.elapsed_s = time.monotonic() - started_at
            if home is not None:
                if self._auth_state is not None and home.auth_provisioned:
                    try:
                        self._auth_state.refresh_from_home(home.path)
                    except (RuntimeError, ValueError) as exc:
                        auth_state_error = str(exc)
                if home.coordination_path is not None:
                    try:
                        _cleanup_coordination_root(home.coordination_path)
                    except ValueError as exc:
                        postflight_error = postflight_error or str(exc)
                home.cleanup()
        run.thread_id = parsed.thread_id
        run.output_text = parsed.output_text
        run.raw_events = parsed.raw_events
        run.native_attempt_events = attempt_events
        run.native_item_counts = parsed.item_counts
        run.tool_elapsed_s = parsed.tool_elapsed_s
        run.tool_result_tokens = parsed.tool_result_tokens
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "command_calls",
            "codemap_calls",
            "codemap_successful_calls",
            "codemap_compact_successful_calls",
            "codemap_direct_calls",
            "codemap_direct_successful_calls",
            "codemap_direct_compact_successful_calls",
            "codemap_skill_calls",
            "codemap_skill_successful_calls",
            "codemap_skill_compact_successful_calls",
            "skill_delivery_observed",
            "codemap_errors",
            "fallback_calls",
            "successful_query_arguments",
        ):
            setattr(run, field_name, getattr(parsed, field_name))
        run.success = parsed.success
        run.incomplete = parsed.incomplete
        run.error = parsed.error
        run.error_type = parsed.error_type
        run.compliance = _arm_compliance(arm, run)
        run.locked_query_conformance = _locked_query_conformance(task, arm, run)
        locked_query_fitness = _locked_query_fitness(task, arm, run)
        if locked_query_fitness is not None:
            run.locked_query_fitness = locked_query_fitness.overall
            run.locked_query_endpoint_fitness = locked_query_fitness.endpoint
            run.locked_query_target_fitness = locked_query_fitness.target
            run.locked_query_option_fitness = locked_query_fitness.options
        if arm == "B_direct_required" and run.compliance:
            run.codemap_delivery = "direct_cli"
        elif arm == "C_skill_required" and run.compliance:
            run.codemap_delivery = "installed_skill"
        run.contaminated = bool(postflight_error) or (arm == "A_plain" and run.codemap_calls > 0)
        run.treatment_adherence = treatment_adherence(
            arm,
            codemap_use_compliance=run.compliance,
            contaminated=run.contaminated,
        )
        run.token_accounting_inconsistent = token_accounting_inconsistent(run.input_tokens, run.cached_input_tokens)
        run.fresh_input_tokens = fresh_input_tokens(run.input_tokens, run.cached_input_tokens)
        if postflight_error:
            run.incomplete = True
            run.error = f"runtime contamination: {postflight_error}"
            run.error_type = "runtime_contamination"
            run.success = False
        if auth_state_error:
            run.incomplete = True
            run.error = "run auth state could not be refreshed"
            run.error_type = "authentication_state_failed"
            run.success = False
        if run.contaminated and not run.error:
            run.error = "contaminated"
            run.success = False
        if run.scoreable and not run.incomplete:
            evaluation = self.evaluator(_raw_task(task), run.output_text)
            run.quality_score = evaluation.quality_score
            run.quality_components = evaluation.components
            run.correct = evaluation.correct
            run.extraction_failed = evaluation.extraction_failed
        return run

    def _subprocess(
        self,
        command: list[str],
        env: Mapping[str, str],
        *,
        timeout: float | None = None,
    ) -> str:
        """Run one Codex attempt within the coordinate's remaining budget."""
        attempt_timeout = self.timeout if timeout is None else timeout
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_path,
                env=dict(env),
                capture_output=True,
                text=True,
                timeout=attempt_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "type": "error",
                    "error": f"timeout ({attempt_timeout}s)",
                    "error_type": "timeout",
                }
            )
        except OSError as exc:
            return json.dumps(
                {
                    "type": "error",
                    "error": f"Codex launch failed: {exc.strerror or type(exc).__name__}",
                    "error_type": "launch_os_error",
                }
            )
        if completed.returncode != 0:
            terminal = json.dumps(
                {
                    "type": "error",
                    "error": completed.stderr.strip()[:300] or f"non-zero exit {completed.returncode}",
                    "error_type": "non_zero_exit",
                }
            )
            return (completed.stdout + "\n" + terminal).lstrip()
        return completed.stdout


def _arm_envelope(arm: str) -> str:
    """Return arm-only tool availability instructions."""
    if arm == "A_plain":
        return "Codemap is absent and inaccessible. Use ordinary provider tools only; do not invoke Codemap."
    if arm == "B_direct_required":
        return (
            "Codemap is available only through the direct CLI. Before answering, complete a dedicated native "
            'command item of the exact form "$CODEMAP_BIN" query --compact <subcommand> <arguments>. '
            "It must exit 0 and emit one JSON document whose index.query_complete and index.compact are true. "
            "Additional reads and shell work are allowed only as separate native items and are ignored for credit."
        )
    if arm == "C_skill_required":
        return (
            "Codemap's installed $codemap-py:query-code Skill is available through the runner-owned immutable "
            "CODEMAP_SKILL_FILE binding. Before the canonical query, complete a separate dedicated native item whose "
            'exact command is cat "$CODEMAP_SKILL_FILE". Then complete a dedicated '
            'native command item of the exact form "$CODEMAP_BIN" query --compact <subcommand> <arguments> with '
            "exit 0 and one JSON document whose index.query_complete and index.compact are true. Additional reads "
            "and shell work are allowed only as separate native items and are ignored for credit."
        )
    raise ValueError(f"unknown benchmark arm {arm!r}")


def _append_run(output_path: Path, run: CodexRun, *, execution_index: int) -> None:
    """Append one completed cell so later failures cannot erase smoke evidence."""
    if execution_index < 0:
        raise ValueError("execution_index must be non-negative")
    run.execution_index = execution_index
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(run), sort_keys=True) + "\n")


def _canonical_telemetry_path(output_path: Path) -> Path:
    """Return the derived canonical-order sidecar path for raw telemetry."""
    return output_path.with_name("telemetry-canonical.jsonl")


def _write_canonical_telemetry(
    output_path: Path,
    canonical_path: Path,
    *,
    task_order: tuple[str, ...],
) -> str:
    """Atomically publish a canonical sidecar without rewriting raw execution evidence."""
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_rows = canonical_result_rows(
        rows,
        task_order=task_order,
        arm_order=CODEX_STRUCTURAL_ARMS,
    )
    serialized = "".join(json.dumps(row, sort_keys=True) + "\n" for row in canonical_rows).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        dir=canonical_path.parent, prefix=f".{canonical_path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(serialized)
    try:
        os.replace(temporary, canonical_path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(serialized).hexdigest()


def _utc_now() -> str:
    """Return one stable UTC timestamp for run-level evidence."""
    return datetime.now(timezone.utc).isoformat()


def _write_run_metadata(metadata_path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically persist run provenance so interruptions retain the last completed cell."""
    serialized = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        dir=metadata_path.parent, prefix=f".{metadata_path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(serialized)
    try:
        os.replace(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)


def _close_runner(runner: Any) -> None:
    """Close optional private runner state without constraining fixture runners."""
    close = getattr(runner, "close", None)
    if callable(close):
        close()


def _regular_file_within(path: Path, root: Path, *, description: str) -> Path:
    """Resolve one immutable rescore input while rejecting links and scope escapes."""
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"offline rescore {description} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not resolved.is_relative_to(root):
        raise ValueError(f"offline rescore {description} escaped the run directory")
    return resolved


def _load_frozen_rescore_inputs(
    run_dir: Path,
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], Path, Path, str]:
    """Load all hash-verified inputs needed to replay one completed run."""
    root = run_dir.resolve(strict=True)
    metadata_candidates = sorted(root.glob("*metadata.json"))
    if len(metadata_candidates) != 1:
        raise ValueError("offline rescore requires exactly one run metadata JSON file")
    metadata_path = _regular_file_within(metadata_candidates[0], root, description="metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("offline rescore metadata is not valid JSON") from exc
    if not isinstance(metadata, dict) or metadata.get("schema_version") not in {
        "codex-structural-run-metadata-v1",
        "codex-structural-run-metadata-v2",
    }:
        raise ValueError("offline rescore metadata schema is unsupported")
    if metadata.get("status") != "completed":
        raise ValueError("offline rescore requires completed run metadata")
    artifacts = metadata.get("artifacts")
    inputs = metadata.get("inputs")
    if not isinstance(artifacts, Mapping) or not isinstance(inputs, Mapping):
        raise ValueError("offline rescore metadata lacks artifact or input provenance")
    telemetry_raw = artifacts.get("telemetry_jsonl")
    snapshot = inputs.get("snapshot")
    if not isinstance(telemetry_raw, str) or not isinstance(snapshot, Mapping):
        raise ValueError("offline rescore metadata lacks frozen telemetry or snapshot")
    telemetry_recorded = Path(telemetry_raw)
    if telemetry_recorded.name != "telemetry.jsonl":
        raise ValueError("offline rescore telemetry provenance has an unexpected name")
    telemetry_path = _regular_file_within(root / telemetry_recorded.name, root, description="telemetry")
    telemetry_bytes = telemetry_path.read_bytes()
    expected_telemetry_hash = artifacts.get("telemetry_sha256")
    if (
        not isinstance(expected_telemetry_hash, str)
        or hashlib.sha256(telemetry_bytes).hexdigest() != expected_telemetry_hash
    ):
        raise ValueError("offline rescore telemetry hash mismatch")
    snapshot_raw = snapshot.get("path")
    snapshot_hash = snapshot.get("sha256")
    if not isinstance(snapshot_raw, str) or not isinstance(snapshot_hash, str):
        raise ValueError("offline rescore snapshot provenance is incomplete")
    snapshot_recorded = Path(snapshot_raw)
    if snapshot_recorded.name != "input-snapshot.json":
        raise ValueError("offline rescore snapshot provenance has an unexpected name")
    snapshot_path = _regular_file_within(
        root / "inputs" / snapshot_recorded.name,
        root,
        description="input snapshot",
    )
    snapshot_bytes = snapshot_path.read_bytes()
    if hashlib.sha256(snapshot_bytes).hexdigest() != snapshot_hash:
        raise ValueError("offline rescore input snapshot hash mismatch")
    try:
        snapshot_payload = json.loads(snapshot_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("offline rescore input snapshot is not valid JSON") from exc
    if (
        not isinstance(snapshot_payload, Mapping)
        or snapshot_payload.get("schema_version") != "codex-structural-input-snapshot-v1"
    ):
        raise ValueError("offline rescore input snapshot schema is unsupported")
    files = snapshot_payload.get("files")
    if not isinstance(files, list):
        raise ValueError("offline rescore input snapshot lacks files")
    task_entry = next(
        (entry for entry in files if isinstance(entry, Mapping) and entry.get("role") == "task_suite"), None
    )
    if task_entry is None:
        raise ValueError("offline rescore input snapshot lacks frozen task suite")
    archived_path = task_entry.get("archived_path")
    expected_task_hash = task_entry.get("sha256")
    if not isinstance(archived_path, str) or not isinstance(expected_task_hash, str):
        raise ValueError("offline rescore frozen task suite provenance is incomplete")
    tasks_path = _regular_file_within(root / "inputs" / archived_path, root, description="frozen task suite")
    if hashlib.sha256(tasks_path.read_bytes()).hexdigest() != expected_task_hash:
        raise ValueError("offline rescore frozen task suite hash mismatch")
    treatments = metadata.get("treatments")
    artifact_hashes = treatments.get("artifact_sha256") if isinstance(treatments, Mapping) else None
    skill_hash = artifact_hashes.get("codemap_query_skill") if isinstance(artifact_hashes, Mapping) else None
    if not isinstance(skill_hash, str) or not skill_hash:
        raise ValueError("offline rescore metadata lacks the frozen Codemap Skill hash")
    skill_entries = [
        entry
        for entry in files
        if isinstance(entry, Mapping)
        and entry.get("role") == "C_skill_required:codemap-py"
        and entry.get("sha256") == skill_hash
        and str(entry.get("archived_path", "")).endswith("/codex-skills/query-code/SKILL.md")
    ]
    if len(skill_entries) != 1:
        raise ValueError("offline rescore snapshot lacks one exact frozen Codemap Skill")
    skill_archived_path = skill_entries[0].get("archived_path")
    if not isinstance(skill_archived_path, str):
        raise ValueError("offline rescore frozen Codemap Skill provenance is incomplete")
    skill_path = _regular_file_within(
        root / "inputs" / skill_archived_path,
        root,
        description="frozen Codemap Skill",
    )
    if hashlib.sha256(skill_path.read_bytes()).hexdigest() != skill_hash:
        raise ValueError("offline rescore frozen Codemap Skill hash mismatch")
    return metadata, telemetry_path, load_task_suite(tasks_path), metadata_path, skill_path, skill_hash


def rescore_results(run_dir: Path) -> Path:
    """Replay frozen raw telemetry and current evaluators into an immutable offline artifact.

    The function accepts only a completed run directory. It never invokes a
    provider, reads credentials, or rewrites raw telemetry, canonical telemetry,
    metadata, or frozen input snapshots.
    """
    root = Path(run_dir).resolve(strict=True)
    metadata, telemetry_path, tasks, metadata_path, skill_path, skill_sha256 = _load_frozen_rescore_inputs(root)
    task_by_id = {str(task["id"]): task for task in tasks}
    execution = metadata.get("execution")
    if not isinstance(execution, Mapping):
        raise ValueError("offline rescore metadata lacks execution scope")
    selected_ids = execution.get("selected_task_ids")
    coordinates = execution.get("coordinates")
    if not isinstance(selected_ids, list) or not all(isinstance(task_id, str) for task_id in selected_ids):
        raise ValueError("offline rescore selected task scope is invalid")
    if set(selected_ids) - task_by_id.keys() or not isinstance(coordinates, list):
        raise ValueError("offline rescore task scope disagrees with frozen suite")
    allowed_coordinates: set[tuple[str, int, str]] = set()
    for coordinate in coordinates:
        if not isinstance(coordinate, Mapping):
            raise ValueError("offline rescore coordinate scope is invalid")
        task_id = coordinate.get("task_id")
        repetition = coordinate.get("repetition")
        arm = coordinate.get("arm")
        if (
            not isinstance(task_id, str)
            or task_id not in selected_ids
            or isinstance(repetition, bool)
            or not isinstance(repetition, int)
            or repetition < 1
            or arm not in CODEX_STRUCTURAL_ARMS
        ):
            raise ValueError("offline rescore coordinate scope is invalid")
        allowed_coordinates.add((task_id, repetition, arm))
    if len(allowed_coordinates) != len(coordinates):
        raise ValueError("offline rescore coordinate scope is invalid")
    telemetry_bytes = telemetry_path.read_bytes()
    source = {
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        "telemetry_sha256": hashlib.sha256(telemetry_bytes).hexdigest(),
        "frozen_suite_semantic_sha256": semantic_suite_hash(tasks),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    rows: list[dict[str, Any]] = []
    seen_coordinates: set[tuple[Any, Any, Any]] = set()
    for line in telemetry_bytes.decode("utf-8").splitlines():
        try:
            raw_row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("offline rescore telemetry is not valid JSONL") from exc
        if not isinstance(raw_row, Mapping):
            raise ValueError("offline rescore telemetry row is not an object")
        task_id = raw_row.get("task_id")
        arm = raw_row.get("arm")
        repetition = raw_row.get("repetition", 1)
        coordinate = (task_id, repetition, arm)
        if (
            not isinstance(task_id, str)
            or task_id not in task_by_id
            or coordinate not in allowed_coordinates
            or coordinate in seen_coordinates
        ):
            raise ValueError("offline rescore telemetry row is outside frozen execution scope")
        raw_events = raw_row.get("raw_events")
        if not isinstance(raw_events, list) or not all(isinstance(event, Mapping) for event in raw_events):
            raise ValueError("offline rescore telemetry row lacks replayable raw events")
        seen_coordinates.add(coordinate)
        parsed = parse_codex_jsonl(
            (json.dumps(event, sort_keys=True) for event in raw_events),
            skill_path=skill_path if arm == "C_skill_required" else None,
            skill_sha256=skill_sha256 if arm == "C_skill_required" else "",
        )
        evaluation = _default_evaluator(task_by_id[task_id], parsed.output_text)
        compliance = _arm_compliance(str(arm), parsed)
        contaminated = arm == "A_plain" and parsed.codemap_calls > 0
        row = {
            "task_id": task_id,
            "repetition": repetition,
            "arm": arm,
            "output_text": parsed.output_text,
            "success": parsed.success,
            "incomplete": parsed.incomplete,
            "error": parsed.error,
            "error_type": parsed.error_type,
            "quality_score": evaluation.quality_score if evaluation.scored else None,
            "quality_components": evaluation.components,
            "correct": evaluation.correct,
            "extraction_failed": evaluation.extraction_failed,
            "compliance": compliance,
            "locked_query_conformance": _locked_query_conformance(task_by_id[task_id], str(arm), parsed),
            "contaminated": contaminated,
            "treatment_adherence": treatment_adherence(
                str(arm),
                codemap_use_compliance=compliance,
                contaminated=contaminated,
            ),
            "codemap_calls": parsed.codemap_calls,
            "codemap_successful_calls": parsed.codemap_successful_calls,
            "codemap_direct_compact_successful_calls": parsed.codemap_direct_compact_successful_calls,
            "codemap_skill_compact_successful_calls": parsed.codemap_skill_compact_successful_calls,
            "skill_delivery_observed": parsed.skill_delivery_observed,
            "successful_query_arguments": parsed.successful_query_arguments,
            "raw_events_sha256": hashlib.sha256(
                json.dumps(raw_events, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        locked_query_fitness = _locked_query_fitness(task_by_id[task_id], str(arm), parsed)
        row.update(
            {
                "locked_query_fitness": locked_query_fitness.overall if locked_query_fitness is not None else None,
                "locked_query_endpoint_fitness": (
                    locked_query_fitness.endpoint if locked_query_fitness is not None else None
                ),
                "locked_query_target_fitness": locked_query_fitness.target
                if locked_query_fitness is not None
                else None,
                "locked_query_option_fitness": locked_query_fitness.options
                if locked_query_fitness is not None
                else None,
            }
        )
        rows.append(row)
    if seen_coordinates != allowed_coordinates:
        raise ValueError("offline rescore telemetry is incomplete for the frozen execution scope")
    payload = {
        "schema_version": "codex-structural-offline-rescore-v2",
        "source": source,
        "rows": rows,
    }
    serialized_without_hash = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    payload["derived_sha256"] = hashlib.sha256(serialized_without_hash).hexdigest()
    serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    artifact_path = root / (f"offline-rescore-v2-{source['telemetry_sha256'][:16]}-{source['runner_sha256'][:16]}.json")
    if artifact_path.exists():
        if artifact_path.read_bytes() != serialized:
            raise ValueError("offline rescore artifact already exists with different derived content")
        return artifact_path
    with artifact_path.open("x", encoding="utf-8") as handle:
        handle.write(serialized.decode("utf-8"))
    return artifact_path


def _initial_run_metadata(
    *,
    manifest_path: Path,
    repo_path: Path,
    index_path: Path | None,
    output_path: Path,
    metadata_path: Path,
    model: str,
    reasoning_effort: str,
    repetitions: int,
    task_arms: Mapping[tuple[str, int], tuple[str, ...]],
    max_wall_clock_seconds: float,
    auth_provisioned: bool,
    input_snapshot: Mapping[str, Any] | None = None,
    study_mode: str = "confirmatory",
    targeted_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete non-secret provenance for one paid structural run."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scope = dict(targeted_scope) if targeted_scope is not None else None
    coordinates = [
        {"task_id": task_id, "repetition": repetition, "arm": arm}
        for (task_id, repetition), arms in task_arms.items()
        for arm in arms
    ]
    return {
        "schema_version": "codex-structural-run-metadata-v2",
        "status": "running",
        "started_at": _utc_now(),
        "completed_at": None,
        "persisted_cells": 0,
        "cell_outcomes": {
            "successful": 0,
            "unsuccessful": 0,
            "unscoreable": 0,
            "incomplete": 0,
            "extraction_failed": 0,
            "contaminated": 0,
            "compliance_failed": 0,
            "locked_query_nonconforming": 0,
            "targeted": 0,
            "token_accounting_inconsistent": 0,
        },
        "last_persisted_coordinate": None,
        "error": None,
        "auth_provisioned": auth_provisioned,
        "auth_source_recorded": False,
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "experiment_id": manifest["experiment_id"],
            "experiment_revision": manifest["experiment_revision"],
        },
        "execution": {
            "study_mode": study_mode,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "repetitions": repetitions,
            "arms": list(CODEX_STRUCTURAL_ARMS),
            "planned_cells": len(coordinates),
            "selected_task_ids": list(dict.fromkeys(task_id for task_id, _ in task_arms)),
            "targeted_scope": scope,
            "targeted_scope_sha256": scope["scope_sha256"] if scope is not None else None,
            "coordinates": coordinates,
            "cell_wall_clock_seconds": PARITY_TIMEOUT_SECONDS,
            "max_wall_clock_seconds": max_wall_clock_seconds,
            "python": sys.version,
            "codex_cli": manifest["codex_cli"],
        },
        "inputs": {
            "target_path": str(repo_path.resolve()),
            "target": manifest["target_source"],
            "index_path": str(index_path.resolve()) if index_path is not None else None,
            "index_sha256": _index_sha(index_path),
            "index": manifest["index"],
            "suite_integrity": manifest["suite_integrity"],
            "snapshot": dict(input_snapshot) if input_snapshot is not None else None,
        },
        "treatments": {
            "arms": manifest["arms"],
            "package_roster": manifest["package_roster"],
            "codemap_candidate": manifest["codemap_candidate"],
            "codex_rig_candidate": manifest["codex_rig_candidate"],
            "artifact_sha256": manifest["artifact_sha256"],
            "permission_profiles": manifest["codex_permission_profiles"],
            "telemetry_admission": manifest["telemetry_admission"],
        },
        "artifacts": {
            "telemetry_jsonl": str(output_path.resolve()),
            "telemetry_canonical_jsonl": str(_canonical_telemetry_path(output_path).resolve()),
            "canonical_telemetry_status": "not_written",
            "canonical_telemetry_pooling_eligible": False,
            "canonical_telemetry_pooling_ineligibility_reasons": [],
            "run_metadata": str(metadata_path.resolve()),
        },
    }


def main(
    *,
    repo_path: Path,
    model: str,
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
    tasks_path: Path,
    manifest_path: Path = PARITY_MANIFEST_PATH,
    index_path: Path | None = None,
    marketplace_root: Path | None = None,
    codemap_bin: Path | None = None,
    auth_source: Path | None = None,
    invocation_launcher_path: Path | None = None,
    output_path: Path | None = None,
    metadata_path: Path | None = None,
    task_ids: list[str] | None = None,
    task_selectors: str | Sequence[str] | None = None,
    scope_sha256: str | None = None,
    repetitions: int | None = None,
    arm: str = "all",
    dry_run: bool = False,
    max_wall_clock_seconds: float | None = None,
    show_legend: bool = True,
) -> None:
    """Validate and plan cells; paid execution also requires a total deadline."""
    _validate_codex_stratum(model, reasoning_effort)
    if task_ids and task_selectors is not None:
        raise ValueError("--task-id and --tasks cannot be combined")
    targeted_scope = resolve_task_selection(Path(manifest_path), task_selectors) if task_selectors is not None else None
    if targeted_scope is not None:
        task_ids = list(targeted_scope["task_ids"])
        repetitions = targeted_scope["repetitions"] if repetitions is None else repetitions
        max_wall_clock_seconds = (
            targeted_scope["complete_run_max_wall_clock_seconds"]
            if max_wall_clock_seconds is None
            else max_wall_clock_seconds
        )
    repetitions = 1 if repetitions is None else repetitions
    if repetitions < 1:
        raise ValueError("--repetitions must be a positive integer")
    if max_wall_clock_seconds is not None and max_wall_clock_seconds <= 0:
        raise ValueError("--max-wall-clock-seconds must be positive")
    manifest_path = Path(manifest_path)
    if targeted_scope is not None:
        _validate_targeted_scope_request(
            targeted_scope,
            repetitions=repetitions,
            arm=arm,
            max_wall_clock_seconds=max_wall_clock_seconds,
            scope_sha256=scope_sha256,
            dry_run=dry_run,
        )
    _validate_unscoped_paid_task_ids(
        manifest_path,
        task_ids,
        targeted=targeted_scope is not None,
        dry_run=dry_run,
    )
    tasks = load_tasks_with_provenance(tasks_path, manifest_path)
    if not tasks:
        raise ValueError("locked task suite must contain at least one task")
    provenance = tasks[0].get(_PROVENANCE_KEY, {})
    experiment_revision = (
        str(provenance.get("experiment_revision", "")) if isinstance(provenance, Mapping) else ""
    ) or _read_manifest_revision(manifest_path)
    if task_ids:
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("--task-id values must be unique")
        missing = set(task_ids) - {task["id"] for task in tasks}
        if missing:
            raise ValueError(f"unknown locked task IDs: {sorted(missing)}")
        selected_ids = set(task_ids)
        tasks = [task for task in tasks if task["id"] in selected_ids]
    explicit_selection = targeted_scope is not None
    for task in tasks:
        _validate_diff_impact_stage(Path(repo_path), task)
    if not dry_run:
        if output_path is None:
            raise ValueError("non-dry Codex runs require --output-path")
        metadata_path = metadata_path or output_path.with_name(f"{output_path.stem}-metadata.json")
        if output_path.exists():
            raise FileExistsError(output_path)
        if metadata_path.exists():
            raise FileExistsError(metadata_path)
        canonical_path = _canonical_telemetry_path(output_path)
        if canonical_path.exists():
            raise FileExistsError(canonical_path)
        if max_wall_clock_seconds is None:
            raise ValueError("non-dry Codex runs require positive --max-wall-clock-seconds")
        _validate_execution_manifest(manifest_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8"):
            pass
    invocation_launcher_sha256: str | None = None
    if invocation_launcher_path is not None:
        invocation_launcher_path = Path(invocation_launcher_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            invocation_launcher_sha256 = str(manifest["artifact_sha256"]["run_all"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("paid manifest lacks the invocation-launcher lock") from exc
        _validate_invocation_launcher(invocation_launcher_path, invocation_launcher_sha256)
    runner = CodexRunner(
        model,
        repo_path,
        reasoning_effort=reasoning_effort,
        index_path=index_path,
        marketplace_root=marketplace_root,
        codemap_bin=codemap_bin,
        manifest_path=manifest_path,
        auth_source=auth_source,
        targeted=explicit_selection,
    )
    if show_legend:
        render_result_rows(f"{_OUTPUT_LEGEND}\n".splitlines(keepends=True), sys.stdout)
    if dry_run:
        try:
            for selected in ARMS if arm == "all" else (arm,):
                evidence = runner.probe_arm(selected)
                runtime = evidence.get("codemap_python") or "absent"
                print(
                    f"PROBE\t{selected}\tcodemap={str(evidence['codemap_available']).lower()}\tcodemap_python={runtime}"
                )
            selected_arms = ARMS if arm == "all" else (arm,)
            preflight = getattr(runner, "preflight_expected_queries", None)
            if callable(preflight):
                preflight(tasks, selected_arms)
            staged_preflight = getattr(runner, "preflight_diff_impact_stages", None)
            if callable(staged_preflight):
                staged_preflight(tasks, selected_arms)
        finally:
            _close_runner(runner)
    if max_wall_clock_seconds is not None:
        print(
            f"CONTROL\tcell_wall_clock_seconds={PARITY_TIMEOUT_SECONDS:g}"
            f"\tmax_wall_clock_seconds={max_wall_clock_seconds:g}"
        )
    if not dry_run:
        assert output_path is not None
        assert metadata_path is not None
        print(f"ARTIFACTS  telemetry={output_path}  metadata={metadata_path}")
    task_arms = {
        (task["id"], repetition): (
            _manifest_arm_order(
                experiment_revision,
                model,
                task["id"],
                repetition,
                reasoning_effort,
                task_ordinal=(
                    int(task[_PROVENANCE_KEY]["task_ordinal"])
                    if isinstance(task.get(_PROVENANCE_KEY), Mapping)
                    and type(task[_PROVENANCE_KEY].get("task_ordinal")) is int
                    else None
                ),
            )
            if arm == "all"
            else (arm,)
        )
        for task in tasks
        for repetition in range(1, repetitions + 1)
    }
    if dry_run:
        for task in tasks:
            for repetition in range(1, repetitions + 1):
                for selected in task_arms[(task["id"], repetition)]:
                    _print_arm_row(_format_plan_row(task["id"], repetition, selected), selected)
        return
    assert max_wall_clock_seconds is not None
    assert output_path is not None
    assert metadata_path is not None
    snapshot_builder = getattr(runner, "create_input_snapshot", None)
    try:
        input_snapshot = (
            snapshot_builder(
                output_path.parent,
                tasks_path=tasks_path,
                manifest_path=manifest_path,
                invocation_launcher_path=invocation_launcher_path,
                tasks=tasks,
                arms=tuple(dict.fromkeys(selected for arms in task_arms.values() for selected in arms)),
            )
            if callable(snapshot_builder)
            else None
        )
        metadata = _initial_run_metadata(
            manifest_path=manifest_path,
            repo_path=repo_path,
            index_path=index_path,
            output_path=output_path,
            metadata_path=metadata_path,
            model=model,
            reasoning_effort=reasoning_effort,
            repetitions=repetitions,
            task_arms=task_arms,
            max_wall_clock_seconds=max_wall_clock_seconds,
            auth_provisioned=auth_source is not None,
            input_snapshot=input_snapshot,
            study_mode="targeted" if explicit_selection else "confirmatory",
            targeted_scope=targeted_scope,
        )
        canonical_path = _canonical_telemetry_path(output_path)
        task_order = tuple(str(task["id"]) for task in tasks)
        _write_run_metadata(metadata_path, metadata)
    except BaseException:
        _close_runner(runner)
        raise
    run_deadline = time.monotonic() + max_wall_clock_seconds
    planned_cells = sum(len(arms) for arms in task_arms.values())
    printed_cells = 0
    pending_result_rows: list[tuple[str, str]] = []
    active_stager: Any | None = None
    active_diff_impact_stage: DiffImpactStageAdmission | None = None
    consecutive_infrastructure_signature = ""
    consecutive_infrastructure_failures = 0
    try:
        for task in tasks:
            for repetition in range(1, repetitions + 1):
                active_stager = _diff_impact_stager(Path(repo_path), task)
                if active_stager is not None:
                    _validate_locked_runtime(Path(repo_path), index_path, "A_plain", manifest_path)
                    try:
                        active_stager.__enter__()
                        active_diff_impact_stage = _capture_diff_impact_stage(Path(repo_path), task)
                    except BaseException:
                        try:
                            active_stager.__exit__(*sys.exc_info())
                        finally:
                            active_stager = None
                            _validate_locked_runtime(Path(repo_path), index_path, "A_plain", manifest_path)
                        raise
                pending_result_rows = []
                for selected in task_arms[(task["id"], repetition)]:
                    if time.monotonic() >= run_deadline:
                        raise TimeoutError("complete-run wall-clock limit exhausted before next cell")
                    if invocation_launcher_path is not None and invocation_launcher_sha256 is not None:
                        _validate_invocation_launcher(invocation_launcher_path, invocation_launcher_sha256)
                    run_kwargs: dict[str, Any] = {"repetition": repetition, "deadline": run_deadline}
                    if active_diff_impact_stage is not None:
                        run_kwargs["diff_impact_stage"] = active_diff_impact_stage
                    run = runner.run(task, selected, **run_kwargs)
                    if invocation_launcher_path is not None and invocation_launcher_sha256 is not None:
                        _validate_invocation_launcher(invocation_launcher_path, invocation_launcher_sha256)
                    run.run_wall_clock_limit_s = max_wall_clock_seconds
                    _append_run(output_path, run, execution_index=int(metadata["persisted_cells"]))
                    metadata["persisted_cells"] = int(metadata["persisted_cells"]) + 1
                    outcomes = metadata["cell_outcomes"]
                    outcomes["successful" if run.success else "unsuccessful"] += 1
                    for outcome, failed in (
                        ("unscoreable", not run.scoreable),
                        ("incomplete", run.incomplete),
                        ("extraction_failed", run.extraction_failed),
                        ("contaminated", run.contaminated),
                        (
                            "compliance_failed",
                            run.arm in {"B_direct_required", "C_skill_required"} and not run.compliance,
                        ),
                        (
                            "locked_query_nonconforming",
                            run.arm in {"B_direct_required", "C_skill_required"}
                            and run.locked_query_conformance is False,
                        ),
                        ("targeted", run.targeted),
                        ("token_accounting_inconsistent", run.token_accounting_inconsistent),
                    ):
                        if failed:
                            outcomes[outcome] += 1
                    pooling_reasons = metadata["artifacts"]["canonical_telemetry_pooling_ineligibility_reasons"]
                    for reason in _pooling_ineligibility_reasons(run):
                        if reason not in pooling_reasons:
                            pooling_reasons.append(reason)
                    metadata["last_persisted_coordinate"] = {
                        "task_id": task["id"],
                        "repetition": repetition,
                        "arm": selected,
                    }
                    metadata["artifacts"]["canonical_telemetry_sha256"] = _write_canonical_telemetry(
                        output_path,
                        canonical_path,
                        task_order=task_order,
                    )
                    metadata["artifacts"]["canonical_telemetry_status"] = "partial"
                    _write_run_metadata(metadata_path, metadata)
                    status = "✓" if run.success else "✗"
                    quality = f"{run.quality_score:.3f}" if run.quality_score is not None else "?"
                    pending_result_rows.append(
                        (
                            selected,
                            _format_result_row(
                                status=status,
                                task_id=task["id"],
                                repetition=repetition,
                                arm=selected,
                                input_tokens=run.input_tokens,
                                cached_input_tokens=run.cached_input_tokens,
                                fresh_tokens=run.fresh_input_tokens,
                                output_tokens=run.output_tokens,
                                elapsed_s=run.elapsed_s,
                                quality=quality,
                                adherence=run.treatment_adherence,
                                codemap_used=run.codemap_calls > 0,
                            ),
                        )
                    )
                    infrastructure_signature = _infrastructure_failure_signature(run)
                    if infrastructure_signature is None:
                        consecutive_infrastructure_signature = ""
                        consecutive_infrastructure_failures = 0
                    elif run.error_type == "authentication_failed":
                        raise RuntimeError(
                            "infrastructure failure: authentication failed; reauthenticate before resuming the benchmark"
                        )
                    elif infrastructure_signature == consecutive_infrastructure_signature:
                        consecutive_infrastructure_failures += 1
                    else:
                        consecutive_infrastructure_signature = infrastructure_signature
                        consecutive_infrastructure_failures = 1
                    if consecutive_infrastructure_failures >= 3:
                        raise RuntimeError(
                            "infrastructure failure recurred three times before a model response; "
                            "preserved partial artifacts and stopped scheduling"
                        )
                    if time.monotonic() >= run_deadline:
                        raise TimeoutError("complete-run wall-clock limit exhausted after persisted cell")
                printed_cells = _print_result_block(
                    pending_result_rows, printed_cells=printed_cells, planned_cells=planned_cells
                )
                pending_result_rows = []
                if active_stager is not None:
                    try:
                        active_stager.__exit__(None, None, None)
                    finally:
                        active_stager = None
                        active_diff_impact_stage = None
                        _validate_locked_runtime(Path(repo_path), index_path, "A_plain", manifest_path)
    except BaseException as exc:
        if active_stager is not None:
            try:
                active_stager.__exit__(*sys.exc_info())
            finally:
                active_stager = None
                active_diff_impact_stage = None
                _validate_locked_runtime(Path(repo_path), index_path, "A_plain", manifest_path)
        if pending_result_rows:
            printed_cells = _print_result_block(
                pending_result_rows, printed_cells=printed_cells, planned_cells=planned_cells
            )
            pending_result_rows = []
        metadata["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        metadata["completed_at"] = _utc_now()
        metadata["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        metadata["artifacts"]["telemetry_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
        pooling_reasons = metadata["artifacts"]["canonical_telemetry_pooling_ineligibility_reasons"]
        if "run_not_completed" not in pooling_reasons:
            pooling_reasons.append("run_not_completed")
        if canonical_path.exists():
            metadata["artifacts"]["canonical_telemetry_status"] = "partial"
            metadata["artifacts"]["canonical_telemetry_pooling_eligible"] = False
        _write_run_metadata(metadata_path, metadata)
        print(f"SUMMARY\tstatus={metadata['status']}\tpersisted_cells={metadata['persisted_cells']}")
        raise
    finally:
        try:
            _close_runner(runner)
        except BaseException as cleanup_exc:
            prior_error = metadata.get("error")
            metadata["status"] = "failed"
            metadata["completed_at"] = _utc_now()
            metadata["error"] = {
                "type": type(cleanup_exc).__name__,
                "message": f"runner credential cleanup failed: {cleanup_exc}"[:1000],
                "prior_error": prior_error,
            }
            metadata["artifacts"]["telemetry_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
            pooling_reasons = metadata["artifacts"]["canonical_telemetry_pooling_ineligibility_reasons"]
            if "run_not_completed" not in pooling_reasons:
                pooling_reasons.append("run_not_completed")
            if canonical_path.exists():
                metadata["artifacts"]["canonical_telemetry_status"] = "partial"
                metadata["artifacts"]["canonical_telemetry_pooling_eligible"] = False
            _write_run_metadata(metadata_path, metadata)
            print(f"SUMMARY\tstatus=failed\tpersisted_cells={metadata['persisted_cells']}")
            raise
    if invocation_launcher_path is not None and invocation_launcher_sha256 is not None:
        _validate_invocation_launcher(invocation_launcher_path, invocation_launcher_sha256)
    metadata["status"] = "completed"
    metadata["completed_at"] = _utc_now()
    metadata["artifacts"]["telemetry_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    metadata["artifacts"]["canonical_telemetry_status"] = "complete"
    metadata["artifacts"]["canonical_telemetry_pooling_eligible"] = not metadata["artifacts"][
        "canonical_telemetry_pooling_ineligibility_reasons"
    ]
    _write_run_metadata(metadata_path, metadata)
    print(
        f"SUMMARY\tstatus=completed\tpersisted_cells={metadata['persisted_cells']}"
        f"\toutcomes={json.dumps(metadata['cell_outcomes'], sort_keys=True)}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--render-results", action="store_true", help="render progress rows from standard input")
    parser.add_argument(
        "--rescore-results",
        type=Path,
        metavar="RUN_DIR",
        help="replay frozen telemetry and tasks into an immutable offline rescore artifact",
    )
    parser.add_argument(
        "--resolve-tasks",
        metavar="SELECTORS",
        help="resolve comma-separated exact task IDs or task families into a targeted scope",
    )
    parser.add_argument("--force-color", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hide-plan", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repo-path", type=Path)
    parser.add_argument("--model")
    parser.add_argument(
        "--reasoning-effort",
        default=PARITY_CODEX_REASONING_EFFORT,
        choices=(PARITY_CODEX_REASONING_EFFORT,),
    )
    parser.add_argument("--tasks-path", type=Path)
    parser.add_argument("--manifest-path", type=Path, default=PARITY_MANIFEST_PATH)
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("--marketplace-root", type=Path, required=False)
    parser.add_argument("--codemap-bin", type=Path)
    parser.add_argument("--auth-source", type=Path)
    parser.add_argument("--invocation-launcher-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--metadata-path", type=Path)
    parser.add_argument("--task-id", dest="task_ids", action="append")
    parser.add_argument("--tasks", dest="task_selectors", help="comma-separated exact task IDs or task families")
    parser.add_argument("--scope-sha256", help="resolved targeted-scope SHA-256 required for paid subsets")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--arm", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-legend", dest="show_legend", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--max-wall-clock-seconds", type=float)
    args = parser.parse_args()
    if args.force_color and not args.render_results:
        parser.error("--force-color requires --render-results")
    if args.hide_plan and not args.render_results:
        parser.error("--hide-plan requires --render-results")
    if args.rescore_results is not None:
        if args.render_results or args.resolve_tasks is not None:
            parser.error("--rescore-results cannot be combined with rendering or task resolution")
        print(rescore_results(args.rescore_results))
    elif args.resolve_tasks is not None:
        if args.render_results:
            parser.error("--resolve-tasks cannot be combined with --render-results")
        print(json.dumps(resolve_task_selection(args.manifest_path, args.resolve_tasks), sort_keys=True))
    elif args.render_results:
        render_result_rows(sys.stdin, sys.stdout, force_color=args.force_color, hide_plan=args.hide_plan)
    else:
        for option in ("repo_path", "model", "tasks_path"):
            if getattr(args, option) is None:
                parser.error(f"--{option.replace('_', '-')} is required unless --render-results is used")
        arguments = vars(args)
        arguments.pop("render_results")
        arguments.pop("rescore_results")
        arguments.pop("resolve_tasks")
        arguments.pop("force_color")
        arguments.pop("hide_plan")
        main(**arguments)
