"""Regression checks for the Codex plain/CLI/Skill integration relock."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
GENERATOR = BENCHMARKS / "build-codex-integration-manifest.py"
SOURCE_MANIFEST = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
MANIFEST = BENCHMARKS / "manifests" / "codex-integration.json"
HUMAN_MANIFEST = BENCHMARKS / "manifests" / "codex-integration.md"
SHORTHAND = re.compile(r"(?<![A-Za-z0-9_-])r[0-9]+(?![A-Za-z0-9_-])")


def _sha256(path: Path) -> str:
    """Return the exact byte identity for one relock input or output."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    """Load one machine-readable benchmark manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    """Execute the relock utility without invoking a model or authentication."""
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_builder_locks_optional_query_arguments_ordering_and_cache_policy() -> None:
    """Builder output must replace inherited query, ordering, and token-reporting drift."""
    builder = runpy.run_path(str(GENERATOR))
    source = _load(SOURCE_MANIFEST)
    arm_order = (
        "deterministic six-permutation counterbalancing by frozen structural task ordinal; "
        "across the 55-task single-repetition execution suite, every arm occupies every ordinal 18 or 19 times"
    )
    token_prompt_cache_policy = (
        "Console and primary efficiency reports use gross provider input tokens only. "
        "Cached and fresh input counts are retained as raw telemetry diagnostics. "
        "The Codex CLI exposes no supported per-cell provider prompt-cache reset or disable control. "
        "Deterministic arm-order counterbalancing mitigates order exposure without claiming cache elimination."
    )

    arms = builder["_arms"]()
    controls = builder["_execution_controls"](source)
    cells = builder["_preregistered_cells"](source)
    task_selection = builder["_task_selection_contract"](source)
    telemetry = builder["_telemetry_admission"]()
    human_manifest = {
        "codemap_candidate": {"package_manifest_sha256": "0" * 64, "version": "test"},
        "codex_cli": {"available": False},
        "codex_rig_candidate": {"version": "test"},
        "execution_controls": controls,
        "task_selection": task_selection,
        "preregistered_cells": cells,
        "source_manifest": {"path": "test.json", "sha256": "0" * 64},
    }
    human = builder["_human_bytes"](human_manifest, "0" * 64).decode("utf-8")

    assert builder["EXPERIMENT_REVISION"] == "codex-integration-prospective-locked-query-components-2026-08-04"
    assert arms["B_direct_required"]["requirement"] == (
        "Run at least one successful compact direct query in its own native command item containing exactly "
        '"$CODEMAP_BIN" query --compact <subcommand> [arguments]; '
        "additional reads and shell work are allowed as separate items."
    )
    assert telemetry["query"]["accepted_form"] == '"$CODEMAP_BIN" query --compact <subcommand> [arguments]'
    assert controls["arm_order"] == arm_order
    assert cells["arm_order"] == arm_order
    assert controls["token_prompt_cache_policy"] == token_prompt_cache_policy
    assert task_selection["repetitions"] == 3
    assert task_selection["coordinate_timeout_seconds"] == 600
    assert task_selection["nonpoolable"] is True
    assert task_selection["allowed_task_ids"] == cells["structural_execution_task_ids"]
    assert task_selection["allowed_families"] == list(
        dict.fromkeys(task_id.split("-", 1)[0] for task_id in cells["structural_execution_task_ids"])
    )
    assert task_selection["resolution_policy"]["exact_id_first"] is True
    assert task_selection["resolution_policy"]["deduplicate"].startswith("selector tokens")
    assert task_selection["scope_digest"]["runtime_derived"] is True
    assert task_selection["scope_digest"]["stored_in_manifest"] is False
    assert '`"$CODEMAP_BIN" query --compact <subcommand> [arguments]`' in human
    assert "every arm occupies every ordinal 18 or 19 times" in human
    assert "Console and primary efficiency reports use gross provider input tokens only." in human
    assert "without claiming cache elimination" in human
    assert "--tasks=DI,GR" in human
    assert "--tasks=DI-01,GR-03" in human
    assert "--tasks=DI,GR-03" in human
    assert "cannot authorize or replace the full scope" in human


def test_generator_is_current_and_never_rewrites_methodology_source() -> None:
    """The integration relock must be deterministic and preserve methodology."""
    before = _sha256(SOURCE_MANIFEST)
    result = _run_generator("--check")

    assert result.returncode == 0, result.stderr
    assert _sha256(SOURCE_MANIFEST) == before


def test_generated_manifest_uses_environment_neutral_cli_and_posix_paths() -> None:
    """Generated records cannot contain host paths or Windows separators."""
    manifest = _load(MANIFEST)
    assert manifest["codex_cli"] == {
        "available": True,
        "path": "<codex-cli>",
        "version": "codex-cli 0.146.0",
    }
    assert manifest["source_manifest"]["path"] == "benchmarks/manifests/provider-parity-methodology.json"
    assert "\\" not in manifest["source_manifest"]["path"]


def test_cli_identity_is_a_host_neutral_reviewed_lock() -> None:
    """Manifest checks must use the reviewed CLI identity on every runner."""
    builder = runpy.run_path(str(GENERATOR))
    assert builder["LOCKED_CODEX_CLI_VERSION"] == "codex-cli 0.146.0"
    assert builder["_codex_cli_identity"]() == {
        "available": True,
        "path": "<codex-cli>",
        "version": "codex-cli 0.146.0",
    }


def test_generator_stale_error_names_exact_rebuild_command(tmp_path: Path) -> None:
    """Internal check mode must identify the command that repairs generated drift."""
    generator = runpy.run_path(str(GENERATOR))

    try:
        generator["_write_or_check"](tmp_path / "stale.json", b"expected\n", True)
    except ValueError as exc:
        assert str(exc).endswith("run: python3 benchmarks/build-codex-integration-manifest.py")
    else:
        raise AssertionError("stale integration output was accepted")


def test_integration_manifest_reuses_every_canonical_suite_identity() -> None:
    """Task, suite, prompt, oracle, evaluator, target, and index identities cannot drift."""
    source = _load(SOURCE_MANIFEST)
    manifest = _load(MANIFEST)

    assert manifest["source_manifest"] == {
        "path": SOURCE_MANIFEST.relative_to(ROOT).as_posix(),
        "sha256": _sha256(SOURCE_MANIFEST),
    }
    for key in (
        "evaluation_contract",
        "headline_structural_v1",
        "index",
        "oracle_remediation",
        "suite_integrity",
        "suites",
        "target_source",
        "validation",
    ):
        assert manifest[key] == source[key]


def test_integration_manifest_locks_plain_cli_and_skill_arms_and_artifacts() -> None:
    """Only the three planned Codex arms and their exact package bytes are eligible."""
    manifest = _load(MANIFEST)

    assert list(manifest["arms"]) == ["A_plain", "B_direct_required", "C_skill_required"]
    assert manifest["model"] == {"name": "gpt-5.6-luna", "reasoning_effort": "high", "strict_config": True}
    assert manifest["estimands"] == {
        "C_skill_required-A_plain": "product effect",
        "B_direct_required-A_plain": "direct CLI effect",
        "C_skill_required-B_direct_required": "integration effect",
    }
    assert manifest["package_roster"] == ["codemap-py", "codex-rig"]
    assert manifest["experiment_id"] == "codex-integration-v1"
    assert manifest["schema_version"] == "codex-integration-manifest-v2"
    assert manifest["experiment_revision"] == "codex-integration-prospective-locked-query-components-2026-08-04"
    assert manifest["preregistered_cells"]["arms"] == [
        "A_plain",
        "B_direct_required",
        "C_skill_required",
    ]
    assert manifest["preregistered_cells"]["providers"] == ["codex"]
    assert manifest["preregistered_cells"]["confirmatory_repetitions"] == 1
    assert manifest["preregistered_cells"]["arm_order"] == (
        "deterministic six-permutation counterbalancing by frozen structural task ordinal; "
        "across the 55-task single-repetition execution suite, every arm occupies every ordinal 18 or 19 times"
    )
    assert len(manifest["preregistered_cells"]["structural_confirmatory_task_ids"]) == 45
    assert len(manifest["preregistered_cells"]["structural_execution_task_ids"]) == 55
    assert len(manifest["preregistered_cells"]["structural_diagnostic_task_ids"]) == 10
    assert set(manifest["preregistered_cells"]["structural_execution_task_ids"]) == (
        set(manifest["preregistered_cells"]["structural_confirmatory_task_ids"])
        | set(manifest["preregistered_cells"]["structural_diagnostic_task_ids"])
    )
    assert not set(manifest["preregistered_cells"]["structural_confirmatory_task_ids"]) & set(
        manifest["preregistered_cells"]["structural_diagnostic_task_ids"]
    )
    assert manifest["codex_permission_profiles"]["treatment"]["arms"] == [
        "B_direct_required",
        "C_skill_required",
    ]
    assert manifest["codex_permission_profiles"]["treatment_runtime"]["scope"] == [
        "B_direct_required",
        "C_skill_required",
    ]
    assert manifest["codex_permission_profiles"]["host_tooling_isolation"] == {
        "access": "deny",
        "arms": ["A_plain", "B_direct_required", "C_skill_required"],
        "roots": ["<host-home>/.agents", "<host-home>/.claude", "<host-home>/.codex"],
        "verification": "no-model directory enumeration must fail without emitting entries",
    }
    assert manifest["codex_permission_profiles"]["marketplace_source_access"] == {
        "A_plain": "deny",
        "B_direct_required": "deny after the locked direct runtime is staged inside its disposable home",
        "C_skill_required": "deny",
    }
    assert manifest["execution_controls"]["parity_timeout_seconds"] == 600
    assert manifest["execution_controls"]["coordinate_timeout_scope"] == (
        "one total 600-second budget shared by the initial attempt and at most two eligible retries"
    )
    assert manifest["execution_controls"]["complete_run_wall_clock"] == (
        "paid execution requires a positive human-approved --max-wall-clock-seconds value; "
        "the exact value is recorded in every result row"
    )
    assert manifest["execution_controls"]["confirmatory_max_wall_clock_seconds"] == 86_400
    assert manifest["execution_controls"]["arm_order"] == (
        "deterministic six-permutation counterbalancing by frozen structural task ordinal; "
        "across the 55-task single-repetition execution suite, every arm occupies every ordinal 18 or 19 times"
    )
    assert manifest["execution_controls"]["token_prompt_cache_policy"] == (
        "Console and primary efficiency reports use gross provider input tokens only. "
        "Cached and fresh input counts are retained as raw telemetry diagnostics. "
        "The Codex CLI exposes no supported per-cell provider prompt-cache reset or disable control. "
        "Deterministic arm-order counterbalancing mitigates order exposure without claiming cache elimination."
    )
    assert manifest["codex_rig_integration_admission"]["required_before_paid_smoke"] == [
        "C installs exactly the locked codemap-py then codex-rig package roster.",
        "The Codex Rig adapter resolves the public CODEMAP_BIN launcher before PATH.",
        "One persisted compact-query context is available without Codemap cache or source reads.",
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["codemap_candidate"]["package_manifest_sha256"])
    assert set(manifest["artifact_sha256"]) == {
        "codemap_candidate_manifest",
        "codemap_query_skill",
        "codemap_runtime_cli",
        "codemap_runtime_entrypoint",
        "codemap_runtime_graph",
        "codemap_runtime_integration",
        "codemap_runtime_query",
        "codex_rig_adapter",
        "codex_rig_contract",
        "codex_rig_integration_host",
        "codex_rig_package_manifest",
        "codex_rig_plugin_manifest",
        "prepare_codex_index",
        "run_all",
        "run_codex_structural",
    }
    assert manifest["implementation_contract"]["artifact_sha256"] == manifest["artifact_sha256"]
    direct_runtime = manifest["direct_cli_runtime"]
    assert direct_runtime["staged_root"] == "<disposable-CODEX_HOME>/direct-cli"
    assert set(direct_runtime["files"]) >= {
        "bin/codemap-py",
        "bin/_exclusions.py",
        "scripts/codemap_py_entry.py",
        "src/codemap_py/query.py",
    }
    assert re.fullmatch(r"[0-9a-f]{64}", direct_runtime["aggregate_sha256"])
    assert manifest["direct_cli_admission"] == {
        "probe_subcommand": "fn-rdeps",
        "probe_target": "lightning.pytorch.trainer.call::_call_lightning_module_hook",
        "required_before_paid_execution": (
            "Execute this compact query through B's staged launcher under the treatment permission profile; "
            "require exit 0, index.query_complete=true, and unchanged locked-index bytes."
        ),
    }
    validation = manifest["no_model_validation"]
    assert validation["model_or_auth_used"] is False
    assert validation["status"] == "runtime_smoke_required_before_paid_execution"
    assert set(validation["checks"].values()) == {"required"}
    assert len(validation["evidence"]) == 2
    assert manifest["telemetry_admission"] == {
        "telemetry_contract_id": "canonical-skill-file-locked-query-components-v2",
        "run_metadata_schema": "codex-structural-run-metadata-v2",
        "auxiliary_item_policy": (
            "B/C may use additional reads and shell commands as separate native items. "
            "They are ignored for query attribution."
        ),
        "raw_result_policy": (
            "Raw JSONL cells are immutable. Parser corrections produce a separately versioned derived evaluation."
        ),
        "rejected_evidence": [
            "launcher inspection without query execution",
            "aliases, assignments, conditionals, compound shell, redirections, substitutions, or nested shells",
            "literal-path, sed, dynamic-range, unquoted-variable, wrong-variable, or reassigned Skill readers",
            "partial, wrong-path, wrong-byte, failed, or non-dedicated Skill reads",
            "Skill reads that occur after the query",
            "query output that is not one JSON document with complete compact index evidence",
            "exact-path or non-CODEMAP_BIN launcher forms",
        ],
        "query": {
            "accepted_form": '"$CODEMAP_BIN" query --compact <subcommand> [arguments]',
            "item_scope": "dedicated native command item",
            "required_exit_code": 0,
            "required_output": "one JSON document with index.query_complete=true and index.compact=true",
        },
        "locked_query_components": {
            "conformance": "locked_query_conformance",
            "overall": "locked_query_fitness",
            "endpoint": "locked_query_endpoint_fitness",
            "target": "locked_query_target_fitness",
            "options": "locked_query_option_fitness",
            "semantics": "Conformance is exact tuple agreement; fitness is continuous component-level Jaccard similarity.",
        },
        "skill_read": {
            "accepted_readers": ['cat "$CODEMAP_SKILL_FILE"'],
            "arm": "C_skill_required",
            "environment_binding": ("runner-owned immutable exact installed query Skill path; absent from A and B"),
            "item_scope": "dedicated native command item",
            "ordering": "before the credited query item",
            "required_output": "exact manifest-locked codemap_query_skill bytes",
        },
        "treatment_attribution": {
            "B_direct_required": "at least one successful compact direct CLI query",
            "C_skill_required": ("dedicated exact Skill read item before at least one successful canonical query item"),
        },
    }


def test_integration_manifest_locks_generic_nonpoolable_task_selection() -> None:
    """Selected task studies are generic, deterministic, and nonpoolable."""
    manifest = _load(MANIFEST)
    scope = manifest["task_selection"]

    execution_ids = manifest["preregistered_cells"]["structural_execution_task_ids"]
    assert scope["selector_option"] == "--tasks"
    assert scope["separator"] == ","
    assert scope["allowed_task_ids"] == execution_ids
    assert scope["allowed_families"] == list(dict.fromkeys(task_id.split("-", 1)[0] for task_id in execution_ids))
    assert scope["resolution_policy"] == {
        "exact_id_first": True,
        "family_match": "a family token selects every matching allowed ID",
        "order": "resolved IDs preserve frozen structural_execution_task_ids order",
        "deduplicate": "selector tokens and overlapping expanded IDs are evaluated once",
        "reject": ["empty tokens", "unknown task IDs", "unknown families"],
    }
    assert scope["arms"] == ["A_plain", "B_direct_required", "C_skill_required"]
    assert scope["repetitions"] == 3
    assert scope["coordinate_timeout_seconds"] == 600
    assert scope["complete_run_max_wall_clock_seconds"] == {
        "derived_at_runtime": True,
        "formula": "resolved_task_count × repetitions × arm_count × coordinate_timeout_seconds",
    }
    assert scope["nonpoolable"] is True
    assert scope["pooling_eligibility"] == "ineligible"
    assert scope["confirmatory_product_acceptance"] == "ineligible"
    assert scope["study_mode"] == "selected_tasks"
    assert scope["scope_digest"] == {
        "canonical_fields": [
            "active manifest SHA-256",
            "resolved ordered task IDs",
            "repetitions",
            "arms",
            "coordinate timeout seconds",
            "derived complete-run wall-clock ceiling",
        ],
        "runtime_derived": True,
        "stored_in_manifest": False,
    }

    human = HUMAN_MANIFEST.read_text(encoding="utf-8")
    assert "## Selected-task scope" in human
    assert "--tasks=DI,GR" in human
    assert "--tasks=DI-01,GR-03" in human
    assert "--tasks=DI,GR-03" in human
    assert "duplicate tokens and overlapping expansions are evaluated once" in human
    assert "derived at runtime" in human
    assert "## Paid selected-task command" in human
    assert "bash benchmarks/run-all.sh codex --struct --tasks=DI,GR" in human
    selected_section = human.split("## Paid selected-task command", 1)[1].split("## Confirmatory execution", 1)[0]
    assert "CODEX_PAID_APPROVAL=<resolved-scope-sha256>" in selected_section
    assert f"CODEX_PAID_APPROVAL={_sha256(MANIFEST)}" not in selected_section
    assert "copy its `selection scope` SHA-256" in selected_section
    assert "--resolve-tasks DI,GR" in selected_section
    assert "# Alternatively" not in selected_section
    assert "post-fix diagnostic" not in human
    assert human.index("## Paid selected-task command") < human.index("## Confirmatory execution")


def test_integration_manifest_has_no_plan_shorthand_and_explicit_launch_authorization() -> None:
    """Committed records use self-contained names and a manifest-bound launch authorization."""
    for path in (SOURCE_MANIFEST, GENERATOR, MANIFEST, HUMAN_MANIFEST):
        assert SHORTHAND.search(path.read_text(encoding="utf-8")) is None

    assert "results" not in MANIFEST.relative_to(ROOT).parts
    assert "results" not in HUMAN_MANIFEST.relative_to(ROOT).parts

    human = HUMAN_MANIFEST.read_text(encoding="utf-8")
    assert "# `codex-integration-v1`" in human
    assert '`"$CODEMAP_BIN" query --compact <subcommand> [arguments]`' in human
    assert "every arm occupies every ordinal 18 or 19 times" in human
    assert "Console and primary efficiency reports use gross provider input tokens only." in human
    assert "without claiming cache elimination" in human
    assert "Runtime smoke and exact coordinate-plan validation are required before paid execution." in human
    assert "## Confirmatory execution" in human
    assert "no separate chat authorization is required" in human
    assert "CODEX_PAID_APPROVAL" in human
    assert "bash benchmarks/run-all.sh codex --struct --dry-run" in human
    assert "immutable, user-owned `0600` auth source" in human
    assert "Do not run a concurrent Codex session with it" in human
    assert "independently authenticated benchmark credential" in human
    assert "The runner keeps private run state and atomically propagates valid refreshes between cells." in human
    assert "reauthenticate after the run if needed" in human
    assert "Known refresh-token authentication failures stop immediately" in human
    assert (
        "three matching unknown zero-token pre-response failures preserve partial artifacts and stop scheduling"
        in human
    )
    assert "This manifest rebuild used no model cell or authentication source." in human
