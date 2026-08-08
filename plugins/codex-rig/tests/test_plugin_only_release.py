"""Acceptance checks for the complete role-card-injected Codex Rig release."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


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
PERSONAL_ABSOLUTE_PATH = re.compile(
    r"(?:/(?:Users|home)/[^/\\\s'\"]+|(?i:[A-Z]:[\\/]+Users[\\/]+[^/\\\s'\"]+))"
    r"(?:[\\/][^\s'\"]+)?",
)


def load_json(path: Path) -> dict[str, object]:
    """Load one UTF-8 JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def normalized_text(path: Path) -> str:
    """Collapse Markdown wrapping while preserving semantic token order."""
    return " ".join(path.read_text(encoding="utf-8").split())


def load_shared_artifact_validator() -> Any:
    """Load the packaged artifact validator without relying on package imports."""
    path = PLUGIN_ROOT / "shared" / "validate-artifacts.py"
    spec = importlib.util.spec_from_file_location("codex_rig_shared_artifact_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_package_validator() -> Any:
    """Load the package validator without relying on package imports."""
    path = PLUGIN_ROOT / "scripts" / "validate_package.py"
    spec = importlib.util.spec_from_file_location("codex_rig_package_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "payload",
    (
        b"C:" + b"\\Users\\" + b"Alice\\project",
        b"d:" + b"/users/" + b"alice/project",
    ),
    ids=("backslash", "case-insensitive-forward-slash"),
)
def test_package_validator_rejects_windows_user_profile_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    """Reject absolute Windows user-profile paths from public payloads."""
    validator = load_package_validator()
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "runtime.txt").write_bytes(payload)
    monkeypatch.setattr(validator, "PACKAGE_ROOT", package_root)

    with pytest.raises(ValueError, match=r"private material in payload: runtime\.txt"):
        validator.validate_publication_payload()


@pytest.mark.parametrize(
    "payload",
    (
        b"C:\\ProgramData\\codex-rig",
        b"%USERPROFILE%\\codex-rig",
        b"docs/windows/users/guide.md",
    ),
    ids=("system-root", "portable-variable", "relative-documentation"),
)
def test_package_validator_accepts_non_private_windows_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    """Keep portable and non-profile Windows paths publishable."""
    validator = load_package_validator()
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "runtime.txt").write_bytes(payload)
    monkeypatch.setattr(validator, "PACKAGE_ROOT", package_root)

    validator.validate_publication_payload()


def write_merge_resolution(path: Path, **overrides: object) -> dict[str, object]:
    """Write one complete merge-resolution fixture with explicit override fields."""
    payload: dict[str, object] = {
        "schema_version": 1,
        "conflicts_detected": False,
        "status": "not-needed",
        "authorization": "not-required",
        "base_remote_ref": "upstream/main",
        "target_oid": "base-oid",
        "pre_merge_head": "head-oid",
        "post_merge_head": "head-oid",
        "merge_commit": None,
        "resolved_paths": [],
        "unmerged_paths": [],
        "evidence": ["merge-tree.txt"],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


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
        and path.name not in {".coverage", "package-manifest.json"}
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
        "Optional codemap-py structural-context integration",
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


def test_commit_contract_requires_descriptive_user_facing_handoffs() -> None:
    """Keep commit handoffs specific enough to audit without reading the diff."""
    contract = normalized_text(PLUGIN_ROOT / "shared" / "commit-response-template.md").lower()
    for required in (
        "required user-facing commit summary",
        "hash and title",
        "behavior",
        "affected surfaces",
        "verification",
        "residual limits",
        "why the boundary exists",
        "never claim a check passed without concrete execution evidence",
    ):
        assert required in contract


def test_calibration_recurrence_cases_cover_each_escalation_stage() -> None:
    """Keep calibration fixtures aligned with the recurrence escalation contract."""
    cases = load_json(PLUGIN_ROOT / "runtime" / "calibration" / "behavioral-cases.json")["cases"]
    case_contract = {
        case["id"]: (case["target"], case["expected_findings"])
        for case in cases
        if case["id"].startswith("recurrence-")
    }

    assert case_contract == {
        "recurrence-initial-obstacle": ("develop", ["initial-obstacle-not-recorded"]),
        "recurrence-second-occurrence-investigate": (
            "investigate",
            [
                "recurrence-investigation-required",
                "root-cause-evidence-required",
                "recurrence-reset-evidence-missing",
            ],
        ),
        "recurrence-third-occurrence-human-handoff": (
            "delegation-lead",
            [
                "recurrence-human-handoff-required",
                "human-handoff-missing",
                "attempted-actions-missing",
                "shared-obstacle-evidence-missing",
            ],
        ),
    }


def test_calibration_recurrence_policy_link_is_limited_to_retry_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject both missing owner links and redundant links on linear workflows."""
    calibration_dir = PLUGIN_ROOT / "runtime" / "calibration"
    monkeypatch.syspath_prepend(str(calibration_dir))
    spec = importlib.util.spec_from_file_location("codex_rig_calibration_recurrence", calibration_dir / "run.py")
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)

    packaged_skills = tuple(sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")))
    packaged_roles = tuple(sorted((PLUGIN_ROOT / "roles").glob("*/ROLE.md")))
    linked_skills = {
        path.parent.name
        for path in packaged_skills
        if runner.RECURRENCE_POLICY_LINK in path.read_text(encoding="utf-8")
    }
    linked_roles = {
        path.parent.name for path in packaged_roles if runner.RECURRENCE_POLICY_LINK in path.read_text(encoding="utf-8")
    }
    assert linked_skills == {"code-remediate", "develop", "investigate"}
    assert linked_roles == {"delegation-lead"}
    assert runner.find_misplaced_packaged_recurrence_policy_links(packaged_skills, packaged_roles) == []

    for source, relative, is_role, remove_link in (
        (PLUGIN_ROOT / "skills" / "develop" / "SKILL.md", Path("skills/develop/SKILL.md"), False, True),
        (PLUGIN_ROOT / "skills" / "manage" / "SKILL.md", Path("skills/manage/SKILL.md"), False, False),
        (
            PLUGIN_ROOT / "roles" / "delegation-lead" / "ROLE.md",
            Path("roles/delegation-lead/ROLE.md"),
            True,
            True,
        ),
        (PLUGIN_ROOT / "roles" / "sw-engineer" / "ROLE.md", Path("roles/sw-engineer/ROLE.md"), True, False),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True)
        shutil.copy2(source, target)
        skill_files = () if is_role else (target,)
        role_files = (target,) if is_role else ()
        assert runner.find_misplaced_packaged_recurrence_policy_links(skill_files, role_files) == []
        content = target.read_text(encoding="utf-8")
        if remove_link:
            content = content.replace(runner.RECURRENCE_POLICY_LINK, "")
        else:
            content += f"\n{runner.RECURRENCE_POLICY_LINK}\n"
        target.write_text(content, encoding="utf-8")
        assert runner.find_misplaced_packaged_recurrence_policy_links(skill_files, role_files) == [target]


def test_code_remediate_accepts_only_completed_intent_first_merge_states(tmp_path: Path) -> None:
    """Allow conflict-free evidence or one explicitly authorized completed merge."""
    validator = load_shared_artifact_validator()
    pr_dir = tmp_path / "pr"
    pr_dir.mkdir()
    path = pr_dir / "merge-resolution.json"
    metadata = {
        "merge_resolution": {
            "artifact_path": str(path),
            "authorization": "not-required",
            "conflicts_detected": False,
            "status": "not-needed",
        }
    }
    target = {"local_head": "base-oid"}

    write_merge_resolution(path)
    validator._validate_code_remediate_merge_resolution(metadata, pr_dir, target)

    write_merge_resolution(
        path,
        conflicts_detected=True,
        status="completed",
        authorization="user-confirmed",
        post_merge_head="merge-oid",
        merge_commit="merge-oid",
        resolved_paths=["src/conflicted.py"],
        evidence=["merge-prestage.md", "pytest.log"],
    )
    metadata["merge_resolution"] = {
        "artifact_path": str(path),
        "authorization": "user-confirmed",
        "conflicts_detected": True,
        "status": "completed",
    }
    validator._validate_code_remediate_merge_resolution(metadata, pr_dir, target)


def test_code_remediate_rejects_conflicts_without_merge_authorization(tmp_path: Path) -> None:
    """Prevent review remediation from bypassing target-merge authorization."""
    validator = load_shared_artifact_validator()
    pr_dir = tmp_path / "pr"
    pr_dir.mkdir()
    path = pr_dir / "merge-resolution.json"
    write_merge_resolution(
        path,
        conflicts_detected=True,
        status="completed",
        authorization="not-required",
        post_merge_head="merge-oid",
        merge_commit="merge-oid",
        resolved_paths=["src/conflicted.py"],
    )
    metadata = {
        "merge_resolution": {
            "artifact_path": str(path),
            "authorization": "not-required",
            "conflicts_detected": True,
            "status": "completed",
        }
    }

    with pytest.raises(SystemExit, match="target-merge-authorization-required"):
        validator._validate_code_remediate_merge_resolution(metadata, pr_dir, {"local_head": "base-oid"})


def test_public_lifecycle_guide_covers_install_update_and_safe_removal() -> None:
    """Keep the user-visible lifecycle and deliberate thin-link limits explicit."""
    guide_path = PLUGIN_ROOT / "README.md"
    guide = normalized_text(guide_path).lower()
    for required in (
        "codex plugin marketplace add borda/ai-rig --ref codex-rig-v0.3.0",
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
    assert "# codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.3.0" in install_lines


def test_repository_sync_installs_plugin_instead_of_copying_codex_tree() -> None:
    """Prevent the maintainer sync entrypoint from recreating legacy home mirrors."""
    sync_path = PLUGIN_ROOT.parents[1] / "sync.sh"
    if not sync_path.is_file():
        return

    raw_script = sync_path.read_text(encoding="utf-8")
    script = " ".join(raw_script.split()).lower()
    assert "scripts/sync_codex.py" in script
    for forbidden in ("codex_src", 'rsync -a --no-perms "$codex_src', 'cp "$codex_src'):
        assert forbidden not in script

    native_sync = PLUGIN_ROOT / "scripts" / "sync_codex.py"
    native_text = native_sync.read_text(encoding="utf-8")
    assert "Legacy files copied by older sync versions are not deleted automatically" in native_text
    assert '"plugin", "marketplace", "upgrade"' in native_text
    assert '"plugin", "marketplace", "add"' in native_text
    assert '"plugin", "add"' in native_text
    assert '"plugin", "list"' in native_text
    assert "--codex-ref)" in raw_script
    assert "print_claude_plugin_identity" in raw_script


def test_repository_sync_defaults_to_latest_and_accepts_explicit_ref(tmp_path: Path, posix_bash: str) -> None:
    """Prove isolated Codex sync uses no ref by default and forwards an explicit pin."""
    sync_path = PLUGIN_ROOT.parents[1] / "sync.sh"
    if not sync_path.is_file():
        return

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex_source = """#!/usr/bin/env python3
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
    print(json.dumps({"installed": [
        {"pluginId": "codex-rig@borda-ai-rig", "enabled": True, "version": "0.3.0"},
        {"pluginId": "codemap-py@borda-ai-rig", "enabled": True, "version": "0.28.8"},
    ]}))
else:
    raise SystemExit(f"unexpected fake Codex call: {args}")
"""
    if sys.platform == "win32":
        fake_program = fake_bin / "fake_codex.py"
        fake_program.write_text(fake_codex_source, encoding="utf-8")
        fake_codex = fake_bin / "codex.cmd"
        fake_codex.write_bytes(f'@echo off\r\n"{sys.executable}" "%~dp0fake_codex.py" %*\r\n'.encode("utf-8"))
    else:
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(fake_codex_source, encoding="utf-8")
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
            ("codex", "--codex-ref", "codex-rig-v0.3.0"),
            "plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.3.0",
            "marketplace source: codex-rig-v0.3.0",
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
        assert "Codex Rig 0.3.0 installed" in result.stdout
        assert "Codemap 0.28.8 installed" in result.stdout
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
