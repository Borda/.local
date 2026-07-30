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
MANIFESTS = BENCHMARKS / "results" / "manifests"
ACTIVE_MANIFEST = MANIFESTS / "provider-parity-v1.json"
ACTIVE_HUMAN_MANIFEST = MANIFESTS / "provider-parity-v1.md"
PREVIOUS_MANIFEST = MANIFESTS / "provider-parity-v1-b0-r6.json"
PREVIOUS_MANIFEST_SHA256 = "971c6ad220c1e821ed72109396f4dce1d745f0a1b74b2790874f6b07e833627b"
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
    authored_paths.extend([ACTIVE_MANIFEST, ACTIVE_HUMAN_MANIFEST])

    shorthand_paths = [path for path in authored_paths if re.search(r"(?:^|_)r[0-9]+(?:_|$)", path.name)]
    shorthand_content = [
        (path, match.group())
        for path in authored_paths
        if (match := SHORTHAND_REVISION.search(path.read_text(encoding="utf-8")))
    ]

    assert shorthand_paths == []
    assert shorthand_content == []


def _suite_identities(manifest: dict[str, Any]) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """Return task, prompt, and suite identities that cannot drift during relock."""
    return [
        (
            suite["path"],
            suite["raw_sha256"],
            [(task["id"], task["canonical_task_sha256"], task["prompt_sha256"]) for task in suite["tasks"]],
        )
        for suite in manifest["suites"]
    ]


def test_active_manifest_supersedes_an_exact_archive_without_input_drift() -> None:
    """The relock must preserve prior evidence and every canonical experiment input."""
    previous = _load(PREVIOUS_MANIFEST)
    active = _load(ACTIVE_MANIFEST)

    assert _sha256(PREVIOUS_MANIFEST) == PREVIOUS_MANIFEST_SHA256
    assert active["experiment_revision"] != previous["experiment_revision"]
    assert active["schema_version"] == 3
    assert active["status"].endswith("_manifest_review_required_before_paid_smoke")
    assert active["supersedes"]["experiment_revision"] == previous["experiment_revision"]
    assert active["supersedes"]["manifest_path"] == str(PREVIOUS_MANIFEST.relative_to(ROOT))
    assert active["supersedes"]["manifest_sha256"] == PREVIOUS_MANIFEST_SHA256
    assert active["supersedes"]["pooling_allowed"] is False
    assert active["supersedes"]["reason"]
    assert _suite_identities(active) == _suite_identities(previous)
    for field in ("target_source", "index", "arms", "headline_structural_v1", "validation"):
        assert active[field] == previous[field]
    for field in (
        "arms",
        "confirmatory_repetitions",
        "pilot_repetitions",
        "providers",
        "smoke_task_ids",
        "structural_confirmatory_task_ids",
        "structural_pilot_task_ids",
    ):
        assert active["preregistered_cells"][field] == previous["preregistered_cells"][field]


def test_active_manifest_locks_luna_high_and_exact_implementation_identities() -> None:
    """The reviewed manifest must bind the only allowed model and changed code bytes."""
    manifest = _load(ACTIVE_MANIFEST)
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
    assert manifest["codemap_plugin"]["launcher_contract"] == {
        "arms": ["B_auto", "C_required"],
        "environment_variable": "CODEMAP_BIN",
        "source": "installedPath returned by codex plugin add --json",
        "validation": "contained regular single-link executable with recorded SHA-256",
    }
    assert "CODEMAP_BIN" in manifest["codex_permission_profiles"]["shell_environment"]["set_allowlist"]


def test_active_manifest_locks_shared_continuous_fitness_and_observed_capability_strata() -> None:
    """Fitness and capability labels must be shared, explicit, and suite-derived."""
    manifest = _load(ACTIVE_MANIFEST)
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


def test_active_manifest_records_complete_no_model_acceptance_and_human_review_identity() -> None:
    """Review material must expose every no-model gate and the exact machine hash."""
    manifest = _load(ACTIVE_MANIFEST)
    checks = manifest["no_model_validation"]
    human = ACTIVE_HUMAN_MANIFEST.read_text(encoding="utf-8")
    manifest_sha = _sha256(ACTIVE_MANIFEST)

    assert checks["model_or_auth_used"] is False
    assert checks["status"] == "pass"
    assert checks["checks"] == {
        "a_plain_isolation": "pass",
        "b_auto_launcher_and_query": "pass",
        "c_required_launcher_and_query": "pass",
        "capability_strata": "pass",
        "effort_and_strict_config": "pass",
        "fitness_components": "pass",
        "launcher_provenance": "pass",
        "manifest_and_suite_identity": "pass",
    }
    assert f"# `{manifest['experiment_revision']}`" in human
    assert f"**Manifest SHA-256**: `{manifest_sha}`" in human
    assert f"`{PREVIOUS_MANIFEST_SHA256}`" in human
    assert "No paid model cell or authentication source was used." in human
    assert "review required before paid smoke" in human.lower()
