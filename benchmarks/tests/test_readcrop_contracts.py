"""Regression tests for the shared read-crop benchmark contract."""

from __future__ import annotations

import pytest

from benchmarks._bench_common import readcrop_contracts as contracts


def _task() -> dict[str, object]:
    """Build a fresh read-crop task requiring both source parameter names.

    >>> task = _task()
    >>> task["symbol"], task["expected_keywords"]
    ('Example.method', ['value', 'flag'])
    >>> task["expected_keywords"].clear()
    >>> _task()["expected_keywords"]
    ['value', 'flag']
    """
    return {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe `Example.method`.",
        "primary_module": "package.module",
        "symbol": "Example.method",
        "expected_keywords": ["value", "flag"],
    }


def test_contract_requires_a_strict_complete_symbol_answer() -> None:
    """Partial keyword mention cannot be promoted to a correct read-crop answer."""
    contract = contracts.build_readcrop_contract(
        _task(), source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
    )

    with pytest.raises(ValueError, match="missing required answer field"):
        contracts.parse_readcrop_answer('{"signature": "method(value)"}')

    answer = contracts.parse_readcrop_answer(
        '{"signature": "Example.method(self, value: int, *, flag: bool = False) -> None", '
        '"parameters": ["value", "flag"], "behavior": "Does the requested work."}'
    )
    score = contracts.score_readcrop_answer(contract, answer)

    assert score.primary_correct is True
    assert score.behavior_protocol_valid is True
    assert score.behavior_fact_recall is None
    assert score.behavior_facts_correct is None
    assert score.quality_score == 1.0
    assert score.keyword_recall == 1.0


def test_focused_parameters_and_behavior_facts_enforce_the_reviewed_task_contract() -> None:
    """Focused parameter and behavior requirements reject an empty context claim."""
    task = {
        **_task(),
        "required_parameters": ["flag"],
        "required_behavior_facts": [{"parameter": "flag", "terms": ["switch"]}],
    }
    contract = contracts.build_readcrop_contract(
        task, source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
    )
    nonsense = contracts.parse_readcrop_answer(
        '{"signature": "Example.method", "parameters": ["flag"], "behavior": "Nonsense context."}'
    )
    covered = contracts.parse_readcrop_answer(
        '{"signature": "Example.method", "parameters": ["flag"], "behavior": "Controls the switch."}'
    )

    nonsense_score = contracts.score_readcrop_answer(contract, nonsense)
    covered_score = contracts.score_readcrop_answer(contract, covered)

    assert contract.source_parameter_names == ("value", "flag")
    assert contract.required_parameter_names == ("flag",)
    assert nonsense_score.behavior_fact_recall == 0.0
    assert nonsense_score.behavior_facts_correct is False
    assert nonsense_score.primary_correct is False
    assert nonsense_score.quality_score == pytest.approx(2 / 3)
    assert covered_score.behavior_fact_recall == 1.0
    assert covered_score.behavior_facts_correct is True
    assert covered_score.primary_correct is True
    assert covered_score.quality_score == 1.0


def test_focused_parameters_must_exist_in_frozen_source() -> None:
    """Task authors cannot introduce an unverified focused parameter oracle."""
    task = {**_task(), "required_parameters": ["missing"]}

    with pytest.raises(ValueError, match="required_parameters are absent from source: missing"):
        contracts.build_readcrop_contract(
            task, source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
        )


def test_missing_focused_parameters_retain_exhaustive_source_wide_recall() -> None:
    """Tasks without a focused list retain the full source signature contract."""
    contract = contracts.build_readcrop_contract(
        _task(), source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
    )
    answer = contracts.parse_readcrop_answer(
        '{"signature": "Example.method", "parameters": ["value"], "behavior": "Context."}'
    )

    score = contracts.score_readcrop_answer(contract, answer)

    assert contract.required_parameter_names == ("value", "flag")
    assert score.parameter_recall == 0.5
    assert score.primary_correct is False


def test_behavior_facts_must_reference_source_validated_required_parameters() -> None:
    """Task behavior facts cannot add an unrelated unreviewed parameter."""
    task = {
        **_task(),
        "required_parameters": ["flag"],
        "required_behavior_facts": [{"parameter": "value", "terms": ["value"]}],
    }

    with pytest.raises(ValueError, match="behavior fact parameter is not required: value"):
        contracts.build_readcrop_contract(
            task, source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
        )


def test_provider_binding_cannot_change_task_or_oracle_identity() -> None:
    """Provider metadata may vary but shared read-crop truth must remain locked."""
    contract = contracts.build_readcrop_contract(
        _task(), source="def method(self, value: int, *, flag: bool = False) -> None:\n    pass\n"
    )
    binding = dict(contract.provider_binding())

    contracts.validate_provider_binding(contract, binding)
    assert len(binding["behavior_contract_sha256"]) == 64
    binding["oracle_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="scientific fields"):
        contracts.validate_provider_binding(contract, binding)


def test_tool_result_tokens_are_separate_from_provider_total_tokens() -> None:
    """Provider-native total and observed tool payload cost must not be conflated."""
    usage = contracts.ReadcropUsage(total_input_tokens=100, tool_result_tokens=30)

    assert usage.total_input_tokens == 100
    assert usage.tool_result_tokens == 30


def test_missing_native_tool_payload_cost_remains_unavailable() -> None:
    """A provider that omits payload accounting must not be coerced to zero."""
    usage = contracts.ReadcropUsage(total_input_tokens=100, tool_result_tokens=None)

    assert usage.tool_result_tokens is None
