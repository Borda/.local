"""Tests for benchmarks/_bench_common/benchmark_paths.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def test_tasks_bench_file_is_under_benchmarks_suite_root(script_benchmark_paths: Any) -> None:
    """The common package resolves suites from benchmarks/, not _bench_common/."""
    assert (
        script_benchmark_paths.TASKS_BENCH_FILE == Path(__file__).resolve().parents[1] / "suites" / "tasks-bench.json"
    )
