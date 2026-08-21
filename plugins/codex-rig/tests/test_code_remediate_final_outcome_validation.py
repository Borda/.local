"""Regression checks for complete code-remediation outcome reconciliation."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TRIAGE_STATUSES = (
    "already-applied",
    "already-fixed",
    "duplicate",
    "needs-clarification",
    "out-of-scope",
    "resolved",
    "stale",
    "valid",
)
RESOLUTION_STATUSES = (
    "already-applied",
    "already-fixed",
    "duplicate",
    "implemented",
    "needs-clarification",
    "not-applicable",
    "rejected",
    "resolved",
    "stale",
    "unresolved",
)


def _load_validator() -> ModuleType:
    """Load the hyphenated artifact-validator module for focused contract tests."""
    path = PLUGIN_ROOT / "shared" / "validate-artifacts.py"
    spec = importlib.util.spec_from_file_location("codex_rig_validate_final_outcomes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _status_counts(statuses: tuple[str, ...], observed: list[str]) -> dict[str, int]:
    """Return complete status counts required by the validator contract."""
    return {status: observed.count(status) for status in statuses}


def _metadata() -> dict[str, object]:
    """Return a valid two-item final resolution ledger with different dispositions."""
    items = [
        {
            "input_item_id": "R1",
            "item_name": "Boundary guard",
            "item_type": "code",
            "sources": [
                {
                    "kind": "report",
                    "source_id": "R1",
                    "location": "src/guard.py:12",
                    "body": "The report says the boundary guard is missing.",
                    "evidence": "findings-input.txt",
                }
            ],
            "triage_status": "valid",
            "resolution_status": "implemented",
            "owner_status": "fixed",
            "resolved_how": "Added the missing guard.",
            "evidence": "tests/test_guard.py passed",
            "selectable": True,
        },
        {
            "input_item_id": "R2",
            "item_name": "Repeated comment",
            "item_type": "process",
            "sources": [
                {
                    "kind": "report",
                    "source_id": "R2",
                    "location": "src/guard.py:12",
                    "body": "The report repeats the boundary guard finding.",
                    "evidence": "findings-input.txt",
                },
                {
                    "kind": "online",
                    "source_id": "thread-991/comment-27",
                    "location": "src/guard.py:12",
                    "body": "Please add the same boundary guard here.",
                    "evidence": "pr/unresolved-review-threads.json",
                },
            ],
            "triage_status": "duplicate",
            "resolution_status": "duplicate",
            "owner_status": "not-actionable",
            "resolved_how": "Same obligation as R1.",
            "evidence": "R1 closure evidence",
            "selectable": False,
        },
    ]
    return {
        "final_resolution_table": {
            "ingested_entries_total": 2,
            "grouped_items_total": 1,
            "items": items,
            "nonselectable_rows_total": 1,
            "omitted_entries_total": 0,
            "omitted_source_records_total": 0,
            "represented_source_records_total": 3,
            "required_columns": [
                "input item",
                "item name",
                "item type",
                "sources",
                "triage status",
                "resolution",
                "owner/status",
                "resolved how",
                "evidence",
            ],
            "resolution_status_counts": _status_counts(
                RESOLUTION_STATUSES, [item["resolution_status"] for item in items]
            ),
            "selectable_rows_total": 1,
            "source_records_total": 3,
            "table_rows_total": 2,
            "triage_status_counts": _status_counts(TRIAGE_STATUSES, [item["triage_status"] for item in items]),
        }
    }


def _write_action_items(metadata: dict[str, object], out_dir: Path) -> None:
    """Render the durable Markdown table from the machine-readable item ledger."""
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    items = table["items"]
    assert isinstance(items, list)
    rows = []
    for item in items:
        sources = "<br>".join(
            "{kind} [{source_id}] @ {location} — {body} — {evidence}".format(**source) for source in item["sources"]
        )
        row_values = {**item, "sources": sources}
        rows.append(
            "| {input_item_id} | {item_name} | {item_type} | {sources} | {triage_status} | "
            "{resolution_status} | {owner_status} | {resolved_how} | {evidence} |".format(**row_values)
        )
    rendered_rows = "\n".join(rows)
    (out_dir / "action-items.md").write_text(
        f"""# Action Items

## Review Item Resolution Table

| Input item | Item name | Item type | Sources | Triage status | Resolution | Owner/status | Resolved how | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
{rendered_rows}

## Final Resolution Summary

Ingested entries: 2. All selected local actionable items are closed.

## Final Resolution Table Completeness

- Ingested entries: 2
- Table rows: 2
- Omitted entries: 0
- Triage status counts: valid=1, duplicate=1
- Resolution status counts: implemented=1, duplicate=1
""",
        encoding="utf-8",
    )


def test_final_resolution_items_reconcile_with_durable_markdown(tmp_path: Path) -> None:
    """Accept a complete machine ledger rendered without loss into Markdown."""
    metadata = _metadata()
    _write_action_items(metadata, tmp_path)

    VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_final_resolution_machine_items_are_required(tmp_path: Path) -> None:
    """Reject aggregate counts that cannot prove the disposition of each input item."""
    metadata = _metadata()
    _write_action_items(metadata, tmp_path)
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    table.pop("items")

    with pytest.raises(SystemExit, match="code-remediate-final-table-items-not-list"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_duplicate_machine_item_ids_fail_closed(tmp_path: Path) -> None:
    """Reject ledgers that account for one ingested item twice and omit another."""
    metadata = _metadata()
    _write_action_items(metadata, tmp_path)
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    items = table["items"]
    assert isinstance(items, list)
    items[1]["input_item_id"] = "R1"

    with pytest.raises(SystemExit, match="code-remediate-final-table-item-id-duplicate"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_markdown_row_omission_fails_even_when_aggregate_counts_match(tmp_path: Path) -> None:
    """Reject a durable table that silently drops one machine-accounted item."""
    metadata = _metadata()
    rendered = copy.deepcopy(metadata)
    table = rendered["final_resolution_table"]
    assert isinstance(table, dict)
    items = table["items"]
    assert isinstance(items, list)
    items.pop()
    _write_action_items(rendered, tmp_path)

    with pytest.raises(SystemExit, match="code-remediate-final-table-markdown-row-count-mismatch"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_markdown_disposition_must_match_machine_item(tmp_path: Path) -> None:
    """Reject a user-facing disposition that differs from the validated ledger."""
    metadata = _metadata()
    _write_action_items(metadata, tmp_path)
    path = tmp_path / "action-items.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("| valid | implemented |", "| valid | unresolved |"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="code-remediate-final-table-markdown-resolution_status-mismatch"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_grouped_item_requires_every_source_body_in_durable_table(tmp_path: Path) -> None:
    """Reject a grouped disposition whose visible row hides its contributing comments."""
    metadata = _metadata()
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    _write_action_items(metadata, tmp_path)
    path = tmp_path / "action-items.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Please add the same boundary guard here.", "online duplicate"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="code-remediate-final-table-markdown-source-body-missing"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_source_category_is_report_or_online(tmp_path: Path) -> None:
    """Keep the user-facing provenance vocabulary limited to report and online."""
    metadata = _metadata()
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    items = table["items"]
    assert isinstance(items, list)
    items[0]["sources"][0]["kind"] = "pr-thread"
    _write_action_items(metadata, tmp_path)

    with pytest.raises(SystemExit, match="code-remediate-final-table-source-kind-invalid"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)


def test_source_record_counts_fail_closed(tmp_path: Path) -> None:
    """Reject aggregate source counts that could conceal an omitted grouped comment."""
    metadata = _metadata()
    table = metadata["final_resolution_table"]
    assert isinstance(table, dict)
    table["represented_source_records_total"] = 2
    _write_action_items(metadata, tmp_path)

    with pytest.raises(SystemExit, match="code-remediate-final-table-source-count-mismatch"):
        VALIDATOR._validate_code_remediate_final_resolution_table(metadata, tmp_path)
