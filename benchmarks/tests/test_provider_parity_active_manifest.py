"""Lock the post-pilot provider-parity manifest without running a model."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks import provider_parity_contracts as core


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
METHODOLOGY_MANIFEST = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
ARCHIVED_MANIFEST = BENCHMARKS / "results" / "manifests" / "provider-parity-v1-b0-r6.json"
ARCHIVED_MANIFEST_SHA256 = "971c6ad220c1e821ed72109396f4dce1d745f0a1b74b2790874f6b07e833627b"
README = BENCHMARKS / "README.md"
REPAIRED_SUITE_PATH = "benchmarks/suites/tasks-bench.json"
PROMPT_ONLY_REPAIRS = frozenset({"RV-01", "RV-02", "RV-03", "RV-04"})
CANONICAL_AND_PROMPT_REPAIRS = frozenset({"RV-05", "CQ-01", "CQ-02", "CQ-03"})
SHORTHAND_REVISION = re.compile(
    r"(?<![A-Za-z0-9_-])r[0-9]+(?![A-Za-z0-9_-])|"
    r"(?<![A-Za-z0-9_-])r[0-9]+_(?=manifest|revision|lock|policy|profile|runtime|execution)"
)


def _sha256(path: Path) -> str:
    """Return the exact byte identity of one locked artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    """Load one machine manifest as a JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_authored_benchmark_files_use_complete_experiment_revision_names() -> None:
    """Prevent plan shorthand from leaking into authored benchmark paths or prose."""
    authored_paths = [
        path
        for path in BENCHMARKS.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".json", ".md", ".py", ".sh"}
        and BENCHMARKS / "results" not in path.parents
    ]
    authored_paths.append(METHODOLOGY_MANIFEST)

    shorthand_paths = [path for path in authored_paths if re.search(r"(?:^|_)r[0-9]+(?:_|$)", path.name)]
    shorthand_content = [
        (path, match.group())
        for path in authored_paths
        if (match := SHORTHAND_REVISION.search(path.read_text(encoding="utf-8")))
    ]

    assert shorthand_paths == []
    assert shorthand_content == []


def _suites_by_path(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return manifest suites keyed by their unique source path."""
    suites = {suite["path"]: suite for suite in manifest["suites"]}
    assert len(suites) == len(manifest["suites"])
    return suites


def _assert_repair_allowlist(previous: dict[str, Any], active: dict[str, Any]) -> None:
    """Allow only the seven documented task-identity repairs during relock."""
    previous_suites = _suites_by_path(previous)
    active_suites = _suites_by_path(active)

    assert list(active_suites) == list(previous_suites)
    for path, previous_suite in previous_suites.items():
        active_suite = active_suites[path]
        previous_tasks = previous_suite["tasks"]
        active_tasks = active_suite["tasks"]
        assert [task["id"] for task in active_tasks] == [task["id"] for task in previous_tasks]

        for previous_task, active_task in zip(previous_tasks, active_tasks, strict=True):
            task_id = active_task["id"]
            assert active_task["id"] == previous_task["id"]
            canonical_changed = active_task["canonical_task_sha256"] != previous_task["canonical_task_sha256"]
            prompt_changed = active_task["prompt_sha256"] != previous_task["prompt_sha256"]
            if task_id in PROMPT_ONLY_REPAIRS:
                assert path == REPAIRED_SUITE_PATH
                assert (canonical_changed, prompt_changed) == (False, True)
            elif task_id in CANONICAL_AND_PROMPT_REPAIRS:
                assert path == REPAIRED_SUITE_PATH
                assert (canonical_changed, prompt_changed) == (True, True)
            else:
                assert (canonical_changed, prompt_changed) == (False, False)


def _assert_manifest_matches_materialized_suite_inputs(manifest: dict[str, Any]) -> None:
    """Bind every active task hash to the exact current provider-visible input."""
    for suite in manifest["suites"]:
        assert suite["raw_sha256"] == _sha256(ROOT / suite["path"])
        source_tasks = core.load_task_suite(ROOT / suite["path"])
        assert [task["id"] for task in suite["tasks"]] == [task["id"] for task in source_tasks]
        for manifest_task, source_task in zip(suite["tasks"], source_tasks, strict=True):
            assert manifest_task["canonical_task_sha256"] == core.canonical_task_hash(source_task)
            assert manifest_task["prompt_sha256"] == core.prompt_hash(source_task)


def test_methodology_manifest_allows_only_documented_input_repairs() -> None:
    """The shared committed source allows only the reviewed task repairs."""
    archived = _load(ARCHIVED_MANIFEST)
    methodology = _load(METHODOLOGY_MANIFEST)

    assert _sha256(ARCHIVED_MANIFEST) == ARCHIVED_MANIFEST_SHA256
    _assert_repair_allowlist(archived, methodology)
    _assert_manifest_matches_materialized_suite_inputs(methodology)
    for field in ("target_source", "index", "headline_structural_v1", "validation"):
        assert methodology[field] == archived[field]
    for field in (
        "confirmatory_repetitions",
        "pilot_repetitions",
        "providers",
        "smoke_task_ids",
        "structural_confirmatory_task_ids",
        "structural_pilot_task_ids",
    ):
        assert methodology["preregistered_cells"][field] == archived["preregistered_cells"][field]


def test_archived_result_manifest_stays_immutable_and_unpoolable() -> None:
    """Historical evidence remains byte-locked and excluded from current pooling."""
    archived = _load(ARCHIVED_MANIFEST)

    assert _sha256(ARCHIVED_MANIFEST) == ARCHIVED_MANIFEST_SHA256
    readme = README.read_text(encoding="utf-8").lower()
    assert "historical evidence" in readme
    assert "never pooled" in readme
    assert archived["experiment_revision"]


def test_methodology_manifest_binds_every_review_subquestion_in_provider_prompt() -> None:
    """Review follow-ups must be hashed as delivered provider input, not evaluator-only metadata."""
    methodology = _load(METHODOLOGY_MANIFEST)
    suite = _suites_by_path(methodology)[REPAIRED_SUITE_PATH]
    manifest_tasks = {task["id"]: task for task in suite["tasks"]}
    source_tasks = {
        task["id"]: task for task in core.load_task_suite(ROOT / REPAIRED_SUITE_PATH) if task["id"].startswith("RV-")
    }

    assert source_tasks.keys() == {"RV-01", "RV-02", "RV-03", "RV-04", "RV-05"}
    for task_id, task in source_tasks.items():
        delivered = core.materialize_task_prompt(task)
        assert delivered != task["prompt"]
        for sub_question in task["sub_questions"]:
            assert sub_question["prompt"] in delivered
        assert manifest_tasks[task_id]["prompt_sha256"] == core.prompt_hash(task)


def test_methodology_manifest_locks_luna_high_and_exact_implementation_identities() -> None:
    """The shared methodology must bind the only allowed model and code bytes."""
    manifest = _load(METHODOLOGY_MANIFEST)
    implementation = manifest["implementation_contract"]

    assert implementation["codex_model_stratum"] == {
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "strict_config": True,
    }
    assert implementation["artifact_sha256"] == {
        "claude_query_skill": _sha256(ROOT / "plugins/codemap-py/claude-skills/query-code/SKILL.md"),
        "codemap_graph": _sha256(ROOT / "plugins/codemap-py/src/codemap_py/graph.py"),
        "codemap_query": _sha256(ROOT / "plugins/codemap-py/src/codemap_py/query.py"),
        "codex_query_skill": _sha256(ROOT / "plugins/codemap-py/codex-skills/query-code/SKILL.md"),
        "provider_parity_contracts": _sha256(BENCHMARKS / "provider_parity_contracts.py"),
        "run_all": _sha256(BENCHMARKS / "run-all.sh"),
        "run_claude_structural": _sha256(BENCHMARKS / "run-claude-structural.py"),
        "run_codex_structural": _sha256(BENCHMARKS / "run-codex-structural.py"),
    }
    assert "CODEMAP_BIN" in manifest["codex_permission_profiles"]["shell_environment"]["set_allowlist"]


def test_methodology_manifest_locks_shared_continuous_fitness_and_observed_capability_strata() -> None:
    """Fitness and capability labels must be shared, explicit, and suite-derived."""
    manifest = _load(METHODOLOGY_MANIFEST)
    evaluation = manifest["evaluation_contract"]
    tasks = core.load_task_suite(BENCHMARKS / "suites" / "tasks-bench.json")
    observed = Counter(stratum for task in tasks for stratum in core.capability_strata(task))

    assert evaluation["provider_neutral"] is True
    assert evaluation["quality_primary"] == "continuous task-family quality_score in [0,1]"
    assert evaluation["binary_guardrail"] == "correct"
    assert evaluation["components"] == ["recall", "caller_recall", "test_recall"]
    assert evaluation["precision_f1_status"] == "not reported without a frozen false-positive oracle"
    assert evaluation["capability_strata_counts"] == dict(sorted(observed.items()))
    assert manifest["preregistered_cells"]["arm_order"] == (
        "sort arms by "
        "sha256(experiment_revision|provider|model|reasoning_effort|task_id|repetition|arm), "
        "ascending raw digest; Claude uses an empty effort coordinate"
    )
