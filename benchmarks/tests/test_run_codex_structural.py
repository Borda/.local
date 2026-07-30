"""No-model acceptance tests for the Codex provider-parity adapter."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks import provider_parity_contracts as core


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BENCHMARKS_DIR / "run-codex-structural.py"
SUITE_PATH = BENCHMARKS_DIR / "suites" / "tasks-bench.json"
MANIFEST_PATH = BENCHMARKS_DIR / "results" / "manifests" / "provider-parity-v1.json"


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

    for arm in ("B_auto", "C_required"):
        treatment_config = script_run_codex._write_permission_config(home, arm, index_path)
        treatment_text = treatment_config.read_text(encoding="utf-8")
        coordination_root = index_path.parent / ".index-rw"

        assert treatment_config == plain_config
        assert 'default_permissions = "provider-parity-codemap"' in treatment_text
        assert "[permissions.provider-parity-codemap]" in treatment_text
        assert 'extends = ":read-only"' in treatment_text
        assert f'"{auth_path.resolve()}" = "deny"' in treatment_text
        assert f'"{coordination_root.resolve()}" = "write"' in treatment_text
        assert "[permissions.provider-parity-codemap.network]" in treatment_text
        assert "enabled = false" in treatment_text
        assert "sandbox_mode" not in treatment_text
        assert "sandbox_workspace_write" not in treatment_text


def test_r6_manifest_locks_exact_treatment_python_runtime() -> None:
    """Prevent another paid treatment from discovering or choosing its own Python."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    runtime = manifest["codex_permission_profiles"]["treatment_runtime"]

    assert manifest["experiment_revision"] == "codemap-provider-parity-v1-b0-r6"
    assert runtime == {
        "environment": {"CODEMAP_PYTHON": "/opt/homebrew/bin/python3.11"},
        "required_major_minor": [3, 11],
        "scope": ["B_auto", "C_required"],
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
                        "scope": ["B_auto", "C_required"],
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
    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args: None)
    monkeypatch.setattr(script_run_codex, "_verify_permission_profile", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script_run_codex, "_verify_plain_plugin_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        script_run_codex,
        "_verify_locked_codemap_python",
        lambda **_kwargs: "/opt/homebrew/bin/python3.11",
    )
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        repo_path,
        index_path=index_path,
        plugin_installer=lambda _home: True,
    )

    with runner._prepare_verified_home("A_plain") as plain:
        plain_evidence = script_run_codex.probe_arm_home(plain)
        plain_has_runtime = "CODEMAP_PYTHON" in plain.env
    with runner._prepare_verified_home("B_auto") as treatment:
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
    home = script_run_codex.ArmHome("B_auto", home_path, {}, True, True)

    def reject_profile(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        if "--version" in command:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.138.0", stderr="")
        return SimpleNamespace(returncode=2, stdout="", stderr="unknown permission profile provider-parity-codemap")

    with pytest.raises(ValueError, match="profile|permission|unsupported"):
        script_run_codex._verify_permission_profile(home, repo_path, command_runner=reject_profile)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is unavailable")
@pytest.mark.skipif(
    os.environ.get("RUN_CODEX_SANDBOX_INTEGRATION") != "1",
    reason="set RUN_CODEX_SANDBOX_INTEGRATION=1 to exercise the installed Codex sandbox",
)
def test_real_codex_profile_denies_source_and_auth_but_allows_coordination(
    script_run_codex: Any, tmp_path: Path
) -> None:
    """The installed Codex sandbox must enforce the exact r6 treatment boundary."""
    repo_path = tmp_path / "target"
    index_path = repo_path / ".cache" / "codemap" / "target.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{}", encoding="utf-8")
    home = script_run_codex.prepare_arm_home("B_auto", root=tmp_path)
    auth_path = home.path / "auth.json"
    auth_path.write_text('{"fixture":"credential-sentinel"}', encoding="utf-8")
    auth_path.chmod(0o600)
    home.coordination_path = script_run_codex._prepare_coordination_root(index_path)
    script_run_codex._write_permission_config(home, "B_auto", index_path)

    try:
        script_run_codex._verify_permission_profile(home, repo_path, index_path)
    finally:
        script_run_codex._cleanup_coordination_root(home.coordination_path)
        home.cleanup()

    assert not any(repo_path.glob(".codex-r6-deny-*"))
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
                "command": "/installed/codemap-py/bin/codemap-py query rdeps lightning.fabric",
                "status": "completed",
                "exit_code": 0,
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
                    "cached_input_tokens": 0,
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

    result = runner.run(loaded_task, "B_auto")

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
                    "command": "/plugin/bin/codemap-py query rdeps pkg.core",
                    "status": "completed",
                    "exit_code": 0,
                }
            ],
            None,
            True,
            False,
            id="plain-contaminated",
        ),
        pytest.param("B_auto", [], None, False, True, id="auto-no-call-valid"),
        pytest.param("C_required", [], False, False, True, id="required-no-call-separate"),
        pytest.param(
            "C_required",
            [
                {
                    "type": "command_execution",
                    "command": "/plugin/bin/codemap-py query rdeps pkg.core",
                    "status": "completed",
                    "exit_code": 0,
                }
            ],
            True,
            False,
            True,
            id="required-call-compliant",
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
                "command": "/plugin/bin/codemap-py query rdeps pkg.core",
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


def test_command_lifecycle_uses_completed_status_once(script_run_codex: Any) -> None:
    """A started command cannot hide its later failed completion status."""
    item = {
        "id": "command-1",
        "type": "command_execution",
        "command": "/plugin/bin/codemap-py query rdeps pkg.core",
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


def test_shell_probe_cannot_mask_codemap_exit_code(script_run_codex: Any) -> None:
    """A trailing shell echo must not turn Codemap exit 127 into a success."""
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

    assert parsed.codemap_calls == 1
    assert parsed.codemap_successful_calls == 0
    assert parsed.codemap_errors == 1


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
        runner.run(tampered, "B_auto")


def test_no_model_plugin_install_uses_marketplace_and_installed_list(script_run_codex: Any, tmp_path: Path) -> None:
    """B/C availability requires a verified exact launcher, not cache guessing."""
    marketplace_root = tmp_path / "marketplace"
    manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"borda-ai-rig","plugins":[]}', encoding="utf-8")
    calls: list[list[str]] = []

    with script_run_codex.prepare_arm_home("B_auto", root=tmp_path) as home:
        installed_path = home.path / "plugins" / "cache" / "borda-ai-rig" / "codemap-py" / "0.27.0"
        launcher = installed_path / "bin" / "codemap-py"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        plugin_manifest = installed_path / ".codex-plugin" / "plugin.json"
        plugin_manifest.parent.mkdir()
        plugin_manifest.write_text('{"name":"codemap-py","version":"0.27.0"}', encoding="utf-8")

        def command_runner(command: list[str], **_kwargs: Any) -> SimpleNamespace:
            calls.append(command)
            if command[1:3] == ["plugin", "add"]:
                stdout = json.dumps({"installedPath": str(installed_path)})
            elif command[1:3] == ["plugin", "list"]:
                stdout = '{"installed":[{"name":"codemap-py","enabled":true}],"available":[]}'
            else:
                stdout = ""
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        installed = script_run_codex._install_codemap_plugin(
            home,
            marketplace_root,
            command_runner=command_runner,
        )

        assert installed is True
        assert home.env["CODEMAP_BIN"] == str(launcher.resolve())
        assert home.codemap_launcher_path == launcher.resolve()
        assert home.codemap_launcher_sha256 == hashlib.sha256(launcher.read_bytes()).hexdigest()
        home.codemap_available = True
        home.codemap_verified = True
        config = home.path / "config.toml"
        config.write_text("", encoding="utf-8")
        config.chmod(0o600)
        evidence = script_run_codex.probe_arm_home(home)
        assert evidence["codemap_launcher_path"] == str(launcher.resolve())
        assert evidence["codemap_launcher_sha256"] == home.codemap_launcher_sha256
        assert calls == [
            ["codex", "plugin", "marketplace", "add", str(marketplace_root)],
            ["codex", "plugin", "add", "codemap-py@borda-ai-rig", "--json"],
            ["codex", "plugin", "list", "--json"],
        ]


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

    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args: None)
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

    monkeypatch.setattr(script_run_codex, "_validate_locked_runtime", lambda *_args: None)
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
    with script_run_codex.prepare_arm_home("B_auto", root=tmp_path) as home:
        with pytest.raises(ValueError, match="verified"):
            script_run_codex.probe_arm_home(home)
        home.codemap_available = True
        home.codemap_verified = True
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

    script_run_codex._validate_locked_runtime(repo_path, index_path, "A_plain")
    script_run_codex._validate_locked_runtime(repo_path, index_path, "B_auto")

    with pytest.raises(ValueError, match="requires the locked index"):
        script_run_codex._validate_locked_runtime(repo_path, None, "A_plain")


def test_result_exposes_native_telemetry_and_turn_limit_capability(script_run_codex: Any, tmp_path: Path) -> None:
    """Every result keeps measurable Codex-native fields and the turn-limit gap."""
    runner = script_run_codex.CodexRunner(
        "fixture-model",
        tmp_path,
        transport=lambda *_args, **_kwargs: _completed_stream(),
        evaluator=lambda *_args: core.EvaluationResult(scored=True, correct=True, quality_score=1.0),
    )

    result = runner.run({"id": "fixture", "prompt": "prompt", "type": "demo"}, "B_auto")

    assert result.elapsed_s >= 0.0
    assert result.native_item_counts == {"agent_message": 1}
    assert result.native_attempt_events == [result.raw_events]
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
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: [task])

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


def test_main_rejects_missing_or_existing_output_before_model_execution(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid execution must have a fresh durable destination before constructing a runner."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: [task])
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


def test_main_rejects_unreviewed_implementation_revision_before_reserving_output(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid execution cannot mix the new runner with the frozen prior manifest."""
    task = {"id": "fixture", "prompt": "prompt", "type": "demo"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"experiment_revision": "codemap-provider-parity-v1-b0-r6"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: [task])
    monkeypatch.setattr(script_run_codex, "PARITY_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(
        script_run_codex,
        "CodexRunner",
        lambda *_args, **_kwargs: pytest.fail("unreviewed manifest reached runner construction"),
    )
    output_path = tmp_path / "unreviewed.jsonl"

    with pytest.raises(ValueError, match="paid execution requires a reviewed"):
        script_run_codex.main(
            repo_path=tmp_path,
            model=script_run_codex.PARITY_CODEX_MODEL,
            tasks_path=tmp_path / "tasks.json",
            output_path=output_path,
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
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: tasks)

    class FixtureRunner:
        """Return one minimal serializable result per planned cell."""

        def __init__(self, model: str, *_args: Any, **_kwargs: Any) -> None:
            self.model = model

        def run(self, task: dict[str, Any], arm: str, *, repetition: int = 1) -> Any:
            return script_run_codex.CodexRun(
                arm=arm,
                task_id=task["id"],
                task_type=task["type"],
                model=self.model,
                parity_arm=arm,
                repetition=repetition,
                success=True,
            )

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "_validate_execution_manifest", lambda: None)
    output_path = tmp_path / "smoke.jsonl"

    script_run_codex.main(
        repo_path=tmp_path,
        model=script_run_codex.PARITY_CODEX_MODEL,
        tasks_path=tmp_path / "tasks.json",
        output_path=output_path,
        repetitions=3,
    )

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [(row["provider"], row["task_id"], row["repetition"], row["arm"]) for row in rows] == [
        ("codex", task["id"], repetition, arm)
        for task in tasks
        for repetition in range(1, 4)
        for arm in core.deterministic_arm_order(
            script_run_codex.PARITY_EXPERIMENT_REVISION,
            "codex",
            script_run_codex.PARITY_CODEX_MODEL,
            task["id"],
            repetition,
            reasoning_effort=script_run_codex.PARITY_CODEX_REASONING_EFFORT,
        )
    ]


def test_main_filters_locked_tasks_in_suite_order_and_rejects_invalid_ids(
    script_run_codex: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke selection keeps canonical suite order without accepting unknown or duplicate IDs."""
    tasks = [
        {"id": "first", "prompt": "one", "type": "demo"},
        {"id": "second", "prompt": "two", "type": "demo"},
    ]
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: tasks)
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

    assert any(row == "PLAN\tsecond\t1\tA_plain" for row in planned)
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
    monkeypatch.setattr(script_run_codex, "load_tasks_with_provenance", lambda _path: tasks)
    planned: list[str] = []

    class FixtureRunner:
        """Provide no-model probe evidence while the plan is constructed."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, arm: str) -> dict[str, bool]:
            return {"codemap_available": arm != "A_plain"}

    monkeypatch.setattr(script_run_codex, "CodexRunner", FixtureRunner)
    monkeypatch.setattr(script_run_codex, "print", planned.append, raising=False)

    script_run_codex.main(
        repo_path=tmp_path,
        model="gpt-5.6-luna",
        tasks_path=tmp_path / "tasks.json",
        task_ids=pilot_ids,
        repetitions=repetitions,
        dry_run=True,
    )

    plan_rows = [line.split("\t")[1:] for line in planned if line.startswith("PLAN\t")]
    expected = [
        [task_id, str(repetition), arm]
        for task_id in pilot_ids
        for repetition in range(1, repetitions + 1)
        for arm in core.deterministic_arm_order(
            script_run_codex.PARITY_EXPERIMENT_REVISION,
            "codex",
            "gpt-5.6-luna",
            task_id,
            repetition,
            reasoning_effort=script_run_codex.PARITY_CODEX_REASONING_EFFORT,
        )
    ]
    assert plan_rows == expected
    assert len(plan_rows) == len({tuple(row) for row in plan_rows}) == 54
