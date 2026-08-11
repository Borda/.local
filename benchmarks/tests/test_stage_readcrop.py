"""No-model contract tests for the Codex read-crop adapter."""

from __future__ import annotations

import hashlib
import inspect
import io
import json
from pathlib import Path
import sys
from typing import Any
from types import SimpleNamespace

import pytest


BENCHMARKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARKS))


def _load() -> Any:
    """Return the private ReadCrop stage scorer without a Fire entrypoint."""
    from _bench_codex import stage_readcrop

    return stage_readcrop


def test_readcrop_prompt_keeps_answer_contract_shared_and_arm_availability_separate() -> None:
    """Arm supplements cannot alter the strict source-answer schema."""
    runner = _load()
    task = {"prompt": "Describe Example.method.", "symbol": "Example.method"}

    plain = runner.readcrop_prompt("A_plain", task)
    strict = runner.readcrop_prompt("C_strict", task)

    assert "BEGIN_READ_CROP_JSON" in plain
    assert "BEGIN_READ_CROP_JSON" in strict
    assert "Codemap is absent" in plain
    assert 'cat "$CODEMAP_SKILL_FILE"' not in strict
    assert "installed $codemap-py:query-code Skill is available" in strict
    assert '"$CODEMAP_BIN" query --compact symbol Example.method' in strict
    assert "frozen static source-graph query tool" in strict
    assert "frozen static source-graph query tool" in runner.readcrop_prompt("B_auto", task)
    assert '"behavior":"non-empty contract summary"' in strict
    assert "every exact source parameter name" in strict
    focused = runner.readcrop_prompt(
        "A_plain",
        {**task, "required_parameters": ["value"]},
    )
    assert "each exact required source parameter name" in focused


def test_readcrop_parser_preserves_answer_and_redacted_event_evidence() -> None:
    """A failed calibration remains diagnosable without a second paid call."""
    runner = _load()
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "primary_module": "package.module",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = runner.build_readcrop_contract(task, source="def method(self, value: int) -> None:\n    pass\n")
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    stream = "\n".join(
        (
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}),
            json.dumps({"type": "turn.completed", "status": "completed"}),
        )
    )

    row = runner.parse_readcrop_stream(stream, arm="A_plain", contract=contract, skill_path=None)
    auto_row = runner.parse_readcrop_stream(stream, arm="B_auto", contract=contract, skill_path=None)

    assert row["success"] is True
    assert row["behavior_fact_recall"] is None
    assert row["behavior_facts_correct"] is None
    assert row["compliance"] is True
    assert row["output_text"] == answer
    assert row["raw_events"]
    assert len(row["raw_events_sha256"]) == 64
    assert auto_row["compliance"] is True


def test_result_row_reports_progress_and_cell_state() -> None:
    """Paid runs expose persisted results instead of ending with a bare path."""
    runner = _load()
    row = {
        "success": True,
        "task_id": "RC-01",
        "arm": "C_strict",
        "input_tokens": 101_400,
        "output_tokens": 2_020,
        "command_calls": 3,
        "elapsed_s": 62.5,
        "primary_correct": True,
        "quality_score": 1.0,
        "codemap_used": True,
        "compliance": True,
    }

    assert runner.format_result_row(row, completed=2, total=6) == (
        "(2/6) ✓  RC-01  C_strict  in=101.4k out= 2.0k cmd= 3 time= 1m2s quality=1.000 correct=✓ codemap=✓"
    )


def test_emit_progress_delegates_paid_rows_to_shared_arm_renderer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ReadCrop rows keep the structural renderer's interactive arm colors."""
    runner = _load()
    rendered: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.runtime, "print_arm_row", lambda row, arm: rendered.append((row, arm)))

    runner.emit_progress(tmp_path / "run.log", "(1/3) ✓  RC-01  C_strict", arm="C_strict")

    assert rendered == [("(1/3) ✓  RC-01  C_strict", "C_strict")]
    assert (tmp_path / "run.log").read_text(encoding="utf-8") == "(1/3) ✓  RC-01  C_strict\n"


def test_emit_progress_keeps_native_log_while_terminal_uses_aggregate_counter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unified presentation cannot mutate ReadCrop's stage-native run log."""
    runner = _load()
    run_log = tmp_path / "run.log"

    with runner.runtime.progress_scope(completed_offset=3, total_cells=12):
        runner.emit_progress(run_log, "(1/3) ✓  RC-01  C_strict", arm="C_strict")

    assert capsys.readouterr().out == "(4/12) ✓  RC-01  C_strict\n"
    assert run_log.read_text(encoding="utf-8") == "(1/3) ✓  RC-01  C_strict\n"


@pytest.mark.parametrize(("arm", "ansi_code"), (("A_plain", "33"), ("B_auto", "36"), ("C_strict", "35")))
def test_readcrop_rows_are_compatible_with_the_shared_arm_palette(arm: str, ansi_code: str) -> None:
    """ReadCrop labels retain the structural A/B/C palette when ANSI is forced."""
    runner = _load()
    row = {
        "success": True,
        "task_id": "RC-01",
        "arm": arm,
        "input_tokens": 100,
        "output_tokens": 20,
        "command_calls": 1,
        "elapsed_s": 2.5,
        "primary_correct": True,
        "quality_score": 1.0,
        "codemap_used": arm != "A_plain",
        "compliance": True,
    }
    formatted = runner.format_result_row(row, completed=1, total=3)
    output = io.StringIO()

    runner.runtime.render_result_rows([f"{formatted}\n"], output, force_color=True)

    assert output.getvalue() == f"\x1b[{ansi_code}m{formatted}\x1b[0m\n"
    assert formatted.endswith(f"codemap={'✓' if arm != 'A_plain' else '✗'}")
    assert "compliance=" not in formatted


def test_checksums_cover_the_retained_readcrop_artifacts(tmp_path: Path) -> None:
    """Completed or failed runs retain an independently checkable artifact ledger."""
    runner = _load()
    (tmp_path / "telemetry.jsonl").write_text("{}\n", encoding="utf-8")
    nested = tmp_path / "inputs"
    nested.mkdir()
    (nested / "input-snapshot.json").write_text("{}\n", encoding="utf-8")

    runner.write_checksums(tmp_path)

    entries = (tmp_path / "checksums.sha256").read_text(encoding="utf-8")
    assert "telemetry.jsonl" in entries
    assert "inputs/input-snapshot.json" in entries
    assert "checksums.sha256" not in entries
    runner.verify_checksums(tmp_path)

    (tmp_path / "telemetry.jsonl").write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        runner.verify_checksums(tmp_path)


def test_strict_readcrop_requires_the_locked_symbol_query(monkeypatch: Any, tmp_path: Path) -> None:
    """A successful unrelated Skill query cannot satisfy strict treatment use."""
    runner = _load()
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "primary_module": "package.module",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = runner.build_readcrop_contract(task, source="def method(self, value: int) -> None:\n    pass\n")
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    parsed = SimpleNamespace(
        output_text=answer,
        success=True,
        skill_delivery_observed=True,
        codemap_skill_compact_successful_calls=1,
        successful_query_arguments=[["symbol", "Other.method"]],
        codemap_calls=1,
        input_tokens=10,
        cached_input_tokens=0,
        output_tokens=1,
        reasoning_output_tokens=0,
        tool_result_tokens=None,
        command_calls=1,
        tool_elapsed_s=0.1,
        raw_events=[],
    )
    monkeypatch.setattr(runner.runtime, "parse_codex_jsonl", lambda *_args, **_kwargs: parsed)
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("fixture\n", encoding="utf-8")

    row = runner.parse_readcrop_stream("ignored", arm="C_strict", contract=contract, skill_path=skill_path)
    contaminated_plain = runner.parse_readcrop_stream("ignored", arm="A_plain", contract=contract, skill_path=None)

    assert row["success"] is True
    assert row["strict_query_conformance"] is False
    assert row["compliance"] is True
    assert row["fresh_input_tokens"] == 10
    assert row["token_accounting_inconsistent"] is False
    assert row["command_calls"] == 1
    assert contaminated_plain["compliance"] is False
    assert contaminated_plain["contaminated"] is True
    assert contaminated_plain["success"] is False


def test_strict_readcrop_credits_the_verified_skill_file_and_locked_query(tmp_path: Path) -> None:
    """Strict treatment accepts only the immutable Skill read followed by its exact query."""
    runner = _load()
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "primary_module": "package.module",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = runner.build_readcrop_contract(task, source="def method(self, value: int) -> None:\n    pass\n")
    skill_path = tmp_path / "SKILL.md"
    skill_text = "---\nname: query-code\n---\n"
    skill_path.write_text(skill_text, encoding="utf-8")
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    stream = "\n".join(
        (
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "id": "skill-read",
                        "command": "/bin/zsh -lc 'cat \"$CODEMAP_SKILL_FILE\"'",
                        "aggregated_output": skill_text,
                        "status": "completed",
                        "exit_code": 0,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "id": "symbol-query",
                        "command": "/bin/zsh -lc '\"$CODEMAP_BIN\" query --compact symbol Example.method'",
                        "aggregated_output": '{"index":{"query_complete":true,"compact":true}}',
                        "status": "completed",
                        "exit_code": 0,
                    },
                }
            ),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}),
            json.dumps({"type": "turn.completed", "status": "completed"}),
        )
    )

    row = runner.parse_readcrop_stream(stream, arm="C_strict", contract=contract, skill_path=skill_path)

    assert row["success"] is True
    assert row["strict_query_conformance"] is True
    assert row["compliance"] is True


def test_dry_run_is_six_tasks_by_three_arms_when_loaded_from_the_locked_suite(tmp_path: Path) -> None:
    """The adapter plans each committed read-crop task in every treatment."""
    runner = _load()
    tasks = [{"contract": type("Contract", (), {"task_id": f"RC-{number:02d}"})()} for number in range(1, 7)]

    rows = runner.dry_run(tasks)

    assert sum(row.startswith("PLAN") for row in rows) == 18
    assert rows[-1] == "PLAN    RC-06  rep=1  C_strict"


def test_scope_hash_changes_when_task_selection_changes() -> None:
    """A paid approval cannot silently expand from a selected calibration."""
    runner = _load()
    manifest = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
    first = [
        {"contract": type("Contract", (), {"task_id": "RC-01", "oracle_sha256": "a" * 64, "source_sha256": "b" * 64})()}
    ]
    second = [
        {"contract": type("Contract", (), {"task_id": "RC-02", "oracle_sha256": "a" * 64, "source_sha256": "b" * 64})()}
    ]

    assert (
        runner.resolve_scope(first, manifest, runner.STRUCTURAL_PATH, "gpt-5.6-luna")["scope_sha256"]
        != runner.resolve_scope(second, manifest, runner.STRUCTURAL_PATH, "gpt-5.6-luna")["scope_sha256"]
    )
    scope = runner.resolve_scope(first, manifest, runner.STRUCTURAL_PATH, "gpt-5.6-luna")
    assert scope["stage_runner_sha256"] == hashlib.sha256(runner.Path(runner.__file__).read_bytes()).hexdigest()
    assert scope["structural_runner_sha256"] == hashlib.sha256(runner.STRUCTURAL_PATH.read_bytes()).hexdigest()


def test_scope_hash_changes_when_treatment_manifest_changes(tmp_path: Path) -> None:
    """A paid approval cannot survive a changed installed-treatment lock."""
    runner = _load()
    methodology = BENCHMARKS / "manifests" / "provider-parity-methodology.json"
    treatment_manifest = tmp_path / "codex-integration.json"
    treatment_manifest.write_text('{"artifact_sha256":{"codex_rig_adapter":"a"}}\n', encoding="utf-8")
    tasks = [
        {"contract": type("Contract", (), {"task_id": "RC-01", "oracle_sha256": "a" * 64, "source_sha256": "b" * 64})()}
    ]

    first = runner.resolve_scope(tasks, methodology, treatment_manifest, "gpt-5.6-luna")
    treatment_manifest.write_text('{"artifact_sha256":{"codex_rig_adapter":"b"}}\n', encoding="utf-8")
    second = runner.resolve_scope(tasks, methodology, treatment_manifest, "gpt-5.6-luna")

    assert first["treatment_manifest_sha256"] != second["treatment_manifest_sha256"]
    assert first["scope_sha256"] != second["scope_sha256"]


def test_paid_stage_scope_drift_reports_hashes_and_safe_recovery(monkeypatch: Any, tmp_path: Path) -> None:
    """A changed stage scope must stop before a model call and explain how to recover."""
    runner = _load()
    current_scope = "b" * 64
    monkeypatch.setattr(
        runner,
        "_prepare_readcrop_scope",
        lambda **_kwargs: ([{"contract": SimpleNamespace(task_id="RC-01")}], {"scope_sha256": current_scope}),
    )
    monkeypatch.setattr(runner, "run_paid", lambda *_args, **_kwargs: pytest.fail("model stage must not start"))

    with pytest.raises(ValueError, match="scope inputs changed after aggregate approval") as error:
        runner.run_stage(
            repo_path=tmp_path / "repo",
            model="gpt-5.6-luna",
            tasks_selector="RC-01",
            dry_run_requested=False,
            resolve_scope_requested=False,
            auth_source=tmp_path / "auth.json",
            run_dir=tmp_path / "run",
            paid_approval="a" * 64,
        )

    message = str(error.value)
    assert f"approved child scope: {'a' * 64}" in message
    assert f"current child scope: {current_scope}" in message
    assert "No model call was made." in message
    assert "--tasks RC-01 --dry-run" in message
    assert not (tmp_path / "run").exists()


def test_preflight_probes_every_native_arm(monkeypatch: Any, tmp_path: Path) -> None:
    """A green read-crop dry run must exercise the real A/B/C home boundary."""
    runner = _load()
    calls: list[str] = []

    class Adapter:
        """Capture isolation probes without creating real homes."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def probe_arm(self, arm: str) -> None:
            calls.append(arm)

        def close(self) -> None:
            pass

    monkeypatch.setattr(runner._structural, "CodexRunner", Adapter)
    runner.preflight_isolation(
        repo_path=tmp_path,
        index_path=tmp_path / "index.json",
        marketplace_root=tmp_path,
        codemap_bin=tmp_path / "codemap-py",
        model="gpt-5.6-luna",
        structural_manifest_path=tmp_path / "manifest.json",
    )

    assert calls == ["A_plain", "B_direct_required", "C_skill_required"]


def test_paid_snapshot_binds_the_structural_launcher_and_readcrop_stage(monkeypatch: Any, tmp_path: Path) -> None:
    """Paid provenance binds the one Fire launcher and the stage-specific scorer."""
    runner = _load()
    captured: dict[str, Any] = {}

    class Adapter:
        """Capture snapshot arguments before any model subprocess can start."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def create_input_snapshot(self, _run_dir: Path, **kwargs: Any) -> None:
            captured.update(kwargs)
            raise KeyboardInterrupt

        def close(self) -> None:
            pass

    monkeypatch.setattr(runner._structural, "CodexRunner", Adapter)
    task = {"task": {"id": "RC-01"}, "contract": type("Contract", (), {"task_id": "RC-01"})()}
    with pytest.raises(KeyboardInterrupt):
        runner.run_paid(
            scope={},
            tasks=[task],
            repo_path=tmp_path,
            index_path=tmp_path / "index.json",
            marketplace_root=tmp_path,
            codemap_bin=tmp_path / "codemap-py",
            auth_source=tmp_path / "auth.json",
            run_dir=tmp_path / "run",
            model="gpt-5.6-luna",
            structural_manifest_path=tmp_path / "manifest.json",
        )

    assert captured["runner_path"] == runner.STRUCTURAL_PATH
    assert captured["additional_shared_files"] == {
        "readcrop-contracts.py": runner.ROOT / "benchmarks" / "_bench_common" / "readcrop_contracts.py",
        "codex-readcrop-stage.py": runner.Path(runner.__file__),
        "codex-runtime.py": runner.BENCHMARKS / "_bench_codex" / "runtime.py",
    }


def test_readcrop_execution_is_controlled_only_by_dry_run() -> None:
    """The unified launcher must not leak a public --paid switch into ReadCrop."""
    runner = _load()
    parameters = inspect.signature(runner.run_stage).parameters

    assert "dry_run_requested" in parameters
    assert "paid" not in parameters
