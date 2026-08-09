"""Define provider-neutral contracts for mutable edit and patch benchmark stages.

Provider adapters may transport a prompt and report execution facts, but they
cannot change a task's oracle, score, exclusions, answer wire contract, or
stage identity. This module does not create a worktree or execute a command;
the mutation lifecycle is owned by the runner boundary in P0.4.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any

try:
    from provider_parity_contracts import canonical_task_hash, prompt_hash
except ModuleNotFoundError:
    from benchmarks.provider_parity_contracts import canonical_task_hash, prompt_hash


_SHA256_RE = re.compile(r"[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40}$")
_DIFF_FENCE_RE = re.compile(r"```diff\\s*\\n(?P<diff>.*?)\\n?```", re.DOTALL)
_SCORER_VERSION = "provider-neutral-edit-score-v1"
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
    diff = diff.strip()
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
