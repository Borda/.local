"""Tests for check_index_freshness bin script.

Covers happy path, missing/invalid input, and stale-threshold boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


import check_index_freshness as cif


def _write_index(tmp_path: Path, scanned_at: str | None) -> Path:
    """Write a minimal codemap index JSON file and return its path."""
    payload: dict[str, object] = {"modules": []}
    if scanned_at is not None:
        payload["scanned_at"] = scanned_at
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestParseScannedAt:
    """Cover datetime parsing for the scanned_at field."""

    def test_parses_iso_with_timezone_suffix(self):
        """First 19 chars of an ISO timestamp parse to a UTC datetime."""
        parsed = cif.parse_scanned_at("2026-01-15T12:30:45Z")
        assert parsed == datetime(2026, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

    def test_returns_none_for_empty_string(self):
        """Empty string yields None instead of raising."""
        assert cif.parse_scanned_at("") is None

    def test_returns_none_for_unparseable_value(self):
        """Non-ISO input returns None rather than raising ValueError."""
        assert cif.parse_scanned_at("not-a-timestamp") is None


class TestAgeDays:
    """Cover day-floor arithmetic between two datetimes."""

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [
            (timedelta(days=0), 0),
            (timedelta(days=1), 1),
            (timedelta(days=3, hours=23), 3),
            (timedelta(days=8), 8),
        ],
    )
    def test_floors_to_whole_days(self, offset: timedelta, expected: int):
        """age_days returns the floor of the elapsed day count."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        assert cif.age_days(now - offset, now) == expected

    def test_negative_delta_clamps_to_zero(self):
        """Future scan times never report negative age."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        future = now + timedelta(days=2)
        assert cif.age_days(future, now) == 0


class TestFormatStatus:
    """Cover the three status-line shapes produced by format_status."""

    def test_fresh_status_under_threshold(self):
        """Two-day-old scans report ✓ freshness."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        scan = now - timedelta(days=2)
        line = cif.format_status("2026-01-08T00:00:00Z", scan, now)
        assert line.startswith("✓ freshness: 2 day(s) ago (2026-01-08)")

    def test_stale_status_over_threshold(self):
        """Ten-day-old scans report ⚠ freshness with refresh hint."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        scan = now - timedelta(days=10)
        line = cif.format_status("2025-12-31T00:00:00Z", scan, now)
        assert "⚠ freshness: 10 day(s) ago (2025-12-31)" in line
        assert "Run /codemap:scan to refresh" in line

    def test_missing_scanned_at_message(self):
        """Missing scanned_at surfaces the corruption hint."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        line = cif.format_status(None, None, now)
        assert line.startswith("⚠ freshness: scanned_at missing")

    def test_unparseable_scanned_at_message(self):
        """Unparsable scanned_at surfaces the raw value in the warning."""
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        line = cif.format_status("bogus", None, now)
        assert "could not parse scanned_at timestamp (bogus)" in line


class TestReadScannedAt:
    """Cover JSON loading behaviour for scanned_at extraction."""

    def test_reads_scanned_at_from_valid_json(self, tmp_path: Path):
        """Valid JSON with scanned_at returns the string."""
        path = _write_index(tmp_path, "2026-01-08T00:00:00Z")
        assert cif.read_scanned_at(path) == "2026-01-08T00:00:00Z"

    def test_missing_field_returns_none(self, tmp_path: Path):
        """JSON without scanned_at returns None."""
        path = _write_index(tmp_path, None)
        assert cif.read_scanned_at(path) is None

    def test_invalid_json_returns_none(self, tmp_path: Path):
        """Non-JSON file returns None instead of raising."""
        path = tmp_path / "broken.json"
        path.write_text("{not-valid-json", encoding="utf-8")
        assert cif.read_scanned_at(path) is None


class TestMain:
    """End-to-end CLI behaviour via ``main(argv)``."""

    def test_missing_path_argument_warns(self, capsys: pytest.CaptureFixture[str]):
        """No argument prints the not-found warning and exits 0."""
        assert cif.main([]) == 0
        captured = capsys.readouterr()
        assert "index not provided or not found" in captured.out

    def test_nonexistent_path_warns(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Path that does not point at a file prints not-found warning."""
        assert cif.main([str(tmp_path / "does-not-exist.json")]) == 0
        captured = capsys.readouterr()
        assert "index not provided or not found" in captured.out

    def test_happy_path_prints_freshness(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Index with a recent scanned_at prints ✓ freshness."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = _write_index(tmp_path, recent)
        assert cif.main([str(path)]) == 0
        captured = capsys.readouterr()
        assert captured.out.startswith("✓ freshness:")

    def test_stale_index_prints_warning(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Index older than threshold prints ⚠ freshness."""
        old = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = _write_index(tmp_path, old)
        assert cif.main([str(path)]) == 0
        captured = capsys.readouterr()
        assert captured.out.startswith("⚠ freshness:")
        assert "Run /codemap:scan to refresh" in captured.out

    def test_missing_scanned_at_field(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Valid JSON without scanned_at prints the corruption warning."""
        path = _write_index(tmp_path, None)
        assert cif.main([str(path)]) == 0
        captured = capsys.readouterr()
        assert "scanned_at missing" in captured.out

    def test_unparseable_scanned_at(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Bad scanned_at content surfaces parse-error warning."""
        path = _write_index(tmp_path, "not-a-real-date")
        assert cif.main([str(path)]) == 0
        captured = capsys.readouterr()
        assert "could not parse scanned_at timestamp" in captured.out
