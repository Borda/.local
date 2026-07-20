"""Acceptance checks for the complete role-card-injected Codex Rig release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "agent-shims",
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
        if skill_id == "agent-shims":
            assert "../../scripts/manage_role_agents.py" in text
            continue
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


def test_release_profile_declares_only_packaged_lifecycle_features() -> None:
    """Keep shim-manager and hook metadata aligned while MCP remains absent."""
    manifest = load_json(PLUGIN_ROOT / "package-manifest.json")
    plugin = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
    assert plugin["description"].startswith("Thirteen portable Codex workflows")
    assert plugin["interface"]["capabilities"] == [
        "13 workflow skills and 1 experimental agent-shim manager",
        "15 specialist role cards",
        "Parallel blank-agent role injection",
        "Authenticated cleanup for prior agent shims",
        "Optional SessionStart health diagnostic",
        "Built-in and inline role fallback",
        "Quality gates",
    ]
    assert manifest["release_profile"] == "role-card-injected"
    assert manifest["features"] == {
        "manager": True,
        "hooks": True,
        "mcp": False,
        "generated_shims": False,
    }
    assert "hooks" not in plugin
    assert "mcpServers" not in plugin

    forbidden_roots = {"manager", "mcp", "shims"}
    for relative in package_files():
        path = Path(relative)
        assert path.parts[0] not in forbidden_roots
        assert relative != ".mcp.json"
        assert not (path.name.startswith("codex-rig-") and path.suffix == ".toml")
    assert (PLUGIN_ROOT / "skills" / "agent-shims" / "SKILL.md").is_file()


def test_manage_and_sync_preserve_installed_plugin_state() -> None:
    """Prevent management workflows from treating the installed cache as editable source."""
    manage = normalized_text(PLUGIN_ROOT / "skills" / "manage" / "SKILL.md").lower()
    for required in (
        "installed plugin tree is immutable input",
        "never edit this skill's plugin cache",
        "reject any target whose canonical path is inside the same installed plugin root",
        "bundled `agent-shims` workflow",
    ):
        assert required in manage

    sync = normalized_text(PLUGIN_ROOT / "skills" / "sync" / "SKILL.md").lower()
    for required in (
        "never copy files into an installed cache",
        "sync never mutates external agent files",
        "before plugin removal, run `agent-shims remove`",
        "after refresh or reinstall, run `agent-shims doctor`",
        "codex plugin marketplace list --json",
        "codex plugin list --marketplace borda-ai-rig --json",
        "codex plugin marketplace upgrade borda-ai-rig",
        "codex plugin add codex-rig@borda-ai-rig",
        "preservation of unknown external agent files",
    ):
        assert required in sync


def test_commit_contract_requires_exact_history_rewrite_authorization() -> None:
    """Prevent ordinary commit requests from authorizing edits to existing history."""
    contract = normalized_text(PLUGIN_ROOT / "shared" / "commit-response-template.md").lower()
    for required in (
        "creating a new commit does not authorize rewriting an existing commit",
        "unless the user explicitly requests that exact history operation",
        "never infer rewrite permission from a commit, cleanup, or commit-diet request",
        "`git commit --amend`",
        "`git rebase`",
        "`git reset`",
    ):
        assert required in contract

    cases = load_json(PLUGIN_ROOT / "runtime" / "calibration" / "behavioral-cases.json")["cases"]
    history_case = next(case for case in cases if case["id"] == "manage-implicit-history-rewrite")
    assert history_case["expected_findings"] == ["history-rewrite-not-explicitly-authorized"]


def test_public_lifecycle_guide_covers_install_update_and_safe_removal() -> None:
    """Keep the user-visible lifecycle and deliberate thin-link limits explicit."""
    guide_path = PLUGIN_ROOT / "README.md"
    guide = normalized_text(guide_path).lower()
    for required in (
        "codex plugin marketplace add borda/ai-rig --ref codex-rig-v0.2.2",
        "codex plugin add codex-rig@borda-ai-rig",
        "optional sessionstart diagnostic",
        "type that exact digest only after explicit approval",
        "plugin reinstall does not update external user-agent files automatically",
        "new installation is platform-blocked",
        "removing plugin first deliberately leaves thin shim files behind",
        "foreign or marker-only `codex-rig-*.toml` files are never adopted, overwritten, or removed",
        "no native bundled agent registrations",
    ):
        assert required in guide

    install_lines = {line.strip() for line in guide_path.read_text(encoding="utf-8").splitlines()}
    assert "codex plugin marketplace add Borda/AI-Rig" in install_lines
    assert "# codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.2.2" in install_lines


def test_repository_sync_installs_plugin_instead_of_copying_codex_tree() -> None:
    """Prevent the maintainer sync entrypoint from recreating legacy home mirrors."""
    sync_path = PLUGIN_ROOT.parents[1] / "sync.sh"
    if not sync_path.is_file():
        return

    raw_script = sync_path.read_text(encoding="utf-8")
    script = " ".join(raw_script.split()).lower()
    for required in (
        "codex plugin marketplace upgrade",
        "codex plugin marketplace add",
        "codex plugin add",
        "codex plugin list",
        "legacy files copied by older sync versions are not deleted automatically",
    ):
        assert required in script
    for forbidden in ("codex_src", 'rsync -a --no-perms "$codex_src', 'cp "$codex_src'):
        assert forbidden not in script

    executable_lines = {
        line.strip() for line in raw_script.splitlines() if line.strip() and not line.lstrip().startswith("#")
    }
    assert 'codex plugin marketplace add "$CODEX_MARKETPLACE_SOURCE"' in executable_lines
    assert 'codex plugin marketplace add "$CODEX_MARKETPLACE_SOURCE" --ref "$CODEX_REF"' in executable_lines
    assert "--codex-ref)" in raw_script
    assert "marketplace source: ${CODEX_REF:-default branch}" in raw_script
    assert "print_claude_plugin_identity" in raw_script


def test_repository_sync_defaults_to_latest_and_accepts_explicit_ref(tmp_path: Path, posix_bash: str) -> None:
    """Prove isolated Codex sync uses no ref by default and forwards an explicit pin."""
    sync_path = PLUGIN_ROOT.parents[1] / "sync.sh"
    if not sync_path.is_file():
        return

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
state = Path(os.environ["FAKE_CODEX_STATE"])
root = Path(os.environ["FAKE_CODEX_ROOT"])
with Path(os.environ["FAKE_CODEX_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(" ".join(args) + "\\n")

if args[:3] == ["plugin", "marketplace", "list"]:
    marketplaces = [{"name": "borda-ai-rig", "root": str(root)}] if state.exists() else []
    print(json.dumps({"marketplaces": marketplaces}))
elif args[:3] == ["plugin", "marketplace", "add"]:
    ref = args[args.index("--ref") + 1] if "--ref" in args else None
    root.mkdir(parents=True, exist_ok=True)
    (root / ".codex-marketplace-install.json").write_text(
        json.dumps({"source_type": "git", "source": "Borda/AI-Rig", "ref_name": ref}),
        encoding="utf-8",
    )
    state.touch()
elif args[:2] == ["plugin", "add"]:
    pass
elif args[:2] == ["plugin", "list"]:
    print(json.dumps({"installed": [{"pluginId": "codex-rig@borda-ai-rig", "enabled": True, "version": "0.2.2"}]}))
else:
    raise SystemExit(f"unexpected fake Codex call: {args}")
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    fake_claude = fake_bin / "claude"
    fake_claude.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    fake_claude.chmod(0o755)

    for case_name, cli_args, expected_add, expected_source, expect_global_agents in (
        (
            "latest",
            ("codex",),
            "plugin marketplace add Borda/AI-Rig",
            "marketplace source: default branch",
            True,
        ),
        (
            "pinned",
            ("codex", "--codex-ref", "codex-rig-v0.2.2"),
            "plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.2.2",
            "marketplace source: codex-rig-v0.2.2",
            True,
        ),
        (
            "no-global-agents",
            ("codex", "--no-codex-global-agents"),
            "plugin marketplace add Borda/AI-Rig",
            "marketplace source: default branch",
            False,
        ),
    ):
        case = tmp_path / case_name
        case.mkdir()
        log = case / "calls.log"
        installed_plugin = case / "marketplace" / "plugins" / "codex-rig"
        (installed_plugin / "assets").mkdir(parents=True)
        (installed_plugin / "scripts").mkdir()
        shutil.copy2(PLUGIN_ROOT / "assets" / "AGENTS.md", installed_plugin / "assets" / "AGENTS.md")
        shutil.copy2(
            PLUGIN_ROOT / "scripts" / "install_global_agents.py",
            installed_plugin / "scripts" / "install_global_agents.py",
        )
        codex_home = case / "codex-home"
        env = os.environ.copy()
        env.update(
            {
                "CODEX_HOME": str(codex_home),
                "FAKE_CODEX_LOG": str(log),
                "FAKE_CODEX_ROOT": str(case / "marketplace"),
                "FAKE_CODEX_STATE": str(case / "configured"),
                "HOME": str(case / "home"),
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            }
        )
        result = subprocess.run(
            [posix_bash, str(sync_path), *cli_args],
            cwd=sync_path.parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = log.read_text(encoding="utf-8").splitlines()
        assert expected_add in calls
        assert expected_source in result.stdout
        assert "Codex Rig 0.2.2 installed" in result.stdout
        assert (codex_home / "AGENTS.md").exists() is expect_global_agents
        if expect_global_agents:
            global_agents = (codex_home / "AGENTS.md").read_text(encoding="utf-8")
            assert "<!-- codex-rig:global-agents begin sha256=" in global_agents
            assert "# Global Agent Instructions" in global_agents


def test_specialist_fallback_ladder_and_evidence_are_complete() -> None:
    """Prevent fallback routing from losing order, fidelity limits, or audit evidence."""
    policy = normalized_text(PLUGIN_ROOT / "shared" / "specialist-orchestration.md")
    route_markers = (
        "1. A runtime-provided blank/default subagent",
        "2. An inline pass in the parent context",
        "3. `unavailable` when the runtime cannot provide any safe route",
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
    assert "Fallback only for route absence or rejection" in policy
    assert "Never retry another route because the specialist disagreed" in policy
    assert "`task_name` is provenance only" in policy
    assert "Persistent named shims are platform-blocked for routing" in policy


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
