"""Reader-side edge cases for the scan-query session-scoped coverage diet.

Complements the ``TestCoverageDiet`` cases in ``test_scan_query.py`` (first-full-then-
compact, missing-marker fail-verbose, ``--verbose-coverage`` override) by pinning the
two fail-verbose branches that block was missing and the compact block's honesty
contract when a result is incomplete:

- Marker present but **unparsable** JSON → full block (never compact on a broken marker).
- Marker present but **ts older than the 30-min TTL** → full block (stale session).
- Compact block on an **incomplete** result keeps ``degraded`` + ``note`` so the diet
  never hides WHY a result is incomplete, alongside the always-present per-query
  honesty signals (``query_complete``, ``stale``, ``root_mismatch``).

The scan-query CLI resolves the marker at ``<git-root>/.cache/codemap/current-session``,
so each test tree is a real git repo. The per-session sentinel lives in the OS temp dir
keyed on the marker's session id; tests clear it around each run so ordering is
deterministic and isolated.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
import sys
import tempfile
import time
from pathlib import Path

import pytest


def _build_diet_repo(root: Path, scan_index: Path, *, degraded: bool = False) -> Path:
    """Git-init *root*, write one module, scan it, return the index path.

    When *degraded* is True a second module is written whose source is unparsable, so
    scan-index records it with ``status="degraded"`` — the whole-graph ``central`` query
    then reports ``query_complete=false`` and the compact block must keep its honesty
    fields.

    Args:
        root: directory to initialise as the scan root (also the git root).
        scan_index: path to the scan-index bin script.
        degraded: if True, add a syntactically broken module to force a degraded status.
    """
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    (root / "modx.py").write_text("def fx(x):\n    return x\n")
    if degraded:
        (root / "broken.py").write_text("def oops(:\n    return\n")  # syntax error → degraded
    subprocess.run(
        [sys.executable, str(scan_index), "--root", str(root)],
        capture_output=True,
        cwd=str(root),
        check=True,
    )
    return root / ".cache" / "codemap" / f"{root.name}.json"


def _write_marker(root: Path, session_id: str, *, ts_ms: int | None = None) -> None:
    """Write the hook-owned session marker matching the cross-agent contract.

    Args:
        root: git root whose ``.cache/codemap/current-session`` receives the marker.
        session_id: session id to embed.
        ts_ms: epoch-ms timestamp; defaults to now. Pass an old value to simulate a
            marker past the TTL.
    """
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    marker = root / ".cache" / "codemap" / "current-session"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"session_id": session_id, "ts": ts_ms}))


def _run_coverage_query(scan_query: Path, root: Path, index_path: Path, *extra: str) -> dict:
    """Run ``central --top 1`` and return its ``index`` coverage block."""
    result = subprocess.run(
        [sys.executable, str(scan_query), "--index", str(index_path), *extra, "central", "--top", "1"],
        capture_output=True,
        text=True,
        cwd=str(root),
        env={**os.environ, "CODEMAP_LOGGING": "false"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)["index"]


# 30 min — mirrors _SESSION_MARKER_TTL_MS baked into scan-query.
_MARKER_TTL_MS = 30 * 60 * 1000


class TestCoverageDietFailVerbose:
    """Marker present-but-invalid must never compact — the diet fails verbose."""

    def test_unparsable_marker_stays_verbose(self, tmp_path, scan_index, scan_query):
        """A marker whose body is not valid JSON is treated as absent → always full block."""
        index_path = _build_diet_repo(tmp_path, scan_index)
        marker = tmp_path / ".cache" / "codemap" / "current-session"
        marker.write_text("{ this is not json")

        first = _run_coverage_query(scan_query, tmp_path, index_path)
        second = _run_coverage_query(scan_query, tmp_path, index_path)

        assert not first.get("compact")
        assert not second.get("compact"), "an unparsable marker must never engage the diet"
        assert "total_modules" in second

    def test_marker_past_ttl_stays_verbose(self, tmp_path, scan_index, scan_query):
        """A marker with a ts older than the 30-min TTL is stale → always full block."""
        index_path = _build_diet_repo(tmp_path, scan_index)
        session_id = f"aged-{tmp_path.name}-{uuid.uuid4().hex[:8]}"
        old_ts = int(time.time() * 1000) - (_MARKER_TTL_MS + 60_000)
        _write_marker(tmp_path, session_id, ts_ms=old_ts)
        sentinel = Path(tempfile.gettempdir()) / f"codemap-coverage-{session_id}"
        sentinel.unlink(missing_ok=True)
        try:
            first = _run_coverage_query(scan_query, tmp_path, index_path)
            second = _run_coverage_query(scan_query, tmp_path, index_path)
        finally:
            sentinel.unlink(missing_ok=True)

        assert not first.get("compact")
        assert not second.get("compact"), "a marker past the TTL must never engage the diet"


class TestCompactBlockHonesty:
    """The compact block keeps per-query honesty signals — and WHY when incomplete."""

    def test_compact_block_always_carries_per_query_signals(self, tmp_path, scan_index, scan_query):
        """Every compact block carries the three per-query honesty signals regardless of value."""
        index_path = _build_diet_repo(tmp_path, scan_index)
        session_id = f"signals-{tmp_path.name}-{uuid.uuid4().hex[:8]}"
        _write_marker(tmp_path, session_id)
        sentinel = Path(tempfile.gettempdir()) / f"codemap-coverage-{session_id}"
        sentinel.unlink(missing_ok=True)
        try:
            _run_coverage_query(scan_query, tmp_path, index_path)  # first → full, consumes sentinel
            compact = _run_coverage_query(scan_query, tmp_path, index_path)  # second → compact
        finally:
            sentinel.unlink(missing_ok=True)

        assert compact.get("compact") is True
        assert {"query_complete", "stale", "root_mismatch"} <= compact.keys()
        # The session-invariant full-block keys are dropped by the diet.
        assert "total_modules" not in compact
        assert "degraded_files" not in compact

    def test_compact_block_keeps_degraded_and_note_when_incomplete(self, tmp_path, scan_index, scan_query):
        """When a degraded module makes the whole-graph query incomplete, the diet keeps WHY."""
        index_path = _build_diet_repo(tmp_path, scan_index, degraded=True)
        session_id = f"incomplete-{tmp_path.name}-{uuid.uuid4().hex[:8]}"
        _write_marker(tmp_path, session_id)
        sentinel = Path(tempfile.gettempdir()) / f"codemap-coverage-{session_id}"
        sentinel.unlink(missing_ok=True)
        try:
            first = _run_coverage_query(scan_query, tmp_path, index_path)  # full block
            compact = _run_coverage_query(scan_query, tmp_path, index_path)  # compact block
        finally:
            sentinel.unlink(missing_ok=True)

        # Precondition: the degraded module really did make the query incomplete.
        assert first["query_complete"] is False, "expected the degraded module to make central incomplete"
        assert compact.get("compact") is True
        assert compact["query_complete"] is False
        # Honesty signal survives the diet: the reason for incompleteness is preserved.
        assert compact["degraded"] >= 1
        assert compact["note"], "the note explaining WHY must survive the compact diet"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
