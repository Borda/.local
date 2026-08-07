"""Build the canonical role-aware prompt used by live route calibration."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any


class Layout(str, Enum):
    """Instruction layout a calibration run reads its assets from.

    Subclasses ``str`` (not ``enum.StrEnum``) because ``requires-python`` is ``>=3.10``.
    The mixin keeps ``Layout.PLUGIN == "plugin"`` true, so the existing ``layout == "plugin"``
    comparisons throughout this package keep working whether they receive a member or a raw
    string from the CLI.

    Examples:
        >>> Layout.PLUGIN == "plugin"
        True
        >>> Layout("source") is Layout.SOURCE
        True
    """

    SOURCE = "source"
    PLUGIN = "plugin"


def prompt_sha256(prompt: str) -> str:
    """Return the canonical digest for an exact A/B prompt."""
    return hashlib.sha256(prompt.encode()).hexdigest()


def task_contract_sha256(task: dict[str, Any]) -> str:
    """Hash the canonical task contract, including fixtures and executable gate."""
    payload = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def candidate_findings(case_id: str, cases: dict[str, dict[str, Any]]) -> list[str]:
    """Build stable expected-plus-distractor choices without leaking labels."""
    expected = list(cases[case_id]["expected_findings"])
    other = sorted(
        finding
        for other_id, case in cases.items()
        if other_id != case_id
        for finding in case["expected_findings"]
        if finding not in expected
    )
    offset = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % len(other)
    distractors = [other[(offset + index) % len(other)] for index in range(4)]
    return sorted(set(expected + distractors))


def role_context(root: Path, role: str, layout: Layout | str = Layout.SOURCE) -> str:
    """Load canonical role instructions for a source or installed plugin layout.

    Args:
        root: Asset root the layout is resolved against.
        role: Role identifier whose instructions are loaded.
        layout: Which layout to read. Accepts a `Layout` member or its plain string value —
            callers passing a raw CLI string stay supported via the `str` mixin.
    """
    layout = Layout(layout)  # rejects unknown values at the boundary
    if layout == Layout.PLUGIN:
        role_path = root / "roles" / role / "ROLE.md"
        instructions = role_path.read_text(encoding="utf-8")
        if not instructions.strip():
            raise ValueError(f"role instructions missing: {role}")
        return f"Canonical {role} role card:\n{instructions}"

    global_instructions = (root / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    role_text = (root / ".codex" / "agents" / f"{role}.toml").read_text(encoding="utf-8")
    match = re.search(r'^developer_instructions\s*=\s*"""(.*?)"""\s*$', role_text, re.MULTILINE | re.DOTALL)
    instructions = match.group(1) if match else ""
    if not instructions.strip():
        raise ValueError(f"role instructions missing: {role}")
    return f"Global project instructions:\n{global_instructions}\n\nRegistered {role} instructions:\n{instructions}"


def build_prompt(
    case: dict[str, Any], candidates: list[str], task: dict[str, Any], registered_role_context: str
) -> str:
    """Build the exact prompt shared by baseline, candidate, and scorer."""
    evidence_scope = task.get("evidence_scope", "classification")
    if evidence_scope == "tool-use":
        instruction = (
            "Work in the provided isolated repository. "
            f"{task['task_prompt']} Return only the requested JSON object as the final response."
        )
    elif evidence_scope == "classification":
        instruction = (
            "This is a read-only behavioral calibration. Assess the scenario and select every valid finding ID "
            "from the allowed list. Do not select unsupported IDs. Return only the requested JSON object."
        )
    else:
        raise ValueError(f"unsupported evidence_scope: {evidence_scope!r}")
    return (
        f"{registered_role_context}\n\nCalibration task:\n{instruction}\n\nScenario:\n{case['prompt']}"
        "\n\nAllowed finding IDs:\n" + "\n".join(f"- {finding}" for finding in candidates)
    )
