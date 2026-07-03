---
name: query-code
description: |
  Query the codemap structural index — central, coupled, deps, rdeps, import path, symbol-level source extraction, function-level call graph (fn-deps, fn-rdeps, fn-central, fn-blast), and listing central modules.
  TRIGGER when: user asks about module relationships, dependency graph, callers/callees, blast radius, or central/coupled modules; phrases: "what depends on", "who calls", "imports of", "dependency graph", "blast radius of", "list central modules".
  SKIP: user wants to rename a symbol (use /codemap:rename-refs); this skill handles call-graph queries only (no rename) — for rename + caller analysis use /codemap:rename-refs; simple grep would suffice; non-Python repo. (A missing or stale index is built/refreshed automatically — see Step 0; no manual /codemap:scan-codebase first.)
argument-hint: "<central [--top N] [--exclude-tests] | coupled [--top N] [--exclude-tests] | deps <module> | rdeps <module> [--exclude-tests] | path <from> <to> | symbol <name> [--limit N] [--exclude-tests] [--with-imports] | symbols <module> | find-symbol <pattern> [--limit N] [--exclude-tests] | list | fn-deps <qname> | fn-rdeps <qname> [--exclude-tests] | fn-central [--top N] [--exclude-tests] | fn-blast <qname> [--index <path>] [--exhaustive]>"
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

Branch on `$STATE`:
- `present` → `"${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental  # timeout: 5000`
- `missing` → `Skill(skill="codemap:scan-codebase")`, then re-read INDEX from tmpfile
- `unresolved` → surface error, stop

## Step 1: Query

**Direction — choose before calling:**
- `rdeps <mod>` — callers: what imports X, blast radius of X
- `deps <mod>` — forward: what X imports

Common mistake: "modules affected if X changes" = `rdeps` (callers), NOT `deps`.

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
| most-coupled | `coupled --top 10` |
| import path | `path <from> <to>` |
| symbol source | `symbol <name> [--with-imports]` |
| all symbols in module | `symbols <mod>` |
| symbol search | `find-symbol <pattern>` |
| outgoing calls | `fn-deps module::function` |
| incoming calls | `fn-rdeps module::function [--exclude-tests]` |
| most-called functions | `fn-central --top 10` |
| transitive callers | `fn-blast module::function` |

**tool_use_error / skill unavailable**: do NOT count as a query attempt. Run `$SQ <same-args>` via Bash directly (timeout: 5000). Apply STOP rule after Bash result.

**exhaustive: true → STOP ALL TOOL CALLS.** List complete and authoritative. Write answer immediately. Do NOT call codemap again. Do NOT grep/glob/bash to verify. (Enforced: a guard hook denies import-greps for any module already returned exhaustive this session — a re-grep wastes a turn and is blocked. Trust the index; this holds for every model tier.)

Truncation check: result count = 20 AND `--limit 0` not passed → re-run once with `--limit 0` (1 budget slot), then apply STOP rule.

Budget: max 3 calls. Non-exhaustive after 3 → report what found, stop.

`find-symbol`: Python regex — `^Auth.*Handler$` (anchored) or `auth` (substring). Escape `.` for literal dot. Always use `--limit 0` when counting or ranking to avoid 20-item truncation.

Symbol staleness: `stale: true` + empty source → `Read(path)` fallback. `stale: false` + empty → `[source not available — re-run /codemap:scan-codebase]`.

## Step 2: Parse JSON + render

`scan-query` always emits JSON.

| Command | JSON key | Render as |
| --- | --- | --- |
| `rdeps`/`deps` | `imported_by`/`direct_imports` | list modules, one per line |
| `central`/`coupled` | `central`/`coupled` array | `name — N importers`, one per line |
| `path` | `path` array or null | `A → B → C`; null → "No import path found." |
| `symbol` | `symbols[].source` | fenced code block; caption = module + line range |
| `symbols` | `symbols` array | `type name (lines start–end)`, one per line |
| `find-symbol` | `matches` array | `module:qualified_name (type)`, one per line |
| `fn-deps`/`fn-rdeps` | `calls`/`called_by` | `module::fn (resolution)`, one per line |
| `fn-central` | `fn_central` | `count module::fn`, one per line |
| `fn-blast` | `blast_radius` | `depth module::fn`, sorted by depth then name |

`index.stale: true` → re-run `scan-index --incremental` and retry.
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
