"""Regression checks for the Codex plain/CLI/Skill integration relock."""

from __future__ import annotations

import hashlib
import json
import re
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


def test_generator_is_current_and_never_rewrites_methodology_source() -> None:
    """The integration relock must be deterministic and preserve methodology."""
    before = _sha256(SOURCE_MANIFEST)
    result = _run_generator("--check")

    assert result.returncode == 0, result.stderr
    assert _sha256(SOURCE_MANIFEST) == before


def test_integration_manifest_reuses_every_canonical_suite_identity() -> None:
    """Task, suite, prompt, oracle, evaluator, target, and index identities cannot drift."""
    source = _load(SOURCE_MANIFEST)
    manifest = _load(MANIFEST)

    assert manifest["source_manifest"] == {
        "path": str(SOURCE_MANIFEST.relative_to(ROOT)),
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
    assert manifest["experiment_revision"] == "codex-integration-single-run-confirmatory-v1"
    assert manifest["preregistered_cells"]["arms"] == [
        "A_plain",
        "B_direct_required",
        "C_skill_required",
    ]
    assert manifest["preregistered_cells"]["providers"] == ["codex"]
    assert manifest["preregistered_cells"]["confirmatory_repetitions"] == 1
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
        "telemetry_contract_id": "canonical-skill-file-v1",
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
            "accepted_form": '"$CODEMAP_BIN" query --compact <subcommand> <arguments>',
            "item_scope": "dedicated native command item",
            "required_exit_code": 0,
            "required_output": "one JSON document with index.query_complete=true and index.compact=true",
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
            "B_direct_required": "at least one successful compact locked CLI query",
            "C_skill_required": ("dedicated exact Skill read item before at least one successful canonical query item"),
        },
    }


def test_integration_manifest_has_no_plan_shorthand_and_human_review_status() -> None:
    """Committed benchmark records use self-contained names and require human approval."""
    for path in (SOURCE_MANIFEST, GENERATOR, MANIFEST, HUMAN_MANIFEST):
        assert SHORTHAND.search(path.read_text(encoding="utf-8")) is None

    assert "results" not in MANIFEST.relative_to(ROOT).parts
    assert "results" not in HUMAN_MANIFEST.relative_to(ROOT).parts

    human = HUMAN_MANIFEST.read_text(encoding="utf-8")
    assert "# `codex-integration-v1`" in human
    assert "Runtime smoke and exact coordinate-plan validation are required before paid execution." in human
    assert "Human review is required before any further paid execution." in human
    assert "This manifest rebuild used no model cell or authentication source." in human
