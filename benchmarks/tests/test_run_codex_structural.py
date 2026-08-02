"""No-model acceptance tests for the Codex provider-parity adapter."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks import provider_parity_contracts as core


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BENCHMARKS_DIR / "run-codex-structural.py"
SUITE_PATH = BENCHMARKS_DIR / "suites" / "tasks-bench.json"
MANIFEST_PATH = BENCHMARKS_DIR / "manifests" / "codex-integration.json"


@pytest.fixture(scope="module")
def script_run_codex() -> Any:
    """Load the Codex adapter without executing its command-line entry point."""
    spec = importlib.util.spec_from_file_location("run_codemap_codex", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Codex adapter at {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_direct_runtime_bundle(root: Path) -> Path:
    """Create the minimum source-shaped direct CLI runtime used by isolation tests."""
    runtime = root / "codemap-runtime"
    launcher = runtime / "bin" / "codemap-py"
    exclusions = runtime / "bin" / "_exclusions.py"
    entrypoint = runtime / "scripts" / "codemap_py_entry.py"
    package = runtime / "src" / "codemap_py"
    launcher.parent.mkdir(parents=True)
    entrypoint.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    exclusions.write_text("EXCLUSION_PATTERNS = ()\n", encoding="utf-8")
    entrypoint.write_text("raise SystemExit(0)\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    return launcher


def test_codex_command_is_ephemeral_json_profile_backed_and_keeps_prompt_exact(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """The transport plan must use isolated profiles and preserve prompt bytes.

    Prevents a legacy command-line sandbox setting from overriding the
    disposable home's permission profile.
    """
    prompt = "Return the callers exactly.\nSecond line stays unchanged."

    command = script_run_codex.build_codex_command(
        repo_path=tmp_path,
        model="fixture-model",
        reasoning_effort="high",
        prompt=prompt,
    )

    assert command[:2] == ["codex", "exec"]
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--strict-config" in command
    assert "--sandbox" not in command
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert command[command.index("--cd") + 1] == str(tmp_path)
    assert command[command.index("--model") + 1] == "fixture-model"
    assert command[-1] == prompt


def test_codex_stratum_locks_luna_and_high_effort(script_run_codex: Any) -> None:
    """Future paid cells must not silently add a model or effort stratum."""
    script_run_codex._validate_codex_stratum("gpt-5.6-luna", "high")

    with pytest.raises(ValueError, match="gpt-5.6-luna"):
        script_run_codex._validate_codex_stratum("gpt-5.3-codex", "high")
    with pytest.raises(ValueError, match="reasoning effort"):
        script_run_codex._validate_codex_stratum("gpt-5.6-luna", "medium")


def test_deterministic_order_uses_only_current_plain_cli_skill_arms(script_run_codex: Any) -> None:
    """Prevent the historical auto/required arm registry leaking into the new experiment."""
    first = script_run_codex._manifest_arm_order(
        "codex-integration-v1",
        "gpt-5.6-luna",
        "FN-02",
        1,
        "high",
    )
    second = script_run_codex._manifest_arm_order(
        "codex-integration-v1",
        "gpt-5.6-luna",
        "FN-02",
        1,
        "high",
    )

    assert first == second
    assert set(first) == {"A_plain", "B_direct_required", "C_skill_required"}


def test_exact_suite_counterbalances_arm_ordinals_at_one_repetition(script_run_codex: Any) -> None:
    """Each treatment must occupy every ordinal 18 or 19 times across all 55 tasks.

    Prevents a deterministic hash order from making prompt-cache exposure a
    systematic arm confound while preserving repeatable execution planning.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    task_ids = manifest["preregistered_cells"]["structural_execution_task_ids"]
    assert len(task_ids) == 55
    ordinals_by_arm = {arm: [0, 0, 0] for arm in script_run_codex.CODEX_STRUCTURAL_ARMS}

    for task_id in task_ids:
        first = script_run_codex._manifest_arm_order(
            "codex-integration-v1",
            script_run_codex.PARITY_CODEX_MODEL,
            task_id,
            1,
            script_run_codex.PARITY_CODEX_REASONING_EFFORT,
        )
        second = script_run_codex._manifest_arm_order(
            "codex-integration-v1",
            script_run_codex.PARITY_CODEX_MODEL,
            task_id,
            1,
            script_run_codex.PARITY_CODEX_REASONING_EFFORT,
        )

        assert first == second
        for ordinal, arm in enumerate(first):
            ordinals_by_arm[arm][ordinal] += 1

    assert all(count in {18, 19} for counts in ordinals_by_arm.values() for count in counts), ordinals_by_arm


def test_permission_profiles_replace_legacy_sandbox_and_grant_only_coordination_write(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """A/B/C configs must expose only their documented permission surface.

    Prevents a legacy ``--sandbox`` transport flag, an implicitly writable
    profile, or a treatment profile that can write outside Codemap's lock root.
    A plausible but incorrect implementation that writes a broad root, omits
    the profile, or leaves the legacy flag would fail a specific assertion.
    """
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "locked-index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    auth_path = home_path / "auth.json"
    auth_path.write_text("fixture-auth", encoding="utf-8")
    home = script_run_codex.ArmHome(
        "A_plain",
        home_path,
        {"PATH": "/fixture/bin", "API_TOKEN": "must-not-leak", "SSH_AUTH_SOCK": "/fixture/socket"},
        False,
    )

    plain_config = script_run_codex._write_permission_config(home, "A_plain", index_path)
    plain_text = plain_config.read_text(encoding="utf-8")
    assert plain_config == home_path / "config.toml"
    assert plain_config.stat().st_mode & 0o777 == 0o600
    assert 'default_permissions = "provider-parity-plain"' in plain_text
    assert "[permissions.provider-parity-plain]" in plain_text
    assert 'extends = ":read-only"' in plain_text
    assert f'"{auth_path.resolve()}" = "deny"' in plain_text
    assert f'"{index_path.parent.resolve()}" = "deny"' in plain_text
    assert "[permissions.provider-parity-plain.network]" in plain_text
    assert "enabled = false" in plain_text
    assert '"write"' not in plain_text
    assert "[shell_environment_policy]" in plain_text
    assert 'inherit = "none"' in plain_text
    assert "API_TOKEN" not in plain_text
    assert "SSH_AUTH_SOCK" not in plain_text
    for denied_root in script_run_codex._untrusted_host_agent_roots(home, "A_plain"):
        assert f'"{denied_root}" = "deny"' in plain_text

    for arm in ("B_direct_required", "C_skill_required"):
        treatment_home_path = tmp_path / f"codex-home-{arm}"
        treatment_home_path.mkdir()
        treatment_auth_path = treatment_home_path / "auth.json"
        treatment_auth_path.write_text("fixture-auth", encoding="utf-8")
        treatment_home = script_run_codex.ArmHome(
            arm,
            treatment_home_path,
            {"PATH": "/fixture/bin"},
            True,
            True,
        )
        marketplace_root = tmp_path / "marketplace"
        treatment_config = script_run_codex._write_permission_config(
            treatment_home,
            arm,
            index_path,
            marketplace_root=marketplace_root,
        )
        treatment_text = treatment_config.read_text(encoding="utf-8")
        coordination_root = index_path.parent / ".index-rw"

        assert treatment_config == treatment_home_path / "config.toml"
        assert 'default_permissions = "provider-parity-codemap"' in treatment_text
        assert "[permissions.provider-parity-codemap]" in treatment_text
        assert 'extends = ":read-only"' in treatment_text
        assert f'"{treatment_auth_path.resolve()}" = "deny"' in treatment_text
        assert f'"{coordination_root.resolve()}" = "write"' in treatment_text
        assert "[permissions.provider-parity-codemap.network]" in treatment_text
        assert "enabled = false" in treatment_text
        assert "sandbox_mode" not in treatment_text
        assert "sandbox_workspace_write" not in treatment_text
        for denied_root in script_run_codex._untrusted_host_agent_roots(treatment_home, arm, marketplace_root):
            assert f'"{denied_root}" = "deny"' in treatment_text


def test_plain_and_direct_homes_drop_host_skill_file_binding(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A/B must not inherit a host Skill path that could contaminate treatment."""
    monkeypatch.setenv("CODEMAP_SKILL_FILE", "/host/untrusted/SKILL.md")
    launcher = _make_direct_runtime_bundle(tmp_path / "direct-runtime")

    with script_run_codex.prepare_arm_home("A_plain", root=tmp_path) as plain_home:
        assert "CODEMAP_SKILL_FILE" not in plain_home.env
    with script_run_codex.prepare_arm_home(
        "B_direct_required",
        root=tmp_path,
        codemap_bin=launcher,
    ) as direct_home:
        assert "CODEMAP_SKILL_FILE" not in direct_home.env


def test_skill_home_preserves_plugin_registration_when_permissions_are_applied(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C must retain enabled plugin tables after applying its permission profile.

    Prevents the runner from verifying plugin installation and then deleting
    its registration by replacing ``config.toml`` before ``codex exec``.
    """
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    marketplace_root = tmp_path / "marketplace"
    marketplace_root.mkdir()

    def install_plugins(home: Any, *_args: Any, **_kwargs: Any) -> bool:
        config_path = home.path / "config.toml"
        config_text = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            config_text
            + '\n[plugins."codemap-py@borda-ai-rig"]\nenabled = true\n'
            + '\n[plugins."codex-rig@borda-ai-rig"]\nenabled = true\n',
            encoding="utf-8",
        )
        home.codemap_skill_path = config_path
        home.codemap_skill_sha256 = "skill-sha"
        home.env["CODEMAP_SKILL_FILE"] = str(config_path.resolve())
        home.codex_rig_path = home.path
        home.codex_rig_manifest_sha256 = "rig-sha"
        return True

    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        script_run_codex,
        "_verify_locked_codemap_python",
        lambda **_kwargs: "/opt/homebrew/bin/python3.11",
    )
    monkeypatch.setattr(script_run_codex, "_install_codemap_plugin", install_plugins)
    monkeypatch.setattr(script_run_codex, "_verify_treatment_artifact_locks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_admit_installed_skill_pair", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_installed_plugin_pair", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_permission_profile", lambda *_args, **_kwargs: None)
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        repo_path,
        index_path=index_path,
        marketplace_root=marketplace_root,
    )

    with runner._prepare_verified_home("C_skill_required") as home:
        config_text = (home.path / "config.toml").read_text(encoding="utf-8")
        coordination_path = home.coordination_path

    assert "[permissions.provider-parity-codemap]" in config_text
    assert '[plugins."codemap-py@borda-ai-rig"]' in config_text
    assert '[plugins."codex-rig@borda-ai-rig"]' in config_text
    assert coordination_path is not None
    script_run_codex._cleanup_coordination_root(coordination_path)


def test_active_manifest_locks_exact_treatment_python_runtime() -> None:
    """Prevent another paid treatment from discovering or choosing its own Python."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    runtime = manifest["codex_permission_profiles"]["treatment_runtime"]

    assert manifest["experiment_revision"]
    assert runtime == {
        "environment": {"CODEMAP_PYTHON": "/opt/homebrew/bin/python3.11"},
        "required_major_minor": [3, 11],
        "scope": ["B_direct_required", "C_skill_required"],
    }


def test_locked_treatment_python_is_executable_and_version_checked(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """Reject missing or wrong-version treatment runtimes before model execution."""
    python_path = tmp_path / "python3.11"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "codex_permission_profiles": {
                    "treatment_runtime": {
                        "environment": {"CODEMAP_PYTHON": str(python_path)},
                        "required_major_minor": [3, 11],
                        "scope": ["B_direct_required", "C_skill_required"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def matching_runtime(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="3.11.15\n", stderr="")

    assert script_run_codex._verify_locked_codemap_python(
        manifest_path=manifest_path,
        command_runner=matching_runtime,
    ) == str(python_path)
    assert commands == [[str(python_path), "--version"]]

    def wrong_runtime(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="Python 3.13.5\n", stderr="")

    with pytest.raises(ValueError, match="3.11"):
        script_run_codex._verify_locked_codemap_python(
            manifest_path=manifest_path,
            command_runner=wrong_runtime,
        )


def test_verified_home_overrides_treatment_python_and_removes_it_from_plain(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove caller environment cannot select B/C Python or leak it into A."""
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEMAP_PYTHON", "/caller/selected/python")
    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_permission_profile", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_plain_plugin_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        script_run_codex,
        "_verify_locked_codemap_python",
        lambda **_kwargs: "/opt/homebrew/bin/python3.11",
    )
    monkeypatch.setattr(script_run_codex, "_verify_treatment_artifact_locks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_admit_staged_direct_cli", lambda *_args, **_kwargs: None)
    launcher = _make_direct_runtime_bundle(tmp_path)
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        repo_path,
        index_path=index_path,
        codemap_bin=launcher,
    )

    with runner._prepare_verified_home("A_plain") as plain:
        plain_evidence = script_run_codex.probe_arm_home(plain)
        plain_has_runtime = "CODEMAP_PYTHON" in plain.env
    with runner._prepare_verified_home("B_direct_required") as treatment:
        treatment_evidence = script_run_codex.probe_arm_home(treatment)
        coordination_path = treatment.coordination_path

    assert plain_evidence["codemap_python"] is None
    assert plain_has_runtime is False
    assert treatment_evidence["codemap_python"] == "/opt/homebrew/bin/python3.11"
    assert coordination_path is not None
    script_run_codex._cleanup_coordination_root(coordination_path)


def test_coordination_root_is_exact_safe_and_cleanup_keeps_the_locked_index(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """The sole treatment write root is the initialized index-local lock directory.

    Prevents writing a parent/cache-wide root or deleting the locked index when
    the disposable coordination state is cleaned up.  A broad or misplaced root
    cannot satisfy the exact-path assertion.
    """
    index_path = tmp_path / "target" / ".cache" / "codemap" / "locked-index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("locked", encoding="utf-8")

    coordination_root = script_run_codex._prepare_coordination_root(index_path)

    assert coordination_root == index_path.parent / ".index-rw"
    assert coordination_root.is_dir()
    assert (coordination_root / "readers").is_dir()
    assert (coordination_root / "registry.lock").is_file()
    script_run_codex._validate_coordination_root(coordination_root)

    script_run_codex._cleanup_coordination_root(coordination_root)

    assert not coordination_root.exists()
    assert index_path.read_text(encoding="utf-8") == "locked"


@pytest.mark.parametrize("unsafe_entry", ["coord-symlink", "readers-symlink"], ids=["coord", "readers"])
def test_coordination_root_rejects_symlinks_and_cannot_escape_its_index_directory(
    script_run_codex: Any, tmp_path: Path, unsafe_entry: str
) -> None:
    """Indirect coordination paths must fail before a treatment can write through them.

    Prevents a symlinked lock root or readers directory from granting write
    access outside the index directory.  Remaining coverage excludes hostile
    concurrent filesystem replacement, which needs process-level fault tests.
    """
    index_path = tmp_path / "target" / ".cache" / "codemap" / "locked-index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("locked", encoding="utf-8")
    escaped_path = tmp_path / "outside"
    escaped_path.mkdir()
    coordination_root = index_path.parent / ".index-rw"

    if unsafe_entry == "coord-symlink":
        coordination_root.symlink_to(escaped_path, target_is_directory=True)
    else:
        coordination_root.mkdir()
        (coordination_root / "readers").symlink_to(escaped_path, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink|escape|safe|coordination"):
        script_run_codex._prepare_coordination_root(index_path)

    assert not (escaped_path / "registry.lock").exists()
    assert not (escaped_path / "readers").exists()


def test_permission_profile_verification_fails_closed_when_codex_rejects_the_profile(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """An unsupported permission profile cannot silently run under Codex defaults.

    Prevents the profile probe from treating an unknown profile as a successful
    setup.  A check that only validates the Codex binary version would fail to
    raise here.
    """
    repo_path = tmp_path / "target"
    repo_path.mkdir()
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    home = script_run_codex.ArmHome("B_direct_required", home_path, {}, True, True)

    def reject_profile(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        if "--version" in command:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.138.0", stderr="")
        return SimpleNamespace(returncode=2, stdout="", stderr="unknown permission profile provider-parity-codemap")

    with pytest.raises(ValueError, match="profile|permission|unsupported"):
        script_run_codex._verify_permission_profile(home, repo_path, command_runner=reject_profile)


def test_permission_profile_resolves_workspace_python_symlink_before_sandbox(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project virtualenv launcher must not be denied as a source-tree executable."""
    repo_path = tmp_path / "target"
    python_dir = repo_path / ".venv" / "bin"
    python_dir.mkdir(parents=True)
    external_python = tmp_path / "runtime" / "python3"
    external_python.parent.mkdir()
    external_python.write_text("fixture", encoding="utf-8")
    external_python.chmod(0o755)
    workspace_python = python_dir / "python3"
    workspace_python.symlink_to(external_python)
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    home = script_run_codex.ArmHome("A_plain", home_path, {}, False)
    commands: list[list[str]] = []

    def reject_after_capture(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        if command == ["codex", "--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.146.0", stderr="")
        return SimpleNamespace(returncode=2, stdout="", stderr="fixture stop")

    monkeypatch.setattr(script_run_codex.sys, "executable", str(workspace_python))

    with pytest.raises(ValueError, match="profile|permission|unsupported"):
        script_run_codex._verify_permission_profile(home, repo_path, command_runner=reject_after_capture)

    sandbox_command = commands[1]
    interpreter = sandbox_command[sandbox_command.index("--") + 1]
    assert interpreter == str(external_python.resolve())


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is unavailable")
@pytest.mark.skipif(
    os.environ.get("RUN_CODEX_SANDBOX_INTEGRATION") != "1",
    reason="set RUN_CODEX_SANDBOX_INTEGRATION=1 to exercise the installed Codex sandbox",
)
def test_real_codex_profile_denies_source_and_auth_but_allows_coordination(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """The installed Codex sandbox must enforce the active treatment boundary."""
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    home = script_run_codex.ArmHome("B_direct_required", home_path, {}, True, True)
    auth_path = home.path / "auth.json"
    auth_path.write_text('{"fixture":"credential-sentinel"}', encoding="utf-8")
    auth_path.chmod(0o600)
    home.coordination_path = script_run_codex._prepare_coordination_root(index_path)
    script_run_codex._write_permission_config(home, "B_direct_required", index_path)

    try:
        script_run_codex._verify_permission_profile(home, repo_path, index_path)
    finally:
        script_run_codex._cleanup_coordination_root(home.coordination_path)
        home.cleanup()

    assert not any(repo_path.glob(".codex-parity-deny-*"))
    assert index_path.read_text(encoding="utf-8") == "{}"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is unavailable")
@pytest.mark.skipif(
    os.environ.get("RUN_CODEX_SANDBOX_INTEGRATION") != "1",
    reason="set RUN_CODEX_SANDBOX_INTEGRATION=1 to exercise the installed Codex sandbox",
)
def test_real_plain_profile_cannot_read_locked_index(script_run_codex: Any, tmp_path: Path) -> None:
    """A must share the locked target while the installed sandbox denies its index."""
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text('{"sentinel":"must-not-be-readable"}', encoding="utf-8")
    home = script_run_codex.prepare_arm_home("A_plain", root=tmp_path)
    auth_path = home.path / "auth.json"
    auth_path.write_text('{"fixture":"credential-sentinel"}', encoding="utf-8")
    auth_path.chmod(0o600)
    script_run_codex._write_permission_config(home, "A_plain", index_path)

    try:
        script_run_codex._verify_permission_profile(home, repo_path, index_path)
    finally:
        home.cleanup()

    assert index_path.read_text(encoding="utf-8") == '{"sentinel":"must-not-be-readable"}'


def _successful_plain_profile_command(command: list[str], **_kwargs: Any) -> SimpleNamespace:
    """Emulate a valid plain profile without executing Codex or exposing auth."""
    if command == ["codex", "--version"]:
        return SimpleNamespace(returncode=0, stdout="codex-cli 0.145.0", stderr="")
    if command[:2] == ["codex", "sandbox"]:
        script = command[command.index("-c") + 1]
        if script == "pass":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Operation not permitted")
    if command == ["codex", "login", "status"]:
        return SimpleNamespace(returncode=0, stdout="Logged in using fixture", stderr="")
    return SimpleNamespace(returncode=0, stdout='{"installed":[],"available":[]}', stderr="")


def test_parse_codex_jsonl_preserves_native_events_and_normalizes_usage(
    script_run_codex: Any,
) -> None:
    """Official JSONL events must yield output, usage, calls, and raw audit evidence."""
    events = [
        {"type": "thread.started", "thread_id": "thread-fixture"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": '"$CODEMAP_BIN" query --compact rdeps lightning.fabric',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                "duration_ms": 1250,
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "answer-1", "type": "agent_message", "text": "Final fixture answer."},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 120,
                "cached_input_tokens": 80,
                "output_tokens": 24,
                "reasoning_output_tokens": 7,
            },
        },
    ]
    stream = "\n".join(json.dumps(event) for event in events)

    parsed = script_run_codex.parse_codex_jsonl(stream)

    assert parsed.thread_id == "thread-fixture"
    assert parsed.output_text == "Final fixture answer."
    assert parsed.input_tokens == 120
    assert parsed.cached_input_tokens == 80
    assert parsed.output_tokens == 24
    assert parsed.reasoning_output_tokens == 7
    assert parsed.command_calls == 1
    assert parsed.codemap_calls == 1
    assert parsed.completed is True
    assert parsed.incomplete is False
    assert parsed.raw_events == events
    assert parsed.item_counts == {"command_execution": 1, "agent_message": 1}
    assert parsed.tool_elapsed_s == pytest.approx(1.25)
    assert parsed.tool_result_tokens is None


def _completed_stream(
    *,
    output: str = "fixture answer",
    input_tokens: int = 10,
    cached_input_tokens: int = 0,
    output_tokens: int = 2,
    commands: list[dict[str, Any]] | None = None,
) -> str:
    """Build one official-shape completed Codex event stream."""
    events: list[dict[str, Any]] = [{"type": "thread.started", "thread_id": "fixture-thread"}]
    events.extend(
        {"type": "item.completed", "item": {"id": f"command-{index}", **command}}
        for index, command in enumerate(commands or [], start=1)
    )
    events.extend(
        [
            {
                "type": "item.completed",
                "item": {"id": "answer", "type": "agent_message", "text": output},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": 0,
                },
            },
        ]
    )
    return "\n".join(json.dumps(event) for event in events)


def test_loaded_task_keeps_canonical_identity_and_shared_evaluator_input(script_run_codex: Any, tmp_path: Path) -> None:
    """Adapter provenance must not enter task hashing or evaluator input."""
    raw_task = next(task for task in core.load_task_suite(SUITE_PATH) if task["id"] == "FN-02")
    loaded_task = next(
        task for task in script_run_codex.load_tasks_with_provenance(SUITE_PATH, MANIFEST_PATH) if task["id"] == "FN-02"
    )
    evaluated: list[tuple[dict[str, Any], str]] = []

    def evaluator(task: dict[str, Any], output_text: str) -> core.EvaluationResult:
        evaluated.append((task, output_text))
        return core.EvaluationResult(scored=True, correct=True, quality_score=0.75)

    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(),
        evaluator=evaluator,
    )

    result = runner.run(loaded_task, "B_direct_required")

    assert result.task_hash == core.canonical_task_hash(raw_task)
    assert result.prompt_hash == core.prompt_hash(raw_task)
    assert result.suite_hash == core.semantic_suite_hash(core.load_task_suite(SUITE_PATH))
    assert result.oracle_class == "independent"
    assert result.headline_eligible_v1 is True
    assert result.quality_score == pytest.approx(0.75)
    assert evaluated == [(raw_task, "fixture answer")]


@pytest.mark.parametrize(
    ("arm", "commands", "expected_compliance", "expected_contamination", "expected_success"),
    [
        pytest.param("A_plain", [], None, False, True, id="plain-clean"),
        pytest.param(
            "A_plain",
            [
                {
                    "type": "command_execution",
                    "command": '"$CODEMAP_BIN" query --compact rdeps pkg.core',
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                }
            ],
            None,
            True,
            False,
            id="plain-contaminated",
        ),
        pytest.param("B_direct_required", [], False, False, True, id="direct-no-call-separate"),
        pytest.param("C_skill_required", [], False, False, True, id="skill-no-call-separate"),
        pytest.param(
            "C_skill_required",
            [
                {
                    "type": "command_execution",
                    "command": '"$CODEMAP_BIN" query --compact rdeps pkg.core',
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                }
            ],
            False,
            False,
            True,
            id="skill-query-without-read-not-compliant",
        ),
    ],
)
def test_arm_call_semantics_are_separate_from_quality(
    script_run_codex: Any,
    tmp_path: Path,
    arm: str,
    commands: list[dict[str, Any]],
    expected_compliance: bool | None,
    expected_contamination: bool,
    expected_success: bool,
) -> None:
    """A contamination and C compliance cannot silently change correctness."""
    task = {"id": "fixture", "prompt": "unchanged prompt", "type": "demo", "scoreable": True}
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(commands=commands),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run(task, arm)

    assert result.compliance is expected_compliance
    assert result.contaminated is expected_contamination
    assert result.success is expected_success
    assert result.correct is True
    assert result.quality_score == pytest.approx(1.0)


def test_runner_persists_cache_over_gross_as_explicit_unscoreable_token_accounting(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """Provider-native gross/cache evidence remains raw when fresh-token derivation is impossible."""
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(input_tokens=25, cached_input_tokens=80),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "A_plain")
    output_path = tmp_path / "telemetry.jsonl"
    script_run_codex._append_run(output_path, result, execution_index=0)
    persisted = json.loads(output_path.read_text(encoding="utf-8"))

    assert (result.input_tokens, result.cached_input_tokens, result.fresh_input_tokens) == (25, 80, None)
    assert result.token_accounting_inconsistent is True
    assert persisted["token_accounting_inconsistent"] is True
    assert persisted["fresh_input_tokens"] is None


def test_result_rows_show_gross_input_while_telemetry_retains_cache_detail(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """Console output avoids cache-derived claims while JSONL retains provider evidence."""
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(input_tokens=120, cached_input_tokens=80),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "A_plain")
    output_path = tmp_path / "telemetry.jsonl"
    script_run_codex._append_run(output_path, result, execution_index=0)
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    row = script_run_codex._format_result_row(
        status="✓",
        task_id=result.task_id,
        repetition=1,
        arm=result.arm,
        input_tokens=result.input_tokens,
        cached_input_tokens=result.cached_input_tokens,
        fresh_tokens=result.fresh_input_tokens,
        output_tokens=result.output_tokens,
        elapsed_s=1.0,
        quality="1.000",
        adherence=True,
        codemap_used=False,
    )

    assert "in=   120  out=" in row
    assert "/" not in row
    assert persisted["input_tokens"] == 120
    assert persisted["cached_input_tokens"] == 80
    assert persisted["fresh_input_tokens"] == 40


def test_parser_marks_malformed_and_missing_terminal_streams_incomplete(script_run_codex: Any) -> None:
    """Invalid or unterminated JSONL cannot become a complete benchmark cell."""
    malformed = script_run_codex.parse_codex_jsonl('{"type":"turn.completed"}\nnot-json')
    unterminated = script_run_codex.parse_codex_jsonl(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "answer", "type": "agent_message", "text": "partial"},
            }
        )
    )

    assert malformed.incomplete is True
    assert malformed.error
    assert malformed.malformed_lines == 1
    assert unterminated.incomplete is True
    assert unterminated.error


def test_codemap_failure_then_ordinary_command_is_fallback(script_run_codex: Any) -> None:
    """Fallback is counted only after a failed Codemap command."""
    stream = _completed_stream(
        commands=[
            {
                "type": "command_execution",
                "command": '"$CODEMAP_BIN" query --compact rdeps pkg.core',
                "status": "failed",
                "exit_code": 1,
            },
            {
                "type": "command_execution",
                "command": "rg 'pkg.core' src",
                "status": "completed",
                "exit_code": 0,
            },
        ]
    )

    parsed = script_run_codex.parse_codex_jsonl(stream)

    assert parsed.codemap_calls == 1
    assert parsed.codemap_errors == 1
    assert parsed.fallback_calls == 1


@pytest.mark.parametrize(
    ("first_stream", "expected_calls", "expected_retries"),
    [
        pytest.param(
            json.dumps({"type": "error", "error": "transport unavailable"}),
            2,
            1,
            id="zero-token-error-retried",
        ),
        pytest.param(
            _completed_stream(input_tokens=0, output_tokens=0),
            1,
            0,
            id="successful-zero-token-not-retried",
        ),
        pytest.param(
            "\n".join(
                [
                    json.dumps({"type": "error", "error": "substantive failure"}),
                    json.dumps(
                        {
                            "type": "turn.failed",
                            "usage": {"input_tokens": 5, "output_tokens": 0},
                            "error": "substantive failure",
                        }
                    ),
                ]
            ),
            1,
            0,
            id="substantive-failure-not-retried",
        ),
    ],
)
def test_retry_policy_only_retries_zero_token_transport_failures(
    script_run_codex: Any,
    tmp_path: Path,
    first_stream: str,
    expected_calls: int,
    expected_retries: int,
) -> None:
    """The locked two-retry allowance cannot repeat a substantive task result."""
    streams = iter([first_stream, _completed_stream()])
    calls = 0

    def transport(*_args: Any, **_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return next(streams)

    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=transport,
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "A_plain")

    assert calls == expected_calls
    assert result.retry_count == expected_retries
    assert runner.timeout == pytest.approx(600.0)


def test_retry_attempts_share_one_coordinate_wall_clock_budget(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport timeout cannot unlock another full coordinate budget."""
    calls = 0

    def transport(*_args: Any, **_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return json.dumps({"type": "error", "error": "transport unavailable"})

    clock = iter([0.0, 0.0, 600.0, 600.0])
    monkeypatch.setattr(script_run_codex.time, "monotonic", lambda: next(clock))
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        timeout=600.0,
        transport=transport,
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "A_plain")

    assert calls == 1
    assert result.retry_count == 0
    assert result.error_type == "cell_timeout"
    assert result.cell_wall_clock_limit_s == pytest.approx(600.0)


def test_command_lifecycle_uses_completed_status_once(script_run_codex: Any) -> None:
    """A started command cannot hide its later failed completion status."""
    item = {
        "id": "command-1",
        "type": "command_execution",
        "command": '"$CODEMAP_BIN" query --compact rdeps pkg.core',
    }
    events = [
        {"type": "item.started", "item": {**item, "status": "in_progress"}},
        {"type": "item.completed", "item": {**item, "status": "failed", "exit_code": 1}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 5, "output_tokens": 1},
        },
    ]

    parsed = script_run_codex.parse_codex_jsonl("\n".join(json.dumps(event) for event in events))

    assert parsed.command_calls == 1
    assert parsed.codemap_calls == 1
    assert parsed.codemap_successful_calls == 0
    assert parsed.codemap_errors == 1


def test_compound_shell_probe_is_not_codemap_delivery_evidence(script_run_codex: Any) -> None:
    """A compound shell command cannot become Codemap delivery evidence."""
    stream = _completed_stream(
        commands=[
            {
                "type": "command_execution",
                "command": "/bin/zsh -lc '/tmp/plugin/bin/codemap-py query central --top 1; echo $?'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": "127\n",
            }
        ]
    )

    parsed = script_run_codex.parse_codex_jsonl(stream)

    assert parsed.codemap_calls == 0
    assert parsed.codemap_successful_calls == 0
    assert parsed.codemap_errors == 0


def test_terminal_event_with_pending_command_is_incomplete(script_run_codex: Any) -> None:
    """A terminal turn cannot make an unfinished command item scoreable."""
    events = [
        {
            "type": "item.started",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "rg fixture src",
                "status": "in_progress",
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}},
    ]

    parsed = script_run_codex.parse_codex_jsonl("\n".join(json.dumps(event) for event in events))

    assert parsed.completed is False
    assert parsed.incomplete is True
    assert parsed.error_type == "pending_item"


def test_mentioning_codemap_in_an_ordinary_search_is_not_adoption(script_run_codex: Any) -> None:
    """A grep query about Codemap text is not a Codemap executable invocation."""
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": "rg 'codemap-py' src",
                    "status": "completed",
                    "exit_code": 0,
                }
            ]
        )
    )

    assert parsed.command_calls == 1
    assert parsed.codemap_calls == 0


def test_loader_rejects_reordered_known_tasks(script_run_codex: Any, tmp_path: Path) -> None:
    """Known task IDs cannot be rearranged into an unregistered suite."""
    tasks = core.load_task_suite(SUITE_PATH)
    reordered_path = tmp_path / "tasks-bench-reordered.json"
    reordered_path.write_text(json.dumps(list(reversed(tasks))), encoding="utf-8")

    with pytest.raises(ValueError, match="order|membership|suite"):
        script_run_codex.load_tasks_with_provenance(reordered_path, MANIFEST_PATH)


def test_runner_rejects_tampered_nested_provenance(script_run_codex: Any, tmp_path: Path) -> None:
    """Supplied provenance cannot override the canonical task-byte hash."""
    loaded = next(
        task for task in script_run_codex.load_tasks_with_provenance(SUITE_PATH, MANIFEST_PATH) if task["id"] == "FN-02"
    )
    tampered = dict(loaded)
    tampered[script_run_codex._PROVENANCE_KEY] = {
        **loaded[script_run_codex._PROVENANCE_KEY],
        "task_hash": "0" * 64,
    }
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    with pytest.raises(ValueError, match="task hash"):
        runner.run(tampered, "B_direct_required")


def test_skill_arm_installs_and_locks_rig_and_codemap_plugins(script_run_codex: Any, tmp_path: Path) -> None:
    """C installs both plugins and records their installed identities before model use."""
    marketplace_root = tmp_path / "marketplace"
    manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"borda-ai-rig","plugins":[]}', encoding="utf-8")
    calls: list[list[str]] = []

    with script_run_codex.prepare_arm_home("C_skill_required", root=tmp_path) as home:
        rig_path = home.path / "plugins" / "cache" / "borda-ai-rig" / "codex-rig" / "0.4.0"
        rig_manifest = rig_path / ".codex-plugin" / "plugin.json"
        rig_manifest.parent.mkdir(parents=True)
        rig_manifest.write_text('{"name":"codex-rig","version":"0.4.0"}', encoding="utf-8")
        adapter = rig_path / "shared" / "codemap_adapter.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text("print('fixture adapter')\n", encoding="utf-8")
        installed_path = home.path / "plugins" / "cache" / "borda-ai-rig" / "codemap-py" / "0.27.0"
        launcher = installed_path / "bin" / "codemap-py"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        plugin_manifest = installed_path / ".codex-plugin" / "plugin.json"
        plugin_manifest.parent.mkdir()
        plugin_manifest.write_text('{"name":"codemap-py","version":"0.27.0"}', encoding="utf-8")
        query_skill = installed_path / "codex-skills" / "query-code" / "SKILL.md"
        query_skill.parent.mkdir(parents=True)
        query_skill.write_text("# query-code\n", encoding="utf-8")

        def command_runner(command: list[str], **_kwargs: Any) -> SimpleNamespace:
            calls.append(command)
            if len(command) > 2 and command[1:3] == ["plugin", "add"]:
                install_path = rig_path if command[3] == "codex-rig@borda-ai-rig" else installed_path
                stdout = json.dumps({"installedPath": str(install_path)})
            elif len(command) > 2 and command[1:3] == ["plugin", "list"]:
                stdout = (
                    '{"installed":[{"name":"codex-rig","enabled":true},'
                    '{"name":"codemap-py","enabled":true}],"available":[]}'
                )
            elif len(command) > 2 and command[1] == str(adapter):
                assert "SECRET" not in _kwargs["env"]
                assert _kwargs["env"]["CODEMAP_BIN"] == str(launcher.resolve())
                assert _kwargs["cwd"] == tmp_path.resolve()
                context_path = Path(command[command.index("--out") + 1])
                index_path = tmp_path / "locked-index.json"
                context_path.write_text(
                    json.dumps(
                        {
                            "protocol_version": "codemap-py.integration.v1",
                            "target": "lightning.pytorch.trainer.call",
                            "status": "degraded",
                            "probe": {
                                "status": "available",
                                "launcher": str(launcher.resolve()),
                                "doctor": {
                                    "plugin_root": str(installed_path.resolve()),
                                    "index_path": str(index_path.resolve()),
                                },
                            },
                            "queries": [{"exit_code": 0, "error": None, "query_complete": True}],
                        }
                    ),
                    encoding="utf-8",
                )
                stdout = ""
            else:
                stdout = ""
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        installed = script_run_codex._install_codemap_plugin(
            home,
            marketplace_root,
            command_runner=command_runner,
        )

        assert installed is True
        assert home.codex_rig_path == rig_path.resolve()
        assert home.codex_rig_manifest_sha256 == hashlib.sha256(rig_manifest.read_bytes()).hexdigest()
        assert home.codex_rig_adapter_path == adapter.resolve()
        assert home.codex_rig_adapter_sha256 == hashlib.sha256(adapter.read_bytes()).hexdigest()
        assert home.env["CODEMAP_BIN"] == str(launcher.resolve())
        assert home.env["CODEMAP_SKILL_FILE"] == str(query_skill.resolve())
        assert home.codemap_launcher_path == launcher.resolve()
        assert home.codemap_launcher_sha256 == hashlib.sha256(launcher.read_bytes()).hexdigest()
        assert home.codemap_skill_path == query_skill.resolve()
        assert home.codemap_skill_sha256 == hashlib.sha256(query_skill.read_bytes()).hexdigest()
        assert script_run_codex._shell_environment(home)["CODEMAP_SKILL_FILE"] == str(query_skill.resolve())
        home.codemap_available = True
        home.codemap_verified = True
        home.env["CODEMAP_PYTHON"] = "/usr/bin/python3"
        home.env["SECRET"] = "must-not-reach-adapter"
        index_path = tmp_path / "locked-index.json"
        index_path.write_text("{}", encoding="utf-8")
        lock_path = tmp_path / "locks.json"
        lock_path.write_text(
            json.dumps(
                {
                    "artifact_sha256": {
                        "codemap_runtime_cli": home.codemap_launcher_sha256,
                        "codemap_candidate_manifest": home.codemap_plugin_manifest_sha256,
                        "codemap_query_skill": home.codemap_skill_sha256,
                        "codex_rig_plugin_manifest": home.codex_rig_manifest_sha256,
                        "codex_rig_adapter": home.codex_rig_adapter_sha256,
                    },
                    "codemap_candidate": {"version": "0.27.0"},
                    "codex_rig_candidate": {"version": "0.4.0"},
                    "codex_rig_integration_admission": {
                        "probe_category": "analysis",
                        "probe_target": "lightning.pytorch.trainer.call",
                    },
                }
            ),
            encoding="utf-8",
        )
        script_run_codex._verify_treatment_artifact_locks(home, lock_path)
        script_run_codex._admit_installed_skill_pair(
            home,
            tmp_path,
            index_path,
            manifest_path=lock_path,
            command_runner=command_runner,
        )
        config = home.path / "config.toml"
        config.write_text("", encoding="utf-8")
        config.chmod(0o600)
        evidence = script_run_codex.probe_arm_home(home)
        assert evidence["codemap_launcher_path"] == str(launcher.resolve())
        assert evidence["codemap_launcher_sha256"] == home.codemap_launcher_sha256
        assert evidence["codemap_skill_path"] == str(query_skill.resolve())
        assert evidence["codemap_skill_sha256"] == home.codemap_skill_sha256
        assert evidence["codemap_skill_file"] == str(query_skill.resolve())
        assert evidence["codex_rig_path"] == str(rig_path.resolve())
        assert evidence["codex_rig_manifest_sha256"] == home.codex_rig_manifest_sha256
        assert evidence["codemap_context_path"] == str(home.codemap_context_path)
        assert evidence["codemap_context_sha256"] == home.codemap_context_sha256
        assert calls == [
            ["codex", "plugin", "marketplace", "add", str(marketplace_root)],
            ["codex", "plugin", "add", "codemap-py@borda-ai-rig", "--json"],
            ["codex", "plugin", "add", "codex-rig@borda-ai-rig", "--json"],
            ["codex", "plugin", "list", "--json"],
            [
                "/usr/bin/python3",
                str(adapter.resolve()),
                "context",
                "--category",
                "analysis",
                "--target",
                "lightning.pytorch.trainer.call",
                "--root",
                str(tmp_path.resolve()),
                "--out",
                str(home.codemap_context_path),
            ],
        ]


@pytest.mark.parametrize(
    "installed",
    [
        pytest.param([{"name": "codemap-py", "enabled": True}], id="missing-rig"),
        pytest.param(
            [
                {"name": "codemap-py", "enabled": True},
                {"name": "codex-rig", "enabled": False},
            ],
            id="disabled-rig",
        ),
        pytest.param(
            [
                {"name": "codemap-py", "enabled": True},
                {"name": "codex-rig", "enabled": True},
                {"name": "unrelated", "enabled": True},
            ],
            id="extra-plugin",
        ),
    ],
)
def test_final_skill_plugin_roster_rejects_missing_disabled_or_extra_entries(
    script_run_codex: Any,
    tmp_path: Path,
    installed: list[dict[str, object]],
) -> None:
    """Final C admission requires exactly the two enabled treatment plugins."""
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    home = script_run_codex.ArmHome("C_skill_required", home_path, {}, True, True)

    def command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"installed": installed, "available": []}),
            stderr="",
        )

    with pytest.raises(RuntimeError, match="plugin registration"):
        script_run_codex._verify_installed_plugin_pair(home, command_runner=command_runner)


def test_auth_source_is_copied_with_private_modes_and_removed_with_home(script_run_codex: Any, tmp_path: Path) -> None:
    """One explicit auth source must remain private and disappear with its arm home."""
    auth_source = tmp_path / "source-auth.json"
    auth_source.write_text('{"fixture_token":"do-not-report"}', encoding="utf-8")
    auth_source.chmod(0o600)

    with script_run_codex.prepare_arm_home(
        "A_plain",
        root=tmp_path,
        auth_source=auth_source,
    ) as home:
        home_path = home.path
        copied_auth = home.path / "auth.json"
        assert home.path.stat().st_mode & 0o777 == 0o700
        assert copied_auth.stat().st_mode & 0o777 == 0o600
        assert copied_auth.read_bytes() == auth_source.read_bytes()
        assert "do-not-report" not in json.dumps(script_run_codex.probe_arm_home(home))

    assert not home_path.exists()
    assert auth_source.read_text(encoding="utf-8") == '{"fixture_token":"do-not-report"}'


def test_arm_home_drops_batch_controls_from_codex_process_environment(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local approval, auth-source, result, and budget values must not reach Codex."""
    control_names = (
        "CODEX_PAID_APPROVAL",
        "CODEX_AUTH_SOURCE",
        "CODEX_RUN_DIR",
        "CODEX_MAX_WALL_CLOCK_SECONDS",
    )
    for name in control_names:
        monkeypatch.setenv(name, f"private-{name.lower()}")

    with script_run_codex.prepare_arm_home("A_plain", root=tmp_path) as home:
        assert all(name not in home.env for name in control_names)


def test_auth_source_rejects_insecure_permissions_and_symlinks(script_run_codex: Any, tmp_path: Path) -> None:
    """Credential propagation must fail closed on readable or indirect sources."""
    auth_source = tmp_path / "source-auth.json"
    auth_source.write_text("fixture", encoding="utf-8")
    auth_source.chmod(0o644)

    with pytest.raises(ValueError, match="permissions"):
        script_run_codex.prepare_arm_home(
            "A_plain",
            root=tmp_path,
            auth_source=auth_source,
        )

    auth_source.chmod(0o600)
    auth_link = tmp_path / "auth-link.json"
    auth_link.symlink_to(auth_source)
    with pytest.raises(ValueError, match="symlink"):
        script_run_codex.prepare_arm_home(
            "A_plain",
            root=tmp_path,
            auth_source=auth_link,
        )


def test_probe_verifies_authentication_without_disclosing_auth_source(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-model probe must prove login while returning no credential material."""
    auth_source = tmp_path / "source-auth.json"
    auth_source.write_text('{"fixture_token":"do-not-report"}', encoding="utf-8")
    auth_source.chmod(0o600)
    calls: list[list[str]] = []

    def command_runner(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        return _successful_plain_profile_command(command, **kwargs)

    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args, **_kwargs: None)
    fixture_index = tmp_path / "fixture-index.json"
    fixture_index.write_text("{}", encoding="utf-8")
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        index_path=fixture_index,
        auth_source=auth_source,
        command_runner=command_runner,
    )

    evidence = runner.probe_arm("A_plain")

    assert evidence["authenticated"] is True
    assert calls[0] == ["codex", "--version"]
    assert ["codex", "login", "status"] in calls
    assert "do-not-report" not in json.dumps(evidence)
    assert str(auth_source) not in json.dumps(evidence)


def test_runner_cleans_auth_home_when_transport_raises(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected execution failures cannot leave a copied credential on disk."""
    auth_source = tmp_path / "source-auth.json"
    auth_source.write_text('{"fixture_token":"do-not-report"}', encoding="utf-8")
    auth_source.chmod(0o600)
    homes: list[Path] = []
    original_prepare_arm_home = script_run_codex.prepare_arm_home

    def prepare_home(arm: str, **kwargs: Any) -> Any:
        home = original_prepare_arm_home(arm, root=tmp_path, **kwargs)
        homes.append(home.path)
        return home

    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_plain_plugin_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "prepare_arm_home", prepare_home)
    fixture_index = tmp_path / "fixture-index.json"
    fixture_index.write_text("{}", encoding="utf-8")
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        index_path=fixture_index,
        auth_source=auth_source,
        command_runner=_successful_plain_profile_command,
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )
    monkeypatch.setattr(
        runner,
        "_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture transport failure")),
    )

    with pytest.raises(RuntimeError, match="fixture transport failure"):
        runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "A_plain")

    assert homes
    assert all(not home.exists() for home in homes)


def test_probe_requires_verified_treatment_home(script_run_codex: Any, tmp_path: Path) -> None:
    """A copied or merely declared treatment home is not installation evidence."""
    with script_run_codex.prepare_arm_home("C_skill_required", root=tmp_path) as home:
        with pytest.raises(ValueError, match="verified"):
            script_run_codex.probe_arm_home(home)
        home.codemap_available = True
        home.codemap_verified = True
        with pytest.raises(ValueError, match="exact installed Skill binding"):
            script_run_codex.probe_arm_home(home)
        skill_path = home.path / "query-code" / "SKILL.md"
        skill_path.parent.mkdir()
        skill_path.write_text("# query-code\n", encoding="utf-8")
        home.codemap_skill_path = skill_path.resolve()
        home.env["CODEMAP_SKILL_FILE"] = "/wrong/SKILL.md"
        with pytest.raises(ValueError, match="exact installed Skill binding"):
            script_run_codex.probe_arm_home(home)
        home.env["CODEMAP_SKILL_FILE"] = str(skill_path.resolve())
        evidence = script_run_codex.probe_arm_home(home)

    assert evidence["codemap_available"] is True
    assert evidence["codemap_verified"] is True


def test_locked_runtime_requires_one_shared_locked_index_for_every_arm(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A/B/C share exact index identity while A's profile denies model access."""
    repo_path = tmp_path / "codemap-target"
    repo_path.mkdir()
    index_path = repo_path / ".cache" / "codemap" / "codemap-target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text('{"git_sha":"fixture-commit","scan_version":11}', encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "target_source": {"commit": "fixture-commit"},
                "index": {
                    "raw_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                    "git_sha": "fixture-commit",
                    "scan_version": 11,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(script_run_codex, "PARITY_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(script_run_codex, "_repo_sha", lambda _path: "fixture-commit")
    monkeypatch.setattr(
        script_run_codex.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    script_run_codex._validate_locked_runtime(repo_path, index_path, "A_plain", manifest_path)
    script_run_codex._validate_locked_runtime(repo_path, index_path, "B_direct_required", manifest_path)

    with pytest.raises(ValueError, match="requires the locked index"):
        script_run_codex._validate_locked_runtime(repo_path, None, "A_plain", manifest_path)


def test_result_exposes_native_telemetry_and_turn_limit_capability(script_run_codex: Any, tmp_path: Path) -> None:
    """Every result keeps measurable Codex-native fields and the turn-limit gap."""
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "B_direct_required")

    assert result.elapsed_s >= 0.0
    assert result.native_item_counts == {"agent_message": 1}
    assert result.native_attempt_events == [result.raw_events]
    assert result.telemetry_contract_id == "canonical-skill-file-v1"
    assert result.tool_elapsed_s is None
    assert result.tool_result_tokens is None
    assert result.error_type == ""
    assert result.turn_budget_enforced is False
    assert result.reasoning_effort == "high"


def test_default_evaluator_score_and_identity_match_claude_reference(
    script_run_codex: Any, script_run_bench: Any
) -> None:
    """The Codex adapter must call the exact Claude evaluator and provenance path."""
    task = next(task for task in core.load_task_suite(SUITE_PATH) if task["id"] == "FN-02")
    output_text = "## Callers\n" + "\n".join(task["ground_truth"]["fn_callers"])

    claude = script_run_bench._evaluate_shared_task(task, output_text)
    codex = script_run_codex._default_evaluator(task, output_text)

    assert codex.scored is claude.scored
    assert codex.correct is claude.correct
    assert codex.quality_score == pytest.approx(claude.recall)
    assert codex.components["recall"] == pytest.approx(claude.recall)
    assert script_run_codex._evaluator_identity(
        task, script_run_codex._default_evaluator
    ) == script_run_bench._evaluator_provenance(task)


def test_runner_default_timeout_matches_shared_parity_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """The Codex adapter inherits the same provider-neutral wall-clock budget."""
    runner = script_run_codex.CodexRunner("fixture-model", tmp_path)

    assert runner.timeout == core.PARITY_TIMEOUT_SECONDS == 600


def test_subprocess_timeout_and_nonzero_exit_keep_distinct_error_types(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transport timeout and nonzero exit remain separately diagnosable."""
    runner = script_run_codex.CodexRunner("fixture-model", tmp_path)

    def timeout(*_args: Any, **_kwargs: Any) -> None:
        raise script_run_codex.subprocess.TimeoutExpired(["codex"], 600)

    monkeypatch.setattr(script_run_codex.subprocess, "run", timeout)
    timed_out = script_run_codex.parse_codex_jsonl(runner._subprocess(["codex"], {}))

    assert timed_out.incomplete is True
    assert timed_out.error_type == "timeout"

    monkeypatch.setattr(
        script_run_codex.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=7,
            stdout=_completed_stream(output="partial answer"),
            stderr="CLI failed",
        ),
    )
    nonzero = script_run_codex.parse_codex_jsonl(runner._subprocess(["codex"], {}))

    assert nonzero.output_text == "partial answer"
    assert nonzero.incomplete is True
    assert nonzero.error_type == "non_zero_exit"


def test_main_dry_run_never_requires_or_writes_output(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-model planning performs probes without reserving a result artifact."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(
        script_run_codex,
        "deterministic_arm_order",
        lambda *_args, **_kwargs: script_run_codex.CODEX_STRUCTURAL_ARMS,
    )

    class FixtureRunner:
        """Supply deterministic no-model arm probes."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, _arm: str) -> dict[str, bool]:
            return {"codemap_available": False}

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        dry_run=True,
    )

    assert list(tmp_path.iterdir()) == []


def test_dry_run_prints_the_proposed_complete_run_limit_without_model_execution(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewable plan exposes the exact proposed total-run authorization boundary."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    planned: list[str] = []

    class FixtureRunner:
        """Supply deterministic no-model probe evidence."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, _arm: str) -> dict[str, bool]:
            return {"codemap_available": False}

    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "print", planned.append, raising=False)

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        arm="A_plain",
        dry_run=True,
        max_wall_clock_seconds=86_400.0,
    )

    assert "CONTROL\tcell_wall_clock_seconds=600\tmax_wall_clock_seconds=86400" in planned
    with pytest.raises(ValueError, match="max-wall-clock-seconds"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            dry_run=True,
            max_wall_clock_seconds=0.0,
        )


def test_main_rejects_missing_or_existing_output_before_model_execution(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid execution must have a fresh durable destination before constructing a runner."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(
        script_run_codex,
        "CodexRunner",
        lambda *_args, **_kwargs: pytest.fail("invalid output reached runner construction"),
    )

    with pytest.raises(ValueError, match="output-path"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
        )

    output_path = tmp_path / "existing.jsonl"
    output_path.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            output_path=output_path,
        )
    assert output_path.read_text(encoding="utf-8") == "preserve\n"


def test_main_rejects_existing_canonical_telemetry_before_model_execution_or_mutation(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A derived canonical sidecar cannot be replaced by a new paid run."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    output_path = tmp_path / "fresh.jsonl"
    metadata_path = tmp_path / "fresh-metadata.json"
    canonical_path = script_run_codex._canonical_telemetry_path(output_path)
    canonical_path.write_text('{"preserve": true}\n', encoding="utf-8")
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(
        script_run_codex,
        "CodexRunner",
        lambda *_args, **_kwargs: pytest.fail("existing sidecar reached runner construction"),
    )

    with pytest.raises(FileExistsError, match="telemetry-canonical\\.jsonl"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            output_path=output_path,
            metadata_path=metadata_path,
            max_wall_clock_seconds=600.0,
        )

    assert canonical_path.read_text(encoding="utf-8") == '{"preserve": true}\n'
    assert not output_path.exists()
    assert not metadata_path.exists()


def test_main_requires_positive_complete_run_wall_clock_limit_before_output_reservation(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid execution cannot begin without a bounded human-reviewable total exposure."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    output_path = tmp_path / "paid.jsonl"

    for limit in (None, 0.0, -1.0):
        with pytest.raises(ValueError, match="max-wall-clock-seconds"):
            script_run_codex.main(
                repo_path=tmp_path,
                model=script_run_codex.PARITY_CODEX_MODEL,
                tasks_path=tmp_path / "tasks.json",
                output_path=output_path,
                max_wall_clock_seconds=limit,
            )
        assert not output_path.exists()


def test_main_stops_at_complete_run_deadline_after_persisting_finished_cells(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The complete-run deadline stops new cells without erasing durable prior evidence."""
    tasks = [
        {"id": "first", "prompt": "one", "type": "demo"},
        {"id": "second", "prompt": "two", "type": "demo"},
    ]
    observed_deadlines: list[float] = []

    class FixtureRunner:
        """Return a serializable row while recording the enforced absolute deadline."""

        def __init__(self, model: str, *_args: Any, **_kwargs: Any) -> None:
            self.model = model

        def run(
            self,
            task: dict[str, Any],
            arm: str,
            *,
            repetition: int = 1,
            deadline: float | None = None,
        ) -> Any:
            assert deadline is not None
            observed_deadlines.append(deadline)
            return script_run_codex.CodexRun(
                arm=arm,
                task_id=task["id"],
                task_type=task["type"],
                model=self.model,
                parity_arm=arm,
                repetition=repetition,
                success=True,
                scoreable=True,
                input_tokens=1,
                output_tokens=1,
                compliance=True,
            )

    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(script_run_codex, "_validate_execution_manifest", lambda _path: None)
    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "deterministic_arm_order", lambda *_args, **_kwargs: ("A_plain",))
    clock = iter([100.0, 100.0, 111.0])
    monkeypatch.setattr(script_run_codex.time, "monotonic", lambda: next(clock))
    output_path = tmp_path / "deadline.jsonl"

    with pytest.raises(TimeoutError, match="complete-run wall-clock limit"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            output_path=output_path,
            max_wall_clock_seconds=10.0,
            arm="A_plain",
        )

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [(row["task_id"], row["arm"]) for row in rows] == [("first", "A_plain")]
    assert rows[0]["run_wall_clock_limit_s"] == pytest.approx(10.0)
    assert observed_deadlines == [pytest.approx(110.0)]
    metadata = json.loads((tmp_path / "deadline-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["persisted_cells"] == 1
    assert metadata["last_persisted_coordinate"] == {
        "task_id": "first",
        "repetition": 1,
        "arm": "A_plain",
    }
    assert metadata["error"]["type"] == "TimeoutError"
    stdout = capsys.readouterr().out
    metadata_path = tmp_path / "deadline-metadata.json"
    assert stdout.count(str(output_path)) == 1
    assert stdout.count(str(metadata_path)) == 1
    assert all(
        str(path) not in line
        for path in (output_path, metadata_path)
        for line in stdout.splitlines()
        if line.startswith("SUMMARY")
    )


def test_main_rejects_unreviewed_implementation_revision_before_reserving_output(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid execution cannot use a manifest that does not hash the active runner."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "experiment_revision": "prior-fixture-revision",
                "implementation_contract": {
                    "artifact_sha256": {"run_codex_structural": "0" * 64},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(
        script_run_codex,
        "CodexRunner",
        lambda *_args, **_kwargs: pytest.fail("unreviewed manifest reached runner construction"),
    )
    output_path = tmp_path / "unreviewed.jsonl"

    with pytest.raises(ValueError, match="manifest locked to this runner"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            manifest_path=manifest_path,
            output_path=output_path,
            max_wall_clock_seconds=600.0,
        )

    assert not output_path.exists()


def test_main_persists_each_completed_cell_in_task_then_arm_order(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial JSONL artifact retains every completed cell in deterministic plan order."""
    tasks = [
        {"id": "first", "prompt": "one", "type": "demo"},
        {"id": "second", "prompt": "two", "type": "demo"},
    ]
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")

    class FixtureRunner:
        """Return one minimal serializable result per planned cell."""

        def __init__(self, model: str, *_args: Any, **_kwargs: Any) -> None:
            self.model = model

        def run(
            self,
            task: dict[str, Any],
            arm: str,
            *,
            repetition: int = 1,
            deadline: float | None = None,
        ) -> Any:
            assert deadline is not None
            return script_run_codex.CodexRun(
                arm=arm,
                task_id=task["id"],
                task_type=task["type"],
                model=self.model,
                parity_arm=arm,
                repetition=repetition,
                success=True,
                scoreable=True,
                input_tokens=1,
                output_tokens=1,
                compliance=True,
            )

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "_validate_execution_manifest", lambda _path: None)
    monkeypatch.setattr(
        script_run_codex,
        "deterministic_arm_order",
        lambda *_args, **_kwargs: script_run_codex.CODEX_STRUCTURAL_ARMS,
    )
    output_path = tmp_path / "smoke.jsonl"

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        output_path=output_path,
        repetitions=3,
        max_wall_clock_seconds=600.0,
    )

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [(row["provider"], row["task_id"], row["repetition"], row["arm"]) for row in rows] == [
        ("codex", task["id"], repetition, arm)
        for task in tasks
        for repetition in range(1, 4)
        for arm in script_run_codex.CODEX_STRUCTURAL_ARMS
    ]
    metadata = json.loads((tmp_path / "smoke-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert metadata["persisted_cells"] == 18
    assert metadata["execution"]["planned_cells"] == 18
    assert metadata["auth_source_recorded"] is False
    assert metadata["artifacts"]["canonical_telemetry_pooling_eligible"] is True
    assert metadata["artifacts"]["canonical_telemetry_pooling_ineligibility_reasons"] == []


def test_main_records_cell_failures_and_continues_after_smoke(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The full run reports treatment failures without optional cell-level stopping."""
    tasks = [
        {"id": "first", "prompt": "one", "type": "demo"},
        {"id": "second", "prompt": "two", "type": "demo"},
    ]

    class FixtureRunner:
        """Return one non-compliant cell followed by one compliant cell."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def run(self, task: dict[str, Any], arm: str, **_kwargs: Any) -> Any:
            return script_run_codex.CodexRun(
                arm=arm,
                task_id=task["id"],
                task_type="demo",
                model=script_run_codex.PARITY_CODEX_MODEL,
                success=True,
                scoreable=True,
                input_tokens=1,
                output_tokens=1,
                compliance=task["id"] == "second",
            )

    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(script_run_codex, "_validate_execution_manifest", lambda _path: None)
    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    output_path = tmp_path / "admission.jsonl"

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        output_path=output_path,
        arm="B_direct_required",
        max_wall_clock_seconds=600,
    )

    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 2
    metadata = json.loads((tmp_path / "admission-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert metadata["persisted_cells"] == 2
    assert metadata["cell_outcomes"]["compliance_failed"] == 1
    assert metadata["artifacts"]["canonical_telemetry_pooling_eligible"] is False
    assert metadata["artifacts"]["canonical_telemetry_pooling_ineligibility_reasons"] == ["required_use_missing"]
    stdout = capsys.readouterr().out
    assert stdout.count("quality=    ?") == 2
    assert sum(line == "LEGEND" for line in stdout.splitlines()) == 1
    assert sum(line == "END LEGEND" for line in stdout.splitlines()) == 1
    assert all(not line.startswith("LEGEND  ") for line in stdout.splitlines())
    assert stdout.count(f"ARTIFACTS  telemetry={output_path}") == 1
    assert stdout.count(str(tmp_path / "admission-metadata.json")) == 1
    assert str(output_path) not in "\n".join(line for line in stdout.splitlines() if line.startswith("RESULT"))


def test_main_emits_plans_only_for_dry_runs_and_paths_only_in_artifact_announcement(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run exposes its plan while a paid run exposes only results and one path announcement."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}

    class FixtureRunner:
        """Provide deterministic probe evidence and one successful paid cell."""

        def __init__(self, model: str, *_args: Any, **_kwargs: Any) -> None:
            self.model = model

        def probe_arm(self, _arm: str) -> dict[str, bool]:
            return {"codemap_available": False}

        def run(self, task: dict[str, Any], arm: str, **_kwargs: Any) -> Any:
            return script_run_codex.CodexRun(
                arm=arm,
                task_id=task["id"],
                task_type=task["type"],
                model=self.model,
                success=True,
                scoreable=True,
                input_tokens=1,
                output_tokens=1,
                compliance=None,
            )

    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: [task])
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    monkeypatch.setattr(script_run_codex, "_validate_execution_manifest", lambda _path: None)
    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        arm="A_plain",
        dry_run=True,
    )
    dry_stdout = capsys.readouterr().out
    assert [line for line in dry_stdout.splitlines() if line.startswith("PLAN")] == ["PLAN    fixture  rep=1  A_plain"]

    output_path = tmp_path / "paid.jsonl"
    metadata_path = tmp_path / "paid-metadata.json"
    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        output_path=output_path,
        arm="A_plain",
        max_wall_clock_seconds=600.0,
    )
    paid_stdout = capsys.readouterr().out
    assert not any(line.startswith("PLAN") for line in paid_stdout.splitlines())
    assert paid_stdout.count(str(output_path)) == 1
    assert paid_stdout.count(str(metadata_path)) == 1
    assert all(
        str(path) not in line
        for path in (output_path, metadata_path)
        for line in paid_stdout.splitlines()
        if line.startswith(("RESULT", "SUMMARY"))
    )


def test_output_legend_defines_treatments_tasks_and_measurement_marks(script_run_codex: Any) -> None:
    """The upfront legend makes every compact terminal field independently interpretable."""
    legend = script_run_codex._OUTPUT_LEGEND

    assert legend.startswith("LEGEND\n")
    assert legend.endswith("END LEGEND")
    assert all(not line.startswith("LEGEND  ") for line in legend.splitlines())
    assert "treatments: A_plain=no Codemap, B_direct=direct Codemap required, C_skill=Codemap Skill required" in legend
    assert "B_direct_required" not in legend
    assert "C_skill_required" not in legend
    assert "status: ✓ completed, ✗ failed" in legend
    assert "quality: continuous [0,1], ? unscoreable" in legend
    assert "treatment: ✓ assigned arm followed, ✗ assigned arm not followed" in legend
    assert "codemap-used: ✓ Codemap call observed; ✗ no Codemap call (expected for A_plain)" in legend
    assert "or required use missed (B/C)" in legend
    assert "input tokens: gross total; cached and fresh details remain in telemetry" in legend
    assert "tokens: k=1,000, M=1,000,000" in legend


@pytest.mark.parametrize(
    ("canonical_arm", "display_arm"),
    [
        pytest.param("A_plain", "A_plain", id="plain"),
        pytest.param("B_direct_required", "B_direct", id="direct"),
        pytest.param("C_skill_required", "C_skill", id="skill"),
    ],
)
def test_human_arm_labels_shorten_only_presentation_names(
    script_run_codex: Any,
    canonical_arm: str,
    display_arm: str,
) -> None:
    """PLAN/RESULT rows use short labels while machine arm IDs remain canonical."""
    plan = script_run_codex._format_plan_row("FN-02", 1, canonical_arm)
    result = script_run_codex._format_result_row(
        status="✓",
        task_id="FN-02",
        repetition=1,
        arm=canonical_arm,
        input_tokens=100,
        cached_input_tokens=20,
        fresh_tokens=80,
        output_tokens=1,
        elapsed_s=1.0,
        quality="1.000",
        adherence=True,
        codemap_used=canonical_arm != "A_plain",
    )

    assert display_arm in plan
    assert display_arm in result
    if canonical_arm != display_arm:
        assert canonical_arm not in plan
        assert canonical_arm not in result


@pytest.mark.parametrize(
    ("code", "meaning"),
    [
        pytest.param("SE", "symbol extraction", id="symbol-extraction"),
        pytest.param("FN", "function-call graph", id="function-call-graph"),
        pytest.param("RV", "review assistance", id="review-assistance"),
        pytest.param("CQ", "code quality", id="code-quality"),
        pytest.param("BR", "blast radius", id="blast-radius"),
        pytest.param("DG", "debug from trace", id="debug-from-trace"),
        pytest.param("FT", "feature scaffolding", id="feature-scaffolding"),
        pytest.param("RI", "real issue", id="real-issue"),
        pytest.param("DI", "diff impact", id="diff-impact"),
        pytest.param("GR", "graph reasoning", id="graph-reasoning"),
        pytest.param("MB", "module blast radius", id="module-blast-radius"),
    ],
)
def test_output_legend_defines_each_task_code(script_run_codex: Any, code: str, meaning: str) -> None:
    """Every task code in compact output expands to its benchmark meaning."""
    assert f"{code}={meaning}" in script_run_codex._OUTPUT_LEGEND


def _render_result_stream(input_text: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the runner's stream-rendering mode with captured text output."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--render-results", *args],
        cwd=BENCHMARKS_DIR.parent,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("arm", "color_code"),
    [
        pytest.param("A_plain", "33", id="plain-yellow"),
        pytest.param("B_direct_required", "36", id="direct-cyan"),
        pytest.param("C_skill_required", "35", id="skill-magenta"),
    ],
)
def test_render_results_force_color_maps_each_arm_to_its_review_color(arm: str, color_code: str) -> None:
    """The test-only flag proves the exact A/B/C terminal palette."""
    row = f"RESULT  ✓  FN-02  rep=1  {arm}  quality=1.000\n"

    completed = _render_result_stream(row, "--force-color")

    assert completed.returncode == 0, completed.stderr
    assert f"\x1b[{color_code}m" in completed.stdout
    assert row.rstrip("\n") in completed.stdout
    assert completed.stdout.endswith("\x1b[0m\n")


def test_render_results_force_color_renders_legend_as_bounded_rich_panel() -> None:
    """Interactive rendering turns the plain legend block into one titled Rich box."""
    input_text = (
        "LEGEND\n"
        "  treatments: A_plain=no Codemap\n"
        "  status: ✓ completed, ✗ failed\n"
        "END LEGEND\n"
        "RESULT  ✓  FN-02  rep=1  A_plain  quality=1.000\n"
    )

    completed = _render_result_stream(input_text, "--force-color")

    assert completed.returncode == 0, completed.stderr
    assert "Legend" in completed.stdout
    assert "End legend" in completed.stdout
    assert "treatments: A_plain=no Codemap" in completed.stdout
    assert completed.stdout.count("Legend") == 1
    assert completed.stdout.count("End legend") == 1


def test_render_results_preserves_noninteractive_stream_byte_for_byte() -> None:
    """Redirected renderer output remains a plain machine-reviewable stream."""
    input_text = "INFO keep this byte-for-byte\nRESULT  ✓  FN-02  rep=1  A_plain  quality=1.000\n"

    completed = _render_result_stream(input_text)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == input_text
    assert "\x1b[" not in completed.stdout


def test_render_results_noninteractive_legend_is_byte_stable() -> None:
    """The noninteractive renderer does not rewrite a bounded plain legend."""
    input_text = (
        "LEGEND\n"
        "  treatments: A_plain=no Codemap\n"
        "  status: ✓ completed, ✗ failed\n"
        "END LEGEND\n"
        "RESULT  ✓  FN-02  rep=1  A_plain  quality=1.000\n"
    )

    completed = _render_result_stream(input_text)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == input_text


def test_render_results_force_color_preserves_unknown_and_non_result_rows() -> None:
    """Only recognized A/B/C RESULT rows receive terminal styling."""
    input_text = "INFO preparation\nRESULT  ✓  FN-02  rep=1  unknown  quality=1.000\n"

    completed = _render_result_stream(input_text, "--force-color")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == input_text
    assert "\x1b[" not in completed.stdout


def test_render_results_hide_plan_omits_only_human_plan_rows() -> None:
    """The optional renderer filter removes PLAN rows without changing other output."""
    input_text = (
        "LEGEND  fields\n"
        "PROBE\tA_plain\tcodemap=false\n"
        "PLAN    SE-01  rep=1  A_plain\n"
        "PLAN    FN-02  rep=1  B_direct_required\n"
        "CONTROL\tcell_wall_clock_seconds=600\n"
        "ARTIFACTS  telemetry=run.jsonl  metadata=metadata.json\n"
        "RESULT  ✓  SE-01  rep=1  A_plain  quality=1.000\n"
        "SUMMARY\tstatus=completed\n"
    )
    expected = (
        "LEGEND  fields\n"
        "PROBE\tA_plain\tcodemap=false\n"
        "CONTROL\tcell_wall_clock_seconds=600\n"
        "ARTIFACTS  telemetry=run.jsonl  metadata=metadata.json\n"
        "RESULT  ✓  SE-01  rep=1  A_plain  quality=1.000\n"
        "SUMMARY\tstatus=completed\n"
    )

    completed = _render_result_stream(input_text, "--hide-plan")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == expected


def test_hide_plan_requires_render_results_mode() -> None:
    """The internal stream filter cannot alter normal benchmark execution."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--hide-plan"],
        cwd=BENCHMARKS_DIR.parent,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "--hide-plan requires --render-results" in completed.stderr


@pytest.mark.parametrize(
    (
        "arm",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "elapsed_s",
        "quality",
        "adherence",
        "codemap_used",
        "expected",
    ),
    [
        pytest.param(
            "A_plain",
            44_441,
            2_000,
            658,
            17.2,
            "1.000",
            True,
            False,
            "RESULT  ✓  SE-01  rep=1  A_plain   in= 44.4k  out=   658  time=  17s  quality=1.000  treatment:✓  codemap-used:✗",
            id="plain-small-output",
        ),
        pytest.param(
            "C_skill_required",
            74_530,
            10_000,
            995,
            24.0,
            "1.000",
            True,
            True,
            "RESULT  ✓  SE-01  rep=1  C_skill   in= 74.5k  out=   995  time=  24s  quality=1.000  treatment:✓  codemap-used:✓",
            id="skill-required",
        ),
        pytest.param(
            "B_direct_required",
            1_230_920,
            230_920,
            1_475,
            97.6,
            "?",
            False,
            True,
            "RESULT  ✗  SE-01  rep=1  B_direct  in=  1.2M  out=  1.5k  time=1m38s  quality=    ?  treatment:✗  codemap-used:✓",
            id="direct-million-and-failure",
        ),
    ],
)
def test_format_result_row_uses_shared_human_units_and_fixed_columns(
    script_run_codex: Any,
    arm: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    elapsed_s: float,
    quality: str,
    adherence: bool,
    codemap_used: bool,
    expected: str,
) -> None:
    """Terminal rows remain compact and visually comparable across all Codex arms."""
    status = "✓" if adherence else "✗"

    assert (
        script_run_codex._format_result_row(
            status=status,
            task_id="SE-01",
            repetition=1,
            arm=arm,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            fresh_tokens=input_tokens - cached_input_tokens,
            output_tokens=output_tokens,
            elapsed_s=elapsed_s,
            quality=quality,
            adherence=adherence,
            codemap_used=codemap_used,
        )
        == expected
    )


def test_format_result_row_hides_inconsistent_cache_detail(script_run_codex: Any) -> None:
    """The terminal display must remain gross-only even for inconsistent cache telemetry."""
    row = script_run_codex._format_result_row(
        status="✓",
        task_id="SE-01",
        repetition=1,
        arm="A_plain",
        input_tokens=25,
        cached_input_tokens=80,
        fresh_tokens=None,
        output_tokens=1,
        elapsed_s=1.0,
        quality="1.000",
        adherence=True,
        codemap_used=False,
    )

    assert "in=    25  out=" in row
    assert "/" not in row


def test_format_result_row_separates_treatment_from_observed_codemap_use(
    script_run_codex: Any,
) -> None:
    """A contaminated plain arm reports use even though its treatment failed."""
    row = script_run_codex._format_result_row(
        status="✗",
        task_id="FN-02",
        repetition=1,
        arm="A_plain",
        input_tokens=86_600,
        cached_input_tokens=77_300,
        fresh_tokens=9_300,
        output_tokens=1,
        elapsed_s=1.0,
        quality="1.000",
        adherence=False,
        codemap_used=True,
    )

    assert "treatment:✗  codemap-used:✓" in row
    assert "in= 86.6k  out=" in row
    assert "/" not in row


@pytest.mark.parametrize(
    ("is_terminal", "expected_rich_calls", "expected_plain_calls"),
    [
        pytest.param(True, 1, 0, id="interactive-rich-color"),
        pytest.param(False, 0, 1, id="redirected-plain-text"),
    ],
)
def test_print_arm_row_colors_only_interactive_output(
    script_run_codex: Any,
    monkeypatch: pytest.MonkeyPatch,
    is_terminal: bool,
    expected_rich_calls: int,
    expected_plain_calls: int,
) -> None:
    """Color aids terminal navigation without contaminating redirected benchmark logs."""
    rich_calls: list[tuple[str, dict[str, Any]]] = []
    plain_calls: list[str] = []

    class FixtureConsole:
        """Record Rich calls behind a configurable terminal boundary."""

        def __init__(self) -> None:
            self.is_terminal = is_terminal

        def print(self, row: str, **kwargs: Any) -> None:
            rich_calls.append((row, kwargs))

    monkeypatch.setattr(script_run_codex, "_console", FixtureConsole())
    monkeypatch.setattr(script_run_codex, "print", plain_calls.append, raising=False)

    script_run_codex._print_arm_row("RESULT fixture", "B_direct_required")

    assert len(rich_calls) == expected_rich_calls
    assert len(plain_calls) == expected_plain_calls
    if rich_calls:
        assert rich_calls == [
            (
                "RESULT fixture",
                {"style": "cyan", "markup": False, "soft_wrap": True},
            )
        ]
    if plain_calls:
        assert plain_calls == ["RESULT fixture"]


def test_main_filters_locked_tasks_in_suite_order_and_rejects_invalid_ids(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke selection keeps canonical suite order without accepting unknown or duplicate IDs."""
    tasks = [
        {"id": "first", "prompt": "one", "type": "demo"},
        {"id": "second", "prompt": "two", "type": "demo"},
    ]
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    planned: list[str] = []

    class FixtureRunner:
        """Record selected dry-run tasks without model execution."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, _arm: str) -> dict[str, bool]:
            return {"codemap_available": False}

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(
        script_run_codex,
        "print",
        lambda text: planned.append(text),
        raising=False,
    )

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        task_ids=["second"],
        arm="A_plain",
        dry_run=True,
    )

    assert any(row == "PLAN    second  rep=1  A_plain" for row in planned)
    assert not any("first" in row for row in planned)
    with pytest.raises(ValueError, match="unique"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            task_ids=["first", "first"],
            dry_run=True,
        )
    with pytest.raises(ValueError, match="unknown"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            task_ids=["missing"],
            dry_run=True,
        )
    with pytest.raises(ValueError, match="positive"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            repetitions=0,
            dry_run=True,
        )


def test_main_plans_every_preregistered_pilot_coordinate_once(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock the six-task, three-repetition pilot to exactly 54 ordered cells."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pilot_ids = manifest["preregistered_cells"]["structural_pilot_task_ids"]
    repetitions = manifest["preregistered_cells"]["pilot_repetitions"]
    tasks = [{"id": task_id, "prompt": task_id, "type": "demo"} for task_id in pilot_ids]
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path, *_args: tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda *_args: "fixture-revision")
    planned: list[str] = []

    class FixtureRunner:
        """Provide no-model probe evidence while the plan is constructed."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, arm: str) -> dict[str, bool]:
            return {"codemap_available": arm != "A_plain"}

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "print", planned.append, raising=False)
    monkeypatch.setattr(
        script_run_codex,
        "deterministic_arm_order",
        lambda *_args, **_kwargs: script_run_codex.CODEX_STRUCTURAL_ARMS,
    )

    script_run_codex.main(
        repo_path=tmp_path,
        model="gpt-5.6-luna",
        tasks_path=tmp_path / "tasks.json",
        task_ids=pilot_ids,
        repetitions=repetitions,
        dry_run=True,
    )

    plan_rows = [line.split()[1:] for line in planned if line.startswith("PLAN ")]
    expected = [
        [task_id, f"rep={repetition}", arm]
        for task_id in pilot_ids
        for repetition in range(1, repetitions + 1)
        for arm in (
            script_run_codex._DISPLAY_ARM_LABELS[canonical_arm]
            for canonical_arm in script_run_codex.CODEX_STRUCTURAL_ARMS
        )
    ]
    assert plan_rows == expected
    assert len(plan_rows) == len({tuple(row) for row in plan_rows}) == 54


def test_codex_arm_envelopes_define_plain_cli_and_skill_treatments(script_run_codex: Any) -> None:
    """The new Codex arms must make delivery mode and required use unambiguous."""
    assert script_run_codex.CODEX_STRUCTURAL_ARMS == (
        "A_plain",
        "B_direct_required",
        "C_skill_required",
    )
    assert "Codemap is absent" in script_run_codex._arm_envelope("A_plain")
    assert '"$CODEMAP_BIN" query --compact' in script_run_codex._arm_envelope("B_direct_required")
    assert "dedicated native command item" in script_run_codex._arm_envelope("B_direct_required")
    assert "$codemap-py:query-code" in script_run_codex._arm_envelope("C_skill_required")
    assert "separate dedicated native item" in script_run_codex._arm_envelope("C_skill_required")
    assert 'cat "$CODEMAP_SKILL_FILE"' in script_run_codex._arm_envelope("C_skill_required")
    assert "sed -n" not in script_run_codex._arm_envelope("C_skill_required")


@pytest.mark.parametrize(
    ("command", "status", "exit_code", "output", "expected_credit"),
    [
        pytest.param(
            '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            True,
            id="canonical-native-item",
        ),
        pytest.param(
            "$CODEMAP_BIN query --compact fn-rdeps pkg.core",
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="unquoted-launcher",
        ),
        pytest.param(
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps pkg.core',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="alias",
        ),
        pytest.param(
            'CODEMAP_BIN=/wrong/codemap-py; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="assignment",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core; printf done',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="compound-command",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core && printf done',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="control-operator",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core > result.json',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="redirection",
        ),
        pytest.param(
            "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact rdeps pkg.core'",
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}',
            True,
            id="one-outer-transport-wrapper",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            "0",
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="noninteger-exit-code",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            1,
            '{"index":{"query_complete":true,"compact":true}}',
            False,
            id="nonzero-exit-code",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            0,
            '{"index":{"query_complete":true}}',
            False,
            id="missing-compact-output",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            0,
            'diagnostic\n{"index":{"query_complete":true,"compact":true}}',
            False,
            id="json-prefix",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}\ndiagnostic',
            False,
            id="json-suffix",
        ),
        pytest.param(
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            "completed",
            0,
            '{"index":{"query_complete":true,"compact":true}}\n{}',
            False,
            id="multiple-json-documents",
        ),
    ],
)
def test_canonical_native_item_query_contract(
    script_run_codex: Any,
    command: str,
    status: str,
    exit_code: object,
    output: str,
    expected_credit: bool,
) -> None:
    """Credit B only for the standalone canonical native command item.

    Prevents telemetry from treating shell interpretation or loosely embedded
    JSON as equivalent to the future benchmark's explicit native-item proof.
    """
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": status,
                    "exit_code": exit_code,
                    "aggregated_output": output,
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == int(expected_credit)
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is expected_credit


def test_canonical_native_query_allows_auxiliary_separate_events(script_run_codex: Any) -> None:
    """Separate native command items cannot contaminate a canonical query item."""
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": "pwd",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "/fixture\n",
                },
                {
                    "type": "command_execution",
                    "command": '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"',
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                },
                {
                    "type": "command_execution",
                    "command": "printf complete",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "complete",
                },
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == 1
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is True


@pytest.mark.parametrize(
    ("command", "expected_credit"),
    [
        pytest.param('"$CODEMAP_BIN" query --compact coupled', True, id="quoted-public-zero-argument-query"),
        pytest.param('"${CODEMAP_BIN}" query --compact coupled', True, id="braced-public-zero-argument-query"),
        pytest.param('"$CODEMAP_BIN" query --help', False, id="help-only"),
    ],
)
def test_public_query_forms_credit_completed_queries_but_not_help(
    script_run_codex: Any,
    command: str,
    expected_credit: bool,
) -> None:
    """A public compact query may omit target arguments; a help call is not evidence."""
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == int(expected_credit)
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is expected_credit


def test_skill_activation_then_public_coupled_query_satisfies_compliance_and_adherence(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """C requires its exact Skill activation plus one completed public compact query."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": 'cat "$CODEMAP_SKILL_FILE"',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": '"${CODEMAP_BIN}" query --compact coupled',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )
    compliance = script_run_codex._arm_compliance("C_skill_required", parsed)

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_skill_compact_successful_calls == 1
    assert compliance is True
    assert core.treatment_adherence("C_skill_required", codemap_use_compliance=compliance, contaminated=False) is True


@pytest.mark.parametrize(
    ("read_command", "read_output", "query_first", "expected_credit"),
    [
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "locked", False, True, id="canonical-skill-file"),
        pytest.param(
            "/bin/zsh -lc 'cat \"$CODEMAP_SKILL_FILE\"'",
            "locked",
            False,
            True,
            id="canonical-transport-wrapper",
        ),
        pytest.param("cat {skill}", "locked", False, False, id="literal-path"),
        pytest.param("sed -n 1,260p {skill}", "locked", False, False, id="static-sed-reader"),
        pytest.param("sed -n '1,$p' {skill}", "locked", False, False, id="dynamic-sed-reader"),
        pytest.param("cat $CODEMAP_SKILL_FILE", "locked", False, False, id="unquoted-skill-file"),
        pytest.param('cat "$OTHER_SKILL_FILE"', "locked", False, False, id="wrong-variable"),
        pytest.param("skill_path={skill}; cat $skill_path", "locked", False, False, id="bound-reader"),
        pytest.param("cat {skill}; printf activated", "lockedactivated", False, False, id="compound-reader"),
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "changed", False, False, id="wrong-reader-bytes"),
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "locked", True, False, id="read-after-query"),
    ],
)
def test_canonical_C_skill_delivery_requires_the_runner_owned_skill_file(
    script_run_codex: Any,
    tmp_path: Path,
    read_command: str,
    read_output: str,
    query_first: bool,
    expected_credit: bool,
) -> None:
    """Require the exact runner-owned Skill command before a canonical query."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"locked"
    skill_path.write_bytes(skill_bytes)
    reader = {
        "type": "item.completed",
        "item": {
            "id": "skill-read",
            "type": "command_execution",
            "command": read_command.format(skill=skill_path),
            "status": "completed",
            "exit_code": 0,
            "aggregated_output": skill_bytes.decode() if read_output == "locked" else read_output,
        },
    }
    query = {
        "type": "item.completed",
        "item": {
            "id": "query",
            "type": "command_execution",
            "command": '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"',
            "status": "completed",
            "exit_code": 0,
            "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
        },
    }
    ordered_events = [query, reader] if query_first else [reader, query]
    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in [*ordered_events, {"type": "turn.completed"}]),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.codemap_skill_compact_successful_calls == int(expected_credit)
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is expected_credit


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("$CODEMAP_BIN query --compact rdeps pkg.core", False, id="historical-unquoted-query"),
        pytest.param('"$CODEMAP_BIN" query --compact rdeps pkg.core', True, id="quoted-query"),
        pytest.param("echo $CODEMAP_BIN", False, id="echo-inspection"),
        pytest.param("env | rg CODEMAP_BIN", False, id="environment-inspection"),
        pytest.param('"$CODEMAP_BIN" --help', False, id="launcher-inspection"),
        pytest.param("$CODEMAP_BIN query --compact rdeps pkg.core &", False, id="historical-background"),
        pytest.param("$CODEMAP_BIN query --compact rdeps pkg.core\nwait", False, id="historical-newline-wait"),
        pytest.param("`$CODEMAP_BIN query --compact rdeps pkg.core`", False, id="backticks"),
        pytest.param('$("$CODEMAP_BIN" query --compact rdeps pkg.core)', False, id="historical-substitution"),
        pytest.param('("$CODEMAP_BIN" query --compact rdeps pkg.core)', False, id="historical-subshell-group"),
        pytest.param('{ "$CODEMAP_BIN" query --compact rdeps pkg.core; }', False, id="brace-group"),
        pytest.param('"$CODEMAP_BIN" query --compact rdeps pkg.core > out.json', False, id="historical-redirect"),
        pytest.param('"$CODEMAP_BIN" query --compact rdeps pkg.core 2>&1', False, id="historical-stderr-redirect"),
    ],
)
def test_historical_shell_query_shapes_reject_the_native_item_contract(
    script_run_codex: Any, command: str, expected: bool
) -> None:
    """Only the exact standalone prospective command is live telemetry evidence."""
    assert script_run_codex._is_codemap_command(command) is expected


def test_required_compliance_needs_successful_compact_delivery_by_arm(script_run_codex: Any, tmp_path: Path) -> None:
    """A query attempt, wrong delivery mode, or missing compact flag cannot comply."""
    task = {"id": "fixture", "prompt": "unchanged prompt", "type": "demo", "scoreable": True}

    def run(arm: str, command: str) -> Any:
        runner = script_run_codex.CodexRunner(
            "fixture-model",
            tmp_path,
            transport=lambda *_args, **_kwargs: _completed_stream(
                commands=[
                    {
                        "type": "command_execution",
                        "command": command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                    }
                ]
            ),
            evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
        )
        return runner.run(task, arm)

    direct = run("B_direct_required", '"$CODEMAP_BIN" query --compact rdeps pkg.core')
    noncompact = run("B_direct_required", '"$CODEMAP_BIN" query rdeps pkg.core')
    skill = run("C_skill_required", '"$CODEMAP_BIN" query --compact rdeps pkg.core')

    assert direct.compliance is True
    assert direct.codemap_direct_successful_calls == 1
    assert direct.codemap_skill_successful_calls == 0
    assert noncompact.compliance is False
    assert noncompact.codemap_delivery == "none"
    assert skill.compliance is False
    assert skill.codemap_direct_successful_calls == 1
    assert skill.codemap_delivery == "none"


def test_direct_cli_arm_never_installs_a_plugin(script_run_codex: Any, tmp_path: Path) -> None:
    """B must expose the supplied launcher without using Codex plugin setup."""
    launcher = _make_direct_runtime_bundle(tmp_path)
    installer_calls: list[Path] = []

    with script_run_codex.prepare_arm_home(
        "B_direct_required",
        root=tmp_path,
        codemap_bin=launcher,
        plugin_installer=lambda home: installer_calls.append(home) or True,
    ) as home:
        assert home.codemap_available is True
        assert home.codemap_verified is True
        staged_launcher = Path(home.env["CODEMAP_BIN"])
        assert staged_launcher == home.path / "direct-cli" / "bin" / "codemap-py"
        assert staged_launcher.read_bytes() == launcher.read_bytes()
        assert (home.path / "direct-cli" / "bin" / "_exclusions.py").is_file()
        assert (home.path / "direct-cli" / "scripts" / "codemap_py_entry.py").is_file()
        assert (home.path / "direct-cli" / "src" / "codemap_py" / "__init__.py").is_file()
        assert not (home.path / "direct-cli" / ".codex-plugin").exists()
        assert not (home.path / "direct-cli" / "codex-skills").exists()
        assert not (home.path / "direct-cli" / "shared").exists()

    assert installer_calls == []


def test_staged_direct_cli_admission_executes_a_task_shaped_query(script_run_codex: Any, tmp_path: Path) -> None:
    """B preflight must execute its staged CLI before any model can consume a cell."""
    repo_path = tmp_path / "target"
    repo_path.mkdir()
    index_path = repo_path / "locked-index.json"
    index_path.write_text("{}", encoding="utf-8")
    home_path = tmp_path / "home"
    launcher = home_path / "direct-cli" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    config = home_path / "config.toml"
    config.write_text("", encoding="utf-8")
    config.chmod(0o600)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "direct_cli_admission": {
                    "probe_subcommand": "fn-rdeps",
                    "probe_target": "lightning.pytorch.trainer.call::_call_lightning_module_hook",
                }
            }
        ),
        encoding="utf-8",
    )
    home = script_run_codex.ArmHome(
        "B_direct_required",
        home_path,
        {
            "PATH": "/fixture/bin",
            "CODEMAP_BIN": str(launcher),
            "CODEMAP_PYTHON": "/usr/bin/python3",
            "SCAN_NO_AUTOBUILD": "1",
        },
        True,
        True,
        permission_profile="provider-parity-codemap",
        codemap_launcher_path=launcher,
    )
    calls: list[list[str]] = []

    def command_runner(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"index": {"query_complete": True, "compact": True}}),
            stderr="",
        )

    script_run_codex._admit_staged_direct_cli(
        home,
        repo_path,
        index_path,
        manifest_path=manifest_path,
        command_runner=command_runner,
    )

    assert calls == [
        [
            "codex",
            "sandbox",
            "-P",
            "provider-parity-codemap",
            "--include-managed-config",
            "-C",
            str(repo_path),
            "--",
            str(launcher),
            "query",
            "--compact",
            "fn-rdeps",
            "lightning.pytorch.trainer.call::_call_lightning_module_hook",
        ]
    ]


def test_no_model_probe_removes_its_coordination_root(
    script_run_codex: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dry probe must not leave the index reader-coordination skeleton behind."""
    home_path = tmp_path / "home"
    home_path.mkdir()
    config = home_path / "config.toml"
    config.write_text("", encoding="utf-8")
    config.chmod(0o600)
    index_path = tmp_path / ".cache" / "codemap" / "fixture.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    coordination_root = script_run_codex._prepare_coordination_root(index_path)
    home = script_run_codex.ArmHome(
        "B_direct_required",
        home_path,
        {},
        codemap_available=True,
        codemap_verified=True,
        coordination_path=coordination_root,
    )
    runner = script_run_codex.CodexRunner("fixture-model", tmp_path)
    monkeypatch.setattr(runner, "_prepare_verified_home", lambda _arm: home)

    runner.probe_arm("B_direct_required")

    assert not coordination_root.exists()
    assert not home_path.exists()


def test_direct_cli_launcher_must_match_its_manifest_hash(script_run_codex: Any, tmp_path: Path) -> None:
    """B rejects a direct executable unless its bytes are the locked runtime launcher."""
    launcher = _make_direct_runtime_bundle(tmp_path)
    lock_path = tmp_path / "locks.json"

    with script_run_codex.prepare_arm_home("B_direct_required", root=tmp_path, codemap_bin=launcher) as home:
        lock_path.write_text(
            json.dumps(
                {
                    "artifact_sha256": {"codemap_runtime_cli": home.codemap_launcher_sha256},
                    "codemap_candidate": {"version": "0.27.0"},
                    "direct_cli_runtime": {
                        "files": script_run_codex._runtime_file_hashes(home.codemap_launcher_path.parent.parent),
                        "aggregate_sha256": script_run_codex._aggregate_file_hashes(
                            script_run_codex._runtime_file_hashes(home.codemap_launcher_path.parent.parent)
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        script_run_codex._verify_treatment_artifact_locks(home, lock_path)

        lock_path.write_text(
            json.dumps(
                {"artifact_sha256": {"codemap_runtime_cli": "0" * 64}, "codemap_candidate": {"version": "0.27.0"}}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="launcher does not match"):
            script_run_codex._verify_treatment_artifact_locks(home, lock_path)


def test_historical_exact_launcher_and_compound_forms_reject_native_item_contract(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """The prospective contract does not infer delivery from paths or shell composition."""
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)

    assert not script_run_codex._is_codemap_command("$CODEMAP_BIN query --compact rdeps pkg.core")
    assert not script_run_codex._is_codemap_command(
        f'"{launcher}" query --compact rdeps pkg.core', launcher_path=launcher
    )
    assert not script_run_codex._is_codemap_command("/plugin/bin/codemap-py query --compact rdeps pkg.core")
    assert not script_run_codex._is_codemap_command("$CODEMAP_BIN query --compact rdeps pkg.core; echo done")


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param(
            "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact rdeps pkg.core'", True, id="one-outer-transport-wrapper"
        ),
        pytest.param(
            '/bin/zsh -lc \'/bin/zsh -lc "\\"$CODEMAP_BIN\\" query --compact rdeps pkg.core"\'',
            False,
            id="nested-wrapper",
        ),
        pytest.param(
            "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact rdeps pkg.core; echo done'",
            False,
            id="historical-compound-wrapper",
        ),
        pytest.param(
            "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact rdeps pkg.core > out.json'",
            False,
            id="historical-redirect-wrapper",
        ),
        pytest.param("/bin/zsh -lc", False, id="missing-wrapper-command"),
    ],
)
def test_one_outer_transport_wrapper_preserves_the_native_item_contract(
    script_run_codex: Any, command: str, expected: bool
) -> None:
    """Only one exact Codex transport wrapper may contain the native payload."""
    assert script_run_codex._is_codemap_command(command) is expected


def test_historical_wrapped_C_delivery_rejects_native_item_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """Historical wrapped C evidence stays available but cannot score a new cell."""
    skill_path = tmp_path / "codex-skills" / "query-code" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_bytes = b"# query-code\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "plugins" / "codemap-py" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    complete_result = json.dumps({"index": {"query_complete": True}})
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'cat \"$CODEMAP_SKILL_FILE\"'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": f"/bin/zsh -lc '\"{launcher}\" query --compact rdeps pkg.core'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": complete_result,
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False

    direct_after_skill = [
        events[0],
        {
            "type": "item.completed",
            "item": {
                "id": "direct-query",
                "type": "command_execution",
                "command": "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact rdeps pkg.core'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": complete_result,
            },
        },
        {"type": "turn.completed"},
    ]
    direct_parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in direct_after_skill),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert direct_parsed.skill_delivery_observed is True
    assert direct_parsed.codemap_calls == 1
    assert script_run_codex._arm_compliance("C_skill_required", direct_parsed) is False

    incomplete = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": "$CODEMAP_BIN query --compact rdeps pkg.core",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "{}",
                }
            ]
        )
    )
    assert incomplete.codemap_calls == 0
    assert script_run_codex._arm_compliance("B_direct_required", incomplete) is False


def test_historical_bound_launcher_query_rejects_native_item_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """The paid local-alias shape remains historical-only evidence."""
    skill_path = tmp_path / "codex-skills" / "query-code" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "plugins" / "codemap-py" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'cat \"$CODEMAP_SKILL_FILE\"'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": (
                    "/bin/zsh -lc '"
                    f'codemap_bin="${{CODEMAP_BIN:-{launcher}}}"; '
                    '"$codemap_bin" query --compact fn-rdeps "pkg.core::target"\''
                ),
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_calls == 0
    assert parsed.codemap_direct_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False

    reversed_parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in [events[1], events[0], events[2]]),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )
    # The exact Skill read is still observable, but it cannot make the preceding
    # non-canonical query compliant.
    assert reversed_parsed.skill_delivery_observed is True
    assert reversed_parsed.codemap_skill_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", reversed_parsed) is False


def test_historical_uppercase_launcher_assignment_rejects_native_item_contract(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """A historical assigned launcher is not a future standalone native item."""
    skill_path = tmp_path / "codex-skills" / "query-code" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "plugins" / "codemap-py" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": 'cat "$CODEMAP_SKILL_FILE"',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": (
                    "/bin/zsh -lc '"
                    f'CODEMAP_BIN="${{CODEMAP_BIN:-{launcher}}}"; '
                    '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"\''
                ),
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_calls == 0
    assert parsed.codemap_direct_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'CODEMAP_BIN="${CODEMAP_BIN:-/wrong/codemap-py}"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="wrong-fallback",
        ),
        pytest.param(
            'CODEMAP_BIN="{launcher}"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="literal-assignment",
        ),
        pytest.param(
            'CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; CODEMAP_BIN=/wrong/codemap-py; '
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="reassigned",
        ),
        pytest.param(
            'export CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="exported",
        ),
        pytest.param(
            'readonly CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="readonly",
        ),
        pytest.param(
            'typeset CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="typeset",
        ),
        pytest.param(
            'CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; unset CODEMAP_BIN; '
            '"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="unset",
        ),
        pytest.param(
            'CODEMAP_BIN="$(printf \'%s\' {launcher})"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="command-substitution",
        ),
        pytest.param(
            'payload="CODEMAP_BIN=/wrong/codemap-py"; eval "$payload"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="dynamic-eval",
        ),
        pytest.param(
            'if true; then CODEMAP_BIN="${CODEMAP_BIN:-{launcher}}"; fi; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="control-flow-binding",
        ),
    ],
)
def test_uppercase_launcher_fallback_rejects_untrusted_shell_forms(
    script_run_codex: Any, tmp_path: Path, command: str
) -> None:
    """Assignments never substitute for the future standalone native item."""
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)

    assert not script_run_codex._is_codemap_command(
        command.replace("{launcher}", str(launcher)), launcher_path=launcher
    )


def test_historical_compound_direct_query_rejects_native_item_contract(script_run_codex: Any) -> None:
    """A diagnostic/query compound is historical evidence, not a future query item."""
    output = "ready\n" + json.dumps({"index": {"query_complete": True, "compact": True}}) + "\ndone\n"
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": ('printf "ready\\n"; "$CODEMAP_BIN" query --compact rdeps pkg.core; printf "done\\n"'),
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": output,
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is False


def test_historical_multiline_direct_query_rejects_native_item_contract(script_run_codex: Any) -> None:
    """The exact paid B wrapper cannot satisfy prospective native telemetry."""
    command = (
        '/bin/zsh -lc "printf \'CODEMAP_BIN=%s\\\\n\' \\""\'$CODEMAP_BIN"\n'
        '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"\''
    )
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": (
                        "CODEMAP_BIN=/fixture/codemap-py\n"
                        + json.dumps({"index": {"query_complete": True, "compact": True}})
                    ),
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is False


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'printf \'CODEMAP_BIN=%s\\n\' "$CODEMAP_BIN"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="historical-semicolon",
        ),
        pytest.param(
            'printf ready &&\n"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="historical-and-newline",
        ),
        pytest.param(
            'false ||\n"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="historical-or-newline",
        ),
        pytest.param(
            'printf ready |\n"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="historical-pipe-newline",
        ),
        pytest.param(
            'CODEMAP_BIN=/wrong/codemap-py\n"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="newline-before-mutated-launcher",
        ),
        pytest.param(
            'printf \'CODEMAP_BIN=/wrong\\n\' "$CODEMAP_BIN" "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="diagnostic-data-without-separator",
        ),
        pytest.param(
            'printf \'CODEMAP_BIN=%s\\n\n"$CODEMAP_BIN" query --compact rdeps pkg.core\' "$CODEMAP_BIN"',
            id="quoted-literal-newline",
        ),
        pytest.param(
            'printf \'CODEMAP_BIN=%s\\n\' "$CODEMAP_BIN" \\\n"$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="escaped-line-continuation",
        ),
    ],
)
def test_historical_newline_shell_forms_reject_native_item_contract(script_run_codex: Any, command: str) -> None:
    """No multiline shell form is the dedicated future native query item."""
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is False


def test_historical_diagnostic_conditional_query_rejects_native_item_contract(script_run_codex: Any) -> None:
    """A historical diagnostic/control command cannot score a future direct query."""
    command = (
        "printf 'CODEMAP_BIN=%s\\n' \"${CODEMAP_BIN-}\"; "
        "rg -n target .; "
        'if [ -n "${CODEMAP_BIN-}" ]; then '
        '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"; '
        "else printf 'CODEMAP_BIN is unset\\n'; fi"
    )
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
                }
            ]
        )
    )

    assert parsed.codemap_direct_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("B_direct_required", parsed) is False


def test_historical_bound_launcher_diagnostic_rejects_native_item_contract(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """A local launcher binding is not a standalone native query command."""
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    command = (
        "printf 'codemap_bin=%s\\n' \"${CODEMAP_BIN-}\"; "
        f'codemap_bin="${{CODEMAP_BIN:-{launcher}}}"; '
        '"$codemap_bin" query --compact rdeps pkg.core'
    )

    assert not script_run_codex._is_codemap_command(command, launcher_path=launcher)


def test_historical_compound_skill_and_control_query_reject_native_item_contract(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """C now requires two dedicated native items rather than compound shell evidence."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    query_output = "diagnostic\n" + json.dumps({"index": {"query_complete": True, "compact": True}})
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": f"sed -n '1,240p' {skill_path}; printf 'activated\\n'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode() + "activated\n",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": (
                    'if [ -n "$CODEMAP_BIN" ]; then "$CODEMAP_BIN" query --compact '
                    'fn-rdeps "pkg.core::target"; else "'
                    f'{launcher}" query --compact fn-rdeps "pkg.core::target"; fi'
                ),
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": query_output,
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is False
    assert parsed.codemap_calls == 0
    assert parsed.codemap_direct_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


def test_historical_conditional_launcher_alias_replay_is_not_canonical_C_compliance(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """Record the observed C command as historical replay incompatibility.

    The prospective C contract is the standalone ``$CODEMAP_BIN query`` form.
    This conditional alias remains corpus evidence for interpreting historical
    rows, not a second command grammar eligible for future compliance credit.
    """
    skill_path = tmp_path / "codex-skills" / "query-code" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "plugins" / "codemap-py" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    query_command = (
        '/bin/zsh -lc \'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
        f'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
        '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"\''
    )
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'cat \"$CODEMAP_SKILL_FILE\"'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": query_command,
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_calls == 0
    assert parsed.codemap_skill_compact_successful_calls == 0
    assert parsed.codemap_direct_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


@pytest.mark.parametrize(
    "template",
    [
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_OTHER="$CODEMAP_BIN"; '
            'else CODEMAP_OTHER="{launcher}"; fi\n'
            '"$CODEMAP_OTHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-alias-name",
        ),
        pytest.param(
            'if [ -n "$OTHER" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-condition-variable",
        ),
        pytest.param(
            'if [ -z "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-condition-operator",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="/wrong/codemap-py"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-then-source",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="/wrong/codemap-py"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-else-path",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="{launcher}"; '
            'else CODEMAP_LAUNCHER="$CODEMAP_BIN"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="swapped-branches",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then :; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="missing-then-branch",
        ),
        pytest.param(
            'CODEMAP_BIN=/wrong/codemap-py; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="precondition-codemap-bin-mutation",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi; CODEMAP_LAUNCHER=/wrong/codemap-py\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="post-fi-alias-reassignment",
        ),
        pytest.param(
            'export CODEMAP_LAUNCHER=/wrong/codemap-py; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="export-alias",
        ),
        pytest.param(
            'readonly CODEMAP_LAUNCHER=/wrong/codemap-py; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="readonly-alias",
        ),
        pytest.param(
            'typeset CODEMAP_LAUNCHER=/wrong/codemap-py; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="typeset-alias",
        ),
        pytest.param(
            'unset CODEMAP_LAUNCHER; if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="unset-alias",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$(printf %s "$CODEMAP_BIN")"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="command-substitution",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi; payload="CODEMAP_LAUNCHER=/wrong/codemap-py"; '
            'eval "$payload"\n"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="eval",
        ),
        pytest.param(
            'source /dev/null; if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="source",
        ),
        pytest.param(
            'read -r CODEMAP_LAUNCHER <<< /wrong/codemap-py; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="read",
        ),
        pytest.param(
            'while false; do CODEMAP_LAUNCHER="$CODEMAP_BIN"; done; if [ -n "$CODEMAP_BIN" ]; '
            'then CODEMAP_LAUNCHER="$CODEMAP_BIN"; else CODEMAP_LAUNCHER="{launcher}"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="loop",
        ),
        pytest.param(
            '( if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi )\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="subshell",
        ),
        pytest.param(
            'if true; then if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="nested-conditional",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi',
            id="query-inside-branch",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="{launcher}"; fi; printf ready\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="intervening-command",
        ),
        pytest.param(
            'if [ -n "$CODEMAP_BIN" ]; then CODEMAP_LAUNCHER="$CODEMAP_BIN"; '
            'else CODEMAP_LAUNCHER="/wrong/codemap-py"; fi\n'
            '"$CODEMAP_LAUNCHER" query --compact fn-rdeps "pkg.core::target"',
            id="wrong-locked-path",
        ),
    ],
)
def test_conditional_launcher_alias_rejects_unproven_forms(
    script_run_codex: Any, tmp_path: Path, template: str
) -> None:
    """Keep conditional alias credit limited to one immutable two-branch form.

    Each case could execute a launcher-like command, so a recognizer that only
    matches ``CODEMAP_LAUNCHER query`` would incorrectly satisfy C compliance.
    """
    skill_path = tmp_path / "codex-skills" / "query-code" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    launcher = tmp_path / "plugins" / "codemap-py" / "bin" / "codemap-py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": 'cat "$CODEMAP_SKILL_FILE"',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode(),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": template.format(launcher=launcher),
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        launcher_path=launcher,
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is True
    assert parsed.codemap_calls == 0
    assert parsed.codemap_skill_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


def test_historical_compound_skill_reader_rejects_native_item_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """A complete Skill body in a compound reader item is insufficient for C."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"# query-code\nline 2\nline 3\n"
    skill_path.write_bytes(skill_bytes)
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "skill-read",
                "type": "command_execution",
                "command": f"sed -n '1,260p' {skill_path}; printf 'activated\\n'",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": skill_bytes.decode() + "activated\n",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "query",
                "type": "command_execution",
                "command": '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"',
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
            },
        },
        {"type": "turn.completed"},
    ]

    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is False
    assert parsed.codemap_skill_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


def test_historical_bound_skill_path_read_rejects_native_item_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """A bound Skill path is historical evidence, not future static-path proof."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    read_command = f"skill_path='{skill_path}'; wc -l \"$skill_path\"; sed -n '1,260p' \"$skill_path\""
    read_output = f"{len(skill_bytes.splitlines())} {skill_path}\n" + skill_bytes.decode()
    query_command = '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"'
    parsed = script_run_codex.parse_codex_jsonl(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "skill-read",
                        "type": "command_execution",
                        "command": read_command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": read_output,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "query",
                        "type": "command_execution",
                        "command": query_command,
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
                    },
                },
                {"type": "turn.completed"},
            ]
        ),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is False
    assert parsed.codemap_skill_compact_successful_calls == 0
    assert parsed.codemap_direct_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


@pytest.mark.parametrize(
    ("template", "output_kind", "_expected_direct_calls"),
    [
        pytest.param(
            "skill_path='{other}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="wrong-path",
        ),
        pytest.param(
            "skill_path='{skill}'; skill_path='{other}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="reassigned",
        ),
        pytest.param(
            "export skill_path='{skill}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="export-declaration",
        ),
        pytest.param(
            "typeset skill_path='{skill}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="shell-declaration",
        ),
        pytest.param(
            "skill_path='{skill}'; read -r skill_path <<< '{other}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            0,
            id="read-mutation",
        ),
        pytest.param(
            "while :; do skill_path='{skill}'; break; done; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="while-binding",
        ),
        pytest.param(
            "if true; then skill_path='{skill}'; fi; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="if-binding",
        ),
        pytest.param(
            "until false; do skill_path='{skill}'; break; done; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="until-binding",
        ),
        pytest.param(
            "( skill_path='{skill}'; sed -n '1,260p' \"$skill_path\" ); {query}",
            "complete",
            0,
            id="subshell-binding",
        ),
        pytest.param(
            "skill_path='{skill}' && sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="conditional-and-binding",
        ),
        pytest.param(
            "skill_path=\"$(printf '%s' '{skill}')\"; sed -n '1,260p' \"$skill_path\"; {query}",
            "complete",
            1,
            id="command-substitution",
        ),
        pytest.param(
            "skill_path='{skill}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "incomplete",
            1,
            id="incomplete-bytes",
        ),
        pytest.param(
            "skill_path='{skill}'; sed -n '1,260p' \"$skill_path\"; {query}",
            "wrong",
            1,
            id="wrong-bytes",
        ),
    ],
)
def test_historical_bound_skill_reader_forms_reject_native_item_contract(
    script_run_codex: Any, tmp_path: Path, template: str, output_kind: str, _expected_direct_calls: int
) -> None:
    """No compound historical reader/query command can earn direct or C credit."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    other_path = tmp_path / "other" / "SKILL.md"
    skill_path.parent.mkdir()
    other_path.parent.mkdir()
    skill_bytes = b"# query-code\nUse the compact query.\n"
    skill_path.write_bytes(skill_bytes)
    other_path.write_bytes(skill_bytes)
    query = '"$CODEMAP_BIN" query --compact fn-rdeps "pkg.core::target"'
    command = template.format(skill=skill_path, other=other_path, query=query)
    output_by_kind = {
        "complete": skill_bytes.decode(),
        "incomplete": "# query-code\n",
        "wrong": skill_bytes.decode().replace("compact", "expanded"),
    }
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": output_by_kind[output_kind]
                    + json.dumps({"index": {"query_complete": True, "compact": True}}),
                }
            ]
        ),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is False
    assert parsed.codemap_skill_successful_calls == 0
    assert parsed.codemap_direct_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


def test_historical_query_then_skill_read_rejects_native_item_contract(script_run_codex: Any, tmp_path: Path) -> None:
    """Reading a Skill in the query item cannot satisfy the separate-item C rule."""
    skill_path = tmp_path / "query-code" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_bytes = b"# query-code\n"
    skill_path.write_bytes(skill_bytes)
    output = json.dumps({"index": {"query_complete": True}}) + "\n" + skill_bytes.decode()
    command = f'"$CODEMAP_BIN" query --compact rdeps pkg.core; cat {skill_path}'
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": output,
                }
            ]
        ),
        skill_path=skill_path,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is False
    assert parsed.codemap_direct_compact_successful_calls == 0
    assert parsed.codemap_skill_compact_successful_calls == 0
    assert script_run_codex._arm_compliance("C_skill_required", parsed) is False


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'CODEMAP_BIN=/wrong/codemap-py; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="direct-variable-reassigned",
        ),
        pytest.param(
            'export CODEMAP_BIN=/wrong/codemap-py; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="direct-variable-exported",
        ),
        pytest.param(
            'codemap_bin="${CODEMAP_BIN:-{launcher}}"; codemap_bin=/wrong; '
            '"$codemap_bin" query --compact rdeps pkg.core',
            id="bound-variable-reassigned",
        ),
        pytest.param(
            'payload="CODEMAP_BIN=/wrong/codemap-py"; eval "$payload"; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="direct-variable-eval-indirection",
        ),
        pytest.param(
            'name=CODEMAP_BIN; typeset "$name"=/wrong/codemap-py; "$CODEMAP_BIN" query --compact rdeps pkg.core',
            id="direct-variable-typeset-indirection",
        ),
        pytest.param(
            'for CODEMAP_BIN in /wrong/codemap-py; do "$CODEMAP_BIN" query --compact rdeps pkg.core; done',
            id="direct-variable-loop-reassignment",
        ),
        pytest.param(
            "printf 'CODEMAP_BIN=%s\\n' \"${CODEMAP_BIN-}\"; "
            "CODEMAP_BIN=/wrong/codemap-py; "
            'if [ -n "${CODEMAP_BIN-}" ]; then '
            '"$CODEMAP_BIN" query --compact rdeps pkg.core; fi',
            id="diagnostic-then-direct-reassignment",
        ),
        pytest.param(
            'while IFS= read -r CODEMAP_BIN; do "$CODEMAP_BIN" query --compact '
            "rdeps pkg.core; break; done <<< /wrong/codemap-py",
            id="while-read-direct-reassignment",
        ),
    ],
)
def test_query_credit_rejects_launcher_variable_mutation(script_run_codex: Any, tmp_path: Path, command: str) -> None:
    """Shell reassignment cannot substitute an unlocked executable for the staged launcher."""
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)

    assert not script_run_codex._is_codemap_command(
        command.replace("{launcher}", str(launcher)),
        launcher_path=launcher,
    )


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'codemap_bin="${CODEMAP_BIN:-/wrong/codemap-py}"; "$codemap_bin" query --compact rdeps pkg.core',
            id="wrong-fallback",
        ),
        pytest.param(
            'codemap_bin="${CODEMAP_BIN:-{launcher}}"; "$codemap_bin" --version',
            id="not-query",
        ),
        pytest.param(
            'codemap_bin="{launcher}"; "$codemap_bin" query --compact rdeps pkg.core',
            id="unbound-direct-assignment",
        ),
        pytest.param(
            'runner="${CODEMAP_BIN:-{launcher}}"; "$runner" query --compact rdeps pkg.core',
            id="other-variable",
        ),
        pytest.param(
            'echo "$CODEMAP_BIN query --compact rdeps pkg.core"',
            id="echo-only",
        ),
    ],
)
def test_bound_launcher_query_rejects_ambiguous_or_unlocked_shell_forms(
    script_run_codex: Any, tmp_path: Path, command: str
) -> None:
    """Do not widen query evidence to unrelated variables, paths, or non-query commands."""
    launcher = tmp_path / "codemap-py"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)

    assert not script_run_codex._is_codemap_command(
        command.replace("{launcher}", str(launcher)), launcher_path=launcher
    )


@pytest.mark.parametrize(
    ("template", "output_kind", "exit_code", "expected"),
    [
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "complete", 0, True, id="canonical-complete"),
        pytest.param("cat {skill}", "complete", 0, False, id="literal-path"),
        pytest.param("sed -n '1,1p' {skill}", "partial", 0, False, id="partial-output"),
        pytest.param("cat {other}", "complete", 0, False, id="wrong-path"),
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "wrong", 0, False, id="wrong-bytes"),
        pytest.param('cat "$CODEMAP_SKILL_FILE"', "complete", 1, False, id="failed-command"),
        pytest.param("cat $CODEMAP_SKILL_FILE", "complete", 0, False, id="unquoted-variable"),
    ],
)
def test_skill_read_requires_exact_environment_command_bytes_and_success(
    script_run_codex: Any,
    tmp_path: Path,
    template: str,
    output_kind: str,
    exit_code: int,
    expected: bool,
) -> None:
    """Only the exact bound reader with exact bytes and zero exit proves activation."""
    skill = tmp_path / "query-code" / "SKILL.md"
    skill.parent.mkdir()
    skill_bytes = b"# query-code\nline 2\nline 3\n"
    skill.write_bytes(skill_bytes)
    command = template.format(skill=skill, other=tmp_path / "other" / "SKILL.md")
    outputs = {
        "complete": skill_bytes.decode(),
        "partial": "# query-code\n",
        "wrong": skill_bytes.decode().replace("line 2", "changed"),
    }
    parsed = script_run_codex.parse_codex_jsonl(
        _completed_stream(
            commands=[
                {
                    "type": "command_execution",
                    "command": command,
                    "status": "completed" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "aggregated_output": outputs[output_kind],
                }
            ]
        ),
        skill_path=skill,
        skill_sha256=hashlib.sha256(skill_bytes).hexdigest(),
    )

    assert parsed.skill_delivery_observed is expected


def test_main_threads_an_explicit_manifest_path_into_task_loading_and_ordering(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future relock must not be silently replaced by the module-global manifest."""
    manifest_path = tmp_path / "future-manifest.json"
    seen: dict[str, Path] = {}
    tasks = [{"id": "fixture", "prompt": "prompt", "type": "demo"}]

    def load_tasks(_tasks_path: Path, selected_manifest: Path) -> list[dict[str, str]]:
        seen["tasks"] = selected_manifest
        return tasks

    def order(revision: str, *_args: Any, **_kwargs: Any) -> tuple[str, ...]:
        seen["revision"] = Path(revision)
        return ("A_plain", "B_direct_required", "C_skill_required")

    class FixtureRunner:
        """Provide deterministic preflight evidence without invoking Codex."""

        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            seen["runner"] = kwargs["manifest_path"]

        def probe_arm(self, _arm: str) -> dict[str, bool]:
            return {"codemap_available": False}

    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", load_tasks)
    monkeypatch.setattr(script_run_codex, "_read_manifest_revision", lambda path: str(path))
    monkeypatch.setattr(script_run_codex, "deterministic_arm_order", order)
    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        manifest_path=manifest_path,
        dry_run=True,
    )

    assert seen["tasks"] == manifest_path
    assert seen["runner"] == manifest_path
    assert seen["revision"] == manifest_path
