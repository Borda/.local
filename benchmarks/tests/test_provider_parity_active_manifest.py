"""Lock the post-pilot provider-parity manifest without running a model."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks import provider_parity_contracts as core


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
METHODOLOGY_MANIFEST = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
CODEX_MANIFEST = BENCHMARKS / "manifests" / "codex-integration.json"
METHODOLOGY_BUILDER = BENCHMARKS / "build-provider-parity-methodology-manifest.py"
ARCHIVED_MANIFEST = BENCHMARKS / "results" / "manifests" / ("provider-parity-v1-b0-" + "r" + "6.json")
ARCHIVED_MANIFEST_SHA256 = "971c6ad220c1e821ed72109396f4dce1d745f0a1b74b2790874f6b07e833627b"
README = BENCHMARKS / "README.md"
REPAIRED_SUITE_PATH = "benchmarks/suites/tasks-bench.json"
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


def _run_methodology_builder(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the provider-neutral relock utility without model or auth access."""
    return subprocess.run(
        [sys.executable, str(METHODOLOGY_BUILDER), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


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


def test_codex_manifest_uses_generic_task_selection_contract() -> None:
    """Codex selection is task/family based rather than diagnostic-mode based."""
    manifest = _load(CODEX_MANIFEST)
    selection = manifest["task_selection"]

    assert selection["selector_option"] == "--tasks"
    assert selection["separator"] == ","
    assert selection["study_mode"] == "selected_tasks"
    assert selection["nonpoolable"] is True
    assert selection["resolution_policy"]["exact_id_first"] is True
    assert selection["resolution_policy"]["deduplicate"].startswith("selector tokens")
    assert "post_fix_diagnostic" not in manifest


def test_methodology_builder_is_deterministic_and_check_mode_rejects_stale_output(tmp_path: Path) -> None:
    """The explicit relock path must reject stale output instead of repairing it implicitly."""
    builder = runpy.run_path(str(METHODOLOGY_BUILDER))
    output = tmp_path / "provider-parity-methodology.json"
    builder["_build_manifest"].__globals__["OUTPUT_MANIFEST"] = output
    expected = builder["_manifest_bytes"](builder["_build_manifest"]())

    try:
        builder["_write_or_check"](output, expected, check=True)
    except ValueError as error:
        assert "stale" in str(error)
    else:
        raise AssertionError("check mode accepted a missing methodology output")

    output.write_bytes(b"{}\n")
    try:
        builder["_write_or_check"](output, expected, check=True)
    except ValueError as error:
        assert "stale" in str(error)
    else:
        raise AssertionError("check mode accepted stale methodology output")

    builder["_write_or_check"](output, expected, check=False)
    builder["_write_or_check"](output, expected, check=True)
    assert expected == builder["_manifest_bytes"](builder["_build_manifest"]())


def test_methodology_builder_rejects_tampered_passthrough_policy_seed(tmp_path: Path) -> None:
    """A generated methodology file can never bootstrap changed policy into acceptance."""
    builder = runpy.run_path(str(METHODOLOGY_BUILDER))
    seed = _load(BENCHMARKS / "manifests" / "provider-parity-methodology-policy.json")
    seed["execution_controls"]["budget"] = "tampered"
    seed_path = tmp_path / "provider-parity-methodology-policy.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    builder["_load_policy_seed"].__globals__["POLICY_SEED"] = seed_path

    assert builder["main"](["--check"]) == 1


def test_methodology_builder_declares_exact_task_identity_change_ledger() -> None:
    """Every identity change from the immutable archive must be reviewed by task and field."""
    builder = runpy.run_path(str(METHODOLOGY_BUILDER))
    archive = _load(ARCHIVED_MANIFEST)
    expected = builder["_build_manifest"]()

    assert expected["methodology_change_ledger"] == builder["TASK_CHANGE_LEDGER"]
    assert builder["_changed_task_identity_fields"](archive, expected) == {
        task_id: entry["identity_fields"] for task_id, entry in builder["TASK_CHANGE_LEDGER"].items()
    }


def test_methodology_builder_output_is_current() -> None:
    """The committed provider-neutral source must equal the explicit deterministic relock output."""
    result = _run_methodology_builder("--check")

    assert result.returncode == 0, result.stderr


def _suites_by_path(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return manifest suites keyed by their unique source path."""
    suites = {suite["path"]: suite for suite in manifest["suites"]}
    assert len(suites) == len(manifest["suites"])
    return suites


def _assert_manifest_matches_materialized_suite_inputs(manifest: dict[str, Any]) -> None:
    """Bind every active task hash to the exact current provider-visible input."""
    semantic_hashes: dict[str, str] = {}
    for suite in manifest["suites"]:
        assert suite["raw_sha256"] == _sha256(ROOT / suite["path"])
        source_tasks = core.load_task_suite(ROOT / suite["path"])
        semantic_hashes[suite["path"]] = core.semantic_suite_hash(source_tasks)
        assert suite["semantic_suite_sha256"] == semantic_hashes[suite["path"]]
        assert [task["id"] for task in suite["tasks"]] == [task["id"] for task in source_tasks]
        for manifest_task, source_task in zip(suite["tasks"], source_tasks, strict=True):
            assert manifest_task["canonical_task_sha256"] == core.canonical_task_hash(source_task)
            assert manifest_task["prompt_sha256"] == core.prompt_hash(source_task)
    assert manifest["suite_integrity"]["semantic_suite_sha256"] == semantic_hashes


def test_methodology_manifest_allows_only_documented_input_repairs() -> None:
    """The shared committed source allows only the reviewed task repairs."""
    archived = _load(ARCHIVED_MANIFEST)
    methodology = _load(METHODOLOGY_MANIFEST)
    builder = runpy.run_path(str(METHODOLOGY_BUILDER))

    assert _sha256(ARCHIVED_MANIFEST) == ARCHIVED_MANIFEST_SHA256
    assert methodology["methodology_change_ledger"] == builder["TASK_CHANGE_LEDGER"]
    assert builder["_changed_task_identity_fields"](archived, methodology) == {
        task_id: entry["identity_fields"] for task_id, entry in builder["TASK_CHANGE_LEDGER"].items()
    }
    _assert_manifest_matches_materialized_suite_inputs(methodology)
    for field in ("target_source", "headline_structural_v1", "validation"):
        assert methodology[field] == archived[field]
    archived_index = archived["index"]
    active_index = methodology["index"]
    for field in ("git_sha", "module_count", "path", "project", "scan_root"):
        assert active_index[field] == archived_index[field]
    assert active_index == builder_index_lock()
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
    assert evaluation["prospective_product_acceptance"] == {
        "efficiency_path": {
            "c_a_gross_input_ratio_95_upper": "< 1.00",
            "c_a_paired_quality_mean": ">= 0.00",
            "c_a_paired_quality_95_lower": ">= -0.02",
        },
        "quality_path": {
            "c_a_gross_input_ratio_95_upper": "<= 1.05",
            "c_a_paired_quality_95_lower": "> 0",
        },
        "task_family_block": "Any repeated task-family mean C_skill-A_plain quality difference < -0.10 blocks acceptance.",
        "historical_evidence": "Historical nonpoolable evidence cannot satisfy this prospective policy.",
    }
    assert manifest["preregistered_cells"]["arm_order"] == (
        "sort arms by "
        "sha256(experiment_revision|provider|model|reasoning_effort|task_id|repetition|arm), "
        "ascending raw digest; Claude uses an empty effort coordinate"
    )


def builder_index_lock() -> dict[str, Any]:
    """Load the explicit scanner-schema lock from the methodology generator."""
    return runpy.run_path(str(METHODOLOGY_BUILDER))["INDEX_LOCK"]
