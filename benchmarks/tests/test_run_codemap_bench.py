"""Tests for benchmarks/run-codemap-bench.py.

Public API surface covered:
  - BenchQuality dataclass: field defaults and types
  - BenchRun dataclass: field defaults and types
  - _extract_int(): regex extraction helper
  - _int_close(): tolerance comparison helper
  - _count_tol_detail(): scoring-detail dict builder
  - _parse_scan_query_subcommand(): Bash-command parser
  - _normalize_external_task(): external task schema normalizer
  - _load_tasks_file(): JSON task loader (error paths and normalization)
  - _evaluate_symbol(): symbol_extraction evaluator
  - _evaluate_fn(): fn_call_graph count evaluator
  - _evaluate_rv(): review_assistance evaluator (count and symbol-recall paths)
  - _evaluate_oss(): code_quality evaluator (coupled / xrefs_broken / undocumented / uncovered)
  - _evaluate_debug(): debug_from_trace evaluator
  - _evaluate_feature(): feature_scaffolding evaluator
  - _evaluate_real_issue(): real_issue evaluator
  - _evaluate_develop_br(): develop_blast_radius recall evaluator
  - _extract_diff(): unified-diff extractor
  - _safe_ratio(): safe division helper
  - _workflow_type_of(): workflow key accessor
  - _effective_recall(): recall accessor with fallback logic

Tests do NOT invoke the claude CLI or write files outside /tmp.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _make_run(script_bench: Any, **overrides: Any) -> Any:
    """Build a minimal BenchRun for testing helper functions."""
    defaults = dict(
        arm="plain",
        task_id="SE-01",
        task_type="symbol_extraction",
        model="haiku",
        success=True,
    )
    defaults.update(overrides)
    return script_bench.BenchRun(**defaults)


def _se_task(start_line: int = 100, qname: str = "Trainer.fit") -> dict:
    """Return a minimal symbol_extraction task dict."""
    return {
        "id": "SE-01",
        "type": "symbol_extraction",
        "ground_truth": {
            "start_line": start_line,
            "qualified_name": qname,
            "end_line": start_line + 10,
            "module": "lightning.pytorch.trainer",
        },
    }


# ===========================================================================
# BenchQuality dataclass
# ===========================================================================


class TestBenchQuality:
    """Field defaults and type constraints for BenchQuality."""

    def test_defaults_scored_false(self, script_run_bench: Any) -> None:
        """Newly constructed BenchQuality must default to unscored state."""
        q = script_run_bench.BenchQuality()
        assert q.scored is False

    def test_defaults_correct_false(self, script_run_bench: Any) -> None:
        """Newly constructed BenchQuality must default correct=False."""
        q = script_run_bench.BenchQuality()
        assert q.correct is False

    def test_defaults_optional_fields_none(self, script_run_bench: Any) -> None:
        """Optional numeric fields default to None when no score was computed."""
        q = script_run_bench.BenchQuality()
        assert q.recall is None
        assert q.metric_expected is None
        assert q.metric_got is None
        assert q.caller_count_gt is None
        assert q.evaluator_used is None
        assert q.evaluator_version is None
        assert q.extracted_metric is None

    def test_defaults_extraction_failed_false(self, script_run_bench: Any) -> None:
        """extraction_failed must default to False on an empty quality object."""
        q = script_run_bench.BenchQuality()
        assert q.extraction_failed is False

    def test_defaults_scoring_detail_empty_dict(self, script_run_bench: Any) -> None:
        """scoring_detail must be an empty dict (not shared mutable default)."""
        q1 = script_run_bench.BenchQuality()
        q2 = script_run_bench.BenchQuality()
        assert q1.scoring_detail == {}
        # mutable default isolation — distinct objects
        q1.scoring_detail["x"] = 1
        assert q2.scoring_detail == {}

    def test_explicit_fields_round_trip(self, script_run_bench: Any) -> None:
        """Explicitly set fields are stored and returned verbatim."""
        q = script_run_bench.BenchQuality(
            scored=True,
            correct=True,
            metric_expected=10,
            metric_got=9,
            recall=0.9,
            evaluator_used="_evaluate_fn",
        )
        assert q.scored is True
        assert q.correct is True
        assert q.metric_expected == 10
        assert q.metric_got == 9
        assert q.recall == pytest.approx(0.9)
        assert q.evaluator_used == "_evaluate_fn"


# ===========================================================================
# BenchRun dataclass
# ===========================================================================


class TestBenchRun:
    """Field defaults and type constraints for BenchRun."""

    def test_required_fields_stored(self, script_run_bench: Any) -> None:
        """Required constructor arguments are stored in matching fields."""
        r = _make_run(script_run_bench)
        assert r.arm == "plain"
        assert r.task_id == "SE-01"
        assert r.task_type == "symbol_extraction"
        assert r.model == "haiku"
        assert r.success is True

    def test_token_defaults_zero(self, script_run_bench: Any) -> None:
        """Token counters default to zero on a fresh run."""
        r = _make_run(script_run_bench)
        assert r.input_tokens == 0
        assert r.output_tokens == 0

    def test_tool_call_counters_default_zero(self, script_run_bench: Any) -> None:
        """All tool-call counters default to zero."""
        r = _make_run(script_run_bench)
        assert r.skill_calls == 0
        assert r.grep_calls == 0
        assert r.bash_calls == 0
        assert r.read_calls == 0
        assert r.scan_query_calls == 0

    def test_tool_log_independent_per_instance(self, script_run_bench: Any) -> None:
        """tool_log must be an independent list per BenchRun, not shared state."""
        r1 = _make_run(script_run_bench)
        r2 = _make_run(script_run_bench)
        r1.tool_log.append("Bash: foo")
        assert r2.tool_log == []

    def test_skill_counts_independent_per_instance(self, script_run_bench: Any) -> None:
        """skill_counts dict must be independent per instance (no shared mutable default)."""
        r1 = _make_run(script_run_bench)
        r2 = _make_run(script_run_bench)
        r1.skill_counts["fix"] = 1
        assert "fix" not in r2.skill_counts

    def test_quality_defaults_to_unscored(self, script_run_bench: Any) -> None:
        """quality field must default to an unscored BenchQuality object."""
        r = _make_run(script_run_bench)
        assert isinstance(r.quality, script_run_bench.BenchQuality)
        assert r.quality.scored is False

    def test_patch_pass_defaults_none(self, script_run_bench: Any) -> None:
        """patch_pass must default to None (no signal) rather than False."""
        r = _make_run(script_run_bench)
        assert r.patch_pass is None

    def test_incomplete_defaults_false(self, script_run_bench: Any) -> None:
        """incomplete flag must default to False."""
        r = _make_run(script_run_bench)
        assert r.incomplete is False

    def test_workflow_type_defaults_empty_string(self, script_run_bench: Any) -> None:
        """workflow_type defaults to empty string when not provided."""
        r = _make_run(script_run_bench)
        assert r.workflow_type == ""

    def test_elapsed_s_defaults_zero(self, script_run_bench: Any) -> None:
        """elapsed_s defaults to 0.0."""
        r = _make_run(script_run_bench)
        assert r.elapsed_s == pytest.approx(0.0)


# ===========================================================================
# _extract_int
# ===========================================================================


class TestExtractInt:
    """Regex-based integer extraction from free-form model output."""

    @pytest.mark.parametrize(
        "text,patterns,expected",
        [
            ("found 42 callers in total", [r"(\d+) caller"], 42),
            ("there are 7 unique callers", [r"(\d+) unique"], 7),
            ("UNIQUE CALLERS: 15", [r"(\d+) caller", r"unique callers:\s*(\d+)"], 15),
            # Bold markers are replaced by spaces; use whitespace-tolerant pattern.
            ("**42** callers", [r"(\d+)\s+caller"], 42),
            ("total: 100", [r"total[:\s]+(\d+)"], 100),
        ],
    )
    def test_extracts_integer_from_matching_pattern(
        self, script_run_bench: Any, text: str, patterns: list[str], expected: int
    ) -> None:
        """_extract_int returns the first integer matching any supplied pattern."""
        assert script_run_bench._extract_int(text, patterns) == expected

    @pytest.mark.parametrize(
        "text,patterns",
        [
            ("no numbers here", [r"(\d+) caller"]),
            ("", [r"(\d+) caller"]),
            ("123", []),  # no patterns → nothing matches
        ],
    )
    def test_returns_none_when_no_match(self, script_run_bench: Any, text: str, patterns: list[str]) -> None:
        """_extract_int returns None when no pattern matches the text."""
        assert script_run_bench._extract_int(text, patterns) is None

    def test_first_pattern_wins_over_later_match(self, script_run_bench: Any) -> None:
        """When multiple patterns match, the one listed first wins."""
        text = "12 unique callers, total: 99"
        result = script_run_bench._extract_int(text, [r"(\d+) unique", r"total[:\s]+(\d+)"])
        assert result == 12

    def test_bold_markers_stripped_before_matching(self, script_run_bench: Any) -> None:
        """Bold markers replaced by spaces; digit survives and can be matched."""
        # After stripping, "**7** unique" becomes " 7  unique" — use whitespace-tolerant pattern.
        text = "**7** unique callers"
        assert script_run_bench._extract_int(text, [r"(\d+)\s+unique"]) == 7


# ===========================================================================
# _int_close
# ===========================================================================


class TestIntClose:
    """Tolerance-based integer comparison helper."""

    @pytest.mark.parametrize(
        "got,expected,tolerance,result",
        [
            (42, 40, 0.10, True),  # within 10%
            (44, 40, 0.10, True),  # exactly at boundary: 4/40 = 0.10
            (45, 40, 0.10, False),  # just over boundary: 5/40 = 0.125
            (40, 40, 0.10, True),  # exact match
            (0, 40, 0.10, False),  # far below
            (42, 30, 0.10, False),  # 12/30 = 0.40
            (1, 1, 0.0, True),  # zero tolerance exact
            (2, 1, 0.0, False),  # zero tolerance mismatch
        ],
    )
    def test_within_tolerance(
        self, script_run_bench: Any, got: int, expected: int, tolerance: float, result: bool
    ) -> None:
        """_int_close returns True iff abs deviation is within fractional tolerance."""
        assert script_run_bench._int_close(got, expected, tolerance=tolerance) is result

    def test_none_always_returns_false(self, script_run_bench: Any) -> None:
        """_int_close returns False when got is None regardless of expected."""
        assert script_run_bench._int_close(None, 40) is False
        assert script_run_bench._int_close(None, 0) is False

    def test_denominator_floor_at_1(self, script_run_bench: Any) -> None:
        """When expected=0, denominator is clamped to 1 to avoid ZeroDivisionError."""
        # abs(1 - 0) / max(0, 1) = 1.0 → outside 10% → False
        assert script_run_bench._int_close(1, 0, tolerance=0.10) is False
        # got == expected == 0 → diff = 0 → True
        assert script_run_bench._int_close(0, 0, tolerance=0.10) is True


# ===========================================================================
# _count_tol_detail
# ===========================================================================


class TestCountTolDetail:
    """Scoring-detail dict builder for count-tolerance evaluators."""

    def test_required_fields_present(self, script_run_bench: Any) -> None:
        """Result contains metric_expected, metric_got, threshold, and method."""
        d = script_run_bench._count_tol_detail(10, 9)
        assert d["metric_expected"] == 10
        assert d["metric_got"] == 9
        assert d["threshold"] == pytest.approx(0.10)
        assert d["method"] == "count_tolerance"

    def test_extra_kwargs_merged(self, script_run_bench: Any) -> None:
        """Extra keyword arguments are merged into the result dict."""
        d = script_run_bench._count_tol_detail(10, 9, check="coupled")
        assert d["check"] == "coupled"

    def test_extra_kwargs_do_not_overwrite_fixed_keys(self, script_run_bench: Any) -> None:
        """Core keys always reflect the positional arguments, not extras."""
        d = script_run_bench._count_tol_detail(5, 3)
        assert d["metric_expected"] == 5
        assert d["metric_got"] == 3

    def test_none_values_accepted(self, script_run_bench: Any) -> None:
        """None values for got are stored without error (extraction failed case)."""
        d = script_run_bench._count_tol_detail(10, None)
        assert d["metric_got"] is None


# ===========================================================================
# _safe_ratio
# ===========================================================================


class TestSafeRatio:
    """Division helper that returns NaN for undefined denominators."""

    @pytest.mark.parametrize(
        "num,den,expected",
        [
            (10, 4, 2.5),
            (0, 5, 0.0),
            (1, 1, 1.0),
            (100, 100, 1.0),
        ],
    )
    def test_normal_division(self, script_run_bench: Any, num: float, den: float, expected: float) -> None:
        """_safe_ratio performs ordinary division when denominator is non-zero."""
        assert script_run_bench._safe_ratio(num, den) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "num,den",
        [
            (10, 0),
            (0, 0),
            (10, None),
            (None, 4),
            (None, None),
        ],
    )
    def test_returns_nan_for_undefined(self, script_run_bench: Any, num: Any, den: Any) -> None:
        """_safe_ratio returns NaN when denominator is zero or either operand is None."""
        assert math.isnan(script_run_bench._safe_ratio(num, den))


# ===========================================================================
# _parse_scan_query_subcommand
# ===========================================================================


class TestParseScanQuerySubcommand:
    """Extract scan-query subcommand from Bash command strings."""

    @pytest.mark.parametrize(
        "command,expected",
        [
            ("scan-query --index /x.json fn-rdeps a.b --exclude-tests", "fn-rdeps"),
            ("scan-query symbol Trainer", "symbol"),
            ("scan-query find-symbol Trainer", "find-symbol"),
            ("scan-query symbols lightning.pytorch.trainer", "symbols"),
            ("scan-query rdeps lightning.pytorch.loops", "rdeps"),
            ("scan-query undocumented lightning.pytorch.trainer", "undocumented"),
            ("scan-query uncovered lightning.pytorch.trainer --top 10", "uncovered"),
            ("scan-query coupled --top 5", "coupled"),
            ("scan-query xrefs lightning.pytorch.trainer", "xrefs"),
            ("/path/to/bin/scan-query symbol Trainer", "symbol"),  # full path form
        ],
    )
    def test_known_subcommands_extracted(self, script_run_bench: Any, command: str, expected: str) -> None:
        """_parse_scan_query_subcommand returns the recognised subcommand token."""
        assert script_run_bench._parse_scan_query_subcommand(command) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r foo .",
            "ls -la",
            "python3 -m pytest",
            "",
        ],
    )
    def test_non_scan_query_command_returns_none(self, script_run_bench: Any, command: str) -> None:
        """_parse_scan_query_subcommand returns None for commands without scan-query."""
        assert script_run_bench._parse_scan_query_subcommand(command) is None

    def test_unknown_subcommand_returns_none(self, script_run_bench: Any) -> None:
        """Unrecognised subcommands (not in the known set) return None."""
        assert script_run_bench._parse_scan_query_subcommand("scan-query unknown-subcmd foo") is None

    def test_index_flag_value_skipped(self, script_run_bench: Any) -> None:
        """--index <path> flag-value pair is skipped before finding the subcommand."""
        cmd = "scan-query --index /some/path/index.json fn-rdeps lightning.pytorch.trainer"
        assert script_run_bench._parse_scan_query_subcommand(cmd) == "fn-rdeps"

    def test_equals_form_flag_skipped(self, script_run_bench: Any) -> None:
        """--index=/path form (= present) is treated as a single token and skipped."""
        cmd = "scan-query --index=/some/path.json symbol Trainer"
        assert script_run_bench._parse_scan_query_subcommand(cmd) == "symbol"


# ===========================================================================
# _normalize_external_task
# ===========================================================================


class TestNormalizeExternalTask:
    """Schema normalizer for tasks loaded via --tasks-file."""

    def test_queries_renamed_to_expected_queries(self, script_run_bench: Any) -> None:
        """'queries' key is renamed to 'expected_queries' and original key removed."""
        task = {
            "id": "B-01",
            "prompt": "p",
            "skill": "fix",
            "queries": [{"cmd": "rdeps", "args": ["m"]}],
        }
        result = script_run_bench._normalize_external_task(task)
        assert "expected_queries" in result
        assert "queries" not in result
        assert result["expected_queries"] == [{"cmd": "rdeps", "args": ["m"]}]

    def test_type_defaults_to_develop_skill_when_missing(self, script_run_bench: Any) -> None:
        """Tasks without a 'type' field get type=develop_skill."""
        task = {"id": "B-01", "prompt": "p", "skill": "fix"}
        result = script_run_bench._normalize_external_task(task)
        assert result["type"] == script_run_bench._EXTERNAL_TASK_TYPE

    def test_scoreable_false_when_no_ground_truth(self, script_run_bench: Any) -> None:
        """Tasks without ground_truth are forced scoreable=False."""
        task = {"id": "B-01", "prompt": "p", "skill": "fix"}
        result = script_run_bench._normalize_external_task(task)
        assert result["scoreable"] is False

    def test_scoreable_true_preserved_when_ground_truth_present(self, script_run_bench: Any) -> None:
        """Tasks with ground_truth and explicit scoreable=True keep that flag."""
        task = {
            "id": "DBG-01",
            "type": "debug_from_trace",
            "scoreable": True,
            "prompt": "p",
            "ground_truth": {"function": "f", "file": "a.py", "start_line": 1},
        }
        result = script_run_bench._normalize_external_task(task)
        assert result["scoreable"] is True

    def test_scoreable_defaults_true_when_ground_truth_present_but_no_flag(self, script_run_bench: Any) -> None:
        """ground_truth present without explicit scoreable → defaults to True."""
        task = {
            "id": "DBG-02",
            "type": "debug_from_trace",
            "prompt": "p",
            "ground_truth": {"function": "g", "file": "b.py", "start_line": 5},
        }
        result = script_run_bench._normalize_external_task(task)
        assert result["scoreable"] is True

    def test_existing_type_preserved(self, script_run_bench: Any) -> None:
        """Tasks with an existing 'type' field keep that type unchanged."""
        task = {
            "id": "DBG-01",
            "type": "debug_from_trace",
            "prompt": "p",
            "ground_truth": {"function": "f", "file": "a.py", "start_line": 1},
        }
        result = script_run_bench._normalize_external_task(task)
        assert result["type"] == "debug_from_trace"

    def test_original_task_dict_not_mutated(self, script_run_bench: Any) -> None:
        """_normalize_external_task must not mutate the input dict."""
        task = {"id": "B-01", "prompt": "p", "queries": [{"cmd": "rdeps"}]}
        original = dict(task)
        script_run_bench._normalize_external_task(task)
        assert task == original


# ===========================================================================
# _load_tasks_file
# ===========================================================================


class TestLoadTasksFile:
    """JSON task file loader — parsing, normalization, and error paths."""

    def _write_json(self, tmp_path: Path, data: Any) -> Path:
        """Write data as JSON to a temp file and return its path."""
        p = tmp_path / "tasks.json"
        p.write_text(json.dumps(data))
        return p

    def test_bare_list_loaded_and_normalized(self, script_run_bench: Any, tmp_path: Path) -> None:
        """A bare JSON list of tasks is loaded and each task normalized."""
        data = [{"id": "X-01", "prompt": "p", "skill": "fix", "queries": [{"cmd": "rdeps"}]}]
        p = self._write_json(tmp_path, data)
        result = script_run_bench._load_tasks_file(p)
        assert len(result) == 1
        assert result[0]["id"] == "X-01"
        assert "expected_queries" in result[0]

    def test_dict_with_tasks_key_loaded(self, script_run_bench: Any, tmp_path: Path) -> None:
        """A {'repo': ..., 'tasks': [...]} shaped file extracts the 'tasks' list."""
        data = {
            "repo": {"name": "myrepo"},
            "tasks": [{"id": "Y-01", "prompt": "p", "skill": "fix"}],
        }
        p = self._write_json(tmp_path, data)
        result = script_run_bench._load_tasks_file(p)
        assert len(result) == 1
        assert result[0]["id"] == "Y-01"

    def test_missing_file_raises_file_not_found(self, script_run_bench: Any, tmp_path: Path) -> None:
        """FileNotFoundError raised when the file does not exist."""
        with pytest.raises(FileNotFoundError, match="not found"):
            script_run_bench._load_tasks_file(tmp_path / "nonexistent.json")

    def test_malformed_json_raises_value_error(self, script_run_bench: Any, tmp_path: Path) -> None:
        """ValueError raised when the file contains invalid JSON."""
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        with pytest.raises(ValueError, match="not valid JSON"):
            script_run_bench._load_tasks_file(p)

    def test_unexpected_shape_raises_value_error(self, script_run_bench: Any, tmp_path: Path) -> None:
        """ValueError raised when JSON is neither a list nor a dict."""
        p = tmp_path / "bad.json"
        p.write_text("42")
        with pytest.raises(ValueError, match="must be a JSON list or object"):
            script_run_bench._load_tasks_file(p)

    def test_empty_list_returns_empty(self, script_run_bench: Any, tmp_path: Path) -> None:
        """An empty task list loads without error and returns an empty list."""
        p = self._write_json(tmp_path, [])
        result = script_run_bench._load_tasks_file(p)
        assert result == []

    def test_multiple_tasks_all_normalized(self, script_run_bench: Any, tmp_path: Path) -> None:
        """All tasks in the list are normalized, not just the first."""
        data = [
            {"id": "A-01", "prompt": "p", "queries": [{"cmd": "rdeps"}]},
            {"id": "A-02", "prompt": "p", "queries": [{"cmd": "symbol"}]},
        ]
        p = self._write_json(tmp_path, data)
        result = script_run_bench._load_tasks_file(p)
        assert all("expected_queries" in t for t in result)
        assert all("queries" not in t for t in result)


# ===========================================================================
# _evaluate_symbol
# ===========================================================================


class TestEvaluateSymbol:
    """symbol_extraction evaluator: start_line within ±5 lines of ground truth."""

    @pytest.mark.parametrize(
        "output_text,start_line,expected_correct",
        [
            ("file_path: x.py  start_line: 100  end_line: 110", 100, True),  # exact
            ("start_line: 104", 100, True),  # within +4 lines
            ("start_line: 96", 100, True),  # within -4 lines
            ("start_line: 105", 100, True),  # exactly ±5 boundary
            ("start_line: 95", 100, True),  # exactly -5 boundary
            ("start_line: 106", 100, False),  # just outside +5
            ("start_line: 94", 100, False),  # just outside -5
            ("Lines 100-110 of the file", 100, True),  # range pattern fallback
            ("starts at line 100 in the file", 100, True),  # "starts at line N"
        ],
    )
    def test_correct_when_start_line_within_tolerance(
        self, script_run_bench: Any, output_text: str, start_line: int, expected_correct: bool
    ) -> None:
        """_evaluate_symbol marks correct when extracted start_line is within ±5 of GT."""
        task = _se_task(start_line=start_line)
        result = script_run_bench._evaluate_symbol(task, output_text)
        assert result.scored is True
        assert result.correct is expected_correct

    def test_extraction_failed_when_no_line_in_output(self, script_run_bench: Any) -> None:
        """extraction_failed=True and correct=False when no start_line can be parsed."""
        task = _se_task(start_line=100)
        result = script_run_bench._evaluate_symbol(task, "The function does something useful.")
        assert result.scored is True
        assert result.extraction_failed is True
        assert result.correct is False

    def test_bold_markers_stripped_before_parsing(self, script_run_bench: Any) -> None:
        """Markdown bold markers around start_line are ignored by the parser."""
        task = _se_task(start_line=200)
        result = script_run_bench._evaluate_symbol(task, "**start_line**: 200")
        assert result.correct is True

    def test_metric_expected_set_to_ground_truth_start(self, script_run_bench: Any) -> None:
        """metric_expected is always the ground-truth start_line value."""
        task = _se_task(start_line=42)
        result = script_run_bench._evaluate_symbol(task, "start_line: 42")
        assert result.metric_expected == 42

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used field identifies the function that ran."""
        task = _se_task()
        result = script_run_bench._evaluate_symbol(task, "start_line: 100")
        assert result.evaluator_used == "_evaluate_symbol"

    def test_scoring_detail_contains_threshold(self, script_run_bench: Any) -> None:
        """scoring_detail carries threshold and method for diagnosis."""
        task = _se_task(start_line=50)
        result = script_run_bench._evaluate_symbol(task, "start_line: 50")
        assert result.scoring_detail["threshold"] == 5
        assert result.scoring_detail["method"] == "line_tolerance"


# ===========================================================================
# ===========================================================================
# _evaluate_rv (review_assistance)
# ===========================================================================


class TestEvaluateRv:
    """review_assistance evaluator: count-tolerance or symbol-recall path."""

    def _rv_task_count(self, count: int) -> dict:
        """Return a review_assistance task graded by count extraction."""
        return {
            "id": "RV-01",
            "type": "review_assistance",
            "sub_questions": [{"ground_truth": {"count": count}}],
        }

    def _rv_task_symbols(self, symbols: list[str]) -> dict:
        """Return a review_assistance task graded by symbol recall."""
        return {
            "id": "RV-05",
            "type": "review_assistance",
            "sub_questions": [{"ground_truth": {"symbols": symbols}}],
        }

    def test_no_sub_questions_returns_unscored(self, script_run_bench: Any) -> None:
        """A task with no sub_questions cannot be scored."""
        task = {"id": "RV-01", "type": "review_assistance", "sub_questions": []}
        result = script_run_bench._evaluate_rv(task, "something")
        assert result.scored is False

    def test_count_path_correct_within_tolerance(self, script_run_bench: Any) -> None:
        """Count path: correct when extracted count is within 10% of expected."""
        task = self._rv_task_count(20)
        result = script_run_bench._evaluate_rv(task, "found 20 undocumented symbols")
        assert result.scored is True
        assert result.correct is True

    def test_count_path_incorrect_outside_tolerance(self, script_run_bench: Any) -> None:
        """Count path: incorrect when extracted count is outside 10%."""
        task = self._rv_task_count(20)
        result = script_run_bench._evaluate_rv(task, "found 30 undocumented symbols")
        assert result.correct is False

    def test_symbol_recall_path_correct_at_threshold(self, script_run_bench: Any) -> None:
        """Symbol-recall path: correct when ≥70% of expected symbols appear in output."""
        syms = [f"lightning.pytorch.mod::Cls.method{i}" for i in range(10)]
        task = self._rv_task_symbols(syms)
        # Include 7 of 10 symbols by their short name (last component after split)
        text = " ".join(s.split(".")[-1] for s in syms[:7])
        result = script_run_bench._evaluate_rv(task, text)
        assert result.scored is True
        assert result.correct is True
        assert result.recall is not None
        assert result.recall >= 0.70

    def test_symbol_recall_path_incorrect_below_threshold(self, script_run_bench: Any) -> None:
        """Symbol-recall path: incorrect when fewer than 70% of symbols found."""
        syms = [f"lightning.pytorch.mod::Cls.method{i}" for i in range(10)]
        task = self._rv_task_symbols(syms)
        # Only 5 of 10 symbols present → recall = 0.50 < 0.70 → incorrect
        text = " ".join(f"method{i}" for i in range(5))
        result = script_run_bench._evaluate_rv(task, text)
        assert result.correct is False
        assert result.recall is not None and result.recall < 0.70

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_rv."""
        task = self._rv_task_count(5)
        result = script_run_bench._evaluate_rv(task, "found 5 undocumented")
        assert result.evaluator_used == "_evaluate_rv"


# ===========================================================================
# _evaluate_oss (code_quality)
# ===========================================================================


class TestEvaluateOss:
    """code_quality evaluator: coupled / xrefs_broken / undocumented / uncovered."""

    def _oss_task(self, check: str, **gt_fields: Any) -> dict:
        """Return a code_quality task dict for the given check type."""
        return {
            "id": "CQ-01",
            "type": "code_quality",
            "ground_truth": {"check": check, **gt_fields},
        }

    def test_coupled_correct_when_dep_count_within_tolerance(self, script_run_bench: Any) -> None:
        """coupled check: correct when dep_count is within 10% of GT."""
        task = self._oss_task("coupled", top_dep_count=100)
        result = script_run_bench._evaluate_oss(task, "dep_count: 100")
        assert result.scored is True
        assert result.correct is True

    def test_coupled_incorrect_outside_tolerance(self, script_run_bench: Any) -> None:
        """coupled check: incorrect when extracted count is outside 10%."""
        task = self._oss_task("coupled", top_dep_count=100)
        result = script_run_bench._evaluate_oss(task, "120 dependencies found")
        assert result.correct is False

    def test_xrefs_broken_exact_match_correct(self, script_run_bench: Any) -> None:
        """xrefs_broken check: correct when exact broken count found in output."""
        task = self._oss_task("xrefs_broken", broken_count=3, broken_targets=[])
        result = script_run_bench._evaluate_oss(task, "3 broken xrefs detected")
        assert result.scored is True
        assert result.correct is True

    def test_xrefs_broken_wrong_count_incorrect(self, script_run_bench: Any) -> None:
        """xrefs_broken check: incorrect when count does not exactly match GT."""
        task = self._oss_task("xrefs_broken", broken_count=3, broken_targets=[])
        result = script_run_bench._evaluate_oss(task, "4 broken xrefs")
        assert result.correct is False

    def test_xrefs_broken_uses_target_names_when_available(self, script_run_bench: Any) -> None:
        """xrefs_broken check: count found symbols from broken_targets list."""
        broken_targets = [{"target": "mod::foo"}, {"target": "mod::bar"}]
        task = self._oss_task("xrefs_broken", broken_count=2, broken_targets=broken_targets)
        # Both short names present in output → got=2 == expected=2 → correct
        result = script_run_bench._evaluate_oss(task, "References to foo and bar are broken.")
        assert result.correct is True

    def test_undocumented_correct_within_tolerance(self, script_run_bench: Any) -> None:
        """combined_health / undocumented: correct within 10%."""
        task = self._oss_task("undocumented", undocumented_count=10)
        result = script_run_bench._evaluate_oss(task, "10 undocumented symbols found")
        assert result.scored is True
        assert result.correct is True

    def test_undocumented_combined_health_variant(self, script_run_bench: Any) -> None:
        """combined_health check uses the same undocumented_count field."""
        task = self._oss_task("combined_health", undocumented_count=5)
        result = script_run_bench._evaluate_oss(task, "5 undocumented symbols")
        assert result.scored is True
        assert result.correct is True

    def test_uncovered_correct_within_tolerance(self, script_run_bench: Any) -> None:
        """uncovered check: correct when extracted count is within 10%."""
        task = self._oss_task("uncovered", uncovered_count=20)
        result = script_run_bench._evaluate_oss(task, "20 uncovered symbols")
        assert result.scored is True
        assert result.correct is True

    def test_unknown_check_type_returns_unscored(self, script_run_bench: Any) -> None:
        """An unrecognised check value results in scored=False."""
        task = self._oss_task("unknown_check", some_count=5)
        result = script_run_bench._evaluate_oss(task, "5 things found")
        assert result.scored is False

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_oss."""
        task = self._oss_task("coupled", top_dep_count=10)
        result = script_run_bench._evaluate_oss(task, "dep_count: 10")
        assert result.evaluator_used == "_evaluate_oss"


# ===========================================================================
# _evaluate_debug
# ===========================================================================


class TestEvaluateDebug:
    """debug_from_trace evaluator: function name and file basename both present."""

    def _debug_task(self, fn: str = "my_function", filepath: str = "src/mod/utils.py") -> dict:
        """Return a minimal debug_from_trace task dict."""
        return {
            "id": "DG-01",
            "type": "debug_from_trace",
            "ground_truth": {"function": fn, "file": filepath, "start_line": 10},
        }

    def test_correct_when_both_fn_and_file_present(self, script_run_bench: Any) -> None:
        """correct=True when both function name and file basename appear in output."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "The bug is in my_function inside utils.py")
        assert result.scored is True
        assert result.correct is True

    def test_incorrect_when_only_fn_present(self, script_run_bench: Any) -> None:
        """correct=False when only the function name appears but not the file."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "The bug is in my_function somewhere")
        assert result.correct is False

    def test_incorrect_when_only_file_present(self, script_run_bench: Any) -> None:
        """correct=False when only the file basename appears but not the function."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "Check inside utils.py for the problem")
        assert result.correct is False

    def test_incorrect_when_neither_present(self, script_run_bench: Any) -> None:
        """correct=False and extraction_failed=True when neither token appears."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "Completely unrelated output text")
        assert result.correct is False
        assert result.extraction_failed is True

    def test_recall_1_when_both_found(self, script_run_bench: Any) -> None:
        """recall=1.0 when both expected tokens are present in output."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "my_function in utils.py is the culprit")
        assert result.recall == pytest.approx(1.0)

    def test_recall_0_5_when_one_of_two_found(self, script_run_bench: Any) -> None:
        """recall=0.5 when exactly one of two expected tokens is found."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "only my_function appears here")
        assert result.recall == pytest.approx(0.5)

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_debug."""
        task = self._debug_task()
        result = script_run_bench._evaluate_debug(task, "my_function utils")
        assert result.evaluator_used == "_evaluate_debug"

    def test_match_is_case_insensitive(self, script_run_bench: Any) -> None:
        """Word-boundary matching is case-insensitive."""
        task = self._debug_task(fn="MyFunction")
        result = script_run_bench._evaluate_debug(task, "MYFUNCTION in utils.py")
        assert result.correct is True


# ===========================================================================
# _evaluate_feature
# ===========================================================================


class TestEvaluateFeature:
    """feature_scaffolding evaluator: entry_point method and primary_file basename."""

    def _feature_task(
        self,
        entry_point: str = "Trainer.validate",
        primary_file: str = "src/lightning/trainer/trainer.py",
    ) -> dict:
        """Return a minimal feature_scaffolding task dict."""
        return {
            "id": "FT-01",
            "type": "feature_scaffolding",
            "ground_truth": {
                "entry_point": entry_point,
                "primary_file": primary_file,
            },
        }

    def test_correct_when_method_and_file_found(self, script_run_bench: Any) -> None:
        """correct=True when both the method and file basename appear in output."""
        task = self._feature_task()
        result = script_run_bench._evaluate_feature(task, "Add validate method to trainer.py")
        assert result.scored is True
        assert result.correct is True

    def test_only_last_component_of_entry_point_matched(self, script_run_bench: Any) -> None:
        """Only the last component of entry_point (after the final dot) is matched."""
        task = self._feature_task(entry_point="Trainer.validate")
        # "validate" alone is sufficient; full qualified name not required
        result = script_run_bench._evaluate_feature(task, "implement validate inside trainer.py")
        assert result.correct is True

    def test_incorrect_when_file_missing_from_output(self, script_run_bench: Any) -> None:
        """correct=False when the file basename is absent from the output."""
        task = self._feature_task()
        result = script_run_bench._evaluate_feature(task, "implement validate somewhere")
        assert result.correct is False

    def test_extraction_failed_when_neither_found(self, script_run_bench: Any) -> None:
        """extraction_failed=True when neither entry_point nor file_stem found."""
        task = self._feature_task()
        result = script_run_bench._evaluate_feature(task, "nothing relevant here")
        assert result.extraction_failed is True

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_feature."""
        task = self._feature_task()
        result = script_run_bench._evaluate_feature(task, "validate inside trainer.py")
        assert result.evaluator_used == "_evaluate_feature"


# ===========================================================================
# _evaluate_real_issue
# ===========================================================================


class TestEvaluateRealIssue:
    """real_issue evaluator: file-set recall >= 0.70 threshold."""

    def _ri_task(self, files: list[str]) -> dict:
        """Return a minimal real_issue task dict."""
        return {
            "id": "RI-01",
            "type": "real_issue",
            "ground_truth": {"files_changed": files},
        }

    def test_correct_when_all_files_found(self, script_run_bench: Any) -> None:
        """correct=True when all GT file basenames appear in the output."""
        task = self._ri_task(["src/trainer.py", "src/loops.py"])
        result = script_run_bench._evaluate_real_issue(task, "Edit trainer.py and loops.py to fix the issue")
        assert result.scored is True
        assert result.correct is True
        assert result.recall == pytest.approx(1.0)

    def test_correct_at_exactly_threshold(self, script_run_bench: Any) -> None:
        """correct=True when recall equals exactly 0.70."""
        files = [f"src/mod{i}.py" for i in range(10)]
        task = self._ri_task(files)
        # Mention exactly 7 out of 10 basenames → recall = 0.70
        text = " ".join(f"mod{i}" for i in range(7))
        result = script_run_bench._evaluate_real_issue(task, text)
        assert result.correct is True

    def test_incorrect_below_threshold(self, script_run_bench: Any) -> None:
        """correct=False when fewer than 70% of GT files are found."""
        files = [f"src/mod{i}.py" for i in range(10)]
        task = self._ri_task(files)
        # Only 5 of 10 → recall = 0.50 < 0.70
        text = " ".join(f"mod{i}" for i in range(5))
        result = script_run_bench._evaluate_real_issue(task, text)
        assert result.correct is False

    def test_empty_files_changed_returns_unscored(self, script_run_bench: Any) -> None:
        """scored=False when ground_truth.files_changed is empty."""
        task = self._ri_task([])
        result = script_run_bench._evaluate_real_issue(task, "anything")
        assert result.scored is False

    def test_extraction_failed_when_no_file_found(self, script_run_bench: Any) -> None:
        """extraction_failed=True when none of the GT file basenames appear."""
        task = self._ri_task(["src/trainer.py"])
        result = script_run_bench._evaluate_real_issue(task, "completely unrelated output")
        assert result.extraction_failed is True

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_real_issue."""
        task = self._ri_task(["src/trainer.py"])
        result = script_run_bench._evaluate_real_issue(task, "trainer.py")
        assert result.evaluator_used == "_evaluate_real_issue"

    def test_file_matched_by_basename_not_full_path(self, script_run_bench: Any) -> None:
        """File matching uses the basename (after last '/'), not the full path."""
        task = self._ri_task(["deeply/nested/path/trainer.py"])
        result = script_run_bench._evaluate_real_issue(task, "edit trainer.py to fix the bug")
        assert result.correct is True


# ===========================================================================
# _evaluate_develop_br
# ===========================================================================


class TestEvaluateDevelopBr:
    """develop_blast_radius evaluator: recall over expected caller list."""

    def _br_task(self, callers: list[str]) -> dict:
        """Return a minimal develop_blast_radius task dict."""
        return {
            "id": "BR-01",
            "type": "develop_blast_radius",
            "ground_truth": {
                "fn_callers": callers,
                "unique_caller_count": len(callers),
            },
        }

    def test_correct_when_all_callers_found(self, script_run_bench: Any) -> None:
        """correct=True when all expected callers appear in canonical :: form."""
        callers = [
            "lightning.pytorch.trainer.trainer::Trainer.fit",
            "lightning.pytorch.loops.fit_loop::FitLoop.advance",
        ]
        task = self._br_task(callers)
        output = (
            "lightning.pytorch.trainer.trainer::Trainer.fit and "
            "lightning.pytorch.loops.fit_loop::FitLoop.advance both call the function"
        )
        result = script_run_bench._evaluate_develop_br(task, output)
        assert result.scored is True
        assert result.correct is True
        assert result.recall == pytest.approx(1.0)

    def test_incorrect_when_recall_below_threshold(self, script_run_bench: Any) -> None:
        """correct=False when fewer than 70% of expected callers are found."""
        callers = [f"lightning.pytorch.mod::Cls.method{i}" for i in range(10)]
        task = self._br_task(callers)
        # Mention only 5 of 10 → recall = 0.50 < 0.70
        output = " ".join(f"lightning.pytorch.mod::Cls.method{i}" for i in range(5))
        result = script_run_bench._evaluate_develop_br(task, output)
        assert result.correct is False
        assert result.recall is not None and result.recall < 0.70

    def test_empty_callers_returns_unscored(self, script_run_bench: Any) -> None:
        """scored=False when ground_truth.fn_callers is an empty list."""
        task = self._br_task([])
        result = script_run_bench._evaluate_develop_br(task, "anything")
        assert result.scored is False

    def test_recall_field_set_on_result(self, script_run_bench: Any) -> None:
        """recall field is always populated (not None) on a scoreable task."""
        callers = ["lightning.pytorch.trainer::Trainer.fit"]
        task = self._br_task(callers)
        result = script_run_bench._evaluate_develop_br(task, "lightning.pytorch.trainer::Trainer.fit")
        assert result.recall is not None

    def test_dotted_form_matched_as_fallback(self, script_run_bench: Any) -> None:
        """Dotted-form output (no ::) is matched against expected callers."""
        callers = ["lightning.pytorch.trainer.trainer::Trainer.fit"]
        task = self._br_task(callers)
        # Write the dotted equivalent without :: separator
        output = "lightning.pytorch.trainer.trainer.Trainer.fit was found"
        result = script_run_bench._evaluate_develop_br(task, output)
        assert result.recall == pytest.approx(1.0)

    def test_extraction_failed_when_no_caller_found(self, script_run_bench: Any) -> None:
        """extraction_failed=True when output contains no recognisable caller tokens."""
        callers = ["lightning.pytorch.trainer::Trainer.fit"]
        task = self._br_task(callers)
        result = script_run_bench._evaluate_develop_br(task, "completely unrelated prose output")
        assert result.extraction_failed is True

    def test_caller_count_gt_set(self, script_run_bench: Any) -> None:
        """caller_count_gt is populated from ground_truth.unique_caller_count."""
        callers = ["lightning.pytorch.mod::Cls.fn"]
        task = self._br_task(callers)
        result = script_run_bench._evaluate_develop_br(task, "")
        assert result.caller_count_gt == 1

    def test_evaluator_name_recorded(self, script_run_bench: Any) -> None:
        """evaluator_used is always _evaluate_develop_br."""
        callers = ["lightning.pytorch.mod::Cls.fn"]
        task = self._br_task(callers)
        result = script_run_bench._evaluate_develop_br(task, "lightning.pytorch.mod::Cls.fn")
        assert result.evaluator_used == "_evaluate_develop_br"

    def test_fuzzy_underscore_prefix_matched(self, script_run_bench: Any) -> None:
        """Underscore-prefixed class names match when method is identical."""
        callers = ["lightning.pytorch.loops.fit_loop::_FitLoop.advance"]
        task = self._br_task(callers)
        # Agent wrote without underscore prefix
        output = "lightning.pytorch.loops.fit_loop::FitLoop.advance"
        result = script_run_bench._evaluate_develop_br(task, output)
        assert result.recall == pytest.approx(1.0)


# ===========================================================================
# _extract_diff
# ===========================================================================


class TestExtractDiff:
    """Unified-diff extractor from agent output text."""

    _SIMPLE_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"

    def test_valid_diff_extracted(self, script_run_bench: Any) -> None:
        """A well-formed unified diff is returned verbatim."""
        text = f"here is the fix\n{self._SIMPLE_DIFF}"
        result = script_run_bench._extract_diff(text)
        assert result is not None
        assert "--- a/x.py" in result
        assert "+++ b/x.py" in result

    def test_none_when_no_diff_present(self, script_run_bench: Any) -> None:
        """None returned when the text contains no unified diff headers."""
        assert script_run_bench._extract_diff("no diff here") is None

    def test_trailing_fence_stripped(self, script_run_bench: Any) -> None:
        """Trailing markdown code fence is stripped from the extracted diff."""
        text = "Here:\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```"
        result = script_run_bench._extract_diff(text)
        assert result is not None
        assert "```" not in result

    def test_diff_ends_with_newline(self, script_run_bench: Any) -> None:
        """Extracted diff always ends with a newline character."""
        text = f"prefix\n{self._SIMPLE_DIFF.rstrip()}"
        result = script_run_bench._extract_diff(text)
        assert result is not None
        assert result.endswith("\n")

    def test_empty_string_returns_none(self, script_run_bench: Any) -> None:
        """Empty input string returns None."""
        assert script_run_bench._extract_diff("") is None

    def test_partial_diff_header_returns_none(self, script_run_bench: Any) -> None:
        """Text with only --- but no +++ header returns None."""
        assert script_run_bench._extract_diff("--- a/x.py\njust a comment") is None


# ===========================================================================
# _workflow_type_of
# ===========================================================================


class TestWorkflowTypeOf:
    """Workflow key accessor with task_type fallback."""

    def test_returns_workflow_type_when_set(self, script_run_bench: Any) -> None:
        """Returns workflow_type field when it is non-empty."""
        run = _make_run(script_run_bench, workflow_type="query", task_type="symbol_extraction")
        assert script_run_bench._workflow_type_of(run) == "query"

    def test_falls_back_to_task_type_when_empty(self, script_run_bench: Any) -> None:
        """Returns task_type when workflow_type is empty string."""
        run = _make_run(script_run_bench, workflow_type="", task_type="symbol_extraction")
        assert script_run_bench._workflow_type_of(run) == "symbol_extraction"

    @pytest.mark.parametrize(
        "workflow_type,task_type,expected",
        [
            ("query", "symbol_extraction", "query"),
            ("", "fn_call_graph", "fn_call_graph"),
            ("debug", "debug_from_trace", "debug"),
        ],
    )
    def test_parametrized_fallback_logic(
        self, script_run_bench: Any, workflow_type: str, task_type: str, expected: str
    ) -> None:
        """workflow_type wins when non-empty; task_type is the fallback."""
        run = _make_run(script_run_bench, workflow_type=workflow_type, task_type=task_type)
        assert script_run_bench._workflow_type_of(run) == expected


# ===========================================================================
# _effective_recall
# ===========================================================================


class TestBuildSystemPrompt:
    """System-prompt assembly must keep every non-tool sentence identical across arms (C-1)."""

    _EFFICIENCY = "Answer in as few tool calls as possible; do not re-verify results you already have."
    _OUTPUT_HDR = "For symbol location tasks: report exactly in this format:"

    def _plain(self, script_run_bench: Any) -> str:
        """Build the plain-arm system prompt with fixed framing arguments."""
        return script_run_bench._build_system_prompt("plain", "demo", "/repo", "/idx.json")

    def _codemap(self, script_run_bench: Any) -> str:
        """Build the codemap-arm system prompt with fixed framing arguments."""
        return script_run_bench._build_system_prompt("codemap", "demo", "/repo", "/idx.json")

    def test_efficiency_sentence_present_in_both_arms(self, script_run_bench: Any) -> None:
        """The single efficiency instruction appears verbatim in both arms."""
        assert self._EFFICIENCY in self._plain(script_run_bench)
        assert self._EFFICIENCY in self._codemap(script_run_bench)

    def test_output_format_block_identical_across_arms(self, script_run_bench: Any) -> None:
        """The output-format requirements block is byte-identical in both arms."""
        plain = self._plain(script_run_bench)
        codemap = self._codemap(script_run_bench)
        marker = self._OUTPUT_HDR
        plain_block = plain[plain.index(marker) :]
        codemap_block = codemap[codemap.index(marker) :]
        assert plain_block == codemap_block

    def test_plain_forbids_scan_query(self, script_run_bench: Any) -> None:
        """Plain arm keeps the scan-query prohibition; codemap arm does not forbid it."""
        plain = self._plain(script_run_bench)
        assert "Do NOT use scan-query" in plain
        assert "Do NOT use the Skill tool" in plain

    def test_codemap_documents_subcommands(self, script_run_bench: Any) -> None:
        """Codemap arm documents scan-query syntax and the subcommand reference list."""
        codemap = self._codemap(script_run_bench)
        assert "scan-query --index /idx.json <subcommand>" in codemap
        assert "fn-rdeps" in codemap
        assert "coupled" in codemap

    def test_index_path_substituted_into_codemap(self, script_run_bench: Any) -> None:
        """The concrete index path is interpolated into the codemap tool section."""
        assert "/custom/index.json" in script_run_bench._build_system_prompt(
            "codemap", "demo", "/repo", "/custom/index.json"
        )

    @pytest.mark.parametrize(
        "removed",
        [
            "STOP after one call",
            "Trust scan-query output as authoritative",
            "burns tokens",
            "MUST be your first tool call",
            "Do NOT grep",
        ],
    )
    def test_strategy_coaching_removed_from_codemap(self, script_run_bench: Any, removed: str) -> None:
        """Efficiency-steering / per-task strategy coaching is gone from the codemap prompt."""
        assert removed not in self._codemap(script_run_bench)

    def test_count_semantics_state_unique_callers(self, script_run_bench: Any) -> None:
        """Any retained fn-rdeps count note states unique callers, not call-site edges."""
        codemap = self._codemap(script_run_bench)
        assert "call-site EDGES" not in codemap
        assert "`count` = unique callers" in codemap


class TestEffectiveRecall:
    """Recall accessor with metric_got/expected fallback for count-based evaluators."""

    def test_returns_recall_field_when_set(self, script_run_bench: Any) -> None:
        """Returns quality.recall directly when it is populated."""
        run = _make_run(script_run_bench)
        run.quality = script_run_bench.BenchQuality(scored=True, recall=0.85)
        assert script_run_bench._effective_recall(run) == pytest.approx(0.85)

    def test_returns_none_for_unscored_run(self, script_run_bench: Any) -> None:
        """Returns None when the run's quality was not scored."""
        run = _make_run(script_run_bench)
        run.quality = script_run_bench.BenchQuality(scored=False)
        assert script_run_bench._effective_recall(run) is None

    def test_returns_none_for_extraction_failed(self, script_run_bench: Any) -> None:
        """Returns None when extraction_failed=True (no metric extracted)."""
        run = _make_run(script_run_bench)
        run.quality = script_run_bench.BenchQuality(scored=True, extraction_failed=True)
        assert script_run_bench._effective_recall(run) is None

    def test_fallback_to_ratio_when_recall_none(self, script_run_bench: Any) -> None:
        """Falls back to metric_got/metric_expected when recall is None."""
        run = _make_run(script_run_bench)
        run.quality = script_run_bench.BenchQuality(scored=True, recall=None, metric_got=8, metric_expected=10)
        result = script_run_bench._effective_recall(run)
        assert result == pytest.approx(0.8)

    def test_returns_none_when_none_run(self, script_run_bench: Any) -> None:
        """Returns None for a None run argument."""
        assert script_run_bench._effective_recall(None) is None

    def test_returns_none_when_metric_expected_zero(self, script_run_bench: Any) -> None:
        """Returns None when metric_expected is 0 (falsy denominator)."""
        run = _make_run(script_run_bench)
        run.quality = script_run_bench.BenchQuality(scored=True, recall=None, metric_got=0, metric_expected=0)
        assert script_run_bench._effective_recall(run) is None
