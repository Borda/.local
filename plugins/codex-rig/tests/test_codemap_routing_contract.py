"""Pin the documented per-skill Codemap route selection against what the skills actually invoke.

``--query-kind`` is a per-workflow choice rather than a migration every consumer owes, so the contract records each
skill's decision in a table. These checks fail when a skill starts or stops selecting routes without moving its row,
which is the drift that made the adoption gap look like an unfinished rollout instead of a recorded choice.
"""

from __future__ import annotations

import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PLUGIN_ROOT / "shared" / "codemap-contract.md"
SKILLS_ROOT = PLUGIN_ROOT / "skills"
_ADAPTER_INVOCATION = "codemap_adapter.py context"
_ROUTE_ROW = re.compile(
    r"^\|\s*`(?P<skill>[a-z-]+)`\s*\|\s*`(?P<category>[a-z]+)`\s*\|\s*(?P<selection>[^|]+?)\s*\|",
    re.MULTILINE,
)


def documented_route_selection() -> dict[str, str]:
    """Return `{skill: selection}` parsed from the contract's route-selection table."""
    section = CONTRACT_PATH.read_text(encoding="utf-8").split("## Route selection per skill", 1)[1]
    table = section.split("\n\n## ", 1)[0]
    return {match["skill"]: match["selection"] for match in _ROUTE_ROW.finditer(table)}


def skills_invoking_adapter() -> dict[str, str]:
    """Return `{skill: adapter invocation line}` for every skill that calls the adapter."""
    invocations: dict[str, str] = {}
    for skill_file in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        for line in skill_file.read_text(encoding="utf-8").splitlines():
            if _ADAPTER_INVOCATION in line:
                invocations[skill_file.parent.name] = line
                break
    return invocations


def test_route_selection_table_covers_every_adapter_consuming_skill() -> None:
    """Keep the documented table and the real consumer set identical in both directions."""
    documented = documented_route_selection()

    assert set(documented) == set(skills_invoking_adapter())


def test_documented_selection_matches_each_skill_invocation() -> None:
    """Fail when a skill's documented route selection disagrees with its own invocation."""
    documented = documented_route_selection()
    invocations = skills_invoking_adapter()

    actual = {skill: "--query-kind" in line for skill, line in invocations.items()}
    expected = {skill: selection.startswith("adaptive") for skill, selection in documented.items()}

    assert actual == expected


def test_standard_batch_skills_are_the_documented_majority_choice() -> None:
    """Pin the recorded split so a silent flip of any row is a test failure, not a doc drift."""
    documented = documented_route_selection()

    adaptive = sorted(skill for skill, selection in documented.items() if selection.startswith("adaptive"))

    assert adaptive == ["implement", "investigate", "optimize"]
