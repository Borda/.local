#!/usr/bin/env python3
"""Build or verify the provider-neutral benchmark methodology lock.

This utility deliberately owns the shared methodology source used by Claude
and Codex. It derives task, prompt, suite, capability, and implementation
identities from committed inputs, while requiring every change from the
immutable historical archive to appear in an explicit reviewed ledger.
``--check`` writes nothing and fails closed on byte drift.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
OUTPUT_MANIFEST = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
POLICY_SEED = BENCHMARKS / "manifests" / "provider-parity-methodology-policy.json"
POLICY_SEED_SHA256 = "62da64ed419bb988794ccd0e6ccc58a61f84a9e0f8b737ccb5ef372a3ec0384d"
ARCHIVED_MANIFEST = BENCHMARKS / "results" / "manifests" / ("provider-parity-v1-b0-" + "r" + "6.json")
ARCHIVED_MANIFEST_SHA256 = "971c6ad220c1e821ed72109396f4dce1d745f0a1b74b2790874f6b07e833627b"
EXPERIMENT_REVISION = "provider-parity-shared-structural-and-agentic-methodology-2026-08-04"
INDEX_LOCK = {
    "change_reason": (
        "Scanner schema 12 now preserves regular-package module identities outside a conventional tests/ prefix; "
        "production-only centrality is recomputed from production importers without changing the schema."
    ),
    "git_sha": "be98784a1a03581b7051a355ae1084fd352d7cea",
    "module_count": 645,
    "path": "/private/tmp/codemap-provider-parity-pl-2.6.5/.cache/codemap/codemap-provider-parity-pl-2.6.5.json",
    "project": "codemap-provider-parity-pl-2.6.5",
    "raw_sha256": "2d48a5ea4ddc3830f83de950713580bbc2e2dd3b43d1326f047cd3e21acec1eb",
    "scan_root": "/private/tmp/codemap-provider-parity-pl-2.6.5",
    "scan_version": 12,
    "scanned_at": "2026-08-03T10:58:35.335616+00:00",
}
PRODUCT_ACCEPTANCE_POLICY = {
    "efficiency_path": {
        "c_a_gross_input_ratio_95_upper": "< 1.00",
        "c_a_paired_quality_mean": ">= 0.00",
        "c_a_paired_quality_95_lower": ">= -0.02",
    },
    "quality_path": {
        "c_a_gross_input_ratio_95_upper": "<= 1.05",
        "c_a_paired_quality_95_lower": "> 0",
    },
    "task_family_block": "Any repeated task-family mean C_skill-A_plain quality difference < -0.10 blocks acceptance.",
    "historical_evidence": "Historical nonpoolable evidence cannot satisfy this prospective policy.",
}

sys.path.insert(0, str(BENCHMARKS))
import provider_parity_contracts as core  # noqa: E402


def _ledger_entry(identity_fields: list[str], reason: str) -> dict[str, Any]:
    """Return one compact, reviewable intentional task-identity declaration."""
    return {"identity_fields": identity_fields, "reason": reason}


TASK_CHANGE_LEDGER: dict[str, dict[str, Any]] = {
    **{
        f"BA-{number:02d}": _ledger_entry(
            ["canonical_task_sha256", "prompt_sha256"],
            "Provider-neutral labelled answer contract makes every requested blast-radius field scoreable.",
        )
        for number in range(1, 17)
    },
    "SE-05": _ledger_entry(["canonical_task_sha256"], "Structured expected query normalizes the symbol target."),
    "FN-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Prompt includes examples/** in the non-test caller scope."
    ),
    "RV-01": _ledger_entry(
        ["prompt_sha256"], "Provider prompt now contains the independently scored review questions."
    ),
    "RV-02": _ledger_entry(
        ["prompt_sha256"], "Provider prompt now contains the independently scored review questions."
    ),
    "RV-03": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Production-only caller oracle adds the explicit --exclude-tests filter to the task query and prompt.",
    ),
    "RV-04": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Production-only callback oracle adds the explicit --exclude-tests filter to the task query and prompt.",
    ),
    "RV-05": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Provider-visible review questions and diagnostic oracle policy are explicit.",
    ),
    "CQ-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Exact labelled conclusion format prevents incidental-text scoring."
    ),
    "CQ-02": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Exact labelled conclusion format prevents incidental-text scoring."
    ),
    "CQ-03": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Exact labelled conclusion format prevents incidental-text scoring."
    ),
    "CQ-05": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Exact labelled conclusion format prevents incidental-text scoring."
    ),
    "BR-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Prompt includes examples/** in the non-test blast-radius scope."
    ),
    "BR-09": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-caller query is required."),
    "DG-01": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "DG-02": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "DG-03": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "DG-04": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "DG-05": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "DG-06": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped symbol query is required."),
    "FT-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Corrected extension target, structured queries, and labelled answer contract.",
    ),
    "FT-02": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Structured queries and labelled answer contract."
    ),
    "FT-03": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Structured queries and labelled answer contract."
    ),
    "FT-04": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Structured queries and labelled answer contract."
    ),
    "FT-05": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"], "Structured queries and labelled answer contract."
    ),
    "DI-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Replaced an external re-export with a staged local target; caller and direct test-import queries are all required.",
    ),
    "DI-02": _ledger_entry(["canonical_task_sha256"], "Caller and direct test-import queries are all required."),
    "DI-03": _ledger_entry(["canonical_task_sha256"], "Caller and direct test-import queries are all required."),
    "DI-04": _ledger_entry(["canonical_task_sha256"], "Caller and direct test-import queries are all required."),
    "DI-05": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Replaced an external re-export with a staged local target; caller and direct test-import queries are all required.",
    ),
    "DI-06": _ledger_entry(
        ["canonical_task_sha256"],
        "Corrected recursive re-export caller oracle; caller and direct test-import queries are all required.",
    ),
    "GR-01": _ledger_entry(
        ["canonical_task_sha256", "prompt_sha256"],
        "Production-only centrality scope is explicit and matches the exclude-tests oracle/query.",
    ),
    "GR-02": _ledger_entry(["canonical_task_sha256"], "Structured graph query is required."),
    "GR-03": _ledger_entry(["canonical_task_sha256"], "Structured graph query is required."),
    "GR-04": _ledger_entry(["canonical_task_sha256"], "Structured graph-centrality query is required."),
    "MB-01": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-import query is required."),
    "MB-02": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-import query is required."),
    "MB-03": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-import query is required."),
    "MB-04": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-import query is required."),
    "MB-05": _ledger_entry(["canonical_task_sha256"], "Structured task-shaped reverse-import query is required."),
}


def _sha256(path: Path) -> str:
    """Return one required file's exact SHA-256 identity."""
    if not path.is_file():
        raise ValueError(f"required methodology input is missing or not a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    """Load one required JSON object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid methodology JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"methodology JSON input must be an object: {path}")
    return payload


def _load_policy_seed() -> dict[str, Any]:
    """Load the immutable passthrough policy without trusting generated output."""
    if _sha256(POLICY_SEED) != POLICY_SEED_SHA256:
        raise ValueError("immutable methodology policy seed SHA-256 changed")
    policy = _load_json(POLICY_SEED)
    expected_fields = {
        "codex_permission_profiles",
        "evaluation_contract",
        "execution_controls",
        "headline_structural_v1",
        "implementation_contract",
        "oracle_remediation",
        "preregistered_cells",
        "target_source",
        "validation",
    }
    if set(policy) != expected_fields:
        raise ValueError("methodology policy seed has unexpected passthrough fields")
    return policy


def _task_rows(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return uniquely keyed task rows from one archived or generated manifest."""
    rows: dict[str, dict[str, Any]] = {}
    suites = manifest.get("suites")
    if not isinstance(suites, list):
        raise ValueError("methodology manifest requires suites")
    for suite in suites:
        if not isinstance(suite, Mapping) or not isinstance(suite.get("tasks"), list):
            raise ValueError("methodology suite requires tasks")
        for task in suite["tasks"]:
            if not isinstance(task, Mapping) or not isinstance(task.get("id"), str):
                raise ValueError("methodology task requires an id")
            task_id = task["id"]
            if task_id in rows:
                raise ValueError(f"methodology manifest duplicates task id {task_id!r}")
            rows[task_id] = dict(task)
    return rows


def _current_suite_tasks(path: str) -> list[dict[str, Any]]:
    """Load one committed suite using the shared raw-task contract."""
    return core.load_task_suite(ROOT / path)


def _changed_task_identity_fields(previous: Mapping[str, Any], active: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return exact canonical/prompt identity changes between two methodology locks."""
    before = _task_rows(previous)
    after = _task_rows(active)
    if before.keys() != after.keys():
        raise ValueError("methodology task ids differ from the immutable archive")
    changes: dict[str, list[str]] = {}
    for task_id, prior in before.items():
        fields = [
            field
            for field in ("canonical_task_sha256", "prompt_sha256")
            if prior.get(field) != after[task_id].get(field)
        ]
        if fields:
            changes[task_id] = fields
    return changes


def _artifact_hashes() -> dict[str, str]:
    """Lock shared provider-neutral implementation bytes used by both runners."""
    paths = {
        "agentic_contracts": "benchmarks/agentic_contracts.py",
        "claude_query_skill": "plugins/codemap-py/claude-skills/query-code/SKILL.md",
        "codemap_graph": "plugins/codemap-py/src/codemap_py/graph.py",
        "codemap_query": "plugins/codemap-py/src/codemap_py/query.py",
        "codex_query_skill": "plugins/codemap-py/codex-skills/query-code/SKILL.md",
        "provider_parity_contracts": "benchmarks/provider_parity_contracts.py",
        "run_all": "benchmarks/run-all.sh",
        "run_claude_agentic": "benchmarks/run-claude-agentic.py",
        "run_claude_structural": "benchmarks/run-claude-structural.py",
        "run_codex_agentic": "benchmarks/run-codex-agentic.py",
        "run_codex_structural": "benchmarks/run-codex-structural.py",
    }
    return {name: _sha256(ROOT / relative_path) for name, relative_path in paths.items()}


def _build_suites(archived: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recompute all suite/task identities while retaining archived classification policy."""
    suites: list[dict[str, Any]] = []
    for archived_suite in archived["suites"]:
        suite = copy.deepcopy(archived_suite)
        path = suite["path"]
        source_tasks = _current_suite_tasks(path)
        prior_rows = {task["id"]: task for task in suite["tasks"]}
        source_ids = [task["id"] for task in source_tasks]
        if source_ids != suite["ordered_task_ids"] or set(prior_rows) != set(source_ids):
            raise ValueError(f"suite task ordering or ids drifted outside the declared methodology contract: {path}")

        rows: list[dict[str, Any]] = []
        for source_task in source_tasks:
            row = copy.deepcopy(prior_rows[source_task["id"]])
            row["canonical_task_sha256"] = core.canonical_task_hash(source_task)
            row["prompt_sha256"] = core.prompt_hash(source_task)
            if "answer_contract" in source_task:
                row["answer_contract"] = copy.deepcopy(source_task["answer_contract"])
            rows.append(row)
        suite["raw_sha256"] = _sha256(ROOT / path)
        suite["task_count"] = len(rows)
        suite["tasks"] = rows
        suite["semantic_suite_sha256"] = core.semantic_suite_hash(source_tasks)
        if path == "benchmarks/suites/tasks-agentic.json":
            suite["current_consumer"] = "run-claude-agentic.py and run-codex-agentic.py defaults"
        else:
            suite["current_consumer"] = suite["current_consumer"].replace(
                "in r" + "6", "in the archived provider-parity study"
            )
        suites.append(suite)
    return suites


def _suite_integrity(suites: list[dict[str, Any]]) -> dict[str, Any]:
    """Return recomputed global cardinality, uniqueness, and semantic identities."""
    tasks = [task for suite in suites for task in suite["tasks"]]
    task_ids = [task["id"] for task in tasks]
    canonical_hashes = [task["canonical_task_sha256"] for task in tasks]
    return {
        "all_tasks_have_id_and_prompt": True,
        "semantic_suite_sha256": {suite["path"]: suite["semantic_suite_sha256"] for suite in suites},
        "suite_count": len(suites),
        "task_count": len(tasks),
        "unique_canonical_task_hashes": len(canonical_hashes) == len(set(canonical_hashes)),
        "unique_ids_within_and_across_suites": len(task_ids) == len(set(task_ids)),
    }


def _evaluation_contract(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute capability strata counts from the current structural suite."""
    contract = copy.deepcopy(policy["evaluation_contract"])
    tasks = _current_suite_tasks("benchmarks/suites/tasks-bench.json")
    counts = Counter(stratum for task in tasks for stratum in core.capability_strata(task))
    contract["capability_strata_counts"] = dict(sorted(counts.items()))
    contract["prospective_product_acceptance"] = copy.deepcopy(PRODUCT_ACCEPTANCE_POLICY)
    return contract


def _build_manifest() -> dict[str, Any]:
    """Build the only accepted current provider-neutral methodology record."""
    if _sha256(ARCHIVED_MANIFEST) != ARCHIVED_MANIFEST_SHA256:
        raise ValueError("immutable archived methodology manifest hash changed")
    archived = _load_json(ARCHIVED_MANIFEST)
    policy = _load_policy_seed()
    suites = _build_suites(archived)
    manifest = copy.deepcopy(policy)
    manifest["experiment_revision"] = EXPERIMENT_REVISION
    manifest["evaluation_contract"] = _evaluation_contract(policy)
    manifest["execution_controls"]["codex_transport"] = (
        "run-codex-structural.py and run-codex-agentic.py provider adapters"
    )
    agentic_suite = next(suite for suite in suites if suite["path"] == "benchmarks/suites/tasks-agentic.json")
    manifest["agentic_execution_contract"] = {
        "arms": list(core.ARM_CONTRACTS),
        "coordinate_timeout_seconds": core.PARITY_TIMEOUT_SECONDS,
        "default_repetitions": 1,
        "default_total_cells_by_provider": {
            "claude": len(agentic_suite["ordered_task_ids"]) * len(core.ARM_CONTRACTS) * 3,
            "codex": len(agentic_suite["ordered_task_ids"]) * len(core.ARM_CONTRACTS),
        },
        "models_by_provider": {"claude": ["haiku", "sonnet", "opus"], "codex": ["gpt-5.6-luna"]},
        "providers": ["claude", "codex"],
        "repeat_override": (
            "Each provider adapter admits a nondefault positive repeat only with a deterministic scope hash binding "
            "the provider, current manifest, ordered tasks, arms, models, repetitions, total cells, and exact wall-clock ceiling."
        ),
        "scoring": (
            "Macro mean across every required answer_contract component; missing components score zero. "
            "EREC and RREC remain diagnostic comparability metrics."
        ),
        "task_ids": agentic_suite["ordered_task_ids"],
    }
    manifest["implementation_contract"]["artifact_sha256"] = _artifact_hashes()
    manifest["index"] = copy.deepcopy(INDEX_LOCK)
    manifest["methodology_change_ledger"] = copy.deepcopy(TASK_CHANGE_LEDGER)
    manifest["suite_integrity"] = _suite_integrity(suites)
    manifest["suites"] = suites

    observed_changes = _changed_task_identity_fields(archived, manifest)
    declared_changes = {task_id: entry["identity_fields"] for task_id, entry in TASK_CHANGE_LEDGER.items()}
    if observed_changes != declared_changes:
        raise ValueError(
            "task identity changes differ from the declared methodology ledger: "
            f"observed={observed_changes}, declared={declared_changes}"
        )
    return manifest


def _manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Serialize the deterministic machine-readable methodology lock."""
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_or_check(path: Path, expected: bytes, *, check: bool) -> None:
    """Write generated output or fail closed when its exact bytes are stale."""
    if check:
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError(f"generated methodology record is stale: {path}; rerun without --check")
        return
    path.write_bytes(expected)


def main(argv: list[str] | None = None) -> int:
    """Build the methodology source or verify it without model or authentication access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed methodology differs from inputs")
    args = parser.parse_args(argv)
    try:
        _write_or_check(OUTPUT_MANIFEST, _manifest_bytes(_build_manifest()), check=args.check)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"{'verified' if args.check else 'wrote'}: {OUTPUT_MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
