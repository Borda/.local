#!/usr/bin/env python3
"""Build or verify the no-model Codex BA-01 agentic manifest.

The manifest freezes the shared task/prompt/scoring identity before any paid
Codex agentic run.  It intentionally records no credential paths or auth
material.  ``--check`` is read-only and fails closed on generated-byte drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
MANIFESTS = BENCHMARKS / "manifests"
SOURCE_MANIFEST = MANIFESTS / "provider-parity-methodology.json"
TASKS_PATH = BENCHMARKS / "suites" / "tasks-agentic.json"
OUTPUT_MANIFEST = MANIFESTS / "codex-agentic.json"
OUTPUT_HUMAN_MANIFEST = MANIFESTS / "codex-agentic.md"
EXPERIMENT_ID = "codex-agentic-ba01"
EXPERIMENT_REVISION = "codex-agentic-ba01-review-ready-2026-08-04"
TASK_ID = "BA-01"
ARMS = ("A_plain", "B_auto", "C_required")
REPETITIONS = 3
COORDINATE_TIMEOUT_SECONDS = 600

sys.path.insert(0, str(BENCHMARKS))
from provider_parity_contracts import canonical_task_hash, prompt_hash, semantic_suite_hash  # noqa: E402


def _sha256(path: Path) -> str:
    """Return one required input's exact SHA-256 digest."""
    if not path.is_file():
        raise ValueError(f"required manifest input is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object and reject another root shape."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return payload


def _ba01_task() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the raw and methodology-locked BA-01 rows after identity checks."""
    suite = _load_json(TASKS_PATH)
    raw_tasks = suite.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("agentic suite requires a tasks list")
    matches = [task for task in raw_tasks if isinstance(task, dict) and task.get("id") == TASK_ID]
    if len(matches) != 1:
        raise ValueError("agentic suite must contain exactly one BA-01 task")
    raw_task = matches[0]
    source = _load_json(SOURCE_MANIFEST)
    suites = source.get("suites")
    if not isinstance(suites, list):
        raise ValueError("methodology manifest requires suites")
    locked_task: dict[str, Any] | None = None
    for source_suite in suites:
        if source_suite.get("path") != "benchmarks/suites/tasks-agentic.json":
            continue
        locked_task = next((task for task in source_suite.get("tasks", []) if task.get("id") == TASK_ID), None)
        break
    if locked_task is None:
        raise ValueError("methodology manifest has no locked BA-01 task")
    if canonical_task_hash(raw_task) != locked_task.get("canonical_task_sha256"):
        raise ValueError("BA-01 canonical task identity drifted")
    if prompt_hash(raw_task) != locked_task.get("prompt_sha256"):
        raise ValueError("BA-01 prompt identity drifted")
    if semantic_suite_hash(raw_tasks) != next(
        suite["semantic_suite_sha256"]
        for suite in suites
        if suite.get("path") == "benchmarks/suites/tasks-agentic.json"
    ):
        raise ValueError("agentic semantic suite identity drifted")
    return raw_task, locked_task


def _artifact_hashes() -> dict[str, str]:
    """Lock the benchmark runner, shared scorer, plugin, and runtime bytes."""
    paths = {
        "codemap_plugin_manifest": "plugins/codemap-py/.codex-plugin/plugin.json",
        "codemap_query_skill": "plugins/codemap-py/codex-skills/query-code/SKILL.md",
        "codemap_launcher": "plugins/codemap-py/bin/codemap-py",
        "codex_rig_plugin_manifest": "plugins/codex-rig/.codex-plugin/plugin.json",
        "codex_rig_package_manifest": "plugins/codex-rig/package-manifest.json",
        "codex_rig_adapter": "plugins/codex-rig/shared/codemap_adapter.py",
        "codex_rig_contract": "plugins/codex-rig/shared/codemap-contract.md",
        "codex_agentic_runner": "benchmarks/run-codex-agentic.py",
        "codex_structural_runner": "benchmarks/run-codex-structural.py",
        "codex_structural_manifest": "benchmarks/manifests/codex-integration.json",
        "claude_agentic_runner": "benchmarks/run-claude-agentic.py",
        "run_all": "benchmarks/run-all.sh",
    }
    return {name: _sha256(ROOT / relative_path) for name, relative_path in paths.items()}


def _build_manifest() -> dict[str, Any]:
    """Build one deterministic BA-01 manifest from locked repository inputs."""
    source = _load_json(SOURCE_MANIFEST)
    raw_task, locked_task = _ba01_task()
    suite_lock = next(suite for suite in source["suites"] if suite["path"] == "benchmarks/suites/tasks-agentic.json")
    artifact_hashes = _artifact_hashes()
    task_identity = {
        "id": TASK_ID,
        "type": raw_task["type"],
        "difficulty": raw_task["difficulty"],
        "primary_module": raw_task["primary_module"],
        "canonical_task_sha256": locked_task["canonical_task_sha256"],
        "prompt_sha256": locked_task["prompt_sha256"],
        "prompt": raw_task["prompt"],
        "oracle_class": locked_task["oracle_class"],
        "effective_scoreable": locked_task["effective_scoreable"],
        "headline_eligible_v1": locked_task["headline_eligible_v1"],
    }
    cells = len(ARMS) * REPETITIONS
    return {
        "experiment_id": EXPERIMENT_ID,
        "experiment_revision": EXPERIMENT_REVISION,
        "schema_version": "codex-agentic-manifest-v1",
        "status": "review_ready_paid_execution_pending_human_launch",
        "model": {"name": "gpt-5.6-luna", "reasoning_effort": "high", "strict_config": True},
        "target_source": source["target_source"],
        "frozen_index_contract": {
            "path": source["index"]["path"],
            "raw_sha256": source["index"]["raw_sha256"],
            "git_sha": source["index"]["git_sha"],
            "scan_version": source["index"]["scan_version"],
            "module_count": source["index"]["module_count"],
        },
        "suite": {
            "path": "benchmarks/suites/tasks-agentic.json",
            "raw_sha256": suite_lock["raw_sha256"],
            "semantic_suite_sha256": suite_lock["semantic_suite_sha256"],
            "task_count": suite_lock["task_count"],
            "task_ids": suite_lock["ordered_task_ids"],
        },
        "task": task_identity,
        "arms": {
            "A_plain": {
                "codemap_available": False,
                "requirement": "No Codemap package, launcher, or Skill is available; no Codemap call is valid.",
                "pooling": "eligible only when all other admission checks pass",
            },
            "B_auto": {
                "codemap_available": True,
                "requirement": "Codemap is available through the plain CLI; use is optional and adoption is measured.",
                "no_call_valid": True,
                "pooling": "eligible only when all other admission checks pass",
            },
            "C_required": {
                "codemap_available": True,
                "requirement": "Read the exact installed Skill before a successful compact query.",
                "skill_path": "plugins/codemap-py/codex-skills/query-code/SKILL.md",
                "no_call_valid": False,
                "row_retained_on_noncompliance": True,
                "pooling": "ineligible when the required Skill read or successful query is absent",
            },
        },
        "preregistered_scope": {
            "task_ids": [TASK_ID],
            "arms": list(ARMS),
            "providers": ["codex"],
            "repetitions": REPETITIONS,
            "total_cells": cells,
            "coordinate_timeout_seconds": COORDINATE_TIMEOUT_SECONDS,
            "complete_run_max_wall_clock_seconds": 5400,
            "nonpoolable": True,
            "pooling_eligibility": "ineligible; exploratory evidence only",
            "arm_order": "deterministic lexical arm order within each repetition",
        },
        "scoring": {
            "provider": "claude_ground_truth_reused",
            "implementation": {
                "path": "benchmarks/run-claude-agentic.py",
                "sha256": artifact_hashes["claude_agentic_runner"],
                "symbol": "GroundTruth.score",
            },
            "metrics": {
                "EREC": "erec_tp / max(len(expected), 1)",
                "E@10": "top10_tp / max(len(top10), 1)",
                "RREC": "rrec_tp / max(len(expected), 1)",
                "DEFF": "erec_tp / max(tool_calls, 1)",
            },
            "quality_score": "shared GroundTruth score over the agent's final answer and exposure corpus",
        },
        "artifact_sha256": artifact_hashes,
        "plugin_runtime": {
            "codemap_version": _load_json(ROOT / "plugins/codemap-py/.codex-plugin/plugin.json")["version"],
            "codex_rig_version": _load_json(ROOT / "plugins/codex-rig/.codex-plugin/plugin.json")["version"],
            "source_hashes": artifact_hashes,
        },
        "admission": {
            "paid_execution": "admitted",
            "authorization": "caller must supply the exact reviewed machine-manifest SHA-256 as CODEX_AGENTIC_PAID_APPROVAL",
            "status": "review-ready; no model or auth used; human execution pending",
            "credentials": "no credential material, auth source, or credential path is part of this manifest",
            "required_before_paid_execution": [
                "Run --dry-run and verify the deterministic 9-cell plan.",
                "Validate target commit/tree and frozen index bytes without model or credentials.",
                "Validate A/B/C isolation and C Skill-before-query evidence without model or credentials.",
                "Caller supplies CODEX_AGENTIC_PAID_APPROVAL equal to the exact reviewed machine-manifest SHA-256.",
            ],
        },
        "artifact_package": {
            "required_files": [
                "run.log",
                "telemetry.jsonl (raw)",
                "telemetry-canonical.jsonl",
                "run-metadata.json",
                "inputs/ (frozen input snapshot)",
                "checksums.sha256",
            ],
            "stop_behavior": (
                "Stop on the first runtime or admission-integrity failure or complete-run wall-clock exhaustion; do not stop "
                "on an ordinary model, task, or treatment-nonadherence row; preserve every partial artifact and never pool "
                "partial or nonpoolable evidence."
            ),
        },
        "source_manifest": {"path": str(SOURCE_MANIFEST.relative_to(ROOT)), "sha256": _sha256(SOURCE_MANIFEST)},
        "runner": "benchmarks/run-codex-agentic.py",
        "runtime_isolation": {
            "adapter": "benchmarks/run-codex-structural.py",
            "manifest": "benchmarks/manifests/codex-integration.json",
            "mapping": {
                "A_plain": "A_plain",
                "B_auto": "B_direct_required capability home; use remains optional",
                "C_required": "C_skill_required",
            },
        },
    }


def _json_bytes(manifest: dict[str, Any]) -> bytes:
    """Serialize the machine manifest deterministically."""
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _human_bytes(manifest: dict[str, Any], machine_sha256: str) -> bytes:
    """Render the concise human review record from machine content."""
    task = manifest["task"]
    scope = manifest["preregistered_scope"]
    lines = [
        f"# `{manifest['experiment_id']}`",
        "",
        f"**Manifest SHA-256**: `{machine_sha256}`",
        "",
        "## Status",
        "",
        "- No model or credentials were used to build this manifest.",
        "- Review-ready; human execution is pending.",
        "- Paid execution is admitted only when the caller supplies the exact reviewed machine-manifest SHA-256.",
        "- The 9-cell scope is exploratory and non-poolable.",
        "",
        "## Locked experiment",
        "",
        f"- Revision: `{manifest['experiment_revision']}`",
        f"- Model: `{manifest['model']['name']}`, effort `{manifest['model']['reasoning_effort']}`.",
        f"- Target: `{manifest['target_source']['tag']}` at `{manifest['target_source']['commit']}`.",
        f"- Frozen index SHA-256: `{manifest['frozen_index_contract']['raw_sha256']}`.",
        f"- Suite: `{manifest['suite']['path']}`; raw SHA-256 `{manifest['suite']['raw_sha256']}`.",
        "",
        "## BA-01 identity",
        "",
        f"- `{task['id']}` `{task['type']}` / `{task['difficulty']}` on `{task['primary_module']}`.",
        f"- Canonical task SHA-256: `{task['canonical_task_sha256']}`.",
        f"- Prompt SHA-256: `{task['prompt_sha256']}`.",
        f"- Oracle: `{task['oracle_class']}`; Claude `GroundTruth.score` is reused.",
        "",
        "## Scope and arms",
        "",
        f"- Tasks: `{scope['task_ids']}`; repetitions: `{scope['repetitions']}`; arms: `{scope['arms']}`.",
        f"- Cells: `{scope['total_cells']}`; coordinate budget: `{scope['coordinate_timeout_seconds']}s`; complete-run ceiling: `{scope['complete_run_max_wall_clock_seconds']}s`.",
        "- `A_plain`: Codemap absent; no-call is valid.",
        "- `B_auto`: Codemap CLI available; use is optional, and adoption is measured.",
        "- `C_required`: exact Skill read must precede a successful compact query; noncompliant rows remain scored but are excluded from pooling.",
        "",
        "## Artifact and stop contract",
        "",
        "- Required package: `run.log`, raw `telemetry.jsonl`, `telemetry-canonical.jsonl`, `run-metadata.json`, frozen `inputs/`, and `checksums.sha256`.",
        "- Stop on the first runtime or admission-integrity failure or complete-run wall-clock exhaustion; ordinary model/task/treatment-nonadherence rows do not stop scheduling; preserve partial artifacts and never pool partial/nonpoolable evidence.",
        "",
        "## Shared scoring",
        "",
        "- `EREC = erec_tp / max(len(expected), 1)`; `E@10 = top10_tp / max(len(top10), 1)`.",
        "- `RREC = rrec_tp / max(len(expected), 1)`; `DEFF = erec_tp / max(tool_calls, 1)`.",
        "",
        "## Runner",
        "",
        f"- `{manifest['runner']}`",
        "- No credential path or auth material is recorded in the machine lock; the caller supplies a private source at execution time.",
        "",
        "## Human execution and approval",
        "",
        "Review the no-model plan first:",
        "",
        "```bash",
        "bash benchmarks/run-all.sh codex --agentic --dry-run",
        "```",
        "",
        "Then run the exact reviewed scope with a fresh run directory:",
        "",
        "```bash",
        "CODEX_AGENTIC_PAID_APPROVAL=<MANIFEST_SHA256> \\",
        'CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \\',
        'CODEX_RUN_DIR="benchmarks/results/codex-agentic-$(date -u +%Y%m%dT%H%M%SZ)" \\',
        "CODEX_MAX_WALL_CLOCK_SECONDS=5400 \\",
        "  bash benchmarks/run-all.sh codex --agentic",
        "```",
        "",
        "Replace `<MANIFEST_SHA256>` with the machine-manifest SHA-256 shown above. The caller supplies authorization; no credential bytes are stored in this manifest.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_or_check(path: Path, expected: bytes, *, check: bool) -> None:
    """Write one generated artifact or fail closed when it differs."""
    if check:
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError(f"generated manifest is stale: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(expected)


def main(argv: list[str] | None = None) -> int:
    """Build both manifest forms or verify their exact current bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args(argv)
    manifest = _build_manifest()
    machine = _json_bytes(manifest)
    human = _human_bytes(manifest, hashlib.sha256(machine).hexdigest())
    try:
        _write_or_check(OUTPUT_MANIFEST, machine, check=args.check)
        _write_or_check(OUTPUT_HUMAN_MANIFEST, human, check=args.check)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"{'verified' if args.check else 'wrote'}: {OUTPUT_MANIFEST.relative_to(ROOT)}")
    print(f"{'verified' if args.check else 'wrote'}: {OUTPUT_HUMAN_MANIFEST.relative_to(ROOT)}")
    print(f"manifest sha256: {hashlib.sha256(machine).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
