"""Regression checks for selecting assessed code-review reports for remediation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FINDER_PATH = PLUGIN_ROOT / "shared" / "find-review-report.py"


def _load_finder() -> object:
    """Load the standalone report finder from its shipped plugin path."""
    specification = importlib.util.spec_from_file_location("find_review_report", FINDER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_report(root: Path, timestamp: str, *, unavailable: bool) -> Path:
    """Create a minimal PR-identified report with an optional terminal collection failure."""
    report_dir = root / timestamp
    report_dir.mkdir()
    if unavailable:
        (report_dir / "pr-target.txt").write_text("https://github.com/acme/widgets/pull/123\n", encoding="utf-8")
    else:
        (report_dir / "pr.json").write_text(
            json.dumps({"number": 123, "url": "https://github.com/acme/widgets/pull/123"}), encoding="utf-8"
        )
    metadata: dict[str, object] = {"scope": "pr", "review_decision": {"recommendation": "needs-more-work"}}
    if unavailable:
        metadata["review_status"] = "unavailable"
    result_path = report_dir / "result.json"
    result_path.write_text(json.dumps({"metadata": metadata}), encoding="utf-8")
    return result_path


def _write_closed_report(root: Path, timestamp: str) -> Path:
    """Create a PR-identified terminal close result that remediation must not consume."""
    report_dir = root / timestamp
    report_dir.mkdir()
    (report_dir / "pr.json").write_text(
        json.dumps({"number": 123, "url": "https://github.com/acme/widgets/pull/123"}), encoding="utf-8"
    )
    result_path = report_dir / "result.json"
    result_path.write_text(
        json.dumps({"metadata": {"scope": "pr", "review_status": "closed", "close_decision": {"code": "DUPLICATE"}}}),
        encoding="utf-8",
    )
    return result_path


def test_newer_unavailable_report_does_not_shadow_older_assessed_review(tmp_path: Path) -> None:
    """Keep automatic remediation bound to findings that were actually assessed."""
    finder = _load_finder()
    assessed = _write_report(tmp_path, "2026-08-10T10-00-00Z", unavailable=False)
    _write_report(tmp_path, "2026-08-10T11-00-00Z", unavailable=True)

    selected = finder.find_latest_review_report("123", [tmp_path])

    assert selected == assessed


def test_only_unavailable_reports_require_a_new_code_review(tmp_path: Path) -> None:
    """Do not let remediation consume an operational diagnostic as source findings."""
    finder = _load_finder()
    _write_report(tmp_path, "2026-08-10T11-00-00Z", unavailable=True)

    with pytest.raises(LookupError, match="matching-review-unavailable-rerun-code-review"):
        finder.find_latest_review_report("https://github.com/acme/widgets/pull/123", [tmp_path])


def test_explicit_unavailable_report_is_rejected_as_remediation_input(tmp_path: Path) -> None:
    """Apply the same assessed-review guard when the report path is user supplied."""
    finder = _load_finder()
    unavailable = _write_report(tmp_path, "2026-08-10T11-00-00Z", unavailable=True)

    with pytest.raises(LookupError, match="matching-review-unavailable-rerun-code-review"):
        finder.require_assessed_review_result(unavailable)


def test_malformed_result_is_rejected_as_remediation_input(tmp_path: Path) -> None:
    """Fail closed instead of treating an unreadable diagnostic as an assessed review."""
    finder = _load_finder()
    malformed = tmp_path / "result.json"
    malformed.write_text("not-json", encoding="utf-8")

    with pytest.raises(LookupError, match="invalid-review-report-rerun-code-review"):
        finder.require_assessed_review_result(malformed)


def test_explicit_closed_report_is_rejected_as_remediation_input(tmp_path: Path) -> None:
    """Do not treat a terminal proposal-level close decision as source findings."""
    finder = _load_finder()
    closed = _write_closed_report(tmp_path, "2026-08-10T11-00-00Z")

    with pytest.raises(LookupError, match="matching-review-closed-not-remediable"):
        finder.require_assessed_review_result(closed)


def test_newer_closed_report_blocks_older_assessed_review(tmp_path: Path) -> None:
    """Prevent remediation from reviving stale findings after a newer close decision."""
    finder = _load_finder()
    _write_report(tmp_path, "2026-08-10T10-00-00Z", unavailable=False)
    _write_closed_report(tmp_path, "2026-08-10T11-00-00Z")

    with pytest.raises(LookupError, match="matching-review-closed-not-remediable"):
        finder.find_latest_review_report("123", [tmp_path])
