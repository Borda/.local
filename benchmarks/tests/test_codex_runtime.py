"""No-model contracts for the shared Codex runtime lifecycle."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


BENCHMARKS = Path(__file__).resolve().parent.parent


def _load() -> Any:
    """Load the private runtime without importing a paid benchmark runner."""
    if str(BENCHMARKS) not in sys.path:
        sys.path.insert(0, str(BENCHMARKS))
    spec = importlib.util.spec_from_file_location(
        "benchmarks_codex_runtime", BENCHMARKS / "_bench_codex" / "runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_lifecycle() -> Any:
    """Return the provider-neutral paid lifecycle owner."""
    if str(BENCHMARKS) not in sys.path:
        sys.path.insert(0, str(BENCHMARKS))
    from _bench_common import paid_lifecycle

    return paid_lifecycle


def _callbacks(
    lifecycle: Any,
    events: list[tuple[str, Any]],
    *,
    fail_at: tuple[str, str] | None = None,
    invalid_at: tuple[str, str] | None = None,
) -> Any:
    """Build observable callbacks for a no-model staged execution."""

    def run_cell(task: str, arm: str) -> dict[str, str]:
        events.append(("run", (task, arm)))
        if (task, arm) == fail_at:
            raise RuntimeError("fixture cell failed")
        return {"task_id": task, "arm": arm}

    def validate_row(task: str, arm: str, row: dict[str, str]) -> None:
        events.append(("validate", (task, arm, dict(row))))
        if (task, arm) == invalid_at:
            raise ValueError("fixture row rejected")

    def persist_metadata(path: Path, metadata: dict[str, Any]) -> None:
        events.append(("metadata", (metadata["status"], metadata["persisted_cells"])))
        path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")

    return lifecycle.PaidStageCallbacks(
        run_cell=run_cell,
        validate_row=validate_row,
        prepare_run=lambda run_dir: events.append(("prepare", run_dir)),
        persist_metadata=persist_metadata,
        emit_lifecycle=lambda event, values: events.append((event, dict(values))),
        emit_row=lambda row, completed, total, arm: events.append(("row", (dict(row), completed, total, arm))),
        write_checksums=lambda run_dir: events.append(("checksums", run_dir)),
        close_adapter=lambda: events.append(("closed", None)),
    )


def test_paid_stage_runs_exact_task_arm_order_and_persists_every_cell(tmp_path: Path) -> None:
    """The lifecycle preserves canonical order and durable per-cell progress."""
    lifecycle = _load_lifecycle()
    events: list[tuple[str, Any]] = []
    run_dir = tmp_path / "runs" / "stage"

    result = lifecycle.run_paid_stage(
        tasks=("T01", "T02"),
        arms=("A", "B"),
        run_dir=run_dir,
        metadata={"scope": "fixture"},
        callbacks=_callbacks(lifecycle, events),
    )

    assert result == run_dir
    assert [value for kind, value in events if kind == "run"] == [
        ("T01", "A"),
        ("T01", "B"),
        ("T02", "A"),
        ("T02", "B"),
    ]
    assert [value for kind, value in events if kind == "metadata"] == [
        ("running", 0),
        ("running", 1),
        ("running", 2),
        ("running", 3),
        ("running", 4),
        ("completed", 4),
    ]
    assert [value[1:] for kind, value in events if kind == "row"] == [
        (1, 4, "A"),
        (2, 4, "B"),
        (3, 4, "A"),
        (4, 4, "B"),
    ]
    assert [kind for kind, _ in events if kind in {"artifacts", "summary"}] == ["artifacts", "summary"]
    assert [kind for kind, _ in events if kind in {"checksums", "closed"}] == ["checksums", "closed"]
    assert [json.loads(line) for line in (run_dir / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()] == [
        {"arm": "A", "task_id": "T01"},
        {"arm": "B", "task_id": "T01"},
        {"arm": "A", "task_id": "T02"},
        {"arm": "B", "task_id": "T02"},
    ]
    assert json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8")) == {
        "persisted_cells": 4,
        "scope": "fixture",
        "status": "completed",
    }


def test_paid_stage_failure_persists_error_summary_and_finalizes_callbacks(tmp_path: Path) -> None:
    """A failed later cell retains the last durable row and closes the adapter."""
    lifecycle = _load_lifecycle()
    events: list[tuple[str, Any]] = []
    run_dir = tmp_path / "failed"

    with pytest.raises(RuntimeError, match="fixture cell failed"):
        lifecycle.run_paid_stage(
            tasks=("T01",),
            arms=("A", "B"),
            run_dir=run_dir,
            metadata={},
            callbacks=_callbacks(lifecycle, events, fail_at=("T01", "B")),
        )

    assert json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8")) == {
        "error": {"message": "fixture cell failed", "type": "RuntimeError"},
        "persisted_cells": 1,
        "status": "failed",
    }
    assert (run_dir / "telemetry.jsonl").read_text(encoding="utf-8") == '{"arm": "A", "task_id": "T01"}\n'
    assert [(kind, value) for kind, value in events if kind == "summary"] == [
        ("summary", {"persisted_cells": 1, "status": "failed", "total_cells": 2})
    ]
    assert [kind for kind, _ in events][-2:] == ["checksums", "closed"]


def test_paid_stage_rejects_an_invalid_row_before_telemetry_persistence(tmp_path: Path) -> None:
    """Binding validation cannot leave an unvalidated row in durable telemetry."""
    lifecycle = _load_lifecycle()
    events: list[tuple[str, Any]] = []
    run_dir = tmp_path / "rejected"

    with pytest.raises(ValueError, match="fixture row rejected"):
        lifecycle.run_paid_stage(
            tasks=("T01",),
            arms=("A",),
            run_dir=run_dir,
            metadata={},
            callbacks=_callbacks(lifecycle, events, invalid_at=("T01", "A")),
        )

    assert (run_dir / "telemetry.jsonl").read_text(encoding="utf-8") == ""
    assert json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))["error"] == {
        "message": "fixture row rejected",
        "type": "ValueError",
    }


def test_paid_stage_marks_keyboard_interrupt_as_interrupted_and_finalizes(tmp_path: Path) -> None:
    """Interrupts retain completed cells and run the same durable finalizers."""
    lifecycle = _load_lifecycle()
    events: list[tuple[str, Any]] = []
    run_dir = tmp_path / "interrupted"

    def interrupting_run_cell(task: str, arm: str) -> dict[str, str]:
        if arm == "B":
            raise KeyboardInterrupt("stop fixture")
        return {"task_id": task, "arm": arm}

    callbacks = _callbacks(lifecycle, events)
    callbacks = lifecycle.PaidStageCallbacks(
        run_cell=interrupting_run_cell,
        validate_row=callbacks.validate_row,
        prepare_run=callbacks.prepare_run,
        persist_metadata=callbacks.persist_metadata,
        emit_lifecycle=callbacks.emit_lifecycle,
        emit_row=callbacks.emit_row,
        write_checksums=callbacks.write_checksums,
        close_adapter=callbacks.close_adapter,
    )
    with pytest.raises(KeyboardInterrupt, match="stop fixture"):
        lifecycle.run_paid_stage(tasks=("T01",), arms=("A", "B"), run_dir=run_dir, metadata={}, callbacks=callbacks)

    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "interrupted"
    assert metadata["persisted_cells"] == 1
    assert [kind for kind, _ in events][-2:] == ["checksums", "closed"]


def test_paid_stage_rejects_an_existing_run_directory_and_still_closes_adapter(tmp_path: Path) -> None:
    """A run path is reserved exclusively even when setup cannot begin."""
    lifecycle = _load_lifecycle()
    events: list[tuple[str, Any]] = []
    run_dir = tmp_path / "occupied"
    run_dir.mkdir()

    with pytest.raises(FileExistsError):
        lifecycle.run_paid_stage(
            tasks=("T01",),
            arms=("A",),
            run_dir=run_dir,
            metadata={},
            callbacks=_callbacks(lifecycle, events),
        )

    assert events == [("closed", None)]


def test_checksum_ledger_detects_retained_artifact_changes(tmp_path: Path) -> None:
    """The shared ledger covers lifecycle evidence and rejects later tampering."""
    lifecycle = _load_lifecycle()
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text('{"task_id": "T01"}\n', encoding="utf-8")
    metadata = tmp_path / "run-metadata.json"
    metadata.write_text('{"status": "completed"}\n', encoding="utf-8")

    lifecycle.write_checksums(tmp_path)

    assert "checksums.sha256" not in (tmp_path / "checksums.sha256").read_text(encoding="utf-8")
    lifecycle.verify_checksums(tmp_path)

    telemetry.write_text('{"task_id": "changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch: telemetry.jsonl"):
        lifecycle.verify_checksums(tmp_path)


def test_checksum_ledger_rejects_a_path_outside_the_run_directory(tmp_path: Path) -> None:
    """Checksum verification never resolves a ledger entry outside its run root."""
    lifecycle = _load_lifecycle()
    (tmp_path / "checksums.sha256").write_text(f"{'0' * 64}  ../outside.jsonl\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe path"):
        lifecycle.verify_checksums(tmp_path)


def test_root_checksum_ledger_covers_each_child_stage_ledger(tmp_path: Path) -> None:
    """A unified run cannot hide changed stage telemetry behind a child ledger."""
    lifecycle = _load_lifecycle()
    child = tmp_path / "readcrop"
    child.mkdir()
    telemetry = child / "telemetry.jsonl"
    telemetry.write_text('{"task_id": "RC-01"}\n', encoding="utf-8")
    lifecycle.write_checksums(child)

    lifecycle.write_checksums(tmp_path)

    root_ledger = (tmp_path / "checksums.sha256").read_text(encoding="utf-8")
    assert "readcrop/telemetry.jsonl" in root_ledger
    assert "readcrop/checksums.sha256" in root_ledger
    lifecycle.verify_checksums(tmp_path)

    telemetry.write_text('{"task_id": "changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch: readcrop/telemetry.jsonl"):
        lifecycle.verify_checksums(tmp_path)


@pytest.mark.parametrize(
    ("local_completed", "local_total", "completed_offset", "expected_prefix"),
    [
        pytest.param(1, 165, 0, "(1/204)", id="structural-first"),
        pytest.param(165, 165, 0, "(165/204)", id="structural-last"),
        pytest.param(1, 18, 165, "(166/204)", id="readcrop-first"),
        pytest.param(18, 18, 165, "(183/204)", id="readcrop-last"),
        pytest.param(1, 12, 183, "(184/204)", id="fix-single-first"),
        pytest.param(12, 12, 183, "(195/204)", id="fix-single-last"),
        pytest.param(1, 9, 195, "(196/204)", id="fix-multi-first"),
        pytest.param(9, 9, 195, "(204/204)", id="fix-multi-last"),
    ],
)
def test_progress_scope_maps_every_native_stage_boundary_to_one_counter(
    local_completed: int,
    local_total: int,
    completed_offset: int,
    expected_prefix: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unified terminal rows advance monotonically while their content stays native."""
    runtime = _load()
    suffix = " ✓  T-01 A_plain native-stage-fields"

    with runtime.progress_scope(completed_offset=completed_offset, total_cells=204):
        runtime.print_arm_row(f"({local_completed}/{local_total}){suffix}", "A_plain")

    assert capsys.readouterr().out.rstrip("\n") == f"{expected_prefix}{suffix}"


def test_progress_scope_restores_stage_local_output_after_an_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed child stage cannot leak aggregate presentation into later runs."""
    runtime = _load()

    with pytest.raises(RuntimeError, match="fixture failure"):
        with runtime.progress_scope(completed_offset=3, total_cells=12):
            runtime.print_arm_row("(1/3) ✓ T-01 A_plain", "A_plain")
            raise RuntimeError("fixture failure")
    runtime.print_arm_row("(1/3) ✓ T-01 A_plain", "A_plain")

    assert capsys.readouterr().out.splitlines() == [
        "(4/12) ✓ T-01 A_plain",
        "(1/3) ✓ T-01 A_plain",
    ]


@pytest.mark.parametrize(
    ("completed_offset", "total_cells"),
    [
        pytest.param(-1, 12, id="negative-offset"),
        pytest.param(0, 0, id="zero-total"),
        pytest.param(12, 12, id="completed-offset"),
    ],
)
def test_progress_scope_rejects_impossible_aggregate_coordinates(completed_offset: int, total_cells: int) -> None:
    """Invalid aggregate coordinates fail before any terminal row is emitted."""
    runtime = _load()

    with pytest.raises(ValueError, match="progress scope"):
        with runtime.progress_scope(completed_offset=completed_offset, total_cells=total_cells):
            pass
