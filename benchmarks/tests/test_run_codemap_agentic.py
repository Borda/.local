"""Tests for benchmarks/run-codemap-agentic.py public API.

Scope: black-box testing of public classes and functions against documented
contracts.  No live ``claude`` subprocess is launched.  Any test that
requires a real codemap index on disk is guarded with
``pytest.mark.skip`` and a clear reason.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Fixtures
# ===========================================================================


def _make_task(mod: Any, **kwargs: Any) -> Any:
    """Return a minimal valid Task, overriding fields via kwargs."""
    defaults = {
        "id": "BA-01",
        "type": "fix",
        "prompt": "Describe blast radius.",
        "primary_module": "lightning.pytorch.callbacks.timer",
        "difficulty": "simple",
    }
    defaults.update(kwargs)
    return mod.Task(**defaults)


def _minimal_index(modules: list[dict]) -> dict:
    """Return a minimal codemap index dict with the given module list."""
    return {"modules": modules}


@pytest.fixture()
def tmp_index(tmp_path: Path, script_run_agentic: Any) -> Path:
    """Write a minimal codemap index to a temporary file and return its path."""
    data = _minimal_index(
        [
            {
                "name": "lightning.pytorch.trainer.trainer",
                "direct_imports": ["lightning.pytorch.callbacks.timer"],
                "dep_count": 10,
                "status": "ok",
            },
            {
                "name": "lightning.pytorch.loops.fit_loop",
                "direct_imports": ["lightning.pytorch.callbacks.timer"],
                "dep_count": 5,
                "status": "ok",
            },
            {
                "name": "lightning.pytorch.callbacks.timer",
                "direct_imports": [],
                "dep_count": 0,
                "status": "ok",
            },
            {
                "name": "tests.test_timer",
                "direct_imports": ["lightning.pytorch.callbacks.timer"],
                "dep_count": 0,
                "status": "ok",
            },
        ]
    )
    index_file = tmp_path / "pytorch-lightning.json"
    index_file.write_text(json.dumps(data))
    return index_file


@pytest.fixture()
def ground_truth(tmp_index: Path, script_run_agentic: Any) -> Any:
    """GroundTruth instance loaded from the tmp_index fixture."""
    task = _make_task(
        script_run_agentic,
        id="BA-01",
        primary_module="lightning.pytorch.callbacks.timer",
    )
    return script_run_agentic.GroundTruth(tmp_index, [task])


# ===========================================================================
# class Task
# ===========================================================================


class TestTask:
    def test_construction_with_required_fields(self, script_run_agentic: Any) -> None:
        """Task with only required fields sets defaults for optional ones.

        Scenario: user builds a Task by supplying id, type, prompt only;
        expects primary_module='', difficulty='unknown' per docstring.
        """
        task = script_run_agentic.Task(id="T01", type="fix", prompt="Fix the bug.")
        assert task.id == "T01"
        assert task.type == "fix"
        assert task.prompt == "Fix the bug."
        assert task.primary_module == ""
        assert task.difficulty == "unknown"

    def test_construction_with_all_fields(self, script_run_agentic: Any) -> None:
        """Task stores every supplied field correctly.

        Scenario: user supplies all optional fields explicitly; values must
        round-trip through the dataclass without modification.
        """
        task = script_run_agentic.Task(
            id="BA-42",
            type="review",
            prompt="Review this change.",
            primary_module="lightning.pytorch.trainer.trainer",
            difficulty="hard",
        )
        assert task.id == "BA-42"
        assert task.type == "review"
        assert task.primary_module == "lightning.pytorch.trainer.trainer"
        assert task.difficulty == "hard"

    @pytest.mark.parametrize(
        "task_type",
        ["fix", "feature", "refactor", "review"],
    )
    def test_accepted_task_types(self, script_run_agentic: Any, task_type: str) -> None:
        """Task accepts all four documented type values without error.

        Scenario: user creates a Task for each benchmark arm type listed
        in the module docstring; no ValueError should be raised.
        """
        task = script_run_agentic.Task(id="X01", type=task_type, prompt="p")
        assert task.type == task_type


# ===========================================================================
# class ToolCounts
# ===========================================================================


class TestToolCounts:
    def test_total_returns_zero_for_default_instance(self, script_run_agentic: Any) -> None:
        """ToolCounts.total is 0 when no tool has been called.

        Scenario: a freshly initialised ToolCounts object has all counters
        at 0; the documented property must return 0.
        """
        tc = script_run_agentic.ToolCounts()
        assert tc.total == 0

    @pytest.mark.parametrize(
        "kwargs,expected_total",
        [
            ({"grep": 3, "bash": 1, "semble": 2}, 6),  # docstring example
            ({"grep": 0, "glob": 0, "bash": 0, "skill": 0, "semble": 0}, 0),
            ({"grep": 1}, 1),
            ({"glob": 5, "skill": 3}, 8),
            ({"grep": 10, "glob": 10, "bash": 10, "skill": 10, "semble": 10}, 50),
        ],
    )
    def test_total_sums_main_counters(self, script_run_agentic: Any, kwargs: dict, expected_total: int) -> None:
        """ToolCounts.total sums grep+glob+bash+skill+semble only.

        Scenario: user constructs ToolCounts with various counter values;
        total must equal the sum of the five core counters. ``blocked``
        and ``bash_for_imports`` are diagnostic fields excluded from total
        per the documented formula.
        """
        tc = script_run_agentic.ToolCounts(**kwargs)
        assert tc.total == expected_total

    def test_total_excludes_blocked_and_bash_for_imports(self, script_run_agentic: Any) -> None:
        """blocked and bash_for_imports are NOT counted in total.

        Scenario: user sets only the diagnostic counters; total must
        remain 0 because these are not exploration tool calls.
        """
        tc = script_run_agentic.ToolCounts(blocked=5, bash_for_imports=3)
        assert tc.total == 0

    def test_total_is_read_only_property(self, script_run_agentic: Any) -> None:
        """ToolCounts.total cannot be assigned (it is a property).

        Scenario: attempting to set total raises AttributeError; the
        docstring declares it as a property, not a settable field.
        """
        tc = script_run_agentic.ToolCounts()
        with pytest.raises(AttributeError):
            tc.total = 99  # type: ignore[misc]


# ===========================================================================
# class QualityScore
# ===========================================================================


class TestQualityScore:
    def test_default_instance_has_scored_false(self, script_run_agentic: Any) -> None:
        """QualityScore() with no args defaults to scored=False.

        Scenario: quality scoring not applicable (task has no primary_module);
        the sentinel field scored must be False, all metrics 0.
        """
        qs = script_run_agentic.QualityScore()
        assert qs.scored is False

    def test_default_numeric_fields_are_zero(self, script_run_agentic: Any) -> None:
        """All numeric fields in a default QualityScore are 0 or 0.0.

        Scenario: user inspects a blank QualityScore expecting clean zeros;
        no NaN or None values should appear in primary metric fields.
        """
        qs = script_run_agentic.QualityScore()
        for attr in ("erec", "rrec", "delta", "deff", "erec_top10", "precision", "recall", "f1", "leaf_recall"):
            assert getattr(qs, attr) == 0.0, f"{attr} should default to 0.0"
        for attr in (
            "erec_tp",
            "erec_fn",
            "rrec_tp",
            "rrec_fn",
            "erec_top10_k",
            "tp",
            "fp",
            "fn",
            "leaf_tp",
            "leaf_fn",
            "ambiguous_leaves",
        ):
            assert getattr(qs, attr) == 0, f"{attr} should default to 0"

    def test_optional_skill_fields_default_to_none(self, script_run_agentic: Any) -> None:
        """skill_coverage and skill_returned default to None.

        Scenario: plain arm never invokes the Skill tool; fields must be
        None (not 0.0) to distinguish 'not applicable' from 'zero coverage'.
        """
        qs = script_run_agentic.QualityScore()
        assert qs.skill_coverage is None
        assert qs.skill_returned is None


# ===========================================================================
# class BenchmarkRun
# ===========================================================================


class TestBenchmarkRun:
    def test_required_fields_stored(self, script_run_agentic: Any) -> None:
        """BenchmarkRun stores the four required positional fields.

        Scenario: benchmark creates a run result record; arm, task_id,
        task_type and model must be accessible after construction.
        """
        run = script_run_agentic.BenchmarkRun(
            arm="plain", task_id="BA-01", task_type="fix", model="haiku", success=False
        )
        assert run.arm == "plain"
        assert run.task_id == "BA-01"
        assert run.task_type == "fix"
        assert run.model == "haiku"
        assert run.success is False

    def test_optional_fields_default_to_zero(self, script_run_agentic: Any) -> None:
        """BenchmarkRun token and timing fields default to 0 / 0.0.

        Scenario: a freshly created run before any events are parsed must
        have zero metrics to avoid polluting aggregation.
        """
        run = script_run_agentic.BenchmarkRun(
            arm="codemap", task_id="T1", task_type="fix", model="haiku", success=False
        )
        assert run.input_tokens == 0
        assert run.output_tokens == 0
        assert run.tool_result_tokens == 0
        assert run.elapsed_s == 0.0
        assert run.tool_elapsed_s == 0.0
        assert run.error == ""

    def test_tools_defaults_to_empty_tool_counts(self, script_run_agentic: Any) -> None:
        """BenchmarkRun.tools is an empty ToolCounts by default.

        Scenario: no tool calls have occurred yet; total must be 0.
        """
        run = script_run_agentic.BenchmarkRun(arm="plain", task_id="T1", task_type="fix", model="haiku", success=False)
        assert isinstance(run.tools, script_run_agentic.ToolCounts)
        assert run.tools.total == 0

    def test_quality_defaults_to_unscored_quality_score(self, script_run_agentic: Any) -> None:
        """BenchmarkRun.quality defaults to QualityScore(scored=False).

        Scenario: run before quality scoring is applied must not falsely
        claim scored=True.
        """
        run = script_run_agentic.BenchmarkRun(arm="plain", task_id="T1", task_type="fix", model="haiku", success=False)
        assert isinstance(run.quality, script_run_agentic.QualityScore)
        assert run.quality.scored is False

    def test_tool_log_and_output_text_default_to_empty(self, script_run_agentic: Any) -> None:
        """tool_log and output_text start as empty collections / strings."""
        run = script_run_agentic.BenchmarkRun(arm="plain", task_id="T1", task_type="fix", model="haiku", success=False)
        assert run.tool_log == []
        assert run.output_text == ""

    @pytest.mark.parametrize("arm", ["plain", "codemap", "semble", "combined"])
    def test_accepted_arm_values(self, script_run_agentic: Any, arm: str) -> None:
        """BenchmarkRun stores all four documented arm identifiers.

        Scenario: the benchmark creates one BenchmarkRun per arm; all four
        documented values must be stored without error.
        """
        run = script_run_agentic.BenchmarkRun(arm=arm, task_id="T1", task_type="fix", model="haiku", success=True)
        assert run.arm == arm


# ===========================================================================
# find_index
# ===========================================================================


class TestFindIndex:
    def test_explicit_path_returned_resolved(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index returns the explicit path resolved when supplied.

        Scenario: user passes --index /some/path; the function must return
        that exact path (resolved) without searching .cache/.
        """
        index = tmp_path / "my-index.json"
        index.write_text("{}")
        result = script_run_agentic.find_index(tmp_path, index)
        assert result == index.resolve()

    def test_discovers_preferred_name_in_codemap_cache(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index prefers <repo_name>.json inside .cache/codemap/.

        Scenario: the repo is named ``myrepo``; a file ``myrepo.json``
        exists under ``.cache/codemap/``; that file must be returned.
        """
        repo = tmp_path / "myrepo"
        repo.mkdir()
        cache = repo / ".cache" / "codemap"
        cache.mkdir(parents=True)
        idx = cache / "myrepo.json"
        idx.write_text("{}")
        result = script_run_agentic.find_index(repo, None)
        assert result == idx.resolve()

    def test_falls_back_to_first_json_in_codemap_cache(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index falls back to lexicographically first *.json when preferred missing.

        Scenario: the repo is named ``myrepo`` but only ``other.json``
        exists in .cache/codemap/; that file must be returned.
        """
        repo = tmp_path / "myrepo"
        repo.mkdir()
        cache = repo / ".cache" / "codemap"
        cache.mkdir(parents=True)
        idx = cache / "other.json"
        idx.write_text("{}")
        result = script_run_agentic.find_index(repo, None)
        assert result == idx.resolve()

    def test_scans_scan_cache_dir_when_codemap_empty(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index checks .cache/scan/ when .cache/codemap/ has no JSON.

        Scenario: user stores their index under .cache/scan/ (legacy path);
        the function must discover it there.
        """
        repo = tmp_path / "myrepo"
        repo.mkdir()
        scan_cache = repo / ".cache" / "scan"
        scan_cache.mkdir(parents=True)
        idx = scan_cache / "myrepo.json"
        idx.write_text("{}")
        result = script_run_agentic.find_index(repo, None)
        assert result == idx.resolve()

    def test_raises_file_not_found_when_no_index_exists(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index raises FileNotFoundError when no index is found anywhere.

        Scenario: user forgot to run scan-index; the function must raise
        FileNotFoundError with an actionable message (per Raises: doc).
        """
        repo = tmp_path / "emptyrepo"
        repo.mkdir()
        with pytest.raises(FileNotFoundError, match="No codemap index found"):
            script_run_agentic.find_index(repo, None)

    def test_codemap_cache_preferred_over_scan_cache(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """find_index checks .cache/codemap/ before .cache/scan/.

        Scenario: both cache dirs contain a JSON file; the one under
        .cache/codemap/ must take priority per documented search order.
        """
        repo = tmp_path / "myrepo"
        repo.mkdir()
        codemap_cache = repo / ".cache" / "codemap"
        codemap_cache.mkdir(parents=True)
        scan_cache = repo / ".cache" / "scan"
        scan_cache.mkdir(parents=True)
        codemap_idx = codemap_cache / "myrepo.json"
        codemap_idx.write_text("{}")
        scan_idx = scan_cache / "myrepo.json"
        scan_idx.write_text("{}")
        result = script_run_agentic.find_index(repo, None)
        assert result == codemap_idx.resolve()


# ===========================================================================
# count_tokens
# ===========================================================================


class TestCountTokens:
    def test_empty_string_returns_nonzero_or_zero(self, script_run_agentic: Any) -> None:
        """count_tokens on an empty string returns 0 (tiktoken encodes nothing).

        Scenario: tool result with no content; token count must be a
        non-negative integer so it does not corrupt running totals.
        """
        result = script_run_agentic.count_tokens("")
        assert isinstance(result, int)
        assert result >= 0

    def test_non_empty_string_returns_positive_count(self, script_run_agentic: Any) -> None:
        """count_tokens on non-empty text returns a positive integer.

        Scenario: a real tool result string; token estimate must be > 0.
        """
        result = script_run_agentic.count_tokens("hello world")
        assert result > 0

    def test_longer_text_has_higher_count_than_shorter(self, script_run_agentic: Any) -> None:
        """Longer text produces a higher token count than shorter text.

        Scenario: comparing two tool results of different lengths; the
        longer one must always produce a higher count (monotonicity).
        """
        short = "hello"
        long_text = "hello world this is a much longer sentence with many more tokens"
        assert script_run_agentic.count_tokens(long_text) > script_run_agentic.count_tokens(short)

    def test_returns_integer_type(self, script_run_agentic: Any) -> None:
        """count_tokens always returns int, not float.

        Scenario: the return value is added to BenchmarkRun.tool_result_tokens
        (an int field); non-integer would cause a type error at runtime.
        """
        result = script_run_agentic.count_tokens("some text")
        assert isinstance(result, int)


# ===========================================================================
# GroundTruth — _generate_match_set (static, pure)
# ===========================================================================


class TestGroundTruthGenerateMatchSet:
    """Tests for the static pattern-generation helper via its observable effects."""

    @pytest.mark.parametrize(
        "module,corpus,should_match",
        [
            # Full dotted path must match
            (
                "lightning.pytorch.trainer.trainer",
                "lightning.pytorch.trainer.trainer",
                True,
            ),
            # File path form must match
            (
                "lightning.pytorch.trainer.trainer",
                "lightning/pytorch/trainer/trainer.py",
                True,
            ),
            # src/ file path form must match
            (
                "lightning.pytorch.trainer.trainer",
                "src/lightning/pytorch/trainer/trainer.py",
                True,
            ),
            # 2-component suffix dotted must match
            (
                "lightning.pytorch.trainer.trainer",
                "trainer.trainer",
                True,
            ),
            # 2-component suffix slash must match
            (
                "lightning.pytorch.trainer.trainer",
                "trainer/trainer",
                True,
            ),
            # 3-component suffix must match
            (
                "lightning.pytorch.trainer.trainer",
                "pytorch.trainer.trainer",
                True,
            ),
            # Bare leaf name must NOT match (enforced minimum 2 components)
            (
                "lightning.pytorch.trainer.trainer",
                "trainer",
                False,
            ),
            # Unrelated text must not match
            (
                "lightning.pytorch.trainer.trainer",
                "completely unrelated text",
                False,
            ),
        ],
    )
    def test_pattern_matches_expected_forms(
        self, script_run_agentic: Any, module: str, corpus: str, should_match: bool
    ) -> None:
        """_generate_match_set creates patterns matching documented surface forms.

        Scenario: the docstring states at least 2 path components are required
        and lists specific forms; each form is tested for correct match/no-match.
        """
        patterns = script_run_agentic.GroundTruth._generate_match_set(module)
        matched = any(p.search(corpus) for p in patterns)
        assert matched == should_match, (
            f"module={module!r}, corpus={corpus!r}: expected match={should_match}, got match={matched}"
        )


# ===========================================================================
# GroundTruth — score()
# ===========================================================================


class TestGroundTruthScore:
    def test_returns_unscored_when_no_ground_truth_for_task(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() returns QualityScore(scored=False) when task has no expected rdeps.

        Scenario: task_id unknown to the index; score() must return an
        unscored sentinel per the documented contract.
        """
        result = ground_truth.score(
            task_id="NONEXISTENT",
            output_text="some output",
            exposure_corpus="some output",
            report_corpus="some output",
        )
        assert result.scored is False
        assert result.erec == 0.0
        assert result.rrec == 0.0

    def test_full_recall_when_all_rdeps_in_corpus(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() returns erec=1.0 when all expected rdeps appear in corpus.

        Scenario: an ideal codemap arm output that lists all expected modules;
        erec should be 1.0 and scored=True.
        """
        corpus = "lightning.pytorch.trainer.trainer lightning.pytorch.loops.fit_loop"
        result = ground_truth.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
        )
        assert result.scored is True
        assert result.erec == pytest.approx(1.0)
        assert result.rrec == pytest.approx(1.0)

    def test_zero_recall_when_no_rdeps_in_corpus(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() returns erec=0.0 when no expected rdeps appear in corpus.

        Scenario: agent output mentions no relevant modules; recall must be 0.
        """
        result = ground_truth.score(
            task_id="BA-01",
            output_text="I could not find the answer.",
            exposure_corpus="I could not find the answer.",
            report_corpus="I could not find the answer.",
        )
        assert result.scored is True
        assert result.erec == pytest.approx(0.0)

    def test_partial_recall_computed_correctly(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() correctly computes erec when only a subset of rdeps are found.

        Scenario: two expected rdeps; agent finds only one; erec must be 0.5.
        """
        corpus = "lightning.pytorch.trainer.trainer"
        result = ground_truth.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
        )
        assert result.scored is True
        assert result.erec == pytest.approx(0.5)

    @pytest.mark.parametrize(
        "found_count,expected_recall",
        [
            (7, 0.7),
            (6, 0.6),
            (10, 1.0),
        ],
    )
    def test_recall_boundary_values_are_exact(
        self, script_run_agentic: Any, tmp_path: Path, found_count: int, expected_recall: float
    ) -> None:
        """score() reports exact recall fractions around the downstream 70% boundary."""
        primary = "pkg.primary"
        callers = [f"pkg.caller{i}" for i in range(10)]
        data = _minimal_index(
            [{"name": primary, "direct_imports": [], "dep_count": 0, "status": "ok"}]
            + [{"name": caller, "direct_imports": [primary], "dep_count": 0, "status": "ok"} for caller in callers]
        )
        index_file = tmp_path / "index.json"
        index_file.write_text(json.dumps(data))
        task = _make_task(script_run_agentic, id="BND-01", primary_module=primary)
        ground_truth = script_run_agentic.GroundTruth(index_file, [task])
        corpus = " ".join(callers[:found_count])

        result = ground_truth.score(
            task_id="BND-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
        )

        assert result.scored is True
        assert result.erec == pytest.approx(expected_recall)
        assert result.rrec == pytest.approx(expected_recall)

    def test_delta_equals_erec_minus_rrec(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() delta field equals erec - rrec (information gap).

        Scenario: agent exposes module in tool output but omits it from final
        answer; delta must reflect the gap.
        """
        exposure = "lightning.pytorch.trainer.trainer lightning.pytorch.loops.fit_loop"
        report = "lightning.pytorch.trainer.trainer"  # only one in final answer
        result = ground_truth.score(
            task_id="BA-01",
            output_text=exposure,
            exposure_corpus=exposure,
            report_corpus=report,
        )
        assert result.scored is True
        assert result.delta == pytest.approx(result.erec - result.rrec)

    def test_deff_equals_erec_tp_divided_by_tool_calls(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() deff = erec_tp / max(tool_calls, 1).

        Scenario: agent uses 4 tool calls and finds 1 rdep; deff = 1/4 = 0.25.
        """
        corpus = "lightning.pytorch.trainer.trainer"
        result = ground_truth.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
            tool_calls=4,
        )
        assert result.scored is True
        assert result.deff == pytest.approx(result.erec_tp / 4)

    def test_deff_with_zero_tool_calls_uses_denominator_one(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() uses max(tool_calls, 1) so deff is never a division-by-zero.

        Scenario: tool_calls=0 (e.g. arm that produced no calls);
        deff must equal erec_tp / 1 (not raise ZeroDivisionError).
        """
        corpus = "lightning.pytorch.trainer.trainer"
        result = ground_truth.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
            tool_calls=0,
        )
        assert result.scored is True
        assert result.deff == pytest.approx(float(result.erec_tp))

    def test_test_modules_excluded_from_expected_rdeps(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """GroundTruth excludes modules whose name starts with 'tests.' from expected.

        Scenario: the index has a test module importing primary_module; it must
        not appear in the expected rdeps set (production callers only, per docs).
        """
        data = _minimal_index(
            [
                {
                    "name": "lightning.pytorch.core.thing",
                    "direct_imports": [],
                    "dep_count": 0,
                    "status": "ok",
                },
                {
                    "name": "tests.test_thing",
                    "direct_imports": ["lightning.pytorch.core.thing"],
                    "dep_count": 0,
                    "status": "ok",
                },
            ]
        )
        index_file = tmp_path / "index.json"
        index_file.write_text(json.dumps(data))
        task = _make_task(script_run_agentic, id="X1", primary_module="lightning.pytorch.core.thing")
        gt = script_run_agentic.GroundTruth(index_file, [task])
        assert "tests.test_thing" not in gt.expected.get("X1", set())

    def test_skill_coverage_parsed_from_json_result(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() computes skill_coverage from valid codemap JSON result.

        Scenario: codemap skill returns JSON with 'imported_by' list
        containing one of two expected rdeps; skill_coverage must be 0.5.
        """
        skill_json = json.dumps(
            {
                "imported_by": ["lightning.pytorch.trainer.trainer"],
            }
        )
        result = ground_truth.score(
            task_id="BA-01",
            output_text="",
            exposure_corpus="",
            report_corpus="",
            skill_result_text=skill_json,
        )
        assert result.scored is True
        assert result.skill_coverage == pytest.approx(0.5)
        assert result.skill_returned == 1

    def test_skill_coverage_is_none_when_skill_result_text_absent(
        self, script_run_agentic: Any, ground_truth: Any
    ) -> None:
        """score() leaves skill_coverage=None when no skill result text provided.

        Scenario: plain arm has no skill result; skill_coverage must remain
        None (not 0.0) to distinguish 'not applicable' from 'zero coverage'.
        """
        result = ground_truth.score(
            task_id="BA-01",
            output_text="",
            exposure_corpus="",
            report_corpus="",
            skill_result_text=None,
        )
        assert result.skill_coverage is None
        assert result.skill_returned is None

    def test_skill_coverage_is_none_for_malformed_json(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() does not crash on malformed skill_result_text; yields None.

        Scenario: skill returned an error or prose text instead of JSON;
        skill_coverage must stay None rather than raising an exception.
        """
        result = ground_truth.score(
            task_id="BA-01",
            output_text="",
            exposure_corpus="",
            report_corpus="",
            skill_result_text="not valid json at all",
        )
        assert result.skill_coverage is None

    def test_skill_coverage_is_none_when_imported_by_key_missing(
        self, script_run_agentic: Any, ground_truth: Any
    ) -> None:
        """score() skips skill coverage when JSON lacks 'imported_by' key.

        Scenario: skill returned valid JSON for a non-rdeps query (e.g. deps);
        skill_coverage must stay None per the documented conditional logic.
        """
        skill_json = json.dumps({"some_other_key": []})
        result = ground_truth.score(
            task_id="BA-01",
            output_text="",
            exposure_corpus="",
            report_corpus="",
            skill_result_text=skill_json,
        )
        assert result.skill_coverage is None

    def test_case_insensitive_matching(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """score() matches module names case-insensitively in corpus.

        Scenario: documentation states patterns are case-insensitive;
        upper-case corpus text must still count as a match.
        """
        corpus = "LIGHTNING.PYTORCH.TRAINER.TRAINER"
        result = ground_truth.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
        )
        assert result.scored is True
        assert result.erec_tp >= 1


# ===========================================================================
# GroundTruth — _extract_modules (classmethod, pure)
# ===========================================================================


class TestGroundTruthExtractModules:
    """Tests for the module extractor whose package set is derived from the tasks."""

    @pytest.mark.parametrize(
        "text,expected_subset",
        [
            pytest.param(
                "lightning.pytorch.trainer.trainer",
                {"lightning.pytorch.trainer.trainer"},
                id="dotted",
            ),
            pytest.param(
                "src/lightning/pytorch/trainer/trainer.py",
                {"lightning.pytorch.trainer.trainer"},
                id="src-path",
            ),
            pytest.param(
                "unrelated text with no lightning modules",
                set(),
                id="no-match",
            ),
        ],
    )
    def test_extracts_lightning_module_names(self, ground_truth: Any, text: str, expected_subset: set) -> None:
        """_extract_modules extracts dotted lightning.* names and converts paths.

        Scenario: agent output contains dotted module names or file paths;
        the extractor must return the canonical dotted form in both cases.
        """
        result = ground_truth._extract_modules(text)
        assert expected_subset <= result

    def test_generalizes_to_non_lightning_package(self, tmp_index: Path, script_run_agentic: Any) -> None:
        """_extract_modules derives its package from the task, not a hardcoded 'lightning'.

        Scenario: a repo whose primary module is ``torch.*`` must be extracted, while
        the legacy hardcoded ``lightning`` prefix must NOT leak in as a match.
        """
        task = _make_task(script_run_agentic, id="T-torch", primary_module="torch.nn.modules.conv")
        gt = script_run_agentic.GroundTruth(tmp_index, [task])
        text = "see torch.nn.functional and src/torch/optim/adam.py but lightning.pytorch.trainer is off-repo"
        result = gt._extract_modules(text)
        assert {"torch.nn.functional", "torch.optim.adam"} <= result
        assert not any(m.startswith("lightning") for m in result)


# ===========================================================================
# aggregate
# ===========================================================================


class TestAggregate:
    def _make_run(
        self,
        script_agentic: Any,
        task_id: str,
        arm: str,
        model: str,
        success: bool,
        total_tools: int = 4,
        input_tokens: int = 1000,
        elapsed_s: float = 10.0,
    ) -> Any:
        """Build a minimal BenchmarkRun for aggregation tests."""
        run = script_agentic.BenchmarkRun(
            arm=arm,
            task_id=task_id,
            task_type="fix",
            model=model,
            success=success,
        )
        run.tools.grep = total_tools
        run.input_tokens = input_tokens
        run.elapsed_s = elapsed_s
        return run

    def test_returns_empty_dict_for_empty_results(self, script_run_agentic: Any) -> None:
        """aggregate returns empty nested dicts when results list is empty.

        Scenario: benchmark run with no completed tasks; aggregate must
        return a dict keyed by task_id with no arm data.
        """
        out = script_run_agentic.aggregate([], ["T01"], model_short=None)
        assert out == {"T01": {}}

    def test_single_run_produces_correct_median(self, script_run_agentic: Any) -> None:
        """aggregate computes median metrics from a single successful run.

        Scenario: one run per (task, arm) cell; median equals the single
        value and must be present in the output dict.
        """
        run = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=True, input_tokens=2000)
        out = script_run_agentic.aggregate([run], ["T01"], model_short=None)
        assert "plain" in out["T01"]
        assert out["T01"]["plain"]["input_tokens"] == pytest.approx(2000.0)

    def test_model_filter_excludes_other_models(self, script_run_agentic: Any) -> None:
        """aggregate(model_short=X) excludes runs from other model tiers.

        Scenario: results contain haiku and sonnet runs; filtering to haiku
        must not expose sonnet metrics in the output.
        """
        haiku_run = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=True, input_tokens=100)
        sonnet_run = self._make_run(script_run_agentic, "T01", "plain", "sonnet", success=True, input_tokens=999)
        out = script_run_agentic.aggregate([haiku_run, sonnet_run], ["T01"], model_short="haiku")
        assert out["T01"]["plain"]["input_tokens"] == pytest.approx(100.0)

    def test_failed_runs_excluded_from_median(self, script_run_agentic: Any) -> None:
        """aggregate excludes success=False runs from median computation.

        Scenario: cell contains one successful and one failed run; median
        must be derived from the successful run only.
        """
        good = self._make_run(script_run_agentic, "T01", "codemap", "haiku", success=True, elapsed_s=5.0)
        bad = self._make_run(script_run_agentic, "T01", "codemap", "haiku", success=False, elapsed_s=300.0)
        out = script_run_agentic.aggregate([good, bad], ["T01"], model_short="haiku")
        assert out["T01"]["codemap"]["elapsed_s"] == pytest.approx(5.0)

    def test_success_rate_reflects_pass_fraction(self, script_run_agentic: Any) -> None:
        """aggregate success_rate = successes / total in cell.

        Scenario: 1 success and 1 failure in same cell; success_rate = 0.5.
        """
        good = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=True)
        bad = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=False)
        out = script_run_agentic.aggregate([good, bad], ["T01"], model_short="haiku")
        assert out["T01"]["plain"]["success_rate"] == pytest.approx(0.5)

    def test_all_success_false_returns_empty_arm_dict(self, script_run_agentic: Any) -> None:
        """aggregate returns {} for an arm when all runs in the cell failed.

        Scenario: every run timed out; no valid median can be computed;
        the arm entry must be absent or empty rather than containing NaN.
        """
        bad = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=False)
        out = script_run_agentic.aggregate([bad], ["T01"], model_short="haiku")
        assert out["T01"].get("plain", {}) == {}

    def test_multiple_tasks_segregated_correctly(self, script_run_agentic: Any) -> None:
        """aggregate groups metrics per task_id independently.

        Scenario: results for T01 and T02; each task's arm dict must
        reflect only that task's runs.
        """
        run_t1 = self._make_run(script_run_agentic, "T01", "plain", "haiku", success=True, input_tokens=100)
        run_t2 = self._make_run(script_run_agentic, "T02", "plain", "haiku", success=True, input_tokens=999)
        out = script_run_agentic.aggregate([run_t1, run_t2], ["T01", "T02"], model_short="haiku")
        assert out["T01"]["plain"]["input_tokens"] == pytest.approx(100.0)
        assert out["T02"]["plain"]["input_tokens"] == pytest.approx(999.0)


# ===========================================================================
# check_semble_mcp
# ===========================================================================


class TestCheckSembleMcp:
    def test_raises_runtime_error_when_semble_not_installed(self, script_run_agentic: Any) -> None:
        """check_semble_mcp raises RuntimeError when semble package missing.

        Scenario: benchmark operator forgets to install semble; the function
        must raise RuntimeError with an actionable install message (per
        Raises: docstring).
        """
        with patch.dict(sys.modules, {"semble": None}):
            with pytest.raises((RuntimeError, ImportError)):
                script_run_agentic.check_semble_mcp()

    def test_raises_runtime_error_when_claude_mcp_get_fails(self, script_run_agentic: Any) -> None:
        """check_semble_mcp raises RuntimeError when 'claude mcp get semble' fails.

        Scenario: semble is installed but not registered as an MCP server;
        the subprocess returns non-zero; RuntimeError with register instructions
        must be raised.
        """
        fake_semble = MagicMock()
        with (
            patch.dict(sys.modules, {"semble": fake_semble}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            with pytest.raises(RuntimeError, match="semble MCP server not configured"):
                script_run_agentic.check_semble_mcp()

    def test_passes_silently_when_semble_installed_and_mcp_registered(self, script_run_agentic: Any) -> None:
        """check_semble_mcp returns None (no exception) when both checks pass.

        Scenario: operator has semble installed and registered; function
        must complete without raising.
        """
        fake_semble = MagicMock()
        with (
            patch.dict(sys.modules, {"semble": fake_semble}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="semble", stderr="")
            result = script_run_agentic.check_semble_mcp()
        assert result is None


# ===========================================================================
# ModelRunner — _ARM_ALLOWED / _ARM_DISALLOWED (headless -p pre-approval)
# ===========================================================================


class TestArmToolPermissions:
    """Each arm's primary discriminator must be pre-approved, else it is denied in -p mode.

    Regression guard: the codemap/combined arms' primary tool is the /codemap:query-code Skill.
    When it was missing from --allowedTools every codemap Skill call returned <tool_use_error>
    (permission denied), the run fell back to grep, and the arm scored codemap_skill_errored —
    silently unmeasurable. Both plugin namespaces (codemap, codemap-py) must be allowed since the
    agent may invoke either.
    """

    @staticmethod
    def _allowed(script_run_agentic: Any, arm: str) -> str:
        """Return the --allowedTools value string for *arm* (empty when the arm has none)."""
        flags = script_run_agentic.ModelRunner._ARM_ALLOWED.get(arm, [])
        return flags[1] if len(flags) == 2 else ""

    @pytest.mark.parametrize("arm", ["codemap", "combined"])
    def test_skill_preapproved_for_skill_arms(self, script_run_agentic: Any, arm: str) -> None:
        """codemap + combined arms pre-approve the /codemap:query-code Skill in both namespaces."""
        allowed = self._allowed(script_run_agentic, arm)
        assert "Skill(codemap:query-code)" in allowed
        assert "Skill(codemap-py:query-code)" in allowed

    @pytest.mark.parametrize("arm", ["codemap", "combined"])
    def test_scan_query_still_preapproved(self, script_run_agentic: Any, arm: str) -> None:
        """The scan-query CLI stays pre-approved alongside the Skill for the codemap/combined arms."""
        assert "Bash(scan-query:*)" in self._allowed(script_run_agentic, arm)

    def test_semble_arm_does_not_preapprove_skill(self, script_run_agentic: Any) -> None:
        """semble arm must not pre-approve the Skill — it hard-blocks it as the control discriminator."""
        assert "Skill(" not in self._allowed(script_run_agentic, "semble")
        disallowed = script_run_agentic.ModelRunner._ARM_DISALLOWED["semble"]
        assert any("Skill" in tok for tok in disallowed)


# ModelRunner — config isolation (--setting-sources / --plugin-dir / --mcp-config)
# ===========================================================================


class TestConfigIsolation:
    """The subprocess excludes user config, then re-supplies each arm's tool under test.

    Excluding user-level config (--setting-sources project,local) strips the caveman plugin,
    foundry Re:Anchor, user CLAUDE.md and hooks so the agent's output is not shaped/inflated by the
    operator's setup. It also drops the codemap plugin (needed for the Skill) and semble MCP, which
    _arm_isolation_flags re-supplies per arm.
    """

    def test_base_cmd_excludes_user_config(self, script_run_agentic: Any) -> None:
        """_CMD passes --setting-sources project,local so USER config never loads."""
        cmd = script_run_agentic.ModelRunner._CMD
        assert "--setting-sources" in cmd
        assert cmd[cmd.index("--setting-sources") + 1] == "project,local"

    def test_plain_arm_gets_no_extra_tools(self, script_run_agentic: Any) -> None:
        """The control arm re-supplies nothing — no plugin, no MCP."""
        assert script_run_agentic.ModelRunner._arm_isolation_flags("plain") == []

    @pytest.mark.parametrize("arm", ["codemap", "combined"])
    def test_skill_arms_load_codemap_plugin(self, script_run_agentic: Any, arm: str) -> None:
        """codemap/combined re-supply the codemap plugin via --plugin-dir (Skill availability)."""
        flags = script_run_agentic.ModelRunner._arm_isolation_flags(arm)
        assert "--plugin-dir" in flags

    @pytest.mark.parametrize("arm", ["semble", "combined"])
    def test_semble_arms_load_semble_mcp_strictly(self, script_run_agentic: Any, arm: str) -> None:
        """semble/combined re-supply the semble server via --mcp-config, restricted with --strict."""
        flags = script_run_agentic.ModelRunner._arm_isolation_flags(arm)
        assert "--mcp-config" in flags
        assert "--strict-mcp-config" in flags

    def test_semble_mcp_config_is_valid_stdio_server(self, script_run_agentic: Any) -> None:
        """The reconstructed semble config is a valid stdio-server JSON for --mcp-config."""
        import json

        path = script_run_agentic.ModelRunner._semble_mcp_config_path()
        cfg = json.loads(Path(path).read_text())
        assert cfg["mcpServers"]["semble"]["command"] == "uvx"

    def test_plain_arm_never_loads_semble_or_plugin(self, script_run_agentic: Any) -> None:
        """Control arm must not gain the codemap plugin or semble — isolation keeps it a true baseline."""
        flags = script_run_agentic.ModelRunner._arm_isolation_flags("plain")
        assert "--plugin-dir" not in flags
        assert "--mcp-config" not in flags


# ModelRunner — _system_prompt (pure string builder)
# ===========================================================================


class TestModelRunnerSystemPrompt:
    @pytest.fixture()
    def runner(self, script_run_agentic: Any, tmp_path: Path) -> Any:
        """Minimal ModelRunner for testing prompt assembly."""
        return script_run_agentic.ModelRunner(
            model_short="haiku",
            model_id=script_run_agentic.MODELS["haiku"],
            repo_path=tmp_path,
            timeout=300,
        )

    @pytest.mark.parametrize("task_type", ["fix", "feature", "refactor", "review"])
    def test_plain_arm_prompt_contains_base_skill(self, script_run_agentic: Any, runner: Any, task_type: str) -> None:
        """plain arm system prompt contains the skill-specific base text.

        Scenario: each of the four task types has a distinct preamble in
        _PLAIN_SKILLS; the assembled prompt must include that preamble.
        """
        prompt = runner._system_prompt(task_type, "plain")
        assert "software engineer" in prompt.lower()

    def test_codemap_arm_prompt_contains_codemap_keyword(self, script_run_agentic: Any, runner: Any) -> None:
        """codemap arm system prompt mentions /codemap:query.

        Scenario: user runs the codemap arm; the injected supplement
        described in the module docstring must reference 'codemap:query'.
        """
        prompt = runner._system_prompt("fix", "codemap")
        assert "codemap:query" in prompt

    def test_semble_arm_prompt_contains_mcp_tool_name(self, script_run_agentic: Any, runner: Any) -> None:
        """semble arm system prompt mentions mcp__semble__search.

        Scenario: user runs the semble arm; the supplement must mention
        the MCP tool name so the agent knows to use it.
        """
        prompt = runner._system_prompt("fix", "semble")
        assert "mcp__semble__search" in prompt

    def test_combined_arm_prompt_contains_both_tools(self, script_run_agentic: Any, runner: Any) -> None:
        """combined arm system prompt mentions both codemap and semble.

        Scenario: user runs the combined arm; agent must know about both
        structural tools.
        """
        prompt = runner._system_prompt("fix", "combined")
        assert "codemap:query" in prompt
        assert "mcp__semble__search" in prompt

    def test_unknown_task_type_falls_back_to_fix_prompt(self, script_run_agentic: Any, runner: Any) -> None:
        """_system_prompt falls back to 'fix' base for unknown task types.

        Scenario: tasks file contains an unexpected type value; prompt
        assembly must not raise KeyError (the implementation uses .get
        with 'fix' as default).
        """
        prompt = runner._system_prompt("unknown_type", "plain")
        assert len(prompt) > 0

    def test_semble_prompt_contains_repo_path(self, script_run_agentic: Any, runner: Any, tmp_path: Path) -> None:
        """semble arm prompt includes the actual repo_path string.

        Scenario: agent needs to pass repo= on every semble call; the
        prompt must contain the resolved repo path so the agent can copy it.
        """
        prompt = runner._system_prompt("fix", "semble")
        assert str(tmp_path) in prompt


# ===========================================================================
# ModelRunner._system_prompt — arm symmetry (review C-4)
# ===========================================================================


class TestPromptSymmetry:
    """The measured signal must come from tool availability, not asymmetric steering.

    Every arm must share the same answer format and efficiency instruction, and none may
    carry call caps, verification bans, or step protocols — that prescriptive steering is what
    manufactured the deff/tool-call gap the benchmark claims to observe.
    """

    _ARMS = ("plain", "codemap", "semble", "combined")

    # Phrases that biased tool-call count in the old prompts; none may survive in any arm.
    _FORBIDDEN = (
        "Do NOT grep",
        "do NOT grep",
        "Maximum 3",
        "max 2 codemap",
        "guard hook",
        "DENIES",
        "STEP 1",
        "STEP 2",
        "STEP 3",
        "Convergence rule",
        "Count Grep matches per module",
        "do NOT call any tool",
        "Copy EVERY module from the codemap result",
    )

    @pytest.fixture()
    def runner(self, script_run_agentic: Any, tmp_path: Path) -> Any:
        """Minimal ModelRunner for prompt assembly."""
        return script_run_agentic.ModelRunner(
            model_short="haiku",
            model_id=script_run_agentic.MODELS["haiku"],
            repo_path=tmp_path,
            timeout=300,
        )

    @pytest.mark.parametrize("arm", _ARMS)
    def test_answer_format_block_present_for_every_arm(self, script_run_agentic: Any, runner: Any, arm: str) -> None:
        """The shared 'Reverse Dependencies Found' answer format appears in every arm prompt.

        Scenario: erec/rrec are extracted from this block; it is the measurement target and
        must be identical across arms, so each arm's prompt must contain it.
        """
        prompt = runner._system_prompt("fix", arm)
        assert "## Required answer format" in prompt
        assert "## Reverse Dependencies Found" in prompt

    @pytest.mark.parametrize("arm", _ARMS)
    def test_efficiency_sentence_present_for_every_arm(self, script_run_agentic: Any, runner: Any, arm: str) -> None:
        """The single shared efficiency instruction appears in every arm prompt.

        Scenario: all arms get the same 'as few tool calls as possible' nudge so no arm is
        uniquely steered toward more or fewer calls.
        """
        prompt = runner._system_prompt("fix", arm)
        assert "as few tool calls as possible" in prompt

    @pytest.mark.parametrize("arm", _ARMS)
    def test_answer_format_is_arm_neutral(self, script_run_agentic: Any, runner: Any, arm: str) -> None:
        """The answer format hardcodes no corpus-specific example module paths.

        Scenario: hardcoded 'lightning.*' example lines would prime some arms with real rdep
        names; the shared block must use generic placeholders only.
        """
        prompt = runner._system_prompt("fix", arm)
        answer_block = prompt[prompt.index("## Required answer format") :]
        assert "lightning.pytorch.trainer.trainer" not in answer_block

    @pytest.mark.parametrize("arm", _ARMS)
    def test_no_forbidden_steering_in_any_arm(self, script_run_agentic: Any, runner: Any, arm: str) -> None:
        """No arm prompt contains call caps, verification bans, or step-protocol steering.

        Scenario: the deff gap was a denominator artifact of instructing the codemap arm to
        stop calling tools; none of the prescriptive phrases may remain in any arm.
        """
        prompt = runner._system_prompt("fix", arm)
        present = [p for p in self._FORBIDDEN if p in prompt]
        assert not present, f"arm={arm!r} still contains steering phrases: {present}"

    def test_all_arms_share_identical_answer_format(self, script_run_agentic: Any, runner: Any) -> None:
        """The answer-format block is byte-identical across all four arms.

        Scenario: any per-arm wording in the extraction target would bias erec/rrec; the shared
        constant must appear verbatim in every arm prompt.
        """
        blocks = {arm: runner._system_prompt("fix", arm) for arm in self._ARMS}
        shared = script_run_agentic.ModelRunner._ANSWER_FORMAT
        assert all(shared in prompt for prompt in blocks.values())


# ===========================================================================
# _tool_key_arg (internal utility tested via documented docstring examples)
# ===========================================================================


class TestToolKeyArg:
    """Validates the tool log formatter against its own docstring examples."""

    def test_grep_with_path(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for Grep produces 'pattern in path' format.

        The function docstring shows this example verbatim.
        """
        result = script_run_agentic._tool_key_arg("Grep", {"pattern": "import auth", "path": "src/"})
        assert result == "'import auth' in src/"

    def test_semble_search_returns_query_repr(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for mcp__semble__search returns query= repr.

        The function docstring shows this example verbatim.
        """
        result = script_run_agentic._tool_key_arg(
            "mcp__semble__search",
            {"query": "import checkpoint_connector", "repo": "/tmp/r", "top_k": 20},
        )
        assert result == "query='import checkpoint_connector'"

    def test_semble_find_related_returns_query_repr(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for mcp__semble__find_related returns query= repr.

        The function docstring shows this example verbatim.
        """
        result = script_run_agentic._tool_key_arg(
            "mcp__semble__find_related",
            {"query": "find related", "line": 42},
        )
        assert result == "query='find related'"

    def test_glob_returns_pattern(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for Glob returns the pattern string directly."""
        result = script_run_agentic._tool_key_arg("Glob", {"pattern": "**/*.py"})
        assert result == "**/*.py"

    def test_bash_truncates_to_120_chars(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for Bash truncates command to 120 characters.

        Scenario: very long shell commands must be truncated at 120 chars
        to keep tool logs readable.
        """
        long_cmd = "x" * 200
        result = script_run_agentic._tool_key_arg("Bash", {"command": long_cmd})
        assert len(result) <= 120

    def test_skill_returns_skill_and_args(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for Skill returns 'skill args' combined string."""
        result = script_run_agentic._tool_key_arg(
            "Skill", {"skill": "codemap:query", "args": "rdeps lightning.pytorch.trainer"}
        )
        assert "codemap:query" in result
        assert "rdeps" in result

    def test_unknown_tool_returns_string(self, script_run_agentic: Any) -> None:
        """_tool_key_arg for unknown tool name returns a non-empty string.

        Scenario: a future tool name not listed in the dispatcher;
        the fallback str() path must not raise.
        """
        result = script_run_agentic._tool_key_arg("UnknownTool", {"key": "val"})
        assert isinstance(result, str)


# ===========================================================================
# ModelRunner._on_tool_result (static, pure accumulator)
# ===========================================================================


class TestOnToolResult:
    def _make_run(self, script_agentic: Any) -> Any:
        """Build a minimal BenchmarkRun for _on_tool_result tests."""
        return script_agentic.BenchmarkRun(arm="codemap", task_id="T1", task_type="fix", model="haiku", success=False)

    def test_string_content_accumulates_tokens(self, script_run_agentic: Any) -> None:
        """_on_tool_result tokenises string content and adds to tool_result_tokens.

        Scenario: a grep result arrives as a plain string; token count
        must increase in the BenchmarkRun.
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result("hello world from tool result", run)
        assert run.tool_result_tokens > 0

    def test_list_content_accumulates_tokens(self, script_run_agentic: Any) -> None:
        """_on_tool_result handles list-of-dict content blocks.

        Scenario: tool results often arrive as list of content blocks;
        text must be extracted and tokenised.
        """
        run = self._make_run(script_run_agentic)
        content = [{"type": "text", "text": "result text here"}]
        script_run_agentic.ModelRunner._on_tool_result(content, run)
        assert run.tool_result_tokens > 0

    def test_skips_tool_use_error_content(self, script_run_agentic: Any) -> None:
        """_on_tool_result does not capture content containing <tool_use_error>.

        Scenario: disallowed tool returns an error block; it must not be
        added to the exposure corpus (codemap_results / semble_results).
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result(
            "<tool_use_error>Permission denied</tool_use_error>",
            run,
            is_rdeps=True,
        )
        assert run.codemap_results == []
        assert run.skill_result_text == ""

    def test_skips_launching_skill_placeholder(self, script_run_agentic: Any) -> None:
        """_on_tool_result ignores 'Launching skill:' status placeholders.

        Scenario: skill executor emits a status line before result; it
        must not be captured as an rdep answer.
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result(
            "Launching skill: codemap:query rdeps ...",
            run,
            is_rdeps=True,
        )
        assert run.codemap_results == []

    def test_rdep_result_captured_in_codemap_results(self, script_run_agentic: Any) -> None:
        """_on_tool_result appends is_rdeps=True content to codemap_results.

        Scenario: a valid codemap rdeps result arrives; it must be
        appended to codemap_results for erec corpus construction.
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result(
            '{"imported_by": ["lightning.pytorch.trainer.trainer"]}',
            run,
            is_rdeps=True,
        )
        assert len(run.codemap_results) == 1
        assert "imported_by" in run.codemap_results[0]

    def test_semble_result_captured_in_semble_results(self, script_run_agentic: Any) -> None:
        """_on_tool_result appends is_semble=True content to semble_results.

        Scenario: semble MCP result arrives; it must be stored in
        semble_results for erec corpus construction.
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result(
            "File: src/lightning/pytorch/trainer.py\nLine 10: import x",
            run,
            is_semble=True,
        )
        assert len(run.semble_results) == 1

    def test_non_rdep_codemap_does_not_populate_codemap_results(self, script_run_agentic: Any) -> None:
        """_on_tool_result with is_codemap=True only (not is_rdeps) skips capture.

        Scenario: a codemap deps (not rdeps) call arrives; it must NOT
        be appended to codemap_results per the documented distinction.
        """
        run = self._make_run(script_run_agentic)
        script_run_agentic.ModelRunner._on_tool_result(
            '{"imports": ["something"]}',
            run,
            is_codemap=True,
            is_rdeps=False,
        )
        assert run.codemap_results == []


# ===========================================================================
# MODELS constant
# ===========================================================================


class TestModelsConstant:
    def test_all_documented_tiers_present(self, script_run_agentic: Any) -> None:
        """MODELS contains the three documented model tiers.

        Scenario: user passes --model haiku/sonnet/opus; all three must
        be valid keys in the MODELS dict.
        """
        for tier in ("haiku", "sonnet", "opus"):
            assert tier in script_run_agentic.MODELS, f"tier {tier!r} missing from MODELS"

    def test_model_ids_are_non_empty_strings(self, script_run_agentic: Any) -> None:
        """Every MODELS value is a non-empty string (full model ID).

        Scenario: the model ID is passed directly to the claude CLI
        via --model; an empty string would silently use the wrong model.
        """
        for tier, model_id in script_run_agentic.MODELS.items():
            assert isinstance(model_id, str) and len(model_id) > 0, f"MODELS[{tier!r}] is empty or not a string"


# ===========================================================================
# Integration-level: GroundTruth loaded from fixture index
# ===========================================================================


class TestGroundTruthIntegration:
    def test_expected_rdeps_exclude_tests_module(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """GroundTruth.expected for BA-01 excludes the tests.test_timer module.

        Scenario: the tmp_index fixture contains tests.test_timer as an
        importer; it must be excluded from expected (production callers only).
        """
        rdeps = ground_truth.expected.get("BA-01", set())
        assert "tests.test_timer" not in rdeps

    def test_expected_rdeps_contains_production_importers(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """GroundTruth.expected for BA-01 includes both production importers.

        Scenario: two non-test modules import lightning.pytorch.callbacks.timer
        in the fixture; both must appear in expected["BA-01"].
        """
        rdeps = ground_truth.expected.get("BA-01", set())
        assert "lightning.pytorch.trainer.trainer" in rdeps
        assert "lightning.pytorch.loops.fit_loop" in rdeps

    def test_top10_expected_populated_for_scored_task(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """GroundTruth.top10_expected is populated for tasks with rdeps.

        Scenario: BA-01 has 2 rdeps; top10_expected must contain a frozenset
        for BA-01 (since |rdeps| ≤ 10, all are included).
        """
        top10 = ground_truth.top10_expected.get("BA-01")
        assert top10 is not None
        assert "lightning.pytorch.trainer.trainer" in top10

    def test_all_modules_populated_from_index(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """GroundTruth.all_modules contains all ok-status modules from index.

        Scenario: four modules in the fixture index, all status='ok';
        all_modules must contain all four names for leaf-name computation.
        """
        assert "lightning.pytorch.callbacks.timer" in ground_truth.all_modules
        assert "lightning.pytorch.trainer.trainer" in ground_truth.all_modules

    def test_task_without_primary_module_skipped_silently(self, script_run_agentic: Any, tmp_index: Path) -> None:
        """GroundTruth silently skips tasks with no primary_module.

        Scenario: a task definition missing primary_module must not raise;
        the task ID must not appear in expected.
        """
        task_no_pm = script_run_agentic.Task(id="NOPRIMARY", type="fix", prompt="x")
        gt = script_run_agentic.GroundTruth(tmp_index, [task_no_pm])
        assert "NOPRIMARY" not in gt.expected


# ===========================================================================
# AST import scan helpers (review C-5)
# ===========================================================================


class TestDeriveModuleName:
    def test_regular_module_uses_package_chain(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """_derive_module_name joins the __init__.py package chain for a regular module.

        Scenario: src-layout file pkg/sub/mod.py with __init__.py at each level resolves to
        the dotted name 'pkg.sub.mod'.
        """
        (tmp_path / "pkg" / "sub").mkdir(parents=True)
        (tmp_path / "pkg" / "__init__.py").write_text("")
        (tmp_path / "pkg" / "sub" / "__init__.py").write_text("")
        mod = tmp_path / "pkg" / "sub" / "mod.py"
        mod.write_text("")
        assert script_run_agentic._derive_module_name(mod, tmp_path) == "pkg.sub.mod"

    def test_init_file_resolves_to_package_name(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """_derive_module_name maps an __init__.py to its package's dotted name.

        Scenario: pkg/sub/__init__.py resolves to 'pkg.sub', not 'pkg.sub.__init__'.
        """
        (tmp_path / "pkg" / "sub").mkdir(parents=True)
        (tmp_path / "pkg" / "__init__.py").write_text("")
        init = tmp_path / "pkg" / "sub" / "__init__.py"
        init.write_text("")
        assert script_run_agentic._derive_module_name(init, tmp_path) == "pkg.sub"


class TestResolveRelativeBase:
    @pytest.mark.parametrize(
        "package,level,module,expected",
        [
            pytest.param("a.b", 1, "c", "a.b.c", id="level1-with-module"),
            pytest.param("a.b", 1, None, "a.b", id="level1-bare"),
            pytest.param("a.b.c", 2, "u", "a.b.u", id="level2-parent"),
            pytest.param("a", 3, "x", None, id="level-above-root"),
        ],
    )
    def test_relative_resolution(
        self, script_run_agentic: Any, package: str, level: int, module: Any, expected: Any
    ) -> None:
        """_resolve_relative_base resolves dotted relative imports against the package.

        Scenario: each documented relative form (current package, parent, over-ascend) must
        map to the correct absolute base or None when it walks above the root.
        """
        assert script_run_agentic._resolve_relative_base(package, level, module) == expected


class TestScanRepoImporters:
    """AST scan builds a tool-independent {module: importers} map across import forms."""

    @pytest.fixture()
    def scanned_repo(self, tmp_path: Path) -> Path:
        """Create a src-layout package exercising every import form plus a test file."""
        pkg = tmp_path / "src" / "app"
        (pkg / "sub").mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "sub" / "__init__.py").write_text("")
        (pkg / "target.py").write_text("X = 1\n")
        (pkg / "caller_submodule.py").write_text("from app import target\n")  # index-blind form
        (pkg / "caller_base.py").write_text("from app.target import X\n")
        (pkg / "caller_relative.py").write_text("from . import target\n")
        (pkg / "caller_plain.py").write_text("import app.target\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("from app.target import X\n")
        return tmp_path

    def test_scan_captures_all_import_forms(self, script_run_agentic: Any, scanned_repo: Path) -> None:
        """_scan_repo_importers finds importers via plain, from-base, from-submodule, and relative forms.

        Scenario: four production callers import app.target through different syntaxes; all four
        must appear as importers, and the test-tree caller must be excluded.
        """
        importers = script_run_agentic._scan_repo_importers(scanned_repo)
        assert importers.get("app.target") == {
            "app.caller_submodule",
            "app.caller_base",
            "app.caller_relative",
            "app.caller_plain",
        }

    def test_test_tree_files_excluded(self, script_run_agentic: Any, scanned_repo: Path) -> None:
        """_scan_repo_importers omits importers under a top-level tests/ directory.

        Scenario: tests/test_app.py imports app.target but must not count as a production rdep.
        """
        importers = script_run_agentic._scan_repo_importers(scanned_repo)
        assert not any(name.startswith("tests") or "test_app" in name for name in importers.get("app.target", set()))


class TestGroundTruthAstOracle:
    """GroundTruth uses the AST scan (not the index) as the rdep oracle and logs divergences."""

    @pytest.fixture()
    def ast_gt(self, tmp_path: Path, script_run_agentic: Any) -> Any:
        """Build a package where the index under-records rdeps vs the AST scan."""
        pkg = tmp_path / "src" / "app"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "target.py").write_text("X = 1\n")
        (pkg / "caller_submodule.py").write_text("from app import target\n")  # index records 'app'
        (pkg / "caller_base.py").write_text("from app.target import X\n")  # index records 'app.target'
        index = _minimal_index(
            [
                {"name": "app.target", "direct_imports": [], "dep_count": 0, "status": "ok"},
                {"name": "app.caller_submodule", "direct_imports": ["app"], "dep_count": 1, "status": "ok"},
                {"name": "app.caller_base", "direct_imports": ["app.target"], "dep_count": 1, "status": "ok"},
                {"name": "app", "direct_imports": [], "dep_count": 0, "status": "ok"},
            ]
        )
        index_file = tmp_path / "idx.json"
        index_file.write_text(json.dumps(index))
        task = script_run_agentic.Task(
            id="BA-01", type="blast_radius_analysis", prompt="p", primary_module="app.target"
        )
        return script_run_agentic.GroundTruth(index_file, [task], repo_path=tmp_path)

    def test_expected_uses_ast_superset(self, script_run_agentic: Any, ast_gt: Any) -> None:
        """GroundTruth.expected includes the submodule-import caller the index misses.

        Scenario: 'from app import target' makes caller_submodule a real rdep; the AST oracle
        must credit it even though the index only recorded a dependency on 'app'.
        """
        assert ast_gt.expected["BA-01"] == {"app.caller_submodule", "app.caller_base"}

    def test_index_expected_retained_as_diagnostic(self, script_run_agentic: Any, ast_gt: Any) -> None:
        """The index-derived list is kept separately and is a strict subset here.

        Scenario: index_expected must still be available for diagnostics and must omit the
        submodule-form caller that only the AST scan catches.
        """
        assert ast_gt.index_expected["BA-01"] == {"app.caller_base"}

    def test_divergence_recorded_with_missing_in_index(self, script_run_agentic: Any, ast_gt: Any) -> None:
        """A divergence entry flags real importers absent from the index.

        Scenario: caller_submodule is in the AST set but not the index set, so it must appear
        under missing_in_index — the harness's C-5 blind-spot signal.
        """
        div = ast_gt.divergences["BA-01"]
        assert div["missing_in_index"] == ["app.caller_submodule"]
        assert div["ast"] == 2 and div["index"] == 1

    def test_ast_only_rdep_is_matchable_in_corpus(self, script_run_agentic: Any, ast_gt: Any) -> None:
        """An AST-only expected rdep can still be credited when found in agent output.

        Scenario: match patterns must cover AST-only expected modules so an arm that reports
        the index-missed caller scores recall for it rather than being silently penalized.
        """
        corpus = "app.caller_submodule app.caller_base"
        score = ast_gt.score(
            task_id="BA-01",
            output_text=corpus,
            exposure_corpus=corpus,
            report_corpus=corpus,
        )
        assert score.erec == pytest.approx(1.0)


# ===========================================================================
# Fix-family prompt symmetry (review N3)
# ===========================================================================


class TestFixFamilyPromptSymmetry:
    """Fix / read_crop prompts must share the efficiency nudge and carry no anti-grep steering."""

    _ARMS = ("plain", "codemap", "semble", "combined")
    _FIX_TYPES = ("fix_single", "fix_multicaller", "read_crop")

    @pytest.fixture()
    def runner(self, script_run_agentic: Any, tmp_path: Path) -> Any:
        """Minimal ModelRunner for prompt assembly."""
        return script_run_agentic.ModelRunner(
            model_short="haiku",
            model_id=script_run_agentic.MODELS["haiku"],
            repo_path=tmp_path,
            timeout=300,
        )

    @pytest.mark.parametrize("task_type", _FIX_TYPES)
    @pytest.mark.parametrize("arm", _ARMS)
    def test_efficiency_sentence_present_in_fix_family(
        self, script_run_agentic: Any, runner: Any, task_type: str, arm: str
    ) -> None:
        """The shared efficiency sentence appears in every fix-family arm prompt.

        Scenario: fix / read_crop prompts previously returned before the shared efficiency
        instruction, so only rdep tasks were symmetric; N3 appends it to every arm here too.
        """
        prompt = runner._system_prompt(task_type, arm)
        assert "as few tool calls as possible" in prompt

    def test_fixmulti_codemap_has_no_anti_grep_steering(self, script_run_agentic: Any, runner: Any) -> None:
        """The fix_multicaller codemap supplement carries only tool availability + syntax.

        Scenario: the old supplement told the codemap arm 'do NOT grep for more' and framed
        codemap as a 'decisive advantage' — that steering was the measured signal (N3).
        """
        prompt = runner._system_prompt("fix_multicaller", "codemap")
        for phrase in ("do NOT grep", "decisive advantage", "plain grep misses"):
            assert phrase not in prompt

    @pytest.mark.parametrize("task_type", _FIX_TYPES)
    @pytest.mark.parametrize("arm", _ARMS)
    def test_rdep_answer_format_absent_from_fix_family(
        self, script_run_agentic: Any, runner: Any, task_type: str, arm: str
    ) -> None:
        """Fix / read_crop prompts do not append the rdep-only 'Reverse Dependencies Found' block.

        Scenario: fix tasks are scored by diff / keyword recall, so the reverse-dependency answer
        format is irrelevant and must not be injected.
        """
        prompt = runner._system_prompt(task_type, arm)
        assert "## Reverse Dependencies Found" not in prompt


# ===========================================================================
# Arm tool policy — semble Bash symmetry (review H-5)
# ===========================================================================


class TestArmToolPolicy:
    """Semble must keep a shell fallback like every other arm; only its primary tool differs."""

    def test_semble_arm_no_longer_blocks_bash(self, script_run_agentic: Any) -> None:
        """The semble disallowed list no longer contains Bash (H-5 handicap removed)."""
        disallowed = script_run_agentic.ModelRunner._ARM_DISALLOWED["semble"]
        joined = ",".join(disallowed)
        assert "Bash" not in joined

    def test_semble_arm_still_blocks_skill(self, script_run_agentic: Any) -> None:
        """The semble arm still blocks the Skill tool so codemap is not its discriminator."""
        disallowed = script_run_agentic.ModelRunner._ARM_DISALLOWED["semble"]
        assert "Skill" in ",".join(disallowed)

    def test_semble_supplement_advertises_bash_fallback(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """The semble supplement mirrors codemap's Grep/Bash error fallback clause."""
        runner = script_run_agentic.ModelRunner("haiku", script_run_agentic.MODELS["haiku"], tmp_path, timeout=300)
        prompt = runner._system_prompt("fix", "semble")
        assert "Grep/Bash fallback" in prompt


# ===========================================================================
# Subprocess env — SCAN_NO_AUTOBUILD opt-out (review N2 / H-3)
# ===========================================================================


class TestSubprocessEnv:
    """codemap / combined arms opt out of in-task index builds; other arms are untouched."""

    @pytest.mark.parametrize("arm", ["codemap", "combined"])
    def test_scan_no_autobuild_set_for_structural_arms(self, script_run_agentic: Any, arm: str) -> None:
        """SCAN_NO_AUTOBUILD=1 is injected for arms that invoke /codemap:query-code (N2)."""
        env = script_run_agentic.ModelRunner._subprocess_env(arm)
        assert env.get("SCAN_NO_AUTOBUILD") == "1"

    @pytest.mark.parametrize("arm", ["plain", "semble", ""])
    def test_scan_no_autobuild_absent_for_other_arms(self, script_run_agentic: Any, arm: str) -> None:
        """Non-structural arms do not receive the build opt-out (they never call the skill)."""
        env = script_run_agentic.ModelRunner._subprocess_env(arm)
        assert "SCAN_NO_AUTOBUILD" not in env


# ===========================================================================
# _seed_index_cache — index present in fix-task sandbox (review H-3)
# ===========================================================================


class TestSeedIndexCache:
    """The prebuilt index cache dirs are copied into a sandbox for non-plain arms."""

    def test_copies_codemap_and_scan_cache(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """_seed_index_cache seeds .cache/codemap and .cache/scan from the original repo.

        Scenario: fix tasks run in a copy that excludes .cache; without the prebuilt index the
        codemap arm would build it inside the measured window (H-3), so it is seeded in.
        """
        repo = tmp_path / "myrepo"
        (repo / ".cache" / "codemap").mkdir(parents=True)
        (repo / ".cache" / "scan").mkdir(parents=True)
        (repo / ".cache" / "codemap" / "myrepo.json").write_text("{}")
        (repo / ".cache" / "scan" / "myrepo.json").write_text("{}")
        sandbox = tmp_path / "sandbox" / "myrepo"
        sandbox.mkdir(parents=True)
        runner = script_run_agentic.ModelRunner("haiku", script_run_agentic.MODELS["haiku"], repo, timeout=300)
        runner._seed_index_cache(sandbox)
        assert (sandbox / ".cache" / "codemap" / "myrepo.json").is_file()
        assert (sandbox / ".cache" / "scan" / "myrepo.json").is_file()

    def test_missing_source_cache_is_skipped_silently(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """_seed_index_cache does not raise when the source cache dirs are absent."""
        repo = tmp_path / "myrepo"
        repo.mkdir()
        sandbox = tmp_path / "sandbox" / "myrepo"
        sandbox.mkdir(parents=True)
        runner = script_run_agentic.ModelRunner("haiku", script_run_agentic.MODELS["haiku"], repo, timeout=300)
        runner._seed_index_cache(sandbox)
        assert not (sandbox / ".cache").exists()


# ===========================================================================
# Semble chunk-hit rate lens (review C-5)
# ===========================================================================


class TestSembleChunkHitRate:
    """chunk_hit_rate credits expected rdeps whose module/file appears in any semble chunk."""

    def test_chunk_hit_rate_partial_when_one_of_two_in_chunks(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """One of two expected rdeps appears in the semble chunks → chunk_hit_rate = 0.5.

        Scenario: BA-01 has two expected rdeps; a semble result mentioning only one file must
        yield 0.5 without requiring the exhaustive dotted rdep list.
        """
        chunks = "File: src/lightning/pytorch/trainer/trainer.py\nLine 10: import timer"
        result = ground_truth.score(
            task_id="BA-01",
            output_text="",
            exposure_corpus="",
            report_corpus="",
            semble_result_text=chunks,
        )
        assert result.chunk_hit_rate == pytest.approx(0.5)

    def test_chunk_hit_rate_none_when_no_semble_corpus(self, script_run_agentic: Any, ground_truth: Any) -> None:
        """chunk_hit_rate stays None for arms that carry no semble corpus (plain / codemap)."""
        result = ground_truth.score(
            task_id="BA-01",
            output_text="x",
            exposure_corpus="x",
            report_corpus="x",
            semble_result_text=None,
        )
        assert result.chunk_hit_rate is None


# ===========================================================================
# Report rendering — success rate, quality, savings n, failures (review H-4)
# ===========================================================================


class TestReportRendering:
    """The report surfaces success rate, quality medians, savings denominators, and failures."""

    def _run(
        self,
        script: Any,
        task_id: str,
        arm: str,
        success: bool,
        erec: float = 0.0,
        chunk: float | None = None,
    ) -> Any:
        """Build a BenchmarkRun with minimal metrics and a scored QualityScore."""
        run = script.BenchmarkRun(arm=arm, task_id=task_id, task_type="fix", model="haiku", success=success)
        run.tools.grep = 4
        run.input_tokens = 1000
        run.elapsed_s = 10.0
        run.quality = script.QualityScore(scored=True, erec=erec, rrec=erec, chunk_hit_rate=chunk)
        return run

    @pytest.fixture()
    def report(self, script_run_agentic: Any) -> Any:
        """Report with a plain+codemap success pair and one codemap failure."""
        tasks = [script_run_agentic.Task(id="BA-01", type="blast_radius_analysis", prompt="p")]
        results = [
            self._run(script_run_agentic, "BA-01", "plain", success=True, erec=0.5),
            self._run(script_run_agentic, "BA-01", "codemap", success=True, erec=0.75),
            self._run(script_run_agentic, "BA-01", "codemap", success=False),
        ]
        return script_run_agentic.Report(results, tasks, {"date": "2026-07-03"})

    def test_render_includes_success_rate_table(self, script_run_agentic: Any, report: Any) -> None:
        """The rendered report contains a success-rate table (H-4)."""
        assert "Success rate (successful / total runs)" in report.render()

    def test_render_includes_quality_tables(self, script_run_agentic: Any, report: Any) -> None:
        """The rendered report contains erec / rrec / chunk-hit quality tables (H-4)."""
        md = report.render()
        assert "Exposure recall (erec)" in md
        assert "Chunk hit rate (semble lens)" in md

    def test_render_includes_failed_runs_section(self, script_run_agentic: Any, report: Any) -> None:
        """Failed runs are listed explicitly, not silently dropped (H-4)."""
        assert "### Failed runs" in report.render()

    def test_savings_summary_has_pair_count_n(self, script_run_agentic: Any, report: Any) -> None:
        """Every savings row carries an 'n' pair-count denominator (H-4)."""
        agg = script_run_agentic.aggregate(report.results, report.task_ids, model_short="haiku")
        rows = report._savings_summary(agg)
        assert rows and all("n" in row for row in rows)

    def test_success_table_counts_failures(self, script_run_agentic: Any, report: Any) -> None:
        """The success table reports 1/2 for the codemap cell (one success, one failure)."""
        counts = report._cell_counts("haiku")
        assert counts["BA-01"]["codemap"] == [2, 1]


class TestReportFixFamilySuppression:
    """Fix-family suites emit no biased efficiency savings row (review N3)."""

    def _fix_run(self, script: Any, arm: str) -> Any:
        """Build a successful fix_multicaller BenchmarkRun."""
        run = script.BenchmarkRun(arm=arm, task_id="FM-01", task_type="fix_multicaller", model="haiku", success=True)
        run.tools.grep = 4
        run.input_tokens = 1000
        run.elapsed_s = 10.0
        run.quality = script.QualityScore(scored=True, erec=1.0, rrec=1.0)
        return run

    def test_efficiency_savings_suppressed_for_fix_suite(self, script_run_agentic: Any) -> None:
        """A pure fix_multicaller suite yields no efficiency savings rows (N3).

        Scenario: fix tasks differ in edit workload, so token / tool-call savings would be biased;
        _savings_summary must exclude them, leaving no rows for an all-fix suite.
        """
        tasks = [script_run_agentic.Task(id="FM-01", type="fix_multicaller", prompt="p")]
        results = [
            self._fix_run(script_run_agentic, "plain"),
            self._fix_run(script_run_agentic, "codemap"),
        ]
        report = script_run_agentic.Report(results, tasks, {"date": "2026-07-03"})
        agg = script_run_agentic.aggregate(results, ["FM-01"], model_short="haiku")
        assert report._savings_summary(agg) == []

    def test_arm_cells_savings_not_applicable_shows_na(self, script_run_agentic: Any) -> None:
        """_arm_cells renders 'n/a' savings when savings_applicable is False."""
        tasks = [script_run_agentic.Task(id="FM-01", type="fix_multicaller", prompt="p")]
        report = script_run_agentic.Report([], tasks, {"date": "2026-07-03"})
        cells = report._arm_cells("codemap", 10.0, 5.0, script_run_agentic.Report._fmt_s, savings_applicable=False)
        assert cells["Codemap savings"] == "n/a"


# ===========================================================================
# Atomic snapshot persistence (review M-1)
# ===========================================================================


class TestAtomicSnapshot:
    """_save_snapshot writes via a temp file + os.replace so an interrupt cannot truncate it."""

    @pytest.fixture()
    def benchmark(self, script_run_agentic: Any, tmp_index: Path, tmp_path: Path) -> Any:
        """Minimal Benchmark whose output path lives in a writable temp dir."""
        task = script_run_agentic.Task(id="BA-01", type="blast_radius_analysis", prompt="p")
        out = tmp_path / "results.json"
        log = tmp_path / "tool-calls.jsonl"
        return script_run_agentic.Benchmark(
            tasks=[task],
            arms=["codemap"],
            models=[("haiku", script_run_agentic.MODELS["haiku"])],
            repo_path=tmp_path,
            index_path=tmp_index,
            output_path=out,
            log_path=log,
        )

    def test_snapshot_writes_valid_json_and_leaves_no_tmp(self, script_run_agentic: Any, benchmark: Any) -> None:
        """The rolling snapshot is valid JSON and no .tmp residue remains after a successful write.

        Scenario: a run has accumulated; _save_snapshot persists it and the file must round-trip
        through json.load with no half-written temp file left in the directory.
        """
        benchmark.results.append(
            script_run_agentic.BenchmarkRun(
                arm="codemap", task_id="BA-01", task_type="fix", model="haiku", success=True
            )
        )
        benchmark._save_snapshot({"date": "2026-07-03"})
        loaded = json.loads(benchmark.output_path.read_text())
        assert loaded["results"][0]["task_id"] == "BA-01"
        assert not list(benchmark.output_path.parent.glob("*.tmp"))

    def test_snapshot_uses_os_replace_from_a_temp_source(self, script_run_agentic: Any, benchmark: Any) -> None:
        """The final file is produced by os.replace from a temp file, not written in place (M-1).

        Scenario: an interrupt mid-write must never truncate the real file; the only way that holds
        is if the payload lands via an atomic rename from a distinct temp path.
        """
        seen: dict[str, Any] = {}
        real_replace = script_run_agentic.os.replace

        def _spy_replace(src: Any, dst: Any) -> Any:
            seen["src"], seen["dst"] = str(src), str(dst)
            return real_replace(src, dst)

        with patch.object(script_run_agentic.os, "replace", _spy_replace):
            benchmark._save_snapshot({"date": "2026-07-03"})
        assert seen["src"].endswith(".tmp")
        assert seen["src"] != str(benchmark.output_path)
        assert seen["dst"] == str(benchmark.output_path)

    def test_snapshot_failure_cleans_temp_and_preserves_nothing_partial(
        self, script_run_agentic: Any, benchmark: Any
    ) -> None:
        """A serialisation failure removes the temp file and never overwrites the target (M-1).

        Scenario: json.dump raises mid-write; the pre-existing (or absent) results file must stay
        untouched and no orphan .tmp file may be left behind.
        """
        with patch.object(script_run_agentic.json, "dump", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                benchmark._save_snapshot({"date": "2026-07-03"})
        assert not benchmark.output_path.exists()
        assert not list(benchmark.output_path.parent.glob("*.tmp"))


# ===========================================================================
# Degenerate-loop classification ordering (review M-2)
# ===========================================================================


class TestDegenerateLoopClassification:
    """A grep-heavy zero-skill BA codemap run is degenerate_grep_loop, not a plain no-call."""

    @pytest.fixture()
    def benchmark(self, script_run_agentic: Any, tmp_index: Path, tmp_path: Path) -> Any:
        """Benchmark whose only task is a blast-radius (non-fix) codemap task."""
        task = script_run_agentic.Task(
            id="BA-01",
            type="blast_radius_analysis",
            prompt="p",
            primary_module="lightning.pytorch.callbacks.timer",
        )
        return (
            script_run_agentic.Benchmark(
                tasks=[task],
                arms=["codemap"],
                models=[("haiku", script_run_agentic.MODELS["haiku"])],
                repo_path=tmp_path,
                index_path=tmp_index,
                output_path=tmp_path / "out.json",
                log_path=tmp_path / "log.jsonl",
            ),
            task,
        )

    def _classify(self, script: Any, bench: Any, task: Any, crafted: Any) -> Any:
        """Drive _run_single with ModelRunner.run patched to return a crafted result."""
        with patch.object(script.ModelRunner, "run", return_value=crafted):
            return bench._run_single(
                task,
                "haiku",
                script.MODELS["haiku"],
                "codemap",
                run_n=1,
                total_runs=1,
                print_fn=lambda *a, **k: None,
                metadata={"date": "2026-07-03"},
            )

    def test_grep_heavy_zero_skill_ba_run_is_degenerate(self, script_run_agentic: Any, benchmark: Any) -> None:
        """BA codemap run with skill==0 and ≥70% grep-like calls is labelled degenerate_grep_loop.

        Scenario: the no-skill-call guard used to claim this run first ("codemap skill never
        called"), leaving the grep-ratio classification unreachable for BA tasks (M-2).
        """
        bench, task = benchmark
        crafted = script_run_agentic.BenchmarkRun(
            arm="codemap", task_id="BA-01", task_type="blast_radius_analysis", model="haiku", success=True
        )
        crafted.tools.grep = 8  # total 8, all grep-like, skill 0 → ratio 1.0
        result = self._classify(script_run_agentic, bench, task, crafted)
        assert result.error_type == "degenerate_grep_loop"
        assert result.success is False

    def test_zero_skill_but_not_grep_heavy_falls_through_to_no_call(
        self, script_run_agentic: Any, benchmark: Any
    ) -> None:
        """A zero-skill BA run below the grep threshold still fails as 'codemap skill never called'.

        Scenario: the reordering must not swallow the no-call guard — a skill==0 run that is NOT
        grep-dominated keeps the original no-call label.
        """
        bench, task = benchmark
        crafted = script_run_agentic.BenchmarkRun(
            arm="codemap", task_id="BA-01", task_type="blast_radius_analysis", model="haiku", success=True
        )
        crafted.tools.grep = 1
        crafted.tools.bash = 9  # total 10, grep-like 1 → ratio 0.1 < 0.70
        result = self._classify(script_run_agentic, bench, task, crafted)
        assert result.error_type != "degenerate_grep_loop"
        assert result.error == "codemap skill never called"
        assert result.success is False


# ===========================================================================
# top10 centrality axis — in-degree not out-degree (review M-3)
# ===========================================================================


class TestTop10InDegree:
    """top10_expected ranks central rdeps by in-degree (reverse-dep count), not dep_count."""

    @pytest.fixture()
    def gt(self, script_run_agentic: Any, tmp_path: Path) -> Any:
        """Index with 11 rdeps: r1..r10 imported once each, r11 imported by nobody but high dep_count."""
        modules: list[dict] = [{"name": "app.target", "direct_imports": [], "dep_count": 0, "status": "ok"}]
        for i in range(1, 11):
            modules.append({"name": f"app.r{i}", "direct_imports": ["app.target"], "status": "ok"})
            # one importer for app.r{i} → in-degree 1
            modules.append({"name": f"imp.r{i}", "direct_imports": [f"app.r{i}"], "status": "ok"})
        # r11 is a rdep with a huge out-degree (dep_count) but ZERO in-degree — nobody imports it.
        modules.append(
            {"name": "app.r11", "direct_imports": ["app.target", "x.a", "x.b"], "dep_count": 999, "status": "ok"}
        )
        index_file = tmp_path / "idx.json"
        index_file.write_text(json.dumps(_minimal_index(modules)))
        task = _make_task(script_run_agentic, id="X", primary_module="app.target")
        return script_run_agentic.GroundTruth(index_file, [task])

    def test_high_in_degree_kept_and_high_out_degree_dropped(self, gt: Any) -> None:
        """The zero-in-degree / high-dep_count rdep is dropped; an in-degree≥1 rdep is kept.

        Scenario: 11 rdeps trim to 10. Ranking by in-degree drops app.r11 (imported by nobody);
        ranking by the old dep_count axis would have kept it and dropped a real central module.
        """
        top10 = gt.top10_expected["X"]
        assert len(top10) == 10
        assert "app.r1" in top10
        assert "app.r11" not in top10


# ===========================================================================
# Keyword scoring — whitespace tolerance + opt-in test signal (review M-4)
# ===========================================================================


class TestFixKeywordNormalization:
    """score_fix / score_read_crop tolerate operator whitespace and carry the test_passed signal."""

    def test_score_fix_matches_operator_keyword_despite_whitespace(self, script_run_agentic: Any) -> None:
        """A '< 1' keyword matches a '<1' diff line after whitespace normalisation (M-4a).

        Scenario: the agent writes 'if patience<1:' while the ground-truth keyword is 'patience < 1';
        the recall scorer must credit it rather than penalising the spacing variant.
        """
        diff = "--- a/x.py\n+++ b/x.py\n+    if patience<1:\n+        raise ValueError\n"
        score = script_run_agentic.score_fix(diff, ["patience < 1"], [])
        assert score.erec == pytest.approx(1.0)

    def test_score_read_crop_matches_operator_keyword_despite_whitespace(self, script_run_agentic: Any) -> None:
        """score_read_crop credits a '< 1' keyword when the answer writes '<1' (M-4a)."""
        score = script_run_agentic.score_read_crop("guard returns <1 on misconfig", ["< 1"])
        assert score.erec == pytest.approx(1.0)

    def test_score_read_crop_preserves_word_boundaries(self, script_run_agentic: Any) -> None:
        """Normalisation keeps word-word spaces so distinct identifiers are not merged (M-4a).

        Scenario: an answer that never mentions 'raise Error' must not falsely match it just because
        whitespace was collapsed elsewhere.
        """
        score = script_run_agentic.score_read_crop("this text has no such token here", ["raise Error"])
        assert score.erec == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "test_passed,expected",
        [pytest.param(True, True, id="passed"), pytest.param(False, False, id="failed")],
    )
    def test_score_fix_records_test_passed_when_supplied(
        self, script_run_agentic: Any, test_passed: bool, expected: bool
    ) -> None:
        """score_fix stores the supplied targeted-test outcome alongside erec (M-4b)."""
        diff = "+++ b/x.py\n+    fixed = True\n"
        score = script_run_agentic.score_fix(diff, ["fixed"], ["x.py"], test_passed=test_passed)
        assert score.test_passed is expected
        assert score.erec == pytest.approx(1.0)  # erec column is unchanged by the test signal

    def test_score_fix_test_passed_defaults_to_none(self, script_run_agentic: Any) -> None:
        """A task with no declared test leaves test_passed=None (M-4b)."""
        score = script_run_agentic.score_fix("+++ b/x.py\n+ fixed\n", ["fixed"], ["x.py"])
        assert score.test_passed is None


class TestRunTargetedTest:
    """_run_targeted_test runs pytest on the post-edit sandbox and reports pass/fail/None."""

    def _runner(self, script: Any, repo: Path) -> Any:
        """Build a ModelRunner rooted at the given repo path."""
        return script.ModelRunner("haiku", script.MODELS["haiku"], repo, timeout=300)

    def test_passing_target_returns_true(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """A passing pytest node yields True."""
        (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
        runner = self._runner(script_run_agentic, tmp_path)
        assert runner._run_targeted_test(tmp_path, "test_ok.py") is True

    def test_failing_target_returns_false(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """A failing pytest node yields False (not None — the run launched fine)."""
        (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n")
        runner = self._runner(script_run_agentic, tmp_path)
        assert runner._run_targeted_test(tmp_path, "test_bad.py") is False


# ===========================================================================
# BA query arms run in an isolated copy, not the real repo (review M-5)
# ===========================================================================


class TestQueryArmIsolation:
    """Non-reset (query) codemap runs execute in a throwaway copy so they cannot mutate the repo."""

    def test_ba_codemap_run_uses_a_copy_and_cannot_mutate_repo(self, script_run_agentic: Any, tmp_path: Path) -> None:
        """A BA codemap run's cwd is a copy of the repo, and edits there never touch self.repo_path.

        Scenario: query arms used to run in-place with Edit/Bash unblocked (M-5); the cwd handed to
        the subprocess must be a distinct copy, and a write into it must not appear in the real repo.
        """
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / "mod.py").write_text("x = 1\n")
        runner = script_run_agentic.ModelRunner("haiku", script_run_agentic.MODELS["haiku"], repo, timeout=300)
        task = script_run_agentic.Task(id="BA-01", type="blast_radius_analysis", prompt="p", requires_reset=False)
        seen: dict[str, Any] = {}

        def _fake_stream(
            self: Any, cmd: Any, result: Any, update_fn: Any = None, cwd: Any = None, arm: Any = None
        ) -> None:
            seen["cwd"] = cwd
            (cwd / "MUTATED.txt").write_text("agent wrote this")  # simulate a stray edit in the sandbox
            result.input_tokens = 10
            result.output_tokens = 10

        with patch.object(script_run_agentic.ModelRunner, "_stream_events", _fake_stream):
            runner.run(task, "codemap")

        assert seen["cwd"] != repo
        assert seen["cwd"].name == repo.name
        assert not (repo / "MUTATED.txt").exists()  # the stray edit stayed in the throwaway copy
