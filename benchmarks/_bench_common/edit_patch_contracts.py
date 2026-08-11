"""Define provider-neutral contracts for mutable edit and patch benchmark stages.

Provider adapters may transport a prompt and report execution facts, but they
cannot change a task's oracle, score, exclusions, answer wire contract, or
stage identity. This module does not create a worktree or execute a command;
the mutation lifecycle is owned by the runner boundary in P0.4.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from .provider_parity_contracts import canonical_task_hash, prompt_hash


_SHA256_RE = re.compile(r"[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40}$")
_DIFF_FENCE_RE = re.compile(r"```diff\\s*\\n(?P<diff>.*?)\\n?```", re.DOTALL)
_SCORER_VERSION = "provider-neutral-edit-score-v1"
_FIX_MULTI_SCORER_VERSION = "provider-neutral-fix-multi-score-v2"
_FIX_MULTI_BASELINE_COMMIT = "be98784a1a03581b7051a355ae1084fd352d7cea"
_FIX_MULTI_ROOT = "src/lightning/pytorch"
_FIX_MULTI_PATHS = {
    "FM-01": (f"{_FIX_MULTI_ROOT}/callbacks/early_stopping.py",),
    "FM-02": (f"{_FIX_MULTI_ROOT}/callbacks/model_checkpoint.py",),
    "FM-03": tuple(
        f"{_FIX_MULTI_ROOT}/strategies/{name}.py"
        for name in ("strategy", "ddp", "fsdp", "deepspeed", "model_parallel", "single_xla", "xla")
    ),
}
_EXCLUSIONS = MappingProxyType(
    {
        "excluded_from_pooling_when": (
            "patch_not_applied",
            "targeted_test_failed",
            "regression_test_missing_or_failed",
            "changed_path_boundary_failed",
            "answer_envelope_invalid",
        ),
        "diagnostic_only": ("expected_path_recall", "keyword_recall"),
    }
)


@dataclass(frozen=True)
class StageIdentity:
    """Immutable identity of a separately reported benchmark stage."""

    stage: str
    revision: str
    task_suite_sha256: str
    contract_sha256: str

    def __post_init__(self) -> None:
        """Reject malformed identity coordinates before they enter evidence."""
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("stage must be a non-empty string")
        if not isinstance(self.revision, str) or not self.revision:
            raise ValueError("stage revision must be a non-empty string")
        for name, value in (("task_suite_sha256", self.task_suite_sha256), ("contract_sha256", self.contract_sha256)):
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    @property
    def sha256(self) -> str:
        """Return the hash of this complete immutable stage coordinate."""
        return _sha256(
            {
                "schema": "provider-parity-stage-identity-v1",
                "stage": self.stage,
                "revision": self.revision,
                "task_suite_sha256": self.task_suite_sha256,
                "contract_sha256": self.contract_sha256,
            }
        )


@dataclass(frozen=True)
class EditTaskContract:
    """Scientific contract for one mutable task, independent of provider transport."""

    task_id: str
    task_type: str
    canonical_task_sha256: str
    prompt_sha256: str
    baseline_commit: str
    expected_paths: tuple[str, ...]
    targeted_test_command: str
    regression_test_commands: tuple[str, ...]
    diagnostic_keywords: tuple[str, ...]
    answer_contract_sha256: str
    oracle_sha256: str
    scorer_sha256: str
    exclusions_sha256: str

    def scientific_field_hashes(self, stage_identity: StageIdentity) -> Mapping[str, str]:
        """Return the exact provider-invariant hashes an adapter must preserve."""
        return MappingProxyType(
            {
                "canonical_task_sha256": self.canonical_task_sha256,
                "prompt_sha256": self.prompt_sha256,
                "answer_contract_sha256": self.answer_contract_sha256,
                "oracle_sha256": self.oracle_sha256,
                "scorer_sha256": self.scorer_sha256,
                "exclusions_sha256": self.exclusions_sha256,
                "stage_identity_sha256": stage_identity.sha256,
            }
        )


@dataclass(frozen=True)
class PatchAnswer:
    """A strictly parsed unified-diff answer returned by one provider."""

    diff: str
    sha256: str


@dataclass(frozen=True)
class EditExecution:
    """Observed, runner-produced facts after one patch candidate executes."""

    patch_applied: bool
    targeted_test_passed: bool
    regression_test_passed: bool | None
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class EditScore:
    """Primary and safety outcomes without promoting diagnostic evidence."""

    primary_correct: bool
    safety_passed: bool
    changed_path_boundary_passed: bool
    pooling_eligible: bool
    diagnostics: Mapping[str, float]


@dataclass(frozen=True)
class FixMultiContract:
    """Immutable multi-caller contract shared by provider transports."""

    task_id: str
    canonical_task_sha256: str
    prompt_sha256: str
    baseline_commit: str
    expected_paths: tuple[str, ...]
    oracle_sha256: str
    scorer_sha256: str

    def provider_binding(self) -> Mapping[str, str]:
        """Return science-bearing fields every provider must preserve."""
        return MappingProxyType(
            {
                "canonical_task_sha256": self.canonical_task_sha256,
                "prompt_sha256": self.prompt_sha256,
                "baseline_commit": self.baseline_commit,
                "oracle_sha256": self.oracle_sha256,
                "scorer_sha256": self.scorer_sha256,
            }
        )


def build_fix_multi_contract(task: Mapping[str, Any]) -> FixMultiContract:
    """Freeze one canonical multi-file task and its complete-caller oracle."""
    task_id = task.get("id")
    if not isinstance(task_id, str) or task_id not in _FIX_MULTI_PATHS or task.get("type") != "fix_multicaller":
        raise ValueError("unknown fix-multi task")
    if not isinstance(task.get("expected_files"), list):
        raise ValueError(f"task {task_id} must retain its canonical expected-files field")
    oracle = {"task_id": task_id, "paths": _FIX_MULTI_PATHS[task_id], "semantics": "complete-caller AST oracle"}
    return FixMultiContract(
        task_id=task_id,
        canonical_task_sha256=canonical_task_hash(task),
        prompt_sha256=prompt_hash(task),
        baseline_commit=_FIX_MULTI_BASELINE_COMMIT,
        expected_paths=_FIX_MULTI_PATHS[task_id],
        oracle_sha256=_sha256(oracle),
        scorer_sha256=_sha256({"version": _FIX_MULTI_SCORER_VERSION, "primary": "complete_callers_and_ast_contract"}),
    )


def validate_fix_multi_binding(contract: FixMultiContract, observed: Mapping[str, object]) -> None:
    """Reject provider evidence that changes a shared task, oracle, or score field."""
    if dict(observed) != dict(contract.provider_binding()):
        raise ValueError("provider adapter changed fix-multi scientific fields")


def run_fix_multi_oracle(repo_path: Path, contract: FixMultiContract) -> bool:
    """Return whether every required caller and method contract is satisfied."""
    trees = {path: ast.parse((repo_path / path).read_text(encoding="utf-8")) for path in contract.expected_paths}
    if contract.task_id == "FM-01":
        return _check_early_stopping(next(iter(trees.values())))
    if contract.task_id == "FM-02":
        return _check_model_checkpoint(next(iter(trees.values())))
    return _check_strategy_callers(trees)


def _check_early_stopping(tree: ast.Module) -> bool:
    """Require an observe-only parameter, branch, and explicit false at each caller."""
    cls = _class(tree, "EarlyStopping")
    method = _method(cls, "_run_early_stopping_check")
    callers = _self_calls(cls, "_run_early_stopping_check")
    return (
        _parameter_false(method, "dry_run")
        and len(callers) == 2
        and all(_keyword_false(call, "dry_run") for call in callers)
        and _observe_only_dry_run_branch(method)
    )


def _check_model_checkpoint(tree: ast.Module) -> bool:
    """Require explicit checkpoint provenance and a log at the persistence boundary."""
    cls = _class(tree, "ModelCheckpoint")
    method = _method(cls, "_save_checkpoint")
    callers = _self_calls_by_method(cls, "_save_checkpoint")
    expected_reasons = {
        "on_exception": "exception",
        "_save_last_checkpoint": "last",
        "_save_none_monitor_checkpoint": "none",
        "_update_best_and_save": "top_k",
    }
    return (
        _parameter_empty_string(method, "reason")
        and set(callers) == set(expected_reasons)
        and all(
            len(calls) == 1 and _keyword_exact_string(calls[0], "reason", reason)
            for caller, reason in expected_reasons.items()
            for calls in (callers.get(caller, []),)
        )
        and _reason_log_precedes_save(method)
    )


def _check_strategy_callers(trees: Mapping[str, ast.Module]) -> bool:
    """Require the base and every declared override to propagate verbose."""
    names = {
        f"{_FIX_MULTI_ROOT}/strategies/strategy.py": "Strategy",
        f"{_FIX_MULTI_ROOT}/strategies/ddp.py": "DDPStrategy",
        f"{_FIX_MULTI_ROOT}/strategies/fsdp.py": "FSDPStrategy",
        f"{_FIX_MULTI_ROOT}/strategies/deepspeed.py": "DeepSpeedStrategy",
        f"{_FIX_MULTI_ROOT}/strategies/model_parallel.py": "ModelParallelStrategy",
        f"{_FIX_MULTI_ROOT}/strategies/single_xla.py": "SingleDeviceXLAStrategy",
        f"{_FIX_MULTI_ROOT}/strategies/xla.py": "XLAStrategy",
    }
    methods = {path: _method(_class(trees[path], name), "setup") for path, name in names.items()}
    base_path = f"{_FIX_MULTI_ROOT}/strategies/strategy.py"
    return (
        _parameter_false(methods[base_path], "verbose")
        and _verbose_log_present(methods[base_path])
        and all(
            _parameter_false(method, "verbose") and _super_verbose_call_present(method)
            for path, method in methods.items()
            if path != base_path
        )
    )


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    """Return a named top-level class or reject malformed candidate source."""
    node = next((item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name), None)
    if node is None:
        raise ValueError(f"candidate lacks class {name}")
    return node


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    """Return a named direct method or reject malformed candidate source."""
    node = next((item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == name), None)
    if node is None:
        raise ValueError(f"candidate lacks method {cls.name}.{name}")
    return node


def _parameter_false(method: ast.FunctionDef, name: str) -> bool:
    """Require one parameter with the exact false default."""
    pairs = list(zip(method.args.args[-len(method.args.defaults) :], method.args.defaults))
    return any(
        arg.arg == name and isinstance(default, ast.Constant) and default.value is False for arg, default in pairs
    )


def _parameter_empty_string(method: ast.FunctionDef, name: str) -> bool:
    """Require one parameter with the exact empty-string default."""
    pairs = list(zip(method.args.args[-len(method.args.defaults) :], method.args.defaults))
    return any(arg.arg == name and isinstance(default, ast.Constant) and default.value == "" for arg, default in pairs)


def _self_calls(cls: ast.ClassDef, method_name: str) -> list[ast.Call]:
    """Return every internal self call excluding the target method body."""
    calls = []
    for method in (item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name != method_name):
        calls.extend(_calls_to_self_method(method, method_name))
    return calls


def _self_calls_by_method(cls: ast.ClassDef, method_name: str) -> dict[str, list[ast.Call]]:
    """Return each direct method's internal calls to the target method."""
    calls_by_method: dict[str, list[ast.Call]] = {}
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef) or method.name == method_name:
            continue
        calls = _calls_to_self_method(method, method_name)
        if calls:
            calls_by_method[method.name] = calls
    return calls_by_method


def _calls_to_self_method(method: ast.FunctionDef, method_name: str) -> list[ast.Call]:
    """Return all direct self calls to one named method within a method body."""
    return [
        call
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr == method_name
    ]


def _keyword_false(call: ast.Call, name: str) -> bool:
    """Return whether a call explicitly supplies false for one keyword."""
    return any(
        keyword.arg == name and isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        for keyword in call.keywords
    )


def _keyword_exact_string(call: ast.Call, name: str, expected: str) -> bool:
    """Return whether a call supplies the one contractually required string."""
    return any(
        keyword.arg == name and isinstance(keyword.value, ast.Constant) and keyword.value.value == expected
        for keyword in call.keywords
    )


def _observe_only_dry_run_branch(method: ast.FunctionDef) -> bool:
    """Require a decision-bearing dry-run path isolated from persistent mutation."""
    branches = [
        node
        for node in method.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "dry_run"
    ]
    if len(branches) != 1:
        return False
    branch = branches[0]
    branch_index = method.body.index(branch)
    prior_text = "\n".join(ast.unparse(node) for node in method.body[:branch_index])
    dry_run_text = "\n".join(ast.unparse(node) for node in branch.body)
    following_text = "\n".join(ast.unparse(node) for node in method.body[branch_index + 1 :])
    returns_from_dry_run = any(isinstance(node, ast.Return) for node in branch.body)
    if returns_from_dry_run:
        normal_path_text = "\n".join(ast.unparse(node) for node in branch.orelse) + following_text
    elif branch.orelse:
        normal_path_text = "\n".join(ast.unparse(node) for node in branch.orelse)
    else:
        return False
    writes_state = "trainer.should_stop" in dry_run_text or "self.stopped_epoch" in dry_run_text
    mutated_before_branch = "trainer.should_stop" in prior_text or "self.stopped_epoch" in prior_text
    dry_run_falls_through_to_mutation = not returns_from_dry_run and (
        "trainer.should_stop" in following_text or "self.stopped_epoch" in following_text
    )
    preserves_normal_mutations = "trainer.should_stop" in normal_path_text and "self.stopped_epoch" in normal_path_text
    has_decision_log = any(
        isinstance(node, ast.Call)
        and ("log." in ast.unparse(node.func) or "_log_info" in ast.unparse(node.func))
        and "should_stop" in ast.unparse(node)
        and "reason" in ast.unparse(node)
        for node in ast.walk(branch)
    )
    return (
        not writes_state
        and not mutated_before_branch
        and not dry_run_falls_through_to_mutation
        and preserves_normal_mutations
        and has_decision_log
    )


def _reason_log_precedes_save(method: ast.FunctionDef) -> bool:
    """Require a reason-and-path log immediately before checkpoint persistence."""
    body = method.body
    for index, node in enumerate(body[:-1]):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Name) or node.test.id != "reason":
            continue
        if not any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "rank_zero_info"
            and "reason" in ast.unparse(child)
            and "filepath" in ast.unparse(child)
            for child in ast.walk(node)
        ):
            return False
        following = body[index + 1]
        return (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Call)
            and isinstance(following.value.func, ast.Attribute)
            and isinstance(following.value.func.value, ast.Name)
            and following.value.func.value.id == "trainer"
            and following.value.func.attr == "save_checkpoint"
        )
    return False


def _verbose_log_present(method: ast.FunctionDef) -> bool:
    """Require verbose-gated base setup logging without fixing message wording."""
    return any(
        isinstance(node, ast.If) and "verbose" in ast.unparse(node.test) and "log.debug" in ast.unparse(node)
        for node in method.body
    )


def _super_verbose_call_present(method: ast.FunctionDef) -> bool:
    """Require an override to pass verbose into immediate base setup."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setup"
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "super"
        and any(
            keyword.arg == "verbose" and isinstance(keyword.value, ast.Name) and keyword.value.id == "verbose"
            for keyword in node.keywords
        )
        for node in ast.walk(method)
    )


def build_edit_task_contract(task: Mapping[str, Any]) -> EditTaskContract:
    """Validate one mutable task and freeze its shared scientific fields.

    A task must name its exact baseline commit, expected changed paths, one
    targeted executable test, and any relevant safety-test commands. Keyword
    and path recall remain diagnostics and are never the primary oracle.
    """
    task_id = _required_string(task, "id")
    task_type = _required_string(task, "type")
    baseline_commit = _required_string(task, "pre_fix_commit")
    if _GIT_COMMIT_RE.fullmatch(baseline_commit) is None:
        raise ValueError("pre_fix_commit must be a lowercase 40-character Git commit")
    targeted_test_command = _required_string(task, "test_command")
    expected_paths = _required_string_sequence(task, "gt_files_changed")
    regression_test_commands = _required_string_sequence(task, "regression_test_commands")
    diagnostic_keywords = _optional_string_sequence(task, "expected_patch_keywords")
    answer_contract = {
        "format": "one_fenced_unified_diff",
        "required_fence": "diff",
        "requires_apply": True,
    }
    oracle = {
        "primary": ("patch_applied", "targeted_test_passed"),
        "safety": "regression_test_passed",
        "expected_paths": expected_paths,
        "targeted_test_command": targeted_test_command,
        "regression_test_commands": regression_test_commands,
    }
    return EditTaskContract(
        task_id=task_id,
        task_type=task_type,
        canonical_task_sha256=canonical_task_hash(task),
        prompt_sha256=prompt_hash(task),
        baseline_commit=baseline_commit,
        expected_paths=expected_paths,
        targeted_test_command=targeted_test_command,
        regression_test_commands=regression_test_commands,
        diagnostic_keywords=diagnostic_keywords,
        answer_contract_sha256=_sha256(answer_contract),
        oracle_sha256=_sha256(oracle),
        scorer_sha256=_sha256({"version": _SCORER_VERSION}),
        exclusions_sha256=_sha256(dict(_EXCLUSIONS)),
    )


def assess_patch_answer(text: str) -> PatchAnswer:
    """Extract exactly one non-empty fenced unified diff, else fail closed."""
    if not isinstance(text, str):
        raise TypeError("patch answer text must be a string")
    sections = text.split("```diff")
    if len(sections) != 2:
        raise ValueError("patch answer requires exactly one fenced diff block")
    _, fenced = sections
    if not fenced.startswith("\n") or fenced.count("```") != 1:
        raise ValueError("patch answer requires exactly one fenced diff block")
    diff, _ = fenced.split("```", maxsplit=1)
    # Preserve unified-diff context markers. In particular, a trailing blank
    # source line is encoded as ``" \n"`` and ``strip()`` would silently turn
    # an otherwise valid hunk into a corrupt patch.
    diff = diff[1:]
    if diff.endswith("\n"):
        diff = diff[:-1]
    if not diff.startswith("diff --git "):
        raise ValueError("patch answer must contain a unified diff")
    return PatchAnswer(diff=diff, sha256=hashlib.sha256(diff.encode("utf-8")).hexdigest())


def score_edit_execution(contract: EditTaskContract, answer: PatchAnswer, execution: EditExecution) -> EditScore:
    """Score executable patch evidence while retaining heuristic recall as diagnostics."""
    if not isinstance(contract, EditTaskContract):
        raise TypeError("contract must be an EditTaskContract")
    if not isinstance(answer, PatchAnswer):
        raise TypeError("answer must be a PatchAnswer")
    if not isinstance(execution, EditExecution):
        raise TypeError("execution must be an EditExecution")
    changed_paths = _normalized_paths(execution.changed_paths)
    expected_paths = set(contract.expected_paths)
    changed_path_boundary_passed = set(changed_paths) == expected_paths
    primary_correct = execution.patch_applied and execution.targeted_test_passed
    safety_passed = execution.regression_test_passed is True
    diagnostics = MappingProxyType(
        {
            "expected_path_recall": _recall(expected_paths, set(changed_paths)),
            "keyword_recall": _keyword_recall(contract.diagnostic_keywords, answer.diff),
        }
    )
    return EditScore(
        primary_correct=primary_correct,
        safety_passed=safety_passed,
        changed_path_boundary_passed=changed_path_boundary_passed,
        pooling_eligible=primary_correct and safety_passed and changed_path_boundary_passed,
        diagnostics=diagnostics,
    )


def validate_provider_binding(
    contract: EditTaskContract,
    stage_identity: StageIdentity,
    reported_hashes: Mapping[str, str],
) -> None:
    """Reject a provider adapter that changes any scientific contract field."""
    expected = contract.scientific_field_hashes(stage_identity)
    if dict(reported_hashes) != dict(expected):
        raise ValueError("provider adapter changed provider-neutral scientific fields")


def compare_stage_identities(expected: Mapping[str, StageIdentity], observed: Mapping[str, StageIdentity]) -> None:
    """Fail closed when a new stage changes immutable earlier-stage identity."""
    if set(expected) != set(observed):
        raise ValueError("prior-stage identity set changed")
    for stage, prior in expected.items():
        if observed[stage] != prior:
            raise ValueError(f"prior-stage identity changed for {stage!r}")


def stage_contract_sha256(contracts: Sequence[EditTaskContract]) -> str:
    """Return the ordered provider-neutral scientific-contract digest for a stage."""
    task_ids = [contract.task_id for contract in contracts]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("stage contracts contain duplicate task ids")
    return _sha256(
        {
            "schema": "provider-neutral-edit-stage-v1",
            "contracts": [
                {
                    "task_id": contract.task_id,
                    "canonical_task_sha256": contract.canonical_task_sha256,
                    "prompt_sha256": contract.prompt_sha256,
                    "baseline_commit": contract.baseline_commit,
                    "expected_paths": contract.expected_paths,
                    "targeted_test_command": contract.targeted_test_command,
                    "regression_test_commands": contract.regression_test_commands,
                    "answer_contract_sha256": contract.answer_contract_sha256,
                    "oracle_sha256": contract.oracle_sha256,
                    "scorer_sha256": contract.scorer_sha256,
                    "exclusions_sha256": contract.exclusions_sha256,
                }
                for contract in contracts
            ],
        }
    )


def _required_string(task: Mapping[str, Any], field: str) -> str:
    """Return one non-empty task string field."""
    value = task.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"task requires non-empty {field}")
    return value


def _required_string_sequence(task: Mapping[str, Any], field: str) -> tuple[str, ...]:
    """Return a unique non-empty task string-list field."""
    value = _optional_string_sequence(task, field)
    if not value:
        raise ValueError(f"task requires non-empty {field}")
    return value


def _optional_string_sequence(task: Mapping[str, Any], field: str) -> tuple[str, ...]:
    """Return an optional unique string-list task field."""
    value = task.get(field)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"task {field} must be a string list")
    if len(set(value)) != len(value):
        raise ValueError(f"task {field} must not contain duplicates")
    return tuple(value)


def _normalized_paths(paths: Sequence[str]) -> tuple[str, ...]:
    """Validate and normalize one observed changed-path sequence."""
    if any(not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/") for path in paths):
        raise ValueError("changed paths must be non-empty relative paths")
    return tuple(dict.fromkeys(paths))


def _recall(expected: set[str], observed: set[str]) -> float:
    """Return expected-set recall, with no empty oracle allowed upstream."""
    return len(expected & observed) / len(expected)


def _keyword_recall(keywords: Sequence[str], diff: str) -> float:
    """Return diagnostic keyword recall without making it a correctness gate."""
    if not keywords:
        return 1.0
    return sum(keyword in diff for keyword in keywords) / len(keywords)


def _sha256(payload: Mapping[str, Any]) -> str:
    """Serialize one immutable contract payload into a canonical digest."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
