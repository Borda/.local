"""Regression checks for bounded, approved code-remediation work buckets."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_validator() -> ModuleType:
    """Load the hyphenated artifact-validator module for focused contract tests."""
    path = PLUGIN_ROOT / "shared" / "validate-artifacts.py"
    spec = importlib.util.spec_from_file_location("codex_rig_validate_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _write_workplan(metadata: dict[str, object], out_dir: Path) -> None:
    """Write plan, approval, context, and human-readable binding evidence."""
    workplan = metadata["resolution_workplan"]
    assert isinstance(workplan, dict)
    buckets = workplan["work_buckets"]
    assert isinstance(buckets, list)

    specialists_dir = out_dir / "specialists"
    specialists_dir.mkdir()
    for bucket in buckets:
        assert isinstance(bucket, dict)
        if bucket["owner"] != "parent":
            (out_dir / str(bucket["context_pack_path"])).write_text("# Context\n", encoding="utf-8")

    plan_path = out_dir / "work-bucket-plan.json"
    plan_path.write_text(
        json.dumps({"schema_version": 1, "work_buckets": buckets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    approval_status = workplan["parallel_approval_status"]
    response = {"approved": "approve", "parent-only": "parent-only", "not-required": "not-required"}[
        str(approval_status)
    ]
    workplan.update(
        {
            "approved_plan_sha256": plan_sha256 if response == "approve" else None,
            "bucket_plan_path": "work-bucket-plan.json",
            "bucket_plan_sha256": plan_sha256,
            "parallel_approval_path": "parallel-approval.json",
            "parallel_approval_response": response,
        }
    )
    (out_dir / "parallel-approval.json").write_text(
        json.dumps(
            {
                "plan_sha256": plan_sha256,
                "prompt_presented": workplan["parallel_prompt_presented"],
                "response": response,
                "source": workplan["parallel_approval_source"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bucket_rows = "\n".join(
        f"| {bucket['bucket_id']} | {bucket['owner']} | {bucket['verifier']} | {bucket['context_pack_path']} | tests |"
        for bucket in buckets
    )
    (out_dir / "resolution-workplan.md").write_text(
        f"""# Resolution Workplan

## Work Bucket Plan

| Bucket | Owner | Verifier | Context | Closure |
| --- | --- | --- | --- | --- |
{bucket_rows}

## Parallel Approval

Approval source: {workplan["parallel_approval_source"]}.
Approval response: {response}.
Plan SHA-256: {plan_sha256}.

## Execution Order

Parallel after approval.

## Ungrouped Items

None.
""",
        encoding="utf-8",
    )


def _parallel_metadata() -> dict[str, object]:
    """Return a valid six-item, two-bucket parallel plan."""
    return {
        "resolution_scope": {"selected_indexes": [1, 2, 3, 4, 5, 6]},
        "resolution_workplan": {
            "execution_mode": "parallel-specialists",
            "groups_total": 2,
            "max_items_per_bucket": 5,
            "parallel_approval_required": True,
            "parallel_approval_source": "explicit-input",
            "parallel_approval_status": "approved",
            "parallel_eligible": True,
            "parallel_prompt_presented": False,
            "parent_owned_groups": 0,
            "specialist_owned_groups": 2,
            "unassigned_selected_items": 0,
            "verifier_groups": 2,
            "work_buckets": [
                {
                    "bucket_id": "B1",
                    "selected_indexes": [1, 2, 3],
                    "owner": "sw-engineer",
                    "verifier": "qa-specialist",
                    "context_pack_path": "specialists/b1-context.md",
                    "owned_paths": ["src/feature.py"],
                    "execution_mode": "parallel",
                },
                {
                    "bucket_id": "B2",
                    "selected_indexes": [4, 5, 6],
                    "owner": "doc-scribe",
                    "verifier": "parent",
                    "context_pack_path": "specialists/b2-context.md",
                    "owned_paths": ["docs/feature.md"],
                    "execution_mode": "parallel",
                },
            ],
            "workplan_path": "resolution-workplan.md",
        },
    }


def test_parallel_work_buckets_accept_bounded_disjoint_approved_plan(tmp_path: Path) -> None:
    """Accept useful fan-out only when coverage, ownership, and approval reconcile."""
    metadata = _parallel_metadata()
    _write_workplan(metadata, tmp_path)

    VALIDATOR._validate_code_remediate_workplan(metadata, tmp_path)


def test_low_volume_selection_stays_in_one_agent_scope(tmp_path: Path) -> None:
    """Accept five-or-fewer selected items only as one non-parallel bucket."""
    metadata = _parallel_metadata()
    metadata["resolution_scope"] = {"selected_indexes": [1, 2]}
    metadata["resolution_workplan"] = {
        "execution_mode": "parent-owned",
        "groups_total": 1,
        "max_items_per_bucket": 5,
        "parallel_approval_required": False,
        "parallel_approval_source": "not-required",
        "parallel_approval_status": "not-required",
        "parallel_eligible": False,
        "parallel_prompt_presented": False,
        "parent_owned_groups": 1,
        "specialist_owned_groups": 0,
        "unassigned_selected_items": 0,
        "verifier_groups": 1,
        "work_buckets": [
            {
                "bucket_id": "B1",
                "selected_indexes": [1, 2],
                "owner": "parent",
                "verifier": "qa-specialist",
                "context_pack_path": "resolution-workplan.md",
                "owned_paths": ["src/feature.py"],
                "execution_mode": "parent",
            }
        ],
        "workplan_path": "resolution-workplan.md",
    }
    _write_workplan(metadata, tmp_path)

    VALIDATOR._validate_code_remediate_workplan(metadata, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("too-large", "code-remediate-work-bucket-too-large"),
        ("duplicate-index", "code-remediate-work-bucket-coverage-mismatch"),
        ("low-volume-fanout", "code-remediate-low-volume-fanout"),
        ("missing-approval", "code-remediate-parallel-approval-missing"),
        ("declined-fanout-unrecorded", "code-remediate-eligible-fanout-approval-not-recorded"),
        ("overlapping-path", "code-remediate-parallel-ownership-overlap"),
        ("ancestor-path-overlap", "code-remediate-parallel-ownership-overlap"),
        ("unsupported-owner", "code-remediate-work-bucket-owner-unsupported"),
        ("parent-parallel-mode", "code-remediate-parent-work-bucket-mode-invalid"),
        ("missing-context", "code-remediate-specialist-context-pack-missing"),
        ("one-specialist-per-finding", "code-remediate-one-specialist-per-finding"),
    ],
)
def test_invalid_work_bucket_plans_fail_closed(tmp_path: Path, mutation: str, error: str) -> None:
    """Reject plans that create excess fan-out, overlap, or unapproved parallel work."""
    metadata = copy.deepcopy(_parallel_metadata())
    scope = metadata["resolution_scope"]
    workplan = metadata["resolution_workplan"]
    assert isinstance(scope, dict) and isinstance(workplan, dict)
    buckets = workplan["work_buckets"]
    assert isinstance(buckets, list)

    if mutation == "too-large":
        buckets[0]["selected_indexes"] = [1, 2, 3, 4, 5, 6]
        buckets.pop()
        workplan["groups_total"] = 1
        workplan["specialist_owned_groups"] = 1
        workplan["verifier_groups"] = 1
    elif mutation == "duplicate-index":
        buckets[1]["selected_indexes"] = [3, 4, 5, 6]
    elif mutation == "low-volume-fanout":
        scope["selected_indexes"] = [1, 2]
        buckets[0]["selected_indexes"] = [1]
        buckets[0]["singleton_rationale"] = "Distinct runtime boundary."
        buckets[1]["selected_indexes"] = [2]
        buckets[1]["singleton_rationale"] = "Distinct documentation boundary."
    elif mutation == "missing-approval":
        workplan["parallel_approval_status"] = "not-required"
    elif mutation == "declined-fanout-unrecorded":
        workplan["execution_mode"] = "sequential-specialists"
        workplan["parallel_approval_required"] = False
        workplan["parallel_approval_source"] = "not-required"
        workplan["parallel_approval_status"] = "parent-only"
        for bucket in buckets:
            bucket["execution_mode"] = "sequential"
    elif mutation == "overlapping-path":
        buckets[1]["owned_paths"] = ["src/feature.py"]
    elif mutation == "ancestor-path-overlap":
        buckets[0]["owned_paths"] = ["src"]
        buckets[1]["owned_paths"] = ["src/feature.py"]
    elif mutation == "unsupported-owner":
        buckets[0]["owner"] = "invented-specialist"
    elif mutation == "parent-parallel-mode":
        buckets[0]["owner"] = "parent"
        workplan["parent_owned_groups"] = 1
        workplan["specialist_owned_groups"] = 1
    elif mutation == "one-specialist-per-finding":
        workplan["groups_total"] = 6
        workplan["specialist_owned_groups"] = 6
        workplan["verifier_groups"] = 6
        workplan["work_buckets"] = [
            {
                "bucket_id": f"B{index}",
                "selected_indexes": [index],
                "owner": "sw-engineer",
                "verifier": "qa-specialist",
                "context_pack_path": f"specialists/b{index}-context.md",
                "owned_paths": [f"src/feature_{index}.py"],
                "execution_mode": "parallel",
                "singleton_rationale": "Distinct file.",
            }
            for index in range(1, 7)
        ]

    _write_workplan(metadata, tmp_path)
    if mutation == "missing-context":
        (tmp_path / "specialists" / "b1-context.md").unlink()

    with pytest.raises(SystemExit, match=error):
        VALIDATOR._validate_code_remediate_workplan(metadata, tmp_path)


def test_parallel_approval_is_bound_to_the_approved_plan_digest(tmp_path: Path) -> None:
    """Reject an approval record copied from a different bucket proposal."""
    metadata = _parallel_metadata()
    _write_workplan(metadata, tmp_path)
    workplan = metadata["resolution_workplan"]
    assert isinstance(workplan, dict)
    workplan["approved_plan_sha256"] = "0" * 64

    with pytest.raises(SystemExit, match="code-remediate-parallel-approved-plan-not-bound"):
        VALIDATOR._validate_code_remediate_workplan(metadata, tmp_path)
