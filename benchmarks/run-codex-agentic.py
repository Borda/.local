#!/usr/bin/env python3
"""Codex agentic provider-parity runner for the locked shared agentic suite.

This module runs every manifest-locked agentic task in the A_plain, B_auto, and
C_strict treatments. It reuses the provider-neutral answer-contract scorer
and the shared Codex native JSONL parser instead of copying either implementation.

``--dry-run`` validates the locked shared provenance and prints the
deterministic task × arm cell plan without reading credentials, invoking a model, or
creating result files. Paid execution is separately admitted only by the agentic
manifest and exact SHA approval; the structural manifest remains an isolated
runtime adapter, never the agentic study definition.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, NoReturn, Sequence

_BENCHMARKS_DIR = Path(__file__).resolve().parent
if str(_BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCHMARKS_DIR))

from _bench_common.presentation import fmt_time, fmt_tok  # noqa: E402
from _bench_codex import runtime as codex_runtime  # noqa: E402
from _bench_common.agentic_contracts import (  # noqa: E402
    AGENTIC_ARMS,
    DEFAULT_REPETITIONS,
    assess_answer_response,
    build_oracle,
    materialize_agentic_prompt,
    parse_labeled_answer as parse_labeled_answer,
    score_answer,
    score_evidence_metrics,
    validate_answer_contract,
)
from _bench_common.provider_parity_contracts import (  # noqa: E402
    ARM_CONTRACTS,
    canonical_result_rows,
    canonical_task_hash,
    fresh_input_tokens,
    semantic_suite_hash,
    token_accounting_inconsistent,
    treatment_adherence,
)


_TASKS_PATH = _BENCHMARKS_DIR / "suites" / "tasks-agentic.json"
_MANIFEST_PATH = _BENCHMARKS_DIR / "manifests" / "codex-agentic.json"
AGENTIC_DEFAULT_REPETITIONS = DEFAULT_REPETITIONS
_NATIVE_HOME_ARM = {
    "A_plain": "A_plain",
    "B_auto": "B_direct_required",
    "C_strict": "C_skill_required",
}
_OUTPUT_LEGEND = (
    "LEGEND\n"
    "  treatments: A_plain=no Codemap, B_auto=CLI available and optional, "
    "C_strict=installed Codemap Skill with compact query required\n"
    "  metrics:\n"
    "      SCORE: mean semantic answer-component score; n/a when no answer can be recovered (higher is better)\n"
    "      EREC: expected-importer recall in all agent text (higher is better)\n"
    "      RREC: expected-importer recall in the final report (higher is better)\n"
    "      DEFF: unbounded expected-importer exposure hits per command (higher is better within the same task)\n"
    "  answer: ✓ strict envelope, △ diagnostic bare-JSON recovery (not poolable), ✗ absent or invalid\n"
    "  status: ✓ completed, ✗ failed\n"
    "  progress: N completed cells / manifest-scoped planned cells\n"
    "  treatment: ✓ assigned arm followed, ✗ assigned arm not followed\n"
    "  codemap-used: ✓ Codemap call observed; ✗ no call observed (A_plain expects none)\n"
    "  input tokens: gross total; cached and fresh details remain in telemetry only (lower is better at equal quality)\n"
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


_structural = _load_sibling("_codex_agentic_structural", "run-codex-structural.py")


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
    quality: Any | None
    evidence: Any | None = None
    answer_error: str = ""
    answer_contract_valid: bool | None = None
    diagnostic_only: bool = False
    answer_pooling_eligible: bool = False
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
    return ArmProbe(arm, codemap_available=True, skill_required=arm == "C_strict")


def prepare_isolated_home(arm: str, **kwargs: Any) -> Any:
    """Create the structural runner's disposable home for a future paid cell.

    The underlying A/B/C homes already prevent host-plugin and credential
    inheritance.  B_auto maps to the direct-Codemap availability home only;
    optional use remains an agentic admission rule, not a home capability.
    No-model dry runs probe the policy without creating a disposable home.
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


def load_agentic_tasks(tasks_path: Path = _TASKS_PATH, manifest_path: Path = _MANIFEST_PATH) -> list[dict[str, Any]]:
    """Load every manifest-locked task after validating suite and task identities."""
    tasks_path = Path(tasks_path)
    manifest_path = Path(manifest_path)
    try:
        suite = json.loads(tasks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("agentic task suite is unavailable or malformed") from exc
    raw_tasks = suite.get("tasks") if isinstance(suite, Mapping) else None
    if not isinstance(raw_tasks, list) or not all(isinstance(task, dict) for task in raw_tasks):
        raise ValueError("agentic task suite requires a task object list")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        suite_lock = manifest["suite"]
        task_locks = manifest["tasks"]
        scope = manifest["preregistered_scope"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("agentic shared manifest is unavailable or malformed") from exc
    if not isinstance(task_locks, list) or not isinstance(scope, Mapping):
        raise ValueError("agentic shared manifest lacks task identities or scope")
    task_locks_by_id = {task.get("id"): task for task in task_locks if isinstance(task, Mapping)}
    task_ids = scope.get("task_ids")
    if not isinstance(task_ids, list) or task_ids != [task.get("id") for task in raw_tasks]:
        raise ValueError("agentic shared task order drifted")
    if (
        suite_lock.get("path") != "benchmarks/suites/tasks-agentic.json"
        or suite_lock.get("raw_sha256") != hashlib.sha256(tasks_path.read_bytes()).hexdigest()
        or suite_lock.get("semantic_suite_sha256") != semantic_suite_hash(raw_tasks)
    ):
        raise ValueError("agentic shared suite identity drifted")
    if set(task_locks_by_id) != set(task_ids):
        raise ValueError("agentic shared task identity set drifted")

    tasks: list[dict[str, Any]] = []
    for raw_task in raw_tasks:
        task_id = str(raw_task["id"])
        task_lock = task_locks_by_id[task_id]
        delivered_prompt = materialize_agentic_prompt(raw_task)
        if (
            task_lock.get("canonical_task_sha256") != canonical_task_hash(raw_task)
            or task_lock.get("prompt_sha256") != hashlib.sha256(delivered_prompt.encode("utf-8")).hexdigest()
        ):
            raise ValueError(f"agentic task identity drifted for {task_id}")
        if raw_task.get("type") != "blast_radius_analysis" or not task_lock.get("effective_scoreable"):
            raise ValueError(f"agentic task {task_id} must retain scoreable blast-radius semantics")
        validate_answer_contract(raw_task)
        tasks.append({**raw_task, "prompt": delivered_prompt})
    return tasks


def parse_agentic_stream(
    stream: str | bytes | Iterable[str | bytes],
    *,
    arm: str,
    task: Mapping[str, Any],
    oracle: Any | None = None,
    repetition: int = 1,
    skill_path: Path | None = None,
    ground_truth: Any | None = None,
) -> AgenticRun:
    """Normalize one native stream and score it with the shared Claude oracle.

    B_auto has optional Codemap use.  C_strict preserves a completed no-call
    row but records compliance/adherence false; aggregation must exclude that
    coordinate rather than erasing its raw evidence.
    """
    if arm not in AGENTIC_ARMS:
        raise ValueError(f"unsupported Codex agentic arm {arm!r}")
    if not isinstance(task.get("id"), str) or not task["id"]:
        raise ValueError("agentic task requires a non-empty id")
    if oracle is None:
        oracle = ground_truth
    if oracle is None:
        raise ValueError("agentic stream scoring requires a shared task oracle")
    if repetition < 1:
        raise ValueError("repetition must be at least 1")
    if arm == "C_strict" and skill_path is None:
        raise ValueError("C_strict requires the exact installed Codemap Skill path")
    if arm != "C_strict" and skill_path is not None:
        raise ValueError("only C_strict accepts a Codemap Skill path")

    skill_bytes = skill_path.read_bytes() if skill_path is not None else b""
    parsed = codex_runtime.parse_codex_jsonl(
        stream,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest() if skill_bytes else "",
    )
    codemap_used = getattr(parsed, "codemap_observed_calls", parsed.codemap_calls) > 0
    contaminated = arm == "A_plain" and codemap_used
    compliance = None
    if arm == "C_strict":
        compliance = bool(parsed.codemap_skill_compact_successful_calls > 0)
    adherence_arm = arm
    adherence = treatment_adherence(
        adherence_arm,
        codemap_use_compliance=compliance,
        contaminated=contaminated,
    )
    report_text = parsed.output_text[parsed.last_tool_text_offset :].lstrip("\n")
    quality: Any | None = None
    evidence: Any | None = None
    answer_error = ""
    answer_contract_valid: bool | None = None
    diagnostic_only = False
    answer_pooling_eligible = False
    if parsed.success:
        assessment = assess_answer_response(task, report_text)
        evidence = score_evidence_metrics(
            oracle,
            exposure_text=parsed.output_text,
            report_text=report_text,
            tool_calls=parsed.command_calls,
        )
        answer_error = assessment.error or ""
        answer_contract_valid = assessment.strict_envelope_valid
        diagnostic_only = assessment.diagnostic_only
        answer_pooling_eligible = assessment.pooling_eligible
        if assessment.answer is not None:
            quality = score_answer(
                oracle,
                assessment.answer,
                exposure_text=parsed.output_text,
                report_text=report_text,
                tool_calls=parsed.command_calls,
            )
    return AgenticRun(
        arm=arm,
        task_id=str(task["id"]),
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
        error=parsed.error or answer_error,
        error_type=parsed.error_type if not answer_error else "answer_contract_failed",
        output_text=parsed.output_text,
        report_text=report_text,
        quality=quality,
        evidence=evidence,
        answer_error=answer_error,
        answer_contract_valid=answer_contract_valid,
        diagnostic_only=diagnostic_only,
        answer_pooling_eligible=answer_pooling_eligible,
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


def resolve_agentic_scope(
    manifest_path: Path = _MANIFEST_PATH,
    *,
    task_ids: Sequence[str] | None = None,
    repetitions: int | None = None,
) -> dict[str, Any]:
    """Resolve and hash one manifest-bound Codex agentic coordinate scope.

    The manifest is the immutable source lock. A caller may explicitly narrow
    its ordered task set or increase positive repetitions, but the derived
    scope hash binds every resulting coordinate and its per-cell timeout.
    """
    manifest_path = Path(manifest_path)
    manifest = _read_agentic_manifest(manifest_path)
    preregistered = manifest.get("preregistered_scope")
    if not isinstance(preregistered, Mapping):
        raise ValueError("Codex agentic manifest lacks preregistered scope")
    repetitions = preregistered.get("repetitions") if repetitions is None else repetitions
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("agentic repetitions must be at least 1")
    locked_task_ids = preregistered.get("task_ids")
    if not isinstance(locked_task_ids, list) or not all(isinstance(task_id, str) for task_id in locked_task_ids):
        raise ValueError("Codex agentic manifest has invalid task IDs")
    selected_task_ids = list(locked_task_ids if task_ids is None else task_ids)
    if not selected_task_ids or len(set(selected_task_ids)) != len(selected_task_ids):
        raise ValueError("agentic scope requires unique manifest-bound task IDs")
    if any(task_id not in locked_task_ids for task_id in selected_task_ids):
        raise ValueError("agentic scope includes a task outside the manifest")
    ordered_task_ids = [task_id for task_id in locked_task_ids if task_id in set(selected_task_ids)]
    coordinate_timeout_seconds = preregistered.get("coordinate_timeout_seconds")
    if type(coordinate_timeout_seconds) is not int or coordinate_timeout_seconds < 1:
        raise ValueError("Codex agentic manifest must lock a positive per-cell timeout")
    total_cells = len(ordered_task_ids) * len(AGENTIC_ARMS) * repetitions
    payload = {
        "manifest_sha256": _manifest_sha256(manifest_path),
        "experiment_revision": manifest.get("experiment_revision"),
        "task_ids": ordered_task_ids,
        "arms": list(AGENTIC_ARMS),
        "repetitions": repetitions,
        "coordinate_timeout_seconds": coordinate_timeout_seconds,
        "total_cells": total_cells,
        "nonpoolable": True,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "scope_sha256": hashlib.sha256(encoded).hexdigest()}


def validate_paid_admission(manifest_path: Path, approval_sha256: str) -> dict[str, Any]:
    """Fail closed unless the agentic manifest admits the default paid study."""
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
    task_ids = scope.get("task_ids")
    arms = scope.get("arms")
    repetitions = scope.get("repetitions")
    coordinate_timeout = scope.get("coordinate_timeout_seconds")
    expected_cells = (
        len(task_ids) * len(arms) * repetitions
        if isinstance(task_ids, list)
        and task_ids
        and all(isinstance(task_id, str) for task_id in task_ids)
        and len(task_ids) == len(set(task_ids))
        and isinstance(arms, list)
        and arms == list(AGENTIC_ARMS)
        and type(repetitions) is int
        and repetitions > 0
        and type(coordinate_timeout) is int
        and coordinate_timeout > 0
        else None
    )
    if (
        manifest.get("schema_version") != "codex-agentic-manifest-v1"
        or admission.get("paid_execution") != "admitted"
        or expected_cells is None
        or scope.get("total_cells") != expected_cells
        or not isinstance(model.get("name"), str)
        or not model.get("name")
        or not isinstance(model.get("reasoning_effort"), str)
        or not model.get("reasoning_effort")
        or model.get("strict_config") is not True
    ):
        raise ValueError("Codex agentic manifest does not admit the default shared paid scope")
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


def _agentic_envelope(arm: str, task: Mapping[str, Any]) -> str:
    """Return the arm instruction and labelled answer contract for one task."""
    if arm == "A_plain":
        treatment = "Codemap is absent and inaccessible. Solve using ordinary provider tools only."
    elif arm == "B_auto":
        treatment = (
            "Codemap's direct CLI is available as $CODEMAP_BIN. Use it when useful, but ordinary reads and shell "
            "tools remain allowed and no Codemap call is required."
        )
    elif arm == "C_strict":
        treatment = (
            "The installed Codemap Skill is bound immutably for this treatment. Use its smallest complete-query "
            "guidance, then complete at least one standalone successful $CODEMAP_BIN query --compact structural query; "
            "do not prefix, assign, wrap, or combine the credited query with shell work. "
            "Other reads and shell commands remain allowed."
        )
    else:
        raise ValueError(f"unsupported Codex agentic arm {arm!r}")
    return treatment


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
        agentic_manifest_path: Path | None = None,
        transport: Callable[..., str | bytes | Iterable[str | bytes]] | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.index_path = Path(index_path).resolve()
        self.agentic_manifest = agentic_manifest
        self.agentic_manifest_path = Path(agentic_manifest_path or _MANIFEST_PATH)
        self.transport = transport
        model = agentic_manifest.get("model")
        scope = agentic_manifest.get("preregistered_scope")
        if not isinstance(model, Mapping) or not isinstance(scope, Mapping):
            raise ValueError("Codex agentic manifest lacks model or per-cell timeout")
        self.adapter = _structural.CodexRunner(
            str(model["name"]),
            self.repo_path,
            reasoning_effort=str(model["reasoning_effort"]),
            index_path=self.index_path,
            timeout=float(scope["coordinate_timeout_seconds"]),
            marketplace_root=marketplace_root,
            codemap_bin=codemap_bin,
            manifest_path=adapter_manifest_path,
            auth_source=auth_source,
        )

    def close(self) -> None:
        """Release the adapter's private credential chain."""
        self.adapter.close()

    def preflight_snapshot_bound_admission(self) -> None:
        """Exercise initial and later snapshot-bound B/C admission without transport."""
        with tempfile.TemporaryDirectory(prefix="codex-agentic-dry-run-") as temporary_root:
            run_dir = Path(temporary_root)
            self.create_input_snapshot(
                run_dir,
                manifest_path=self.agentic_manifest_path,
                invocation_launcher_path=_BENCHMARKS_DIR / "run-all.sh",
            )
            for arm in ("B_direct_required", "C_skill_required"):
                home = self.adapter._prepare_verified_home(arm)
                try:
                    _structural.probe_arm_home(home)
                finally:
                    if home.coordination_path is not None:
                        _structural._cleanup_coordination_root(home.coordination_path)
                    home.cleanup()

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
        snapshot_root = Path(run_dir) / "inputs"
        if snapshot_root.exists():
            raise FileExistsError(snapshot_root)
        # Reserve evidence before the first disposable home so an admission
        # failure survives the home cleanup that records it.
        self.adapter._runtime_evidence_path = Path(run_dir) / "runtime-isolation.jsonl"
        self.adapter._runtime_evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.adapter._runtime_evidence_path.touch(exist_ok=False)
        self.adapter._runtime_evidence_path.chmod(0o600)
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
                elif arm == "C_strict":
                    if home.codemap_plugin_path is None or home.codex_rig_path is None:
                        raise RuntimeError("C_strict snapshot lacks verified Codemap or Codex Rig package")
                    arm_archives[arm] = {"codemap-py": home.codemap_plugin_path, "codex-rig": home.codex_rig_path}
                    if home.codemap_context_path is not None:
                        arm_files[arm]["codemap-context.json"] = home.codemap_context_path
                    self.adapter._record_runtime_success(_NATIVE_HOME_ARM[arm], home)
            snapshot = _write_agentic_input_snapshot(
                snapshot_root,
                manifest_path=Path(manifest_path),
                tasks_path=_TASKS_PATH,
                runner_path=Path(__file__),
                invocation_launcher_path=invocation_launcher_path,
                index_path=self.index_path,
                auth_source=self.adapter.auth_source,
                arm_archives=arm_archives,
                arm_files=arm_files,
            )
            if isinstance(snapshot.get("path"), str):
                self.adapter._bind_runtime_snapshot(
                    snapshot_root,
                    {
                        "B_direct_required": {"direct-cli": snapshot_root / "B_auto" / "direct-cli"},
                        "C_skill_required": {
                            "codemap-py": snapshot_root / "C_strict" / "codemap-py",
                            "codex-rig": snapshot_root / "C_strict" / "codex-rig",
                        },
                    },
                )
            return snapshot
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

    def run(
        self,
        task: Mapping[str, Any],
        arm: str,
        *,
        repetition: int,
        oracle: Any | None = None,
        ground_truth: Any | None = None,
    ) -> AgenticRun:
        """Run one agentic coordinate, retrying only empty retryable transport failures."""
        if oracle is None:
            oracle = ground_truth
        if oracle is None:
            raise ValueError("agentic runner requires a shared task oracle")
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
            command = self.adapter.build_command(f"{_agentic_envelope(arm, task)}\n\n{task['prompt']}")
            for attempt in range(3):
                remaining = self.adapter.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    timeout_stream = json.dumps({"type": "error", "error": "cell timeout", "error_type": "timeout"})
                    result = parse_agentic_stream(
                        timeout_stream,
                        arm=arm,
                        task=task,
                        oracle=oracle,
                        repetition=repetition,
                        skill_path=home.codemap_skill_path if arm == "C_strict" and home is not None else None,
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
                    oracle=oracle,
                    repetition=repetition,
                    skill_path=home.codemap_skill_path if arm == "C_strict" and home is not None else None,
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
        if arm == "C_strict":
            _structural._write_frozen_marketplace(snapshot_root, arm, entries)
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
    codex_runtime.render_result_rows(f"{_OUTPUT_LEGEND}\n".splitlines(keepends=True), destination)


def _format_plan(task_id: str, repetition: int, arm: str) -> str:
    """Render one deterministic dry-run coordinate."""
    return f"PLAN    {task_id:<5}  rep={repetition}  {arm}"


def dry_run(
    *,
    tasks_path: Path = _TASKS_PATH,
    manifest_path: Path = _MANIFEST_PATH,
    task_ids: Sequence[str] | None = None,
    repetitions: int = AGENTIC_DEFAULT_REPETITIONS,
) -> list[str]:
    """Validate one resolved scope and return its exact no-model cell plan."""
    scope = resolve_agentic_scope(manifest_path, task_ids=task_ids, repetitions=repetitions)
    tasks = load_agentic_tasks(tasks_path, manifest_path)
    tasks_by_id = {task["id"]: task for task in tasks}
    if set(AGENTIC_ARMS) != set(ARM_CONTRACTS):
        raise ValueError("agentic arm contracts drifted from the shared provider policy")
    lines = [_format_probe(probe_arm(arm)) for arm in AGENTIC_ARMS]
    for task_id in scope["task_ids"]:
        if task_id not in tasks_by_id:
            raise ValueError(f"agentic scope task {task_id} is not loadable")
        for repetition in range(1, repetitions + 1):
            for arm in AGENTIC_ARMS:
                lines.append(_format_plan(task_id, repetition, arm))
    return lines


# ``main``'s ``--dry-run`` flag binds the name ``dry_run`` inside its body, so the planner is
# reached there through this module-level alias; ``dry_run`` itself stays the public entry point.
_dry_run_plan = dry_run


def _append_telemetry(path: Path, run: AgenticRun, execution_index: int) -> None:
    """Append one immutable raw agentic row before updating derived evidence."""
    row = vars(run).copy()
    if run.quality is not None:
        row["quality"] = {**vars(run.quality), "components": dict(run.quality.components)}
    if run.evidence is not None:
        row["evidence"] = vars(run.evidence)
    row["execution_index"] = execution_index
    row["fresh_input_tokens"] = fresh_input_tokens(run.input_tokens, run.cached_input_tokens)
    row["token_accounting_inconsistent"] = token_accounting_inconsistent(run.input_tokens, run.cached_input_tokens)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_canonical_telemetry(raw_path: Path, task_ids: Sequence[str]) -> str:
    """Publish the derived agentic canonical order without rewriting raw JSONL."""
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line]
    canonical = canonical_result_rows(rows, task_order=task_ids, arm_order=AGENTIC_ARMS)
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
    """Refresh result checksums while excluding the separately validated source archive."""
    source_root = run_dir / ".launcher" / "source"
    files = [
        path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "checksums.sha256" and not path.is_relative_to(source_root)
    ]
    payload = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run_dir).as_posix()}\n" for path in files
    )
    (run_dir / "checksums.sha256").write_text(payload, encoding="utf-8")


def _runtime_plugin_identities_are_valid(identities: Mapping[str, Any]) -> bool:
    """Return whether identities exactly describe the two required locked plugins."""
    if set(identities) != {"codemap-py", "codex-rig"}:
        return False
    for identity in identities.values():
        if not isinstance(identity, Mapping):
            return False
        version = identity.get("version")
        manifest_sha256 = identity.get("manifest_sha256")
        if (
            not isinstance(version, str)
            or not version
            or not isinstance(manifest_sha256, str)
            or len(manifest_sha256) != 64
            or any(character not in "0123456789abcdef" for character in manifest_sha256)
        ):
            return False
    return True


def _attest_runtime_isolation(path: Path) -> None:
    """Require verified, non-secret runtime identity evidence before paid cells run."""
    try:
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("runtime isolation evidence is unavailable or malformed") from exc
    if not any(
        isinstance(row, Mapping)
        and row.get("arm") == "C_skill_required"
        and row.get("status") == "verified"
        and isinstance(expected := row.get("expected_plugin_identities"), Mapping)
        and isinstance(observed := row.get("observed_plugin_identities"), Mapping)
        and expected == observed
        and _runtime_plugin_identities_are_valid(expected)
        and _runtime_plugin_identities_are_valid(observed)
        for row in rows
    ):
        raise RuntimeError("runtime isolation evidence lacks a verified C expected/observed identity match")


def _progress_line(execution_index: int, total_cells: int, run: AgenticRun) -> str:
    """Render one compact agentic result after its immutable telemetry row is persisted."""
    status = "✓" if run.success else "✗"
    treatment = "✓" if run.treatment_adherence else "✗"
    used = "✓" if run.codemap_used else "✗"
    score = "n/a" if run.quality is None else f"{run.quality.quality_score:.3f}"
    answer = "✓" if run.answer_contract_valid else ("△" if run.diagnostic_only else "✗")
    erec = run.evidence.erec if run.evidence is not None else 0.0
    rrec = run.evidence.rrec if run.evidence is not None else 0.0
    deff = run.evidence.deff if run.evidence is not None else 0.0
    return (
        f"({execution_index}/{total_cells}) {status}  {run.task_id:<5}  rep={run.repetition}  {run.arm:<10}"
        f"  in={fmt_tok(run.input_tokens):>6}  out={fmt_tok(run.output_tokens):>6}"
        f"  time={fmt_time(run.elapsed_s):>5}  SCORE={score}  EREC={erec:.3f}"
        f"  RREC={rrec:.3f}  DEFF={deff:.3f}  answer:{answer}  treatment:{treatment}  codemap-used:{used}"
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
    tasks: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
    invocation_launcher_path: Path,
) -> dict[str, Any]:
    """Build compact provenance before the first paid coordinate is scheduled."""
    manifest = _read_agentic_manifest(manifest_path)
    model = manifest["model"]
    coordinates = [
        {"task_id": task["id"], "repetition": repetition, "arm": arm}
        for task in tasks
        for repetition in range(1, int(scope["repetitions"]) + 1)
        for arm in AGENTIC_ARMS
    ]
    return {
        "schema": "codex-agentic-run-v1",
        "status": "running",
        "started_at": _structural._utc_now(),
        "persisted_cells": 0,
        "last_persisted_coordinate": None,
        "error": None,
        "manifest": {"path": str(manifest_path.resolve()), "sha256": _manifest_sha256(manifest_path)},
        "approval_sha256": approval_sha256,
        "scope": dict(scope),
        "invocation_launcher": {"path": str(invocation_launcher_path.resolve())},
        "execution": {
            "model": model["name"],
            "reasoning_effort": model["reasoning_effort"],
            "codex_cli_observed_version": os.environ.get("CODEX_CLI_OBSERVED_VERSION"),
            "cell_wall_clock_seconds": scope["coordinate_timeout_seconds"],
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
    """Allow only run-all's verified launcher and frozen source before a paid run starts."""
    expected_launcher = run_dir / ".launcher" / "run-all.sh"
    source_root = expected_launcher.parent / "source"
    source_manifest = expected_launcher.parent / "source.sha256"
    if invocation_launcher_path.absolute() != expected_launcher.absolute():
        raise FileExistsError(run_dir)
    try:
        entries = {entry.name for entry in run_dir.iterdir()}
        launcher_entries = {entry.name for entry in expected_launcher.parent.iterdir()}
        source_metadata = source_root.lstat()
        source_manifest_metadata = source_manifest.lstat()
    except OSError as exc:
        raise FileExistsError(run_dir) from exc
    if (
        entries != {".launcher"}
        or launcher_entries != {"run-all.sh", "source", "source.sha256"}
        or not stat.S_ISDIR(source_metadata.st_mode)
        or not stat.S_ISREG(source_manifest_metadata.st_mode)
    ):
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
    task_ids: Sequence[str] | None = None,
    repetitions: int | None = None,
    scope_sha256: str | None = None,
    runner_factory: Callable[..., Any] | None = None,
) -> Path:
    """Execute one admitted shared-task scope with immutable partial evidence.

    Test fixtures may inject ``runner_factory``; production always uses the
    structural adapter for credential lifecycle, permissions, and native Codex
    transport.  The function never records the auth path or credential bytes.
    """
    if not auth_source:
        raise ValueError("paid Codex agentic execution requires an auth source")
    if invocation_launcher_path is None:
        raise ValueError("paid Codex agentic execution requires the invocation launcher path")
    scope = resolve_agentic_scope(manifest_path, task_ids=task_ids, repetitions=repetitions)
    repetitions = int(scope["repetitions"])
    preregistered = _read_agentic_manifest(manifest_path)["preregistered_scope"]
    is_default_scope = task_ids is None and repetitions == preregistered["repetitions"]
    if is_default_scope:
        manifest = validate_paid_admission(manifest_path, approval_sha256)
        if scope_sha256 is not None and scope_sha256 != scope["scope_sha256"]:
            raise ValueError("default agentic scope hash does not match the manifest-bound scope")
    else:
        manifest = validate_paid_admission(manifest_path, _manifest_sha256(Path(manifest_path)))
        if approval_sha256 != scope["scope_sha256"] or scope_sha256 != scope["scope_sha256"]:
            raise ValueError("nondefault agentic scope requires its exact derived scope SHA-256 approval")
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
    all_tasks = load_agentic_tasks(_TASKS_PATH, manifest_path)
    tasks_by_id = {task["id"]: task for task in all_tasks}
    tasks = [tasks_by_id[task_id] for task_id in scope["task_ids"]]
    metadata = _initial_metadata(
        manifest_path=Path(manifest_path),
        approval_sha256=approval_sha256,
        run_dir=run_dir,
        tasks=tasks,
        scope=scope,
        invocation_launcher_path=invocation_launcher_path,
    )
    _structural._write_run_metadata(metadata_path, metadata)
    _emit_output_legend()
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(_OUTPUT_LEGEND + "\n")
    factory = runner_factory or AgenticCodexRunner
    runner: Any | None = None
    try:
        oracles = {task["id"]: build_oracle(task, repo_path) for task in tasks}
        runner = factory(
            repo_path=repo_path,
            index_path=index_path,
            marketplace_root=marketplace_root,
            codemap_bin=codemap_bin,
            auth_source=Path(auth_source),
            adapter_manifest_path=adapter_manifest_path,
            agentic_manifest=manifest,
            agentic_manifest_path=Path(manifest_path),
        )
        snapshot_builder = getattr(runner, "create_input_snapshot", None)
        if not callable(snapshot_builder):
            raise RuntimeError("agentic runner must create and attest an immutable runtime snapshot")
        metadata["inputs"] = {
            "snapshot": snapshot_builder(
                run_dir, manifest_path=Path(manifest_path), invocation_launcher_path=invocation_launcher_path
            )
        }
        runtime_evidence = run_dir / "runtime-isolation.jsonl"
        _attest_runtime_isolation(runtime_evidence)
        metadata["artifacts"]["runtime_isolation_jsonl"] = str(runtime_evidence.resolve())
        metadata["artifacts"]["runtime_isolation_sha256"] = hashlib.sha256(runtime_evidence.read_bytes()).hexdigest()
        _structural._write_run_metadata(metadata_path, metadata)
        _write_checksums(run_dir)
        for task in tasks:
            for repetition in range(1, repetitions + 1):
                for arm in AGENTIC_ARMS:
                    run = runner.run(task, arm, repetition=repetition, oracle=oracles[task["id"]])
                    _validate_agentic_runtime(manifest, repo_path, index_path)
                    _structural._validate_invocation_launcher(invocation_launcher_path, launcher_hash)
                    _append_telemetry(raw_path, run, int(metadata["persisted_cells"]))
                    metadata["persisted_cells"] = int(metadata["persisted_cells"]) + 1
                    metadata["last_persisted_coordinate"] = {
                        "task_id": task["id"],
                        "repetition": repetition,
                        "arm": arm,
                    }
                    metadata["artifacts"]["canonical_telemetry_sha256"] = _write_canonical_telemetry(
                        raw_path, scope["task_ids"]
                    )
                    _structural._write_run_metadata(metadata_path, metadata)
                    _emit_run_line(
                        run_log,
                        _progress_line(int(metadata["persisted_cells"]), int(scope["total_cells"]), run),
                    )
                    _write_checksums(run_dir)
        metadata["status"] = "completed"
        metadata["completed_at"] = _structural._utc_now()
        _structural._write_run_metadata(metadata_path, metadata)
        _emit_run_line(
            run_log,
            f"SUMMARY  status=completed  persisted_cells={metadata['persisted_cells']}/{scope['total_cells']}",
        )
        _write_checksums(run_dir)
        return run_dir
    except BaseException as exc:
        metadata["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        metadata["completed_at"] = _structural._utc_now()
        metadata["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        _structural._write_run_metadata(metadata_path, metadata)
        _emit_run_line(
            run_log,
            f"SUMMARY  status={metadata['status']}  persisted_cells={metadata['persisted_cells']}/{scope['total_cells']}",
        )
        _write_checksums(run_dir)
        raise
    finally:
        if runner is not None:
            _structural._close_runner(runner)


def _cli_error(message: str) -> NoReturn:
    """Reject one invocation exactly as the previous argparse parser did.

    Args:
        message: Human-readable reason the invocation cannot proceed.

    Raises:
        SystemExit: Always, carrying argparse's usage-error status 2.

    Examples:
        >>> try:
        ...     _cli_error("bad invocation")
        ... except SystemExit as exit_status:
        ...     exit_status.code
        2
    """
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _normalize_task_ids(task_id: str | Sequence[str] | None) -> list[str] | None:
    """Normalize one Fire ``--task-id`` value into an ordered task-ID list.

    The comma-separated ``--task-id BA-01,BA-02`` form is split here rather than
    relying on Fire: Fire only splits a comma-joined value when it parses as a
    Python literal, which ``BA-01,BA-02`` does not, so it arrives as one string.
    A value Fire did split (a sequence) is accepted unchanged. An empty token is
    rejected here rather than silently dropped, so a stray comma cannot quietly
    narrow the resolved scope.

    Args:
        task_id: Raw Fire value: ``None``, one comma-separated string, or a sequence.

    Returns:
        The selected task IDs, or ``None`` when no task was selected.

    Raises:
        SystemExit: When any comma-separated token is empty.

    Examples:
        >>> _normalize_task_ids(None) is None
        True
        >>> _normalize_task_ids("BA-01")
        ['BA-01']
        >>> _normalize_task_ids("BA-01,BA-02")
        ['BA-01', 'BA-02']
        >>> _normalize_task_ids(("BA-01", "BA-02"))
        ['BA-01', 'BA-02']
    """
    if task_id is None:
        return None
    values = task_id if isinstance(task_id, (list, tuple)) else [task_id]
    task_ids = [token.strip() for value in values for token in str(value).split(",")]
    if not task_ids or any(not selected for selected in task_ids):
        _cli_error("--task-id values cannot be empty")
    return task_ids


def _require_paid_arguments(**arguments: Any) -> None:
    """Reject a paid invocation that omits any required command-line argument.

    Args:
        **arguments: Parameter name to supplied value, in flag order; a ``None``
            value marks that flag as missing.

    Raises:
        SystemExit: When at least one required flag was not supplied.

    Examples:
        >>> _require_paid_arguments(repo_path=Path("."), run_dir=Path("."))
        >>> try:
        ...     _require_paid_arguments(repo_path=None, run_dir=Path("."))
        ... except SystemExit as exit_status:
        ...     exit_status.code
        2
    """
    missing = [f"--{name.replace('_', '-')}" for name, value in arguments.items() if value is None]
    if missing:
        _cli_error(f"paid Codex agentic execution requires {' '.join(missing)}")


def _require_dry_run_admission_arguments(**arguments: Any) -> None:
    """Reject a runtime dry run that cannot exercise isolated B/C admission."""
    missing = [f"--{name.replace('_', '-')}" for name, value in arguments.items() if value is None]
    if missing:
        _cli_error(f"Codex agentic dry-run admission requires {' '.join(missing)}")


def main(  # noqa: PLR0913 — fire CLI adapter: every param is a keyword flag with a default (0 required)
    dry_run: bool = False,
    resolve_scope: bool = False,
    tasks_path: Path = _TASKS_PATH,
    manifest_path: Path = _MANIFEST_PATH,
    task_id: str | Sequence[str] | None = None,
    repetitions: int | None = None,
    repo_path: Path | None = None,
    index_path: Path | None = None,
    marketplace_root: Path | None = None,
    codemap_bin: Path | None = None,
    auth_source: Path | None = None,
    invocation_launcher_path: Path | None = None,
    run_dir: Path | None = None,
    paid_approval: str | None = None,
    scope_sha256: str | None = None,
) -> None:
    """Run a no-model scope preflight or a separately admitted paid study.

    Args:
        dry_run: Print the resolved no-model cell plan and exit.
        resolve_scope: Print the resolved scope JSON and exit.
        tasks_path: Locked shared agentic task suite.
        manifest_path: Locked Codex agentic manifest.
        task_id: One manifest-bound task ID, or several as a single comma-separated
            value (``--task-id BA-01,BA-02``); absent selects the whole locked scope.
        repetitions: Positive repeat count per task and arm.
        repo_path: Locked agentic target repository root (paid execution only).
        index_path: Locked frozen Codemap index (paid execution only).
        marketplace_root: Optional verified plugin marketplace root.
        codemap_bin: Optional verified Codemap CLI path.
        auth_source: Codex credential source for the isolated homes (paid execution only).
        invocation_launcher_path: run-all launcher snapshot inside the run directory (paid execution only).
        run_dir: Empty run directory holding only that launcher snapshot (paid execution only).
        paid_approval: Exact SHA-256 of the reviewed admitted agentic manifest.
        scope_sha256: Exact SHA-256 of a nondefault resolved scope.

    Raises:
        SystemExit: When the invocation is rejected before any paid coordinate runs.

    Examples:
        >>> main.__name__
        'main'
    """
    # fire passes CLI strings through regardless of annotation — coerce every typed argument.
    task_ids = _normalize_task_ids(task_id)
    manifest_path = Path(manifest_path)
    repetitions = None if repetitions is None else int(repetitions)
    paid_approval = None if paid_approval is None else str(paid_approval)
    scope_sha256 = None if scope_sha256 is None else str(scope_sha256)
    try:
        scope = resolve_agentic_scope(manifest_path, task_ids=task_ids, repetitions=repetitions)
    except ValueError as exc:
        _cli_error(str(exc))
    repetitions = int(scope["repetitions"])
    if scope_sha256 is not None and scope_sha256 != scope["scope_sha256"]:
        _cli_error("--scope-sha256 does not match the resolved agentic scope")
    if resolve_scope:
        print(json.dumps(scope, sort_keys=True))
        return
    if dry_run:
        _require_dry_run_admission_arguments(
            repo_path=repo_path,
            index_path=index_path,
            marketplace_root=marketplace_root,
            codemap_bin=codemap_bin,
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _cli_error(f"agentic manifest is unavailable or malformed: {exc}")
        if not isinstance(manifest, Mapping):
            _cli_error("agentic manifest must be a JSON object")
        runtime = manifest.get("runtime_isolation")
        if not isinstance(runtime, Mapping) or not isinstance(runtime.get("manifest"), str):
            _cli_error("Codex agentic manifest lacks a structural runtime adapter manifest")
        adapter_manifest_path = (_BENCHMARKS_DIR.parent / runtime["manifest"]).resolve()
        if not adapter_manifest_path.is_file():
            _cli_error("Codex agentic structural runtime adapter manifest is unavailable")
        try:
            runner = AgenticCodexRunner(
                repo_path=Path(repo_path),
                index_path=Path(index_path),
                marketplace_root=Path(marketplace_root),
                codemap_bin=Path(codemap_bin),
                auth_source=None,
                adapter_manifest_path=adapter_manifest_path,
                agentic_manifest=manifest,
                agentic_manifest_path=manifest_path,
            )
            try:
                runner.preflight_snapshot_bound_admission()
            finally:
                runner.close()
        except ValueError as exc:
            _cli_error(str(exc))
        _emit_output_legend()
        for line in _dry_run_plan(
            tasks_path=Path(tasks_path),
            manifest_path=manifest_path,
            task_ids=task_ids,
            repetitions=repetitions,
        ):
            print(line)
        return
    _require_paid_arguments(
        repo_path=repo_path,
        index_path=index_path,
        auth_source=auth_source,
        invocation_launcher_path=invocation_launcher_path,
        run_dir=run_dir,
        paid_approval=paid_approval,
    )
    run_paid(
        repo_path=Path(repo_path),
        index_path=Path(index_path),
        auth_source=Path(auth_source),
        approval_sha256=paid_approval,
        run_dir=Path(run_dir),
        manifest_path=manifest_path,
        marketplace_root=None if marketplace_root is None else Path(marketplace_root),
        codemap_bin=None if codemap_bin is None else Path(codemap_bin),
        invocation_launcher_path=Path(invocation_launcher_path),
        task_ids=task_ids,
        repetitions=repetitions,
        scope_sha256=scope_sha256,
    )


if __name__ == "__main__":
    from fire import Fire

    Fire(main)
