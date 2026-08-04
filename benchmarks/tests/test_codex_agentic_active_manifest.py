"""No-model checks for the Codex BA-01 agentic manifest."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
BUILDER = BENCHMARKS / "build-codex-agentic-manifest.py"
MANIFEST = BENCHMARKS / "manifests" / "codex-agentic.json"
HUMAN_MANIFEST = BENCHMARKS / "manifests" / "codex-agentic.md"


def _load(path: Path) -> dict[str, Any]:
    """Load one generated machine manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    """Return one exact artifact digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_builder(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the deterministic builder without model or credential inputs."""
    return subprocess.run(
        [sys.executable, str(BUILDER), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_manifest_is_current_and_regeneration_is_byte_stable() -> None:
    """Generation followed by check must reproduce identical machine and human bytes."""
    builder = runpy.run_path(str(BUILDER))
    manifest = builder["_build_manifest"]()
    machine_before = builder["_json_bytes"](manifest)
    human_before = builder["_human_bytes"](manifest, hashlib.sha256(machine_before).hexdigest())
    assert machine_before == MANIFEST.read_bytes()
    assert human_before == HUMAN_MANIFEST.read_bytes()
    assert _run_builder("--check").returncode == 0


def test_manifest_locks_ba01_scope_and_shared_identity() -> None:
    """The locked scope is exactly BA-01, three arms, three repetitions, and nine cells."""
    manifest = _load(MANIFEST)
    assert manifest["experiment_id"] == "codex-agentic-ba01"
    assert manifest["model"] == {"name": "gpt-5.6-luna", "reasoning_effort": "high", "strict_config": True}
    assert manifest["task"]["id"] == "BA-01"
    assert manifest["task"]["type"] == "blast_radius_analysis"
    assert manifest["task"]["primary_module"] == "lightning.pytorch.callbacks.timer"
    assert len(manifest["task"]["prompt"]) > 200
    scope = manifest["preregistered_scope"]
    assert scope["task_ids"] == ["BA-01"]
    assert scope["arms"] == ["A_plain", "B_auto", "C_required"]
    assert scope["repetitions"] == 3
    assert scope["total_cells"] == 9
    assert scope["coordinate_timeout_seconds"] == 600
    assert scope["complete_run_max_wall_clock_seconds"] == 5400
    assert scope["nonpoolable"] is True
    assert scope["pooling_eligibility"] == "ineligible; exploratory evidence only"
    assert manifest["target_source"]["tag"] == "2.6.5"
    assert manifest["target_source"]["commit"] == "be98784a1a03581b7051a355ae1084fd352d7cea"
    assert manifest["frozen_index_contract"]["raw_sha256"] == (
        "2d48a5ea4ddc3830f83de950713580bbc2e2dd3b43d1326f047cd3e21acec1eb"
    )


def test_manifest_has_exact_shared_scoring_and_plugin_hashes() -> None:
    """The scorer formulas and all integration/runtime identities are explicit."""
    manifest = _load(MANIFEST)
    assert manifest["scoring"]["implementation"]["symbol"] == "GroundTruth.score"
    assert manifest["scoring"]["metrics"] == {
        "EREC": "erec_tp / max(len(expected), 1)",
        "E@10": "top10_tp / max(len(top10), 1)",
        "RREC": "rrec_tp / max(len(expected), 1)",
        "DEFF": "erec_tp / max(tool_calls, 1)",
    }
    hashes = manifest["artifact_sha256"]
    assert len(hashes) == 12
    assert all(len(value) == 64 for value in hashes.values())
    assert manifest["plugin_runtime"]["source_hashes"] == hashes
    assert manifest["plugin_runtime"]["codemap_version"] == "0.28.3"
    assert manifest["plugin_runtime"]["codex_rig_version"] == "0.4.1"
    assert manifest["runtime_isolation"]["manifest"] == "benchmarks/manifests/codex-integration.json"
    assert manifest["runtime_isolation"]["mapping"]["B_auto"].endswith("use remains optional")
    assert "run_all" in hashes
    assert manifest["artifact_package"]["required_files"] == [
        "run.log",
        "telemetry.jsonl (raw)",
        "telemetry-canonical.jsonl",
        "run-metadata.json",
        "inputs/ (frozen input snapshot)",
        "checksums.sha256",
    ]


def test_arm_admission_semantics_are_explicit() -> None:
    """Optional B use and required C Skill sequencing remain distinguishable."""
    arms = _load(MANIFEST)["arms"]
    assert arms["A_plain"]["codemap_available"] is False
    assert arms["B_auto"]["no_call_valid"] is True
    assert "adoption" in arms["B_auto"]["requirement"]
    assert arms["C_required"]["no_call_valid"] is False
    assert arms["C_required"]["row_retained_on_noncompliance"] is True
    assert "installed Skill" in arms["C_required"]["requirement"]


def test_manifest_contains_no_credentials_or_ignored_historical_paths() -> None:
    """The lock cannot leak auth material or point at result/history artifacts."""
    text = MANIFEST.read_text(encoding="utf-8") + HUMAN_MANIFEST.read_text(encoding="utf-8")
    lowered = text.lower()
    for forbidden in ("password", "secret", "api_key", 'codex_auth_source="/users/'):
        assert forbidden not in lowered
    assert 'CODEX_AUTH_SOURCE="$HOME/.codex/auth.json"' in text
    assert 'CODEX_AUTH_SOURCE="/Users/' not in text
    assert "benchmarks/results" not in MANIFEST.read_text(encoding="utf-8")
    assert "results/manifests" not in text
    assert "historical/" not in text
    assert "__pycache__" not in text
    assert "first-slice" not in lowered
    assert "manifest sha-256" in HUMAN_MANIFEST.read_text(encoding="utf-8").lower()


def test_runner_accepts_exact_manifest_authorization() -> None:
    """The runner and generated admission contract must accept only the exact lock hash."""
    runner = runpy.run_path(str(BENCHMARKS / "run-codex-agentic.py"))
    manifest_hash = _sha256(MANIFEST)
    admitted = runner["validate_paid_admission"](MANIFEST, manifest_hash)
    assert admitted["admission"]["paid_execution"] == "admitted"
    with pytest.raises(ValueError, match="exact current manifest"):
        runner["validate_paid_admission"](MANIFEST, "0" * 64)
