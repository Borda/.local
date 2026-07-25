---
name: query-code
description: |
  Query the codemap structural index — module deps/rdeps/central/coupled/path, symbol-level source extraction,
  function call graph (fn-deps, fn-rdeps, fn-central, fn-blast), plus quality/coverage queries.
  Trigger with `$codemap-py:query-code <subcommand> ...` for: "what depends on", "who calls", "imports of",
  "dependency graph", "blast radius of", "list central modules".
  Skip for: rename intent (use `$codemap-py:rename-refs`); simple grep suffices; non-Python repo. Missing/stale
  index auto-builds — no manual scan-codebase needed.
---

# Query Code

Python import-graph + symbol queries via the codemap-py unified CLI's `query` subcommand.

Module: `central [--top N]`, `coupled [--top N]`, `deps <mod>`, `rdeps <mod>`, `path <from> <to>`
Symbol: `symbol <name> [--with-imports]`, `symbols <mod>`, `find-symbol <pattern>`
Function call-graph (v3 index): `fn-deps <qname>`, `fn-rdeps <qname>`, `fn-central [--top N]`, `fn-blast <qname>`
qname format: `mypackage.auth::validate_token`

NOT for: repo rebuild (use `$codemap-py:scan-codebase`); renaming symbols (use `$codemap-py:rename-refs`);
non-Python files.

## Runtime note

Codex has no `bin/` PATH entry and no `$CLAUDE_PLUGIN_ROOT`-equivalent environment variable, so there is no PATH →
env-var → cache three-tier fallback to run here. Resolve this skill's installed plugin-root path once, substitute
it for `PLUGIN_ROOT` below, and invoke the unified CLI directly:

```bash
PLUGIN_ROOT/bin/codemap-py query <subcommand> <args>
```

Shell state does not persist across tool calls — keep the resolved path in reasoning, not a shell variable.

## Step 0: Index freshness (once per task)

```bash
PLUGIN_ROOT/bin/codemap-py query central --top 1 >/dev/null 2>&1; echo $?
```

A missing index reports a resolvable error; distinguish "index missing" from "index present but query failed" by
the error body, not just the exit code.

Auto-build opt-out via `SCAN_NO_AUTOBUILD=1` (queries run against the index exactly as-is — no refresh, no full
build); echo build wall-time when a build runs, to keep build cost separable from query cost.

- Index present → refresh in place (honors the opt-out):

```bash
PLUGIN_ROOT/bin/codemap-py index --incremental
```

- Index missing and `SCAN_NO_AUTOBUILD=1` → refuse:

```text
codemap index missing and SCAN_NO_AUTOBUILD=1 — refusing to auto-build.
Build it manually first: $codemap-py:scan-codebase
```

- Index missing and auto-build not opted out → run `PLUGIN_ROOT/bin/codemap-py index` in the foreground, wait for
  it to finish, then proceed.
- Resolution genuinely fails (not just "missing") → surface the error and stop.

## Step 1: Query

**Direction — choose before calling:**

- `rdeps <mod>` — callers: what imports X, blast radius of X
- `deps <mod>` — forward: what X imports

Common mistake: "modules affected if X changes" = `rdeps` (callers), not `deps`.

```bash
PLUGIN_ROOT/bin/codemap-py query rdeps "mypackage.auth"
PLUGIN_ROOT/bin/codemap-py query symbol "MyClass.method" --with-imports
PLUGIN_ROOT/bin/codemap-py query fn-rdeps "mypackage.auth::validate_token"
```

| Goal | Command |
| --- | --- |
| callers / blast radius | `rdeps <mod> [--exclude-tests]` |
| forward deps | `deps <mod>` |
| central modules | `central --top 10` |
| import path | `path <from> <to>` |
| symbol source | `symbol <name> [--with-imports]` |
| all symbols in module | `symbols <mod>` |
| symbol search | `find-symbol <pattern>` |
| outgoing calls | `fn-deps module::function` |
| incoming calls | `fn-rdeps module::function [--exclude-tests]` |
| blast radius of current git change set | `diff-impact [--base REF]` |

**Quality / coverage / test-graph queries** (each needs the index version noted — auto-build upgrades):

| Goal | Command | Min index |
| --- | --- | --- |
| test files that mock a symbol via `patch()` | `mock-rdeps <mod::sym \ | mod>` | v4.1 |
| public symbols missing a docstring | `undocumented [<mod>] [--all]` | v4.4 |
| public symbols with no test callers and no mocks | `uncovered [<mod>] [--all] [--sort loc\ | name\ | module] [--top N]` | v4.2 |
| stdlib / third-party / internal import groups | `import-types <mod>` | v4.3 |
| doc xrefs for a symbol / find broken refs | `xrefs <qname>` · `xrefs <mod> --broken` | v4.5 |
| public symbols with zero callers anywhere | `dead-symbols [--min-loc N]` | v4.6 |
| modules with zero external importers | `dead-modules` | v4.6 |
| what a module spawns as a subprocess | `subprocess-deps <mod>` | v5.2 |
| what spawns a module as a subprocess | `subprocess-rdeps <mod>` | v5.2 |
| test files that use a pytest fixture | `fixture-rdeps <fixture-name>` | v5.3 |
| fixture dependency tree for a test file | `fixture-graph <test-file>` | v5.3 |
| `coverage_pct` + `covered_by` for a symbol / module | `coverage <mod::sym \ | mod>` | v5.4 |
| symbols below a coverage threshold | `coverage-gap [<mod>] [--all] [--threshold P]` | v5.4 |

Missing/old index → the query needing a newer version exits with a "requires vN+ index" message; re-run auto-build
(Step 0) or `$codemap-py:scan-codebase` to upgrade. Anything not listed here — `codemap-py query --help` has the
full reference.

**`query_complete: true` → STOP ALL TOOL CALLS.** The list is complete and authoritative for THIS query's
direction. Write the answer immediately. Do not query again, and do not grep/glob/read to verify.
(`query_complete` is direction-scoped: a `deps`/`symbols` query on a healthy module can be complete even while
another file is degraded, but `rdeps`/`central`/`path` are complete only when `degraded: 0`. Legacy `exhaustive`
field mirrors `query_complete` for one deprecation cycle — prefer `query_complete`.)

**`query_complete: false`** → the result is direction-incomplete. Check `degraded_files` (files that failed to
parse — may hide edges), `untracked_py` (new files not yet tracked — invisible to staleness diffing), and `stale`;
verify with a search only for those named gaps.

Truncation check: result count = 20 and `--limit 0` not passed → re-run once with `--limit 0` (one budget slot),
then apply the STOP rule.

Budget: max 3 calls. Non-exhaustive after 3 → report what was found and stop.

`find-symbol`: Python regex — `^Auth.*Handler$` (anchored) or `auth` (substring). Escape `.` for a literal dot.
Always pass `--limit 0` when counting/ranking to avoid 20-item truncation.

Symbol staleness: `stale: true` with empty source → read the file directly as a fallback. `stale: false` with
empty source → source genuinely unavailable; re-run `$codemap-py:scan-codebase`.

Targeted edit (known symbol, file >~300 lines): `symbol <mod::name>` → take the line span → read only that slice
(with margin) → edit. Spans come from the index; if the file changed since the scan, spans may drift — fall back
to a full file read before editing when an edit fails to match.

## Step 2: Parse JSON and render

`codemap-py query` always emits JSON.

| Command | JSON key | Render as |
| --- | --- | --- |
| `rdeps`/`deps` | `imported_by`/`direct_imports` | list modules, one per line |
| `central`/`coupled` | `central`/`coupled` array | `name — N importers`, one per line |
| `path` | `path` array or null | `A → B → C`; null (with `reason: "no-import-path"`, exit 0) → "No import path found." |
| `symbol` | `symbols[].source` | fenced code block; caption = module + line range |
| `symbols` | `symbols` array | `type name (lines start–end)`, one per line |
| `find-symbol` | `matches` array | `module:qualified_name (type)`, one per line |
| `fn-deps`/`fn-rdeps` | `calls`/`called_by` | `module::fn (resolution)`, one per line |
| `fn-central` | `fn_central` | `count module::fn`, one per line |
| `fn-blast` | `blast_radius` | `depth module::fn`, sorted by depth then name |
| `diff-impact` | `changed_modules` array | `module (risk) — changed symbols`, one per line; end with `test_impact.pytest_cmd` |

`index.stale: true` → the query already attempted a bounded inline self-heal (`index --incremental`) before
answering; `stale` remaining true means the heal was skipped (change set over cap, or git unavailable). Re-run
`$codemap-py:scan-codebase --incremental` manually, then retry.
`index.not_covered` non-empty → note the scope caveat in the response.
`index.degraded > 0` → caveat that some modules are unparsable; `path` results may be incomplete.
`index.confidence == "exact"` → skip verification caveats.

## Output routing

≥5 items → write a report to `.reports/codex/codemap-py/query-<subcommand>-<YYYY-MM-DD>.md` with a short header
(title, date, scope, outcome, next steps) and print the path plus the top-5 results. ≤4 items → reply inline only.

Follow-up: ask in chat — (a) run another query, or (b) done — and wait for the reply. Skip this when running inside
another skill's pipeline.
