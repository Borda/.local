<!-- file: capability-contract.md — consumers: plugins/codemap-py/claude-skills/*/SKILL.md, plugins/codemap-py/codex-skills/*/SKILL.md, tests/integration/test_skill_parity.py -->

# Codemap-py capability contract — v1

Single source of truth-claims for the six `codemap-py` skills, shared by both runtime rosters
(`claude-skills/`, `codex-skills/`). Authoritative per plan §8.2: runtime skills may differ in
invocation syntax and tool bindings but **must not** differ in truth claims — inputs, outputs, exit
codes, completeness metadata, or caveats. `tests/integration/test_skill_parity.py` diffs both
rosters against this file; a runtime skill that adds an undocumented capability, drops a documented
one, or states a stronger/weaker guarantee than listed here fails parity.

Full state/CLI authority: `.plans/active/plan_codemap-py-dual-runtime-package.md` §7.5 (exit codes),
§8.2 (skill parity table), §8.3 (integration skill — see `integration-contract.md`). This file does
not re-derive those sections; it enumerates the six skills' truth claims against them.

## Shared exit-code contract (§7.5)

All six skills' underlying CLI calls (`scan-index`, `scan-query`, `codemap-py integrate`) obey:

| Exit | Meaning | Output |
| --- | --- | --- |
| `0` | valid success, incl. valid empty/disconnected result | requested text or JSON |
| `1` | valid request cannot complete — index/domain/fs/runtime failure | bounded structured error, no traceback |
| `2` | invalid command syntax, option, value, or malformed batch input | one bounded usage/JSON error |
| `3` | requested module/symbol not indexed — distinct from valid empty result | parseable JSON error on stdout |
| `127` | no eligible CPython interpreter, incl. invalid `CODEMAP_PYTHON` or untested future minor | empty stdout, one actionable stderr line |

A skill's own pre-flight shell logic (e.g. an unsupported-flag check before the CLI is even
invoked) may take a shortcut exit path; that shortcut is skill-local UX, not a redefinition of the
underlying CLI's exit-code contract above. Both rosters' shortcut paths must reach the same
decision (reject vs proceed) for the same input, even if the intermediate exit code differs from
`2` before the pinned CLI surface (`integration.py`) lands.

## Completeness metadata (shared vocabulary)

Every `scan-query` result JSON carries an `index` block; all six skills interpret it identically:

- `index.method` — technique used (`static-ast`, `import-graph`, `index-lookup`, `ast-flags`).
- `index.not_covered` — list of what the method structurally misses; non-empty → surface as a
  scope caveat, never fill the gap by re-querying codemap.
- `index.hint` — actionable alternative when deeper coverage is needed.
- `index.confidence: "exact"` — result authoritative; skip verification caveats.
- `index.degraded` — count of modules that failed to parse; `>0` → some edges may be missing.
- `query_complete` (forward field) / `exhaustive` (legacy alias, one deprecation cycle) —
  direction-scoped completeness: `true` → result authoritative for that query's direction, stop
  querying/grepping; `false` → check `degraded_files`, `untracked_py`, `stale` before filling gaps.
- `stale` — index older than source; skills that self-heal (bounded inline `scan-index
  --incremental`) report whether the heal ran or was skipped (change set over cap, git unavailable).

Consumers may skip re-querying **only** when completeness is exhaustive/`query_complete: true`.

---

## Skill: `scan-codebase`

**Purpose**: build/refresh the Python structural JSON index (import graph + blast-radius metrics
+ symbol table) at `.cache/codemap/<project>.json` (or `$CODEMAP_INDEX_DIR/<project>.json`).

**Inputs**: `[--root <path>] [--incremental]`. No target/symbol arguments — whole-project scan.

**Outputs**: index JSON on disk; terminal summary (`N modules indexed, M degraded`); no stdout
JSON payload for programmatic consumption (that is `query-code`'s job).

**Exit codes**: `0` success (including empty-Python-project index); `1` scanner failure
(`scan-index` internal error); `2` unsupported flag rejected before the scanner runs.

**Completeness metadata**: post-scan summary reports `degraded` module count only — no per-file
list at this skill's surface (obtainable via `query-code` once indexed).

**Caveats**:
- Python only — non-`.py`/`.pyi` files never parsed, never silently counted as indexed.
- `--root <path>` names the index after `basename(path)`, distinct from the default git-root index;
  queries against the default index will not see a custom-root index unless invoked consistently
  with the same `--root`.
- Zero-Python project: index writes but is empty; downstream queries return no results, not an error.
- `--incremental` with no prior index falls back to a full scan (informational, not a failure).

**NOT for**: querying an existing index (`query-code`); integration health/wiring (`integration`).

---

## Skill: `query-code`

**Purpose**: read-only structural queries over the index — module deps/rdeps/central/coupled/path,
symbol-level source extraction, function call graph (fn-deps/fn-rdeps/fn-central/fn-blast), and the
extended quality/coverage/test-graph query family (`mock-rdeps`, `undocumented`, `uncovered`,
`import-types`, `xrefs`, `dead-symbols`, `dead-modules`, `subprocess-deps(-rdeps)`,
`fixture-rdeps`/`fixture-graph`, `coverage`/`coverage-gap`, `diff-impact`).

**Inputs**: one subcommand + target (`<module>`, `<qname>` as `module::symbol`, or none for
`central`/`coupled`); shared modifiers `--top N`, `--exclude-tests`, `--limit N`, `--with-imports`.

**Outputs**: JSON on stdout for every subcommand (never prose-only); the skill wrapper renders it
into the per-command table format documented in each roster's SKILL.md (list/pair/fenced-code/etc.
per subcommand — rendering choice is runtime-specific, not a truth claim).

**Exit codes**: `0` success incl. valid empty result (e.g. `path` → null with
`reason: "no-import-path"`); `1` index/runtime failure; `2` bad subcommand/flag; `3` requested
module/symbol not indexed; a query requiring a newer index generation than what's on disk exits
with a "requires vN+ index" message (upgrade path: re-run auto-build or `scan-codebase`).

**Completeness metadata**: full shared vocabulary above applies; this is the primary skill where
`query_complete`/`exhaustive`, `not_covered`, `degraded`, and `confidence` are consumed.

**Caveats**:
- Skip Codemap when an exact file and symbol are supplied for a localized edit and no caller, dependency, blast-radius, test-impact, import, or source-slice fact remains unresolved. An explicit structural query or tool requirement overrides this skip; otherwise choose the smallest complete query.
- Auto-builds/refreshes a missing or stale index unless `SCAN_NO_AUTOBUILD=1` is set, in which case
  a missing index is a hard refusal (exit non-zero) rather than a silent skip.
- Direction matters: `rdeps` = callers/blast-radius, `deps` = forward imports — swapping them is the
  most common misuse and is called out explicitly to both rosters.
- For requests for test modules that directly import a module, use `rdeps <module>` and filter/report test
  modules; reserve `test-impact <target>` for transitive affected-test selection.
- Symbol staleness: `stale: true` + empty source → fall back to a file read; `stale: false` + empty
  → source genuinely unavailable, re-scan required.
- Result truncation at 20 items is a real cap, not an exhaustive list, unless `--limit 0` is passed.

**NOT for**: index rebuild (`scan-codebase`); rename intent (`rename-refs`); non-Python repos.

---

## Skill: `test-impact`

**Purpose**: identify the minimal test set affected by a changed function or module via static
call/import graph traversal (no test execution); emits a ready-to-run `pytest` command.

**Inputs**: `<module::symbol | module> [--no-mocks]`. Function-level (`module::symbol`) does BFS
over the reverse call graph; module-level (bare `module`) does BFS over the reverse import graph.
Both include tests that mock the target (`mock_patches`) unless `--no-mocks` is passed.

**Outputs**: JSON with `test_files`, `pytest_cmd`, `via_call`/`via_mock` breakdown, `index` block.
Rendered as: affected-tests list + copy-pasteable pytest command + caveat line when applicable.

**Exit codes**: `0` success including `total == 0` (valid "no tests found" result, not an error);
`1` index build/query failure or non-JSON output from the underlying query; `2` no target supplied
and the interactive clarification path is unavailable (non-interactive runtime); `127` propagated
from a missing interpreter at the `scan-query` binary boundary.

**Completeness metadata**: `index.not_covered` surfaced as a caveat (dynamic dispatch, hook
callbacks, string-dispatch callers — same blind spot as `fn-blast`); this is a structural
limitation of static analysis, not a query-quality defect, and is never closed by grepping.

**Caveats**:
- Accepts exactly one symbol/module per invocation; multiple space-separated tokens use only the
  first — the discarded remainder must be surfaced, never silently dropped.
- Underlying JSON may carry non-JSON prefix/suffix noise on some model tiers — the truth claim is
  "test-impact returns exactly the JSON payload's `test_files`/`pytest_cmd` fields," and a runtime
  that can't parse it must fail loudly (re-run/rebuild suggestion), never guess.

**NOT for**: enumerating all callers of a function (`query-code fn-blast`); running the identified
tests (identifies, does not execute).

---

## Skill: `rename-refs`

**Purpose**: atomic rename of a Python symbol or module across every statically discoverable site —
definition, `__all__` re-exports, import call sites (via `fn-rdeps`/`rdeps` + symbol line-range
narrowing), Sphinx docstring cross-refs (`:func:`/`:class:`/`:meth:`/`:mod:`/`:attr:`) — with
optional deprecated-alias (`--deprecate`) or hard-delete (`--remove-if-no-callers`) behavior.

**Inputs**: `symbol <old_qname> <new_qname> [--dry-run] [--deprecate[=<decorator>]] [--since <ver>]
[--removed-in <ver>] [--remove-if-no-callers]` or `module <old_module_path> <new_module_path>
[--dry-run]`. 1:1 renames only.

**Outputs**: in-place source edits (unless `--dry-run`); a blast-radius/confirmation report before
any edit; a re-scan-and-verify pass after edits; a final summary (files changed, call sites
updated, docstring refs updated, advisories for out-of-scope hits).

**Exit codes**: `0` rename applied and verified (or dry-run report written); `1` index missing/
staleness abort, symbol not found, or scan-index re-verify failure; `2` invalid subcommand/flag or
conflicting flags (`--deprecate` + `--remove-if-no-callers`); `3` zero matches for the target
symbol/module (distinct from a valid "renamed with zero callers" outcome, which is `0`).

**Completeness metadata**: gates every mutating action on the index's `exhaustive`/`stale` state —
`--remove-if-no-callers` refuses to fire unless the caller count is both `0` and exhaustive; a
non-exhaustive rename proceeds but the summary must carry the non-exhaustive caveat.

**Caveats** (static-analysis hard limits — not fixable by this skill, must be surfaced, never
silently missed):
- `getattr(obj, "old_name")` string-bound dispatch — not statically tracked; grep advisory emitted.
- Cross-repo callers — out of scope; recommend `--deprecate` + semver bump for public APIs.
- ABC/Protocol subclass overrides — not tracked by static import analysis; must be reviewed and
  renamed manually via `fn-rdeps` inspection.
- Caller count > 50 → edit pass capped at first 50; the remainder is written to a full-list report
  file, never silently dropped.

**NOT for**: building the index (`scan-codebase`); querying without rename intent (`query-code`);
non-Python files; 1:N symbol splits; package-directory rename (use `git mv` directly). No
`--index <path>` override — always operates against the default project index.

---

## Skill: `integration`

**Purpose**: runtime adapter over the `codemap-py integrate` pinned CLI surface — audit, plan,
source-wire, locally sync, and demonstrate the supported consumer set. Full contract:
`integration-contract.md` (this directory) — this entry only states the skill-level truth claims
that must hold identically across both runtime adapters.

**Inputs**: one mode — `check [--runtime {claude,codex,both}] [--json]` / `plan [--runtime ...]
[--consumers <csv>] [--source {local-candidate,release}] [--out <artifact>]` / `apply --plan
<artifact> --approve <sha256>` / `sync --source {local-candidate,release} --plan <artifact>
--approve <sha256> [--runtime ...]` / `demo [--runtime ...]`.

**Outputs**: `check` → health report (installed/active versions, roots, protocol compatibility,
Codex-Rig global-instruction status when verifiable, shared-index identity, log isolation);
`plan` → a report artifact (never mutates); `apply`/`sync` → mutation + verification result +
journal entry; `demo` → check output + representative plain-vs-structural-context evidence.

**Exit codes**: per §7.5, same table as above; `check`/`plan` are zero-write and always exit `0`
on a successfully *completed* inspection even when the reported state is unhealthy (unhealthy
state is data in the report, not a process failure) — `1`/`2` are reserved for the inspection or
planning process itself failing (fs/runtime error, bad syntax).

**Completeness metadata**: `check` reports `split_index_roots` when the two runtime environments
resolve different index paths; reports Codex-Rig global-instruction status as only `absent`,
`present`, or `authenticated` from verifiable bytes — never `stale` without a versioned Codex-Rig-
owned read-only status contract, and never guessed.

**Caveats**: `--approve` is valid only with an explicit mutation mode, a saved plan artifact, and
the displayed SHA-256; it never authorizes new targets, remote publication, git/marketplace
mutation, or deletion. Both runtime adapters target the same closed consumer set (see
`integration-contract.md`) — neither adapter may invoke the other host runtime's model.

**NOT for**: structural queries (`query-code`); explicit standalone index rebuild outside of a
side-effect build during `plan`/`sync` bring-up.

---

## Skill: `debrief-coding`

**Purpose**: read-only diagnostic/usage report over local codemap telemetry
(`.cache/codemap/logs/*.jsonl`) — subcommand distribution, timing, coverage gaps, error patterns,
skill-invocation counts, session timelines, and avoidance-event (guard-chain leak) rate.

**Inputs**: `[--since <YYYY-MM-DD>] [--session <id>] [--anonymize] [--output <path>]`.

**Outputs**: a markdown report, default `.reports/codemap/debrief-<YYYY-MM-DD>.md`; with
`--anonymize`, pseudonymized copies under `.cache/codemap/export/` are read instead of raw logs,
and the report never includes the reversibility salt.

**Exit codes**: `0` report written (including a report over zero matching records after a filter
narrows to nothing); `1` no telemetry found at all (nothing to report), anonymize requested with
no source logs present, or report-write failure.

**Completeness metadata**: not index-completeness in the query sense — this skill reports its own
data-completeness caveats explicitly: "session not found in `<file>`" when a `--session` filter
matches zero records in one log layer (expected when that layer never logged the session, not a
data-loss condition); "scripted/polluted records excluded: N" when benchmark/test-suite noise is
filtered from organic-usage stats.

**Caveats**: telemetry is sharded per-session (`cli_<session>.jsonl`, `skills_<session>.jsonl`,
`tools_<session>.jsonl`) with a legacy unsuffixed fallback (`cli.jsonl`, etc.) for runs with no
seeded session ID; a report must aggregate **all** matching shards, never just the legacy file, or
it silently under-reports. All logs and the anonymization salt stay local to
`.cache/codemap/logs/` — the salt is never included in shareable output.

**NOT for**: validating codemap installation health (`integration check`); building/querying the
structural index (`scan-codebase`/`query-code`).

---

## Parity requirements (§8.2)

- Both runtime rosters expose exactly these six skill names — no extra, none missing.
- A parity test rejects: a missing skill, a stale command/subcommand name, a runtime-specific
  filesystem path presented as if portable, or a truth claim in one roster that contradicts (is
  strictly stronger or weaker than) the corresponding entry in this file.
- Runtime-specific latitude: invocation syntax (`/codemap-py:<skill>` vs `$codemap-py:<skill>`),
  tool bindings (Claude `Bash`/`Read`/`Write`/`Skill`/`AskUserQuestion` vs Codex's resolved
  plugin-root path convention), and result-injection/wording differences per the plan §8.2 table.
- Every runtime-specific instruction in a roster's SKILL.md must have an executable or inspection
  oracle behind it — no unverifiable prose claim about what a command does.

## Confidence

**Score**: 0.88 — moderate ⚠
orchestrator may re-run with the specific gap addressed
**Gaps**:
- `integration` skill's exit-code row for `check`/`plan` is written against the *target* pinned CLI
  surface (delivery-plan.md's Wave-1 contract), not the currently-committed `claude-skills/
  integration/SKILL.md` (which still implements the legacy `check|init|demo` modes pending Wave 2's
  rewrite by slice D) — intentional per the assignment ("truth-claim source both runtimes' skills
  must not contradict," forward-referencing the pinned surface both C and D code to), but a reader
  diffing this file against the current on-disk integration skill today will see a mismatch until
  Wave 2 lands.
- Exact skill-level exit codes for `scan-codebase`/`rename-refs` unsupported-flag paths are read
  from the current SKILL.md's own bash (`exit 1`), which does not literally match §7.5's `2` for
  invalid syntax; documented as skill-local shortcut UX rather than silently reconciled or hidden.

**Refinements**: 1 pass.
- Pass 1: added the explicit caveat paragraph under the exit-code table distinguishing skill-local
  shell shortcuts from the underlying CLI's §7.5 contract, after noticing the scan-codebase/
  rename-refs SKILL.md text uses `exit 1` for what §7.5 defines as a `2`-class syntax error.
