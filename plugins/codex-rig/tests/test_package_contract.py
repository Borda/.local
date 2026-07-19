"""Acceptance checks for the Codex Rig package contract."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / ".codex" / "plugin-package.json"


def load_contract() -> dict[str, object]:
    """Load the tracked Codex Rig package contract."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_freezes_exact_capability_rosters() -> None:
    """Prevent skill, role, and shim rosters from drifting silently."""
    contract = load_contract()

    assert len(contract["workflow_skills"]) == 13
    assert len(contract["all_skills"]) == 14
    assert len(contract["roles"]) == 15
    assert contract["manager_skill"] == "agent-shims"
    assert "kaggle" in contract["workflow_skills"]
    assert {"review", "resolve"}.isdisjoint(contract["all_skills"])

    source_skills = {
        path.parent.name
        for path in (REPO_ROOT / ".codex" / "skills").glob("*/SKILL.md")
        if path.parent.name != "_shared"
    }
    source_roles = {path.stem for path in (REPO_ROOT / ".codex" / "agents").glob("*.toml")}
    assert source_skills == set(contract["workflow_skills"])
    assert source_roles == set(contract["roles"])
    assert len(contract["shim_outputs"]) == len(set(contract["shim_outputs"])) == 15


def test_contract_sources_exist_and_destinations_are_unique() -> None:
    """Prevent missing sources and ambiguous package destinations."""
    contract = load_contract()
    mappings = contract["source_mappings"]
    destinations = [mapping["destination"] for mapping in mappings]

    assert len(destinations) == len(set(destinations))
    for mapping in mappings:
        assert (REPO_ROOT / mapping["source"]).exists(), mapping

    existing = contract["existing_sources"]
    discovered_skill_files = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / ".codex" / "skills").glob("**/*")
        if path.is_file() and path.parent.name != "_shared" and "__pycache__" not in path.parts
    )
    discovered_role_tomls = sorted(
        path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / ".codex" / "agents").glob("*.toml")
    )
    assert discovered_skill_files == existing["skill_files"]
    assert discovered_role_tomls == existing["role_tomls"]

    shared_root = REPO_ROOT / ".codex" / "skills" / "_shared"
    shared_files = sorted(path.name for path in shared_root.iterdir() if path.is_file())
    calibration_root = REPO_ROOT / ".codex" / "calibration"
    calibration_files = sorted(
        path.relative_to(calibration_root).as_posix()
        for path in calibration_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert shared_files == sorted(contract["shared_runtime"])
    assert calibration_files == sorted(contract["calibration_runtime"])


def test_contract_freezes_lifecycle_and_publication_limits() -> None:
    """Prevent lifecycle scope or distribution policy from widening implicitly."""
    contract = load_contract()
    lifecycle = contract["lifecycle"]
    publication = contract["publication"]

    assert lifecycle["scope"] == "user-only"
    assert lifecycle["platform_semantics"] == "doctor-proven-posix-local-filesystem"
    assert lifecycle["test_matrix"] == ["macos", "linux"]
    assert lifecycle["actions"] == ["doctor", "status", "install", "remove"]
    assert lifecycle["batch"] == "whole-roster"
    assert lifecycle["recovery"] == "rollback-only"
    assert lifecycle["mcp"] == "absent"
    assert {"windows", "network-filesystems", "project-scope"}.issubset(lifecycle["unsupported"])
    assert publication["marketplace"] == "borda-ai-rig"
    assert publication["repository"] == "https://github.com/Borda/AI-Rig"
    assert publication["license"] == "Apache-2.0"
    assert contract["release_profiles"]["0.1.0"] == {
        "manager": False,
        "hooks": False,
        "mcp": False,
        "generated_shims": False,
    }
    assert contract["runtime_gates"]["shared_marketplace_name_must_coexist_with_legacy_catalog"] is True


def test_contract_excludes_retired_and_machine_local_paths() -> None:
    """Prevent retired or machine-local payloads from entering the package."""
    contract = load_contract()
    exclusions = set(contract["excluded_paths"])

    assert ".codex/skills/review" in exclusions
    assert ".codex/skills/resolve" in exclusions
    assert ".codex/hooks/rtk-enforce.js" in exclusions
    assert ".codex/config.toml" in exclusions
    assert ".codex/AGENTS.md" in exclusions


def test_contract_separates_sources_from_planned_outputs() -> None:
    """Prevent future generated files from masquerading as current sources."""
    contract = load_contract()
    existing_paths = {path for group in contract["existing_sources"].values() for path in group}
    planned_paths = {item["path"] for item in contract["planned_outputs"]}

    assert existing_paths.isdisjoint(planned_paths)
    assert "plugins/codex-rig/package-manifest.json" in planned_paths
    assert any(item["rule"] == "generated-hashes-excluding-self" for item in contract["planned_outputs"])
