"""Regression checks for intentionally networked CLI approval ownership."""

import json
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SHARED_CONTRACT = PLUGIN_ROOT / "shared" / "native-skill-contract.md"
GLOBAL_INSTRUCTIONS = PLUGIN_ROOT / "assets" / "AGENTS.md"
BEHAVIORAL_CASES = PLUGIN_ROOT / "runtime" / "calibration" / "behavioral-cases.json"
README = PLUGIN_ROOT / "README.md"
CHANGELOG = PLUGIN_ROOT / "CHANGELOG.md"


@pytest.mark.parametrize(
    ("skill_name", "network_marker"),
    [
        ("analyse", "github_read.py"),
        ("calibrate", "run_live_ab.py"),
        ("code-remediate", "collect_pr.py"),
        ("code-review", "collect_pr.py"),
        ("kaggle", "kaggle competitions list -p 1"),
        ("release", "github_read.py"),
        ("sync", "codex plugin marketplace upgrade"),
    ],
)
def test_networked_cli_skills_require_complete_owning_command_approval(
    skill_name: str,
    network_marker: str,
) -> None:
    """Keep every designed shell-network path behind one owning-command approval."""
    skill = (PLUGIN_ROOT / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")

    assert network_marker in skill
    assert "complete owning command" in skill or "complete collector command" in skill
    assert '`sandbox_permissions="require_escalated"`' in skill
    assert "never enable persistent workspace network access" in skill


def test_shared_contract_covers_known_networked_cli_families() -> None:
    """Prevent a new workflow from narrowing approval to a nested executable."""
    contract = SHARED_CONTRACT.read_text(encoding="utf-8")

    assert "Networked CLI Approval" in contract
    assert "complete owning command" in contract
    assert '`sandbox_permissions="require_escalated"`' in contract
    assert "never enable persistent workspace network access" in contract.lower()
    for marker in ("`gh`", "`kaggle`", "`git fetch`", "Codex Git marketplace", "`codex exec`"):
        assert marker in contract
    assert "marketplace add/upgrade" in contract
    assert "`codex plugin add` from a configured marketplace snapshot" in contract


def test_missing_kaggle_cli_remains_user_owned_setup() -> None:
    """Never turn a missing optional CLI into a workflow-owned installation."""
    kaggle_skill = (PLUGIN_ROOT / "skills" / "kaggle" / "SKILL.md").read_text(encoding="utf-8")
    contract = SHARED_CONTRACT.read_text(encoding="utf-8")
    instructions = GLOBAL_INSTRUCTIONS.read_text(encoding="utf-8")
    public_docs = README.read_text(encoding="utf-8") + CHANGELOG.read_text(encoding="utf-8")

    kaggle_policy = kaggle_skill.lower()
    assert "do not install it" in kaggle_policy
    assert "ask the user to install and authenticate" in kaggle_policy
    for text in (kaggle_skill, contract, instructions, public_docs):
        assert "pip install kaggle" not in text
        assert "approved Kaggle package installation" not in text
        assert "approved package installation" not in text
        assert "approved package-install" not in text


def test_shipped_global_instructions_keep_network_blocked_by_default() -> None:
    """Keep the installed agent policy aligned with the skill-level contract."""
    instructions = GLOBAL_INSTRUCTIONS.read_text(encoding="utf-8")

    assert "complete owning command" in instructions
    assert '`sandbox_permissions="require_escalated"`' in instructions
    assert "never enable persistent workspace network access" in instructions


def test_calibration_rejects_persistent_or_nested_only_network_approval() -> None:
    """Keep the generalized approval contract in behavioral calibration."""
    payload = json.loads(BEHAVIORAL_CASES.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in payload["cases"]}

    case = cases["develop-networked-cli-owning-command-approval"]
    assert case["target"] == "develop"
    assert case["expected_findings"] == [
        "complete-owning-command-network-approval-missing",
        "missing-kaggle-cli-setup-not-user-owned",
        "persistent-workspace-network-enabled",
        "nested-network-cli-approval-scope-invalid",
    ]
