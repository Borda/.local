---
name: query-code
description: |
  Query the codemap structural index — module deps/rdeps/central/coupled/path, symbol-level source extraction, function call graph (fn-deps, fn-rdeps, fn-central, fn-blast).
  TRIGGER: "what depends on", "who calls", "imports of", "dependency graph", "blast radius of", "list central modules".
  SKIP: rename intent (use /codemap:rename-refs); simple grep suffices; non-Python repo. Missing/stale index auto-builds — no manual scan-codebase needed.
argument-hint: "<central [--top N] [--exclude-tests] | coupled [--top N] [--exclude-tests] | deps <module> | rdeps <module> [--exclude-tests] | path <from> <to> | symbol <name> [--limit N] [--exclude-tests] [--with-imports] | symbols <module> | find-symbol <pattern> [--limit N] [--exclude-tests] | list | fn-deps <qname> | fn-rdeps <qname> [--exclude-tests] | fn-central [--top N] [--exclude-tests] | fn-blast <qname> [--index <path>]>"
allowed-tools: Bash, Read, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>
Python import-graph + symbol queries via `scan-query` CLI (on PATH after codemap install).

Module: `central [--top N]`, `coupled [--top N]`, `deps <mod>`, `rdeps <mod>`, `path <from> <to>`
Symbol (~70–94% token reduction vs Read): `symbol <name> [--with-imports]`, `symbols <mod>`, `find-symbol <pat>`
Function call-graph (v3 index): `fn-deps <qname>`, `fn-rdeps <qname>`, `fn-central [--top N]`, `fn-blast <qname>`
qname format: `mypackage.auth::validate_token`

NOT for: repo rebuild (use `/codemap:scan-codebase`); renaming symbols (use `/codemap:rename-refs`); non-Python files.
</objective>

<workflow>

## Step 0: Index freshness (once per task — skip if already ran this turn)

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
[ -n "$INDEX" ] && { [ -f "$INDEX" ] && STATE="present" || STATE="missing"; } || STATE="unresolved"
```

Branch on `$STATE`. Auto-build opt-out via `SCAN_NO_AUTOBUILD=1` (set to run queries against index exactly as-is — no refresh, no full build); build wall-time echoed when it runs, keeps build cost separable from query cost.

- `present` → refresh in place (honors the opt-out, echoes build time):

```bash
# timeout: 8000
if [ "${SCAN_NO_AUTOBUILD:-0}" = "1" ]; then
    echo "[codemap] SCAN_NO_AUTOBUILD=1 — using existing index as-is (no refresh)"
else
    _CM_BUILD_T0=$(date +%s)
    "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental
    echo "[codemap] index built in $(( $(date +%s) - _CM_BUILD_T0 ))s"
fi
```

- `missing` → no index to query yet; auto-build is refused when opted out:

```bash
# timeout: 5000
if [ "${SCAN_NO_AUTOBUILD:-0}" = "1" ]; then
    echo "! codemap index missing and SCAN_NO_AUTOBUILD=1 — refusing to auto-build."
    echo "  Build it manually first: /codemap:scan-codebase"
    exit 1
fi
```

If not refused → `Skill(skill="codemap:scan-codebase")`, then re-read INDEX from tmpfile.

- `unresolved` → surface error, stop

## Step 1: Query

**Direction — choose before calling:**
- `rdeps <mod>` — callers: what imports X, blast radius of X
- `deps <mod>` — forward: what X imports

Common mistake: "modules affected if X changes" = `rdeps` (callers), not `deps`.

Missing binary fallback:
```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
```

```bash
scan-query rdeps "mypackage.auth"  # timeout: 5000
scan-query symbol "MyClass.method" --with-imports  # timeout: 5000
scan-query fn-rdeps "mypackage.auth::validate_token"  # timeout: 5000
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

Missing/old index → query needing newer version exits with "requires vN+ index" message; re-run auto-build (Step 0) or `/codemap:scan-codebase` to upgrade.

Anything not listed here — `scan-query --help` has full reference.

**tool_use_error / skill unavailable**: do NOT count as query attempt. Run `$SQ <same-args>` via Bash directly (timeout: 5000). Apply STOP rule after Bash result.

**`query_complete: true` → STOP ALL TOOL CALLS.** List complete and authoritative for THIS query's direction. Write answer immediately. Do NOT call codemap again. Do NOT grep/glob/bash to verify. (`query_complete` direction-scoped: a `deps`/`symbols` query on healthy module can be complete even while another file degraded, but `rdeps`/`central`/`path` complete only when `degraded: 0`. Legacy `exhaustive` field mirrors `query_complete` for one deprecation cycle — prefer `query_complete`.) (Enforced: guard hook denies import-greps for any module already returned complete this session — re-grep wastes turn, blocked. Trust index; holds for every model tier.)

**`query_complete: false`** → result direction-incomplete. Check `degraded_files` (files failed to parse — may hide edges), `untracked_py` (new files not yet `git add`-ed — invisible to staleness diff), `stale`; verify with grep only for those named gaps.

Truncation check: result count = 20 AND `--limit 0` not passed → re-run once with `--limit 0` (1 budget slot), then apply STOP rule.

Budget: max 3 calls. Non-exhaustive after 3 → report what found, stop.

`find-symbol`: Python regex — `^Auth.*Handler$` (anchored) or `auth` (substring). Escape `.` for literal dot. Always use `--limit 0` when counting/ranking to avoid 20-item truncation.

Symbol staleness: `stale: true` + empty source → `Read(path)` fallback. `stale: false` + empty → `[source not available — re-run /codemap:scan-codebase]`.

Targeted edit (known symbol, file >~300 lines): `symbol <mod::name>` → take line span → `Read(offset=span_start−10, limit=span_len+20)` → Edit. Slice Read suffices — Edit needs only slice containing target, not whole file. Spans come from index; file changed since scan → spans may drift (self-heal usually covers it). Edit errors "Found N matches" (`old_string` not file-wide unique) or no-match (drifted out of slice) → do full `Read`, then Edit with larger unique `old_string`.

## Step 2: Parse JSON + render

`scan-query` always emits JSON.

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

`index.stale: true` → scan-query already attempted bounded inline self-heal (`scan-index --incremental`) before answering; `stale` remaining true means heal was skipped (change set over cap, or git unavailable). Re-run `/codemap:scan-codebase --incremental` manually, then retry.
`index.not_covered` non-empty → note scope caveat in response.
`index.degraded > 0` → caveat some modules unparsable; `path` results may be incomplete.
`index.confidence == "exact"` → skip verification caveats.

## Output routing

≥5 items → Write `.temp/output-codemap-query-<branch>-<YYYY-MM-DD>.md` with YAML header:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
```
```yaml
---
Title:      codemap-query-code — <subcommand> <target>
Date:       <YYYY-MM-DD>
Scope:      <project>
Focus:      structural index query
Agents:     codemap:query-code
Outcome:    <N results | exhaustive: true/false>
Confidence: <exhaustive|partial|stale|unknown>
Next steps: /codemap:query-code <follow-up> or /codemap:rename-refs if renaming
Path:       → .temp/output-codemap-query-<branch>-<YYYY-MM-DD>.md
---
```
Print path + top-5 to terminal. ≤4 items → terminal only.

Follow-up gate: `AskUserQuestion` — (a) Run another query, (b) Done. Skip inside another skill's pipeline.

</workflow>
