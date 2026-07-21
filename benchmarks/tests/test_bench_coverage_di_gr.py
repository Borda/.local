"""Tests for the diff-impact (DI) and graph (GR) benchmark coverage extension.

Covers:
  - Task schema for the new DI/GR series in tasks-bench.json.
  - Generator validators / oracles for diff_impact, graph_central, graph_path, graph_fn_blast
    on tiny fixture repos (deterministic AST — no scan-query, no LLM).
  - DiffImpactStager stage/revert safety, including dirty-tree refusal.
  - Batch counter parsing + used_batch field.
  - The new runner evaluators (caller recall, set overlap, ordered path, transitive recall).

No LLM calls, no benchmark execution — every test is pure AST / regex / git-porcelain.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SUITE = Path(__file__).resolve().parent.parent / "suites" / "tasks-bench.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    """A tiny 3-module repo + one test module for oracle unit tests.

    Graph: c imports b imports a; b.caller calls a.target; tests/test_a.py imports+calls a.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def target():\n    pass\n")
    (repo / "b.py").write_text("import a\n\n\ndef caller():\n    a.target()\n")
    (repo / "c.py").write_text("import b\n")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_a.py").write_text("import a\n\n\ndef test_it():\n    a.target()\n")
    return repo


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A committed git repo with one source file, for stage/revert tests."""
    repo = tmp_path / "gitrepo"
    repo.mkdir()
    (repo / "src.py").write_text("def widely_used():\n    return 1\n")
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.t"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "src.py"],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# Task schema
# ---------------------------------------------------------------------------


class TestDiGrTaskSchema:
    """Schema invariants for the new DI/GR tasks in tasks-bench.json."""

    @pytest.fixture(scope="class")
    @staticmethod
    def tasks() -> list[dict]:
        return json.loads(SUITE.read_text())["tasks"]

    def test_suite_is_valid_json_object(self) -> None:
        """tasks-bench.json is an object with repo header + tasks list."""
        data = json.loads(SUITE.read_text())
        assert set(data) >= {"repo", "tasks"}
        assert isinstance(data["tasks"], list)

    def test_has_six_di_tasks(self, tasks: list[dict]) -> None:
        di = [t for t in tasks if t["id"].startswith("DI-")]
        assert len(di) == 6
        assert all(t["type"] == "diff_impact" for t in di)

    def test_has_four_gr_tasks(self, tasks: list[dict]) -> None:
        gr = [t for t in tasks if t["id"].startswith("GR-")]
        assert len(gr) == 4
        assert {t["type"] for t in gr} == {"graph_central", "graph_path", "graph_fn_blast"}

    def test_di_tasks_have_stage_spec_and_primary_fn(self, tasks: list[dict]) -> None:
        for t in (t for t in tasks if t["id"].startswith("DI-")):
            assert "::" in t["primary_fn"], t["id"]
            assert isinstance(t.get("stage"), list) and t["stage"], t["id"]
            for edit in t["stage"]:
                assert edit.get("file"), t["id"]
                assert ("append" in edit) or ("find" in edit and "replace" in edit), t["id"]

    def test_new_tasks_are_gt_pending(self, tasks: list[dict]) -> None:
        """Target repo is absent at authoring time — every new task ships gt_pending=true."""
        new = [t for t in tasks if t["id"].startswith(("DI-", "GR-"))]
        assert new
        assert all(t["ground_truth"].get("gt_pending") is True for t in new)

    def test_graph_path_task_declares_source_and_target(self, tasks: list[dict]) -> None:
        gp = [t for t in tasks if t["type"] == "graph_path"]
        assert gp
        for t in gp:
            assert t["ground_truth"]["source"]
            assert t["ground_truth"]["target"]

    def test_di_gr_tasks_are_scoreable(self, tasks: list[dict]) -> None:
        for t in (t for t in tasks if t["id"].startswith(("DI-", "GR-"))):
            assert t.get("scoreable") is True, t["id"]


# ---------------------------------------------------------------------------
# Generator validators / oracles (tiny fixture repos)
# ---------------------------------------------------------------------------


class TestDiffImpactValidator:
    """_validate_diff_impact computes AST caller + test-import GT independent of scan-query."""

    def test_computes_callers_and_test_modules(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {
            "type": "diff_impact",
            "id": "DI-x",
            "primary_fn": "a::target",
            "primary_module": "a",
            "ground_truth": {"gt_pending": True, "fn_callers": [], "test_modules": []},
        }
        ok, live, reason = script_gen_bench._validate_diff_impact(task, None, None, mini_repo)
        assert ok is False  # gt_pending → not-ok, but oracle GT computed
        assert live["fn_callers"] == ["b::caller"]
        assert live["test_modules"] == ["tests.test_a"]
        assert live["gt_pending"] is False
        assert "computed" in reason

    def test_pending_flag_cleared_when_gt_matches(self, script_gen_bench: Any, mini_repo: Path) -> None:
        """Once GT is populated (gt_pending cleared), a matching task validates ok."""
        task = {
            "type": "diff_impact",
            "id": "DI-x",
            "primary_fn": "a::target",
            "primary_module": "a",
            "ground_truth": {
                "gt_pending": False,
                "fn_callers": ["b::caller"],
                "test_modules": ["tests.test_a"],
            },
        }
        ok, _live, reason = script_gen_bench._validate_diff_impact(task, None, None, mini_repo)
        assert ok is True, reason

    def test_rejects_malformed_primary_fn(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {"type": "diff_impact", "id": "DI-x", "primary_fn": "no_colons", "ground_truth": {}}
        ok, live, reason = script_gen_bench._validate_diff_impact(task, None, None, mini_repo)
        assert ok is False and live is None and "primary_fn" in reason


class TestGraphValidators:
    """graph_central / graph_path / graph_fn_blast validators on a tiny fixture repo."""

    def test_central_ranks_by_in_degree(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {"type": "graph_central", "id": "GR-x", "ground_truth": {"gt_pending": True, "top": 2}}
        ok, live, _reason = script_gen_bench._validate_graph_central(task, None, None, mini_repo)
        assert ok is False  # pending
        # a is imported by b; b is imported by c → both have in-degree 1, c has 0.
        assert set(live["central_modules"]) == {"a", "b"}

    def test_path_returns_unique_chain(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {
            "type": "graph_path",
            "id": "GR-p",
            "ground_truth": {"gt_pending": True, "source": "c", "target": "a"},
        }
        ok, live, _reason = script_gen_bench._validate_graph_path(task, None, None, mini_repo)
        assert ok is False  # pending
        assert live["import_path"] == ["c", "b", "a"]
        assert live["path_is_unique"] is True

    def test_path_requires_source_and_target(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {"type": "graph_path", "id": "GR-p", "ground_truth": {"gt_pending": True}}
        ok, live, reason = script_gen_bench._validate_graph_path(task, None, None, mini_repo)
        assert ok is False and live is None and "source" in reason

    def test_fn_blast_depth2_closure(self, script_gen_bench: Any, mini_repo: Path) -> None:
        task = {
            "type": "graph_fn_blast",
            "id": "GR-fb",
            "primary_fn": "a::target",
            "ground_truth": {"gt_pending": True, "depth": 2},
        }
        ok, live, _reason = script_gen_bench._validate_graph_fn_blast(task, None, None, mini_repo)
        assert ok is False  # pending
        assert live["blast_callers"] == ["b::caller"]


class TestGtPending:
    """_gt_is_pending helper + oracle-backed registration."""

    def test_gt_is_pending_true_false(self, script_gen_bench: Any) -> None:
        assert script_gen_bench._gt_is_pending({"ground_truth": {"gt_pending": True}}) is True
        assert script_gen_bench._gt_is_pending({"ground_truth": {"gt_pending": False}}) is False
        assert script_gen_bench._gt_is_pending({"ground_truth": {}}) is False

    def test_new_types_are_oracle_backed(self, script_gen_bench: Any) -> None:
        for ttype in ("diff_impact", "graph_central", "graph_path", "graph_fn_blast"):
            assert script_gen_bench._update_is_oracle_backed({"type": ttype}) is True

    def test_new_types_registered_in_validators(self, script_gen_bench: Any) -> None:
        for ttype in ("diff_impact", "graph_central", "graph_path", "graph_fn_blast"):
            assert ttype in script_gen_bench.VALIDATORS


# ---------------------------------------------------------------------------
# DiffImpactStager stage / revert / dirty-tree refusal
# ---------------------------------------------------------------------------


class TestDiffImpactStager:
    """Stage-then-revert safety, including dirty-tree refusal."""

    def _spec(self) -> list[dict]:
        return [
            {"file": "src.py", "find": "def widely_used(", "replace": "def widely_used(new_arg=None,  # staged\n    "}
        ]

    def test_stage_applies_and_revert_restores(self, script_run_bench: Any, git_repo: Path) -> None:
        original = (git_repo / "src.py").read_text()
        stager = script_run_bench.DiffImpactStager(git_repo, self._spec())
        with stager:
            staged = (git_repo / "src.py").read_text()
            assert "new_arg=None" in staged
        # On block exit the change is reverted via git checkout --.
        assert (git_repo / "src.py").read_text() == original

    def test_revert_runs_even_on_exception(self, script_run_bench: Any, git_repo: Path) -> None:
        original = (git_repo / "src.py").read_text()
        stager = script_run_bench.DiffImpactStager(git_repo, self._spec())
        with pytest.raises(RuntimeError):
            with stager:
                assert "new_arg=None" in (git_repo / "src.py").read_text()
                raise RuntimeError("arm blew up mid-task")
        assert (git_repo / "src.py").read_text() == original

    def test_refuses_dirty_tree(self, script_run_bench: Any, git_repo: Path) -> None:
        # Dirty the staged path BEFORE staging — the stager must refuse.
        (git_repo / "src.py").write_text("def widely_used():\n    return 999  # user edit\n")
        stager = script_run_bench.DiffImpactStager(git_repo, self._spec())
        with pytest.raises(script_run_bench.DirtyTreeError):
            stager.__enter__()

    def test_refuses_dirty_tree_leaves_user_edit_intact(self, script_run_bench: Any, git_repo: Path) -> None:
        dirty = "def widely_used():\n    return 999  # user edit\n"
        (git_repo / "src.py").write_text(dirty)
        stager = script_run_bench.DiffImpactStager(git_repo, self._spec())
        with pytest.raises(script_run_bench.DirtyTreeError):
            stager.__enter__()
        # Refusal must not have touched or reverted the user's own edit.
        assert (git_repo / "src.py").read_text() == dirty

    def test_missing_find_text_aborts(self, script_run_bench: Any, git_repo: Path) -> None:
        bad = [{"file": "src.py", "find": "NONEXISTENT_TOKEN", "replace": "x"}]
        stager = script_run_bench.DiffImpactStager(git_repo, bad)
        with pytest.raises(script_run_bench.DirtyTreeError):
            stager.__enter__()
        stager.revert()  # best-effort cleanup

    def test_append_edit_form(self, script_run_bench: Any, git_repo: Path) -> None:
        original = (git_repo / "src.py").read_text()
        stager = script_run_bench.DiffImpactStager(git_repo, [{"file": "src.py", "append": "\n# appended\n"}])
        with stager:
            assert (git_repo / "src.py").read_text().endswith("# appended\n")
        assert (git_repo / "src.py").read_text() == original


# ---------------------------------------------------------------------------
# Batch counter parsing + used_batch
# ---------------------------------------------------------------------------


class TestBatchParsing:
    """_parse_batch_subcommands + used_batch counter wiring."""

    def test_parses_inner_cmds(self, script_run_bench: Any) -> None:
        cmd = 'scan-query batch <<< \'[{"cmd": "fn-rdeps", "args": ["m::f"]}, {"cmd": "rdeps", "args": ["m"]}]\''
        assert script_run_bench._parse_batch_subcommands(cmd) == ["fn-rdeps", "rdeps"]

    def test_non_batch_returns_empty(self, script_run_bench: Any) -> None:
        assert script_run_bench._parse_batch_subcommands("scan-query symbol Trainer") == []

    def test_unknown_inner_cmd_dropped(self, script_run_bench: Any) -> None:
        assert script_run_bench._parse_batch_subcommands('scan-query batch <<< \'[{"cmd": "bogus"}]\'') == []

    def test_malformed_json_returns_empty(self, script_run_bench: Any) -> None:
        assert script_run_bench._parse_batch_subcommands("scan-query batch <<< '[not json'") == []

    def test_batch_and_diff_impact_are_subcommands(self, script_run_bench: Any) -> None:
        assert "batch" in script_run_bench._SCAN_QUERY_SUBCOMMANDS
        assert "diff-impact" in script_run_bench._SCAN_QUERY_SUBCOMMANDS
        assert script_run_bench._parse_scan_query_subcommand("scan-query diff-impact --base HEAD~1") == "diff-impact"

    def test_record_tool_use_sets_used_batch_and_attributes_inner(self, script_run_bench: Any) -> None:
        run = script_run_bench.BenchRun(
            arm="codemap", task_id="X", task_type="diff_impact", model="haiku", success=False
        )
        cmd = 'scan-query batch <<< \'[{"cmd": "fn-rdeps", "args": ["m::f"]}, {"cmd": "rdeps", "args": ["m"]}]\''
        script_run_bench.BenchRunner._record_tool_use("Bash", {"command": cmd}, run)
        assert run.used_batch is True
        # Outer `batch` counted once; each inner cmd attributed to its own counter.
        assert run.scan_query_subcommands.get("batch") == 1
        assert run.scan_query_subcommands.get("fn-rdeps") == 1
        assert run.scan_query_subcommands.get("rdeps") == 1

    def test_used_batch_defaults_false(self, script_run_bench: Any) -> None:
        run = script_run_bench.BenchRun(
            arm="codemap", task_id="X", task_type="symbol_extraction", model="haiku", success=False
        )
        assert run.used_batch is False

    def test_used_batch_serialised_to_jsonl(self, script_run_bench: Any) -> None:
        from dataclasses import asdict

        run = script_run_bench.BenchRun(
            arm="codemap", task_id="X", task_type="diff_impact", model="haiku", success=False
        )
        run.used_batch = True
        assert asdict(run)["used_batch"] is True


# ---------------------------------------------------------------------------
# Runner evaluators
# ---------------------------------------------------------------------------


class TestDiffImpactEvaluator:
    """_evaluate_diff_impact: caller recall AND test-file recall both ≥ 0.70."""

    def _task(self) -> dict:
        return {
            "type": "diff_impact",
            "id": "DI-x",
            "ground_truth": {
                "fn_callers": ["lightning.a::Foo.bar", "lightning.b::Baz.qux"],
                "unique_caller_count": 2,
                "test_modules": ["tests.test_a", "tests.test_b"],
            },
        }

    def test_both_recalls_high_is_correct(self, script_run_bench: Any) -> None:
        out = "## Callers\nlightning.a::Foo.bar\nlightning.b::Baz.qux\n## Tests\ntests.test_a\ntests.test_b\n"
        q = script_run_bench._evaluate_diff_impact(self._task(), out)
        assert q.correct is True
        assert q.scoring_detail["caller_recall"] == 1.0
        assert q.scoring_detail["test_recall"] == 1.0

    def test_missing_tests_fails_even_with_all_callers(self, script_run_bench: Any) -> None:
        out = "## Callers\nlightning.a::Foo.bar\nlightning.b::Baz.qux\n"
        q = script_run_bench._evaluate_diff_impact(self._task(), out)
        assert q.correct is False
        assert q.scoring_detail["caller_recall"] == 1.0
        assert q.scoring_detail["test_recall"] == 0.0

    def test_empty_gt_not_scored(self, script_run_bench: Any) -> None:
        task = {"type": "diff_impact", "id": "DI-x", "ground_truth": {"fn_callers": [], "test_modules": []}}
        assert script_run_bench._evaluate_diff_impact(task, "anything").scored is False


class TestGraphEvaluators:
    """Central set-overlap, path ordered-chain, fn-blast recall."""

    def test_central_set_overlap(self, script_run_bench: Any) -> None:
        task = {
            "type": "graph_central",
            "id": "GR-c",
            "ground_truth": {"central_modules": ["lightning.a.b", "lightning.c.d", "lightning.e.f"]},
        }
        out = "## Modules\nlightning.a.b\nlightning.c.d\n"
        q = script_run_bench._evaluate_graph_central(task, out)
        assert q.recall == pytest.approx(2 / 3, abs=0.01)
        assert q.correct is False  # 0.67 < 0.70

    def test_path_ordered_chain_correct(self, script_run_bench: Any) -> None:
        task = {
            "type": "graph_path",
            "id": "GR-p",
            "ground_truth": {"import_path": ["lightning.x.a", "lightning.x.b", "lightning.x.c"]},
        }
        out = "## Path\nlightning.x.a\nlightning.x.b\nlightning.x.c\n"
        q = script_run_bench._evaluate_graph_path(task, out)
        assert q.correct is True

    def test_path_out_of_order_incorrect(self, script_run_bench: Any) -> None:
        task = {
            "type": "graph_path",
            "id": "GR-p",
            "ground_truth": {"import_path": ["lightning.x.a", "lightning.x.b", "lightning.x.c"]},
        }
        out = "lightning.x.c came from lightning.x.b came from lightning.x.a"
        q = script_run_bench._evaluate_graph_path(task, out)
        assert q.correct is False  # reversed order

    def test_fn_blast_recall(self, script_run_bench: Any) -> None:
        task = {
            "type": "graph_fn_blast",
            "id": "GR-fb",
            "ground_truth": {"blast_callers": ["lightning.a::Foo.mid", "lightning.b::Bar.top"]},
        }
        out = "## Callers\nlightning.a::Foo.mid\nlightning.b::Bar.top\n"
        q = script_run_bench._evaluate_graph_fn_blast(task, out)
        assert q.correct is True
        assert q.recall == 1.0


class TestModuleMatchHelpers:
    """_module_mentioned / _module_first_pos matching semantics."""

    def test_exact_and_suffix_match(self, script_run_bench: Any) -> None:
        assert script_run_bench._module_mentioned("lightning.pytorch.loops.eval_loop", "see loops.eval_loop") is True
        assert script_run_bench._module_mentioned("a.b.c", "unrelated") is False

    def test_single_component_tail_not_matched(self, script_run_bench: Any) -> None:
        # A bare single-component tail is too weak to count on its own.
        assert script_run_bench._module_mentioned("lightning.pytorch.trainer", "the trainer runs") is False

    def test_first_pos_returns_earliest(self, script_run_bench: Any) -> None:
        assert script_run_bench._module_first_pos("a.b.c", "xx a.b.c yy") == 3
        assert script_run_bench._module_first_pos("a.b.c", "nope") is None


# ---------------------------------------------------------------------------
# Registration wiring in the runner
# ---------------------------------------------------------------------------


class TestRunnerRegistration:
    """New evaluators + diff_impact type are wired into the runner."""

    def test_evaluators_registered(self, script_run_bench: Any) -> None:
        for ttype in ("diff_impact", "graph_central", "graph_path", "graph_fn_blast"):
            assert ttype in script_run_bench._EVALUATORS

    def test_diff_impact_type_constant(self, script_run_bench: Any) -> None:
        assert script_run_bench._DIFF_IMPACT_TYPE == "diff_impact"

    def test_codemap_tools_document_new_subcommands(self, script_run_bench: Any) -> None:
        prompt = script_run_bench._build_system_prompt("codemap", "r", "/repo", "/idx.json")
        for token in ("central", "path <source>", "fn-blast", "diff-impact", "batch"):
            assert token in prompt, token
