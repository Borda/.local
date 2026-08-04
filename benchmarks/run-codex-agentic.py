#!/usr/bin/env python3
"""Codex agentic provider-parity runner for the locked BA-01 first slice.

This module intentionally supports only the BA-01 agentic pilot coordinate and
its A_plain, B_auto, and C_required treatments.  It reuses the Claude
``GroundTruth`` scorer and the Codex structural runner's native JSONL parser
instead of copying either implementation.  Both sibling runners have hyphens
in their filenames, so ``importlib`` loading is the smallest safe way to keep
their single-source contracts importable without renaming established scripts.

``--dry-run`` validates the locked BA-01 provenance and prints the
deterministic 3×3 cell plan without reading credentials, invoking a model, or
creating result files. Paid execution is separately admitted only by the agentic
manifest and exact SHA approval; the structural manifest remains an isolated
runtime adapter, never the agentic study definition.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping

_BENCHMARKS_DIR = Path(__file__).resolve().parent
if str(_BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCHMARKS_DIR))

from _utilities import fmt_time, fmt_tok  # noqa: E402
from provider_parity_contracts import (  # noqa: E402
    ARM_CONTRACTS,
    canonical_task_hash,
    prompt_hash,
    semantic_suite_hash,
    treatment_adherence,
)


_TASKS_PATH = _BENCHMARKS_DIR / "suites" / "tasks-agentic.json"
_MANIFEST_PATH = _BENCHMARKS_DIR / "manifests" / "codex-agentic.json"
AGENTIC_ARMS = ("A_plain", "B_auto", "C_required")
AGENTIC_TASK_ID = "BA-01"
AGENTIC_REPETITIONS = 3
_NATIVE_HOME_ARM = {
    "A_plain": "A_plain",
    "B_auto": "B_direct_required",
    "C_required": "C_skill_required",
}
_OUTPUT_LEGEND = (
    "LEGEND\n"
    "  treatments: A_plain=no Codemap, B_auto=CLI available and optional, "
    "C_required=Codemap Skill read plus compact query required\n"
    "  metrics:\n"
    "      EREC: expected direct-importer recall\n"
    "      RREC: final-report recall\n"
    "      DEFF: expected dependencies exposed per tool call\n"
    "  status: ✓ completed, ✗ failed\n"
    "  progress: N completed cells / 9 planned cells\n"
    "  treatment: ✓ assigned arm followed, ✗ assigned arm not followed\n"
    "  codemap-used: ✓ Codemap call observed; ✗ no call observed (A_plain expects none)\n"
    "  input tokens: gross total; cached and fresh details remain in telemetry only\n"
    "END LEGEND"
)


def _load_sibling(module_name: str, filename: str) -> ModuleType:
    """Load one hyphenated benchmark sibling once by its stable local path."""
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        return loaded
    path = _BENCHMARKS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark sibling {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_claude = _load_sibling("_codex_agentic_claude", "run-claude-agentic.py")
_structural = _load_sibling("_codex_agentic_structural", "run-codex-structural.py")
GroundTruth = _claude.GroundTruth
Task = _claude.Task
QualityScore = _claude.QualityScore


@dataclass(frozen=True)
class ArmProbe:
    """No-model evidence that one agentic treatment has the required isolation."""

    arm: str
    codemap_available: bool
    skill_required: bool


@dataclass
class AgenticRun:
    """Normalized no-model Codex agentic evidence for one completed native stream."""

    arm: str
    task_id: str
    repetition: int
    success: bool
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    command_calls: int
    codemap_calls: int
    codemap_successful_calls: int
    codemap_used: bool
    compliance: bool | None
    treatment_adherence: bool
    contaminated: bool
    incomplete: bool
    malformed_lines: int
    error: str
    error_type: str
    output_text: str
    report_text: str
    quality: QualityScore
    elapsed_s: float = 0.0
    retry_count: int = 0
    raw_events: list[dict[str, Any]] | None = None
    native_attempt_events: list[list[dict[str, Any]]] | None = None


def probe_arm(arm: str) -> ArmProbe:
    """Return pure isolated-home policy evidence for one supported treatment.

    Actual homes are created only by the future paid runner after agentic admission;
    this pure preflight cannot touch credentials, plugin installation, or model
    state.  The availability assertions are still explicit and fail closed.
    """
    if arm not in AGENTIC_ARMS:
        raise ValueError(f"unsupported Codex agentic arm {arm!r}")
    if arm == "A_plain":
        return ArmProbe(arm, codemap_available=False, skill_required=False)
    return ArmProbe(arm, codemap_available=True, skill_required=arm == "C_required")


def prepare_isolated_home(arm: str, **kwargs: Any) -> Any:
    """Create the structural runner's disposable home for a future paid cell.

    The underlying A/B/C homes already prevent host-plugin and credential
    inheritance.  B_auto maps to the direct-Codemap availability home only;
    optional use remains an agentic admission rule, not a home capability.
    This function is intentionally never called by the first-slice dry run.
    """
    if arm not in AGENTIC_ARMS:
        raise ValueError(f"unsupported Codex agentic arm {arm!r}")
    return _structural.prepare_arm_home(_NATIVE_HOME_ARM[arm], **kwargs)


def probe_isolated_home(home: Any, arm: str) -> dict[str, Any]:
    """Probe one runner-owned home and reject capability drift before a paid cell."""
    expected = probe_arm(arm)
    evidence = _structural.probe_arm_home(home)
    if bool(evidence.get("codemap_available")) != expected.codemap_available:
        raise ValueError(f"{arm} isolated-home Codemap availability drifted")
    return evidence


def load_ba01_task(tasks_path: Path = _TASKS_PATH, manifest_path: Path = _MANIFEST_PATH) -> Task:
    """Load exactly BA-01 after validating the dedicated first-slice lock."""
    tasks_path = Path(tasks_path)
    manifest_path = Path(manifest_path)
    raw_tasks = _claude.load_task_suite(tasks_path)
    matches = [task for task in raw_tasks if task.get("id") == AGENTIC_TASK_ID]
    if len(matches) != 1:
        raise ValueError(f"agentic first slice requires exactly one {AGENTIC_TASK_ID} task")
    raw_task = matches[0]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        suite_lock = manifest["suite"]
        task_lock = manifest["task"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("agentic first-slice manifest is unavailable or malformed") from exc
    if (
        suite_lock.get("path") != "benchmarks/suites/tasks-agentic.json"
        or suite_lock.get("raw_sha256") != hashlib.sha256(tasks_path.read_bytes()).hexdigest()
        or suite_lock.get("semantic_suite_sha256") != semantic_suite_hash(raw_tasks)
        or task_lock.get("id") != AGENTIC_TASK_ID
        or task_lock.get("canonical_task_sha256") != canonical_task_hash(raw_task)
        or task_lock.get("prompt_sha256") != prompt_hash(raw_task)
    ):
        raise ValueError("agentic first-slice task or suite identity drifted")
    task = Task(
        id=str(raw_task["id"]),
        type=str(raw_task["type"]),
        prompt=str(raw_task["prompt"]),
        primary_module=str(raw_task.get("primary_module", "")),
        difficulty=str(raw_task.get("difficulty", "unknown")),
        experiment_revision=str(manifest.get("experiment_revision", "")),
        task_hash=str(task_lock["canonical_task_sha256"]),
        prompt_hash=str(task_lock["prompt_sha256"]),
        suite_hash=str(suite_lock["semantic_suite_sha256"]),
        suite_raw_hash=str(suite_lock["raw_sha256"]),
        oracle_class=str(task_lock.get("oracle_class", "unknown")),
        headline_eligible_v1=bool(task_lock.get("headline_eligible_v1", False)),
        scoreable=bool(task_lock.get("effective_scoreable", False)),
    )
    if task.type != "blast_radius_analysis" or not task.scoreable:
        raise ValueError(f"{AGENTIC_TASK_ID} must retain blast_radius_analysis semantics")
    return task


def parse_agentic_stream(
    stream: str | bytes | Iterable[str | bytes],
    *,
    arm: str,
    task: Task,
    ground_truth: GroundTruth,
    repetition: int = 1,
    skill_path: Path | None = None,
) -> AgenticRun:
    """Normalize one native stream and score it with the shared Claude oracle.

    B_auto has optional Codemap use.  C_required preserves a completed no-call
    row but records compliance/adherence false; aggregation must exclude that
    coordinate rather than erasing its raw evidence.
    """
    if arm not in AGENTIC_ARMS:
        raise ValueError(f"unsupported Codex agentic arm {arm!r}")
    if task.id != AGENTIC_TASK_ID:
        raise ValueError(f"agentic first slice supports only {AGENTIC_TASK_ID}")
    if repetition < 1:
        raise ValueError("repetition must be at least 1")
    if arm == "C_required" and skill_path is None:
        raise ValueError("C_required requires the exact installed Codemap Skill path")
    if arm != "C_required" and skill_path is not None:
        raise ValueError("only C_required accepts a Codemap Skill path")

    skill_bytes = skill_path.read_bytes() if skill_path is not None else b""
    parsed = _structural.parse_codex_jsonl(
        stream,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest() if skill_bytes else "",
    )
    codemap_used = parsed.codemap_calls > 0
    contaminated = arm == "A_plain" and codemap_used
    compliance = None
    if arm == "C_required":
        compliance = bool(parsed.skill_delivery_observed and parsed.codemap_skill_compact_successful_calls > 0)
    adherence_arm = arm
    adherence = treatment_adherence(
        adherence_arm,
        codemap_use_compliance=compliance,
        contaminated=contaminated,
    )
    report_text = parsed.output_text[parsed.last_tool_text_offset :].lstrip("\n")
    quality = ground_truth.score(
        task.id,
        parsed.output_text,
        parsed.output_text,
        report_text,
        tool_calls=parsed.command_calls,
    )
    return AgenticRun(
        arm=arm,
        task_id=task.id,
        repetition=repetition,
        success=parsed.success,
        input_tokens=parsed.input_tokens,
        cached_input_tokens=parsed.cached_input_tokens,
        output_tokens=parsed.output_tokens,
        command_calls=parsed.command_calls,
        codemap_calls=parsed.codemap_calls,
        codemap_successful_calls=parsed.codemap_successful_calls,
        codemap_used=codemap_used,
        compliance=compliance,
        treatment_adherence=adherence,
        contaminated=contaminated,
        incomplete=parsed.incomplete,
        malformed_lines=parsed.malformed_lines,
        error=parsed.error,
        error_type=parsed.error_type,
        output_text=parsed.output_text,
        report_text=report_text,
        quality=quality,
        raw_events=parsed.raw_events,
    )


def _read_agentic_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load the dedicated agentic manifest as one validated JSON object."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Codex agentic manifest is unavailable or malformed") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Codex agentic manifest must be a JSON object")
    return manifest


def _manifest_sha256(manifest_path: Path) -> str:
    """Return the exact bytes hash required for explicit paid authorization."""
    try:
        return hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("Codex agentic manifest is unavailable") from exc


def validate_paid_admission(manifest_path: Path, approval_sha256: str) -> dict[str, Any]:
    """Fail closed unless the agentic manifest admits this exact paid BA-01 study."""
    manifest_path = Path(manifest_path)
    observed_hash = _manifest_sha256(manifest_path)
    if approval_sha256 != observed_hash:
        raise ValueError("paid Codex agentic execution requires the exact current manifest SHA-256 approval")
    manifest = _read_agentic_manifest(manifest_path)
    scope = manifest.get("preregistered_scope")
    model = manifest.get("model")
    admission = manifest.get("admission")
    if not isinstance(scope, Mapping) or not isinstance(model, Mapping) or not isinstance(admission, Mapping):
        raise ValueError("Codex agentic manifest lacks admission, model, or scope")
    expected_scope = {
        "arms": list(AGENTIC_ARMS),
        "task_ids": [AGENTIC_TASK_ID],
        "repetitions": AGENTIC_REPETITIONS,
        "coordinate_timeout_seconds": 600,
        "complete_run_max_wall_clock_seconds": 5400,
        "total_cells": 9,
    }
    if (
        manifest.get("schema_version") != "codex-agentic-manifest-v1"
        or admission.get("paid_execution") != "admitted"
        or any(scope.get(key) != value for key, value in expected_scope.items())
        or model.get("name") != "gpt-5.6-luna"
        or model.get("reasoning_effort") != "high"
        or model.get("strict_config") is not True
    ):
        raise ValueError("Codex agentic manifest does not admit the fixed BA-01 paid scope")
    artifact_hashes = manifest.get("artifact_sha256")
    if not isinstance(artifact_hashes, Mapping):
        raise ValueError("Codex agentic manifest lacks artifact hashes")
    launcher_hash = artifact_hashes.get("run_all")
    if not isinstance(launcher_hash, str) or len(launcher_hash) != 64:
        raise ValueError("Codex agentic manifest lacks the locked run-all launcher hash")
    current_runner_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if artifact_hashes.get("codex_agentic_runner") != current_runner_hash:
        raise ValueError("Codex agentic runner bytes differ from the admitted manifest")
    return manifest


def _agentic_envelope(arm: str) -> str:
    """Return the agentic arm instruction without importing structural task policy."""
    if arm == "A_plain":
        return "Codemap is absent and inaccessible. Solve using ordinary provider tools only."
    if arm == "B_auto":
        return (
            "Codemap's direct CLI is available as $CODEMAP_BIN. Use it when useful, but ordinary reads and shell "
            "tools remain allowed and no Codemap call is required."
        )
    if arm == "C_required":
        return (
            'Use the installed Codemap Skill before answering: first execute exactly cat "$CODEMAP_SKILL_FILE", '
            "then complete at least one successful $CODEMAP_BIN query --compact structural query. Other reads and "
            "shell commands remain allowed."
        )
    raise ValueError(f"unsupported Codex agentic arm {arm!r}")


class AgenticCodexRunner:
    """Execute agentic cells through the structural runner's isolated native homes.

    The dedicated agentic manifest controls agentic semantics and admission.  The
    structural manifest named in its ``runtime_isolation`` section is used only
    to obtain the existing disposable permissions, plugin, and credential path.
    """

    def __init__(
        self,
        *,
        repo_path: Path,
        index_path: Path,
        marketplace_root: Path | None,
        codemap_bin: Path | None,
        auth_source: Path | None,
        adapter_manifest_path: Path,
        agentic_manifest: Mapping[str, Any],
        transport: Callable[..., str | bytes | Iterable[str | bytes]] | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.index_path = Path(index_path).resolve()
        self.agentic_manifest = agentic_manifest
        self.transport = transport
        self.adapter = _structural.CodexRunner(
            "gpt-5.6-luna",
            self.repo_path,
            reasoning_effort="high",
            index_path=self.index_path,
            timeout=600,
            marketplace_root=marketplace_root,
            codemap_bin=codemap_bin,
            manifest_path=adapter_manifest_path,
            auth_source=auth_source,
        )

    def close(self) -> None:
        """Release the adapter's private credential chain."""
        self.adapter.close()

    def _postflight(self, home: Any | None) -> str:
        """Return a concrete error when a native attempt changed locked runtime state."""
        try:
            _validate_agentic_runtime(self.agentic_manifest, self.repo_path, self.index_path)
            if home is not None and home.coordination_path is not None:
                _structural._validate_coordination_root(home.coordination_path)
        except ValueError as exc:
            return str(exc)
        return ""

    def create_input_snapshot(
        self, run_dir: Path, *, manifest_path: Path, invocation_launcher_path: Path
    ) -> dict[str, Any]:
        """Archive only immutable, non-secret agentic inputs and verified runtime bytes."""
        homes: list[Any] = []
        arm_archives: dict[str, dict[str, Path]] = {}
        arm_files: dict[str, dict[str, Path]] = {}
        operation_error: BaseException | None = None
        try:
            for arm in AGENTIC_ARMS:
                home = self.adapter._prepare_verified_home(_NATIVE_HOME_ARM[arm])
                homes.append(home)
                arm_files[arm] = {"config.toml": home.path / "config.toml"}
                if arm == "B_auto":
                    arm_archives[arm] = {"direct-cli": home.path / "direct-cli"}
                elif arm == "C_required":
                    if home.codemap_plugin_path is None or home.codex_rig_path is None:
                        raise RuntimeError("C_required snapshot lacks verified Codemap or Codex Rig package")
                    arm_archives[arm] = {"codemap-py": home.codemap_plugin_path, "codex-rig": home.codex_rig_path}
                    if home.codemap_context_path is not None:
                        arm_files[arm]["codemap-context.json"] = home.codemap_context_path
            return _write_agentic_input_snapshot(
                Path(run_dir) / "inputs",
                manifest_path=Path(manifest_path),
                tasks_path=_TASKS_PATH,
                runner_path=Path(__file__),
                invocation_launcher_path=invocation_launcher_path,
                index_path=self.index_path,
                auth_source=self.adapter.auth_source,
                arm_archives=arm_archives,
                arm_files=arm_files,
            )
        except BaseException as exc:
            operation_error = exc
            raise
        finally:
            cleanup_errors: list[BaseException] = []
            cleaned_coordination_paths: set[Path] = set()
            for home in homes:
                try:
                    if self.adapter._auth_state is not None and home.auth_provisioned:
                        self.adapter._auth_state.refresh_from_home(home.path)
                except BaseException as exc:
                    cleanup_errors.append(exc)
                try:
                    coordination_path = home.coordination_path
                    if coordination_path is not None and coordination_path not in cleaned_coordination_paths:
                        cleaned_coordination_paths.add(coordination_path)
                        _structural._cleanup_coordination_root(coordination_path)
                except BaseException as exc:
                    cleanup_errors.append(exc)
                try:
                    home.cleanup()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if operation_error is None and cleanup_errors:
                raise cleanup_errors[0]

    def run(self, task: Task, arm: str, *, repetition: int, ground_truth: GroundTruth, deadline: float) -> AgenticRun:
        """Run one agentic coordinate, retrying only empty retryable transport failures."""
        home: Any | None = None
        started = time.monotonic()
        attempts: list[list[dict[str, Any]]] = []
        result: AgenticRun | None = None
        postflight_error = ""
        auth_state_error = ""
        cleanup_error = ""
        if self.transport is None:
            home = self.adapter._prepare_verified_home(_NATIVE_HOME_ARM[arm])
        try:
            command = self.adapter.build_command(f"{_agentic_envelope(arm)}\n\n{task.prompt}")
            for attempt in range(3):
                remaining = min(600.0 - (time.monotonic() - started), deadline - time.monotonic())
                if remaining <= 0:
                    timeout_stream = json.dumps({"type": "error", "error": "cell timeout", "error_type": "timeout"})
                    result = parse_agentic_stream(
                        timeout_stream,
                        arm=arm,
                        task=task,
                        ground_truth=ground_truth,
                        repetition=repetition,
                        skill_path=home.codemap_skill_path if arm == "C_required" and home is not None else None,
                    )
                    break
                if self.transport is None:
                    assert home is not None
                    stream = self.adapter._subprocess(command, home.env, timeout=remaining)
                else:
                    stream = self.transport(command, arm=arm)
                result = parse_agentic_stream(
                    stream,
                    arm=arm,
                    task=task,
                    ground_truth=ground_truth,
                    repetition=repetition,
                    skill_path=home.codemap_skill_path if arm == "C_required" and home is not None else None,
                )
                attempts.append(result.raw_events or [])
                postflight_error = self._postflight(home)
                if postflight_error:
                    result.incomplete = True
                    result.success = False
                    result.error = f"runtime contamination: {postflight_error}"
                    result.error_type = "runtime_contamination"
                    break
                empty_retryable = (
                    result.input_tokens == 0
                    and result.output_tokens == 0
                    and not result.output_text.strip()
                    and result.error_type in {"turn_failed", "response_failed", "transport_error", "launch_os_error"}
                )
                if not empty_retryable or attempt == 2:
                    break
            assert result is not None
        finally:
            if home is not None:
                try:
                    if self.adapter._auth_state is not None and home.auth_provisioned:
                        self.adapter._auth_state.refresh_from_home(home.path)
                except (RuntimeError, ValueError) as exc:
                    auth_state_error = str(exc)
                try:
                    if home.coordination_path is not None:
                        _structural._cleanup_coordination_root(home.coordination_path)
                except ValueError as exc:
                    cleanup_error = str(exc)
                finally:
                    home.cleanup()
        result.elapsed_s = time.monotonic() - started
        result.retry_count = max(len(attempts) - 1, 0)
        result.native_attempt_events = attempts
        if auth_state_error:
            result.incomplete = True
            result.success = False
            result.error = "run auth state could not be refreshed"
            result.error_type = "authentication_state_failed"
        if cleanup_error:
            result.incomplete = True
            result.success = False
            result.error = f"runner cleanup failed: {cleanup_error}"
            result.error_type = "cleanup_failed"
        if result.contaminated:
            result.success = False
            result.error = result.error or "contaminated"
        return result


def _validate_agentic_runtime(manifest: Mapping[str, Any], repo_path: Path, index_path: Path) -> None:
    """Check the agentic target and frozen index without treating it as structural policy."""
    target = manifest.get("target_source")
    index = manifest.get("frozen_index_contract")
    if not isinstance(target, Mapping) or not isinstance(index, Mapping):
        raise ValueError("Codex agentic manifest lacks target or frozen-index contract")
    if _structural._repo_sha(repo_path) != target.get("commit"):
        raise ValueError("agentic Codex run requires the locked target commit")
    if _structural._git_porcelain_status(repo_path):
        raise ValueError("agentic Codex run requires a clean target worktree")
    if not index_path.is_file() or hashlib.sha256(index_path.read_bytes()).hexdigest() != index.get("raw_sha256"):
        raise ValueError("agentic Codex run requires the locked frozen index bytes")
    try:
        metadata = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("agentic Codex frozen index is unavailable or malformed") from exc
    if metadata.get("git_sha") != index.get("git_sha") or metadata.get("scan_version") != index.get("scan_version"):
        raise ValueError("agentic Codex frozen index metadata drifted")


def _write_agentic_input_snapshot(
    snapshot_root: Path,
    *,
    manifest_path: Path,
    tasks_path: Path,
    runner_path: Path,
    invocation_launcher_path: Path,
    index_path: Path,
    auth_source: Path | None,
    arm_archives: Mapping[str, Mapping[str, Path]],
    arm_files: Mapping[str, Mapping[str, Path]],
) -> dict[str, Any]:
    """Write immutable non-secret agentic inputs with accurate runner provenance."""
    if snapshot_root.exists():
        raise FileExistsError(snapshot_root)
    snapshot_root.mkdir(parents=True, mode=0o700)
    entries: list[dict[str, Any]] = []
    shared = snapshot_root / "shared"
    for role, source, relative in (
        ("manifest", manifest_path, Path("manifest.json")),
        ("task_suite", tasks_path, Path("tasks-agentic.json")),
        ("agentic_runner", runner_path, Path("run-codex-agentic.py")),
        ("invocation_launcher", invocation_launcher_path, Path("run-all.sh")),
        ("locked_index", index_path, Path("locked-index.json")),
    ):
        _structural._archive_snapshot_file(
            source, shared / relative, role=role, archive_root=snapshot_root, entries=entries
        )
    for arm in AGENTIC_ARMS:
        for relative, source in sorted(arm_files.get(arm, {}).items()):
            _structural._archive_snapshot_file(
                source,
                snapshot_root / arm / relative,
                role=f"{arm}:{relative}",
                archive_root=snapshot_root,
                entries=entries,
            )
        for package_role, root in sorted(arm_archives.get(arm, {}).items()):
            _structural._archive_snapshot_tree(
                root, snapshot_root / arm / package_role, role=f"{arm}:{package_role}", entries=entries
            )
    entries.sort(key=lambda item: (str(item["role"]), str(item["archived_path"])))
    payload = {
        "schema_version": "codex-agentic-input-snapshot-v1",
        "files": entries,
        "auth_source": {"supplied": True, "archived": False} if auth_source is not None else None,
    }
    snapshot_path = snapshot_root / "input-snapshot.json"
    serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    snapshot_path.write_bytes(serialized)
    snapshot_path.chmod(0o600)
    payload["path"] = str(snapshot_path.resolve())
    payload["sha256"] = hashlib.sha256(serialized).hexdigest()
    payload["bytes"] = len(serialized)
    return payload


def _format_probe(probe: ArmProbe) -> str:
    """Render one deterministic no-model treatment probe."""
    availability = "true" if probe.codemap_available else "false"
    required = "true" if probe.skill_required else "false"
    return f"PROBE   {probe.arm:<10} codemap={availability:<5} skill-required={required}"


def _emit_output_legend(output: Any | None = None) -> None:
    """Emit the agentic legend through the structural shared renderer."""
    destination = sys.stdout if output is None else output
    _structural.render_result_rows(f"{_OUTPUT_LEGEND}\n".splitlines(keepends=True), destination)


def _format_plan(task_id: str, repetition: int, arm: str) -> str:
    """Render one deterministic dry-run coordinate."""
    return f"PLAN    {task_id:<5}  rep={repetition}  {arm}"


def dry_run(
    *,
    tasks_path: Path = _TASKS_PATH,
    manifest_path: Path = _MANIFEST_PATH,
    repetitions: int = AGENTIC_REPETITIONS,
) -> list[str]:
    """Validate the BA-01 contract and return its exact no-model cell plan."""
    if repetitions != AGENTIC_REPETITIONS:
        raise ValueError(f"agentic first slice requires exactly {AGENTIC_REPETITIONS} repetitions")
    task = load_ba01_task(tasks_path, manifest_path)
    if set(AGENTIC_ARMS) != set(ARM_CONTRACTS):
        raise ValueError("agentic arm contracts drifted from the shared provider policy")
    lines = [_format_probe(probe_arm(arm)) for arm in AGENTIC_ARMS]
    for repetition in range(1, repetitions + 1):
        for arm in AGENTIC_ARMS:
            lines.append(_format_plan(task.id, repetition, arm))
    return lines


def _append_telemetry(path: Path, run: AgenticRun, execution_index: int) -> None:
    """Append one immutable raw agentic row before updating derived evidence."""
    row = asdict(run)
    row["execution_index"] = execution_index
    row["fresh_input_tokens"] = _structural.fresh_input_tokens(run.input_tokens, run.cached_input_tokens)
    row["token_accounting_inconsistent"] = _structural.token_accounting_inconsistent(
        run.input_tokens, run.cached_input_tokens
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_canonical_telemetry(raw_path: Path) -> str:
    """Publish the derived agentic canonical order without rewriting raw JSONL."""
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line]
    canonical = _structural.canonical_result_rows(rows, task_order=(AGENTIC_TASK_ID,), arm_order=AGENTIC_ARMS)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in canonical).encode("utf-8")
    output = raw_path.with_name("telemetry-canonical.jsonl")
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def _write_checksums(run_dir: Path) -> None:
    """Refresh checksums for every persisted agentic artifact, including partials."""
    files = [path for path in sorted(run_dir.rglob("*")) if path.is_file() and path.name != "checksums.sha256"]
    payload = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run_dir).as_posix()}\n" for path in files
    )
    (run_dir / "checksums.sha256").write_text(payload, encoding="utf-8")


def _progress_line(execution_index: int, run: AgenticRun) -> str:
    """Render one compact agentic result after its immutable telemetry row is persisted."""
    quality = run.quality
    status = "✓" if run.success else "✗"
    treatment = "✓" if run.treatment_adherence else "✗"
    used = "✓" if run.codemap_used else "✗"
    return (
        f"({execution_index}/9) {status}  {run.task_id:<5}  rep={run.repetition}  {run.arm:<10}"
        f"  in={fmt_tok(run.input_tokens):>6}  out={fmt_tok(run.output_tokens):>6}"
        f"  time={fmt_time(run.elapsed_s):>5}  EREC={quality.erec:.3f}  RREC={quality.rrec:.3f}"
        f"  DEFF={quality.deff:.3f}  treatment:{treatment}  codemap-used:{used}"
    )


def _emit_run_line(run_log: Path, line: str) -> None:
    """Print and append one human-readable paid-run evidence line."""
    print(line)
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _initial_metadata(
    *,
    manifest_path: Path,
    approval_sha256: str,
    run_dir: Path,
    task: Task,
    max_wall_clock_seconds: float,
    invocation_launcher_path: Path,
) -> dict[str, Any]:
    """Build compact provenance before the first paid coordinate is scheduled."""
    coordinates = [
        {"task_id": task.id, "repetition": repetition, "arm": arm}
        for repetition in range(1, AGENTIC_REPETITIONS + 1)
        for arm in AGENTIC_ARMS
    ]
    return {
        "schema": "codex-agentic-run-v1",
        "status": "running",
        "started_at": _structural._utc_now(),
        "persisted_cells": 0,
        "last_persisted_coordinate": None,
        "error": None,
        "manifest": {"path": str(manifest_path.resolve()), "sha256": approval_sha256},
        "invocation_launcher": {"path": str(invocation_launcher_path.resolve())},
        "execution": {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "cell_wall_clock_seconds": 600,
            "max_wall_clock_seconds": max_wall_clock_seconds,
            "coordinates": coordinates,
            "pooling_eligible": False,
        },
        "artifacts": {
            "telemetry_jsonl": str((run_dir / "telemetry.jsonl").resolve()),
            "telemetry_canonical_jsonl": str((run_dir / "telemetry-canonical.jsonl").resolve()),
            "run_metadata": str((run_dir / "run-metadata.json").resolve()),
        },
    }


def _admit_run_directory(run_dir: Path, invocation_launcher_path: Path, launcher_hash: str) -> None:
    """Allow only run-all's verified launcher snapshot before a paid run starts."""
    expected_launcher = run_dir / ".launcher" / "run-all.sh"
    if invocation_launcher_path.absolute() != expected_launcher.absolute():
        raise FileExistsError(run_dir)
    try:
        entries = {entry.name for entry in run_dir.iterdir()}
        launcher_entries = {entry.name for entry in expected_launcher.parent.iterdir()}
    except OSError as exc:
        raise FileExistsError(run_dir) from exc
    if entries != {".launcher"} or launcher_entries != {"run-all.sh"}:
        raise FileExistsError(run_dir)
    _structural._validate_invocation_launcher(expected_launcher, launcher_hash)


def run_paid(
    *,
    repo_path: Path,
    index_path: Path,
    auth_source: Path,
    approval_sha256: str,
    run_dir: Path,
    manifest_path: Path = _MANIFEST_PATH,
    marketplace_root: Path | None = None,
    codemap_bin: Path | None = None,
    invocation_launcher_path: Path | None = None,
    max_wall_clock_seconds: float = 5400,
    runner_factory: Callable[..., Any] | None = None,
) -> Path:
    """Execute the admitted BA-01 nine-cell study with immutable partial evidence.

    Test fixtures may inject ``runner_factory``; production always uses the
    structural adapter for credential lifecycle, permissions, and native Codex
    transport.  The function never records the auth path or credential bytes.
    """
    if max_wall_clock_seconds != 5400:
        raise ValueError("agentic complete-run wall-clock limit must equal the admitted 5400 seconds")
    if not auth_source:
        raise ValueError("paid Codex agentic execution requires an auth source")
    if invocation_launcher_path is None:
        raise ValueError("paid Codex agentic execution requires the invocation launcher path")
    manifest = validate_paid_admission(manifest_path, approval_sha256)
    repo_path = Path(repo_path).resolve()
    index_path = Path(index_path).resolve()
    _validate_agentic_runtime(manifest, repo_path, index_path)
    runtime = manifest.get("runtime_isolation")
    if not isinstance(runtime, Mapping) or not isinstance(runtime.get("manifest"), str):
        raise ValueError("Codex agentic manifest lacks a structural runtime adapter manifest")
    adapter_manifest_path = (_BENCHMARKS_DIR.parent / runtime["manifest"]).resolve()
    if not adapter_manifest_path.is_file():
        raise ValueError("Codex agentic structural runtime adapter manifest is unavailable")
    launcher_hash = str(manifest["artifact_sha256"]["run_all"])
    invocation_launcher_path = Path(invocation_launcher_path)
    _structural._validate_invocation_launcher(invocation_launcher_path, launcher_hash)
    run_dir = Path(run_dir)
    _admit_run_directory(run_dir, invocation_launcher_path, launcher_hash)
    raw_path = run_dir / "telemetry.jsonl"
    raw_path.touch(exist_ok=False)
    run_log = run_dir / "run.log"
    run_log.touch(exist_ok=False)
    metadata_path = run_dir / "run-metadata.json"
    task = load_ba01_task(_TASKS_PATH, manifest_path)
    metadata = _initial_metadata(
        manifest_path=Path(manifest_path),
        approval_sha256=approval_sha256,
        run_dir=run_dir,
        task=task,
        max_wall_clock_seconds=max_wall_clock_seconds,
        invocation_launcher_path=invocation_launcher_path,
    )
    _structural._write_run_metadata(metadata_path, metadata)
    _emit_output_legend()
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(_OUTPUT_LEGEND + "\n")
    factory = runner_factory or AgenticCodexRunner
    runner: Any | None = None
    deadline = time.monotonic() + max_wall_clock_seconds
    try:
        truth = GroundTruth(index_path, [task], repo_path=repo_path)
        runner = factory(
            repo_path=repo_path,
            index_path=index_path,
            marketplace_root=marketplace_root,
            codemap_bin=codemap_bin,
            auth_source=Path(auth_source),
            adapter_manifest_path=adapter_manifest_path,
            agentic_manifest=manifest,
        )
        snapshot_builder = getattr(runner, "create_input_snapshot", None)
        if callable(snapshot_builder):
            metadata["inputs"] = {
                "snapshot": snapshot_builder(
                    run_dir, manifest_path=Path(manifest_path), invocation_launcher_path=invocation_launcher_path
                )
            }
            _structural._write_run_metadata(metadata_path, metadata)
            _write_checksums(run_dir)
        for repetition in range(1, AGENTIC_REPETITIONS + 1):
            for arm in AGENTIC_ARMS:
                if time.monotonic() >= deadline:
                    raise TimeoutError("agentic complete-run wall-clock limit exhausted before next cell")
                run = runner.run(task, arm, repetition=repetition, ground_truth=truth, deadline=deadline)
                _validate_agentic_runtime(manifest, repo_path, index_path)
                _structural._validate_invocation_launcher(invocation_launcher_path, launcher_hash)
                _append_telemetry(raw_path, run, int(metadata["persisted_cells"]))
                metadata["persisted_cells"] = int(metadata["persisted_cells"]) + 1
                metadata["last_persisted_coordinate"] = {"task_id": task.id, "repetition": repetition, "arm": arm}
                metadata["artifacts"]["canonical_telemetry_sha256"] = _write_canonical_telemetry(raw_path)
                _structural._write_run_metadata(metadata_path, metadata)
                _emit_run_line(run_log, _progress_line(int(metadata["persisted_cells"]), run))
                _write_checksums(run_dir)
        metadata["status"] = "completed"
        metadata["completed_at"] = _structural._utc_now()
        _structural._write_run_metadata(metadata_path, metadata)
        _emit_run_line(run_log, f"SUMMARY  status=completed  persisted_cells={metadata['persisted_cells']}/9")
        _write_checksums(run_dir)
        return run_dir
    except BaseException as exc:
        metadata["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        metadata["completed_at"] = _structural._utc_now()
        metadata["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        _structural._write_run_metadata(metadata_path, metadata)
        _emit_run_line(
            run_log, f"SUMMARY  status={metadata['status']}  persisted_cells={metadata['persisted_cells']}/9"
        )
        _write_checksums(run_dir)
        raise
    finally:
        if runner is not None:
            _structural._close_runner(runner)


def main(argv: list[str] | None = None) -> int:
    """Run the no-model preflight or the separately admitted paid BA-01 study."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the fixed BA-01 no-model plan")
    parser.add_argument("--tasks-path", type=Path, default=_TASKS_PATH)
    parser.add_argument("--manifest-path", type=Path, default=_MANIFEST_PATH)
    parser.add_argument("--task-id", default=AGENTIC_TASK_ID)
    parser.add_argument("--repetitions", type=int, default=AGENTIC_REPETITIONS)
    parser.add_argument("--repo-path", type=Path)
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("--marketplace-root", type=Path)
    parser.add_argument("--codemap-bin", type=Path)
    parser.add_argument("--auth-source", type=Path)
    parser.add_argument("--invocation-launcher-path", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--paid-approval", help="exact SHA-256 of the reviewed admitted agentic manifest")
    parser.add_argument("--max-wall-clock-seconds", type=float, default=5400)
    args = parser.parse_args(argv)
    if args.task_id != AGENTIC_TASK_ID:
        parser.error(f"agentic first slice supports only --task-id {AGENTIC_TASK_ID}")
    if args.dry_run:
        _emit_output_legend()
        for line in dry_run(tasks_path=args.tasks_path, manifest_path=args.manifest_path, repetitions=args.repetitions):
            print(line)
        return 0
    required = {
        "--repo-path": args.repo_path,
        "--index-path": args.index_path,
        "--auth-source": args.auth_source,
        "--invocation-launcher-path": args.invocation_launcher_path,
        "--run-dir": args.run_dir,
        "--paid-approval": args.paid_approval,
    }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        parser.error(f"paid Codex agentic execution requires {' '.join(missing)}")
    run_paid(
        repo_path=args.repo_path,
        index_path=args.index_path,
        auth_source=args.auth_source,
        approval_sha256=args.paid_approval,
        run_dir=args.run_dir,
        manifest_path=args.manifest_path,
        marketplace_root=args.marketplace_root,
        codemap_bin=args.codemap_bin,
        invocation_launcher_path=args.invocation_launcher_path,
        max_wall_clock_seconds=args.max_wall_clock_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
