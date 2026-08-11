"""Regression tests for the provider-neutral edit and patch benchmark contract."""

from __future__ import annotations

import pytest

try:
    from _bench_common.edit_patch_contracts import (
        EditExecution,
        StageIdentity,
        assess_patch_answer,
        build_edit_task_contract,
        compare_stage_identities,
        score_edit_execution,
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
        validate_provider_binding,
    )


def _patch_task() -> dict[str, object]:
    """Return a minimal patch task with an executable primary oracle."""
    return {
        "id": "PT-fixture",
        "type": "patch_task",
        "prompt": "Fix the fixture and return one unified diff.",
        "pre_fix_commit": "a" * 40,
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
