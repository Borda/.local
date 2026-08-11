"""No-model contracts for the private Codex executable-fix stage."""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
from typing import Any

import pytest


BENCHMARKS = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def stage_fix() -> Any:
    """Load the structural transport before its private fix-stage consumer."""
    structural_path = BENCHMARKS / "run-codex-structural.py"
    spec = importlib.util.spec_from_file_location("codex_structural_for_stage_fix", structural_path)
    assert spec is not None and spec.loader is not None
    structural = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = structural
    spec.loader.exec_module(structural)
    from _bench_codex import stage_fix as module

    return module


def _source_row(*, captured_diff: object, tool_result_tokens: int | None = None) -> dict[str, object]:
    """Build one replayable executable-stage telemetry row."""
    return {
        "task_id": "fixture-task",
        "arm": "A_plain",
        "raw_events": [],
        "captured_diff": captured_diff,
        "provider_binding": {},
        "input_tokens": 11,
        "cached_input_tokens": 2,
        "output_tokens": 3,
        "tool_result_tokens": tool_result_tokens,
    }


def _rescored_row(*, tool_result_tokens: int | None) -> dict[str, object]:
    """Return the minimal scoreable replay result for fixture parsers."""
    return {
        "task_id": "fixture-task",
        "arm": "A_plain",
        "input_tokens": 11,
        "cached_input_tokens": 2,
        "output_tokens": 3,
        "tool_result_tokens": tool_result_tokens,
        "command_calls": 0,
        "provider_binding": {},
        "primary_correct": False,
        "codemap_used": False,
        "pooling_eligible": False,
        "compliance": True,
        "execution": {"recount_recoverable": False, "patch_applied": False, "targeted_test_passed": False},
    }


def test_executable_result_row_uses_private_runtime_formatters(stage_fix: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Progress rendering must not depend on formatters removed from the public runner."""
    monkeypatch.setattr(stage_fix, "_structural", lambda: SimpleNamespace())
    row = {
        "task_id": "FS-01",
        "arm": "A_plain",
        "input_tokens": 12_345,
        "output_tokens": 678,
        "command_calls": 2,
        "elapsed_s": 61.0,
        "primary_correct": True,
        "pooling_eligible": True,
        "codemap_used": False,
        "compliance": True,
        "execution": {
            "recount_recoverable": False,
            "recount_oracle_passed": None,
            "patch_applied": True,
            "targeted_test_passed": True,
        },
    }

    rendered = stage_fix.format_executable_result_row(row, completed=1, total=6)

    assert "in= 12.3k" in rendered
    assert "out=  678" in rendered
    assert "time= 1m1s" in rendered
    assert "compliance=" not in rendered


def test_paid_stage_request_explains_missing_flags_and_stale_scope(stage_fix: Any, tmp_path: Path) -> None:
    """Paid admission errors must name the problem and give a safe recovery path."""
    common = {
        "study": "fix-single",
        "repo_path": tmp_path / "repo",
        "task_ids": ["FS-01", "FS-03"],
        "model": "gpt-5.6-luna",
        "expected_scope": "fresh-scope",
    }

    with pytest.raises(ValueError, match=r"missing --auth-source, --run-dir, --paid-approval"):
        stage_fix._require_paid_stage_request(**common, auth_source=None, run_dir=None, paid_approval=None)
    with pytest.raises(ValueError, match=r"received --paid-approval: stale-scope") as error:
        stage_fix._require_paid_stage_request(
            **common,
            auth_source=tmp_path / "auth.json",
            run_dir=tmp_path / "run",
            paid_approval="stale-scope",
        )

    message = str(error.value)
    assert "current scope: fresh-scope" in message
    assert "--tasks FS-01,FS-03 --dry-run" in message
    assert "No model call was made." in message


def test_scope_binds_the_validated_source_and_index(stage_fix: Any) -> None:
    """A changed source input must invalidate executable paid approval."""
    task = {"contract": SimpleNamespace(task_id="FS-01", provider_binding=lambda: {"task": "one"})}
    shared = {"repo_path": "/private/tmp/repo", "repo_sha256": "repo", "manifest_sha256": "manifest"}

    first = stage_fix._resolve_scope([task], "gpt-5.6-luna", {**shared, "index_sha256": "one"})
    second = stage_fix._resolve_scope([task], "gpt-5.6-luna", {**shared, "index_sha256": "two"})

    assert first["scope_sha256"] != second["scope_sha256"]


def test_managed_input_recovery_preserves_the_invalid_target(stage_fix: Any) -> None:
    """Managed-target admission must recommend a recoverable reconstruction, never deletion."""
    recovery = stage_fix._stage_input_recovery(Path("/private/tmp/codemap-provider-parity-pl-2.6.5"))

    assert "mv /private/tmp/codemap-provider-parity-pl-2.6.5" in recovery
    assert "run-all.sh codex --struct --tasks=FN-02 --dry-run" in recovery
    assert "rm -rf" not in recovery


def test_dry_run_emits_exact_paid_command_after_preflight(
    stage_fix: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A successful no-model admission must print a copy-paste paid command without creating a run directory."""
    contract = SimpleNamespace(task_id="FS-01", baseline_commit="baseline", provider_binding=lambda: {})
    adapter = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(stage_fix, "load_fix_single_tasks", lambda *_args: [{"task": {}, "contract": contract}])
    monkeypatch.setattr(stage_fix, "_stage_source_binding", lambda *_args: {"source": "locked"})
    monkeypatch.setattr(stage_fix, "_resolve_scope", lambda *_args: {"scope_sha256": "fixture-scope"})
    monkeypatch.setattr(
        stage_fix, "_structural", lambda: SimpleNamespace(CodexRunner=lambda *_args, **_kwargs: adapter)
    )
    monkeypatch.setattr(stage_fix, "preflight_executable_agent_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(stage_fix, "_suggested_run_dir", lambda _study: Path("benchmarks/results/fresh-run"))

    stage_fix.run_fix_stage(
        study="fix-single",
        repo_path=tmp_path / "repo",
        selected={"FS-01"},
        dry_run=True,
        resolve_scope=False,
        auth_source=None,
        run_dir=None,
        paid_approval=None,
        model="gpt-5.6-luna",
        index_path=tmp_path / "repo/.cache/codemap/repo.json",
        marketplace_root=BENCHMARKS.parent,
        codemap_bin=BENCHMARKS.parent / "plugins/codemap-py/bin/codemap-py",
    )

    output = capsys.readouterr().out
    assert "SCOPE   fixture-scope" in output
    assert "PAID_COMMAND" in output
    assert "--run-dir benchmarks/results/fresh-run" in output
    assert "--paid-approval fixture-scope" in output
    assert "--tasks FS-01" in output
    assert "--study" not in output
    assert "--paid=True" not in output


def test_full_study_dry_run_emits_paid_command_without_task_selector(
    stage_fix: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The canonical full-study command must preserve omission of ``--tasks``."""
    contracts = [
        SimpleNamespace(task_id=task_id, baseline_commit="baseline", provider_binding=lambda: {})
        for task_id in ("FS-01", "FS-02", "FS-03", "FS-04")
    ]
    adapter = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        stage_fix,
        "load_fix_single_tasks",
        lambda _path, _selected: [{"task": {}, "contract": contract} for contract in contracts],
    )
    monkeypatch.setattr(
        stage_fix,
        "load_task_suite",
        lambda _path: [{"id": contract.task_id} for contract in contracts],
    )
    monkeypatch.setattr(stage_fix, "_stage_source_binding", lambda *_args: {"source": "locked"})
    monkeypatch.setattr(stage_fix, "_resolve_scope", lambda *_args: {"scope_sha256": "full-scope"})
    monkeypatch.setattr(
        stage_fix, "_structural", lambda: SimpleNamespace(CodexRunner=lambda *_args, **_kwargs: adapter)
    )
    monkeypatch.setattr(stage_fix, "preflight_executable_agent_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(stage_fix, "_suggested_run_dir", lambda _study: Path("benchmarks/results/full-run"))

    stage_fix.run_fix_stage(
        study="fix-single",
        repo_path=tmp_path / "repo",
        selected=None,
        dry_run=True,
        resolve_scope=False,
        auth_source=None,
        run_dir=None,
        paid_approval=None,
        model="gpt-5.6-luna",
        index_path=tmp_path / "repo/.cache/codemap/repo.json",
        marketplace_root=BENCHMARKS.parent,
        codemap_bin=BENCHMARKS.parent / "plugins/codemap-py/bin/codemap-py",
    )

    output = capsys.readouterr().out
    assert "PLAN    FS-04 C_strict" in output
    assert "--run-dir benchmarks/results/full-run" in output
    assert "--tasks" not in output


def test_executable_cells_and_preflight_keep_permission_verification_enabled(
    stage_fix: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both executable paths must validate their declared workspace permissions."""
    workspace_path, source_path = tmp_path / "workspace", tmp_path / "source"
    workspace_path.mkdir()
    source_path.mkdir()
    preparation_kwargs: list[dict[str, Any]] = []
    workspace = SimpleNamespace(
        worktree=workspace_path,
        index_relocation={},
        capture_diff=lambda: "diff --git a/example.py b/example.py\n",
        changed_paths=lambda: (),
        index_unchanged=lambda: True,
        cleanup=lambda: True,
    )
    home = SimpleNamespace(coordination_path=None, cleanup=lambda: None, codemap_skill_path=None, env={})

    @contextlib.contextmanager
    def bind_workspace(*_args: Any, **_kwargs: Any) -> Any:
        yield

    class Adapter:
        """Capture the private home preparation performed by executable cells."""

        def _prepare_verified_home(self, *_args: Any, **kwargs: Any) -> Any:
            preparation_kwargs.append(kwargs)
            return home

        def build_command(self, *_args: Any, **_kwargs: Any) -> list[str]:
            return ["codex", "exec"]

        def _subprocess(self, *_args: Any, **_kwargs: Any) -> str:
            return ""

    structural = stage_fix._structural()
    monkeypatch.setattr(structural, "create_executable_agent_workspace", lambda *_args: workspace)
    monkeypatch.setattr(structural, "bind_executable_agent_workspace", bind_workspace)
    monkeypatch.setattr(structural, "_repo_sha", lambda _path: "baseline")
    monkeypatch.setattr(structural, "_git_porcelain_status", lambda _path: "")
    stage_fix.execute_executable_agent_cell(
        adapter=Adapter(),
        source_repo=source_path,
        source_index=tmp_path / "index.json",
        baseline_commit="baseline",
        native_arm="A_plain",
        arm="A_plain",
        prompt="fixture prompt",
        item={},
        parser=lambda *_args, **_kwargs: {
            "success": True,
            "primary_correct": True,
            "pooling_eligible": True,
            "answer_error": "",
        },
    )
    stage_fix.preflight_executable_agent_workspace(
        Adapter(), source_repo=source_path, source_index=tmp_path / "index.json", baseline_commit="baseline"
    )

    assert len(preparation_kwargs) == 1 + len(stage_fix.NATIVE_ARMS)
    assert all(kwargs["writable_workspace"] == workspace_path for kwargs in preparation_kwargs)
    assert all(kwargs["denied_workspace"] == source_path for kwargs in preparation_kwargs)


def test_rescore_fix_stage_reuses_captured_agent_worktree_diff(
    stage_fix: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline replay preserves the patch transport captured from the agent worktree."""
    source_dir, output_dir = tmp_path / "source", tmp_path / "rescored"
    source_dir.mkdir()
    source_row = _source_row(captured_diff="diff --git a/example.py b/example.py\n", tool_result_tokens=4)
    (source_dir / "run-metadata.json").write_text('{"status":"completed"}', encoding="utf-8")
    (source_dir / "telemetry.jsonl").write_text(json.dumps(source_row) + "\n", encoding="utf-8")
    (source_dir / "checksums.sha256").write_text("fixture\n", encoding="utf-8")
    observed: dict[str, object] = {}
    monkeypatch.setattr(stage_fix, "verify_checksums", lambda _path: None)
    monkeypatch.setattr(stage_fix, "_print_executable_result_row", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        stage_fix, "load_fix_single_tasks", lambda *_args: [{"contract": SimpleNamespace(task_id="fixture-task")}]
    )
    monkeypatch.setattr(stage_fix, "validate_fix_single_binding", lambda *_args: None)
    monkeypatch.setattr(
        stage_fix,
        "parse_fix_single_cell",
        lambda *_args, **kwargs: (
            observed.update(captured_diff=kwargs["captured_diff"]) or _rescored_row(tool_result_tokens=4)
        ),
    )

    stage_fix.rescore_fix_stage(source_dir, output_dir, tmp_path, study="fix-single")

    assert observed["captured_diff"] == source_row["captured_diff"]


@pytest.mark.parametrize(
    ("study", "loader", "scope"),
    (
        ("fix-single", "load_fix_single_tasks", "resolve_fix_single_scope"),
        ("fix-multi", "load_fix_multi_tasks", "resolve_fix_multi_scope"),
    ),
)
def test_executable_paid_stages_route_every_arm_row_through_shared_renderer(
    stage_fix: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    study: str,
    loader: str,
    scope: str,
) -> None:
    """All executable paid stages preserve the established interactive A/B/C renderer."""
    rendered: list[tuple[str, str]] = []
    contract = SimpleNamespace(task_id="fixture-task", baseline_commit="baseline")
    adapter = SimpleNamespace(create_input_snapshot=lambda *_args, **_kwargs: None, close=lambda: None)
    monkeypatch.setattr(
        stage_fix, "_structural", lambda: SimpleNamespace(CodexRunner=lambda *_args, **_kwargs: adapter)
    )
    monkeypatch.setattr(stage_fix, loader, lambda *_args: [{"task": {}, "contract": contract}])
    monkeypatch.setattr(stage_fix, scope, lambda *_args: {"scope_sha256": "fixture-scope"})
    monkeypatch.setattr(stage_fix, "_resolve_scope", lambda *_args: {"scope_sha256": "fixture-scope"})
    monkeypatch.setattr(stage_fix, "_stage_source_binding", lambda *_args: {"source": "locked"})
    monkeypatch.setattr(stage_fix, "preflight_executable_agent_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        stage_fix,
        "validate_fix_single_binding" if study == "fix-single" else "validate_fix_multi_binding",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        stage_fix, "fix_single_prompt" if study == "fix-single" else "fix_multi_prompt", lambda *_args: "fixture prompt"
    )
    monkeypatch.setattr(stage_fix.runtime, "print_arm_row", lambda row, arm: rendered.append((row, arm)))
    monkeypatch.setattr(
        stage_fix,
        "execute_executable_agent_cell",
        lambda *_args, **kwargs: {
            **_rescored_row(tool_result_tokens=None),
            "arm": kwargs["arm"],
            "elapsed_s": 1.0,
            "primary_correct": True,
            "pooling_eligible": True,
            "execution": {
                "recount_recoverable": False,
                "recount_oracle_passed": None,
                "patch_applied": True,
                "targeted_test_passed": True,
            },
        },
    )

    stage_fix.run_fix_stage(
        study=study,
        repo_path=tmp_path,
        selected={"fixture-task"},
        dry_run=False,
        resolve_scope=False,
        auth_source=tmp_path / "auth.json",
        run_dir=tmp_path / study,
        paid_approval="fixture-scope",
        model="fixture-model",
    )

    assert [arm for _row, arm in rendered] == list(stage_fix.ARMS)
    assert all("quality=1.000" in row and "oracle=✓" in row for row, _arm in rendered)
    output = capsys.readouterr().out
    assert f"ARTIFACTS\n\ttelemetry={tmp_path / study / 'telemetry.jsonl'}" in output
    assert f"\tmetadata={tmp_path / study / 'run-metadata.json'}" in output


@pytest.mark.parametrize("captured_diff", (None, "", "not a diff", {"not": "a diff"}))
def test_rescore_fix_stage_rejects_missing_or_invalid_captured_diff(
    stage_fix: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured_diff: object
) -> None:
    """Agent-worktree replays cannot silently fall back to a response envelope."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "run-metadata.json").write_text('{"status":"completed"}', encoding="utf-8")
    (source_dir / "telemetry.jsonl").write_text(
        json.dumps(_source_row(captured_diff=captured_diff)) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(stage_fix, "verify_checksums", lambda _path: None)
    monkeypatch.setattr(
        stage_fix, "load_fix_single_tasks", lambda *_args: [{"contract": SimpleNamespace(task_id="fixture-task")}]
    )
    monkeypatch.setattr(stage_fix, "validate_fix_single_binding", lambda *_args: None)

    with pytest.raises(ValueError, match="captured.*diff"):
        stage_fix.rescore_fix_stage(source_dir, tmp_path / "rescored", tmp_path, study="fix-single")


@pytest.mark.parametrize(
    "observed_arguments",
    (
        ["symbol", "EarlyStopping._run_early_stopping_check"],
        [
            "fn-rdeps",
            "lightning.pytorch.callbacks.early_stopping::EarlyStopping._run_early_stopping_check",
        ],
        [
            "fn-rdeps",
            "--exclude-tests",
            "lightning.pytorch.callbacks.early_stopping::EarlyStopping._run_early_stopping_check",
        ],
    ),
)
def test_strict_executable_patch_rejects_noncanonical_query_use_from_pooling(
    stage_fix: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, observed_arguments: list[str]
) -> None:
    """C compact-call compliance does not let a wrong task-fit argv enter pooling."""
    task = next(task for task in stage_fix.load_task_suite(stage_fix.FIX_MULTI_TASKS_PATH) if task["id"] == "FM-01")
    contract = stage_fix.build_fix_multi_contract(task)
    parsed = SimpleNamespace(
        success=True,
        output_text="summary",
        input_tokens=10,
        cached_input_tokens=2,
        output_tokens=3,
        reasoning_output_tokens=1,
        tool_result_tokens=None,
        command_calls=1,
        tool_elapsed_s=None,
        codemap_calls=1,
        codemap_successful_calls=1,
        codemap_direct_compact_successful_calls=0,
        codemap_skill_compact_successful_calls=1,
        codemap_errors=0,
        skill_delivery_observed=True,
        successful_query_arguments=[observed_arguments],
        raw_events=[],
    )
    execution = {
        "baseline_failed": True,
        "patch_applied": True,
        "changed_paths": list(contract.expected_paths),
        "targeted_test_passed": True,
        "recount_recoverable": False,
        "recount_oracle_passed": None,
        "cleanup_verified": True,
        "error": "",
    }
    monkeypatch.setattr(stage_fix.runtime, "parse_codex_jsonl", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(
        stage_fix, "execute_fix_multi_patch", lambda *_args, **_kwargs: SimpleNamespace(as_dict=lambda: execution)
    )

    row = stage_fix.parse_fix_multi_cell(
        "{}",
        arm="C_strict",
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff="diff --git a/a.py b/a.py\n",
    )

    assert row["success"] is True
    assert row["primary_correct"] is True
    assert row["codemap_used"] is True
    assert row["compliance"] is True
    assert row["strict_query_conformance"] is False
    assert row["pooling_eligible"] is False


@pytest.mark.parametrize(
    ("arm", "expected_compliance", "expected_pooling"),
    (("B_auto", True, True), ("C_strict", False, False)),
)
def test_fix_single_preserves_optional_and_forced_query_controls(
    stage_fix: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arm: str,
    expected_compliance: bool,
    expected_pooling: bool,
) -> None:
    """B permits zero use while C remains an ineligible forced-query negative control."""
    task = next(iter(stage_fix.load_task_suite(stage_fix.FIX_SINGLE_TASKS_PATH)))
    contract = stage_fix.build_fix_single_contract(task)
    parsed = SimpleNamespace(
        success=True,
        output_text="summary",
        input_tokens=10,
        cached_input_tokens=2,
        output_tokens=3,
        reasoning_output_tokens=1,
        tool_result_tokens=None,
        command_calls=0,
        tool_elapsed_s=None,
        codemap_calls=0,
        codemap_successful_calls=0,
        codemap_direct_compact_successful_calls=0,
        codemap_skill_compact_successful_calls=0,
        codemap_errors=0,
        skill_delivery_observed=False,
        successful_query_arguments=[],
        raw_events=[],
    )
    execution = {
        "baseline_failed": True,
        "patch_applied": True,
        "changed_paths": list(contract.expected_paths),
        "targeted_test_passed": True,
        "recount_recoverable": False,
        "recount_oracle_passed": None,
        "cleanup_verified": True,
        "error": "",
    }
    monkeypatch.setattr(stage_fix.runtime, "parse_codex_jsonl", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(
        stage_fix, "execute_fix_single_patch", lambda *_args, **_kwargs: SimpleNamespace(as_dict=lambda: execution)
    )
    expected_path = contract.expected_paths[0]
    captured_diff = (
        f"diff --git a/{expected_path} b/{expected_path}\n"
        f"--- a/{expected_path}\n"
        f"+++ b/{expected_path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    row = stage_fix.parse_fix_single_cell(
        "{}",
        arm=arm,
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff=captured_diff,
    )

    assert row["codemap_used"] is False
    assert row["compliance"] is expected_compliance
    assert row["strict_query_conformance"] is (None if arm == "B_auto" else False)
    assert row["pooling_eligible"] is expected_pooling
    if arm == "B_auto":
        assert "use it when useful" in stage_fix.fix_single_prompt(arm, task)
    else:
        prompt = stage_fix.fix_single_prompt(arm, task)
        expected_arguments = stage_fix._FIX_SINGLE_QUERY_ARGUMENTS[contract.task_id]
        assert f'`"$CODEMAP_BIN" query --compact {shlex.join(expected_arguments)}`.' in prompt


@pytest.mark.parametrize(
    ("task_id", "expected_arguments"),
    (
        (
            "FM-01",
            [
                "fn-rdeps",
                "lightning.pytorch.callbacks.early_stopping::EarlyStopping._run_early_stopping_check",
                "--exclude-tests",
            ],
        ),
        (
            "FM-02",
            [
                "fn-rdeps",
                "lightning.pytorch.callbacks.model_checkpoint::ModelCheckpoint._save_checkpoint",
                "--exclude-tests",
            ],
        ),
        ("FM-03", ["find-symbol", r"Strategy\.setup$", "--exclude-tests", "--limit", "0"]),
    ),
)
def test_fix_multi_strict_prompt_and_conformance_use_task_specific_argv(
    stage_fix: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task_id: str,
    expected_arguments: list[str],
) -> None:
    """Each Fix-Multi strict task requires and credits only its compact query argv."""
    task = next(task for task in stage_fix.load_task_suite(stage_fix.FIX_MULTI_TASKS_PATH) if task["id"] == task_id)
    contract = stage_fix.build_fix_multi_contract(task)
    parsed = SimpleNamespace(
        success=True,
        output_text="summary",
        input_tokens=10,
        cached_input_tokens=2,
        output_tokens=3,
        reasoning_output_tokens=1,
        tool_result_tokens=None,
        command_calls=1,
        tool_elapsed_s=None,
        codemap_calls=1,
        codemap_successful_calls=1,
        codemap_direct_compact_successful_calls=0,
        codemap_skill_compact_successful_calls=1,
        codemap_errors=0,
        skill_delivery_observed=True,
        successful_query_arguments=[expected_arguments],
        raw_events=[],
    )
    execution = {
        "baseline_failed": True,
        "patch_applied": True,
        "changed_paths": list(contract.expected_paths),
        "targeted_test_passed": True,
        "recount_recoverable": False,
        "recount_oracle_passed": None,
        "cleanup_verified": True,
        "error": "",
    }
    monkeypatch.setattr(stage_fix.runtime, "parse_codex_jsonl", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(
        stage_fix, "execute_fix_multi_patch", lambda *_args, **_kwargs: SimpleNamespace(as_dict=lambda: execution)
    )

    prompt = stage_fix.fix_multi_prompt("C_strict", task)
    row = stage_fix.parse_fix_multi_cell(
        "{}",
        arm="C_strict",
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff="diff --git a/a.py b/a.py\n",
    )

    assert f'`"$CODEMAP_BIN" query --compact {shlex.join(expected_arguments)}`.' in prompt
    assert row["strict_query_conformance"] is True
    assert row["pooling_eligible"] is True


def test_executable_prompt_discloses_unavailable_git_and_project_test_boundaries(stage_fix: Any) -> None:
    """All arms avoid wasting turns on intentionally inaccessible workspace facilities."""
    task = next(task for task in stage_fix.load_task_suite(stage_fix.FIX_MULTI_TASKS_PATH) if task["id"] == "FM-01")

    for arm in stage_fix.ARMS:
        prompt = stage_fix.fix_multi_prompt(arm, task)
        assert "Git metadata is intentionally inaccessible" in prompt
        assert "Do not invoke Git" in prompt
        assert "project dependencies are intentionally unavailable" in prompt


def test_fix_multi_changed_path_boundary_uses_unordered_set_semantics(
    stage_fix: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Equivalent changed-path sets remain eligible when Git returns another order."""
    task = next(task for task in stage_fix.load_task_suite(stage_fix.FIX_MULTI_TASKS_PATH) if task["id"] == "FM-03")
    contract = stage_fix.build_fix_multi_contract(task)
    parsed = SimpleNamespace(
        success=True,
        output_text="summary",
        input_tokens=10,
        cached_input_tokens=2,
        output_tokens=3,
        reasoning_output_tokens=1,
        tool_result_tokens=None,
        command_calls=0,
        tool_elapsed_s=None,
        codemap_calls=0,
        codemap_successful_calls=0,
        codemap_direct_compact_successful_calls=0,
        codemap_skill_compact_successful_calls=0,
        codemap_errors=0,
        skill_delivery_observed=False,
        successful_query_arguments=[],
        raw_events=[],
    )
    execution = {
        "baseline_failed": True,
        "patch_applied": True,
        "changed_paths": list(reversed(contract.expected_paths)),
        "targeted_test_passed": True,
        "recount_recoverable": False,
        "recount_oracle_passed": None,
        "cleanup_verified": True,
        "error": "",
    }
    monkeypatch.setattr(stage_fix.runtime, "parse_codex_jsonl", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(
        stage_fix, "execute_fix_multi_patch", lambda *_args, **_kwargs: SimpleNamespace(as_dict=lambda: execution)
    )

    row = stage_fix.parse_fix_multi_cell(
        "{}",
        arm="A_plain",
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff="diff --git a/a.py b/a.py\n",
    )

    assert row["changed_path_boundary_passed"] is True
    assert row["pooling_eligible"] is True

    execution["changed_paths"] = list(contract.expected_paths[:-1])
    missing = stage_fix.parse_fix_multi_cell(
        "{}",
        arm="A_plain",
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff="diff --git a/a.py b/a.py\n",
    )
    assert missing["changed_path_boundary_passed"] is False
    assert missing["pooling_eligible"] is False

    execution["changed_paths"] = [*contract.expected_paths, "src/lightning/pytorch/strategies/extra.py"]
    extra = stage_fix.parse_fix_multi_cell(
        "{}",
        arm="A_plain",
        item={"contract": contract},
        skill_path=None,
        repo_path=tmp_path,
        captured_diff="diff --git a/a.py b/a.py\n",
    )
    assert extra["changed_path_boundary_passed"] is False
    assert extra["pooling_eligible"] is False


def test_fix_stage_execution_is_controlled_only_by_dry_run(stage_fix: Any) -> None:
    """The unified launcher must not leak a public --paid switch into a fix stage."""
    parameters = inspect.signature(stage_fix.run_fix_stage).parameters

    assert "dry_run" in parameters
    assert "paid" not in parameters
