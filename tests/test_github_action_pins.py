"""Regression checks for immutable third-party GitHub Actions references."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(?P<target>\S+?)(?:\s+#\s*(?P<comment>.+))?\s*$")
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^v\d+(?:\.\d+){0,2}$")


def test_external_workflow_actions_use_immutable_commit_pins() -> None:
    """Prevent mutable tags, branches, and expressions from re-entering CI workflows."""
    workflow_paths = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    assert workflow_paths
    external_references: list[tuple[Path, int, str, str | None]] = []
    for path in workflow_paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES_LINE.match(line)
            if match is None:
                continue
            target = match.group("target")
            if target.startswith("./"):
                continue
            external_references.append((path, line_number, target, match.group("comment")))

    assert external_references
    for path, line_number, target, comment in external_references:
        location = f"{path.relative_to(ROOT)}:{line_number}"
        assert PINNED_ACTION.fullmatch(target), f"mutable or malformed action at {location}: {target}"
        assert comment is not None and VERSION_COMMENT.fullmatch(comment), (
            f"missing human-readable version comment at {location}: {comment!r}"
        )
