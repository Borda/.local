"""Tests for bin/codemap_cache.py — review→resolve pre-flight cache.

Covers: write splitting a batch into per-module artifacts, read freshness verdicts (fresh, cold miss, index-rebuilt,
git-sha mismatch, index-stamp mismatch, content-hash mismatch), and the reuse_ratio report metric.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import codemap_cache  # type: ignore[import-not-found]

# Pinned so two identical _write_index calls produce an identical file stamp; the
# real clock would make every rewrite look like a new index and every reuse test flaky.
_FIXED_MTIME_NS = 1_700_000_000_000_000_000


def _write_index(
    tmp_path: Path,
    git_sha: str = "abc123",
    scanned_at: str = "2026-07-10T00:00:00+00:00",
    mtime_ns: int = _FIXED_MTIME_NS,
) -> Path:
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps({"git_sha": git_sha, "scanned_at": scanned_at, "modules": {}}))
    os.utime(idx, ns=(mtime_ns, mtime_ns))
    return idx


def _write_batch(tmp_path: Path) -> Path:
    batch = {
        "batch": [
            {"ok": True, "index": 0, "cmd": "central", "result": {"central": []}},
            {"ok": True, "index": 1, "cmd": "rdeps", "result": {"module": "pkg.mod", "importers": ["a"]}},
            {"ok": True, "index": 2, "cmd": "fn-rdeps", "result": {"qname": "pkg.mod::fn", "called_by": []}},
            {"ok": True, "index": 3, "cmd": "uncovered", "result": {"query": "pkg.other", "symbols": ["f"]}},
            {"ok": False, "index": 4, "cmd": "rdeps", "result": {"error": "boom"}},
        ],
        "count": 5,
        "index": {"query_complete": True},
    }
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch))
    return path


class TestWrite:
    """Write subcommand — batch → per-module artifacts."""

    def test_write_splits_by_module(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = tmp_path / "cache"
        rc = codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["modules_written"] == 2
        assert (cache / "pkg.mod.json").exists()
        assert (cache / "pkg.other.json").exists()

    def test_write_prefix_delta_shape(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        art = json.loads((cache / "pkg.mod.json").read_text())
        assert art["prefix"]["git_sha"] == "abc123"
        assert art["prefix"]["scanned_at"] == "2026-07-10T00:00:00+00:00"
        assert art["prefix"]["index_stamp"] == codemap_cache._file_stamp(_write_index(tmp_path))
        # fn-rdeps keys on qname "pkg.mod::fn" — grouped under module pkg.mod
        assert set(art["prefix"]["answers"]) == {"rdeps", "fn-rdeps"}
        assert art["delta"] == {"touched_files": [], "exhausted_queries": [], "notes": []}

    def test_write_skips_failed_items(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        art = json.loads((cache / "pkg.mod.json").read_text())
        # the ok=False rdeps item must not overwrite the valid one
        assert art["prefix"]["answers"]["rdeps"]["importers"] == ["a"]


class TestRead:
    """Read subcommand — freshness verdicts."""

    def _seed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
        cache = tmp_path / "cache"
        codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        capsys.readouterr()  # drain the write's stdout so read verdicts parse cleanly
        return cache

    def test_fresh_reuse(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = self._seed(tmp_path, capsys)
        rc = codemap_cache.main(
            ["read", "--module", "pkg.mod", "--index", str(_write_index(tmp_path)), "--cache-dir", str(cache)]
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is True
        assert out["reason"] == "fresh"
        assert out["answers"]["rdeps"]["importers"] == ["a"]

    def test_cold_miss(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = self._seed(tmp_path, capsys)
        rc = codemap_cache.main(
            ["read", "--module", "pkg.absent", "--index", str(_write_index(tmp_path)), "--cache-dir", str(cache)]
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "cold_miss"

    def test_index_rebuilt_invalidates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = self._seed(tmp_path, capsys)
        newer = _write_index(tmp_path, git_sha="abc123", scanned_at="2026-07-11T00:00:00+00:00")
        codemap_cache.main(["read", "--module", "pkg.mod", "--index", str(newer), "--cache-dir", str(cache)])
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "index_rebuilt"

    def test_git_sha_mismatch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = self._seed(tmp_path, capsys)
        moved = _write_index(tmp_path, git_sha="def456")
        codemap_cache.main(["read", "--module", "pkg.mod", "--index", str(moved), "--cache-dir", str(cache)])
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "git_sha_mismatch"

    def test_in_place_rewrite_invalidates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Index rewritten with identical metadata but a new mtime → no reuse.

        ``git_sha`` and ``scanned_at`` are the index's own declared fields, so an incremental scan or a restored backup
        that leaves them untouched was indistinguishable from no change at all, and stale answers were served as fresh.
        """
        cache = self._seed(tmp_path, capsys)
        rewritten = _write_index(tmp_path, mtime_ns=_FIXED_MTIME_NS + 5_000_000_000)
        codemap_cache.main(["read", "--module", "pkg.mod", "--index", str(rewritten), "--cache-dir", str(cache)])
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "index_stamp_mismatch"

    def test_artifact_without_stamp_fails_closed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A pre-stamp artifact is re-queried, never trusted (fail-closed)."""
        cache = self._seed(tmp_path, capsys)
        art_path = cache / "pkg.mod.json"
        art = json.loads(art_path.read_text())
        del art["prefix"]["index_stamp"]
        art_path.write_text(json.dumps(art))
        codemap_cache.main(
            ["read", "--module", "pkg.mod", "--index", str(_write_index(tmp_path)), "--cache-dir", str(cache)]
        )
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "index_stamp_mismatch"

    def test_content_hash_mismatch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = self._seed(tmp_path, capsys)
        art_path = cache / "pkg.mod.json"
        art = json.loads(art_path.read_text())
        art["prefix"]["answers"]["rdeps"]["importers"] = ["tampered"]
        art_path.write_text(json.dumps(art))
        codemap_cache.main(
            ["read", "--module", "pkg.mod", "--index", str(_write_index(tmp_path)), "--cache-dir", str(cache)]
        )
        out = json.loads(capsys.readouterr().out)
        assert out["reuse"] is False
        assert out["reason"] == "content_hash_mismatch"


class TestReport:
    """Report subcommand — reuse_ratio metric."""

    def test_zero_when_no_reuse_markers(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = tmp_path / "cache"
        codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        capsys.readouterr()  # drain the write's stdout
        codemap_cache.main(["report", "--cache-dir", str(cache)])
        out = json.loads(capsys.readouterr().out)
        assert out["reuse_ratio"] == 0.0
        assert out["answers_total"] == 3  # rdeps + fn-rdeps (pkg.mod) + uncovered (pkg.other)

    def test_ratio_counts_reused_marker(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cache = tmp_path / "cache"
        codemap_cache.main(
            [
                "write",
                "--batch",
                str(_write_batch(tmp_path)),
                "--index",
                str(_write_index(tmp_path)),
                "--cache-dir",
                str(cache),
            ]
        )
        art_path = cache / "pkg.mod.json"
        art = json.loads(art_path.read_text())
        art["delta"]["notes"].append("reused@2026-07-10")
        art_path.write_text(json.dumps(art))
        capsys.readouterr()  # drain the write's stdout
        codemap_cache.main(["report", "--cache-dir", str(cache)])
        out = json.loads(capsys.readouterr().out)
        assert out["answers_reused"] == 2  # pkg.mod had 2 answers
        assert out["reuse_ratio"] == round(2 / 3, 3)


def test_bad_args_exit_1(tmp_path: Path) -> None:
    """Unreadable batch input → exit 1, error on stderr."""
    rc = codemap_cache.main(
        [
            "write",
            "--batch",
            str(tmp_path / "nope.json"),
            "--index",
            str(tmp_path / "nope2.json"),
            "--cache-dir",
            str(tmp_path),
        ]
    )
    assert rc == 1
