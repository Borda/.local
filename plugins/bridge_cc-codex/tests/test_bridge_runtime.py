"""Deterministic public-behavior tests for the portable bridge runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import pytest


BIN_ROOT = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_ROOT) not in sys.path:
    sys.path.insert(0, str(BIN_ROOT))

import bridge_call  # noqa: E402  (loaded from the installed-plugin-equivalent bin directory)
import bridge_diagnose  # noqa: E402  (shares bridge_call's local import seam)
import bridge_mcp  # noqa: E402  (shares bridge_call's local import seam)


def _supports_directory_symlinks() -> bool:
    """Probe symlink capability at collection time for the containment regression."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "target"
        link = root / "link"
        target.mkdir()
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            return False
        return link.is_symlink()


DIRECTORY_SYMLINKS_SUPPORTED = _supports_directory_symlinks()


def _request(tmp_path: Path, **overrides: Any) -> bridge_call.Request:
    """Build one small local request with explicit, deterministic routing values."""
    values: dict[str, Any] = {
        "verb": "advise",
        "task": "Report completion.",
        "model": "test-model",
        "effort": "medium",
        "timeout_seconds": 1.0,
        "depth": 0,
        "run_id": "run-fixed",
        "workspace": tmp_path,
        "direction": "claude_to_codex",
    }
    values.update(overrides)
    return bridge_call.Request(**values)


def _core(status: str = "complete", *, details: list[str] | None = None, **overrides: object) -> dict[str, object]:
    """Return a valid peer result fixture with optional transcript-only detail."""
    core: dict[str, object] = {
        "status": status,
        "verdict": "Finished deterministically.",
        "findings": [],
        "files_touched": [],
        "remaining": [],
        "blockers": [],
        "details": details or [],
    }
    core.update(overrides)
    return core


def _outcome(
    *, core: dict[str, object] | None = None, error: str | None = None, timed_out: bool = False
) -> bridge_call.ChildOutcome:
    """Create a fake child result using the real JSONL parser's event shapes."""
    records: list[dict[str, object]] = [{"type": "thread.started", "thread_id": "session-fixed"}]
    if core is not None:
        records.append({"type": "item.completed", "item": {"text": json.dumps(core)}})
        records.append({"type": "turn.completed", "usage": {"input": 3, "output": 2, "cost": 0.01}})
    if error is not None:
        records.append(
            {
                "type": "turn.failed",
                "error": {"code": "unsupported_value", "param": "reasoning.effort", "message": error},
            }
        )
    return bridge_call.ChildOutcome(
        "\n".join(json.dumps(item) for item in records), "", 0 if core else 1, timed_out, None
    )


def _claude_outcome(core: dict[str, object]) -> bridge_call.ChildOutcome:
    """Create one Claude print-mode response at the provider process boundary."""
    return bridge_call.ChildOutcome(
        json.dumps({"structured_output": core, "usage": {"input": 3, "output": 2}}), "", 0, False, None
    )


def _process_exists(pid: int) -> bool:
    """Report process liveness without using Windows os.kill termination semantics."""
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        return result.returncode == 0 and f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_fresh_review_and_resume_argv_preserve_routing_contract(tmp_path: Path) -> None:
    """Prevent subtle Codex argv drift that changes sandbox, review, or resume behavior."""
    schema_path = tmp_path / "core-schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    fresh = bridge_call.build_codex_argv(_request(tmp_path, verb="advise"), schema_path)
    review = bridge_call.build_codex_argv(_request(tmp_path, verb="review"), schema_path)
    implement = bridge_call.build_codex_argv(_request(tmp_path, verb="implement"), schema_path)
    resumed = bridge_call.build_codex_argv(
        _request(tmp_path, verb="implement", session_id="session-fixed", origin_workspace=tmp_path), schema_path
    )

    assert fresh[:2] == ["codex", "exec"]
    assert ["-s", "read-only"] == fresh[fresh.index("-s") : fresh.index("-s") + 2]
    assert "--ephemeral" in fresh and "--ignore-user-config" in fresh
    assert 'model_reasoning_effort="medium"' in fresh
    assert all("--skip-git-repo-check" in command for command in (fresh, review, implement))
    assert review[:2] == ["codex", "exec"]
    assert review[:3] != ["codex", "exec", "review"]
    assert ["-s", "read-only"] == review[review.index("-s") : review.index("-s") + 2]
    assert "--ephemeral" in review
    assert "adversarial" in review[-1].lower()
    assert "review" in review[-1].lower()
    assert resumed[:4] == ["codex", "exec", "resume", "session-fixed"]
    assert "--last" not in resumed
    assert "--skip-git-repo-check" in resumed
    assert 'sandbox_mode="workspace-write"' in resumed
    with pytest.raises(ValueError, match="only implement"):
        bridge_call.build_codex_argv(
            _request(tmp_path, session_id="session-fixed", origin_workspace=tmp_path), schema_path
        )
    with pytest.raises(ValueError, match="originating workspace"):
        bridge_call.build_codex_argv(
            _request(tmp_path, verb="implement", session_id="session-fixed", origin_workspace=tmp_path / "other"),
            schema_path,
        )


def test_invalid_effort_is_rejected_before_a_child_can_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent an unknown caller effort from silently consuming default-tier tokens."""
    monkeypatch.setattr(bridge_call, "_run_child", lambda *args: pytest.fail("invalid effort spawned a child"))

    result = bridge_call.run_request(_request(tmp_path, effort="bogus"))

    assert result["status"] == "blocked"
    assert "unsupported effort level" in result["verdict"]
    assert (tmp_path / ".temp" / "bridge" / "health.jsonl").is_file()


@pytest.mark.skipif(not DIRECTORY_SYMLINKS_SUPPORTED, reason="requires directory symlink creation capability")
def test_artifact_store_rejects_a_preexisting_temp_symlink_before_any_write(tmp_path: Path) -> None:
    """Prevent bridge artifacts from escaping the selected workspace through a hostile ancestor link."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".temp").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        bridge_call.run_request(_request(tmp_path, effort="bogus"))

    assert not (outside / "bridge").exists()


@pytest.mark.skipif(not DIRECTORY_SYMLINKS_SUPPORTED, reason="requires directory symlink creation capability")
def test_mcp_containment_rejection_returns_a_generic_error_without_provider_dispatch(tmp_path: Path) -> None:
    """Prevent an escaped artifact root from leaking host paths through the reverse MCP transport."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-mcp-outside"
    outside.mkdir()
    (workspace / ".temp").symlink_to(outside, target_is_directory=True)
    messages = "\n".join(
        json.dumps(message)
        for message in (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "bridge_advise", "arguments": {"task": "Reject the escaped artifact root."}},
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
    )
    result = subprocess.run(
        [sys.executable, str(BIN_ROOT / "bridge_mcp.py"), "--stdio"],
        input=messages + "\n",
        capture_output=True,
        text=True,
        cwd=workspace,
        check=False,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["error"] == {"code": -32603, "message": "bridge execution failed"}
    assert str(outside) not in responses[0]["error"]["message"]
    assert not (outside / "bridge").exists()
    assert set(tool["name"] for tool in responses[1]["result"]["tools"]) == set(bridge_mcp.TOOL_NAMES)


@pytest.mark.parametrize("timeout", ("nan", "inf", "-inf"), ids=("nan", "positive-infinity", "negative-infinity"))
def test_cli_rejects_nonfinite_timeout_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], timeout: str
) -> None:
    """Prevent a non-finite CLI deadline from reaching a provider child process."""
    monkeypatch.setattr(
        bridge_call, "_run_child", lambda *args: pytest.fail("non-finite timeout dispatched a provider")
    )

    exit_code = bridge_call.main(
        [
            "advise",
            "--task",
            "Reject this malformed deadline.",
            f"--timeout-seconds={timeout}",
            "--workspace",
            str(tmp_path),
        ]
    )

    response = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert response["status"] == "error"


def test_structured_unsupported_effort_retries_once_and_records_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent an unsupported-effort loop from repeatedly charging or dispatching peers."""
    attempts: list[str] = []

    def fake_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        attempts.append(next(item for item in command if item.startswith("model_reasoning_effort=")))
        return _outcome(error="target rejected effort")

    monkeypatch.setattr(bridge_call, "_run_child", fake_child)
    result = bridge_call.run_request(_request(tmp_path, effort="high", supported_efforts=("low", "medium", "high")))

    assert attempts == ['model_reasoning_effort="high"', 'model_reasoning_effort="medium"']
    assert result["status"] == "blocked"
    assert result["effort_substituted"] == {
        "requested": "high",
        "applied": "medium",
        "reason": "structured unsupported effort",
    }


def test_general_review_runs_read_only_exec_and_returns_a_compact_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent native review prose from bypassing the bridge's structured-result contract."""
    commands: list[list[str]] = []

    def fake_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        commands.append(command)
        return _outcome(core=_core(details=["Reviewed the full local diff."]))

    monkeypatch.setattr(bridge_call, "_run_child", fake_child)
    result = bridge_call.run_request(_request(tmp_path, verb="review"))

    assert commands[0][:2] == ["codex", "exec"]
    assert commands[0][:3] != ["codex", "exec", "review"]
    assert ["-s", "read-only"] == commands[0][commands[0].index("-s") : commands[0].index("-s") + 2]
    assert "--ephemeral" in commands[0]
    assert "adversarial" in commands[0][-1].lower()
    assert "review" in commands[0][-1].lower()
    assert result["status"] == "complete"
    assert result["verdict"] == "Finished deterministically."
    assert "details" not in result


def test_partial_result_keeps_remaining_work_public_and_details_transcript_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent incomplete work from being hidden solely in the transcript-only detail field."""
    remaining = "Run the focused package validation."
    detail = "The peer explains why the package validation remains necessary."
    monkeypatch.setattr(
        bridge_call,
        "_run_child",
        lambda *args: _outcome(core=_core("partial", remaining=[remaining], details=[detail])),
    )

    envelope = bridge_call.run_request(_request(tmp_path))
    transcript = (tmp_path / envelope["transcript_path"]).read_text(encoding="utf-8")

    assert envelope["status"] == "partial"
    assert envelope["remaining"] == [remaining]
    assert "details" not in envelope
    assert detail in transcript


def test_oversized_remaining_summary_becomes_a_blocked_public_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent more than eight decision-critical remaining items from escaping the compact envelope."""
    monkeypatch.setattr(
        bridge_call,
        "_run_child",
        lambda *args: _outcome(core=_core("partial", remaining=["follow-up"] * 9)),
    )

    envelope = bridge_call.run_request(_request(tmp_path))

    assert envelope["status"] == "blocked"
    assert "invalid model result" in envelope["verdict"]


def test_budget_prompt_and_timeout_terminate_held_process(tmp_path: Path) -> None:
    """Prevent an inherited stdin/process-group hang from outliving the hard deadline."""
    request = _request(tmp_path, timeout_seconds=0.1)
    prompt = bridge_call._prompt_with_budget(request)
    assert "soft budget of 0.1 seconds" in prompt
    assert "Bridge depth is 0; run id is run-fixed" in prompt

    outcome = bridge_call._run_child([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 0.05)

    assert outcome.timed_out is True
    assert outcome.returncode is not None


def test_timeout_retries_read_only_once_at_a_lower_tier_but_never_implement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a timeout retry from escalating cost, duplicating implement edits, or looping on advise."""
    efforts: list[str] = []

    def timeout_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        efforts.append(next(item for item in command if item.startswith("model_reasoning_effort=")))
        return _outcome(timed_out=True)

    monkeypatch.setattr(bridge_call, "_run_child", timeout_child)
    advise = bridge_call.run_request(_request(tmp_path, effort="medium", supported_efforts=("low", "medium")))
    floor = bridge_call.run_request(_request(tmp_path, effort="low", supported_efforts=("low", "medium")))
    implement = bridge_call.run_request(
        _request(tmp_path, verb="implement", effort="medium", supported_efforts=("low", "medium"))
    )

    assert efforts == [
        'model_reasoning_effort="medium"',
        'model_reasoning_effort="low"',
        'model_reasoning_effort="low"',
        'model_reasoning_effort="medium"',
    ]
    assert advise["status"] == "timeout"
    assert advise["effort_substituted"] == {"requested": "medium", "applied": "low", "reason": "timeout retry"}
    assert floor["status"] == "timeout"
    assert floor["effort_substituted"] is None
    assert implement["status"] == "timeout"
    assert implement["effort_substituted"] is None


def test_event_parsing_and_terminal_incident_health_workspace_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent lost session/usage data and missing implement-delta evidence after a cutoff."""
    parsed = bridge_call._parse_output(_outcome(core=_core()).stdout, "codex")
    assert parsed.core == _core()
    assert parsed.session_id == "session-fixed"
    assert parsed.tokens == {"input": 3.0, "output": 2.0}
    assert parsed.cost == 0.01

    snapshots = iter([[], [" M landed.py"]])
    monkeypatch.setattr(bridge_call, "_workspace_state", lambda workspace: next(snapshots))
    monkeypatch.setattr(bridge_call, "_run_child", lambda *args: _outcome(timed_out=True))
    result = bridge_call.run_request(_request(tmp_path, verb="implement"))

    incident = json.loads((tmp_path / result["incident"]).read_text(encoding="utf-8"))
    health = [json.loads(line) for line in (tmp_path / ".temp" / "bridge" / "health.jsonl").read_text().splitlines()]
    assert result["status"] == "timeout"
    assert incident["workspace_delta"] == [" M landed.py"]
    assert health[-1]["run_id"] == "run-fixed"
    assert health[-1]["status"] == "timeout"


def test_claude_parser_preserves_top_level_aggregate_cost() -> None:
    """Prevent a valid Claude result from losing cost stored beside nested usage counters."""
    stdout = json.dumps(
        {
            "structured_output": _core(),
            "usage": {"input_tokens": 41, "output_tokens": 7},
            "total_cost_usd": 0.451996,
            "session_id": "claude-session-fixed",
        }
    )

    parsed = bridge_call._parse_output(stdout, "claude")

    assert parsed.core == _core()
    assert parsed.tokens == {"input_tokens": 41.0, "output_tokens": 7.0}
    assert parsed.cost == 0.451996
    assert parsed.session_id == "claude-session-fixed"


def test_claude_aggregate_cost_reaches_public_envelope_and_health_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent correct Claude parsing from being dropped by envelope or accounting wiring."""
    provider_result = {
        "structured_output": _core(),
        "usage": {"input_tokens": 41, "output_tokens": 7},
        "total_cost_usd": 0.451996,
    }
    monkeypatch.setattr(
        bridge_call,
        "_run_child",
        lambda *args: bridge_call.ChildOutcome(json.dumps(provider_result), "", 0, False, None),
    )

    result = bridge_call.run_request(_request(tmp_path, direction="codex_to_claude"), host="claude")

    health = [json.loads(line) for line in (tmp_path / ".temp" / "bridge" / "health.jsonl").read_text().splitlines()]
    assert result["cost"] == 0.451996
    assert result["tokens"] == {"input_tokens": 41.0, "output_tokens": 7.0}
    assert health[-1]["cost"] == 0.451996
    assert health[-1]["direction"] == "codex_to_claude"


def test_claude_provider_error_preserves_bounded_api_context_and_zero_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent Claude rate-limit failures from degrading to a generic child-exit verdict."""
    provider_message = "Spend limit reached; " + "x" * (bridge_call.MAX_VERDICT_CHARS * 2)
    provider_result = {
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": 429,
        "result": provider_message,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "details": ["Transcript-only provider diagnostic."],
    }
    monkeypatch.setattr(
        bridge_call,
        "_run_child",
        lambda *args: bridge_call.ChildOutcome(json.dumps(provider_result), "", 1, False, None),
    )

    result = bridge_call.run_request(_request(tmp_path, direction="codex_to_claude"), host="claude")

    incident = json.loads((tmp_path / result["incident"]).read_text(encoding="utf-8"))
    transcript = (tmp_path / result["transcript_path"]).read_text(encoding="utf-8")
    assert result["status"] == "blocked"
    assert result["verdict"].startswith("api_error: HTTP 429: Spend limit reached; ")
    assert len(result["verdict"]) == bridge_call.MAX_VERDICT_CHARS
    assert result["tokens"] == {"input_tokens": 0.0, "output_tokens": 0.0}
    assert "details" not in result
    assert incident["fault"] == "blocked"
    assert incident["reason"] == result["verdict"]
    assert provider_result["details"][0] in transcript
    assert provider_result["details"][0] not in result["verdict"]


def test_reverse_read_only_maximum_budgets_both_hard_cutoff_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent the reverse retry path from outliving the MCP host deadline."""
    hard_cutoffs: list[float] = []

    def timeout_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        hard_cutoffs.append(timeout)
        return _outcome(timed_out=True)

    monkeypatch.setattr(bridge_call, "_run_child", timeout_child)
    maximum = bridge_mcp.MAX_MCP_TIMEOUT_SECONDS_BY_VERB["advise"]
    result = bridge_call.run_request(
        _request(
            tmp_path,
            direction="codex_to_claude",
            timeout_seconds=maximum,
            effort="medium",
            supported_efforts=("low", "medium"),
        ),
        host="claude",
    )

    assert result["status"] == "timeout"
    assert hard_cutoffs == [maximum * bridge_call.CHILD_TIMEOUT_MULTIPLIER] * 2
    assert sum(hard_cutoffs) + bridge_mcp.MCP_RESPONSE_MARGIN_SECONDS < bridge_mcp.MCP_HOST_DEADLINE_SECONDS


def test_job_lifecycle_uses_workspace_local_record_and_missing_signal_doubles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent status/cancel from depending on host process signalling or home-state records."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "11111111-1111-4111-8111-111111111111"
    job_path = paths.jobs / f"{job_id}.json"
    job_path.write_text(json.dumps({"job_id": job_id, "status": "running", "pid": 42}), encoding="utf-8")
    # Liveness probing has its own tests; pin it alive so this test observes
    # only cancel semantics, deterministically on every host.
    monkeypatch.setattr(bridge_call, "_process_exists", lambda pid: True)
    monkeypatch.setattr(bridge_call.os, "kill", lambda *args: pytest.fail("cancellation signalled a persisted PID"))
    monkeypatch.setattr(
        bridge_call.os, "killpg", lambda *args: pytest.fail("cancellation signalled a process group"), raising=False
    )

    assert bridge_call.job_status(tmp_path, "22222222-2222-4222-8222-222222222222")["status"] == "missing"
    cancelled = bridge_call.cancel_job(tmp_path, job_id)

    assert cancelled["status"] == "cancel_requested"
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "cancel_requested"


@pytest.mark.parametrize("command", ("status", "result", "cancel"), ids=("status", "result", "cancel"))
def test_lifecycle_cli_rejects_job_identifier_traversal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """Prevent lifecycle commands from reading or rewriting records outside the job store."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    escaped_record = paths.root / "escaped.json"
    original = {"job_id": "escaped", "status": "finished", "pid": 42}
    escaped_record.write_text(json.dumps(original), encoding="utf-8")

    exit_code = bridge_call.main([command, "--job-id", "../escaped", "--workspace", str(tmp_path)])
    response = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert response["status"] == "error"
    assert "job" in response["error"].lower()
    assert json.loads(escaped_record.read_text(encoding="utf-8")) == original


def test_supervisor_rejects_job_identifier_traversal_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a detached supervisor from creating or overwriting an escaped job record."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    escaped_record = paths.root / "escaped.json"
    original = {"job_id": "escaped", "status": "finished", "pid": 42}
    escaped_record.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(
        bridge_call, "run_request", lambda request, **kwargs: pytest.fail("invalid supervisor dispatched")
    )

    exit_code = bridge_call.main(
        [
            "advise",
            "--task",
            "Keep the record contained.",
            "--job-id",
            "../escaped",
            "--supervisor",
            "--workspace",
            str(tmp_path),
        ]
    )
    response = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert response["status"] == "error"
    assert "job" in response["error"].lower()
    assert json.loads(escaped_record.read_text(encoding="utf-8")) == original


def test_background_dispatch_leaves_pid_ownership_to_the_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent the launcher from racing its supervisor's record writes or losing the result."""

    class Process:
        pid = 123

    monkeypatch.setattr(bridge_call.subprocess, "Popen", lambda *args, **kwargs: Process())
    started = bridge_call.start_background(_request(tmp_path, background=True))
    record_path = tmp_path.resolve() / ".temp" / "bridge" / "jobs" / f"{started['job_id']}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert started["status"] == "queued"
    assert record["status"] == "queued"
    assert record["pid"] is None
    assert isinstance(record["started_ts"], float)
    assert record["request"]["run_id"] == "run-fixed"

    record.update({"status": "finished", "pid": 123, "result": _finished_envelope()})
    bridge_call._write_json(record_path, record)

    assert bridge_call.job_status(tmp_path.resolve(), started["job_id"]) == {
        "job_id": started["job_id"],
        "status": "finished",
        "pid": 123,
    }
    assert bridge_call.job_result(tmp_path.resolve(), started["job_id"]) == _finished_envelope()


def _finished_envelope() -> dict[str, object]:
    """Return a complete valid public envelope for stored-job-result fixtures."""
    return {
        "status": "complete",
        "verdict": "done",
        "findings": [],
        "files_touched": [],
        "remaining": [],
        "blockers": [],
        "model": "test-model",
        "effort": "medium",
        "effort_substituted": None,
        "cost": None,
        "tokens": {},
        "duration_seconds": 0.0,
        "depth": 0,
        "run_id": "run-fixed",
        "incident": None,
        "session_id": None,
        "transcript_path": ".temp/bridge/raw-fixed.txt",
        "verb": "implement",
        "direction": "claude_to_codex",
    }


def test_job_result_rejects_a_tampered_stored_envelope(tmp_path: Path) -> None:
    """Prevent a hand-edited job record from masquerading as a validated envelope."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "88888888-8888-4888-8888-888888888888"
    tampered = {**_finished_envelope(), "status": "totally-fine"}
    bridge_call._write_json(
        paths.jobs / f"{job_id}.json",
        {"job_id": job_id, "status": "finished", "pid": None, "result": tampered},
    )

    with pytest.raises(ValueError, match="unsupported status"):
        bridge_call.job_result(tmp_path, job_id)

    bridge_call._write_json(paths.jobs / f"{job_id}.cancel.json", {"job_id": job_id})

    with pytest.raises(ValueError, match="unsupported status"):
        bridge_call.job_result(tmp_path, job_id)


def test_help_token_matching_requires_word_boundaries() -> None:
    """Prevent a removed CLI subcommand from passing preflight via a prose substring."""
    assert bridge_diagnose._token_present("exec", "codex exec --json") is True
    assert bridge_diagnose._token_present("exec", "commands execute quickly") is False
    assert bridge_diagnose._token_present("--json", "supports --json output") is True
    assert bridge_diagnose._token_present("--json", "supports --json-schema output") is False


def test_background_dispatch_omits_unselected_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a host-default background request from passing a null subprocess argument."""

    class Process:
        pid = 123

    commands: list[list[object]] = []

    def fake_popen(command: list[object], **kwargs: object) -> Process:
        commands.append(command)
        return Process()

    monkeypatch.setattr(bridge_call.subprocess, "Popen", fake_popen)
    bridge_call.start_background(_request(tmp_path, background=True, model=None))

    assert commands
    assert "--model" not in commands[0]
    assert all(argument is not None for argument in commands[0])


def test_cancel_does_not_signal_a_stale_persisted_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a stale job record from targeting an unrelated recycled process."""
    paths = bridge_call.BridgePaths(tmp_path.resolve())
    paths.prepare()
    job_id = "33333333-3333-4333-8333-333333333333"
    job_path = paths.jobs / f"{job_id}.json"
    job_path.write_text(json.dumps({"job_id": job_id, "status": "running", "pid": 42}), encoding="utf-8")
    monkeypatch.setattr(bridge_call, "_process_exists", lambda pid: True)
    monkeypatch.setattr(bridge_call.os, "kill", lambda *args: pytest.fail("stale PID was signalled"))
    monkeypatch.setattr(
        bridge_call.os, "killpg", lambda *args: pytest.fail("stale process group was signalled"), raising=False
    )
    monkeypatch.setattr(
        bridge_call.subprocess, "run", lambda *args, **kwargs: pytest.fail("stale PID reached taskkill")
    )

    cancelled = bridge_call.cancel_job(tmp_path, job_id)

    assert cancelled["status"] == "cancel_requested"
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "cancel_requested"


def test_dead_supervisor_running_record_is_reported_stalled(tmp_path: Path) -> None:
    """Prevent a killed supervisor from leaving a job that reports running forever."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    exited = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL)
    exited.wait()
    stalled_id = "44444444-4444-4444-8444-444444444444"
    live_id = "55555555-5555-4555-8555-555555555555"
    (paths.jobs / f"{stalled_id}.json").write_text(
        json.dumps({"job_id": stalled_id, "status": "running", "pid": exited.pid}), encoding="utf-8"
    )
    (paths.jobs / f"{live_id}.json").write_text(
        json.dumps({"job_id": live_id, "status": "running", "pid": os.getpid()}), encoding="utf-8"
    )

    assert bridge_call.job_status(tmp_path, stalled_id)["status"] == "stalled"
    assert bridge_call.job_result(tmp_path, stalled_id)["status"] == "stalled"
    assert bridge_call.job_status(tmp_path, live_id)["status"] == "running"


def test_windows_stalled_probe_uses_tasklist_and_never_signals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the Windows liveness probe from using os.kill termination semantics."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "77777777-7777-4777-8777-777777777777"
    (paths.jobs / f"{job_id}.json").write_text(
        json.dumps({"job_id": job_id, "status": "running", "pid": 4242}), encoding="utf-8"
    )
    probes: list[list[str]] = []

    def fake_tasklist(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        probes.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="INFO: No tasks are running.", stderr="")

    monkeypatch.setattr(bridge_call.os, "name", "nt")
    monkeypatch.setattr(bridge_call.os, "kill", lambda *args: pytest.fail("liveness probe signalled a PID"))
    monkeypatch.setattr(bridge_call.subprocess, "run", fake_tasklist)

    assert bridge_call.job_status(tmp_path, job_id)["status"] == "stalled"
    assert probes and probes[0][0] == "tasklist"


def test_cancelling_a_stalled_job_keeps_the_terminal_stalled_signal(tmp_path: Path) -> None:
    """Prevent a cancel on a dead supervisor from masking stalled behind cancel_requested forever."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    exited = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL)
    exited.wait()
    job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    (paths.jobs / f"{job_id}.json").write_text(
        json.dumps({"job_id": job_id, "status": "running", "pid": exited.pid}), encoding="utf-8"
    )

    cancelled = bridge_call.cancel_job(tmp_path, job_id)

    assert cancelled["status"] == "stalled"
    assert not (paths.jobs / f"{job_id}.cancel.json").exists()
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "stalled"
    assert bridge_call.job_result(tmp_path, job_id)["status"] == "stalled"


def test_expired_queued_record_without_a_supervisor_is_reported_stalled(tmp_path: Path) -> None:
    """Prevent a supervisor that died before its first record write from leaving queued forever."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    stale = time.time() - bridge_call.QUEUED_STALL_SECONDS - 1
    (paths.jobs / f"{job_id}.json").write_text(
        json.dumps({"job_id": job_id, "status": "queued", "pid": None, "started_ts": stale}), encoding="utf-8"
    )
    fresh_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    (paths.jobs / f"{fresh_id}.json").write_text(
        json.dumps({"job_id": fresh_id, "status": "queued", "pid": None, "started_ts": time.time()}),
        encoding="utf-8",
    )

    assert bridge_call.job_status(tmp_path, job_id)["status"] == "stalled"
    assert bridge_call.job_status(tmp_path, fresh_id)["status"] == "queued"


def test_cancel_marker_arriving_before_a_retry_stops_the_second_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a retry recursion from dropping the job path and ignoring a cancellation."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    job_path = paths.jobs / f"{job_id}.json"
    attempts: list[str] = []

    def timeout_then_cancelled(
        command: list[str], workspace: Path, timeout: float, job: Path | None = None
    ) -> bridge_call.ChildOutcome:
        attempts.append(command[-1])
        bridge_call._write_json(job_path.with_name(f"{job_id}.cancel.json"), {"job_id": job_id})
        return _outcome(timed_out=True)

    monkeypatch.setattr(bridge_call, "_run_child", timeout_then_cancelled)
    result = bridge_call.run_request(
        _request(tmp_path, effort="medium", supported_efforts=("low", "medium")), _job_path=job_path
    )

    assert len(attempts) == 1
    assert result["status"] == "blocked"
    assert result["blockers"] == ["cancelled by job owner"]


def test_supervisor_internal_failure_writes_a_terminal_failed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prevent a supervisor exception from leaving a running record no caller can resolve."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    bridge_call._write_json(
        paths.jobs / f"{job_id}.json", {"job_id": job_id, "status": "queued", "pid": None, "result": None}
    )

    def exploding_run_request(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("artifact store exploded")

    monkeypatch.setattr(bridge_call, "run_request", exploding_run_request)
    exit_code = bridge_call.main(
        ["implement", "--task", "Fail internally.", "--job-id", job_id, "--supervisor", "--workspace", str(tmp_path)]
    )
    capsys.readouterr()

    assert exit_code == 2
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "failed"
    record = json.loads((paths.jobs / f"{job_id}.json").read_text(encoding="utf-8"))
    assert record["error"] == "artifact store exploded"


def test_corrupt_cancel_marker_is_ignored_instead_of_killing_the_supervisor(tmp_path: Path) -> None:
    """Prevent a malformed cancellation marker from crashing the poll loop over a live child."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "99999999-9999-4999-8999-999999999999"
    job_path = paths.jobs / f"{job_id}.json"
    (paths.jobs / f"{job_id}.cancel.json").write_text("{truncated", encoding="utf-8")

    assert bridge_call._job_cancel_requested(job_path) is False

    (paths.jobs / f"{job_id}.cancel.json").write_text(json.dumps({"job_id": "someone-else"}), encoding="utf-8")

    assert bridge_call._job_cancel_requested(job_path) is False


def test_write_verb_effort_failure_is_reported_without_a_second_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a failed write-capable child from being rerun against an already-edited worktree."""
    attempts: list[list[str]] = []

    def failing_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        attempts.append(command)
        return _outcome(error="target rejected effort")

    monkeypatch.setattr(bridge_call, "_run_child", failing_child)
    result = bridge_call.run_request(
        _request(tmp_path, verb="implement", effort="high", supported_efforts=("low", "medium", "high"))
    )

    assert len(attempts) == 1
    assert result["status"] == "blocked"
    assert result["effort_substituted"] is None


def test_workspace_state_degrades_when_git_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a machine without Git from crashing write-capable dispatch instead of degrading."""

    def missing_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(bridge_call.subprocess, "run", missing_git)

    assert bridge_call._workspace_state(tmp_path) == []


def test_supervisor_preserves_a_cancellation_requested_during_its_final_record_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a completed supervisor update from overwriting a concurrent cancellation request."""
    paths = bridge_call.BridgePaths(tmp_path)
    paths.prepare()
    job_id = "66666666-6666-4666-8666-666666666666"
    record_path = paths.jobs / f"{job_id}.json"
    bridge_call._write_json(record_path, {"job_id": job_id, "status": "queued", "pid": None, "result": None})
    original_write_json = bridge_call._write_json
    cancellation_injected = False

    def fake_run_request(request: bridge_call.Request, **kwargs: object) -> dict[str, object]:
        return {
            "status": "complete",
            "verdict": "The child completed before the owner cancelled.",
            "findings": ["Adjusted the bounded module."],
            "files_touched": ["landed.py"],
            "remaining": ["Run the focused test."],
            "blockers": [],
            "model": "test-model",
            "effort": "medium",
            "effort_substituted": None,
            "cost": None,
            "tokens": {},
            "duration_seconds": 0.0,
            "depth": 0,
            "run_id": "run-fixed",
            "incident": None,
            "session_id": None,
            "transcript_path": ".temp/bridge/raw-fixed.txt",
            "verb": "implement",
            "direction": "claude_to_codex",
        }

    def write_with_racing_cancellation(path: Path, value: dict[str, object]) -> None:
        nonlocal cancellation_injected
        if path == record_path and value.get("result") is not None and not cancellation_injected:
            cancellation_injected = True
            bridge_call.cancel_job(tmp_path, job_id)
        original_write_json(path, value)

    monkeypatch.setattr(bridge_call, "run_request", fake_run_request)
    monkeypatch.setattr(bridge_call, "_write_json", write_with_racing_cancellation)

    exit_code = bridge_call.main(
        [
            "implement",
            "--task",
            "Finish a bounded task.",
            "--job-id",
            job_id,
            "--supervisor",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert cancellation_injected is True
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "cancelled"
    result = bridge_call.job_result(tmp_path, job_id)
    assert result["status"] == "blocked"
    assert result["blockers"] == ["cancelled by job owner"]
    assert result["files_touched"] == ["landed.py"]
    assert result["findings"] == ["Adjusted the bounded module."]
    assert result["remaining"] == ["Run the focused test."]


def test_diagnostics_detect_missing_help_flag_without_live_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent static setup from reporting success when a required CLI option disappeared."""

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="exec resume review --json", stderr="")

    monkeypatch.setattr(bridge_diagnose.subprocess, "run", fake_run)
    result = bridge_diagnose.diagnose("codex", tmp_path, live=False)

    assert result["live"] is False
    assert result["ok"] is False
    assert "--output-schema" in result["findings"][0]["missing"]


def test_diagnostics_report_a_malformed_baseline_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prevent a corrupted shipped baseline from crashing setup instead of reporting a finding."""
    with monkeypatch.context() as patched:
        patched.setattr(
            bridge_diagnose.json,
            "loads",
            lambda text: {"codex": {"required": []}, "claude": {"required": ["--print"]}},
        )
        exit_code = bridge_diagnose.main(["--direction", "codex", "--workspace", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["ok"] is False
    assert "baseline" in report["error"]


def test_claude_diagnostic_baseline_covers_every_runtime_argv_flag(tmp_path: Path) -> None:
    """Prevent static preflight from missing a Claude switch the bridge dispatches at runtime."""
    schema_path = tmp_path / "core-schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    baseline = json.loads(
        (Path(__file__).resolve().parents[1] / "rules" / "cli-baseline.json").read_text(encoding="utf-8")
    )
    runtime_flags = {
        item
        for verb in ("implement", "advise", "review")
        for item in bridge_call.build_claude_argv(_request(tmp_path, verb=verb), schema_path)
        if item.startswith("--")
    }

    assert runtime_flags <= set(baseline["claude"]["required"])


def test_codex_diagnostic_baseline_covers_every_runtime_argv_flag(tmp_path: Path) -> None:
    """Prevent static preflight from missing a Codex switch the bridge dispatches at runtime."""
    schema_path = tmp_path / "core-schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    baseline = json.loads(
        (Path(__file__).resolve().parents[1] / "rules" / "cli-baseline.json").read_text(encoding="utf-8")
    )
    fresh_commands = [
        bridge_call.build_codex_argv(_request(tmp_path, verb=verb), schema_path)
        for verb in ("advise", "review", "implement")
    ]
    resumed_command = bridge_call.build_codex_argv(
        _request(tmp_path, verb="implement", session_id="session-fixed", origin_workspace=tmp_path), schema_path
    )
    runtime_flags = {
        item for command in [*fresh_commands, resumed_command] for item in command if item.startswith("--")
    }

    assert runtime_flags <= set(baseline["codex"]["required"])


def test_cli_implement_is_the_only_write_capable_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prevent implement from becoming read-only or a read-only verb from gaining write access."""
    commands: dict[str, list[str]] = {}

    def fake_child(command: list[str], *args: object) -> bridge_call.ChildOutcome:
        commands[verb] = command
        return _outcome(core=_core())

    monkeypatch.setattr(bridge_call, "_run_child", fake_child)

    for verb in ("implement", "advise", "review"):
        exit_code = bridge_call.main([verb, "--task", "Make the bounded change.", "--workspace", str(tmp_path)])
        envelope = json.loads(capsys.readouterr().out)

        assert exit_code == 0
        assert envelope["status"] == "complete"
        assert envelope["verb"] == verb

    sandbox = {verb: command[command.index("-s") + 1] for verb, command in commands.items()}
    assert sandbox == {"implement": "workspace-write", "advise": "read-only", "review": "read-only"}
    with pytest.raises(SystemExit):
        bridge_call.main(["delegate", "--task", "Rejected.", "--workspace", str(tmp_path)])


def test_mcp_exposes_implement_and_refuses_the_retired_delegate_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent the reverse bridge from dropping implement or resurrecting a second write-capable tool name."""
    captured: list[bridge_call.Request] = []

    def fake_run_request(request: bridge_call.Request, *, host: str) -> dict[str, object]:
        captured.append(request)
        assert host == "claude"
        return {"status": "complete"}

    monkeypatch.setattr(bridge_mcp, "run_request", fake_run_request)
    listed = {tool["name"] for tool in bridge_mcp.tool_definitions()}

    response = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "bridge_implement", "arguments": {"task": "Make the bounded change."}},
        },
        trusted_workspace=tmp_path,
    )
    assert response["result"]["isError"] is False

    retired = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "bridge_delegate", "arguments": {"task": "Make the bounded change."}},
        },
        trusted_workspace=tmp_path,
    )
    assert "error" in retired

    assert "bridge_implement" in listed
    assert "bridge_delegate" not in listed
    assert [request.verb for request in captured] == ["implement"]


def test_mcp_handshake_tools_call_and_recursion_guard_preserve_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent MCP transport drift, unknown fields, and a second cross-host hop."""
    initialized = bridge_mcp.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    tools = bridge_mcp.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert initialized["result"]["capabilities"] == {"tools": {}}
    listed = {item["name"]: item for item in tools["result"]["tools"]}
    assert set(listed) == {"bridge_implement", "bridge_advise", "bridge_review"}
    assert "background" not in listed["bridge_implement"]["inputSchema"]["properties"]
    assert "workspace" not in listed["bridge_advise"]["inputSchema"]["properties"]

    result = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "bridge_advise",
                "arguments": {"task": "No peer call.", "depth": 1, "run_id": "tree-fixed"},
            },
        },
        trusted_workspace=tmp_path,
    )
    envelope = json.loads(result["result"]["content"][0]["text"])
    assert envelope["status"] == "refused"
    assert envelope["blockers"] == ["recursion-depth"]
    assert envelope["run_id"] == "tree-fixed"


def test_mcp_rejects_model_supplied_workspace_and_reverse_session(tmp_path: Path) -> None:
    """Prevent a write-capable MCP call from widening host authority or faking resume."""
    for unsupported in (
        {"workspace": str(tmp_path.parent)},
        {"background": True},
        {"session_id": "session-fixed"},
    ):
        result = bridge_mcp.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "bridge_implement", "arguments": {"task": "No write.", **unsupported}},
            },
            trusted_workspace=tmp_path,
        )

        assert result["error"]["code"] == -32602
        assert "unsupported tool arguments" in result["error"]["message"]


def test_mcp_rejects_nonfinite_timeout_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent non-finite MCP deadlines from bypassing the provider dispatch boundary."""
    monkeypatch.setattr(
        bridge_mcp, "run_request", lambda *args, **kwargs: pytest.fail("non-finite timeout dispatched a provider")
    )

    for request_id, timeout in enumerate((float("nan"), float("inf"), float("-inf")), start=1):
        response = bridge_mcp.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "bridge_advise",
                    "arguments": {"task": "Reject this malformed deadline.", "timeout_seconds": timeout},
                },
            },
            trusted_workspace=tmp_path,
        )

        assert response["error"]["code"] == -32602


def test_mcp_rejects_invalid_request_shapes_with_the_standard_error_code() -> None:
    """Prevent malformed JSON-RPC requests from being treated as unknown methods."""
    for message in (
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2},
        {"jsonrpc": "2.0", "id": 3, "method": ["tools/list"]},
    ):
        response = bridge_mcp.handle_message(message)

        assert response["error"]["code"] == -32600


def test_mcp_notifications_never_reply_or_execute_a_provider_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent notification-shaped tool calls from consuming provider capacity without a response channel."""
    monkeypatch.setattr(
        bridge_mcp, "run_request", lambda *args, **kwargs: pytest.fail("notification dispatched a provider")
    )

    response = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "bridge_advise", "arguments": {"task": "Do not run this notification."}},
        },
        trusted_workspace=tmp_path,
    )

    assert response is None


def test_unknown_mcp_notification_does_not_receive_a_method_error() -> None:
    """Prevent an unknown notification from producing an invalid response without an identifier."""
    response = bridge_mcp.handle_message({"jsonrpc": "2.0", "method": "notifications/unknown"})

    assert response is None


def test_id_bearing_initialized_receives_an_acknowledgement() -> None:
    """Prevent a malformed id-bearing initialized message from leaving its request unanswered."""
    response = bridge_mcp.handle_message({"jsonrpc": "2.0", "id": 7, "method": "notifications/initialized"})

    assert response == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_malformed_notification_never_receives_an_error_response() -> None:
    """Prevent validation failures on id-less messages from violating the notification contract."""
    assert bridge_mcp.handle_message({"jsonrpc": "1.0", "method": "notifications/initialized"}) is None
    assert bridge_mcp.handle_message({"jsonrpc": "2.0", "method": ""}) is None
    assert bridge_mcp.handle_message({"jsonrpc": "2.0", "method": "tools/call", "params": 5}) is None


def test_mcp_refuses_write_verbs_from_a_home_or_root_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a host that launches the server from $HOME from rooting acceptEdits runs there."""
    dispatched: list[str] = []

    def fake_run_request(request: bridge_call.Request, **kwargs: object) -> dict[str, object]:
        dispatched.append(request.verb)
        return {"status": "complete"}

    monkeypatch.setattr(bridge_mcp, "run_request", fake_run_request)

    response = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "bridge_implement", "arguments": {"task": "Edit something."}},
        },
        trusted_workspace=Path.home(),
    )
    advisory = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "bridge_advise", "arguments": {"task": "Answer without editing."}},
        },
        trusted_workspace=Path.home(),
    )

    assert response is not None and response["error"]["code"] == -32602
    assert "workspace" in response["error"]["message"]
    assert advisory is not None and "error" not in advisory
    assert dispatched == ["advise"]


@pytest.mark.parametrize(
    "invalid_arguments",
    (
        {"depth": True},
        {"timeout_seconds": True},
        {"timeout_seconds": 360.1},
        {"supported_efforts": []},
    ),
    ids=("boolean-depth", "boolean-timeout", "timeout-over-host-safe-maximum", "empty-supported-efforts"),
)
def test_mcp_rejects_values_that_disagree_with_its_json_schema(
    tmp_path: Path, invalid_arguments: dict[str, object]
) -> None:
    """Prevent Python's bool-as-int rule or empty capability data from bypassing the MCP contract."""
    result = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "bridge_advise", "arguments": {"task": "Keep schema parity.", **invalid_arguments}},
        },
        trusted_workspace=tmp_path,
    )

    assert result["error"]["code"] == -32602


def test_mcp_uses_trusted_workspace_instead_of_model_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a reverse bridge request from escaping the MCP launch workspace."""
    captured: list[bridge_call.Request] = []

    def fake_run_request(request: bridge_call.Request, *, host: str) -> dict[str, object]:
        captured.append(request)
        assert host == "claude"
        return {"status": "complete", "run_id": request.run_id}

    monkeypatch.setattr(bridge_mcp, "run_request", fake_run_request)
    result = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "bridge_advise", "arguments": {"task": "Stay in the launch workspace."}},
        },
        trusted_workspace=tmp_path,
    )

    assert result["result"]["isError"] is False
    assert captured[0].workspace == tmp_path.resolve()
    assert captured[0].background is False
    assert captured[0].session_id is None


def test_reverse_mcp_uses_a_claude_compatible_schema_and_keeps_peer_details_in_the_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent verbose peer detail from escaping the compact MCP envelope or a rejected schema from reaching Claude."""
    commands: list[list[str]] = []
    peer_detail = "The provider emitted this verbose diagnostic only for the saved transcript."

    def fake_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        commands.append(command)
        return _claude_outcome(_core(details=[peer_detail]))

    monkeypatch.setattr(bridge_call, "_run_child", fake_child)
    response = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "bridge_advise", "arguments": {"task": "Return a bounded answer."}},
        },
        trusted_workspace=tmp_path,
    )

    envelope = json.loads(response["result"]["content"][0]["text"])
    schema = json.loads(commands[0][commands[0].index("--json-schema") + 1])
    canonical_schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "envelope.schema.json").read_text(encoding="utf-8")
    )
    transcript = (tmp_path / envelope["transcript_path"]).read_text(encoding="utf-8")

    assert "$schema" not in schema
    canonical_schema.pop("$schema")
    assert schema == canonical_schema
    assert set(schema["required"]) == {
        "status",
        "verdict",
        "findings",
        "files_touched",
        "remaining",
        "blockers",
        "details",
    }
    assert envelope["status"] == "complete"
    assert "details" not in envelope
    assert peer_detail in transcript
    assert peer_detail not in response["result"]["content"][0]["text"]


def test_mcp_implement_runs_real_supervisor_with_claude_write_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent implement from using read-only Claude flags or bypassing the real bridge envelope path."""
    commands: list[list[str]] = []
    marker = tmp_path / "implemented-marker.txt"
    peer_detail = "The fake provider's private implementation detail belongs only in the transcript."

    def fake_child(command: list[str], workspace: Path, timeout: float) -> bridge_call.ChildOutcome:
        commands.append(command)
        assert workspace == tmp_path.resolve()
        marker.write_text("implemented by fake Claude child\n", encoding="utf-8")
        return _claude_outcome(_core(files_touched=[marker.name], details=[peer_detail]))

    monkeypatch.setattr(bridge_call, "_run_child", fake_child)
    response = bridge_mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 18,
            "method": "tools/call",
            "params": {"name": "bridge_implement", "arguments": {"task": "Create a trusted marker."}},
        },
        trusted_workspace=tmp_path,
    )

    envelope = json.loads(response["result"]["content"][0]["text"])
    transcript = (tmp_path / envelope["transcript_path"]).read_text(encoding="utf-8")
    command = commands[0]
    assert response["result"]["isError"] is False
    assert marker.read_text(encoding="utf-8") == "implemented by fake Claude child\n"
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"
    assert "--disallowed-tools" not in command
    assert "Edit" not in command and "Write" not in command
    assert envelope["status"] == "complete"
    assert envelope["verb"] == "implement"
    assert envelope["direction"] == "codex_to_claude"
    assert envelope["files_touched"] == [marker.name]
    assert "details" not in envelope
    assert peer_detail in transcript
    assert peer_detail not in response["result"]["content"][0]["text"]


@pytest.mark.parametrize(
    "invalid_core",
    (
        _core(details=["detail"] * 33),
        _core(details=["x" * 2001]),
        _core(verdict="x" * 501),
        _core(findings=["finding"] * 9),
        _core(findings=["x" * 501]),
    ),
    ids=("too-many-details", "detail-too-long", "verdict-too-long", "too-many-findings", "finding-too-long"),
)
def test_peer_summary_limits_reject_oversized_model_output(invalid_core: dict[str, object]) -> None:
    """Prevent a peer from smuggling unbounded verbose or summary content across the bridge boundary."""
    with pytest.raises(ValueError):
        bridge_call.validate_model_core(invalid_core)


def test_mcp_stdio_returns_one_response_per_request_without_peer_cli(tmp_path: Path) -> None:
    """Prevent stdio framing regressions that corrupt a Codex MCP client's request stream."""
    messages = "\n".join(
        json.dumps(message)
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
    )
    result = subprocess.run(
        [sys.executable, str(BIN_ROOT / "bridge_mcp.py"), "--stdio"],
        input=messages + "\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert [response["id"] for response in responses] == [1, 2]
    assert set(item["name"] for item in responses[1]["result"]["tools"]) == set(bridge_mcp.TOOL_NAMES)


def test_mcp_stdio_malformed_tool_name_returns_invalid_params_and_keeps_serving(tmp_path: Path) -> None:
    """Prevent a malformed tool name from terminating the server before a later valid request."""
    messages = "\n".join(
        json.dumps(message)
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": [], "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
    )
    result = subprocess.run(
        [sys.executable, str(BIN_ROOT / "bridge_mcp.py"), "--stdio"],
        input=messages + "\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["error"]["code"] == -32602
    assert set(tool["name"] for tool in responses[1]["result"]["tools"]) == set(bridge_mcp.TOOL_NAMES)


def test_mcp_stdio_raw_nonfinite_timeout_returns_invalid_params_without_a_provider(tmp_path: Path) -> None:
    """Prevent a raw non-finite JSON timeout from reaching a provider child before a later request."""
    messages = "\n".join(
        (
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"bridge_advise","arguments":{"task":"Reject this malformed deadline.","timeout_seconds":NaN}}}',
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        )
    )
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path / "no-provider-bin")
    result = subprocess.run(
        [sys.executable, str(BIN_ROOT / "bridge_mcp.py"), "--stdio"],
        input=messages + "\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["error"]["code"] == -32602
    assert set(tool["name"] for tool in responses[1]["result"]["tools"]) == set(bridge_mcp.TOOL_NAMES)


def test_cli_invalid_input_has_one_json_error_and_nonzero_exit(tmp_path: Path) -> None:
    """Prevent skills from accepting a failed request as a successful JSON result."""
    result = subprocess.run(
        [
            sys.executable,
            str(BIN_ROOT / "bridge_call.py"),
            "advise",
            "--task",
            "Report completion.",
            "--effort",
            "not-a-level",
            "--workspace",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    lines = result.stdout.splitlines()
    assert result.returncode != 0
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "error"


def test_cli_rejects_negative_depth_before_dispatch(tmp_path: Path) -> None:
    """Prevent a caller from bypassing recursion accounting with a negative depth."""
    result = subprocess.run(
        [
            sys.executable,
            str(BIN_ROOT / "bridge_call.py"),
            "advise",
            "--task",
            "Report completion.",
            "--depth",
            "-1",
            "--workspace",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    lines = result.stdout.splitlines()
    assert result.returncode != 0
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"status": "error", "error": "--depth must be a non-negative integer"}


def test_trusted_inherited_depth_cannot_be_lowered_by_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a caller-provided zero from bypassing an inherited recursion refusal."""
    monkeypatch.setenv(bridge_call.DEPTH_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setattr(bridge_call, "_run_child", lambda *args: pytest.fail("refused call dispatched a child"))

    result = bridge_call.run_request(_request(tmp_path, depth=0))

    assert result["status"] == "refused"
    assert result["depth"] == 1
    assert result["blockers"] == ["recursion-depth"]


def test_child_receives_incremented_trusted_depth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a peer process from inheriting its parent's depth and permitting another hop."""
    environments: list[dict[str, str]] = []

    class Process:
        returncode = 0

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "", ""

    def fake_popen(command: list[str], **kwargs: object) -> Process:
        environments.append(kwargs["env"])
        return Process()

    monkeypatch.setenv(bridge_call.DEPTH_ENVIRONMENT_VARIABLE, "2")
    monkeypatch.setattr(bridge_call.subprocess, "Popen", fake_popen)

    bridge_call._run_child(["fake-peer"], tmp_path, timeout=1.0)

    assert environments == [{**os.environ, bridge_call.DEPTH_ENVIRONMENT_VARIABLE: "3"}]


def test_windows_child_launch_uses_a_new_process_group_without_posix_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent the portable Windows branch from passing POSIX-only process-launch options."""
    launches: list[dict[str, object]] = []

    class Process:
        returncode = 0

        def communicate(self, timeout: float) -> tuple[str, str]:
            return "", ""

    def fake_popen(command: list[str], **kwargs: object) -> Process:
        launches.append(kwargs)
        return Process()

    monkeypatch.setattr(bridge_call.os, "name", "nt")
    monkeypatch.setattr(bridge_call.subprocess, "CREATE_NEW_PROCESS_GROUP", 2468, raising=False)
    monkeypatch.setattr(bridge_call.subprocess, "Popen", fake_popen)

    outcome = bridge_call._run_child(["fake-peer"], tmp_path, timeout=1.0)

    assert outcome.returncode == 0
    assert launches[0]["creationflags"] == 2468
    assert "start_new_session" not in launches[0]


@pytest.mark.skipif(
    (os.name == "nt" and (shutil.which("taskkill") is None or shutil.which("tasklist") is None))
    or (os.name != "nt" and not hasattr(os, "killpg")),
    reason="requires native process-tree termination and liveness capabilities",
)
def test_cancelling_detached_supervisor_terminates_its_real_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent cancellation from leaving a detached peer child alive after its supervisor dies."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    child_pid_path = tmp_path / "child.pid"
    peer_script = fake_bin / "codex_peer.py"
    peer_script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path(os.environ['BRIDGE_TEST_CHILD_PID']).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
        newline="\n",
    )
    if os.name == "nt":
        fake_codex = fake_bin / "codex.cmd"
        fake_codex.write_text(f'@"{sys.executable}" "{peer_script}" %*\r\n', encoding="utf-8", newline="")
    else:
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            "#!" + sys.executable + "\n" + peer_script.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("BRIDGE_TEST_CHILD_PID", str(child_pid_path))

    job_id: str | None = None
    child_pid: int | None = None
    try:
        started = bridge_call.start_background(
            _request(tmp_path, verb="implement", background=True, timeout_seconds=30.0)
        )
        job_id = started["job_id"]
        deadline = time.monotonic() + 3.0
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_path.is_file(), "fake peer did not start its child"
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        bridge_call.cancel_job(tmp_path, job_id)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not _process_exists(child_pid):
                break
            time.sleep(0.02)
        else:
            pytest.fail("detached peer child survived supervisor cancellation")
    finally:
        if job_id is not None:
            bridge_call.cancel_job(tmp_path, job_id)
        if child_pid is not None and _process_exists(child_pid):
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(child_pid, bridge_call.signal.SIGKILL)


def test_posix_termination_falls_back_when_killpg_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent simulated Windows/minimal-POSIX hosts from crashing on a missing killpg API."""
    killed: list[bool] = []

    class Process:
        pid = 42

        def wait(self, timeout: float) -> None:
            raise subprocess.TimeoutExpired("fake", timeout)

        def kill(self) -> None:
            killed.append(True)

    monkeypatch.setattr(bridge_call.os, "name", "posix")
    monkeypatch.delattr(bridge_call.os, "killpg", raising=False)
    bridge_call._terminate_process_group(Process())

    assert killed == [True]


def test_windows_termination_uses_ctrl_break_then_tree_kill_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a failed Windows Ctrl-Break from leaving descendants behind."""
    sent: list[int] = []
    killed: list[bool] = []
    tree_kills: list[list[str]] = []
    monkeypatch.setattr(bridge_call.os, "name", "nt")
    monkeypatch.setattr(bridge_call.signal, "CTRL_BREAK_EVENT", 2468, raising=False)
    monkeypatch.setattr(
        bridge_call.subprocess,
        "run",
        lambda command, **kwargs: tree_kills.append(command) or subprocess.CompletedProcess(command, 0),
    )

    class Process:
        pid = 42

        def send_signal(self, signal_number: int) -> None:
            sent.append(signal_number)

        def wait(self, timeout: float) -> None:
            raise subprocess.TimeoutExpired("fake", timeout)

        def kill(self) -> None:
            killed.append(True)

    bridge_call._terminate_process_group(Process())

    assert sent == [2468]
    assert tree_kills == [["taskkill", "/PID", "42", "/T", "/F"]]
    assert killed == []


def test_windows_cancel_is_cooperative_without_posix_process_apis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent Windows cancellation from signalling a PID stored in a job record."""
    paths = bridge_call.BridgePaths(tmp_path.resolve())
    paths.prepare()
    job_id = "44444444-4444-4444-8444-444444444444"
    bridge_call._write_json(paths.jobs / f"{job_id}.json", {"job_id": job_id, "status": "running", "pid": 42})
    monkeypatch.setattr(bridge_call.os, "name", "nt")
    monkeypatch.setattr(bridge_call, "_process_exists", lambda pid: True)
    monkeypatch.setattr(
        bridge_call.os, "kill", lambda *args: pytest.fail("Windows cancellation signalled a PID"), raising=False
    )
    monkeypatch.setattr(
        bridge_call.os, "killpg", lambda *args: pytest.fail("Windows cancellation used killpg"), raising=False
    )

    cancelled = bridge_call.cancel_job(tmp_path, job_id)

    assert cancelled["status"] == "cancel_requested"
    assert bridge_call.job_status(tmp_path, job_id)["status"] == "cancel_requested"


def test_windows_cancel_never_uses_taskkill_for_a_persisted_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent a stale Windows record from escalating cooperative cancellation into tree termination."""
    paths = bridge_call.BridgePaths(tmp_path.resolve())
    paths.prepare()
    job_id = "55555555-5555-4555-8555-555555555555"
    bridge_call._write_json(paths.jobs / f"{job_id}.json", {"job_id": job_id, "status": "running", "pid": 42})

    def fail_on_taskkill(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "taskkill":
            pytest.fail("taskkill was run")
        return subprocess.CompletedProcess(command, 0, stdout='"codex.exe","42"', stderr="")

    monkeypatch.setattr(bridge_call.os, "name", "nt")
    monkeypatch.setattr(bridge_call.subprocess, "run", fail_on_taskkill)

    cancelled = bridge_call.cancel_job(tmp_path, job_id)

    assert cancelled["status"] == "cancel_requested"
