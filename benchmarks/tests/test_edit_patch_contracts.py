"""Regression tests for the provider-neutral edit and patch benchmark contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

try:
    from _bench_common.edit_patch_contracts import (
        EditExecution,
        StageIdentity,
        assess_patch_answer,
        build_edit_task_contract,
        compare_stage_identities,
        score_edit_execution,
        semantic_index_sha256,
        validate_patch_index_bundle,
        validate_provider_binding,
    )
except ModuleNotFoundError:
    from benchmarks._bench_common.edit_patch_contracts import (
        EditExecution,
        StageIdentity,
        assess_patch_answer,
        build_edit_task_contract,
        compare_stage_identities,
        score_edit_execution,
        semantic_index_sha256,
        validate_patch_index_bundle,
        validate_provider_binding,
    )


def _patch_task() -> dict[str, object]:
    """Return a minimal patch task with an executable primary oracle."""
    return {
        "id": "PT-fixture",
        "type": "patch_task",
        "prompt": "Fix the fixture and return one unified diff.",
        "pre_fix_commit": "a" * 40,
        "test_fixture_patch": (
            "diff --git a/tests/test_fixture.py b/tests/test_fixture.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/tests/test_fixture.py\n"
            "@@ -0,0 +1 @@\n"
            "+def test_fixture() -> None: pass\n"
        ),
        "test_command": "pytest tests/test_fixture.py::test_fix -x",
        "gt_files_changed": ["src/fixture.py"],
        "regression_test_commands": ["pytest tests/test_fixture.py -x"],
        "scoreable": True,
    }


def test_provider_neutral_patch_contract_requires_executable_oracle() -> None:
    """A patch task without a target test cannot enter the shared edit stage."""
    task = _patch_task()
    task.pop("test_command")

    with pytest.raises(ValueError, match="test_command"):
        build_edit_task_contract(task)


def test_provider_neutral_patch_contract_requires_regression_and_staged_fixture() -> None:
    """A target-only patch task cannot enter the shared executable contract."""
    task = _patch_task()
    task.pop("regression_test_commands")

    with pytest.raises(ValueError, match="regression_test_commands"):
        build_edit_task_contract(task)

    task = _patch_task()
    task.pop("test_fixture_patch")

    with pytest.raises(ValueError, match="test_fixture_patch"):
        build_edit_task_contract(task)

    task = _patch_task()
    task["gt_files_changed"] = ["tests/test_fixture.py"]

    with pytest.raises(ValueError, match="must not overlap"):
        build_edit_task_contract(task)


def test_patch_score_requires_application_targeted_and_regression_evidence() -> None:
    """Keyword/file diagnostics cannot replace patch and test evidence."""
    contract = build_edit_task_contract(_patch_task())
    answer = assess_patch_answer("```diff\ndiff --git a/src/fixture.py b/src/fixture.py\n```")
    execution = EditExecution(
        patch_applied=True,
        targeted_test_passed=True,
        regression_test_passed=False,
        changed_paths=("src/fixture.py",),
    )

    score = score_edit_execution(contract, answer, execution)

    assert score.primary_correct is True
    assert score.safety_passed is False
    assert score.pooling_eligible is False


def test_edit_execution_serializes_provider_neutral_patch_evidence() -> None:
    """Patch adapters need the same JSON-safe execution boundary as Fix stages.

    Regression: Claude Patch completed its independent execution, then failed
    before persisting cell 1 because ``EditExecution`` lacked ``as_dict()``.
    """
    execution = EditExecution(
        patch_applied=True,
        targeted_test_passed=True,
        regression_test_passed=True,
        changed_paths=("src/fixture.py",),
        command_evidence={"target": {"returncode": 0}},
    )

    assert execution.as_dict() == {
        "patch_applied": True,
        "targeted_test_passed": True,
        "regression_test_passed": True,
        "changed_paths": ("src/fixture.py",),
        "baseline_target_failed": True,
        "baseline_regressions_passed": True,
        "fixture_intact": True,
        "source_integrity": True,
        "index_integrity": None,
        "cleanup_verified": True,
        "command_evidence": {"target": {"returncode": 0}},
        "error": None,
    }


def test_patch_score_rejects_lifecycle_failure_and_unexpected_paths() -> None:
    """A passing target cannot compensate for a leaked fixture or extra source path."""
    contract = build_edit_task_contract(_patch_task())
    answer = assess_patch_answer("```diff\ndiff --git a/src/fixture.py b/src/fixture.py\n```")
    execution = EditExecution(
        patch_applied=True,
        targeted_test_passed=True,
        regression_test_passed=True,
        changed_paths=("src/fixture.py", "src/unexpected.py"),
        baseline_target_failed=True,
        baseline_regressions_passed=True,
        fixture_intact=False,
    )

    score = score_edit_execution(contract, answer, execution)

    assert score.primary_correct is False
    assert score.safety_passed is False
    assert score.changed_path_boundary_passed is False
    assert score.pooling_eligible is False


def test_pt05_contract_excludes_reference_only_documentation() -> None:
    """PT-05 accepts its behaviorally complete source-only patch boundary."""
    suite_path = Path(__file__).parents[1] / "suites" / "tasks-patch.json"
    task = next(item for item in json.loads(suite_path.read_text(encoding="utf-8"))["tasks"] if item["id"] == "PT-05")
    contract = build_edit_task_contract(task)
    answer = assess_patch_answer(
        "```diff\n"
        "diff --git a/src/lightning/pytorch/loops/training_epoch_loop.py "
        "b/src/lightning/pytorch/loops/training_epoch_loop.py\n"
        "```"
    )
    execution = EditExecution(
        patch_applied=True,
        targeted_test_passed=True,
        regression_test_passed=True,
        changed_paths=("src/lightning/pytorch/loops/training_epoch_loop.py",),
    )

    score = score_edit_execution(contract, answer, execution)

    assert contract.expected_paths == ("src/lightning/pytorch/loops/training_epoch_loop.py",)
    assert score.changed_path_boundary_passed is True
    assert score.pooling_eligible is True


def test_malformed_or_multiple_patch_envelopes_fail_closed() -> None:
    """Only one fenced diff may become a mutable-cell candidate."""
    with pytest.raises(ValueError, match="exactly one fenced diff"):
        assess_patch_answer("```diff\ndiff --git a/a b/a\n```\n```diff\ndiff --git a/b b/b\n```")


def test_patch_answer_preserves_a_trailing_blank_context_marker() -> None:
    """Fence framing may be removed, but a diff's meaningful leading space must survive."""
    answer = assess_patch_answer("```diff\ndiff --git a/a.py b/a.py\n@@ -1 +1 @@\n old\n \n```")

    assert answer.diff.endswith("\n ")


def test_stage_identity_detects_prior_stage_drift() -> None:
    """A new stage cannot silently replace an already admitted stage identity."""
    prior = StageIdentity(stage="agentic-v1", revision="rev-1", task_suite_sha256="a" * 64, contract_sha256="b" * 64)
    observed = StageIdentity(stage="agentic-v1", revision="rev-1", task_suite_sha256="c" * 64, contract_sha256="b" * 64)

    with pytest.raises(ValueError, match="prior-stage identity changed"):
        compare_stage_identities({prior.stage: prior}, {observed.stage: observed})


def test_provider_binding_cannot_change_scientific_fields() -> None:
    """Provider metadata may vary, but the shared contract hashes may not."""
    contract = build_edit_task_contract(_patch_task())
    stage = StageIdentity(
        stage="patch-v1",
        revision="rev-1",
        task_suite_sha256="a" * 64,
        contract_sha256="b" * 64,
    )
    binding = dict(contract.scientific_field_hashes(stage))

    validate_provider_binding(contract, stage, binding)
    binding["oracle_sha256"] = "c" * 64

    with pytest.raises(ValueError, match="scientific fields"):
        validate_provider_binding(contract, stage, binding)


def test_patch_index_validation_rejects_post_build_byte_drift(tmp_path: Path) -> None:
    """Provider preflight must recheck installed graph bytes, not trust preparation history."""
    contract = build_edit_task_contract(_patch_task())
    index_path = tmp_path / ".cache/codemap/patch/PT-fixture.json"
    index_path.parent.mkdir(parents=True)
    payload = {
        "scan_version": 13,
        "scanned_at": "locked",
        "project": "provider-parity-PT-fixture",
        "scan_root": str(tmp_path),
        "modules": [{"name": "fixture", "path": "src/fixture.py"}],
    }
    index_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    index_path.write_bytes(index_bytes)
    locks_path = tmp_path / "locks.json"
    locks_path.write_text(
        json.dumps(
            {
                "schema_version": "provider-parity-patch-index-locks-v1",
                "canonical_scan_root": str(tmp_path),
                "tasks": {
                    "PT-fixture": {
                        "baseline_commit": contract.baseline_commit,
                        "module_count": 1,
                        "raw_sha256_at_canonical_root": hashlib.sha256(index_bytes).hexdigest(),
                        "scan_version": 13,
                        "scanned_at": "locked",
                        "semantic_sha256": semantic_index_sha256(payload, tmp_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    coordinates = validate_patch_index_bundle(tmp_path, locks_path, [contract])
    assert coordinates[contract.task_id]["baseline_commit"] == contract.baseline_commit
    assert coordinates[contract.task_id]["raw_index_sha256"] == hashlib.sha256(index_bytes).hexdigest()
    assert coordinates[contract.task_id]["scan_version"] == "13"

    payload["modules"][0]["name"] = "tampered"
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="semantic SHA-256 drifted"):
        validate_patch_index_bundle(tmp_path, locks_path, [contract])
