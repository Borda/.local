"""Skill-roster + truth-claim parity between ``claude-skills/`` and ``codex-skills/`` (plan §8.2).

Black-box against on-disk ``SKILL.md`` files and ``shared/capability-contract.md`` — the single
source of truth-claims both runtime rosters must not contradict (per that file's own header).
Comparator helpers here are exercised positively against the real rosters (must pass with zero
violations) and negatively against synthetic fixture rosters built under ``tmp_path`` (missing
skill, stale command name, unsupported cache path, contradictory limit) — real plugin files are
never mutated to prove the negative paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_SKILLS_DIR = _PLUGIN_ROOT / "claude-skills"
_CODEX_SKILLS_DIR = _PLUGIN_ROOT / "codex-skills"
_CAPABILITY_CONTRACT = _PLUGIN_ROOT / "shared" / "capability-contract.md"
_INTEGRATION_CONTRACT = _PLUGIN_ROOT / "shared" / "integration-contract.md"
_CODEX_MANIFEST = _PLUGIN_ROOT / ".codex-plugin" / "plugin.json"

_CANONICAL_SKILLS = {"scan-codebase", "query-code", "test-impact", "rename-refs", "integration", "debrief-coding"}

_NOT_FOR_RE = re.compile(
    r"(?:NOT for|Skip for|SKIP)\s*:\s*(.+?)(?:\n[ \t]*\n|</objective>|\Z)", re.IGNORECASE | re.DOTALL
)
_SKILL_REF_RE = re.compile(r"[/$]codemap-py:([a-z][a-z-]*)")


# Query routing is a product contract, not merely documentation style.  Both
# surfaces must steer the model to the same supported high-leverage command.
_QUERY_CODE_REQUIRED_SNIPPETS = (
    "most-imported modules / highest in-degree | `central --top n`",
    "internal-import coupling (not centrality)",
    "fn-blast <module::symbol>",
    "never `--depth`",
    "never invent flags",
    "ordinary repository reads remain allowed",
    "distinct independent ast/oracle view",
)
_QUERY_CODE_FORBIDDEN_SNIPPETS = ("fn-blast <module::symbol> --depth",)


# --------------------------------------------------------------------------------------
# Roster exactness.
# --------------------------------------------------------------------------------------


def _skill_roster(skills_dir: Path) -> set[str]:
    """Return skill names with a ``SKILL.md`` directly under *skills_dir*."""
    if not skills_dir.is_dir():
        return set()
    return {p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}


def _roster_violations(claude_dir: Path, codex_dir: Path, canonical: set[str]) -> list[str]:
    """Return roster-exactness violations: missing/extra skills vs *canonical*, and cross-roster mismatch."""
    violations: list[str] = []
    rosters = {"claude": _skill_roster(claude_dir), "codex": _skill_roster(codex_dir)}
    for label, roster in rosters.items():
        missing = canonical - roster
        extra = roster - canonical
        if missing:
            violations.append(f"{label} roster missing skill(s): {sorted(missing)}")
        if extra:
            violations.append(f"{label} roster has undocumented extra skill(s): {sorted(extra)}")
    if rosters["claude"] != rosters["codex"]:
        violations.append(f"roster mismatch: claude={sorted(rosters['claude'])} codex={sorted(rosters['codex'])}")
    return violations


def test_real_rosters_are_exact() -> None:
    """Both real rosters expose exactly the six canonical skill names — no extra, none missing."""
    assert _roster_violations(_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR, _CANONICAL_SKILLS) == []


def test_codex_manifest_advertises_skills_dir() -> None:
    """The Codex manifest declares the ``codex-skills/`` roster path (Phase 4, six-skill roster)."""
    manifest = json.loads(_CODEX_MANIFEST.read_text())
    assert manifest["skills"] == "./codex-skills/"


@pytest.mark.parametrize(
    ("mutation", "expected_substring"),
    [
        pytest.param("remove_claude_skill", "claude roster missing", id="missing-skill"),
        pytest.param("extra_codex_skill", "codex roster has undocumented extra", id="extra-skill"),
    ],
)
def test_roster_checker_rejects_synthetic_violations(tmp_path: Path, mutation: str, expected_substring: str) -> None:
    """The roster checker itself rejects a missing skill and an undocumented extra skill."""
    claude_dir = tmp_path / "claude-skills"
    codex_dir = tmp_path / "codex-skills"
    for name in _CANONICAL_SKILLS:
        (claude_dir / name).mkdir(parents=True)
        (claude_dir / name / "SKILL.md").write_text("---\nname: x\n---\nbody\n")
        (codex_dir / name).mkdir(parents=True)
        (codex_dir / name / "SKILL.md").write_text("---\nname: x\n---\nbody\n")

    if mutation == "remove_claude_skill":
        skill_dir = claude_dir / "query-code"
        (skill_dir / "SKILL.md").unlink()
        skill_dir.rmdir()
    elif mutation == "extra_codex_skill":
        (codex_dir / "bogus-extra-skill").mkdir()
        (codex_dir / "bogus-extra-skill" / "SKILL.md").write_text("---\nname: bogus\n---\n")

    violations = _roster_violations(claude_dir, codex_dir, _CANONICAL_SKILLS)
    assert any(expected_substring in v for v in violations)


# --------------------------------------------------------------------------------------
# Truth-claim parity — pinned CLI mode/exit table (integration skill; verbatim by design).
# --------------------------------------------------------------------------------------


def _extract_mode_table(text: str) -> str:
    """Return the pinned five-mode CLI table's rows, verbatim, stopping at the first non-row line."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("| Mode") and "Exit" in line)
    rows: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        rows.append(stripped)
    header_plus_separator = 2
    assert len(rows) >= header_plus_separator, "pinned-CLI mode/exit table too short"
    return "\n".join(rows)


def test_integration_mode_table_matches_across_runtimes() -> None:
    """The pinned five-mode CLI table is byte-identical between the Claude and Codex integration skills."""
    claude_text = (_CLAUDE_SKILLS_DIR / "integration" / "SKILL.md").read_text()
    codex_text = (_CODEX_SKILLS_DIR / "integration" / "SKILL.md").read_text()
    assert _extract_mode_table(claude_text) == _extract_mode_table(codex_text)


def test_integration_mode_table_matches_shared_contract() -> None:
    """Both runtime skills' mode table matches the shared ``integration-contract.md`` source of truth."""
    contract_text = _INTEGRATION_CONTRACT.read_text()
    claude_text = (_CLAUDE_SKILLS_DIR / "integration" / "SKILL.md").read_text()
    assert _extract_mode_table(contract_text) == _extract_mode_table(claude_text)


def test_mode_table_checker_rejects_stale_command_name() -> None:
    """The mode-table comparator rejects a stale mode name (e.g. a retired ``check|init|demo`` model)."""
    current = (_CLAUDE_SKILLS_DIR / "integration" / "SKILL.md").read_text()
    stale = current.replace("`plan`", "`init`", 1)
    assert _extract_mode_table(current) != _extract_mode_table(stale)


# --------------------------------------------------------------------------------------
# Truth-claim parity — cross-referenced skill names in NOT-for/Skip-for clauses.
# --------------------------------------------------------------------------------------


def _not_for_skill_refs(full_text: str) -> set[str]:
    """Union of skill names cross-referenced by every NOT-for/Skip-for clause in *full_text*.

    Deliberately tolerant of prose-wording differences (explicitly allowed latitude per
    capability-contract.md's parity requirements) — only *which skill* is referenced counts.
    """
    refs: set[str] = set()
    for clause in _NOT_FOR_RE.findall(full_text):
        refs |= set(_SKILL_REF_RE.findall(clause))
    return refs


@pytest.mark.parametrize("skill_name", sorted(_CANONICAL_SKILLS))
def test_not_for_references_match_across_runtimes(skill_name: str) -> None:
    """Each skill's NOT-for/Skip-for clauses defer to the same other skills in both rosters."""
    claude_text = (_CLAUDE_SKILLS_DIR / skill_name / "SKILL.md").read_text()
    codex_text = (_CODEX_SKILLS_DIR / skill_name / "SKILL.md").read_text()
    claude_refs = _not_for_skill_refs(claude_text)
    codex_refs = _not_for_skill_refs(codex_text)
    assert claude_refs, f"{skill_name}: no NOT-for/Skip-for skill reference found in claude-skills"
    assert codex_refs, f"{skill_name}: no NOT-for/Skip-for skill reference found in codex-skills"
    assert claude_refs == codex_refs
    assert claude_refs <= _CANONICAL_SKILLS, f"{skill_name}: claude NOT-for references unknown skill(s)"
    assert codex_refs <= _CANONICAL_SKILLS, f"{skill_name}: codex NOT-for references unknown skill(s)"


def test_not_for_checker_rejects_contradictory_reference() -> None:
    """The NOT-for comparator rejects two rosters deferring to a different skill for the same claim."""
    claude_text = "NOT for: renaming symbols (use `/codemap-py:rename-refs`)."
    codex_text = "NOT for: renaming symbols (use `$codemap-py:query-code`)."
    assert _not_for_skill_refs(claude_text) != _not_for_skill_refs(codex_text)


def test_not_for_checker_rejects_unsupported_cache_path_masquerading_as_skill_ref() -> None:
    """A contradictory limit — one roster naming a skill the other omits — is detected as a real mismatch."""
    claude_text = "NOT for: index rebuild (use `/codemap-py:scan-codebase`)."
    codex_text = "NOT for: index rebuild — no equivalent skill; edit `~/.claude/plugins/cache/foo` directly."
    assert _not_for_skill_refs(claude_text) != _not_for_skill_refs(codex_text)


# --------------------------------------------------------------------------------------
# Query-code routing parity — prevent expensive, incorrect substitutes.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_routes_centrality_and_transitive_blast_to_supported_commands(runtime_dir: Path) -> None:
    """Keep centrality and transitive caller requests off coupling and invented flags."""
    skill_text = (runtime_dir / "query-code" / "SKILL.md").read_text(encoding="utf-8").lower()

    assert all(snippet in skill_text for snippet in _QUERY_CODE_REQUIRED_SNIPPETS)
    assert all(snippet not in skill_text for snippet in _QUERY_CODE_FORBIDDEN_SNIPPETS)
