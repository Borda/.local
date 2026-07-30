"""Acceptance contract for the provider-neutral parity contract library.

These tests intentionally define the small B1 surface shared by future provider
adapters. They do not exercise a provider CLI or execute a model.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import pytest

from benchmarks import provider_parity_contracts as core


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = BENCHMARKS_DIR / "results" / "manifests" / "provider-parity-v1.json"
SUITE_PATH = BENCHMARKS_DIR / "suites" / "tasks-bench.json"
EXPERIMENT_REVISION = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["experiment_revision"]


def _record(**overrides: Any) -> Any:
    """Build one eligible result record with deterministic pair coordinates."""
    values = {
        "revision": EXPERIMENT_REVISION,
        "provider": "claude",
        "model": "test-model",
        "task_id": "FN-02",
        "repetition": 1,
        "arm": "A_plain",
        "input_tokens": 100,
        "quality_score": 0.6,
    }
    values.update(overrides)
    return core.ResultRecord(**values)


def _synthetic_policies() -> dict[str, Any]:
    """Return the explicit independent-task policy required by synthetic pairing tests."""
    policy = core.TaskPolicy(
        experiment_revision=EXPERIMENT_REVISION,
        task_id="FN-02",
        oracle_class="independent",
        headline_eligible_v1=True,
        scoreable=True,
    )
    return {policy.task_id: policy}


def _manifest_task(task_id: str) -> dict[str, Any]:
    """Return the locked manifest row for one task ID."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for suite in manifest["suites"]:
        for task in suite["tasks"]:
            if task["id"] == task_id:
                return task
    raise AssertionError(f"manifest task {task_id!r} was not found")


class TestTaskSuiteLoading:
    """Raw task loading must not silently apply runner-specific normalization."""

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            pytest.param(
                [{"id": "L-01", "prompt": "list task", "custom": {"nested": True}}],
                [{"id": "L-01", "prompt": "list task", "custom": {"nested": True}}],
                id="bare-list",
            ),
            pytest.param(
                {
                    "repo": {"name": "fixture"},
                    "tasks": [{"id": "O-01", "prompt": "object task", "scoreable": False}],
                },
                [{"id": "O-01", "prompt": "object task", "scoreable": False}],
                id="object-wrapper",
            ),
        ],
    )
    def test_load_task_suite_valid_shape_preserves_raw_task_mapping(
        self, tmp_path: Path, payload: list[dict[str, Any]] | dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        """A list or wrapper loads exactly its raw task mappings without inferred fields."""
        suite_path = tmp_path / "suite.json"
        suite_path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = core.load_task_suite(suite_path)

        assert loaded == expected

    @pytest.mark.parametrize(
        ("payload", "error"),
        [
            pytest.param({"repo": {"name": "missing-tasks"}}, "tasks", id="wrapper-without-tasks"),
            pytest.param({"tasks": {"id": "not-a-list"}}, "list", id="wrapper-tasks-not-list"),
            pytest.param(["not a mapping"], "object", id="list-entry-not-object"),
            pytest.param([{"prompt": "missing id"}], "id", id="missing-id"),
            pytest.param([{"id": "M-01"}], "prompt", id="missing-prompt"),
            pytest.param([{"id": "", "prompt": "empty id"}], "id", id="empty-id"),
            pytest.param([{"id": "M-02", "prompt": ""}], "prompt", id="empty-prompt"),
            pytest.param(
                [{"id": "D-01", "prompt": "first"}, {"id": "D-01", "prompt": "duplicate"}],
                "duplicate",
                id="duplicate-id",
            ),
        ],
    )
    def test_load_task_suite_rejects_invalid_contract(self, tmp_path: Path, payload: object, error: str) -> None:
        """Malformed task files fail instead of changing suite membership or identity."""
        suite_path = tmp_path / "invalid-suite.json"
        suite_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match=error):
            core.load_task_suite(suite_path)


class TestCanonicalTaskIdentity:
    """Task and prompt identity must match the approved B0 manifest byte for byte."""

    def test_canonical_task_hash_and_prompt_hash_match_locked_manifest(self) -> None:
        """FN-02 has the manifest's raw-object hash and exact UTF-8 prompt hash."""
        suite = core.load_task_suite(SUITE_PATH)
        task = next(task for task in suite if task["id"] == "FN-02")
        locked = _manifest_task("FN-02")
        expected_bytes = json.dumps(task, sort_keys=True).encode("utf-8")

        assert core.canonical_task_bytes(task) == expected_bytes
        assert core.canonical_task_hash(task) == locked["canonical_task_sha256"]
        assert core.prompt_hash(task) == locked["prompt_sha256"]
        assert core.prompt_hash(task) == hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest()

    def test_canonical_task_hash_includes_raw_fields_without_normalization(self) -> None:
        """Adding a raw field changes identity, preventing inferred-field substitution."""
        task = {"id": "T-01", "prompt": "Inspect this.", "custom": {"order": 1}}
        altered_task = {**task, "scoreable": False}

        assert core.canonical_task_hash(task) != core.canonical_task_hash(altered_task)

    def test_semantic_suite_hash_tracks_ordered_tasks_not_root_wrapper_metadata(self) -> None:
        """Suite identity ignores transport metadata but detects task content and ordering drift."""
        tasks = [
            {"id": "T-01", "prompt": "First.", "type": "demo"},
            {"id": "T-02", "prompt": "Second.", "type": "demo"},
        ]

        expected = core.semantic_suite_hash(tasks)

        assert core.semantic_suite_hash(list(tasks)) == expected
        assert core.semantic_suite_hash(list(reversed(tasks))) != expected
        assert core.semantic_suite_hash([{**tasks[0], "prompt": "Changed."}, tasks[1]]) != expected


class TestArmContracts:
    """A/B/C instructions are locked separately from canonical task prompts."""

    def test_parity_timeout_is_one_shared_provider_neutral_budget(self) -> None:
        """Every provider adapter receives the same 600-second parity timeout."""
        assert core.PARITY_TIMEOUT_SECONDS == 600

    def test_arm_contracts_match_manifest_and_are_immutable(self) -> None:
        """The three semantic arm contracts retain their approved exact hashes."""
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        assert set(core.ARM_CONTRACTS) == {"A_plain", "B_auto", "C_required"}
        for arm, expected in manifest["arms"].items():
            actual = core.ARM_CONTRACTS[arm]
            assert actual["contract"] == expected["contract"]
            assert actual["contract_sha256"] == expected["contract_sha256"]
            assert "prompt" not in actual

        with pytest.raises(TypeError):
            core.ARM_CONTRACTS["A_plain"]["contract"] = "changed"

    def test_arm_contract_lookup_does_not_mutate_task_prompt(self) -> None:
        """Arm metadata remains separate so every provider receives identical task bytes."""
        task = {"id": "T-02", "prompt": "Keep these exact bytes: café."}
        original_prompt = task["prompt"]
        original_bytes = core.canonical_task_bytes(task)

        for arm in core.ARM_CONTRACTS:
            _ = core.ARM_CONTRACTS[arm]["contract"]

        assert task["prompt"] == original_prompt
        assert core.canonical_task_bytes(task) == original_bytes

    def test_arm_order_is_revision_bound_and_rejects_invalid_coordinates(self) -> None:
        """One block has a stable complete order that changes with experiment identity."""
        r6_order = core.deterministic_arm_order(
            "codemap-provider-parity-v1-b0-r6",
            "codex",
            "gpt-5.6-luna",
            "FN-02",
            1,
        )

        assert r6_order == ("C_required", "A_plain", "B_auto")
        assert set(r6_order) == set(core.ARM_CONTRACTS)
        assert r6_order != core.deterministic_arm_order(
            "codemap-provider-parity-v1-b0-r5",
            "codex",
            "gpt-5.6-luna",
            "FN-02",
            1,
        )
        with pytest.raises(ValueError, match="repetition"):
            core.deterministic_arm_order("r4", "codex", "model", "FN-02", 0)

    def test_arm_order_includes_reasoning_effort_in_the_model_stratum(self) -> None:
        """Effort drift must change the randomized block identity."""
        high = [
            core.deterministic_arm_order(
                "r7",
                "codex",
                "gpt-5.6-luna",
                f"T-{index}",
                1,
                reasoning_effort="high",
            )
            for index in range(12)
        ]
        medium = [
            core.deterministic_arm_order(
                "r7",
                "codex",
                "gpt-5.6-luna",
                f"T-{index}",
                1,
                reasoning_effort="medium",
            )
            for index in range(12)
        ]

        assert high == [
            core.deterministic_arm_order(
                "r7",
                "codex",
                "gpt-5.6-luna",
                f"T-{index}",
                1,
                reasoning_effort="high",
            )
            for index in range(12)
        ]
        assert any(left != right for left, right in zip(high, medium))

    @pytest.mark.parametrize(
        ("task", "expected"),
        [
            (
                {"type": "develop_blast_radius", "ground_truth": {"fn_callers": [str(i) for i in range(20)]}},
                ("direct_reverse_call", "high_fan_in"),
            ),
            (
                {"type": "graph_fn_blast", "ground_truth": {"blast_callers": ["a", "b"]}},
                ("transitive_reverse_call",),
            ),
            (
                {"type": "graph_path", "ground_truth": {"import_path": ["a", "b", "c"]}},
                ("dependency_path",),
            ),
            (
                {"type": "diff_impact", "ground_truth": {"fn_callers": ["a"], "test_modules": ["test_a"]}},
                ("diff_impact", "test_selection"),
            ),
        ],
    )
    def test_capability_strata_expose_where_codemap_can_help(
        self,
        task: dict[str, Any],
        expected: tuple[str, ...],
    ) -> None:
        """The suite must expose named structural-capability strata."""
        assert core.capability_strata(task) == expected

    def test_r5_changes_only_transport_control_not_locked_benchmark_inputs(self) -> None:
        """The r5 profile relock must preserve every r4 suite, task, and prompt identity."""
        r5_path = MANIFEST_PATH.with_name("provider-parity-v1-b0-r5.json")
        r5 = json.loads(r5_path.read_text(encoding="utf-8"))
        r4_path = MANIFEST_PATH.with_name("provider-parity-v1-b0-r4.json")
        r4 = json.loads(r4_path.read_text(encoding="utf-8"))

        def locked_identities(manifest: dict[str, Any]) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
            return [
                (
                    suite["path"],
                    suite["raw_sha256"],
                    [(task["id"], task["canonical_task_sha256"], task["prompt_sha256"]) for task in suite["tasks"]],
                )
                for suite in manifest["suites"]
            ]

        assert locked_identities(r5) == locked_identities(r4)
        assert r5["target_source"] == r4["target_source"]
        assert r5["index"] == r4["index"]
        assert r5["arms"].keys() == r4["arms"].keys()
        for arm in r5["arms"]:
            assert r5["arms"][arm]["contract"] == r4["arms"][arm]["contract"]
            assert r5["arms"][arm]["contract_sha256"] == r4["arms"][arm]["contract_sha256"]

    def test_r6_changes_only_treatment_runtime_not_locked_benchmark_inputs(self) -> None:
        """The r6 runtime relock must preserve all r5 experimental inputs except runtime."""
        r6 = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        r5_path = MANIFEST_PATH.with_name("provider-parity-v1-b0-r5.json")
        r5 = json.loads(r5_path.read_text(encoding="utf-8"))

        def locked_identities(manifest: dict[str, Any]) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
            return [
                (
                    suite["path"],
                    suite["raw_sha256"],
                    [(task["id"], task["canonical_task_sha256"], task["prompt_sha256"]) for task in suite["tasks"]],
                )
                for suite in manifest["suites"]
            ]

        assert locked_identities(r6) == locked_identities(r5)
        assert r6["target_source"] == r5["target_source"]
        assert r6["index"] == r5["index"]
        assert r6["arms"] == r5["arms"]
        assert r6["preregistered_cells"] == r5["preregistered_cells"]
        assert r6["codex_permission_profiles"]["plain"] == r5["codex_permission_profiles"]["plain"]
        assert r6["codex_permission_profiles"]["treatment"] == r5["codex_permission_profiles"]["treatment"]

    def test_r6_manifest_locks_split_profiles_runtime_and_structural_only_runner(self) -> None:
        """The active manifest must describe the exact tested Codex permission/runtime boundary."""
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        profiles = manifest["codex_permission_profiles"]

        assert manifest["experiment_revision"] == "codemap-provider-parity-v1-b0-r6"
        assert manifest["status"] == "r6_manifest_review_required_before_paid_smoke"
        assert profiles["plain"]["extends"] == ":read-only"
        assert profiles["plain"]["write_roots"] == []
        assert profiles["plain"]["filesystem_overrides"]["<locked-index-parent>"] == "deny"
        assert profiles["treatment"]["extends"] == ":read-only"
        assert profiles["treatment"]["write_roots"] == ["<locked-index-parent>/.index-rw"]
        assert profiles["plain"]["network_enabled"] is False
        assert profiles["treatment"]["network_enabled"] is False
        assert profiles["shell_environment"]["inherit"] == "none"
        assert profiles["shell_environment"]["secret_inheritance"] is False
        assert profiles["treatment_runtime"] == {
            "environment": {"CODEMAP_PYTHON": "/opt/homebrew/bin/python3.11"},
            "required_major_minor": [3, 11],
            "scope": ["B_auto", "C_required"],
        }
        assert manifest["execution_controls"]["codex_transport"] == (
            "run-codex-structural.py; no Codex agentic adapter is registered in r6"
        )


class TestTaskPolicies:
    """The B0 manifest is the sole source of headline eligibility policy."""

    def test_load_task_policies_matches_every_unique_manifest_task_and_revision(self) -> None:
        """Every manifest row becomes one immutable policy carrying its experiment revision."""
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_rows = [task for suite in manifest["suites"] for task in suite["tasks"]]

        policies = core.load_task_policies(MANIFEST_PATH)

        assert set(policies) == {task["id"] for task in expected_rows}
        assert len(policies) == len(expected_rows)
        for task in expected_rows:
            policy = policies[task["id"]]
            assert policy.experiment_revision == manifest["experiment_revision"]
            assert policy.task_id == task["id"]
            assert policy.oracle_class == task["oracle_class"]
            assert policy.headline_eligible_v1 is task["headline_eligible_v1"]
            assert policy.scoreable is task["effective_scoreable"]

        with pytest.raises(TypeError):
            policies["FN-02"] = policies["FN-02"]
        with pytest.raises(AttributeError):
            policies["FN-02"].scoreable = False

    def test_manifest_policy_keeps_known_diagnostic_tasks_out_of_headline_pairing(self) -> None:
        """Policy, not optional record flags, blocks approved diagnostic and unscoreable tasks."""
        policies = core.load_task_policies(MANIFEST_PATH)

        assert policies["SE-01"].oracle_class == "static_reference"
        assert policies["RI-05"].scoreable is False
        for task_id in ("SE-01", "RV-05", "CQ-02", "CQ-03", "CQ-04", "CQ-05", "RI-05"):
            assert core.result_eligibility(_record(task_id=task_id), policies) is False


class TestEvaluatorRegistry:
    """Scoring dispatch is explicit, provider-neutral, and fail-closed."""

    def test_evaluate_scoreable_task_uses_registered_evaluator_without_provider(self) -> None:
        """Identical adapter-labelled calls receive an identical shared score."""
        calls: list[tuple[dict[str, Any], str]] = []

        def evaluate_demo(task: dict[str, Any], output_text: str) -> Any:
            calls.append((task, output_text))
            return core.EvaluationResult(scored=True, correct=True, quality_score=0.75)

        registry = core.EvaluatorRegistry({"demo": evaluate_demo})
        task = {"id": "EV-01", "prompt": "Score me", "type": "demo", "scoreable": True}
        output_text = "shared answer"

        adapter_results = {adapter: registry.evaluate(task, output_text) for adapter in ("claude", "codex")}

        assert tuple(inspect.signature(registry.evaluate).parameters) == ("task", "output_text")
        assert adapter_results["claude"] == adapter_results["codex"]
        assert adapter_results["claude"].scored is True
        assert adapter_results["claude"].correct is True
        assert adapter_results["claude"].quality_score == pytest.approx(0.75)
        assert calls == [(task, output_text), (task, output_text)]

    def test_evaluate_unscoreable_task_bypasses_unknown_evaluator(self) -> None:
        """A deliberately unscoreable task remains diagnostic without registry dispatch."""
        registry = core.EvaluatorRegistry({})

        result = registry.evaluate({"id": "U-01", "type": "unknown", "scoreable": False}, "answer")

        assert result == core.EvaluationResult(scored=False, correct=False, quality_score=None)

    def test_evaluate_unknown_scoreable_task_rejects_methodology_drift(self) -> None:
        """A new scoreable type cannot silently become an unscored result."""
        registry = core.EvaluatorRegistry({})

        with pytest.raises(ValueError, match="unknown"):
            registry.evaluate({"id": "U-02", "type": "unknown", "scoreable": True}, "answer")


class TestResultEligibility:
    """Headline pairing excludes preregistered diagnostic and failed-result classes."""

    def test_result_eligibility_requires_explicit_policy_mapping(self) -> None:
        """Eligibility without B0 policy provenance cannot infer a headline result."""
        with pytest.raises(TypeError):
            core.result_eligibility(_record())

    def test_result_eligibility_accepts_clean_independent_score(self) -> None:
        """A complete independent scoreable result is eligible for paired headline metrics."""
        assert core.result_eligibility(_record(), _synthetic_policies()) is True

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"scoreable": False}, id="unscoreable"),
            pytest.param({"self_consistency": True}, id="self-consistency"),
            pytest.param({"approximate": True}, id="approximate-oracle"),
            pytest.param({"static_reference": True}, id="static-reference"),
            pytest.param({"incomplete": True}, id="incomplete"),
            pytest.param({"extraction_failed": True}, id="extraction-failed"),
            pytest.param({"contaminated": True}, id="contaminated"),
        ],
    )
    def test_result_eligibility_rejects_excluded_result_class(self, overrides: dict[str, Any]) -> None:
        """Each labelled diagnostic/failure state stays out of the headline pair population."""
        assert core.result_eligibility(_record(**overrides), _synthetic_policies()) is False

    @pytest.mark.parametrize(
        "record",
        [
            pytest.param(_record(task_id="unknown"), id="unknown-task"),
            pytest.param(_record(revision="wrong-revision"), id="wrong-revision"),
        ],
    )
    def test_result_eligibility_rejects_unknown_policy_or_revision(self, record: Any) -> None:
        """An omitted or mismatched policy coordinate cannot become headline-eligible by default."""
        with pytest.raises(ValueError):
            core.result_eligibility(record, _synthetic_policies())


class TestPairedEffects:
    """Pair construction is repetition-preserving and block-local."""

    def test_pair_effects_preserves_repetitions_and_computes_effects(self) -> None:
        """Each task repetition produces its own log token ratio and quality delta."""
        records = [
            _record(arm="A_plain", repetition=1, input_tokens=100, quality_score=0.6),
            _record(arm="C_required", repetition=1, input_tokens=50, quality_score=0.8),
            _record(arm="A_plain", repetition=2, input_tokens=80, quality_score=1.0),
            _record(arm="C_required", repetition=2, input_tokens=160, quality_score=0.5),
        ]

        effects = core.pair_effects(
            records,
            baseline_arm="A_plain",
            treatment_arm="C_required",
            policies=_synthetic_policies(),
        )
        by_repetition = {effect.repetition: effect for effect in effects}

        assert set(by_repetition) == {1, 2}
        assert by_repetition[1].provider == "claude"
        assert by_repetition[1].model == "test-model"
        assert by_repetition[1].revision == EXPERIMENT_REVISION
        assert by_repetition[1].task_id == "FN-02"
        assert by_repetition[1].log_input_token_ratio == pytest.approx(math.log(0.5))
        assert by_repetition[1].quality_delta == pytest.approx(0.2)
        assert by_repetition[2].log_input_token_ratio == pytest.approx(math.log(2.0))
        assert by_repetition[2].quality_delta == pytest.approx(-0.5)

    def test_pair_effects_keeps_provider_blocks_separate(self) -> None:
        """Equal task/repetition coordinates from two providers cannot be pooled together."""
        records = [
            _record(arm="A_plain", provider="claude"),
            _record(arm="B_auto", provider="claude", input_tokens=50, quality_score=0.7),
            _record(arm="A_plain", provider="codex"),
            _record(arm="B_auto", provider="codex", input_tokens=200, quality_score=0.4),
        ]

        effects = core.pair_effects(
            records,
            baseline_arm="A_plain",
            treatment_arm="B_auto",
            policies=_synthetic_policies(),
        )
        by_provider = {effect.provider: effect for effect in effects}

        assert set(by_provider) == {"claude", "codex"}
        assert by_provider["claude"].log_input_token_ratio == pytest.approx(math.log(0.5))
        assert by_provider["claude"].quality_delta == pytest.approx(0.1)
        assert by_provider["codex"].log_input_token_ratio == pytest.approx(math.log(2.0))
        assert by_provider["codex"].quality_delta == pytest.approx(-0.2)

    @pytest.mark.parametrize(
        "records",
        [
            pytest.param(
                [_record(arm="A_plain")],
                id="missing-treatment-arm",
            ),
            pytest.param(
                [
                    _record(arm="A_plain"),
                    _record(arm="B_auto", provider="codex"),
                ],
                id="cross-provider-arms-cannot-pair",
            ),
            pytest.param(
                [
                    _record(arm="A_plain"),
                    _record(arm="A_plain", input_tokens=90),
                    _record(arm="B_auto"),
                ],
                id="duplicate-baseline-cell",
            ),
        ],
    )
    def test_pair_effects_rejects_missing_or_duplicate_cells(self, records: list[Any]) -> None:
        """Missing arms and duplicate arm cells must fail instead of being silently discarded."""
        with pytest.raises(ValueError):
            core.pair_effects(
                records,
                baseline_arm="A_plain",
                treatment_arm="B_auto",
                policies=_synthetic_policies(),
            )

    def test_pair_effects_requires_explicit_policy_mapping(self) -> None:
        """Pairing without B0 policy provenance is rejected instead of inferring eligibility."""
        records = [_record(arm="A_plain"), _record(arm="B_auto")]

        with pytest.raises(TypeError):
            core.pair_effects(records, baseline_arm="A_plain", treatment_arm="B_auto")

    def test_pair_effects_rejects_policy_ineligible_task_with_clean_record_flags(self) -> None:
        """Diagnostic task IDs remain excluded even when every ResultRecord flag uses its default."""
        policies = core.load_task_policies(MANIFEST_PATH)
        records = [
            _record(arm="A_plain", task_id="RV-05"),
            _record(arm="B_auto", task_id="RV-05"),
        ]

        with pytest.raises(ValueError, match="ineligible"):
            core.pair_effects(records, baseline_arm="A_plain", treatment_arm="B_auto", policies=policies)

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"input_tokens": 0}, id="zero-input-tokens"),
            pytest.param({"quality_score": True}, id="bool-quality-score"),
            pytest.param({"quality_score": float("nan")}, id="nan-quality-score"),
        ],
    )
    def test_pair_effects_rejects_invalid_numeric_record_values(self, overrides: dict[str, Any]) -> None:
        """Invalid token and quality values cannot produce undefined or misleading effects."""
        records = [
            _record(arm="A_plain", **overrides),
            _record(arm="B_auto"),
        ]

        with pytest.raises(ValueError):
            core.pair_effects(
                records,
                baseline_arm="A_plain",
                treatment_arm="B_auto",
                policies=_synthetic_policies(),
            )
