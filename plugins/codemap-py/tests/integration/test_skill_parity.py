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
from fnmatch import fnmatchcase
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
    "choose the smallest complete query set",
    "production module importers / blast radius | `rdeps <module> --exclude-tests`",
    "production centrality / highest in-degree | `central --top n --exclude-tests`",
    "internal-import coupling (not centrality)",
    "direct production callers | `fn-rdeps <module::symbol> --exclude-tests`",
    "transitive callers / function blast | `fn-blast <module::symbol>`",
    "broken sphinx cross-references | `xrefs --broken <module>`",
    "never `--depth`",
    "never invent flags",
    "ordinary repository reads remain allowed",
    "distinct independent ast/oracle view",
)
_QUERY_CODE_FORBIDDEN_SNIPPETS = ("fn-blast <module::symbol> --depth",)
_DIRECT_CALLER_ROUTING_RULE = (
    "for caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, "
    "and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive "
    "callers, closure, hops, or all levels."
)
_DIRECT_TEST_IMPORT_ROUTING_SNIPPETS = (
    "directly import a module",
    "`rdeps <module>`",
    "filter/report test modules",
    "reserve `test-impact <target>` for transitive affected-test selection",
)
_CALLER_AND_TEST_IMPORT_ROUTING_SNIPPETS = (
    "callers plus test-module importers",
    "`fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>`",
)
_SYMBOL_TARGET_GRAMMAR_SNIPPETS = (
    "`symbol <name>` accepts a bare function name",
    "`authenticate`",
    "`myclass.method`",
    "`module::symbol` belongs to `fn-*` call-graph queries",
    "query the requested qualified extension method",
    "`symbol myclass.add_feature`",
    "not a nearby `symbol myclass` or `symbols <module>` listing",
)
_SYMBOL_TO_CALL_GRAPH_CHAINING_SNIPPETS = (
    "qualified_name",
    "<module>::<qualified_name>",
    "mypackage.module::myclass.method",
)
_OVERRIDE_CANDIDATE_SNIPPETS = (
    "find-symbol '<classsuffix>\\.<method>$' --exclude-tests --limit 0",
    "same-name implementation/override candidates",
    "name matching is candidate discovery only, not proof of inheritance",
    "verify ancestry and package boundaries",
)
_LOCALIZED_EDIT_ROUTING_SNIPPETS = (
    "exact file",
    "symbol",
    "localized",
    "skip codemap",
    "caller",
    "dependency",
    "blast radius",
    "test impact",
    "import",
    "source slice",
    "explicit structural",
    "tool requirement",
    "override",
    "smallest complete query",
)
_CLAUDE_QUERY_CURRENT_REPOSITORY_SNIPPETS = (
    "run every query from the caller's current repository",
    "codemap-py query --compact <subcommand> [arguments]",
    "do not `cd` into `$claude_plugin_root`",
)
_CLAUDE_QUERY_COMMAND_LITERAL = "codemap-py query --compact <subcommand> [arguments]"
_CLAUDE_QUERY_BASH_PATTERNS = (
    "codemap-py query:*",
    "*/bin/codemap-py* query:*",
)
_CLAUDE_QUERY_ALLOWED_TOOLS = "allowed-tools: Bash(codemap-py query:*), Bash(*/bin/codemap-py* query:*), Read, Write"
_QUERY_PATH_BASE_SNIPPETS = (
    "complete-query paths are caller-repo-relative",
    "never skill-relative",
    "do not re-query/read/grep",
)


def _direct_caller_routing_violations(skill_text: str) -> list[str]:
    """Return a violation when ambiguous caller wording can select a transitive query."""
    if _DIRECT_CALLER_ROUTING_RULE in skill_text.lower():
        return []
    return ["ambiguous direct-caller wording lacks the fn-rdeps routing rule"]


def _claude_query_current_repository_violations(skill_text: str) -> list[str]:
    """Return violations when the Claude query skill can leave the caller repository."""
    normalized = skill_text.lower()
    violations = [
        f"missing current-repository query contract: {snippet}"
        for snippet in _CLAUDE_QUERY_CURRENT_REPOSITORY_SNIPPETS
        if snippet.lower() not in normalized
    ]
    if re.search(r"(?m)^\s*cd\s+", skill_text):
        violations.append("forbidden current-directory change in query-code command")
    return violations


def _claude_query_frontmatter_violations(skill_text: str) -> list[str]:
    """Return violations when query-code can invoke arbitrary Bash instead of its read-only CLI surface."""
    frontmatter = skill_text.split("---", 2)[1]
    if _CLAUDE_QUERY_ALLOWED_TOOLS in frontmatter:
        return []
    return ["query-code must allow only the PATH or installed absolute `codemap-py query` launchers, Read, and Write"]


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


@pytest.mark.parametrize(
    "contract_path",
    (
        _CLAUDE_SKILLS_DIR / "query-code" / "SKILL.md",
        _CODEX_SKILLS_DIR / "query-code" / "SKILL.md",
        _CAPABILITY_CONTRACT,
    ),
    ids=("claude", "codex", "shared-contract"),
)
def test_query_code_skips_fully_localized_edits_but_preserves_explicit_structural_routing(
    contract_path: Path,
) -> None:
    """Avoid retrieval with no unresolved fact while preserving explicit and structural demand."""
    skill_text = " ".join(contract_path.read_text(encoding="utf-8").lower().replace("-", " ").split())

    assert all(snippet in skill_text for snippet in _LOCALIZED_EDIT_ROUTING_SNIPPETS)


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_routes_ambiguous_caller_requests_to_direct_production_callers(runtime_dir: Path) -> None:
    """Prevent `fn-blast` for direct caller requests phrased as a blast radius or every caller."""
    skill_text = (runtime_dir / "query-code" / "SKILL.md").read_text(encoding="utf-8").lower()

    assert _direct_caller_routing_violations(skill_text) == []


@pytest.mark.parametrize(
    "contract_path",
    (
        _CLAUDE_SKILLS_DIR / "query-code" / "SKILL.md",
        _CODEX_SKILLS_DIR / "query-code" / "SKILL.md",
        _CAPABILITY_CONTRACT,
    ),
    ids=("claude", "codex", "shared-contract"),
)
def test_query_code_resolves_result_paths_from_the_callers_repository(contract_path: Path) -> None:
    """Prevent complete query results from being re-read relative to an installed Skill directory."""
    skill_text = " ".join(contract_path.read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _QUERY_PATH_BASE_SNIPPETS)


def test_direct_caller_routing_contract_rejects_transitive_substitute() -> None:
    """Ensure a plausible `fn-blast` substitute cannot satisfy the direct-caller routing contract."""
    wrong_rule = _DIRECT_CALLER_ROUTING_RULE.replace(
        "`fn-rdeps <module::symbol> --exclude-tests`", "`fn-blast <module::symbol>`"
    )

    assert _direct_caller_routing_violations(wrong_rule) == [
        "ambiguous direct-caller wording lacks the fn-rdeps routing rule"
    ]


def test_claude_query_code_runs_from_the_callers_repository() -> None:
    """Keep installed-plugin execution from redirecting structural queries into the plugin checkout."""
    skill_text = (_CLAUDE_SKILLS_DIR / "query-code" / "SKILL.md").read_text(encoding="utf-8")

    assert _claude_query_current_repository_violations(skill_text) == []


def test_claude_current_repository_contract_rejects_plugin_root_directory_change() -> None:
    """Prove the launcher stays safe only while the caller repository remains the working directory."""
    stale = 'cd "$CLAUDE_PLUGIN_ROOT"\n"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact rdeps package.module'

    violations = _claude_query_current_repository_violations(stale)

    assert any("forbidden current-directory change" in violation for violation in violations)


def test_claude_query_code_limits_bash_to_the_query_cli() -> None:
    """Prevent query-code from rebuilding indexes or using unrelated shell recovery commands."""
    skill_text = (_CLAUDE_SKILLS_DIR / "query-code" / "SKILL.md").read_text(encoding="utf-8")

    assert _claude_query_frontmatter_violations(skill_text) == []


def test_claude_query_permission_pattern_matches_the_literal_path_launcher() -> None:
    """Ensure the restricted Bash pattern admits the non-expanding primary command."""
    command_pattern = f"{_CLAUDE_QUERY_BASH_PATTERNS[0].removesuffix(':*')}*"

    assert fnmatchcase(_CLAUDE_QUERY_COMMAND_LITERAL, command_pattern)
    assert not fnmatchcase(_CLAUDE_QUERY_COMMAND_LITERAL.replace(" query ", " index "), command_pattern)


def test_claude_query_frontmatter_rejects_unrestricted_bash() -> None:
    """Prove the frontmatter contract rejects the historical unrestricted Bash allowance."""
    stale = "---\nallowed-tools: Bash, Read, Write\n---\n"

    assert _claude_query_frontmatter_violations(stale) == [
        "query-code must allow only the PATH or installed absolute `codemap-py query` launchers, Read, and Write"
    ]


@pytest.mark.parametrize(
    "contract_path",
    (
        _CLAUDE_SKILLS_DIR / "query-code" / "SKILL.md",
        _CODEX_SKILLS_DIR / "query-code" / "SKILL.md",
        _CAPABILITY_CONTRACT,
    ),
    ids=("claude", "codex", "shared-contract"),
)
def test_query_code_routes_direct_test_importers_to_module_rdeps(contract_path: Path) -> None:
    """Keep direct test-module importer requests on ``rdeps`` in every truth-claim surface."""
    skill_text = " ".join(contract_path.read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _DIRECT_TEST_IMPORT_ROUTING_SNIPPETS)


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_allows_two_queries_when_one_answer_requires_callers_and_test_importers(runtime_dir: Path) -> None:
    """Keep a one-query optimization from dropping an independently required result set."""
    skill_text = " ".join((runtime_dir / "query-code" / "SKILL.md").read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _CALLER_AND_TEST_IMPORT_ROUTING_SNIPPETS)


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_preserves_symbol_target_grammar_for_feature_scaffolding(runtime_dir: Path) -> None:
    """Feature scaffolding queries the named method, not a nearby class or module inventory."""
    skill_path = runtime_dir / "query-code" / "SKILL.md"
    skill_text = " ".join(skill_path.read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _SYMBOL_TARGET_GRAMMAR_SNIPPETS)


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_composes_symbol_results_for_function_call_queries(runtime_dir: Path) -> None:
    """Prevent a bare method suffix from wasting a call-graph query before the canonical target is retried."""
    skill_text = " ".join((runtime_dir / "query-code" / "SKILL.md").read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _SYMBOL_TO_CALL_GRAPH_CHAINING_SNIPPETS)


@pytest.mark.parametrize("runtime_dir", (_CLAUDE_SKILLS_DIR, _CODEX_SKILLS_DIR), ids=("claude", "codex"))
def test_query_code_qualifies_override_candidates_as_name_matches(runtime_dir: Path) -> None:
    """Require complete same-name candidate discovery plus explicit inheritance verification."""
    skill_text = " ".join((runtime_dir / "query-code" / "SKILL.md").read_text(encoding="utf-8").lower().split())

    assert all(snippet in skill_text for snippet in _OVERRIDE_CANDIDATE_SNIPPETS)


def test_readme_does_not_claim_fn_rdeps_returns_override_lists() -> None:
    """Keep README call-graph semantics distinct from same-name override candidate discovery."""
    readme_text = " ".join((_PLUGIN_ROOT / "README.md").read_text(encoding="utf-8").lower().split())

    assert "fn-rdeps` reports incoming call edges" in readme_text
    assert "complete override list in one call" not in readme_text
    assert all(snippet in readme_text for snippet in _OVERRIDE_CANDIDATE_SNIPPETS)
