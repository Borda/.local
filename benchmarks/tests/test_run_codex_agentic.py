"""No-model contracts for the shared Codex agentic study."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
AGENTIC_TASK_IDS = tuple(f"BA-{number:02d}" for number in range(1, 17))
AGENTIC_ARMS = ("A_plain", "B_auto", "C_required")


def _load_agentic() -> Any:
    """Load the hyphenated Codex agentic runner as an importable test module."""
    module_name = "run_codex_agentic"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    path = BENCHMARKS_DIR / "run-codex-agentic.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agentic() -> Any:
    """Expose the no-model Codex agentic runner."""
    return _load_agentic()


@pytest.fixture()
def task_and_truth(agentic: Any, tmp_path: Path) -> tuple[Any, Any]:
    """Build a two-importer source tree and provider-neutral answer oracle."""
    task = {
        "id": "BA-01",
        "type": "blast_radius_analysis",
        "prompt": "List importers.",
        "primary_module": "lightning.pytorch.callbacks.timer",
        "answer_contract": {
            "fields": ["production_importers", "rdep_counts", "ranking"],
            "params": {"ranking": {"candidate_set": "production_importers", "top_k": 1}},
        },
    }
    for relative, source in {
        "lightning/pytorch/callbacks/timer.py": "",
        "lightning/pytorch/trainer/trainer.py": "import lightning.pytorch.callbacks.timer\n",
        "lightning/pytorch/loops/fit_loop.py": "import lightning.pytorch.callbacks.timer\n",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return task, agentic.build_oracle(task, tmp_path)


def _stream(*events: dict[str, Any]) -> str:
    """Serialize native Codex events as one JSONL stream."""
    return "\n".join(json.dumps(event) for event in events)


def _message(text: str) -> dict[str, Any]:
    """Return one completed native assistant message event."""
    return {"type": "item.completed", "item": {"id": "m", "type": "agent_message", "text": text}}


def _labelled(text: str, oracle: Any) -> str:
    """Attach one exact shared answer-contract envelope to test report prose."""
    return f"{text}\nBEGIN_ANSWER_JSON\n{json.dumps(dict(oracle.expected), sort_keys=True)}\nEND_ANSWER_JSON"


def _completed() -> dict[str, Any]:
    """Return a successful terminal event with deterministic native usage."""
    return {
        "type": "turn.completed",
        "status": "completed",
        "usage": {"input_tokens": 123, "cached_input_tokens": 23, "output_tokens": 45},
    }


def _query(item_id: str = "q") -> dict[str, Any]:
    """Return one successful compact direct Codemap query event."""
    return {
        "type": "item.completed",
        "item": {
            "id": item_id,
            "type": "command_execution",
            "command": "$CODEMAP_BIN query --compact rdeps lightning.pytorch.callbacks.timer",
            "status": "completed",
            "exit_code": 0,
            "aggregated_output": json.dumps({"index": {"query_complete": True, "compact": True}}),
        },
    }


def test_dry_run_has_three_probes_and_default_shared_coordinates(agentic: Any) -> None:
    """The default dry run exposes all shared tasks once in every canonical arm."""
    rows = agentic.dry_run()
    probes = [row for row in rows if row.startswith("PROBE")]
    plan = [row for row in rows if row.startswith("PLAN")]

    assert len(probes) == 3
    assert len(plan) == len(AGENTIC_TASK_IDS) * len(AGENTIC_ARMS)
    assert plan[0] == "PLAN    BA-01  rep=1  A_plain"
    assert plan[-1] == "PLAN    BA-16  rep=1  C_required"


def test_dry_run_default_coordinates_equal_the_shared_16_task_scope(agentic: Any) -> None:
    """The default no-model plan schedules each shared parity coordinate once.

    Prevents a runner that advertises parity while retaining the BA-01 pilot,
    omitting an arm, duplicating a coordinate, or using a hidden default repeat.
    A mere plan-length assertion could miss swapped or repeated coordinates, so
    this compares the complete coordinate set.
    """
    rows = agentic.dry_run()
    actual = {
        (parts[1], int(parts[2].removeprefix("rep=")), parts[3])
        for row in rows
        if row.startswith("PLAN")
        for parts in [row.split()]
    }
    expected = {
        (task_id, repetition, arm) for task_id in AGENTIC_TASK_IDS for repetition in (1,) for arm in AGENTIC_ARMS
    }

    assert actual == expected
    assert sum(row.startswith("PLAN") for row in rows) == len(expected)


def test_dry_run_accepts_a_positive_explicit_repeat_override(agentic: Any) -> None:
    """A caller can request an admitted repeat count without changing the task scope.

    Prevents the former fixed-three-repeat pilot behavior and a runner that
    silently ignores an explicit repeat request. Zero remains invalid because it
    would create no evidence-bearing parity coordinates.
    """
    rows = agentic.dry_run(repetitions=2)
    plan = [row.split() for row in rows if row.startswith("PLAN")]

    assert len(plan) == len(AGENTIC_TASK_IDS) * len(AGENTIC_ARMS) * 2
    assert {parts[1] for parts in plan} == set(AGENTIC_TASK_IDS)
    assert {parts[2] for parts in plan} == {"rep=1", "rep=2"}
    assert {parts[3] for parts in plan} == set(AGENTIC_ARMS)
    with pytest.raises(ValueError, match="positive|at least 1"):
        agentic.dry_run(repetitions=0)


def test_agentic_output_legend_uses_shared_renderer_contract(agentic: Any) -> None:
    """Agentic output declares its treatments and metrics in one shared-renderer block."""
    legend = agentic._OUTPUT_LEGEND
    assert legend.startswith("LEGEND\n")
    assert legend.endswith("END LEGEND")
    assert legend.count("LEGEND") == 2
    assert "treatments: A_plain=no Codemap, B_auto=CLI available and optional, C_required=Codemap Skill read" in legend
    assert "SCORE: mean answer-contract component score" in legend
    assert "correct: ✓ every declared answer field is correct" in legend


@pytest.mark.parametrize(
    ("arm", "native_arm", "available"),
    [
        pytest.param("A_plain", "A_plain", False, id="plain"),
        pytest.param("B_auto", "B_direct_required", True, id="optional-direct-home"),
        pytest.param("C_required", "C_skill_required", True, id="required-skill-home"),
    ],
)
def test_isolated_home_adapter_uses_existing_structural_isolation(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, arm: str, native_arm: str, available: bool
) -> None:
    """The agentic slice maps its semantic arms to the established disposable homes."""
    calls: list[str] = []
    home = object()
    monkeypatch.setattr(
        agentic._structural,
        "prepare_arm_home",
        lambda selected_arm, **_kwargs: calls.append(selected_arm) or home,
    )
    monkeypatch.setattr(agentic._structural, "probe_arm_home", lambda _home: {"codemap_available": available})

    assert agentic.prepare_isolated_home(arm) is home
    assert calls == [native_arm]
    assert agentic.probe_isolated_home(home, arm) == {"codemap_available": available}


def test_clean_plain_stream_is_scored_without_codemap(task_and_truth: tuple[Any, Any], agentic: Any) -> None:
    """A_plain remains valid when its output names both expected importers without Codemap."""
    task, truth = task_and_truth
    text = "lightning.pytorch.trainer.trainer and lightning.pytorch.loops.fit_loop import the timer module."
    result = agentic.parse_agentic_stream(
        _stream(_message(_labelled(text, truth)), _completed()), arm="A_plain", task=task, ground_truth=truth
    )

    assert result.success is True
    assert result.codemap_used is False
    assert result.treatment_adherence is True
    assert result.input_tokens == 123
    assert result.cached_input_tokens == 23
    assert result.output_tokens == 45


def test_auto_direct_query_is_valid_but_not_required(task_and_truth: tuple[Any, Any], agentic: Any) -> None:
    """B_auto records an optional successful direct query and stays adherent."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(
        _stream(
            _query(),
            _message(_labelled("lightning.pytorch.trainer.trainer and lightning.pytorch.loops.fit_loop.", truth)),
            _completed(),
        ),
        arm="B_auto",
        task=task,
        ground_truth=truth,
    )

    assert result.success is True
    assert result.codemap_used is True
    assert result.compliance is None
    assert result.treatment_adherence is True
    assert result.command_calls == 1


def test_auto_no_call_is_valid(task_and_truth: tuple[Any, Any], agentic: Any) -> None:
    """B_auto preserves the Claude contract: not using Codemap is still valid."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(
        _stream(_message(_labelled("lightning.pytorch.trainer.trainer.", truth)), _completed()),
        arm="B_auto",
        task=task,
        ground_truth=truth,
    )

    assert result.success is True
    assert result.codemap_used is False
    assert result.treatment_adherence is True


def test_required_skill_read_precedes_compact_query(
    task_and_truth: tuple[Any, Any], agentic: Any, tmp_path: Path
) -> None:
    """C_required credits only an exact installed Skill read before a compact query."""
    task, truth = task_and_truth
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("# locked Codemap skill\n", encoding="utf-8")
    skill_read = {
        "type": "item.completed",
        "item": {
            "id": "skill",
            "type": "command_execution",
            "command": 'cat "$CODEMAP_SKILL_FILE"',
            "status": "completed",
            "exit_code": 0,
            "aggregated_output": skill_path.read_text(encoding="utf-8"),
        },
    }
    result = agentic.parse_agentic_stream(
        _stream(
            skill_read,
            _query(),
            _message(_labelled("lightning.pytorch.trainer.trainer and lightning.pytorch.loops.fit_loop.", truth)),
            _completed(),
        ),
        arm="C_required",
        task=task,
        ground_truth=truth,
        skill_path=skill_path,
    )

    assert result.success is True
    assert result.codemap_used is True
    assert result.compliance is True
    assert result.treatment_adherence is True


def test_plain_codemap_call_is_contamination(task_and_truth: tuple[Any, Any], agentic: Any) -> None:
    """A_plain keeps successful provider telemetry but fails treatment adherence on leakage."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(
        _stream(_query(), _message(_labelled("lightning.pytorch.trainer.trainer.", truth)), _completed()),
        arm="A_plain",
        task=task,
        ground_truth=truth,
    )

    assert result.success is True
    assert result.contaminated is True
    assert result.treatment_adherence is False


def _admitted_manifest(agentic: Any, tmp_path: Path) -> tuple[Path, str]:
    """Copy the checked-in agentic lock and admit it for mocked paid-path tests."""
    manifest = json.loads(agentic._MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["admission"]["paid_execution"] = "admitted"
    manifest["preregistered_scope"]["complete_run_max_wall_clock_seconds"] = 28800
    manifest["artifact_sha256"]["codex_agentic_runner"] = hashlib.sha256(
        Path(agentic.__file__).read_bytes()
    ).hexdigest()
    manifest["artifact_sha256"]["run_all"] = "a" * 64
    path = tmp_path / "codex-agentic.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_paid_admission_requires_exact_hash_and_admitted_manifest(agentic: Any, tmp_path: Path) -> None:
    """Paid execution rejects stale approval and an explicitly unadmitted study manifest."""
    manifest_path, approved_hash = _admitted_manifest(agentic, tmp_path)

    assert agentic.validate_paid_admission(manifest_path, approved_hash)["admission"]["paid_execution"] == "admitted"
    with pytest.raises(ValueError, match="exact current manifest"):
        agentic.validate_paid_admission(manifest_path, "0" * 64)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["admission"]["paid_execution"] = "not_admitted"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="does not admit"):
        agentic.validate_paid_admission(manifest_path, hashlib.sha256(manifest_path.read_bytes()).hexdigest())


class _FixtureRunner:
    """No-auth, no-model runner proving paid artifact persistence contracts."""

    def __init__(self, *, fail_after: int | None = None, **_kwargs: Any) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def close(self) -> None:
        """Match the production runner cleanup protocol."""

    def run(self, task: Any, arm: str, *, repetition: int, **_kwargs: Any) -> Any:
        """Return a completed scored row or inject a deterministic interruption."""
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("fixture interruption")
        compliant = None if arm != "C_required" else False
        return _load_agentic().AgenticRun(
            arm=arm,
            task_id=task["id"],
            repetition=repetition,
            success=True,
            input_tokens=10,
            cached_input_tokens=0,
            output_tokens=2,
            command_calls=0,
            codemap_calls=0,
            codemap_successful_calls=0,
            codemap_used=False,
            compliance=compliant,
            treatment_adherence=arm != "C_required",
            contaminated=False,
            incomplete=False,
            malformed_lines=0,
            error="",
            error_type="",
            output_text="",
            report_text="",
            quality=None,
            raw_events=[],
        )


class _SnapshotFailureRunner(_FixtureRunner):
    """Fixture that fails while writing pre-cell immutable inputs."""

    def create_input_snapshot(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        """Exercise durable failure handling before a coordinate starts."""
        raise RuntimeError("fixture snapshot interruption")


def _prepare_paid_fixture(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str, Path, Path]:
    """Set up a valid manifest and local index while bypassing target Git checks."""
    manifest_path, _approval = _admitted_manifest(agentic, tmp_path)
    launcher_path = tmp_path / "run-all.sh"
    launcher_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"]["run_all"] = hashlib.sha256(launcher_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    approval = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"modules": []}), encoding="utf-8")
    monkeypatch.setattr(agentic, "_validate_agentic_runtime", lambda *_args: None)
    return manifest_path, approval, index_path, launcher_path


def _lock_run_launcher(manifest_path: Path, run_dir: Path) -> tuple[str, Path]:
    """Create run-all's sole permitted pre-dispatch artifact and lock its bytes."""
    launcher_path = run_dir / ".launcher" / "run-all.sh"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"]["run_all"] = hashlib.sha256(launcher_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest(), launcher_path


def test_paid_run_persists_full_scope_and_noncompliant_c_row(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Paid orchestration retains C no-call evidence while marking it treatment-ineligible."""
    manifest_path, _approval, index_path, _launcher_path = _prepare_paid_fixture(agentic, monkeypatch, tmp_path)
    run_dir = tmp_path / "result"
    approval, launcher_path = _lock_run_launcher(manifest_path, run_dir)

    agentic.run_paid(
        repo_path=tmp_path,
        index_path=index_path,
        auth_source=tmp_path / "auth-not-read.json",
        approval_sha256=approval,
        run_dir=run_dir,
        manifest_path=manifest_path,
        runner_factory=_FixtureRunner,
        invocation_launcher_path=launcher_path,
    )

    rows = [json.loads(line) for line in (run_dir / "telemetry.jsonl").read_text().splitlines()]
    metadata = json.loads((run_dir / "run-metadata.json").read_text())
    assert len(rows) == 48
    assert metadata["status"] == "completed"
    assert rows[-1]["arm"] == "C_required"
    assert rows[-1]["treatment_adherence"] is False
    assert (run_dir / "telemetry-canonical.jsonl").is_file()
    assert (run_dir / "checksums.sha256").is_file()
    output = capsys.readouterr().out
    assert "(1/48) ✓  BA-01" in output
    assert "SCORE=n/a" in output
    assert "SUMMARY  status=completed  persisted_cells=48/48" in output
    run_log = (run_dir / "run.log").read_text(encoding="utf-8")
    assert run_log == output


def test_paid_run_preserves_partial_artifacts_on_failure(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A later runner failure cannot erase previously appended agentic evidence."""
    manifest_path, _approval, index_path, _launcher_path = _prepare_paid_fixture(agentic, monkeypatch, tmp_path)
    run_dir = tmp_path / "partial"
    approval, launcher_path = _lock_run_launcher(manifest_path, run_dir)

    with pytest.raises(RuntimeError, match="fixture interruption"):
        agentic.run_paid(
            repo_path=tmp_path,
            index_path=index_path,
            auth_source=tmp_path / "auth-not-read.json",
            approval_sha256=approval,
            run_dir=run_dir,
            manifest_path=manifest_path,
            runner_factory=lambda **kwargs: _FixtureRunner(fail_after=1, **kwargs),
            invocation_launcher_path=launcher_path,
        )

    assert len((run_dir / "telemetry.jsonl").read_text().splitlines()) == 1
    assert json.loads((run_dir / "run-metadata.json").read_text())["status"] == "failed"
    assert (run_dir / "checksums.sha256").is_file()


@pytest.mark.parametrize(
    ("runner_factory", "error"),
    [
        pytest.param(
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture factory interruption")),
            "fixture factory interruption",
            id="factory-initialization",
        ),
        pytest.param(_SnapshotFailureRunner, "fixture snapshot interruption", id="snapshot-initialization"),
    ],
)
def test_paid_run_persists_failed_artifact_when_initialization_fails(
    agentic: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner_factory: Any,
    error: str,
) -> None:
    """Runner and snapshot initialization failures leave a complete failed artifact."""
    manifest_path, _approval, index_path, _launcher_path = _prepare_paid_fixture(agentic, monkeypatch, tmp_path)
    run_dir = tmp_path / "initialization-failure"
    approval, launcher_path = _lock_run_launcher(manifest_path, run_dir)

    with pytest.raises(RuntimeError, match=error):
        agentic.run_paid(
            repo_path=tmp_path,
            index_path=index_path,
            auth_source=tmp_path / "auth-not-read.json",
            approval_sha256=approval,
            run_dir=run_dir,
            manifest_path=manifest_path,
            runner_factory=runner_factory,
            invocation_launcher_path=launcher_path,
        )

    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["persisted_cells"] == 0
    assert (run_dir / "telemetry.jsonl").read_text(encoding="utf-8") == ""
    assert "SUMMARY  status=failed  persisted_cells=0/48" in (run_dir / "run.log").read_text(encoding="utf-8")
    assert (run_dir / "checksums.sha256").is_file()


def test_paid_run_rejects_changed_or_unlocked_launcher(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A paid invocation cannot proceed when its launcher differs from the agentic lock."""
    manifest_path, _approval, index_path, _launcher_path = _prepare_paid_fixture(agentic, monkeypatch, tmp_path)
    run_dir = tmp_path / "launcher-rejected"
    approval, launcher_path = _lock_run_launcher(manifest_path, run_dir)
    launcher_path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invocation launcher changed"):
        agentic.run_paid(
            repo_path=tmp_path,
            index_path=index_path,
            auth_source=tmp_path / "auth-not-read.json",
            approval_sha256=approval,
            run_dir=run_dir,
            manifest_path=manifest_path,
            runner_factory=_FixtureRunner,
            invocation_launcher_path=launcher_path,
        )


@pytest.mark.parametrize(
    ("kind", "artifact_name", "accepted"),
    [
        pytest.param("new", None, False, id="new-directory-without-launcher"),
        pytest.param("launcher", None, True, id="run-all-launcher-only-directory"),
        pytest.param("artifact", "telemetry.jsonl", False, id="reused-telemetry-artifact-directory"),
        pytest.param("artifact", ".agentic-console.log", False, id="reused-agentic-console-artifact-directory"),
    ],
)
def test_run_directory_admission_allows_only_locked_launcher_snapshot(
    agentic: Any, tmp_path: Path, kind: str, artifact_name: str | None, accepted: bool
) -> None:
    """Run-all may pre-create only its locked launcher snapshot; all other reuse is rejected."""
    run_dir = tmp_path / kind
    launcher = tmp_path / "launcher.sh"
    launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
    if kind == "launcher":
        launcher = run_dir / ".launcher" / "run-all.sh"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
    elif kind == "artifact":
        run_dir.mkdir()
        assert artifact_name is not None
        (run_dir / artifact_name).write_text("old evidence\n", encoding="utf-8")

    if accepted:
        agentic._admit_run_directory(run_dir, launcher, launcher_hash)
        assert run_dir.is_dir()
    else:
        with pytest.raises(FileExistsError):
            agentic._admit_run_directory(run_dir, launcher, launcher_hash)


def test_agentic_snapshot_records_its_own_runner_identity(agentic: Any, tmp_path: Path) -> None:
    """Agentic bytes are archived under their real name, role, and immutable hash."""
    runner_path = Path(agentic.__file__)
    payload = agentic._write_agentic_input_snapshot(
        tmp_path / "inputs",
        manifest_path=agentic._MANIFEST_PATH,
        tasks_path=agentic._TASKS_PATH,
        runner_path=runner_path,
        invocation_launcher_path=BENCHMARKS_DIR / "run-all.sh",
        index_path=agentic._MANIFEST_PATH,
        auth_source=None,
        arm_archives={},
        arm_files={},
    )

    runner_entries = [entry for entry in payload["files"] if entry["role"] == "agentic_runner"]
    assert runner_entries == [
        {
            "role": "agentic_runner",
            "archived_path": "shared/run-codex-agentic.py",
            "sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
            "bytes": runner_path.stat().st_size,
        }
    ]
    assert not (tmp_path / "inputs" / "shared" / "run-codex-structural.py").exists()


def test_agentic_snapshot_attempts_every_cleanup_after_auth_refresh_failure(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot refresh failure cannot skip coordination or disposable-home cleanup."""
    events: list[str] = []

    class Home:
        """Minimal verified-home seam with identifiable independent cleanup steps."""

        auth_provisioned = True
        codemap_plugin_path = tmp_path / "codemap"
        codex_rig_path = tmp_path / "codex-rig"
        codemap_context_path = None

        def __init__(self, arm: str) -> None:
            self.arm = arm
            self.path = tmp_path / arm
            self.coordination_path = tmp_path / f"coordination-{arm}"

        def cleanup(self) -> None:
            events.append(f"home:{self.arm}")

    class Adapter:
        """Snapshot adapter whose refresh fails after every disposable home."""

        auth_source = None

        class AuthState:
            """Fail refresh so the cleanup sequence must continue."""

            def refresh_from_home(self, path: Path) -> None:
                events.append(f"refresh:{path.name}")
                raise RuntimeError("refresh failed")

        _auth_state = AuthState()

        def _prepare_verified_home(self, native_arm: str) -> Home:
            return Home(native_arm)

    runner = object.__new__(agentic.AgenticCodexRunner)
    runner.adapter = Adapter()
    runner.index_path = tmp_path / "index.json"
    monkeypatch.setattr(agentic, "_write_agentic_input_snapshot", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        agentic._structural,
        "_cleanup_coordination_root",
        lambda path: events.append(f"coordination:{path.name}"),
    )

    with pytest.raises(RuntimeError, match="refresh failed"):
        runner.create_input_snapshot(
            tmp_path / "run",
            manifest_path=agentic._MANIFEST_PATH,
            invocation_launcher_path=BENCHMARKS_DIR / "run-all.sh",
        )

    assert events == [
        "refresh:A_plain",
        "coordination:coordination-A_plain",
        "home:A_plain",
        "refresh:B_direct_required",
        "coordination:coordination-B_direct_required",
        "home:B_direct_required",
        "refresh:C_skill_required",
        "coordination:coordination-C_skill_required",
        "home:C_skill_required",
    ]


def test_agentic_snapshot_cleans_a_shared_treatment_coordination_root_once(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B/C snapshot homes share one index-local coordination root safely."""
    events: list[str] = []
    shared_root = tmp_path / ".index-rw"
    live_roots = {shared_root}

    class Home:
        """Minimal snapshot home with one shared B/C coordination path."""

        auth_provisioned = False
        codemap_plugin_path = tmp_path / "codemap"
        codex_rig_path = tmp_path / "codex-rig"
        codemap_context_path = None

        def __init__(self, arm: str) -> None:
            self.arm = arm
            self.path = tmp_path / arm
            self.coordination_path = shared_root if arm != "A_plain" else None

        def cleanup(self) -> None:
            events.append(f"home:{self.arm}")

    class Adapter:
        """Provide the three canonical homes without credential state."""

        auth_source = None
        _auth_state = None

        def _prepare_verified_home(self, native_arm: str) -> Home:
            return Home(native_arm)

    def cleanup(path: Path) -> None:
        events.append(f"coordination:{path.name}")
        if path not in live_roots:
            raise ValueError("Codemap coordination root is unavailable")
        live_roots.remove(path)

    runner = object.__new__(agentic.AgenticCodexRunner)
    runner.adapter = Adapter()
    runner.index_path = tmp_path / "index.json"
    monkeypatch.setattr(agentic, "_write_agentic_input_snapshot", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(agentic._structural, "_cleanup_coordination_root", cleanup)

    assert runner.create_input_snapshot(
        tmp_path / "run",
        manifest_path=agentic._MANIFEST_PATH,
        invocation_launcher_path=BENCHMARKS_DIR / "run-all.sh",
    ) == {"ok": True}
    assert events == [
        "home:A_plain",
        "coordination:.index-rw",
        "home:B_direct_required",
        "home:C_skill_required",
    ]


def test_native_runner_refreshes_auth_and_fails_postflight_contamination(
    agentic: Any, monkeypatch: pytest.MonkeyPatch, task_and_truth: tuple[Any, Any], tmp_path: Path
) -> None:
    """Native cells propagate refreshed auth and turn postflight drift into an ineligible row."""
    task, truth = task_and_truth
    refreshes: list[Path] = []

    class Home:
        """Minimal disposable home compatible with the native runner seam."""

        auth_provisioned = True
        coordination_path = None
        codemap_skill_path = None

        def __init__(self) -> None:
            self.cleaned = False
            self.env = {}
            self.path = tmp_path / "home"

        def cleanup(self) -> None:
            self.cleaned = True

    home = Home()

    class Adapter:
        """Native transport seam with a refreshable private auth state."""

        class AuthState:
            """Record whether cleanup transfers refreshed auth out of the disposable home."""

            def refresh_from_home(self, path: Path) -> None:
                refreshes.append(path)

        _auth_state = AuthState()

        def _prepare_verified_home(self, _arm: str) -> Home:
            return home

        def build_command(self, _prompt: str) -> list[str]:
            return ["codex", "exec"]

        def _subprocess(self, _command: list[str], _env: dict[str, str], *, timeout: float) -> str:
            del timeout
            return _stream(_message(_labelled("lightning.pytorch.trainer.trainer.", truth)), _completed())

        def close(self) -> None:
            return None

    runner = object.__new__(agentic.AgenticCodexRunner)
    runner.repo_path = tmp_path
    runner.index_path = tmp_path / "index.json"
    runner.agentic_manifest = {}
    runner.transport = None
    runner.adapter = Adapter()
    monkeypatch.setattr(agentic, "_validate_agentic_runtime", lambda *_args: None)
    successful = runner.run(task, "A_plain", repetition=1, oracle=truth, deadline=10**12)
    assert successful.success is True
    assert refreshes == [home.path]

    def contaminated(*_args: Any) -> None:
        raise ValueError("locked index bytes changed")

    monkeypatch.setattr(agentic, "_validate_agentic_runtime", contaminated)
    failed = runner.run(task, "A_plain", repetition=1, ground_truth=truth, deadline=10**12)
    assert failed.success is False
    assert failed.incomplete is True
    assert failed.error_type == "runtime_contamination"


@pytest.mark.parametrize(
    ("stream", "error_type"),
    [
        pytest.param("{\n" + _stream(_completed()), "malformed_stream", id="malformed"),
        pytest.param(_stream({"type": "turn.failed", "error": "transport failed"}), "turn_failed", id="failed"),
        pytest.param(_stream(_message("unfinished")), "missing_terminal", id="incomplete"),
    ],
)
def test_malformed_incomplete_and_error_streams_fail_closed(
    task_and_truth: tuple[Any, Any], agentic: Any, stream: str, error_type: str
) -> None:
    """Malformed, incomplete, and provider-error native streams cannot become successful rows."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(stream, arm="A_plain", task=task, ground_truth=truth)

    assert result.success is False
    assert result.incomplete is True
    assert result.error_type == error_type


@pytest.mark.parametrize(
    "answer_text",
    [
        pytest.param("Final answer without the required envelope.", id="missing-envelope"),
        pytest.param("BEGIN_ANSWER_JSON\n{not-json}\nEND_ANSWER_JSON", id="invalid-json"),
    ],
)
def test_completed_invalid_answer_is_scored_zero_without_becoming_transport_failure(
    task_and_truth: tuple[Any, Any], agentic: Any, answer_text: str, tmp_path: Path
) -> None:
    """A completed native turn with an invalid answer remains complete and receives zero quality."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(
        _stream(_message(answer_text), _completed()), arm="A_plain", task=task, ground_truth=truth
    )

    assert result.success is True
    assert result.incomplete is False
    assert result.error_type == "answer_contract_failed"
    assert result.error
    assert result.answer_error == result.error
    assert result.quality.scored is True
    assert result.quality.quality_score == 0.0
    assert result.quality.correct is False
    assert set(result.quality.components) == set(truth.fields)
    assert all(component == 0.0 for component in result.quality.components.values())
    assert result.quality.erec == 0.0
    assert result.quality.rrec == 0.0
    assert result.quality.deff == 0.0
    assert "SCORE=0.000" in agentic._progress_line(1, 1, result)

    telemetry_path = tmp_path / "telemetry.jsonl"
    agentic._append_telemetry(telemetry_path, result, execution_index=1)
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert telemetry["success"] is True
    assert telemetry["answer_error"] == result.answer_error
    assert telemetry["quality"]["quality_score"] == 0.0


def test_required_no_call_preserves_scored_row_but_fails_admission(
    task_and_truth: tuple[Any, Any], agentic: Any, tmp_path: Path
) -> None:
    """C_required no-call evidence is retained for diagnosis rather than dropped from telemetry."""
    task, truth = task_and_truth
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("# locked Codemap skill\n", encoding="utf-8")
    result = agentic.parse_agentic_stream(
        _stream(
            _message(_labelled("lightning.pytorch.trainer.trainer and lightning.pytorch.loops.fit_loop.", truth)),
            _completed(),
        ),
        arm="C_required",
        task=task,
        ground_truth=truth,
        skill_path=skill_path,
    )

    assert result.success is True
    assert result.quality.scored is True
    assert result.compliance is False
    assert result.treatment_adherence is False


def test_identical_output_uses_shared_answer_contract_score_and_legacy_metrics(
    task_and_truth: tuple[Any, Any], agentic: Any
) -> None:
    """Codex uses the exact shared scorer rather than a second quality implementation."""
    task, truth = task_and_truth
    text = "lightning.pytorch.trainer.trainer and lightning.pytorch.loops.fit_loop import the timer module."
    result = agentic.parse_agentic_stream(
        _stream(_message(_labelled(text, truth)), _completed()), arm="A_plain", task=task, ground_truth=truth
    )
    report = _labelled(text, truth)
    expected = agentic.score_answer(
        truth,
        agentic.parse_labeled_answer(task, report),
        exposure_text=report,
        report_text=report,
        tool_calls=0,
    )

    assert result.quality.erec == expected.erec
    assert result.quality.rrec == expected.rrec
    assert result.quality.deff == expected.deff
    assert result.quality.quality_score == expected.quality_score


def test_report_recall_uses_only_text_after_the_last_tool(task_and_truth: tuple[Any, Any], agentic: Any) -> None:
    """RREC excludes exploratory prose emitted before the final tool call."""
    task, truth = task_and_truth
    result = agentic.parse_agentic_stream(
        _stream(
            _message("lightning.pytorch.trainer.trainer is one candidate."),
            _query(),
            _message(_labelled("Final: lightning.pytorch.loops.fit_loop.", truth)),
            _completed(),
        ),
        arm="B_auto",
        task=task,
        ground_truth=truth,
    )

    assert result.quality.erec == 1.0
    assert result.quality.rrec == 1.0
    assert result.report_text.startswith("Final: lightning.pytorch.loops.fit_loop.")
