"""Acceptance checks for the complete plugin-only Codex Rig release."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "analyse",
    "audit",
    "calibrate",
    "code-remediate",
    "code-review",
    "develop",
    "investigate",
    "kaggle",
    "manage",
    "optimize",
    "release",
    "research",
    "sync",
)
EXPECTED_ROLES = {
    "challenger": ("gpt-5.6-terra", "read-only"),
    "cicd-steward": ("gpt-5.6-luna", "workspace-write"),
    "curator": ("gpt-5.6-terra", "workspace-write"),
    "data-steward": ("gpt-5.6-terra", "workspace-write"),
    "delegation-lead": ("gpt-5.6-luna", "workspace-write"),
    "doc-scribe": ("gpt-5.6-luna", "workspace-write"),
    "linting-expert": ("gpt-5.6-luna", "workspace-write"),
    "oss-shepherd": ("gpt-5.6-luna", "read-only"),
    "qa-specialist": ("gpt-5.6-terra", "workspace-write"),
    "scientist": ("gpt-5.6-terra", "workspace-write"),
    "security-auditor": ("gpt-5.6-sol", "read-only"),
    "solution-architect": ("gpt-5.6-sol", "workspace-write"),
    "squeezer": ("gpt-5.6-terra", "read-only"),
    "sw-engineer": ("gpt-5.6-terra", "workspace-write"),
    "web-explorer": ("gpt-5.6-luna", "read-only"),
}
EXPECTED_KAGGLE_REFERENCES = {
    "composition.md",
    "eda.md",
    "foundation.md",
    "inference.md",
    "modality-dispatch.md",
    "style-rules.md",
    "submission.md",
    "training.md",
}
RELATIVE_DEPENDENCY = re.compile(r"`((?:\.\./\.\./(?:shared|runtime)/|references/)[A-Za-z0-9_./-]+)")
PRIVATE_WORK_ITEM = re.compile(r"\b(?:W\d+|H\d{2}|M\d{2})\b")
PRIVATE_PLAN_REFERENCE = re.compile(r"(?:^|[/\s`'\"])(plan_[A-Za-z0-9_.-]+\.md)")
PERSONAL_ABSOLUTE_PATH = re.compile(r"/(?:Users|home)/[^/\s'\"]+(?:/[^\s'\"]+)?")


def load_json(path: Path) -> dict[str, object]:
    """Load one UTF-8 JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def normalized_text(path: Path) -> str:
    """Collapse Markdown wrapping while preserving semantic token order."""
    return " ".join(path.read_text(encoding="utf-8").split())


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse the flat scalar fields used by packaged skill and role cards."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", path
    closing_index = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:closing_index]:
        key, separator, value = line.partition(":")
        assert separator and key and key not in fields, (path, line)
        fields[key] = value.strip()
    return fields


def package_files() -> set[str]:
    """Return all regular release payload paths except the self-hashing manifest."""
    return {
        path.relative_to(PLUGIN_ROOT).as_posix()
        for path in PLUGIN_ROOT.rglob("*")
        if path.is_file()
        and path.name != "package-manifest.json"
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def test_skill_roster_names_and_manifest_records_are_exact() -> None:
    """Prevent missing, renamed, retired, or silently added workflow skills."""
    skill_root = PLUGIN_ROOT / "skills"
    discovered = {path.parent.name for path in skill_root.glob("*/SKILL.md")}
    assert discovered == set(EXPECTED_SKILLS)
    assert {"review", "resolve"}.isdisjoint(discovered)

    for skill_id in EXPECTED_SKILLS:
        fields = parse_frontmatter(skill_root / skill_id / "SKILL.md")
        assert fields["name"] == skill_id
        assert fields["description"]

    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    assert manifest["skills"] == [
        {"id": skill_id, "path": f"skills/{skill_id}/SKILL.md"} for skill_id in EXPECTED_SKILLS
    ]


def test_skill_dependencies_are_cache_local_and_manifested() -> None:
    """Prevent installed skills from referring to missing or source-tree-only dependencies."""
    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    recorded_paths = {record["path"] for record in manifest["files"]}

    for skill_id in EXPECTED_SKILLS:
        skill_path = PLUGIN_ROOT / "skills" / skill_id / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        assert "../_shared/" not in text
        assert "../../shared/" in text

        dependencies = set(RELATIVE_DEPENDENCY.findall(text)) | {"result-template.json"}
        if skill_id == "code-review":
            dependencies.add("validate_artifacts.py")
        for relative in dependencies:
            dependency = (skill_path.parent / relative).resolve()
            assert dependency.is_relative_to(PLUGIN_ROOT), (skill_id, relative)
            assert dependency.is_file(), (skill_id, relative)
            assert dependency.relative_to(PLUGIN_ROOT).as_posix() in recorded_paths, (skill_id, relative)

    assert recorded_paths == package_files()


def test_kaggle_reference_set_is_exact_and_manifested() -> None:
    """Prevent notebook composition stages from disappearing or gaining unreviewed inputs."""
    references_root = PLUGIN_ROOT / "skills" / "kaggle" / "references"
    discovered = {path.name for path in references_root.glob("*.md")}
    assert discovered == EXPECTED_KAGGLE_REFERENCES

    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    recorded_paths = {record["path"] for record in manifest["files"]}
    expected_paths = {f"skills/kaggle/references/{name}" for name in EXPECTED_KAGGLE_REFERENCES}
    assert expected_paths <= recorded_paths


def test_role_roster_frontmatter_and_runtime_records_are_exact() -> None:
    """Prevent specialist identity or execution defaults from drifting independently."""
    role_root = PLUGIN_ROOT / "roles"
    discovered = {path.parent.name for path in role_root.glob("*/ROLE.md")}
    assert discovered == set(EXPECTED_ROLES)

    expected_records = []
    for role_id, (model, sandbox_mode) in EXPECTED_ROLES.items():
        role_path = role_root / role_id / "ROLE.md"
        fields = parse_frontmatter(role_path)
        assert fields == {
            "role_id": role_id,
            "name": f"codex-rig-{role_id}",
            "model": model,
            "model_reasoning_effort": "high",
            "approval_policy": "on-request",
            "sandbox_mode": sandbox_mode,
            "fallback_modes": "[shim, built-in-injected, inline]",
        }
        expected_records.append(
            {
                "id": role_id,
                "path": f"roles/{role_id}/ROLE.md",
                "sha256": hashlib.sha256(role_path.read_bytes()).hexdigest(),
                "runtime": {
                    "model": model,
                    "model_reasoning_effort": "high",
                    "approval_policy": "on-request",
                    "sandbox_mode": sandbox_mode,
                },
            }
        )

    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    assert manifest["roles"] == expected_records


def test_release_profile_contains_no_future_lifecycle_payload() -> None:
    """Prevent plugin-only metadata or files from enabling future lifecycle features."""
    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    plugin = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
    assert manifest["release_profile"] == "plugin-only"
    assert manifest["features"] == {
        "manager": False,
        "hooks": False,
        "mcp": False,
        "generated_shims": False,
    }
    assert "hooks" not in plugin
    assert "mcpServers" not in plugin

    forbidden_roots = {"hooks", "manager", "mcp", "shims"}
    for relative in package_files():
        path = Path(relative)
        assert path.parts[0] not in forbidden_roots
        assert relative != ".mcp.json"
        assert not (path.name.startswith("codex-rig-") and path.suffix == ".toml")
    assert not (PLUGIN_ROOT / "skills" / "agent-shims").exists()


def test_manage_and_sync_preserve_installed_plugin_state() -> None:
    """Prevent management workflows from treating the installed cache as editable source."""
    manage = normalized_text(PLUGIN_ROOT / "skills" / "manage" / "SKILL.md").lower()
    for required in (
        "installed plugin tree is immutable input",
        "never edit this skill's plugin cache",
        "reject any target whose canonical path is inside the same installed plugin root",
        "separately released `agent-shims` workflow",
    ):
        assert required in manage

    sync = normalized_text(PLUGIN_ROOT / "skills" / "sync" / "SKILL.md").lower()
    for required in (
        "never copy files into an installed cache",
        "plugin-only releases own no external agent files",
        "leave every existing `codex-rig-*.toml` untouched",
        "codex plugin marketplace list --json",
        "codex plugin list --marketplace borda-ai-rig --json",
        "codex plugin marketplace upgrade borda-ai-rig",
        "codex plugin add codex-rig@borda-ai-rig",
        "plugin-only sync never deletes or overwrites a match",
    ):
        assert required in sync


def test_specialist_fallback_ladder_and_evidence_are_complete() -> None:
    """Prevent fallback routing from losing order, fidelity limits, or audit evidence."""
    policy = normalized_text(PLUGIN_ROOT / "shared" / "specialist-orchestration.md")
    route_markers = (
        "1. A currently available `codex-rig-<role-id>` custom agent",
        "2. A runtime-provided blank/default subagent",
        "3. An inline pass in the parent context",
        "4. `unavailable` when the runtime cannot provide any safe route",
    )
    positions = [policy.index(marker) for marker in route_markers]
    assert positions == sorted(positions)
    for field in (
        "`role_id`",
        "role-card SHA-256",
        "route",
        "attempted routes",
        "fallback reason",
        "actual model",
        "reasoning effort",
        "requested and observed sandbox/approval controls",
        "independence",
        "nesting depth",
        "material fidelity limits",
    ):
        assert field in policy
    assert "Fallback only for route absence, rejection, or failed bootstrap" in policy
    assert "Never retry another route because the specialist disagreed" in policy


def test_public_payload_has_no_private_release_references() -> None:
    """Prevent internal planning identifiers and personal paths from entering the release."""
    forbidden_references = ("plugin-" + "package.json",)
    violations: list[tuple[str, str]] = []
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(PLUGIN_ROOT).as_posix()
        for reference in forbidden_references:
            if reference in text:
                violations.append((relative, reference))
        if match := PRIVATE_PLAN_REFERENCE.search(text):
            violations.append((relative, match.group(1)))
        if match := PRIVATE_WORK_ITEM.search(text):
            violations.append((relative, match.group(0)))
        if match := PERSONAL_ABSOLUTE_PATH.search(text):
            violations.append((relative, match.group(0)))

    assert violations == []
