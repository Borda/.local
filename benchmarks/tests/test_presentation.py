"""Terminal presentation contracts shared by benchmark providers."""

from __future__ import annotations

from pathlib import Path
import sys


BENCHMARKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARKS))

from _bench_common.presentation import format_artifact_block, format_quality  # noqa: E402


def test_multiple_artifacts_render_as_a_readable_list() -> None:
    """Two durable paths must not be compressed into one unscannable terminal line."""
    assert format_artifact_block(telemetry="results/run/telemetry.jsonl", metadata="results/run/run-metadata.json") == (
        "ARTIFACTS:\n - telemetry=results/run/telemetry.jsonl\n - metadata=results/run/run-metadata.json"
    )


def test_quality_format_preserves_the_shared_column_width() -> None:
    """Scores retain fixed-width alignment without duplicating row eligibility state."""
    assert format_quality(1.0) == "1.000 "
    assert format_quality(0.258) == "0.258 "
    assert format_quality(0.0) == "0.000 "
