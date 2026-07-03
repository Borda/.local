"""Tests for benchmarks/generate-tasks-bench.py.

Covers pure validation logic (validator functions, JSON parsing, ground-truth
comparison, mode selection, task-type routing) with mocked scan-query subprocess
calls.  No real scan-query binary or codemap index is needed.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# TASKS_FILE constant
# ===========================================================================


class TestTasksFile:
    """Contract: TASKS_FILE must resolve relative to the script, not cwd."""

    def test_tasks_file_points_to_suites_dir(self, script_gen_bench: Any) -> None:
        """TASKS_FILE is inside benchmarks/suites/ regardless of working directory.

        Scenario: script is loaded from any cwd; TASKS_FILE must always name
        the same file within the project tree.
        """
        assert script_gen_bench.TASKS_FILE.parent.name == "suites"
        assert script_gen_bench.TASKS_FILE.name == "tasks-bench.json"

    def test_tasks_file_parent_is_under_benchmarks(self, script_gen_bench: Any) -> None:
        """TASKS_FILE's grandparent directory is the benchmarks/ directory.

        Scenario: confirms the two-level path structure
        benchmarks/suites/tasks-bench.json is always resolved.
        """
        assert script_gen_bench.TASKS_FILE.parent.parent.name == "benchmarks"

    def test_tasks_file_exists(self, script_gen_bench: Any) -> None:
        """TASKS_FILE points at an actual file on disk.

        Scenario: suite file is present; generator can open it without error.
        """
        assert script_gen_bench.TASKS_FILE.exists(), f"{script_gen_bench.TASKS_FILE} must exist"

    def test_tasks_file_is_valid_json(self, script_gen_bench: Any) -> None:
        """tasks-bench.json can be parsed without error.

        Scenario: file has not been corrupted; basic sanity for all downstream
        tasks that read it.
        """
        content = script_gen_bench.TASKS_FILE.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, (dict, list))

    def test_tasks_file_contains_task_list(self, script_gen_bench: Any) -> None:
        """tasks-bench.json contains a non-empty 'tasks' list.

        Scenario: file is a dict wrapper with a 'tasks' key (the format the
        script documents); at least one task must be present.
        """
        data = json.loads(script_gen_bench.TASKS_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        tasks = data.get("tasks", [])
        assert len(tasks) > 0


# ===========================================================================
# find_codemap_bin
# ===========================================================================


class TestFindCodemapBin:
    """Contract: resolve binary by PATH lookup then plugin-dir fallback."""

    def test_returns_none_when_not_found(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when binary absent from PATH and plugin root.

        Scenario: clean environment; binary not installed.
        """
        with patch("shutil.which", return_value=None):
            result = script_gen_bench.find_codemap_bin("scan-query", tmp_path)
        assert result is None

    def test_returns_path_when_on_path(self, script_gen_bench: Any) -> None:
        """Returns Path object when binary is found via shutil.which.

        Scenario: binary installed globally; PATH lookup succeeds.
        """
        with patch("shutil.which", return_value="/usr/local/bin/scan-query"):
            result = script_gen_bench.find_codemap_bin("scan-query")
        assert result == Path("/usr/local/bin/scan-query")

    def test_falls_back_to_plugin_dir(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Falls back to plugins/codemap/bin/<name> when PATH lookup fails.

        Scenario: binary not on PATH but present in plugin directory structure.
        """
        bin_dir = tmp_path / "plugins" / "codemap" / "bin"
        bin_dir.mkdir(parents=True)
        binary = bin_dir / "scan-query"
        binary.write_text("#!/bin/sh")

        with patch("shutil.which", return_value=None):
            result = script_gen_bench.find_codemap_bin("scan-query", tmp_path)
        assert result == binary

    def test_plugin_fallback_returns_none_when_file_absent(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when plugin dir exists but binary file is absent.

        Scenario: partial plugin install; bin/ dir created but binary not
        present.
        """
        bin_dir = tmp_path / "plugins" / "codemap" / "bin"
        bin_dir.mkdir(parents=True)
        # binary file deliberately NOT created

        with patch("shutil.which", return_value=None):
            result = script_gen_bench.find_codemap_bin("scan-query", tmp_path)
        assert result is None

    def test_no_plugin_root_returns_none_without_which(self, script_gen_bench: Any) -> None:
        """Returns None when plugin_root omitted and PATH lookup fails.

        Scenario: no plugin_root provided; which() returns None.
        """
        with patch("shutil.which", return_value=None):
            result = script_gen_bench.find_codemap_bin("scan-query")
        assert result is None


# ===========================================================================
# resolve_index_path
# ===========================================================================


class TestResolveIndexPath:
    """Contract: return explicit arg as-is; otherwise discover index file."""

    def test_returns_explicit_arg_unchanged(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns the explicit --index-path argument verbatim as a Path.

        Scenario: user passes --index-path; resolution must not alter it.
        """
        explicit = "/some/custom/index.json"
        result = script_gen_bench.resolve_index_path(explicit, tmp_path)
        assert result == Path(explicit)

    def test_finds_index_in_cache_codemap(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Discovers index JSON at <repo>/.cache/codemap/<name>.json.

        Scenario: default layout; index built into .cache/codemap/.
        """
        repo_name = tmp_path.name
        cache_dir = tmp_path / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        index_file = cache_dir / f"{repo_name}.json"
        index_file.write_text("{}")

        result = script_gen_bench.resolve_index_path(None, tmp_path)
        assert result == index_file

    def test_finds_index_in_cache_scan(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Falls back to .cache/scan/ when .cache/codemap/<name>.json absent.

        Scenario: older layout uses .cache/scan/ instead of .cache/codemap/.
        """
        repo_name = tmp_path.name
        cache_dir = tmp_path / ".cache" / "scan"
        cache_dir.mkdir(parents=True)
        index_file = cache_dir / f"{repo_name}.json"
        index_file.write_text("{}")

        result = script_gen_bench.resolve_index_path(None, tmp_path)
        assert result == index_file

    def test_strips_master_suffix_from_repo_name(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Strips -master suffix when looking up index file.

        Scenario: repo cloned as pytorch-lightning-master; index stored as
        pytorch-lightning.json.
        """
        # Use a temp dir whose name ends in -master by creating a subdir
        repo_dir = tmp_path / "myrepo-master"
        repo_dir.mkdir()
        cache_dir = repo_dir / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        # file uses stem without -master suffix
        (cache_dir / "myrepo.json").write_text("{}")

        result = script_gen_bench.resolve_index_path(None, repo_dir)
        assert result == cache_dir / "myrepo.json"

    def test_falls_back_to_first_json_glob(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Falls back to first JSON found via glob when name-based lookup fails.

        Scenario: index named differently from repo; glob returns first match.
        """
        cache_dir = tmp_path / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        index_file = cache_dir / "other-name.json"
        index_file.write_text("{}")

        result = script_gen_bench.resolve_index_path(None, tmp_path)
        assert result == index_file

    def test_returns_fallback_path_when_no_index_found(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns a constructed path (that may not exist) when no index found.

        Scenario: empty repo; no .cache/ directory; returns computed fallback.
        """
        result = script_gen_bench.resolve_index_path(None, tmp_path)
        # Must be a Path object under .cache/codemap/
        assert isinstance(result, Path)
        assert ".cache" in result.parts


# ===========================================================================
# run_scan_query
# ===========================================================================


class TestRunScanQuery:
    """Contract: subprocess wrapper returns parsed dict or None on failure."""

    def _make_proc(self, returncode: int, stdout: str, stderr: str = "") -> MagicMock:
        """Build a MagicMock simulating subprocess.CompletedProcess."""
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_returns_dict_on_success(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns parsed JSON dict when subprocess exits 0 with valid JSON.

        Scenario: happy path; scan-query returns well-formed JSON.
        """
        payload = {"symbols": [{"qualified_name": "Foo.bar"}]}
        proc = self._make_proc(0, json.dumps(payload))
        sq = tmp_path / "scan-query"
        index = tmp_path / "index.json"

        with patch("subprocess.run", return_value=proc):
            result = script_gen_bench.run_scan_query(sq, ["symbol", "Foo.bar"], index, tmp_path)

        assert result == payload

    def test_returns_none_on_nonzero_exit(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when subprocess exits non-zero.

        Scenario: scan-query fails (e.g., index not found); caller gets None.
        """
        proc = self._make_proc(1, "")
        sq = tmp_path / "scan-query"
        index = tmp_path / "index.json"

        with patch("subprocess.run", return_value=proc):
            result = script_gen_bench.run_scan_query(sq, ["symbol", "X"], index, tmp_path)

        assert result is None

    def test_returns_none_on_json_decode_error(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when subprocess output is not valid JSON.

        Scenario: scan-query prints human-readable error; JSON parse fails.
        """
        proc = self._make_proc(0, "not json output")
        sq = tmp_path / "scan-query"
        index = tmp_path / "index.json"

        with patch("subprocess.run", return_value=proc):
            result = script_gen_bench.run_scan_query(sq, ["symbol", "X"], index, tmp_path)

        assert result is None

    def test_returns_none_on_timeout(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when subprocess times out.

        Scenario: scan-query hangs; TimeoutExpired is caught and swallowed.
        """
        sq = tmp_path / "scan-query"
        index = tmp_path / "index.json"

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sq", timeout=30)):
            result = script_gen_bench.run_scan_query(sq, ["symbol", "X"], index, tmp_path)

        assert result is None

    def test_returns_none_on_os_error(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns None when the binary cannot be executed (OSError).

        Scenario: scan-query path does not exist or permissions denied.
        """
        sq = tmp_path / "scan-query"
        index = tmp_path / "index.json"

        with patch("subprocess.run", side_effect=OSError("no such file")):
            result = script_gen_bench.run_scan_query(sq, ["symbol", "X"], index, tmp_path)

        assert result is None


# ===========================================================================
# _validate_symbol
# ===========================================================================


class TestValidateSymbol:
    """Contract: symbol_extraction validator compares scan-query output to gt."""

    def _task(self, module: str, qualified_name: str, start: int, end: int) -> dict:
        """Build a minimal symbol_extraction task dict."""
        return {
            "type": "symbol_extraction",
            "ground_truth": {
                "module": module,
                "qualified_name": qualified_name,
                "start_line": start,
                "end_line": end,
            },
        }

    def _sq_response(self, symbols: list[dict]) -> dict:
        """Build a minimal scan-query symbol response."""
        return {"symbols": symbols}

    def test_passes_when_all_fields_match(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, live_gt, '') when scan-query result matches ground truth exactly.

        Scenario: symbol found with correct module, qname, start_line, end_line.
        """
        task = self._task("pkg.mod", "MyClass.method", 10, 20)
        payload = self._sq_response(
            [{"module": "pkg.mod", "qualified_name": "MyClass.method", "start_line": 10, "end_line": 20}]
        )

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert reason == ""
        assert live_gt["start_line"] == 10
        assert live_gt["end_line"] == 20

    def test_fails_when_start_line_differs(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, live_gt, reason) when start_line does not match ground truth.

        Scenario: index rebuilt after refactor shifted function up one line.
        """
        task = self._task("pkg.mod", "MyClass.method", 10, 20)
        payload = self._sq_response(
            [{"module": "pkg.mod", "qualified_name": "MyClass.method", "start_line": 99, "end_line": 20}]
        )

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "start_line" in reason

    def test_fails_when_symbol_not_found(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when symbol absent from scan-query results.

        Scenario: symbol renamed; query returns empty symbols list.
        """
        task = self._task("pkg.mod", "MissingFn", 1, 5)
        payload = self._sq_response([])

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None
        assert "not found" in reason

    def test_returns_none_on_scan_query_failure(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when scan-query returns None.

        Scenario: binary error; subprocess call failed.
        """
        task = self._task("pkg.mod", "MyClass.method", 1, 5)

        with patch.object(script_gen_bench, "run_scan_query", return_value=None):
            ok, live_gt, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None

    def test_widens_to_qname_match_when_module_differs(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Falls back to matching on qualified_name alone when module differs.

        Scenario: symbol moved to different module but qname preserved; doc
        says 'Widen to any symbol with the right qname'.
        """
        task = self._task("pkg.old_mod", "MyClass.method", 10, 20)
        # Returned symbol has same qname but different module
        payload = self._sq_response(
            [{"module": "pkg.new_mod", "qualified_name": "MyClass.method", "start_line": 10, "end_line": 20}]
        )

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        # Symbol IS found via widened match; line numbers match so ok=True
        assert live_gt is not None  # widened match succeeded

    @pytest.mark.parametrize(
        "gt_field,live_value,expected_problem",
        [
            ("start_line", 99, "start_line"),
            ("end_line", 99, "end_line"),
            # module mismatch: symbol is found via widened qname match but module field differs
            ("module", "wrong.mod", "module"),
        ],
    )
    def test_reports_specific_field_mismatch(
        self, script_gen_bench: Any, tmp_path: Path, gt_field: str, live_value: Any, expected_problem: str
    ) -> None:
        """Failure reason names the specific field that differs from ground truth.

        Scenario: each ground-truth field individually diverges; the symbol IS
        found (qname matches) but the stored field value differs from live; the
        reason message must identify the offending field by name.
        Note: qualified_name cannot be tested this way — if qname differs, the
        symbol is not found at all rather than producing a field-mismatch message.
        """
        base = {
            "module": "pkg.mod",
            "qualified_name": "Cls.fn",
            "start_line": 10,
            "end_line": 20,
        }
        task = {"type": "symbol_extraction", "ground_truth": dict(base)}

        live = dict(base)
        live[gt_field] = live_value

        payload = self._sq_response([live])

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_symbol(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert expected_problem in reason


# ===========================================================================
# _validate_fn
# ===========================================================================


class TestValidateFn:
    """Contract: fn_call_graph validator checks caller counts and sets."""

    def _task(
        self,
        primary_fn: str,
        callers: list[str],
        unique_count: int,
        raw_count: int,
        exclude_tests: bool = False,
    ) -> dict:
        """Build a minimal fn_call_graph task dict."""
        return {
            "type": "fn_call_graph",
            "primary_fn": primary_fn,
            "ground_truth": {
                "fn_callers": callers,
                "unique_caller_count": unique_count,
                "raw_caller_count": raw_count,
                "exclude_tests": exclude_tests,
            },
        }

    def _sq_response(self, callers: list[str], count: int | None = None) -> dict:
        """Build a minimal fn-rdeps scan-query response."""
        called_by = [{"caller": c} for c in callers]
        result: dict = {"called_by": called_by}
        if count is not None:
            result["count"] = count
        return result

    def _write_callers(self, repo: Path, callers: list[str], target: str) -> None:
        """Write Python files so the AST oracle discovers exactly ``callers`` of ``target``.

        Each caller string is ``<module>::<scope>`` where scope is ``func`` or ``Class.method``.
        A file at ``<module-as-path>.py`` is created whose scope body calls ``target()`` — the
        AST oracle then attributes that call to ``<module>::<scope>``.
        """
        for caller in callers:
            module, scope = caller.split("::")
            fpath = repo / (module.replace(".", "/") + ".py")
            fpath.parent.mkdir(parents=True, exist_ok=True)
            if "." in scope:
                cls, meth = scope.split(".", 1)
                src = f"class {cls}:\n    def {meth}(self):\n        {target}()\n"
            else:
                src = f"def {scope}():\n    {target}()\n"
            fpath.write_text(src)

    def test_passes_when_callers_match_exactly(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, live_gt, '') when the AST oracle's callers match ground truth.

        Scenario: unchanged codebase; the independent AST oracle (now authoritative) agrees
        with the stored caller set.
        """
        callers = ["mod.a::fn_a", "mod.b::fn_b"]
        task = self._task("mod::target", callers, 2, 2)
        payload = self._sq_response(callers, 2)
        self._write_callers(tmp_path, callers, "target")

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert reason == ""

    def test_fails_on_extra_caller(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when the AST oracle finds a caller not in ground truth.

        Scenario: new function added that calls target; GT is stale relative to the oracle.
        """
        gt_callers = ["mod.a::fn_a"]
        task = self._task("mod::target", gt_callers, 1, 1)
        oracle_callers = ["mod.a::fn_a", "mod.b::fn_b"]  # extra caller present in source
        payload = self._sq_response(oracle_callers, 2)
        self._write_callers(tmp_path, oracle_callers, "target")

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "extra" in reason

    def test_fails_on_missing_caller(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when a ground-truth caller is absent from the AST oracle.

        Scenario: caller refactored away; the oracle no longer sees it in source.
        """
        gt_callers = ["mod.a::fn_a", "mod.b::fn_b"]
        task = self._task("mod::target", gt_callers, 2, 2)
        oracle_callers = ["mod.a::fn_a"]  # missing mod.b::fn_b in source
        payload = self._sq_response(oracle_callers, 1)
        self._write_callers(tmp_path, oracle_callers, "target")

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "missing" in reason

    def test_fails_on_count_mismatch(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when unique_caller_count differs from ground truth.

        Scenario: count field diverges even if set comparison matches.
        """
        callers = ["mod.a::fn_a"]
        task = self._task("mod::target", callers, 99, 1)  # wrong expected unique_count
        payload = self._sq_response(callers, 1)

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "unique_caller_count" in reason

    def test_returns_none_when_scan_query_fails(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when scan-query call fails.

        Scenario: binary not available; subprocess returns None.
        """
        task = self._task("mod::fn", [], 0, 0)

        with patch.object(script_gen_bench, "run_scan_query", return_value=None):
            ok, live_gt, reason = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None

    def test_excludes_tests_flag_added_to_args(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Appends --exclude-tests flag when ground_truth.exclude_tests is True.

        Scenario: task configured to exclude test-file callers; flag must be
        forwarded to scan-query.
        """
        task = self._task("mod::fn", [], 0, 0, exclude_tests=True)

        captured_args: list[list] = []

        def fake_sq(sq: Any, args: list, index: Any, repo: Any) -> dict:
            captured_args.append(args)
            return {"called_by": [], "count": 0}

        with patch.object(script_gen_bench, "run_scan_query", side_effect=fake_sq):
            script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert captured_args, "run_scan_query must be called at least once"
        assert "--exclude-tests" in captured_args[0]

    def test_deduplicates_scan_callers_in_diagnostic(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Deduplicates repeated scan-query callers in the diagnostic scan_caller_count.

        Scenario: scan-query returns the same caller twice (raw > unique). The authoritative
        unique_caller_count comes from the AST oracle; the scan_caller_count diagnostic must
        still deduplicate the tool's output.
        """
        callers = ["mod.a::fn_a", "mod.a::fn_a"]  # duplicate scan output
        task = self._task("mod::target", ["mod.a::fn_a"], 1, 2)
        payload = self._sq_response(callers, 2)
        self._write_callers(tmp_path, ["mod.a::fn_a"], "target")

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, _ = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert live_gt["unique_caller_count"] == 1  # AST oracle (authoritative)
        assert live_gt["scan_caller_count"] == 1  # scan output deduplicated


# ===========================================================================
# _extract_rv_value
# ===========================================================================


class TestExtractRvValue:
    """Contract: correct value extracted per (cmd, match_type) combination."""

    @pytest.mark.parametrize(
        "cmd,data,expected",
        [
            ("rdeps", {"imported_by": ["a", "b", "c"]}, 3),
            ("rdeps", {"imported_by": []}, 0),
            ("fn-rdeps", {"count": 7, "called_by": []}, 7),
            ("fn-rdeps", {"called_by": [1, 2]}, 2),  # fallback len(called_by)
            ("undocumented", {"total": 12}, 12),
            ("uncovered", {"total": 5}, 5),
            ("unknown-cmd", {}, 0),
        ],
    )
    def test_integer_extract(self, script_gen_bench: Any, cmd: str, data: dict, expected: int) -> None:
        """Returns integer count from scan-query output for integer_extract match type.

        Scenario: each supported subcommand returns count from different keys;
        unknown cmd falls through to 0.
        """
        result = script_gen_bench._extract_rv_value(cmd, data, "integer_extract")
        assert result == expected

    @pytest.mark.parametrize(
        "cmd,data,count_hint,expected",
        [
            (
                "undocumented",
                {"undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}]},
                0,
                ["A", "B"],
            ),
            (
                "undocumented",
                {"undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}, {"qualified_name": "C"}]},
                2,
                ["A", "B"],  # truncated to count_hint
            ),
            (
                "uncovered",
                {"uncovered": [{"qualified_name": "X"}]},
                0,
                ["X"],
            ),
            (
                "unknown-cmd",
                {"anything": []},
                0,
                [],  # unknown cmd returns empty list for symbol_name_set
            ),
        ],
    )
    def test_symbol_name_set(
        self, script_gen_bench: Any, cmd: str, data: dict, count_hint: int, expected: list
    ) -> None:
        """Returns qualified_name list for symbol_name_set match type.

        Scenario: undocumented and uncovered commands return symbol names;
        count_hint truncates the list; unknown cmd returns empty.
        """
        result = script_gen_bench._extract_rv_value(cmd, data, "symbol_name_set", count_hint=count_hint)
        assert result == expected

    def test_entry_falls_back_to_name_key(self, script_gen_bench: Any) -> None:
        """Uses 'name' key when 'qualified_name' absent from entry dict.

        Scenario: some scan-query versions use 'name' instead of
        'qualified_name'; fallback must be used.
        """
        data = {"undocumented": [{"name": "fallback_fn"}]}
        result = script_gen_bench._extract_rv_value("undocumented", data, "symbol_name_set")
        assert result == ["fallback_fn"]


# ===========================================================================
# _validate_rv
# ===========================================================================


class TestValidateRv:
    """Contract: review_assistance validator checks sub-question ground truth."""

    def _task(self, sub_questions: list[dict], expected_queries: list[dict] | None = None) -> dict:
        """Build a minimal review_assistance task dict."""
        # Use explicit None sentinel so callers can pass [] to test the empty-query path.
        if expected_queries is None:
            expected_queries = [{"cmd": "fn-rdeps", "args": ["mod::fn"]}]
        return {
            "type": "review_assistance",
            "sub_questions": sub_questions,
            "expected_queries": expected_queries,
        }

    def test_passes_when_integer_count_matches(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, live_gt, '') when integer sub-question count matches GT.

        Scenario: fn-rdeps count matches stored expected count.
        """
        task = self._task([{"id": "sq1", "match": "integer_extract", "ground_truth": {"count": 3}}])
        payload = {"count": 3, "called_by": []}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert reason == ""

    def test_fails_when_integer_count_differs(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure reason naming sub-question id when count differs.

        Scenario: refactor changed call graph; count in GT now stale.
        """
        task = self._task([{"id": "sq1", "match": "integer_extract", "ground_truth": {"count": 10}}])
        payload = {"count": 7, "called_by": []}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "sq1" in reason

    def test_passes_when_symbol_set_matches(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, ...) when symbol_name_set sub-question matches GT.

        Scenario: undocumented symbols match stored ground truth exactly.
        """
        task = self._task(
            [{"id": "sq2", "match": "symbol_name_set", "ground_truth": {"symbols": ["A", "B"]}}],
            expected_queries=[{"cmd": "undocumented", "args": []}],
        )
        payload = {"undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}]}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True

    def test_fails_when_symbol_set_has_missing(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure describing missing symbols from expected set.

        Scenario: GT expects ['A','B'] but live returns only ['A'].
        """
        task = self._task(
            [{"id": "sq2", "match": "symbol_name_set", "ground_truth": {"symbols": ["A", "B"]}}],
            expected_queries=[{"cmd": "undocumented", "args": []}],
        )
        payload = {"undocumented": [{"qualified_name": "A"}]}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "missing" in reason

    def test_fails_when_expected_queries_empty(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when expected_queries list is empty.

        Scenario: malformed task; no query defined.
        """
        task = self._task([], expected_queries=[])

        ok, live_gt, reason = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None
        assert "expected_queries" in reason

    def test_returns_none_when_scan_query_fails(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when the scan-query call returns None.

        Scenario: binary failure; all sub-question checks are skipped.
        """
        task = self._task([{"id": "sq1", "match": "integer_extract", "ground_truth": {"count": 1}}])

        with patch.object(script_gen_bench, "run_scan_query", return_value=None):
            ok, live_gt, _ = script_gen_bench._validate_rv(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None


# ===========================================================================
# _validate_oss
# ===========================================================================


class TestValidateOss:
    """Contract: code_quality validator routes by gt['check'] field."""

    def _task_undocumented(self, count: int, syms: list[str]) -> dict:
        """Build a code_quality task with check='undocumented'."""
        return {
            "type": "code_quality",
            "expected_queries": [{"cmd": "undocumented", "args": []}],
            "ground_truth": {
                "check": "undocumented",
                "undocumented_count": count,
                "undocumented_symbols": syms,
            },
        }

    def _task_uncovered(self, count: int, syms: list[str]) -> dict:
        """Build a code_quality task with check='uncovered'."""
        return {
            "type": "code_quality",
            "expected_queries": [{"cmd": "uncovered", "args": []}],
            "ground_truth": {
                "check": "uncovered",
                "uncovered_count": count,
                "uncovered_symbols": syms,
            },
        }

    def _task_coupled(self, top_module: str, dep_count: int, internal: int) -> dict:
        """Build a code_quality task with check='coupled'."""
        return {
            "type": "code_quality",
            "expected_queries": [{"cmd": "coupled", "args": []}],
            "ground_truth": {
                "check": "coupled",
                "top_module": top_module,
                "top_dep_count": dep_count,
                "top_internal_dep_count": internal,
            },
        }

    def _task_xrefs(self, broken_count: int, targets: list[dict]) -> dict:
        """Build a code_quality task with check='xrefs_broken'."""
        return {
            "type": "code_quality",
            "expected_queries": [{"cmd": "xrefs", "args": []}],
            "ground_truth": {
                "check": "xrefs_broken",
                "broken_count": broken_count,
                "broken_targets": targets,
            },
        }

    def _write_undoc(self, repo: Path, names: list[str]) -> None:
        """Write a module whose public classes ``names`` all lack docstrings.

        The AST undocumented oracle (now authoritative) then reports exactly ``names`` as the
        undocumented public symbol set.
        """
        body = "\n\n".join(f"class {n}:\n    pass" for n in names) + "\n"
        (repo / "m.py").write_text(body)

    def test_undocumented_passes_on_match(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, ...) when the AST oracle's undocumented set matches GT.

        Scenario: check='undocumented'; the authoritative AST oracle agrees with stored GT.
        """
        task = self._task_undocumented(2, ["A", "B"])
        payload = {"total": 2, "undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}]}
        self._write_undoc(tmp_path, ["A", "B"])

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert reason == ""

    def test_undocumented_fails_on_count_mismatch(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when the AST oracle's undocumented count differs from GT.

        Scenario: symbols documented after GT was captured; the oracle now sees fewer.
        """
        task = self._task_undocumented(5, ["A", "B", "C", "D", "E"])
        payload = {
            "total": 3,
            "undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}, {"qualified_name": "C"}],
        }
        self._write_undoc(tmp_path, ["A", "B", "C"])

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "undocumented_count" in reason

    def _write_uncovered(self, repo: Path, uncovered: list[str], covered: list[str]) -> None:
        """Write a source module of public functions; a test file references only ``covered``.

        The AST uncovered oracle (now authoritative) then reports exactly ``uncovered`` — the public
        functions no test module calls.
        """
        body = "\n\n".join(f"def {n}():\n    pass" for n in [*uncovered, *covered]) + "\n"
        (repo / "m.py").write_text(body)
        tests = repo / "tests"
        tests.mkdir(exist_ok=True)
        calls = "\n".join(f"    {n}()" for n in covered) or "    pass"
        (tests / "test_m.py").write_text(f"def test_all():\n{calls}\n")

    def test_uncovered_passes_on_match(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, ...) when the AST oracle's uncovered set matches GT.

        Scenario: check='uncovered'; the authoritative AST test-reference oracle agrees with stored GT.
        """
        task = self._task_uncovered(1, ["orphan"])
        payload = {"total": 1, "uncovered": [{"qualified_name": "orphan"}]}
        self._write_uncovered(tmp_path, ["orphan"], ["used"])

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert reason == ""

    def test_uncovered_fails_on_symbol_mismatch(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when the AST oracle's uncovered set differs from GT.

        Scenario: check='uncovered'; a symbol GT expected as uncovered is actually referenced by a test.
        """
        task = self._task_uncovered(2, ["a", "b"])
        payload = {"total": 2, "uncovered": [{"qualified_name": "a"}, {"qualified_name": "c"}]}
        self._write_uncovered(tmp_path, ["a"], ["b"])  # only 'a' is uncovered; 'b' is test-referenced

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "uncovered" in reason

    def test_coupled_passes_on_match(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, ...) when top coupled module fields match GT.

        Scenario: check='coupled'; top entry matches GT top_module and counts.
        """
        task = self._task_coupled("my.module", 10, 5)
        payload = {"coupled": [{"name": "my.module", "dep_count": 10, "internal_dep_count": 5}]}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True

    def test_coupled_fails_on_top_module_mismatch(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when top coupled module name differs from GT.

        Scenario: codebase restructured; most-coupled module changed.
        """
        task = self._task_coupled("expected.module", 10, 5)
        payload = {"coupled": [{"name": "actual.module", "dep_count": 10, "internal_dep_count": 5}]}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "top_module" in reason

    def test_coupled_fails_when_empty_result(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when coupled list is empty.

        Scenario: scan-query coupled returns no results (unexpected).
        """
        task = self._task_coupled("mod", 1, 0)
        payload = {"coupled": []}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, live_gt, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "empty" in reason

    def test_xrefs_passes_on_match(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (True, ...) when broken cross-reference count and targets match GT.

        Scenario: check='xrefs_broken'; live broken refs match GT exactly.
        """
        targets = [{"target": "mod::Fn", "line": 42}]
        task = self._task_xrefs(1, targets)
        payload = {"broken": [{"target": "mod::Fn", "line": 42}], "count": 1}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True

    def test_xrefs_fails_on_broken_count_mismatch(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns failure when broken_count differs from GT.

        Scenario: additional broken reference introduced; count changed.
        """
        task = self._task_xrefs(1, [{"target": "mod::Fn", "line": 10}])
        payload = {"broken": [{"target": "mod::Fn", "line": 10}, {"target": "other::X", "line": 5}], "count": 2}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert "broken_count" in reason

    def test_fails_when_no_expected_queries(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) for check='undocumented' with no queries.

        Scenario: malformed task; expected_queries list absent.
        """
        task = {
            "type": "code_quality",
            "expected_queries": [],
            "ground_truth": {"check": "undocumented", "undocumented_count": 0, "undocumented_symbols": []},
        }

        ok, live_gt, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None

    def test_scan_query_failure_returns_none(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns (False, None, reason) when scan-query call returns None.

        Scenario: binary error on any check type; cascade to failure.
        """
        task = self._task_undocumented(0, [])

        with patch.object(script_gen_bench, "run_scan_query", return_value=None):
            ok, live_gt, _ = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is False
        assert live_gt is None

    def test_combined_health_validates_both_counts(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Validates both undocumented and uncovered fields for combined_health check.

        Scenario: check='combined_health'; both sub-checks must match GT;
        single count mismatch causes overall failure.
        """
        task = {
            "type": "code_quality",
            "expected_queries": [
                {"cmd": "undocumented", "args": []},
                {"cmd": "uncovered", "args": []},
            ],
            "ground_truth": {
                "check": "combined_health",
                "undocumented_count": 2,
                "undocumented_symbols": ["A", "B"],
                "uncovered_count": 1,
                "uncovered_symbols": ["C"],
            },
        }
        undoc_payload = {"total": 2, "undocumented": [{"qualified_name": "A"}, {"qualified_name": "B"}]}
        uncov_payload = {"total": 1, "uncovered": [{"qualified_name": "C"}]}

        call_counter = {"n": 0}

        def sq_side_effect(sq: Any, args: list, index: Any, repo: Any) -> dict:
            call_counter["n"] += 1
            if args[0] == "undocumented":
                return undoc_payload
            if args[0] == "uncovered":
                return uncov_payload
            return None  # type: ignore[return-value]

        with patch.object(script_gen_bench, "run_scan_query", side_effect=sq_side_effect):
            ok, _, reason = script_gen_bench._validate_oss(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert ok is True
        assert call_counter["n"] == 2  # both queries fired


# ===========================================================================
# _build_updated_ground_truth
# ===========================================================================


class TestBuildUpdatedGroundTruth:
    """Contract: merge live GT into existing GT correctly per task type."""

    @pytest.mark.parametrize(
        "task_type",
        ["symbol_extraction", "fn_call_graph", "develop_blast_radius", "code_quality"],
    )
    def test_merges_live_into_existing(self, script_gen_bench: Any, task_type: str) -> None:
        """Returns merged dict with live values overriding existing for standard types.

        Scenario: validator computed live_gt; _build must integrate it into
        existing GT while preserving unrelated fields.
        """
        existing = {"preserved_field": "keep", "start_line": 99}
        live = {"start_line": 10, "end_line": 20}
        result = script_gen_bench._build_updated_ground_truth(task_type, live, existing)
        assert result["start_line"] == 10  # live overrides
        assert result["preserved_field"] == "keep"  # existing preserved

    def test_review_assistance_returns_live_gt_only(self, script_gen_bench: Any) -> None:
        """Returns live_gt unchanged for review_assistance (no merge with existing).

        Scenario: review_assistance stores per-sub_question entries; live_gt is
        the authoritative new structure; existing GT is discarded.
        """
        existing = {"old_key": "old_value"}
        live = {"sq1": {"count": 5}}
        result = script_gen_bench._build_updated_ground_truth("review_assistance", live, existing)
        assert result == live
        assert "old_key" not in result

    def test_unknown_type_returns_existing(self, script_gen_bench: Any) -> None:
        """Returns existing GT unchanged for unknown task types.

        Scenario: new task type not yet handled; existing GT must be preserved.
        """
        existing = {"some": "data"}
        live = {"new": "data"}
        result = script_gen_bench._build_updated_ground_truth("unknown_type", live, existing)
        assert result == existing


# ===========================================================================
# VALIDATORS routing dict
# ===========================================================================


class TestValidatorsDict:
    """Contract: VALIDATORS maps each documented task type to the right function."""

    @pytest.mark.parametrize(
        "task_type,expected_fn_name",
        [
            ("symbol_extraction", "_validate_symbol"),
            ("fn_call_graph", "_validate_fn"),
            ("develop_blast_radius", "_validate_fn"),
            ("review_assistance", "_validate_rv"),
            ("code_quality", "_validate_oss"),
        ],
    )
    def test_task_type_routes_to_correct_validator(
        self, script_gen_bench: Any, task_type: str, expected_fn_name: str
    ) -> None:
        """Each task type key maps to its documented validator function.

        Scenario: main() looks up VALIDATORS[task_type]; mapping must be
        correct for all five documented task types.
        """
        actual_fn = script_gen_bench.VALIDATORS.get(task_type)
        expected_fn = getattr(script_gen_bench, expected_fn_name)
        assert actual_fn is expected_fn

    def test_unknown_type_returns_none(self, script_gen_bench: Any) -> None:
        """VALIDATORS.get returns None for an unrecognised task type.

        Scenario: main() skips tasks with unknown type; VALIDATORS.get(type)
        must return None without raising.
        """
        assert script_gen_bench.VALIDATORS.get("nonexistent_type") is None


# ===========================================================================
# _CallerFinder / _callers_via_ast
# ===========================================================================


class TestCallFinderAst:
    """Contract: _CallFinder records enclosing scope of matching call sites."""

    def _parse_and_visit(self, script_gen_bench: Any, source: str, simple_name: str, rel_module: str) -> set:
        """Helper: parse source, run _CallFinder, return caller set."""
        callers: set = set()
        tree = ast.parse(source)
        script_gen_bench._CallFinder(simple_name, rel_module, callers).visit(tree)
        return callers

    def test_finds_direct_call(self, script_gen_bench: Any) -> None:
        """Records module::function when function directly calls the target.

        Scenario: simple function calling target by name.
        """
        source = "def caller():\n    target()\n"
        callers = self._parse_and_visit(script_gen_bench, source, "target", "mod")
        assert "mod::caller" in callers

    def test_finds_attribute_call(self, script_gen_bench: Any) -> None:
        """Records caller when target is called as attribute (obj.target()).

        Scenario: method call via attribute access; dot-call form.
        """
        source = "def caller():\n    obj.target()\n"
        callers = self._parse_and_visit(script_gen_bench, source, "target", "mod")
        assert "mod::caller" in callers

    def test_does_not_record_module_level_call(self, script_gen_bench: Any) -> None:
        """Does not record call at module level (no enclosing scope stack).

        Scenario: call outside any function/class is ignored per _scope_stack
        guard (``if matched and self._scope_stack``).
        """
        source = "target()\n"
        callers = self._parse_and_visit(script_gen_bench, source, "target", "mod")
        assert callers == set()

    def test_nested_class_method(self, script_gen_bench: Any) -> None:
        """Records nested class method as Module::Class.method scope string.

        Scenario: call inside a method; scope stack includes class and method.
        """
        source = "class MyClass:\n    def my_method(self):\n        target()\n"
        callers = self._parse_and_visit(script_gen_bench, source, "target", "mod")
        assert "mod::MyClass.my_method" in callers

    def test_does_not_match_different_name(self, script_gen_bench: Any) -> None:
        """Does not record callers of functions with different names.

        Scenario: false-positive guard; only exact simple name matches.
        """
        source = "def caller():\n    other_fn()\n"
        callers = self._parse_and_visit(script_gen_bench, source, "target", "mod")
        assert callers == set()

    def test_callers_via_ast_empty_repo(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Returns empty caller set for repo with no Python files.

        Scenario: fresh empty repository; AST walker finds nothing.
        """
        callers, err = script_gen_bench._callers_via_ast("mod::target", tmp_path)
        assert callers == set()
        assert err is None

    def test_callers_via_ast_finds_caller_in_py_file(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Finds callers from Python files in the repo tree.

        Scenario: single Python file with a caller; walker returns that caller.
        """
        (tmp_path / "example.py").write_text("def do_thing():\n    target()\n")
        callers, err = script_gen_bench._callers_via_ast("mod::target", tmp_path)
        assert "example::do_thing" in callers
        assert err is None

    def test_callers_via_ast_skips_venv_dir(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Skips .venv directory when walking the repo.

        Scenario: virtualenv present; must not traverse into it.
        """
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "pkg.py").write_text("def hidden():\n    target()\n")

        (tmp_path / "real.py").write_text("# no calls here\n")
        callers, _ = script_gen_bench._callers_via_ast("mod::target", tmp_path)
        assert all(".venv" not in c for c in callers)

    def test_callers_via_ast_handles_syntax_error_gracefully(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Skips files with syntax errors without raising.

        Scenario: malformed Python file in repo; walker must continue.
        """
        (tmp_path / "broken.py").write_text("def bad syntax !!!\n")
        (tmp_path / "good.py").write_text("def ok():\n    target()\n")
        callers, err = script_gen_bench._callers_via_ast("any::target", tmp_path)
        # good.py must still be processed
        assert "good::ok" in callers


# ===========================================================================
# _QualifiedCallFinder / _walk_caller_sets (review N1)
# ===========================================================================


class TestQualifiedCallerOracle:
    """Contract: authoritative caller set resolves receivers; loose set over-approximates (N1)."""

    def test_same_named_method_in_unrelated_class_not_credited(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A `self.bar()` call in an unrelated class is NOT credited as a caller of Foo.bar.

        Scenario: two classes define a `bar` method call; only the one whose enclosing class is the
        target class resolves. The loose (simple-name) set still contains both — kept as diagnostic.
        """
        src = (
            "class Foo:\n    def caller(self):\n        self.bar()\n\n"
            "class Baz:\n    def other(self):\n        self.bar()\n"
        )
        (tmp_path / "m.py").write_text(src)
        qualified, loose, err = script_gen_bench._walk_caller_sets("m::Foo.bar", tmp_path)
        assert err is None
        assert qualified == {"m::Foo.caller"}
        assert "m::Baz.other" in loose

    def test_direct_class_instantiation_credited(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A `Foo().bar()` reference resolves to the target class and is credited.

        Scenario: a free function instantiates the class and calls the method directly.
        """
        (tmp_path / "m.py").write_text("def use():\n    Foo().bar()\n")
        qualified, _loose, _ = script_gen_bench._walk_caller_sets("m::Foo.bar", tmp_path)
        assert qualified == {"m::use"}

    def test_module_function_attribute_call_uses_target_module(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A cross-module `foo.func()` is credited only when `foo` is the TARGET module, not the caller.

        Scenario (N1 challenger fix): the module-level-function branch compares the receiver tail
        against the target module (`pkg.foo`), never the caller file's own module — so `foo.func()`
        from pkg.bar IS credited while a same-named `bar.func()` is NOT.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "foo.py").write_text("def func():\n    pass\n")
        (pkg / "bar.py").write_text("def use_target():\n    foo.func()\n\n\ndef use_other():\n    bar.func()\n")
        qualified, _loose, _ = script_gen_bench._walk_caller_sets("pkg.foo::func", tmp_path)
        assert qualified == {"pkg.bar::use_target"}

    def test_emitted_module_paths_carry_no_src_prefix(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A caller under a `src/` layout is emitted in the repo namespace, not with a `src.` prefix.

        Scenario: `--update` on a real src-layout clone must write GT in the repo's real namespace.
        """
        f = tmp_path / "src" / "pkg" / "mod.py"
        f.parent.mkdir(parents=True)
        f.write_text("def caller():\n    target()\n")
        qualified, _loose, _ = script_gen_bench._walk_caller_sets("pkg::target", tmp_path)
        assert qualified == {"pkg.mod::caller"}
        assert all(not c.startswith("src.") for c in qualified)

    def test_test_modules_excluded_from_callers(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Callers inside a `tests/` directory are excluded from the emitted namespace.

        Scenario: a test file calls the target; only the production caller is credited.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_mod.py").write_text("def test_x():\n    target()\n")
        (tmp_path / "prod.py").write_text("def caller():\n    target()\n")
        qualified, _loose, _ = script_gen_bench._walk_caller_sets("mod::target", tmp_path)
        assert qualified == {"prod::caller"}
        assert all("test" not in c for c in qualified)

    def test_src_and_flat_layouts_emit_repo_namespaces(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A repo mixing src-layout and flat-layout packages emits each in its repo namespace (no `src.`).

        Scenario (parity): `src/pkg/sub/mod.py` (full __init__ chain under src/) and `flatpkg/mod.py`
        (flat __init__) both call the module-level target; the src caller must be credited as
        `pkg.sub.mod::src_caller` (structurally stripping the `src/` prefix) and the flat caller as
        `flatpkg.mod::flat_caller` — matching what scan-query/scan-index emit for the same clone.
        """
        src_mod = tmp_path / "src" / "pkg" / "sub" / "mod.py"
        src_mod.parent.mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "__init__.py").write_text("")
        (tmp_path / "src" / "pkg" / "sub" / "__init__.py").write_text("")
        src_mod.write_text("def src_caller():\n    target()\n")
        flat_mod = tmp_path / "flatpkg" / "mod.py"
        flat_mod.parent.mkdir(parents=True)
        (tmp_path / "flatpkg" / "__init__.py").write_text("")
        flat_mod.write_text("def flat_caller():\n    target()\n")

        qualified, _loose, _ = script_gen_bench._walk_caller_sets("pkg.sub.mod::target", tmp_path)

        assert qualified == {"pkg.sub.mod::src_caller", "flatpkg.mod::flat_caller"}
        assert all(not c.startswith("src.") for c in qualified)


# ===========================================================================
# main() unit + error paths
# ===========================================================================


class TestIsPublicQualname:
    """Contract: public qualified name = no dotted component starts with underscore (C-2)."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Trainer.fit", True),
            ("func", True),
            ("_helper", False),
            ("_Cache.get", False),
            ("Trainer.__init__", False),
            ("", False),
        ],
    )
    def test_public_rule(self, script_gen_bench: Any, name: str, expected: bool) -> None:
        """Mirrors scan-query _is_public_symbol: any leading-underscore component is private."""
        assert script_gen_bench._is_public_qualname(name) is expected


class TestUndocumentedViaAst:
    """Contract: independent AST oracle lists public symbols lacking a docstring (C-2)."""

    def test_finds_public_undocumented(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Public class/function without a docstring is reported."""
        (tmp_path / "m.py").write_text("class A:\n    pass\n\n\ndef pub():\n    pass\n")
        syms, err = script_gen_bench._undocumented_via_ast(tmp_path)
        assert err is None
        assert syms == {"A", "pub"}

    def test_documented_symbol_excluded(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A symbol with a docstring is not reported as undocumented."""
        (tmp_path / "m.py").write_text('def pub():\n    """Doc."""\n    return 1\n')
        syms, _ = script_gen_bench._undocumented_via_ast(tmp_path)
        assert "pub" not in syms

    def test_private_symbol_excluded(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Private (leading-underscore) symbols are excluded even without a docstring."""
        (tmp_path / "m.py").write_text("def _helper():\n    pass\n")
        syms, _ = script_gen_bench._undocumented_via_ast(tmp_path)
        assert syms == set()

    def test_nested_method_qualified_name(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Methods are reported as Class.method module-relative qualified names."""
        (tmp_path / "m.py").write_text("class Cls:\n    def meth(self):\n        pass\n")
        syms, _ = script_gen_bench._undocumented_via_ast(tmp_path)
        assert "Cls.meth" in syms

    def test_test_modules_skipped(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Files named test_*.py are skipped (scan-query skips test modules)."""
        (tmp_path / "test_x.py").write_text("def pub():\n    pass\n")
        syms, _ = script_gen_bench._undocumented_via_ast(tmp_path)
        assert syms == set()

    def test_module_filter_unresolvable_returns_error(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A module name that maps to no file yields an error reason, empty set."""
        syms, err = script_gen_bench._undocumented_via_ast(tmp_path, module="pkg.missing")
        assert syms == set()
        assert err is not None and "not resolvable" in err

    def test_module_filter_resolves_src_layout(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A dotted module resolves against <repo>/src/<parts>.py."""
        f = tmp_path / "src" / "pkg" / "mod.py"
        f.parent.mkdir(parents=True)
        f.write_text("def pub():\n    pass\n")
        syms, err = script_gen_bench._undocumented_via_ast(tmp_path, module="pkg.mod")
        assert err is None
        assert syms == {"pub"}


class TestUncoveredViaAst:
    """Contract: independent AST oracle lists public symbols no test references (C-2 remainder)."""

    def test_symbol_with_no_test_reference_is_uncovered(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A public symbol that no test file calls is reported as uncovered."""
        (tmp_path / "m.py").write_text("def orphan():\n    pass\n")
        syms, err = script_gen_bench._uncovered_via_ast(tmp_path)
        assert err is None
        assert syms == {"orphan"}

    def test_test_called_symbol_is_covered(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A public symbol a test file calls is NOT reported as uncovered."""
        (tmp_path / "m.py").write_text("def used():\n    pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_m.py").write_text("def test_it():\n    used()\n")
        syms, _ = script_gen_bench._uncovered_via_ast(tmp_path)
        assert "used" not in syms

    def test_mock_patched_symbol_is_covered(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A symbol referenced only through a patch() string target counts as covered."""
        (tmp_path / "m.py").write_text("def mocked():\n    pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_m.py").write_text(
            "from unittest.mock import patch\n\n\n@patch('m.mocked')\ndef test_it():\n    pass\n"
        )
        syms, _ = script_gen_bench._uncovered_via_ast(tmp_path)
        assert "mocked" not in syms

    def test_private_symbol_excluded(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Private (leading-underscore) symbols are never reported (scan-query public-only rule)."""
        (tmp_path / "m.py").write_text("def _helper():\n    pass\n")
        syms, _ = script_gen_bench._uncovered_via_ast(tmp_path)
        assert syms == set()

    def test_nested_method_qualified_name(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """Uncovered methods are reported as module-relative Class.method qualified names."""
        (tmp_path / "m.py").write_text("class Cls:\n    def orphan(self):\n        pass\n")
        syms, _ = script_gen_bench._uncovered_via_ast(tmp_path)
        assert "Cls.orphan" in syms

    def test_module_filter_scopes_scan(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """A module filter restricts the source scan to that module."""
        f = tmp_path / "src" / "pkg" / "mod.py"
        f.parent.mkdir(parents=True)
        f.write_text("def solo():\n    pass\n")
        syms, err = script_gen_bench._uncovered_via_ast(tmp_path, module="pkg.mod")
        assert err is None
        assert syms == {"solo"}


class TestValidateFnAstAuthoritative:
    """Contract: _validate_fn treats the AST oracle as authoritative, scan as diagnostic (C-2)."""

    def _task(self, primary_fn: str, callers: list[str]) -> dict:
        """Build an fn_call_graph task with the given expected callers."""
        return {
            "type": "fn_call_graph",
            "primary_fn": primary_fn,
            "ground_truth": {"fn_callers": callers, "unique_caller_count": len(callers), "raw_caller_count": 0},
        }

    def test_scan_output_stored_as_diagnostic(self, script_gen_bench: Any, tmp_path: Path) -> None:
        """scan-query callers are preserved under fn_callers_scan, not as the authoritative set."""
        (tmp_path / "mod" / "a.py").parent.mkdir(parents=True)
        (tmp_path / "mod" / "a.py").write_text("def fn_a():\n    target()\n")
        task = self._task("mod::target", ["mod.a::fn_a"])
        payload = {"called_by": [{"caller": "other::ghost"}], "count": 1}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            _, live_gt, _ = script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        assert live_gt["fn_callers"] == ["mod.a::fn_a"]  # AST oracle authoritative
        assert live_gt["fn_callers_scan"] == ["other::ghost"]  # scan diagnostic
        assert live_gt["ast_divergence"]["scan_only"] == ["other::ghost"]
        assert live_gt["ast_divergence"]["ast_only"] == ["mod.a::fn_a"]

    def test_divergence_warning_printed(self, script_gen_bench: Any, tmp_path: Path, capsys: Any) -> None:
        """A loud divergence banner is printed when AST and scan disagree."""
        task = self._task("mod::target", [])
        payload = {"called_by": [{"caller": "other::ghost"}], "count": 1}

        with patch.object(script_gen_bench, "run_scan_query", return_value=payload):
            script_gen_bench._validate_fn(task, MagicMock(), tmp_path / "idx.json", tmp_path)

        out = capsys.readouterr().out
        assert "DIVERGENCE" in out


class TestUpdateGating:
    """Contract: circular (scan-derived) refresh is gated behind --update-from-tool (C-3)."""

    @pytest.mark.parametrize(
        "task,expected",
        [
            ({"type": "fn_call_graph"}, True),
            ({"type": "develop_blast_radius"}, True),
            ({"type": "code_quality", "ground_truth": {"check": "undocumented"}}, True),
            ({"type": "code_quality", "ground_truth": {"check": "uncovered"}}, True),
            ({"type": "code_quality", "ground_truth": {"check": "xrefs_broken"}}, False),
            ({"type": "code_quality", "ground_truth": {"check": "coupled"}}, False),
            ({"type": "review_assistance"}, False),
            ({"type": "symbol_extraction"}, False),
        ],
    )
    def test_oracle_backed_classification(self, script_gen_bench: Any, task: dict, expected: bool) -> None:
        """Only AST-oracle-backed types are safe to refresh under a plain --update."""
        assert script_gen_bench._update_is_oracle_backed(task) is expected

    def test_oracle_backed_type_refreshes_by_default(self, script_gen_bench: Any) -> None:
        """An fn_call_graph task refreshes under plain --update (update_from_tool=False)."""
        task = {"type": "fn_call_graph", "ground_truth": {"fn_callers": []}}
        live = {"fn_callers": ["m::a"], "unique_caller_count": 1}
        stored, status = script_gen_bench._refresh_task_gt(task, live, update_from_tool=False)
        assert status == "UPDATED"
        assert stored["ground_truth"]["fn_callers"] == ["m::a"]

    def test_tool_derived_type_skipped_without_flag(self, script_gen_bench: Any) -> None:
        """A scan-derived task (coupled) is NOT refreshed under plain --update; original preserved."""
        task = {"type": "code_quality", "ground_truth": {"check": "coupled", "top_dep_count": 1}}
        live = {"check": "coupled", "top_dep_count": 99}
        stored, status = script_gen_bench._refresh_task_gt(task, live, update_from_tool=False)
        assert "SKIP UPDATE" in status
        assert stored["ground_truth"]["top_dep_count"] == 1  # unchanged

    def test_tool_derived_type_refreshes_with_flag_and_warns(self, script_gen_bench: Any, capsys: Any) -> None:
        """--update-from-tool refreshes scan-derived (coupled) GT after a loud circularity warning."""
        task = {"type": "code_quality", "ground_truth": {"check": "coupled", "top_dep_count": 1}}
        live = {"check": "coupled", "top_dep_count": 99}
        stored, status = script_gen_bench._refresh_task_gt(task, live, update_from_tool=True)
        assert status == "UPDATED"
        assert stored["ground_truth"]["top_dep_count"] == 99
        assert "CIRCULAR UPDATE" in capsys.readouterr().out

    def test_review_assistance_merges_sub_questions_with_flag(self, script_gen_bench: Any) -> None:
        """review_assistance refresh (tool-derived) merges per-sub_question GT under the flag."""
        task = {
            "type": "review_assistance",
            "sub_questions": [{"id": "sq1", "ground_truth": {"count": 1}}],
        }
        live = {"sq1": {"count": 5}}
        stored, status = script_gen_bench._refresh_task_gt(task, live, update_from_tool=True)
        assert status == "UPDATED"
        assert stored["sub_questions"][0]["ground_truth"] == {"count": 5}


class TestMainUnitBehavior:
    """Unit-level tests for main() error paths using mocked dependencies."""

    def test_main_exits_when_tasks_file_unreadable(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() prints error and calls sys.exit(1) when TASKS_FILE missing.

        Scenario: tasks-bench.json deleted; main must exit with code 1.
        """
        broken_path = tmp_path / "nonexistent.json"
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", broken_path)

        with pytest.raises(SystemExit) as exc_info:
            script_gen_bench.main(repo_path=str(tmp_path))
        assert exc_info.value.code == 1

    def test_main_exits_when_no_repo_path(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """main() exits 1 when no --repo-path and no default_path in tasks file.

        Scenario: tasks file has no repo.default_path; user forgot --repo-path.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({"repo": {}, "tasks": []}))
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        with pytest.raises(SystemExit) as exc_info:
            script_gen_bench.main()  # no repo_path
        assert exc_info.value.code == 1

    def test_main_exits_when_repo_path_not_dir(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() exits 1 when --repo-path exists but is a file, not a directory.

        Scenario: user passes a file path by mistake.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({"repo": {}, "tasks": []}))
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        file_path = tmp_path / "notadir.txt"
        file_path.write_text("content")

        with pytest.raises(SystemExit) as exc_info:
            script_gen_bench.main(repo_path=str(file_path))
        assert exc_info.value.code == 1

    def test_main_exits_when_scan_query_not_found(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() exits 1 when scan-query binary cannot be found.

        Scenario: no binary on PATH and no plugin directory fallback.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({"repo": {}, "tasks": []}))
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        with patch.object(script_gen_bench, "find_codemap_bin", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                script_gen_bench.main(repo_path=str(tmp_path))
        assert exc_info.value.code == 1

    def test_main_exits_when_index_not_found(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() exits 1 when resolved index path does not exist.

        Scenario: scan-query found but codemap index JSON missing.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({"repo": {}, "tasks": []}))
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        fake_sq = tmp_path / "scan-query"
        fake_sq.write_text("#!/bin/sh")
        nonexistent_index = tmp_path / "missing.json"

        with (
            patch.object(script_gen_bench, "find_codemap_bin", return_value=fake_sq),
            patch.object(script_gen_bench, "resolve_index_path", return_value=nonexistent_index),
        ):
            with pytest.raises(SystemExit) as exc_info:
                script_gen_bench.main(repo_path=str(tmp_path))
        assert exc_info.value.code == 1

    def test_main_skips_unknown_task_type(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """main() prints SKIP for tasks with an unrecognised type field.

        Scenario: task list contains a type not in VALIDATORS; main continues
        rather than crashing.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(
            json.dumps(
                {
                    "repo": {},
                    "tasks": [{"id": "X-01", "type": "unknown_type", "ground_truth": {}}],
                }
            )
        )
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        fake_sq = tmp_path / "scan-query"
        fake_sq.write_text("#!/bin/sh")
        fake_index = tmp_path / "index.json"
        fake_index.write_text("{}")

        with (
            patch.object(script_gen_bench, "find_codemap_bin", return_value=fake_sq),
            patch.object(script_gen_bench, "resolve_index_path", return_value=fake_index),
        ):
            # Should not raise or exit 1 for unknown type alone
            script_gen_bench.main(repo_path=str(tmp_path))

        out = capsys.readouterr().out
        assert "SKIP" in out
        assert "X-01" in out

    def test_main_filters_by_task_id(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() runs only the task matching --task <id> when filter supplied.

        Scenario: user passes --task SE-01; only that task is validated.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(
            json.dumps(
                {
                    "repo": {},
                    "tasks": [
                        {"id": "SE-01", "type": "unknown_type", "ground_truth": {}},
                        {"id": "SE-02", "type": "unknown_type", "ground_truth": {}},
                    ],
                }
            )
        )
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        fake_sq = tmp_path / "scan-query"
        fake_sq.write_text("#!/bin/sh")
        fake_index = tmp_path / "index.json"
        fake_index.write_text("{}")

        processed_ids: list[str] = []

        def tracking_validator(task: dict, sq: Any, index: Any, repo: Any) -> tuple:
            processed_ids.append(task["id"])
            return True, {}, ""

        with (
            patch.object(script_gen_bench, "find_codemap_bin", return_value=fake_sq),
            patch.object(script_gen_bench, "resolve_index_path", return_value=fake_index),
            patch.object(script_gen_bench, "VALIDATORS", {"unknown_type": tracking_validator}),
        ):
            script_gen_bench.main(repo_path=str(tmp_path), task="SE-01")

        assert processed_ids == ["SE-01"]

    def test_main_exits_when_task_id_not_found(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() exits 1 when --task <id> does not match any task in file.

        Scenario: user passes a non-existent task ID.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(
            json.dumps(
                {
                    "repo": {},
                    "tasks": [{"id": "SE-01", "type": "symbol_extraction", "ground_truth": {}}],
                }
            )
        )
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        fake_sq = tmp_path / "scan-query"
        fake_sq.write_text("#!/bin/sh")
        fake_index = tmp_path / "index.json"
        fake_index.write_text("{}")

        with (
            patch.object(script_gen_bench, "find_codemap_bin", return_value=fake_sq),
            patch.object(script_gen_bench, "resolve_index_path", return_value=fake_index),
        ):
            with pytest.raises(SystemExit) as exc_info:
                script_gen_bench.main(repo_path=str(tmp_path), task="NO-SUCH")
        assert exc_info.value.code == 1

    def test_main_full_file_update_writes_back(
        self, script_gen_bench: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Regression: full-file --update (no --task) processes every task and writes GT back.

        The loop variable must not shadow the ``task`` filter parameter; if it did, the
        write-back guard ``if task is None`` would never fire and the file would never be
        written despite --update.
        """
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(
            json.dumps(
                {
                    "repo": {},
                    "tasks": [
                        {"id": "A-01", "type": "t", "ground_truth": {}},
                        {"id": "A-02", "type": "t", "ground_truth": {}},
                    ],
                }
            )
        )
        monkeypatch.setattr(script_gen_bench, "TASKS_FILE", tasks_file)

        fake_sq = tmp_path / "scan-query"
        fake_sq.write_text("#!/bin/sh")
        fake_index = tmp_path / "index.json"
        fake_index.write_text("{}")

        processed: list[str] = []

        def tracking_validator(task: dict, sq: Any, index: Any, repo: Any) -> tuple:
            processed.append(task["id"])
            return True, {}, ""

        with (
            patch.object(script_gen_bench, "find_codemap_bin", return_value=fake_sq),
            patch.object(script_gen_bench, "resolve_index_path", return_value=fake_index),
            patch.object(script_gen_bench, "VALIDATORS", {"t": tracking_validator}),
        ):
            script_gen_bench.main(repo_path=str(tmp_path), update=True)

        assert processed == ["A-01", "A-02"]  # loop iterated all tasks
        assert "Wrote updated ground truth" in capsys.readouterr().out  # write-back guard fired
