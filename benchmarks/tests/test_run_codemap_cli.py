"""Tests for benchmarks/run-codemap-cli.py.

Covers public API surface:
  - Dataclass defaults and construction (Task, ScenarioResult, TimingStats,
    AccuracyStats, SuiteStats, ValidationResult, Query)
  - Task loading (load_tasks, load_oss_tasks) with and without filters
  - Pure helper logic (path_to_module, module_to_grep_pattern, module_to_package)
  - Accuracy scoring (compute_precision_recall)
  - Verdict computation (compute_verdict)
  - JSON structure validators (validate_central_json, validate_rdeps_json,
    validate_deps_json)
  - scan-query subprocess wrapper (run_scan_query) with mocked subprocess
  - Index-path resolution (resolve_index_path)
  - Repo-path resolution (resolve_repo_path) with env-var override
  - load_oss_tasks absent-file skip behaviour
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(scope="session")
def real_tasks(script_run_cli: Any) -> list:
    """Load tasks-code.json once for the whole session.

    Returns:
        All benchmark tasks parsed from the real tasks-code.json file.
    """
    return script_run_cli.load_tasks()


@pytest.fixture()
def minimal_task_dict() -> dict:
    """Return a minimal valid raw task dict matching the tasks-code.json schema.

    Returns:
        Dict with all required keys populated with well-formed values.
    """
    return {
        "id": "T-99",
        "skill": "fix",
        "prompt": "A test prompt.",
        "primary_module": "pkg.mod",
        "risk_tier": "high",
        "queries": [{"cmd": "rdeps", "args": ["pkg.mod"]}],
        "ground_truth_keys": ["imported_by"],
    }


def _make_scenario(script_cli: Any, passed: bool, suite: str = "calls") -> Any:
    """Build a ScenarioResult with the minimum required fields.

    Args:
        script_cli: Loaded scan-query module fixture.
        passed: Whether the scenario passed.
        suite: Suite name string.

    Returns:
        ScenarioResult instance.
    """
    return script_cli.ScenarioResult(
        scenario="C1",
        name="coverage-gap",
        suite=suite,
        passed=passed,
        result={"coverage_gap": 0.5},
        threshold=script_cli.THRESHOLDS["C1"],
    )


# ===========================================================================
# Dataclass construction
# ===========================================================================


class TestDataclasses:
    """Verify dataclass fields and defaults behave as documented."""

    def test_query_stores_cmd_and_args(self, script_run_cli: Any) -> None:
        """Scenario: Query created from raw dict has correct cmd and args."""
        q = script_run_cli.Query(cmd="rdeps", args=["foo.bar"])
        assert q.cmd == "rdeps"
        assert q.args == ["foo.bar"]

    def test_task_from_dict_roundtrip(self, script_run_cli: Any, minimal_task_dict: dict) -> None:
        """Scenario: Task.from_dict parses every field correctly."""
        t = script_run_cli.Task.from_dict(minimal_task_dict)
        assert t.id == "T-99"
        assert t.skill == "fix"
        assert t.primary_module == "pkg.mod"
        assert t.risk_tier == "high"
        assert len(t.queries) == 1
        assert t.queries[0].cmd == "rdeps"

    def test_task_from_dict_empty_queries(self, script_run_cli: Any, minimal_task_dict: dict) -> None:
        """Scenario: Task.from_dict with empty queries list produces empty list."""
        minimal_task_dict["queries"] = []
        t = script_run_cli.Task.from_dict(minimal_task_dict)
        assert t.queries == []

    def test_scenario_result_notes_default_empty(self, script_run_cli: Any) -> None:
        """Scenario: ScenarioResult notes field defaults to empty string."""
        r = script_run_cli.ScenarioResult(
            scenario="C1",
            name="x",
            suite="calls",
            passed=True,
            result={},
            threshold={},
        )
        assert r.notes == ""

    def test_timing_stats_stores_all_fields(self, script_run_cli: Any) -> None:
        """Scenario: TimingStats round-trips all timing fields."""
        ts = script_run_cli.TimingStats(min_ms=1.0, median_ms=2.5, max_ms=10.0, n=5)
        assert ts.min_ms == 1.0
        assert ts.median_ms == 2.5
        assert ts.max_ms == 10.0
        assert ts.n == 5

    def test_accuracy_stats_stores_all_fields(self, script_run_cli: Any) -> None:
        """Scenario: AccuracyStats round-trips precision/recall and TP/FP/FN."""
        a = script_run_cli.AccuracyStats(
            precision=0.9,
            recall=0.8,
            tp=9,
            fp=1,
            fn=2,
            fp_modules=["a.b"],
            fn_modules=["c.d"],
        )
        assert a.precision == pytest.approx(0.9)
        assert a.recall == pytest.approx(0.8)
        assert a.tp == 9
        assert a.fp_modules == ["a.b"]

    def test_suite_stats_defaults_zero(self, script_run_cli: Any) -> None:
        """Scenario: SuiteStats initialises all counters to zero."""
        s = script_run_cli.SuiteStats()
        assert s.total == 0
        assert s.passed == 0
        assert s.failed == 0

    def test_validation_result_ok_has_empty_reason(self, script_run_cli: Any) -> None:
        """Scenario: ValidationResult ok=True carries an empty reason string."""
        vr = script_run_cli.ValidationResult(ok=True, reason="")
        assert vr.ok is True
        assert vr.reason == ""

    def test_validation_result_fail_has_reason(self, script_run_cli: Any) -> None:
        """Scenario: ValidationResult ok=False carries a non-empty reason."""
        vr = script_run_cli.ValidationResult(ok=False, reason="missing key")
        assert vr.ok is False
        assert "missing" in vr.reason


# ===========================================================================
# Task loading — load_tasks
# ===========================================================================


class TestLoadTasks:
    """Validate load_tasks contract against the real tasks-code.json file."""

    def test_load_tasks_returns_list_of_task_objects(self, script_run_cli: Any, real_tasks: list) -> None:
        """Scenario: load_tasks with no filter returns Task instances for all records."""
        assert len(real_tasks) > 0
        assert all(isinstance(t, script_run_cli.Task) for t in real_tasks)

    def test_load_tasks_total_count_matches_file(self, script_run_cli: Any, real_tasks: list) -> None:
        """Scenario: task count matches number of objects in tasks-code.json."""
        with script_run_cli.TASKS_FILE.open() as f:
            raw = json.load(f)
        assert len(real_tasks) == len(raw)

    @pytest.mark.parametrize("skill", ["fix", "feature", "refactor"])
    def test_load_tasks_skill_filter_returns_matching_only(self, script_run_cli: Any, skill: str) -> None:
        """Scenario: skill_filter keeps only tasks whose skill field matches.

        Args:
            skill: One of the three documented skill values.
        """
        filtered = script_run_cli.load_tasks(skill_filter=skill)
        assert len(filtered) > 0, f"Expected at least one '{skill}' task"
        assert all(t.skill == skill for t in filtered)

    def test_load_tasks_unknown_skill_filter_returns_empty(self, script_run_cli: Any) -> None:
        """Scenario: skill_filter with an unknown value produces an empty list."""
        result = script_run_cli.load_tasks(skill_filter="nonexistent_skill")
        assert result == []

    def test_load_tasks_no_filter_includes_all_skills(self, script_run_cli: Any, real_tasks: list) -> None:
        """Scenario: unfiltered load contains tasks from all three skill groups."""
        skills = {t.skill for t in real_tasks}
        assert skills >= {"fix", "feature", "refactor"}

    def test_load_tasks_queries_are_query_objects(self, script_run_cli: Any, real_tasks: list) -> None:
        """Scenario: every query within every task is a Query dataclass instance."""
        for task in real_tasks:
            for q in task.queries:
                assert isinstance(q, script_run_cli.Query), f"Task {task.id}: expected Query, got {type(q)}"

    def test_load_tasks_primary_module_is_dotted_string(self, script_run_cli: Any, real_tasks: list) -> None:
        """Scenario: primary_module for every task is a non-empty dotted string."""
        for task in real_tasks:
            assert "." in task.primary_module, f"Task {task.id} module not dotted: {task.primary_module}"

    def test_load_tasks_with_nonexistent_file_raises(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: TASKS_FILE pointing at a missing file raises FileNotFoundError."""
        with patch.object(script_run_cli, "TASKS_FILE", tmp_path / "missing.json"):
            with pytest.raises(FileNotFoundError):
                script_run_cli.load_tasks()

    def test_load_tasks_with_malformed_json_raises(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: TASKS_FILE containing invalid JSON raises json.JSONDecodeError."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with patch.object(script_run_cli, "TASKS_FILE", bad):
            with pytest.raises(json.JSONDecodeError):
                script_run_cli.load_tasks()


# ===========================================================================
# Task loading — load_oss_tasks
# ===========================================================================


@pytest.fixture()
def oss_tasks_file(tmp_path: Path) -> Path:
    """Write a minimal flat-list tasks-bench.json for load_oss_tasks tests.

    The load_oss_tasks function documents that it returns ``list[dict]`` and
    calls ``json.load`` expecting a list directly.  This fixture provides a
    controlled flat-list file so tests are independent of the real file layout.

    Returns:
        Path to a temporary tasks-bench.json containing a flat list of tasks.
    """
    tasks = [
        {"id": "SE-01", "type": "symbol_extraction", "ground_truth": {"qualified_name": "Foo.bar"}},
        {"id": "CQ-01", "type": "code_quality", "ground_truth": {"check": "undocumented"}},
        {"id": "RI-01", "type": "real_issue"},
        {"id": "DB-01", "type": "debug_from_trace"},
    ]
    p = tmp_path / "tasks-bench.json"
    p.write_text(json.dumps(tasks), encoding="utf-8")
    return p


class TestLoadOssTasks:
    """Validate load_oss_tasks contract (expects flat list JSON)."""

    def test_load_oss_tasks_returns_list(self, script_run_cli: Any, oss_tasks_file: Path) -> None:
        """Scenario: load_oss_tasks returns a list when the file contains a flat list."""
        with patch.object(script_run_cli, "OSS_TASKS_FILE", oss_tasks_file):
            result = script_run_cli.load_oss_tasks()
        assert isinstance(result, list)

    def test_load_oss_tasks_absent_file_returns_empty(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: load_oss_tasks returns [] when OSS_TASKS_FILE does not exist."""
        with patch.object(script_run_cli, "OSS_TASKS_FILE", tmp_path / "missing.json"):
            result = script_run_cli.load_oss_tasks()
        assert result == []

    @pytest.mark.parametrize(
        "type_filter",
        [
            pytest.param("symbol_extraction", id="symbol_extraction"),
            pytest.param("code_quality", id="code_quality"),
            pytest.param("real_issue", id="real_issue"),
        ],
    )
    def test_load_oss_tasks_type_filter_matches_only(
        self, script_run_cli: Any, type_filter: str, oss_tasks_file: Path
    ) -> None:
        """Scenario: type_filter keeps only tasks whose 'type' field matches.

        Args:
            type_filter: One of the documented task type values.
            oss_tasks_file: Path to fixture tasks file.
        """
        with patch.object(script_run_cli, "OSS_TASKS_FILE", oss_tasks_file):
            result = script_run_cli.load_oss_tasks(type_filter=type_filter)
        assert len(result) >= 1
        assert all(t.get("type") == type_filter for t in result)

    def test_load_oss_tasks_unknown_type_returns_empty(self, script_run_cli: Any, oss_tasks_file: Path) -> None:
        """Scenario: type_filter with an unknown value produces an empty list."""
        with patch.object(script_run_cli, "OSS_TASKS_FILE", oss_tasks_file):
            result = script_run_cli.load_oss_tasks(type_filter="does_not_exist")
        assert result == []

    def test_load_oss_tasks_no_filter_includes_all_types(self, script_run_cli: Any, oss_tasks_file: Path) -> None:
        """Scenario: unfiltered load returns all tasks across types."""
        with patch.object(script_run_cli, "OSS_TASKS_FILE", oss_tasks_file):
            all_tasks = script_run_cli.load_oss_tasks()
        types = {t.get("type") for t in all_tasks}
        assert "symbol_extraction" in types
        assert "code_quality" in types

    def test_load_oss_tasks_result_dicts_have_id_field(self, script_run_cli: Any, oss_tasks_file: Path) -> None:
        """Scenario: every returned dict has a non-empty 'id' field."""
        with patch.object(script_run_cli, "OSS_TASKS_FILE", oss_tasks_file):
            tasks = script_run_cli.load_oss_tasks()
        for t in tasks:
            assert t.get("id"), f"Task missing 'id': {t}"

    def test_load_oss_tasks_with_flat_list_json(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: flat-list JSON is returned as-is without wrapping.

        Args:
            tmp_path: Pytest temporary directory.
        """
        flat = [{"id": "X-01", "type": "code_quality"}]
        f = tmp_path / "flat.json"
        f.write_text(json.dumps(flat), encoding="utf-8")
        with patch.object(script_run_cli, "OSS_TASKS_FILE", f):
            result = script_run_cli.load_oss_tasks()
        assert result == flat


# ===========================================================================
# Path helpers
# ===========================================================================


class TestPathToModule:
    """Validate path_to_module conversion logic."""

    @pytest.mark.parametrize(
        "path,repo_root,expected",
        [
            # Standard layout
            ("/repo/pkg/mod.py", "/repo", "pkg.mod"),
            # src/ layout — strip prefix
            ("/repo/src/pkg/mod.py", "/repo", "pkg.mod"),
            # __init__.py collapses to package
            ("/repo/pkg/__init__.py", "/repo", "pkg"),
            # Nested __init__.py
            ("/repo/pkg/sub/__init__.py", "/repo", "pkg.sub"),
            # src/ layout with __init__.py
            ("/repo/src/pkg/__init__.py", "/repo", "pkg"),
        ],
    )
    def test_converts_py_path_to_dotted_module(
        self, script_run_cli: Any, path: str, repo_root: str, expected: str
    ) -> None:
        """Scenario: .py path is converted to the expected dotted module name.

        Args:
            path: Filesystem path to a Python source file.
            repo_root: Repository root used as os.path.relpath base.
            expected: Expected dotted module name.
        """
        assert script_run_cli.path_to_module(path, repo_root) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "/repo/README.md",
            "/repo/data.csv",
            "/repo/LICENSE",
        ],
    )
    def test_returns_none_for_non_py_files(self, script_run_cli: Any, path: str) -> None:
        """Scenario: non-.py paths return None.

        Args:
            path: Path to a non-Python file.
        """
        assert script_run_cli.path_to_module(path, "/repo") is None


class TestModuleToGrepPattern:
    """Validate module_to_grep_pattern output contract."""

    @pytest.mark.parametrize(
        "module,expected",
        [
            ("foo.bar", r"from foo.bar import\|import foo.bar"),
            ("pkg", r"from pkg import\|import pkg"),
            (
                "lightning.pytorch.trainer.trainer",
                r"from lightning.pytorch.trainer.trainer import\|import lightning.pytorch.trainer.trainer",
            ),
        ],
    )
    def test_pattern_contains_both_import_forms(self, script_run_cli: Any, module: str, expected: str) -> None:
        r"""Scenario: pattern contains 'from X import' and 'import X' forms joined by \|.

        Args:
            module: Dotted module name.
            expected: Expected grep alternation string.
        """
        assert script_run_cli.module_to_grep_pattern(module) == expected


class TestModuleToPackage:
    """Validate module_to_package parent extraction."""

    @pytest.mark.parametrize(
        "module,expected",
        [
            ("foo.bar.baz", "foo.bar"),
            ("foo.bar", "foo"),
            ("foo", None),
        ],
    )
    def test_returns_parent_package_or_none(self, script_run_cli: Any, module: str, expected: str | None) -> None:
        """Scenario: parent package extracted correctly for nested and top-level modules.

        Args:
            module: Dotted module name.
            expected: Expected parent package, or None for top-level.
        """
        assert script_run_cli.module_to_package(module) == expected


# ===========================================================================
# Accuracy scoring — compute_precision_recall
# ===========================================================================


class TestComputePrecisionRecall:
    """Validate compute_precision_recall contract from the docs."""

    @pytest.mark.parametrize(
        "codemap_set,grep_set,expected_precision,expected_recall,expected_tp,expected_fp,expected_fn",
        [
            # Perfect agreement
            ({"a", "b", "c"}, {"a", "b", "c"}, 1.0, 1.0, 3, 0, 0),
            # Codemap finds extra (FP)
            ({"a", "b", "x"}, {"a", "b"}, 2 / 3, 1.0, 2, 1, 0),
            # Codemap misses some (FN)
            ({"a"}, {"a", "b"}, 1.0, 0.5, 1, 0, 1),
            # No overlap at all
            ({"x"}, {"y"}, 0.0, 0.0, 0, 1, 1),
            # Single matching element
            ({"a"}, {"a"}, 1.0, 1.0, 1, 0, 0),
        ],
    )
    def test_precision_recall_values(
        self,
        script_run_cli: Any,
        codemap_set: set,
        grep_set: set,
        expected_precision: float,
        expected_recall: float,
        expected_tp: int,
        expected_fp: int,
        expected_fn: int,
    ) -> None:
        """Scenario: precision/recall computed correctly for documented TP/FP/FN formula.

        Args:
            codemap_set: Modules returned by scan-query rdeps.
            grep_set: Modules found by the grep baseline.
            expected_precision: Expected precision value.
            expected_recall: Expected recall value.
            expected_tp: Expected true positive count.
            expected_fp: Expected false positive count.
            expected_fn: Expected false negative count.
        """
        stats = script_run_cli.compute_precision_recall(codemap_set, grep_set)
        assert stats.precision == pytest.approx(expected_precision, abs=1e-4)
        assert stats.recall == pytest.approx(expected_recall, abs=1e-4)
        assert stats.tp == expected_tp
        assert stats.fp == expected_fp
        assert stats.fn == expected_fn

    def test_empty_codemap_set_precision_defaults_to_one(self, script_run_cli: Any) -> None:
        """Scenario: empty codemap set yields precision=1.0 per documented default."""
        stats = script_run_cli.compute_precision_recall(set(), {"a", "b"})
        assert stats.precision == pytest.approx(1.0)

    def test_empty_grep_set_recall_defaults_to_one(self, script_run_cli: Any) -> None:
        """Scenario: empty grep set yields recall=1.0 per documented default."""
        stats = script_run_cli.compute_precision_recall({"a", "b"}, set())
        assert stats.recall == pytest.approx(1.0)

    def test_both_empty_returns_perfect_scores(self, script_run_cli: Any) -> None:
        """Scenario: both sets empty yields precision=1.0 and recall=1.0."""
        stats = script_run_cli.compute_precision_recall(set(), set())
        assert stats.precision == pytest.approx(1.0)
        assert stats.recall == pytest.approx(1.0)

    def test_fp_modules_sorted(self, script_run_cli: Any) -> None:
        """Scenario: fp_modules list is sorted alphabetically."""
        stats = script_run_cli.compute_precision_recall({"z", "a", "m"}, set())
        assert stats.fp_modules == sorted(stats.fp_modules)

    def test_fn_modules_sorted(self, script_run_cli: Any) -> None:
        """Scenario: fn_modules list is sorted alphabetically."""
        stats = script_run_cli.compute_precision_recall(set(), {"z", "a", "m"})
        assert stats.fn_modules == sorted(stats.fn_modules)

    def test_precision_rounded_to_four_places(self, script_run_cli: Any) -> None:
        """Scenario: precision is rounded to 4 decimal places as documented."""
        # 2/3 = 0.6667
        stats = script_run_cli.compute_precision_recall({"a", "b", "c"}, {"a", "b"})
        assert stats.precision == round(stats.precision, 4)


# ===========================================================================
# Verdict computation — compute_verdict
# ===========================================================================


class TestComputeVerdict:
    """Validate compute_verdict against documented thresholds."""

    def test_all_pass_returns_pass(self, script_run_cli: Any) -> None:
        """Scenario: all scenarios passed → verdict is PASS."""
        results = [_make_scenario(script_run_cli, True) for _ in range(3)]
        assert script_run_cli.compute_verdict(results) == "PASS"

    def test_all_fail_returns_fail(self, script_run_cli: Any) -> None:
        """Scenario: all scenarios failed → verdict is FAIL."""
        results = [_make_scenario(script_run_cli, False) for _ in range(4)]
        assert script_run_cli.compute_verdict(results) == "FAIL"

    def test_empty_results_returns_fail(self, script_run_cli: Any) -> None:
        """Scenario: empty results list → FAIL per documented behaviour."""
        assert script_run_cli.compute_verdict([]) == "FAIL"

    @pytest.mark.parametrize(
        "n_pass,n_total,expected",
        [
            (3, 4, "PARTIAL"),  # 75% >= 50% but not 100%
            (1, 2, "PARTIAL"),  # exactly 50%
            (1, 3, "FAIL"),  # 33% < 50%
            (0, 3, "FAIL"),  # 0%
        ],
    )
    def test_partial_and_fail_boundary(self, script_run_cli: Any, n_pass: int, n_total: int, expected: str) -> None:
        """Scenario: verdict boundary at 50% pass rate per documented thresholds.

        Args:
            n_pass: Number of passing scenarios.
            n_total: Total number of scenarios.
            expected: Expected verdict string.
        """
        results = [_make_scenario(script_run_cli, i < n_pass) for i in range(n_total)]
        assert script_run_cli.compute_verdict(results) == expected


# ===========================================================================
# JSON validators
# ===========================================================================


class TestValidateCentralJson:
    """Validate validate_central_json contract."""

    def test_valid_central_response_returns_ok(self, script_run_cli: Any) -> None:
        """Scenario: well-formed central response with rdep_count → ok=True."""
        data = {"central": [{"name": "foo.bar", "rdep_count": 5}]}
        result = script_run_cli.validate_central_json(data)
        assert result.ok is True
        assert result.reason == ""

    def test_missing_central_key_returns_not_ok(self, script_run_cli: Any) -> None:
        """Scenario: response missing 'central' key → ok=False with reason."""
        result = script_run_cli.validate_central_json({"other_key": []})
        assert result.ok is False
        assert "central" in result.reason

    def test_empty_central_list_returns_not_ok(self, script_run_cli: Any) -> None:
        """Scenario: 'central' key present but empty list → ok=False."""
        result = script_run_cli.validate_central_json({"central": []})
        assert result.ok is False

    def test_central_not_a_list_returns_not_ok(self, script_run_cli: Any) -> None:
        """Scenario: 'central' value is not a list → ok=False."""
        result = script_run_cli.validate_central_json({"central": "not a list"})
        assert result.ok is False

    def test_item_missing_rdep_count_returns_not_ok(self, script_run_cli: Any) -> None:
        """Scenario: central item without rdep_count → ok=False with reason."""
        data = {"central": [{"name": "foo", "other": 1}]}
        result = script_run_cli.validate_central_json(data)
        assert result.ok is False
        assert "rdep_count" in result.reason

    def test_multiple_valid_items_returns_ok(self, script_run_cli: Any) -> None:
        """Scenario: multiple items all having rdep_count → ok=True."""
        data = {"central": [{"rdep_count": i} for i in range(5)]}
        result = script_run_cli.validate_central_json(data)
        assert result.ok is True


class TestValidateRdepsJson:
    """Validate validate_rdeps_json contract."""

    def test_valid_rdeps_response_returns_ok(self, script_run_cli: Any) -> None:
        """Scenario: response with imported_by and module keys → ok=True."""
        data = {"imported_by": ["a.b", "c.d"], "module": "foo.bar"}
        result = script_run_cli.validate_rdeps_json(data)
        assert result.ok is True

    @pytest.mark.parametrize(
        "data,expected_reason_fragment",
        [
            ({"module": "foo"}, "imported_by"),  # missing imported_by
            ({"imported_by": []}, "module"),  # missing module
            ({}, "imported_by"),  # both missing — first check wins
        ],
    )
    def test_missing_keys_return_not_ok(self, script_run_cli: Any, data: dict, expected_reason_fragment: str) -> None:
        """Scenario: missing required keys produce ok=False with the key name in reason.

        Args:
            data: Incomplete response dict.
            expected_reason_fragment: Substring expected in the reason string.
        """
        result = script_run_cli.validate_rdeps_json(data)
        assert result.ok is False
        assert expected_reason_fragment in result.reason


class TestValidateDepsJson:
    """Validate validate_deps_json contract."""

    def test_valid_deps_response_returns_ok(self, script_run_cli: Any) -> None:
        """Scenario: response with direct_imports and module keys → ok=True."""
        data = {"direct_imports": ["x.y"], "module": "foo.bar"}
        result = script_run_cli.validate_deps_json(data)
        assert result.ok is True

    @pytest.mark.parametrize(
        "data,expected_reason_fragment",
        [
            ({"module": "foo"}, "direct_imports"),
            ({"direct_imports": []}, "module"),
            ({}, "direct_imports"),
        ],
    )
    def test_missing_keys_return_not_ok(self, script_run_cli: Any, data: dict, expected_reason_fragment: str) -> None:
        """Scenario: missing required keys produce ok=False with the key name in reason.

        Args:
            data: Incomplete response dict.
            expected_reason_fragment: Substring expected in the reason string.
        """
        result = script_run_cli.validate_deps_json(data)
        assert result.ok is False
        assert expected_reason_fragment in result.reason


# ===========================================================================
# run_scan_query — subprocess wrapper
# ===========================================================================


class TestRunScanQuery:
    """Validate run_scan_query subprocess contract via mocked subprocess.run."""

    def _fake_bin(self, tmp_path: Path) -> Path:
        """Create a placeholder binary file for path resolution.

        Args:
            tmp_path: Pytest temporary directory.

        Returns:
            Path to a file named 'scan-query'.
        """
        p = tmp_path / "scan-query"
        p.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        return p

    def test_returns_parsed_json_on_success(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: zero-exit scan-query with valid JSON stdout returns parsed dict."""
        payload = {"imported_by": ["a.b"], "module": "foo"}
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = json.dumps(payload)

        with patch.object(script_run_cli, "_run", return_value=fake_result):
            result = script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["rdeps", "foo"],
                tmp_path / "index.json",
                tmp_path,
            )
        assert result == payload

    def test_returns_none_on_nonzero_exit(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: non-zero returncode from scan-query yields None."""
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = ""

        with patch.object(script_run_cli, "_run", return_value=fake_result):
            result = script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["rdeps", "missing"],
                tmp_path / "index.json",
                tmp_path,
            )
        assert result is None

    def test_returns_none_on_json_decode_error(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: scan-query returns non-JSON stdout → None, no exception raised."""
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "not json at all"

        with patch.object(script_run_cli, "_run", return_value=fake_result):
            result = script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["central", "--top", "5"],
                tmp_path / "index.json",
                tmp_path,
            )
        assert result is None

    def test_returns_none_on_timeout(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: subprocess.TimeoutExpired from _run is caught and returns None."""
        with patch.object(script_run_cli, "_run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=30)):
            result = script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["central"],
                tmp_path / "index.json",
                tmp_path,
            )
        assert result is None

    def test_returns_none_on_os_error(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: OSError (binary missing) is caught and returns None."""
        with patch.object(script_run_cli, "_run", side_effect=OSError("file not found")):
            result = script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["rdeps", "foo"],
                tmp_path / "index.json",
                tmp_path,
            )
        assert result is None

    def test_passes_index_flag_to_subprocess(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: run_scan_query always injects --index <path> into the command."""
        index_path = tmp_path / "my-index.json"
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = json.dumps({"ok": True})

        captured: list[list[str]] = []

        def _capture_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return fake_result

        with patch.object(script_run_cli, "_run", side_effect=_capture_run):
            script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["rdeps", "foo.bar"],
                index_path,
                tmp_path,
            )

        assert len(captured) == 1
        cmd = captured[0]
        assert "--index" in cmd
        idx = cmd.index("--index")
        assert str(index_path.resolve()) in cmd[idx + 1]

    def test_subcommand_appended_after_index(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: subcommand args appear after --index flag in the assembled command."""
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = json.dumps({})
        captured: list[list[str]] = []

        def _capture(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return fake_result

        with patch.object(script_run_cli, "_run", side_effect=_capture):
            script_run_cli.run_scan_query(
                self._fake_bin(tmp_path),
                ["deps", "some.module"],
                tmp_path / "idx.json",
                tmp_path,
            )

        cmd = captured[0]
        assert "deps" in cmd
        assert "some.module" in cmd


# ===========================================================================
# resolve_index_path
# ===========================================================================


class TestResolveIndexPath:
    """Validate resolve_index_path resolution order."""

    def test_explicit_arg_returned_directly(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: when arg is provided it is returned without further resolution."""
        result = script_run_cli.resolve_index_path("/custom/path/index.json", tmp_path)
        assert result == Path("/custom/path/index.json")

    def test_finds_index_in_cache_codemap_by_repo_name(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: index at <repo>/.cache/codemap/<name>.json is discovered automatically."""
        # Create the directory structure matching the lookup logic.
        cache_dir = tmp_path / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        index_file = cache_dir / f"{tmp_path.name}.json"
        index_file.write_text("{}", encoding="utf-8")

        result = script_run_cli.resolve_index_path(None, tmp_path)
        assert result == index_file

    def test_finds_index_after_stripping_master_suffix(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: repo named '<name>-master' resolves to '<name>.json' in cache."""
        # Simulate a repo dir named pytorch-lightning-master
        repo = tmp_path / "pytorch-lightning-master"
        repo.mkdir()
        cache_dir = repo / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        index_file = cache_dir / "pytorch-lightning.json"
        index_file.write_text("{}", encoding="utf-8")

        result = script_run_cli.resolve_index_path(None, repo)
        assert result == index_file

    def test_falls_back_to_first_json_in_cache_codemap(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: when name-based lookup fails, first *.json in .cache/codemap/ is used."""
        cache_dir = tmp_path / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        fallback = cache_dir / "anything.json"
        fallback.write_text("{}", encoding="utf-8")

        # repo name won't match 'anything'
        result = script_run_cli.resolve_index_path(None, tmp_path)
        # either the name-based default path or 'anything.json' — both are valid
        # but the file 'anything.json' exists so it should be found first
        assert result.exists()

    def test_returns_default_path_when_no_index_found(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: when no index exists the function returns the canonical default path."""
        # No .cache/ dir created — lookup finds nothing.
        result = script_run_cli.resolve_index_path(None, tmp_path)
        # Should be a path under tmp_path/.cache/codemap/
        assert ".cache" in str(result)
        assert result.suffix == ".json"


# ===========================================================================
# resolve_repo_path
# ===========================================================================


class TestResolveRepoPath:
    """Validate resolve_repo_path resolution order."""

    def test_explicit_existing_dir_returns_path(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: valid existing directory arg is returned as Path."""
        result = script_run_cli.resolve_repo_path(str(tmp_path))
        assert result == tmp_path

    def test_explicit_nonexistent_dir_returns_none(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: arg pointing to a non-existent directory returns None."""
        missing = str(tmp_path / "no_such_dir")
        result = script_run_cli.resolve_repo_path(missing)
        assert result is None

    def test_env_var_used_when_arg_absent(
        self, script_run_cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario: PYTORCH_LIGHTNING_PATH env var is consulted when arg is None."""
        monkeypatch.setenv("PYTORCH_LIGHTNING_PATH", str(tmp_path))
        result = script_run_cli.resolve_repo_path(None)
        assert result == tmp_path

    def test_env_var_nonexistent_dir_falls_through(
        self, script_run_cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario: PYTORCH_LIGHTNING_PATH pointing to missing dir falls through to local check."""
        monkeypatch.setenv("PYTORCH_LIGHTNING_PATH", str(tmp_path / "no_such"))
        # Patch cwd so ./pytorch-lightning also doesn't exist.
        with patch("pathlib.Path.is_dir", return_value=False):
            result = script_run_cli.resolve_repo_path(None)
        assert result is None

    def test_no_arg_no_env_no_local_returns_none(self, script_run_cli: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scenario: all three resolution sources absent → None returned."""
        monkeypatch.delenv("PYTORCH_LIGHTNING_PATH", raising=False)
        # Make Path.is_dir always False to suppress ./pytorch-lightning fallback.
        with patch("pathlib.Path.is_dir", return_value=False):
            result = script_run_cli.resolve_repo_path(None)
        assert result is None


# ===========================================================================
# find_codemap_bin
# ===========================================================================


class TestFindCodemapBin:
    """Validate find_codemap_bin resolution logic."""

    def test_returns_none_when_not_on_path_and_no_plugin_root(
        self, script_run_cli: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario: binary absent from PATH and no plugin_root → None."""
        with patch("shutil.which", return_value=None):
            result = script_run_cli.find_codemap_bin("scan-query", plugin_root=None)
        assert result is None

    def test_finds_binary_via_shutil_which(self, script_run_cli: Any) -> None:
        """Scenario: binary present on PATH is returned as a Path."""
        with patch("shutil.which", return_value="/usr/local/bin/scan-query"):
            result = script_run_cli.find_codemap_bin("scan-query", plugin_root=None)
        assert result == Path("/usr/local/bin/scan-query")

    def test_finds_binary_in_plugin_root_when_not_on_path(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: binary not on PATH but present under plugin_root/plugins/codemap/bin/."""
        bin_dir = tmp_path / "plugins" / "codemap" / "bin"
        bin_dir.mkdir(parents=True)
        binary = bin_dir / "scan-query"
        binary.write_text("#!/usr/bin/env python3\n")

        with patch("shutil.which", return_value=None):
            result = script_run_cli.find_codemap_bin("scan-query", plugin_root=tmp_path)
        assert result == binary

    def test_returns_none_when_plugin_root_lacks_binary(self, script_run_cli: Any, tmp_path: Path) -> None:
        """Scenario: plugin_root provided but binary file absent → None."""
        with patch("shutil.which", return_value=None):
            result = script_run_cli.find_codemap_bin("scan-query", plugin_root=tmp_path)
        assert result is None


# ===========================================================================
# THRESHOLDS config sanity
# ===========================================================================


class TestThresholdsConfig:
    """Smoke-check that THRESHOLDS dict has expected keys and numeric values."""

    @pytest.mark.parametrize(
        "key,sub_key,lo,hi",
        [
            ("C1", "coverage_gap_min", 0.0, 1.0),
            ("C2", "infeasible_path_fraction_min", 0.0, 1.0),
            ("C3", "leverage_ratio_min", 1.0, 100.0),
            ("A1", "precision_min", 0.0, 1.0),
            ("A1", "recall_min", 0.0, 1.0),
            ("A2", "precision_min", 0.0, 1.0),
            ("A3", "fp_rate_max", 0.0, 1.0),
            ("L1", "median_ms_max", 1.0, 10_000.0),
            ("L2", "median_ms_max", 1.0, 10_000.0),
            ("L3", "amortized_ms_max", 1.0, 10_000.0),
            ("L4", "speedup_min", 1.0, 1_000.0),
        ],
    )
    def test_threshold_value_in_expected_range(
        self, script_run_cli: Any, key: str, sub_key: str, lo: float, hi: float
    ) -> None:
        """Scenario: each threshold value is a float within a plausible range.

        Args:
            key: Top-level THRESHOLDS key (e.g. 'C1').
            sub_key: Sub-key within the threshold dict.
            lo: Lower bound for the plausible range.
            hi: Upper bound for the plausible range.
        """
        value = script_run_cli.THRESHOLDS[key][sub_key]
        assert isinstance(value, (int, float)), f"THRESHOLDS[{key!r}][{sub_key!r}] is not numeric"
        assert lo <= value <= hi, f"THRESHOLDS[{key!r}][{sub_key!r}]={value} not in [{lo}, {hi}]"

    def test_injection_thresholds_have_boolean_flags(self, script_run_cli: Any) -> None:
        """Scenario: injection thresholds have block_present and json_valid booleans."""
        for key in ("I_fix", "I_feature", "I_refactor"):
            assert script_run_cli.THRESHOLDS[key]["block_present"] is True
            assert script_run_cli.THRESHOLDS[key]["json_valid"] is True


# ===========================================================================
# Integration — scan-query binary against a real repo (psf/requests)
# ===========================================================================


@pytest.mark.integration
class TestIntegrationScanQuery:
    """Run the scan-query binary against a cloned psf/requests repo.

    Skipped when the binary is absent or git clone fails (no network).
    """

    def test_central_returns_valid_structure(
        self, script_run_cli: Any, scan_query_binary: Any, sample_repo: Any
    ) -> None:
        """Scenario: central subcommand returns a dict that passes validate_central_json."""
        repo, index = sample_repo
        data = script_run_cli.run_scan_query(scan_query_binary, ["central"], index, repo)
        assert data is not None, "run_scan_query returned None for 'central'"
        result = script_run_cli.validate_central_json(data)
        assert result.ok, f"validate_central_json failed: {result.reason}"

    def test_rdeps_known_module_returns_valid_structure(
        self, script_run_cli: Any, scan_query_binary: Any, sample_repo: Any
    ) -> None:
        """Scenario: rdeps for requests.api returns a dict that passes validate_rdeps_json."""
        repo, index = sample_repo
        data = script_run_cli.run_scan_query(scan_query_binary, ["rdeps", "requests.api"], index, repo)
        assert data is not None, "run_scan_query returned None for 'rdeps requests.api'"
        result = script_run_cli.validate_rdeps_json(data)
        assert result.ok, f"validate_rdeps_json failed: {result.reason}"

    def test_deps_known_module_returns_valid_structure(
        self, script_run_cli: Any, scan_query_binary: Any, sample_repo: Any
    ) -> None:
        """Scenario: deps for requests.api returns a dict that passes validate_deps_json."""
        repo, index = sample_repo
        data = script_run_cli.run_scan_query(scan_query_binary, ["deps", "requests.api"], index, repo)
        assert data is not None, "run_scan_query returned None for 'deps requests.api'"
        result = script_run_cli.validate_deps_json(data)
        assert result.ok, f"validate_deps_json failed: {result.reason}"

    def test_unknown_subcommand_returns_none(
        self, script_run_cli: Any, scan_query_binary: Any, sample_repo: Any
    ) -> None:
        """Scenario: unrecognised subcommand causes run_scan_query to return None."""
        repo, index = sample_repo
        data = script_run_cli.run_scan_query(scan_query_binary, ["not-a-real-subcommand"], index, repo)
        assert data is None

    def test_central_entries_have_name_and_rdep_count(
        self, script_run_cli: Any, scan_query_binary: Any, sample_repo: Any
    ) -> None:
        """Scenario: every entry in central list has both 'name' and 'rdep_count' fields."""
        repo, index = sample_repo
        data = script_run_cli.run_scan_query(scan_query_binary, ["central"], index, repo)
        assert data is not None
        for entry in data["central"]:
            assert "name" in entry, f"central entry missing 'name': {entry}"
            assert "rdep_count" in entry, f"central entry missing 'rdep_count': {entry}"


# ===========================================================================
# Integration — full suites against pytorch-lightning repo
# Skipped when PL_REPO_PATH not set and ~/Workspace/pytorch-lightning-master absent.
# ===========================================================================


@pytest.mark.integration
class TestIntegrationSuiteC:
    """Suite C: call-savings measurement against pytorch-lightning."""

    def test_returns_three_results(self, script_run_cli: Any, pytorch_lightning_repo: Any) -> None:
        """Scenario: run_measure_calls returns exactly 3 ScenarioResult objects."""
        results = script_run_cli.run_measure_calls(pytorch_lightning_repo)
        assert len(results) == 3

    def test_scenario_ids(self, script_run_cli: Any, pytorch_lightning_repo: Any) -> None:
        """Scenario: the three results have scenario IDs C1, C2, C3."""
        results = script_run_cli.run_measure_calls(pytorch_lightning_repo)
        assert {r.scenario for r in results} == {"C1", "C2", "C3"}

    def test_results_are_scenario_result_instances(self, script_run_cli: Any, pytorch_lightning_repo: Any) -> None:
        """Scenario: every item returned is a ScenarioResult dataclass."""
        results = script_run_cli.run_measure_calls(pytorch_lightning_repo)
        for r in results:
            assert isinstance(r, script_run_cli.ScenarioResult)


@pytest.mark.integration
class TestIntegrationSuiteA:
    """Suite A: accuracy measurement against pytorch-lightning."""

    def test_returns_three_results(
        self, script_run_cli: Any, pytorch_lightning_repo: Any, scan_query_binary: Any, pytorch_lightning_index: Any
    ) -> None:
        """Scenario: run_measure_accuracy returns exactly 3 ScenarioResult objects."""
        results = script_run_cli.run_measure_accuracy(
            pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index
        )
        assert len(results) == 3

    def test_scenario_ids(
        self, script_run_cli: Any, pytorch_lightning_repo: Any, scan_query_binary: Any, pytorch_lightning_index: Any
    ) -> None:
        """Scenario: the three results have scenario IDs A1, A2, A3."""
        results = script_run_cli.run_measure_accuracy(
            pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index
        )
        assert {r.scenario for r in results} == {"A1", "A2", "A3"}


@pytest.mark.integration
class TestIntegrationSuiteL:
    """Suite L: latency measurement against pytorch-lightning."""

    def test_returns_four_results(
        self,
        script_run_cli: Any,
        pytorch_lightning_repo: Any,
        scan_query_binary: Any,
        pytorch_lightning_index: Any,
        scan_index_binary: Any,
    ) -> None:
        """Scenario: run_measure_latency returns exactly 4 ScenarioResult objects."""
        results = script_run_cli.run_measure_latency(
            pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index, scan_index_binary
        )
        assert len(results) == 4

    def test_scenario_ids(
        self,
        script_run_cli: Any,
        pytorch_lightning_repo: Any,
        scan_query_binary: Any,
        pytorch_lightning_index: Any,
        scan_index_binary: Any,
    ) -> None:
        """Scenario: the four results have scenario IDs L1, L2, L3, L4."""
        results = script_run_cli.run_measure_latency(
            pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index, scan_index_binary
        )
        assert {r.scenario for r in results} == {"L1", "L2", "L3", "L4"}


@pytest.mark.integration
class TestIntegrationSuiteI:
    """Suite I: injection verification against pytorch-lightning."""

    def test_returns_three_results(
        self,
        script_run_cli: Any,
        pytorch_lightning_repo: Any,
        scan_query_binary: Any,
        pytorch_lightning_index: Any,
    ) -> None:
        """Scenario: run_measure_injection returns exactly 3 ScenarioResult objects."""
        results = script_run_cli.run_measure_injection(
            REPO_ROOT, pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index
        )
        assert len(results) == 3

    def test_scenario_ids(
        self,
        script_run_cli: Any,
        pytorch_lightning_repo: Any,
        scan_query_binary: Any,
        pytorch_lightning_index: Any,
    ) -> None:
        """Scenario: the three results have scenario IDs I_fix, I_feature, I_refactor."""
        results = script_run_cli.run_measure_injection(
            REPO_ROOT, pytorch_lightning_repo, scan_query_binary, pytorch_lightning_index
        )
        assert {r.scenario for r in results} == {"I_fix", "I_feature", "I_refactor"}
