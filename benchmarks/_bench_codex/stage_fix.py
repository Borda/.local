"""Executable Fix-Single and Fix-Multi benchmark stages.

The structural runner supplies the established native Codex transport and
disposable-home isolation. This module owns executable task contracts, prompts,
patch scoring, offline rescoring, and Fix-Single/Fix-Multi stage execution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import time
from types import ModuleType
from typing import Any, Callable, Mapping
from uuid import uuid4


BENCHMARKS = Path(__file__).resolve().parents[1]
ROOT = BENCHMARKS.parent
STRUCTURAL_PATH = BENCHMARKS / "run-codex-structural.py"
PARITY_MANIFEST_PATH = BENCHMARKS / "manifests" / "codex-integration.json"
FIX_SINGLE_TASKS_PATH = BENCHMARKS / "suites" / "tasks-fix-single.json"
FIX_MULTI_TASKS_PATH = BENCHMARKS / "suites" / "tasks-fix-multi.json"
_MANAGED_PARITY_REPO = Path("/private/tmp/codemap-provider-parity-pl-2.6.5")
ARMS = ("A_plain", "B_auto", "C_strict")
NATIVE_ARMS = {"A_plain": "A_plain", "B_auto": "B_direct_required", "C_strict": "C_skill_required"}
_FIX_SINGLE_QUERY_ARGUMENTS = {
    "FS-01": ("symbol", "EarlyStopping.__init__"),
    "FS-02": ("symbol", "EarlyStopping.__init__"),
    "FS-03": ("symbol", "ModelCheckpoint._save_checkpoint"),
    "FS-04": ("symbol", "ModelCheckpoint.__init__"),
}
_FIX_MULTI_QUERY_ARGUMENTS = {
    "FM-01": (
        "fn-rdeps",
        "lightning.pytorch.callbacks.early_stopping::EarlyStopping._run_early_stopping_check",
        "--exclude-tests",
    ),
    "FM-02": (
        "fn-rdeps",
        "lightning.pytorch.callbacks.model_checkpoint::ModelCheckpoint._save_checkpoint",
        "--exclude-tests",
    ),
    "FM-03": ("find-symbol", r"Strategy\.setup_environment$", "--exclude-tests", "--limit", "0"),
}
_FIX_SINGLE_ANSWER_RE = re.compile(r"BEGIN_FIX_SINGLE_DIFF\s*(?P<diff>```diff\s*.*?```)", re.DOTALL)
_FIX_MULTI_ANSWER_RE = re.compile(r"BEGIN_FIX_MULTI_DIFF\s*(?P<diff>```diff\s*.*?```)", re.DOTALL)

sys.path.insert(0, str(BENCHMARKS))

from _bench_common.edit_patch_contracts import (  # noqa: E402
    assess_patch_answer,
    build_fix_multi_contract,
    build_fix_single_contract,
    validate_fix_multi_binding,
    validate_fix_single_binding,
)
from _bench_common.mutation_isolation import (  # noqa: E402
    FixExecution,
    execute_fix_multi_patch,
    execute_fix_single_patch,
)
from _bench_common.paid_lifecycle import (  # noqa: E402
    PaidStageCallbacks,
    run_paid_stage,
    verify_checksums,
    write_checksums,
)
from . import runtime  # noqa: E402
from _bench_common.provider_parity_contracts import (  # noqa: E402
    fresh_input_tokens,
    load_task_suite,
    token_accounting_inconsistent,
)


def _structural() -> ModuleType:
    """Return the already-loaded structural runner without importing another copy.

    Test suites frequently execute the runner under a generated module name, so
    module identity is established by its resolved source path instead of name.
    """
    structural_path = STRUCTURAL_PATH.resolve()
    for module in tuple(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if module_file is not None and Path(module_file).resolve() == structural_path:
            return module
    raise RuntimeError("the structural runner must be loaded before the executable stage")


def _executable_codemap_boundary() -> str:
    """Describe the frozen index boundary shared by executable task prompts."""
    return (
        " Codemap is a frozen static source-graph query tool: use it only for symbol, dependency, importer, or caller "
        "facts. Do not ask it to validate runtime behavior, execute tests, apply edits, or resolve facts once a compact "
        "query reports index.query_complete=true; use direct source reads and the task's tests for those remaining facts."
    )


def _task_prompt(
    arm: str, task: Mapping[str, Any], *, query_arguments: Mapping[str, tuple[str, ...]], study: str
) -> str:
    """Materialize one immutable executable prompt with its arm-only treatment supplement."""
    task_id = str(task["id"])
    if arm == "A_plain":
        supplement = "Codemap is absent and inaccessible. Use ordinary repository tools."
    elif arm == "B_auto":
        supplement = (
            "Codemap's direct CLI is available as $CODEMAP_BIN; use it when useful." + _executable_codemap_boundary()
        )
    elif arm == "C_strict":
        supplement = (
            _structural()._arm_envelope("C_skill_required")
            + f' The required canonical query is exactly `"$CODEMAP_BIN" query --compact {shlex.join(query_arguments[task_id])}`.'
            + _executable_codemap_boundary()
        )
    else:
        raise ValueError(f"unknown {study} arm {arm}")
    return (
        f"{supplement}\n\n{task['prompt']}\n\n"
        "You are inside a benchmark-owned disposable checkout. Git metadata is intentionally inaccessible inside "
        "the agent sandbox. Do not invoke Git. The project dependencies are intentionally unavailable in this agent "
        "environment, so do not run project pytest; use bounded syntax and static validation. Implement the change "
        "directly in the checkout. "
        "Modify only the task's required source paths; do not commit, reset, clean, alter benchmark metadata, or return a diff. "
        "Finish with a concise summary only. The harness captures and validates the canonical Git diff after you finish."
    )


def fix_single_prompt(arm: str, task: Mapping[str, Any]) -> str:
    """Materialize a Fix-Single prompt for one treatment arm."""
    return _task_prompt(arm, task, query_arguments=_FIX_SINGLE_QUERY_ARGUMENTS, study="fix-single")


def fix_multi_prompt(arm: str, task: Mapping[str, Any]) -> str:
    """Materialize a Fix-Multi prompt for one treatment arm."""
    return _task_prompt(arm, task, query_arguments=_FIX_MULTI_QUERY_ARGUMENTS, study="fix-multi")


def _sha256(value: Mapping[str, object]) -> str:
    """Return the canonical SHA-256 for one immutable contract payload."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_fix_single_tasks(path: Path, selected: set[str]) -> list[dict[str, Any]]:
    """Load selected immutable Fix-Single tasks with their executable contracts."""
    loaded = [
        {"task": task, "contract": build_fix_single_contract(task)}
        for task in load_task_suite(path)
        if task["id"] in selected
    ]
    if {item["contract"].task_id for item in loaded} != selected:
        raise ValueError("--tasks must select known fix-single task IDs")
    return loaded


def load_fix_multi_tasks(path: Path, selected: set[str]) -> list[dict[str, Any]]:
    """Load selected immutable Fix-Multi tasks with their complete-caller contracts."""
    loaded = [
        {"task": task, "contract": build_fix_multi_contract(task)}
        for task in load_task_suite(path)
        if task["id"] in selected
    ]
    if {item["contract"].task_id for item in loaded} != selected:
        raise ValueError("--tasks must select known fix-multi task IDs")
    return loaded


def normalize_fix_single_patch_wire(diff: str) -> str:
    """Restore presentation-omitted diff markers without changing candidate code."""
    normalized: list[str] = []
    in_hunk = False
    lines = diff.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            in_hunk = False
            normalized.append(line)
            if index + 1 < len(lines) and lines[index + 1].startswith("@@ "):
                parts = line.split()
                if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                    raise ValueError("diff --git header must name a/ and b/ paths")
                normalized.extend((f"--- {parts[2]}", f"+++ {parts[3]}"))
            continue
        if line.startswith("@@ "):
            in_hunk = True
        normalized.append(" " if in_hunk and not line else line)
    return "\n".join(normalized) + "\n"


def _parse_patch_cell(
    stream: str | bytes,
    *,
    arm: str,
    item: Mapping[str, Any],
    skill_path: Path | None,
    repo_path: Path,
    captured_diff: str | None,
    answer_re: re.Pattern[str],
    query_arguments: Mapping[str, tuple[str, ...]],
    execute_patch: Callable[[Path, Any, str], FixExecution],
) -> dict[str, Any]:
    """Normalize one native response and score its stage-owned executable patch."""
    skill_sha256 = hashlib.sha256(skill_path.read_bytes()).hexdigest() if skill_path else ""
    parsed = runtime.parse_codex_jsonl(stream, skill_path=skill_path, skill_sha256=skill_sha256)
    contract = item["contract"]
    match = answer_re.search(parsed.output_text)
    answer_error = ""
    candidate_diff = normalized_diff = ""
    execution: dict[str, Any] = {
        "baseline_failed": False,
        "patch_applied": False,
        "changed_paths": [],
        "targeted_test_passed": False,
        "recount_recoverable": False,
        "recount_oracle_passed": None,
        "cleanup_verified": False,
        "error": "answer unavailable",
    }
    if captured_diff is None and match is None:
        answer_error = "missing exact fenced diff envelope"
    else:
        try:
            candidate_diff = (
                captured_diff if captured_diff is not None else assess_patch_answer(match.group("diff")).diff
            )
            if not candidate_diff.startswith("diff --git "):
                raise ValueError("captured executable patch must contain a unified diff")
            normalized_diff = normalize_fix_single_patch_wire(candidate_diff)
            execution = execute_patch(repo_path, contract, normalized_diff).as_dict()
        except ValueError as exc:
            answer_error = str(exc)
    codemap_observed_calls = getattr(parsed, "codemap_observed_calls", parsed.codemap_calls)
    codemap_used = codemap_observed_calls > 0
    contaminated = arm == "A_plain" and codemap_used
    compliance = {
        "A_plain": not contaminated,
        "B_auto": True,
        "C_strict": parsed.codemap_skill_compact_successful_calls > 0,
    }[arm]
    path_ok = set(execution["changed_paths"]) == set(contract.expected_paths)
    primary = bool(execution["baseline_failed"] and execution["patch_applied"] and execution["targeted_test_passed"])
    strict_query_conformance = (
        None if arm != "C_strict" else list(query_arguments[contract.task_id]) in parsed.successful_query_arguments
    )
    return {
        "task_id": contract.task_id,
        "arm": arm,
        "success": parsed.success and not answer_error and not contaminated and bool(execution["cleanup_verified"]),
        "primary_correct": primary,
        "pooling_eligible": bool(
            primary
            and path_ok
            and execution["cleanup_verified"]
            and not answer_error
            and compliance is not False
            and strict_query_conformance is not False
        ),
        "changed_path_boundary_passed": path_ok,
        "answer_error": answer_error,
        "patch_wire_normalized": bool(
            captured_diff is None and match is not None and not answer_error and normalized_diff != candidate_diff
        ),
        "patch_transport": "agent_worktree" if captured_diff is not None else "response_envelope",
        "execution": execution,
        "input_tokens": parsed.input_tokens,
        "cached_input_tokens": parsed.cached_input_tokens,
        "fresh_input_tokens": fresh_input_tokens(parsed.input_tokens, parsed.cached_input_tokens),
        "token_accounting_inconsistent": token_accounting_inconsistent(parsed.input_tokens, parsed.cached_input_tokens),
        "output_tokens": parsed.output_tokens,
        "reasoning_output_tokens": parsed.reasoning_output_tokens,
        "tool_result_tokens": parsed.tool_result_tokens,
        "command_calls": parsed.command_calls,
        "tool_elapsed_s": parsed.tool_elapsed_s,
        "codemap_used": codemap_used,
        "codemap_calls": parsed.codemap_calls,
        "codemap_observed_calls": codemap_observed_calls,
        "codemap_successful_calls": parsed.codemap_successful_calls,
        "codemap_direct_compact_successful_calls": parsed.codemap_direct_compact_successful_calls,
        "codemap_skill_compact_successful_calls": parsed.codemap_skill_compact_successful_calls,
        "codemap_errors": parsed.codemap_errors,
        "skill_delivery_observed": parsed.skill_delivery_observed,
        "successful_query_arguments": parsed.successful_query_arguments,
        "compliance": compliance,
        "strict_query_conformance": strict_query_conformance,
        "contaminated": contaminated,
        "output_text": parsed.output_text,
        "raw_events": parsed.raw_events,
        "raw_events_sha256": hashlib.sha256(
            json.dumps(parsed.raw_events, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "provider_binding": dict(contract.provider_binding()),
    }


def parse_fix_single_cell(
    stream: str | bytes,
    *,
    arm: str,
    item: Mapping[str, Any],
    skill_path: Path | None,
    repo_path: Path,
    captured_diff: str | None = None,
) -> dict[str, Any]:
    """Parse and score one Fix-Single native cell."""
    return _parse_patch_cell(
        stream,
        arm=arm,
        item=item,
        skill_path=skill_path,
        repo_path=repo_path,
        captured_diff=captured_diff,
        answer_re=_FIX_SINGLE_ANSWER_RE,
        query_arguments=_FIX_SINGLE_QUERY_ARGUMENTS,
        execute_patch=execute_fix_single_patch,
    )


def parse_fix_multi_cell(
    stream: str | bytes,
    *,
    arm: str,
    item: Mapping[str, Any],
    skill_path: Path | None,
    repo_path: Path,
    captured_diff: str | None = None,
) -> dict[str, Any]:
    """Parse and score one Fix-Multi native cell."""
    return _parse_patch_cell(
        stream,
        arm=arm,
        item=item,
        skill_path=skill_path,
        repo_path=repo_path,
        captured_diff=captured_diff,
        answer_re=_FIX_MULTI_ANSWER_RE,
        query_arguments=_FIX_MULTI_QUERY_ARGUMENTS,
        execute_patch=execute_fix_multi_patch,
    )


def _stage_input_recovery(repo_path: Path) -> str:
    """Return the least-destructive recovery for a failed executable input preflight."""
    if repo_path.resolve() == _MANAGED_PARITY_REPO:
        return (
            "The managed target's Git metadata is invalid or its locked index is stale. Preserve it by moving it aside, "
            "then let the no-model launcher reconstruct and verify the canonical pair:\n"
            "mv /private/tmp/codemap-provider-parity-pl-2.6.5 "
            '"/private/tmp/codemap-provider-parity-pl-2.6.5.invalid-$(date -u +%Y%m%dT%H%M%SZ)"\n'
            "bash benchmarks/run-all.sh codex --struct --tasks=FN-02 --dry-run"
        )
    return "Use the managed canonical repository and its manifest-locked index, then rerun this stage with --dry-run."


def _stage_source_binding(repo_path: Path, index_path: Path) -> dict[str, str]:
    """Validate and fingerprint the frozen source/index pair before paid admission."""
    structural = _structural()
    try:
        structural._validate_locked_runtime(repo_path, index_path, "C_skill_required", PARITY_MANIFEST_PATH)
    except ValueError as exc:
        raise ValueError(
            f"executable-stage input preflight failed: {exc}\n"
            "No paid model call was started. " + _stage_input_recovery(repo_path)
        ) from None
    return {
        "repo_path": str(repo_path.resolve()),
        "repo_sha256": hashlib.sha256(structural._repo_sha(repo_path).encode("utf-8")).hexdigest(),
        "index_path": str(index_path.resolve()),
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(PARITY_MANIFEST_PATH.read_bytes()).hexdigest(),
    }


def _resolve_scope(tasks: list[dict[str, Any]], model: str, source_binding: Mapping[str, str]) -> dict[str, Any]:
    """Bind one selected executable stage to immutable contracts, scorer, and source inputs."""
    payload: dict[str, Any] = {
        "arms": ARMS,
        "model": model,
        "stage_runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "invocation_launcher_sha256": hashlib.sha256(STRUCTURAL_PATH.read_bytes()).hexdigest(),
        "lifecycle_sha256": hashlib.sha256((BENCHMARKS / "_bench_codex" / "runtime.py").read_bytes()).hexdigest(),
        "task_ids": [item["contract"].task_id for item in tasks],
        "contracts": {item["contract"].task_id: dict(item["contract"].provider_binding()) for item in tasks},
        "source_binding": dict(source_binding),
    }
    payload["scope_sha256"] = _sha256(payload)
    return payload


def _require_paid_stage_request(
    *,
    study: str,
    repo_path: Path,
    task_ids: list[str],
    model: str,
    auth_source: Path | None,
    run_dir: Path | None,
    paid_approval: str | None,
    expected_scope: str,
    explicit_selection: bool = True,
) -> None:
    """Fail closed with the exact recovery command for an invalid paid request.

    Scope approval binds the runner, shared lifecycle, task contracts, and
    model. A code or contract change therefore intentionally invalidates an
    earlier approval before a model call can start.
    """
    missing = [
        flag
        for flag, present in (
            ("--auth-source", auth_source is not None),
            ("--run-dir", run_dir is not None),
            ("--paid-approval", paid_approval is not None),
        )
        if not present
    ]
    if missing:
        raise ValueError(
            f"cannot start paid {study} run; missing {', '.join(missing)}.\n"
            "Required form: --auth-source <auth.json> --run-dir <new-run-dir> "
            "--paid-approval <fresh-scope>."
        )
    if paid_approval == expected_scope:
        return
    task_selector = f" --tasks {','.join(task_ids)}" if explicit_selection else ""
    raise ValueError(
        f"paid {study} approval does not match the current immutable scope.\n"
        f"received --paid-approval: {paid_approval}\n"
        f"current scope: {expected_scope}\n"
        "The runner, lifecycle, or task contract changed after the earlier approval. "
        "No model call was made. Run the no-model preflight, then copy its emitted PAID_COMMAND exactly:\n"
        f"python3 benchmarks/run-codex-structural.py --repo-path {repo_path} "
        f"--model {model}{task_selector} --dry-run\n"
        "Do not reuse the previous --paid-approval value."
    )


def _suggested_run_dir(study: str) -> Path:
    """Return a non-reserved, collision-resistant relative result directory for a paid command."""
    return Path("benchmarks") / "results" / f"codex-{study}-{uuid4().hex[:12]}"


def _print_paid_command(
    *,
    study: str,
    repo_path: Path,
    index_path: Path,
    marketplace_root: Path,
    codemap_bin: Path,
    model: str,
    task_ids: list[str],
    scope_sha256: str,
    explicit_selection: bool,
) -> None:
    """Print the exact user-owned paid command admitted by a successful no-model preflight."""
    run_dir = _suggested_run_dir(study)
    tasks = ",".join(task_ids)
    print("PAID_COMMAND")
    print("python3 benchmarks/run-codex-structural.py \\")
    print(f"  --repo-path {repo_path.resolve()} \\")
    print(f"  --index-path {index_path.resolve()} \\")
    print(f"  --marketplace-root {marketplace_root.resolve()} \\")
    print(f"  --codemap-bin {codemap_bin.resolve()} \\")
    print(f"  --model {model} \\")
    if explicit_selection:
        print(f"  --tasks {tasks} \\")
    print('  --auth-source "$HOME/.codex/auth.json" \\')
    print(f"  --run-dir {run_dir} \\")
    print(f"  --paid-approval {scope_sha256}")


def resolve_fix_single_scope(
    tasks: list[dict[str, Any]], model: str, source_binding: Mapping[str, str]
) -> dict[str, Any]:
    """Resolve Fix-Single's paid-execution scope authorization."""
    return _resolve_scope(tasks, model, source_binding)


def resolve_fix_multi_scope(
    tasks: list[dict[str, Any]], model: str, source_binding: Mapping[str, str]
) -> dict[str, Any]:
    """Resolve Fix-Multi's paid-execution scope authorization."""
    return _resolve_scope(tasks, model, source_binding)


def _load_fix_stage(
    study: str, selected: set[str] | None
) -> tuple[
    list[dict[str, Any]],
    Path,
    Callable[[str, Mapping[str, Any]], str],
    Callable[..., dict[str, Any]],
    Callable[[Any, Mapping[str, Any]], None],
]:
    """Load one executable stage and its native prompt, parser, and validator."""
    if study == "fix-single":
        selected = selected or {str(task["id"]) for task in load_task_suite(FIX_SINGLE_TASKS_PATH)}
        return (
            load_fix_single_tasks(FIX_SINGLE_TASKS_PATH, selected),
            FIX_SINGLE_TASKS_PATH,
            fix_single_prompt,
            parse_fix_single_cell,
            validate_fix_single_binding,
        )
    if study == "fix-multi":
        selected = selected or {str(task["id"]) for task in load_task_suite(FIX_MULTI_TASKS_PATH)}
        return (
            load_fix_multi_tasks(FIX_MULTI_TASKS_PATH, selected),
            FIX_MULTI_TASKS_PATH,
            fix_multi_prompt,
            parse_fix_multi_cell,
            validate_fix_multi_binding,
        )
    raise ValueError("executable stage must be 'fix-single' or 'fix-multi'")


def resolve_fix_stage_scope(
    *,
    study: str,
    repo_path: Path,
    selected: set[str] | None,
    model: str,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve one executable stage without constructing a model adapter."""
    tasks, _, _, _, _ = _load_fix_stage(study, selected)
    index_path = index_path or repo_path / ".cache" / "codemap" / f"{repo_path.name}.json"
    return _resolve_scope(tasks, model, _stage_source_binding(repo_path, index_path))


def format_executable_result_row(row: Mapping[str, Any], completed: int, total: int) -> str:
    """Render one executable cell row while retaining detailed evidence on disk."""
    elapsed_s = row.get("elapsed_s")
    elapsed_text = runtime.fmt_time(float(elapsed_s)) if isinstance(elapsed_s, (int, float)) else "?"
    recovery = ""
    if row["execution"]["recount_recoverable"]:
        recovery = " recount=✓"
        if row["execution"]["recount_oracle_passed"] is not None:
            recovery += f" recount-oracle={'✓' if row['execution']['recount_oracle_passed'] else '✗'}"
    return (
        f"({completed}/{total}) {'✓' if row['pooling_eligible'] else '✗'}  {row['task_id']} {row['arm']:<8} "
        f"in={runtime.fmt_tok(row['input_tokens']):>6} out={runtime.fmt_tok(row['output_tokens']):>5} cmd={row['command_calls']:>2} "
        f"time={elapsed_text:>5} quality={'1.000' if row['primary_correct'] else '0.000'} "
        f"patch={'✓' if row['execution']['patch_applied'] else '✗'} oracle={'✓' if row['execution']['targeted_test_passed'] else '✗'} "
        f"codemap={'✓' if row['codemap_used'] else '✗'}{recovery}"
    )


def _print_executable_result_row(row: Mapping[str, Any], *, completed: int, total: int) -> None:
    """Route executable stage progress through the shared interactive arm renderer."""
    runtime.print_arm_row(format_executable_result_row(row, completed, total), str(row["arm"]))


def execute_executable_agent_cell(
    *,
    adapter: Any,
    source_repo: Path,
    source_index: Path,
    baseline_commit: str,
    native_arm: str,
    arm: str,
    prompt: str,
    item: Mapping[str, Any],
    parser: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Run one writable agent cell and score the captured canonical Git diff."""
    structural = _structural()
    workspace = structural.create_executable_agent_workspace(source_repo, source_index, baseline_commit)
    home = None
    row: dict[str, Any] | None = None
    started = time.monotonic()
    captured_diff = ""
    changed_paths: tuple[str, ...] = ()
    index_unchanged = False
    try:
        with structural.bind_executable_agent_workspace(adapter, workspace):
            home = adapter._prepare_verified_home(
                native_arm,
                writable_workspace=workspace.worktree,
                denied_workspace=source_repo,
                index_relocation=workspace.index_relocation,
            )
            stream = adapter._subprocess(adapter.build_command(prompt), home.env, working_directory=workspace.worktree)
            captured_diff, changed_paths = workspace.capture_diff(), workspace.changed_paths()
            row = parser(
                stream,
                arm=arm,
                item=item,
                skill_path=home.codemap_skill_path if arm == "C_strict" else None,
                repo_path=source_repo,
                captured_diff=captured_diff,
            )
            index_unchanged = workspace.index_unchanged()
    finally:
        try:
            if home is not None:
                if home.coordination_path is not None:
                    structural._cleanup_coordination_root(home.coordination_path)
                home.cleanup()
        finally:
            workspace_cleanup_verified = workspace.cleanup()
    source_unchanged = structural._repo_sha(source_repo) == baseline_commit and not structural._git_porcelain_status(
        source_repo
    )
    if row is None:
        raise RuntimeError("executable agent cell did not produce a scoreable result")
    row.update(
        {
            "elapsed_s": time.monotonic() - started,
            "captured_diff": captured_diff,
            "captured_diff_sha256": hashlib.sha256(captured_diff.encode("utf-8")).hexdigest(),
            "agent_workspace": {
                "changed_paths": list(changed_paths),
                "cleanup_verified": workspace_cleanup_verified,
                "index_relocation": dict(workspace.index_relocation),
                "index_unchanged": index_unchanged,
                "source_unchanged": source_unchanged,
            },
        }
    )
    if not workspace_cleanup_verified or not source_unchanged or not index_unchanged:
        reason = next(
            value
            for value, condition in (
                ("agent workspace cleanup failed", not workspace_cleanup_verified),
                ("source repository changed", not source_unchanged),
                ("derived frozen index changed", not index_unchanged),
            )
            if condition
        )
        row["success"] = row["primary_correct"] = row["pooling_eligible"] = False
        row["answer_error"] = "; ".join(value for value in (row["answer_error"], reason) if value)
    return row


def preflight_executable_agent_workspace(
    adapter: Any, *, source_repo: Path, source_index: Path, baseline_commit: str
) -> None:
    """Validate writable-worktree permissions for every arm without a model call."""
    structural = _structural()
    workspace = structural.create_executable_agent_workspace(source_repo, source_index, baseline_commit)
    try:
        for native_arm in NATIVE_ARMS.values():
            with structural.bind_executable_agent_workspace(adapter, workspace):
                home = adapter._prepare_verified_home(
                    native_arm,
                    writable_workspace=workspace.worktree,
                    denied_workspace=source_repo,
                    index_relocation=workspace.index_relocation,
                )
            try:
                pass
            finally:
                if home.coordination_path is not None:
                    structural._cleanup_coordination_root(home.coordination_path)
                home.cleanup()
    finally:
        if not workspace.cleanup():
            raise RuntimeError("executable agent workspace preflight cleanup failed")


def run_fix_stage(
    *,
    study: str,
    repo_path: Path,
    selected: set[str] | None,
    dry_run: bool,
    resolve_scope: bool,
    auth_source: Path | None,
    run_dir: Path | None,
    paid_approval: str | None,
    model: str,
    index_path: Path | None = None,
    marketplace_root: Path | None = None,
    codemap_bin: Path | None = None,
    emit_authorization: bool = True,
) -> None:
    """Run one complete executable study or an explicitly selected task subset."""
    explicit_selection = selected is not None
    tasks, suite_path, prompt, parser, validate = _load_fix_stage(study, selected)
    index_path = index_path or repo_path / ".cache" / "codemap" / f"{repo_path.name}.json"
    source_binding = _stage_source_binding(repo_path, index_path)
    admitted = _resolve_scope(tasks, model, source_binding)
    if resolve_scope:
        print(json.dumps(admitted, sort_keys=True))
        return
    if not dry_run:
        _require_paid_stage_request(
            study=study,
            repo_path=repo_path,
            task_ids=[item["contract"].task_id for item in tasks],
            model=model,
            auth_source=auth_source,
            run_dir=run_dir,
            paid_approval=paid_approval,
            expected_scope=admitted["scope_sha256"],
            explicit_selection=explicit_selection,
        )
    adapter = _structural().CodexRunner(
        model,
        repo_path,
        index_path=index_path,
        marketplace_root=marketplace_root or ROOT,
        codemap_bin=codemap_bin or ROOT / "plugins/codemap-py/bin/codemap-py",
        auth_source=auth_source,
    )
    if dry_run:
        try:
            preflight_executable_agent_workspace(
                adapter,
                source_repo=repo_path,
                source_index=index_path,
                baseline_commit=tasks[0]["contract"].baseline_commit,
            )
        finally:
            adapter.close()
        for item in tasks:
            for arm in ARMS:
                print(f"PLAN    {item['contract'].task_id} {arm}")
        if emit_authorization:
            print(f"SCOPE   {admitted['scope_sha256']}")
            _print_paid_command(
                study=study,
                repo_path=repo_path,
                index_path=index_path,
                marketplace_root=marketplace_root or ROOT,
                codemap_bin=codemap_bin or ROOT / "plugins/codemap-py/bin/codemap-py",
                model=model,
                task_ids=[item["contract"].task_id for item in tasks],
                scope_sha256=admitted["scope_sha256"],
                explicit_selection=explicit_selection,
            )
        return
    assert run_dir is not None
    try:
        preflight_executable_agent_workspace(
            adapter,
            source_repo=repo_path,
            source_index=index_path,
            baseline_commit=tasks[0]["contract"].baseline_commit,
        )
    except BaseException:
        adapter.close()
        raise

    def prepare_run(destination: Path) -> None:
        """Archive immutable stage inputs before the first native cell."""
        adapter.create_input_snapshot(
            destination,
            tasks_path=suite_path,
            manifest_path=PARITY_MANIFEST_PATH,
            runner_path=Path(__file__),
            invocation_launcher_path=STRUCTURAL_PATH,
            tasks=[item["task"] for item in tasks],
            arms=tuple(NATIVE_ARMS.values()),
            additional_shared_files={"codex-runtime.py": BENCHMARKS / "_bench_codex" / "runtime.py"},
        )

    def run_cell(item: Mapping[str, Any], arm: str) -> Mapping[str, Any]:
        """Execute one stage-owned task and arm inside the shared lifecycle."""
        return execute_executable_agent_cell(
            adapter=adapter,
            source_repo=repo_path,
            source_index=index_path,
            baseline_commit=item["contract"].baseline_commit,
            native_arm=NATIVE_ARMS[arm],
            arm=arm,
            prompt=prompt(arm, item["task"]),
            item=item,
            parser=parser,
        )

    def persist_metadata(path: Path, payload: Mapping[str, Any]) -> None:
        """Write the current executable-stage state as canonical JSON."""
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def emit_lifecycle(event: str, values: Mapping[str, Any]) -> None:
        """Print concise lifecycle evidence without adding ANSI escape codes."""
        if event == "artifacts":
            print(f"ARTIFACTS\n\ttelemetry={values['telemetry_path']}\n\tmetadata={values['metadata_path']}")
        else:
            print(
                f"SUMMARY  status={values['status']}  persisted_cells={values['persisted_cells']}/{values['total_cells']}"
            )

    run_paid_stage(
        tasks=tasks,
        arms=ARMS,
        run_dir=run_dir,
        metadata={"stage_id": study, "scope": admitted},
        callbacks=PaidStageCallbacks(
            run_cell=run_cell,
            validate_row=lambda item, _arm, row: validate(item["contract"], row["provider_binding"]),
            prepare_run=prepare_run,
            persist_metadata=persist_metadata,
            emit_lifecycle=emit_lifecycle,
            emit_row=lambda row, completed, total, _arm: _print_executable_result_row(
                row, completed=completed, total=total
            ),
            write_checksums=write_checksums,
            close_adapter=adapter.close,
        ),
    )
    print(f"done: {run_dir}")


def rescore_fix_stage(source_dir: Path, output_dir: Path, repo_path: Path, *, study: str | None = None) -> Path:
    """Reparse one checksummed executable stage, inferring its persisted scorer."""
    if output_dir.exists():
        raise FileExistsError(f"rescore output already exists: {output_dir}")
    verify_checksums(source_dir)
    source_metadata = json.loads((source_dir / "run-metadata.json").read_text(encoding="utf-8"))
    if source_metadata.get("status") != "completed":
        raise ValueError("only completed executable-stage runs can be rescored")
    persisted_stage = source_metadata.get("stage_id")
    if study is None:
        study = persisted_stage
    if study not in {"fix-single", "fix-multi"} or persisted_stage not in {None, study}:
        raise ValueError("offline executable rescore requires one consistent fix stage_id")
    source_rows = [
        json.loads(line) for line in (source_dir / "telemetry.jsonl").read_text(encoding="utf-8").splitlines() if line
    ]
    if not source_rows:
        raise ValueError("executable-stage result has no telemetry rows")
    selected = {str(row.get("task_id")) for row in source_rows}
    loader, suite_path, parser, validate = (
        (load_fix_single_tasks, FIX_SINGLE_TASKS_PATH, parse_fix_single_cell, validate_fix_single_binding)
        if study == "fix-single"
        else (load_fix_multi_tasks, FIX_MULTI_TASKS_PATH, parse_fix_multi_cell, validate_fix_multi_binding)
    )
    tasks = {item["contract"].task_id: item for item in loader(suite_path, selected)}
    for source_row in source_rows:
        captured_diff = source_row.get("captured_diff")
        if not isinstance(captured_diff, str) or not captured_diff.startswith("diff --git "):
            raise ValueError("source executable-stage telemetry lacks a captured Git diff")
    output_dir.mkdir(parents=True)
    print(f"ARTIFACTS\n\ttelemetry={output_dir / 'telemetry.jsonl'}\n\tmetadata={output_dir / 'run-metadata.json'}")
    persisted = 0
    with (output_dir / "telemetry.jsonl").open("x", encoding="utf-8") as output:
        for source_row in source_rows:
            task_id, arm, raw_events = source_row.get("task_id"), source_row.get("arm"), source_row.get("raw_events")
            if task_id not in tasks or arm not in ARMS or not isinstance(raw_events, list):
                raise ValueError("source executable-stage telemetry lacks a replayable task, arm, or native events")
            item = tasks[task_id]
            validate(item["contract"], source_row.get("provider_binding", {}))
            skill_path = (
                source_dir / "inputs/C_skill_required/codemap-py/codex-skills/query-code/SKILL.md"
                if arm == "C_strict"
                else None
            )
            if skill_path is not None and not skill_path.is_file():
                raise ValueError("source executable-stage snapshot lacks the frozen Codemap Skill")
            captured_diff = source_row["captured_diff"]
            row = parser(
                (json.dumps(event, sort_keys=True) for event in raw_events),
                arm=arm,
                item=item,
                skill_path=skill_path,
                repo_path=repo_path,
                captured_diff=captured_diff,
            )
            for field in ("input_tokens", "cached_input_tokens", "output_tokens", "tool_result_tokens"):
                if source_row.get(field) != row[field]:
                    raise ValueError(f"source executable-stage native {field} changed during reparse")
            row["elapsed_s"] = source_row.get("elapsed_s")
            row["source_telemetry_row_sha256"] = hashlib.sha256(
                json.dumps(source_row, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            output.write(json.dumps(row, sort_keys=True) + "\n")
            output.flush()
            persisted += 1
            _print_executable_result_row(row, completed=persisted, total=len(source_rows))
    (output_dir / "run-metadata.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "kind": f"offline-{study}-reparse-v2",
                "source_run_dir": str(source_dir.resolve()),
                "source_checksums_sha256": hashlib.sha256((source_dir / "checksums.sha256").read_bytes()).hexdigest(),
                "rescorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "persisted_cells": persisted,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_checksums(output_dir)
    print(f"SUMMARY  status=completed  persisted_cells={persisted}/{len(source_rows)}")
    return output_dir
