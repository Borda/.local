---
name: query-code
description: |
  Query the codemap structural index — central, coupled, deps, rdeps, import path, symbol-level source extraction, and function-level call graph (fn-deps, fn-rdeps, fn-central, fn-blast).
  TRIGGER when: user asks about module relationships, dependency graph, callers/callees, or blast radius; phrases: "what depends on", "who calls", "imports of", "dependency graph", "blast radius of".
  SKIP: user wants to rename a symbol (use /codemap:rename-refs); simple grep would suffice; non-Python repo. (A missing or stale index is built/refreshed automatically — see Step 0; no manual /codemap:scan-codebase first.)
when_to_use: |
  TRIGGER when: user asks about module relationships, dependency graph, callers/callees, blast radius, or central/coupled modules; phrases: "what depends on", "who calls", "imports of", "dependency graph", "blast radius of", "list central modules".
  SKIP: user wants to rename a symbol (use `/codemap:rename-refs`); simple grep would suffice; non-Python repository. (Missing/stale index auto-handled in Step 0 — no manual build needed.)
argument-hint: "<central [--top N] [--exclude-tests] | coupled [--top N] [--exclude-tests] | deps <module> | rdeps <module> [--exclude-tests] | path <from> <to> | symbol <name> [--limit N] [--exclude-tests] [--with-imports] | symbols <module> | find-symbol <pattern> [--limit N] [--exclude-tests] | list | fn-deps <qname> | fn-rdeps <qname> [--exclude-tests] | fn-central [--top N] [--exclude-tests] | fn-blast <qname> [--index <path>] [--exhaustive]>"
allowed-tools: Bash, Read, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>

Query codemap structural index for import-graph analysis, symbol-level source extraction, function-level call graph traversal. **Python projects only** — index covers `.py` files; queries on non-Python projects return empty or error. `scan-query` on PATH (installed by codemap plugin).

**Module-level queries** (import graph):
- `central [--top N]` — most-imported modules (highest blast radius, default top 10)
- `coupled [--top N]` — modules with most imports (highest coupling, default top 10)
- `deps <module>` — what module imports
- `rdeps <module>` — what imports module
- `path <from> <to>` — shortest import path between two modules

**Symbol-level queries** (use instead of reading full files — ~70–94% token reduction (single known-name lookup on large file)):
- `symbol <name> [--with-imports]` — get source of function/class/method by name; returns `stale: bool` per result; add `--with-imports` to include module-level import block alongside source
- `symbols <module>` — list all symbols in module (no file I/O)
- `find-symbol <pattern>` — regex search across all symbol names in index

**Function-level call graph queries** (v3 index — requires `/codemap:scan-codebase` with call graph):
- `fn-deps <qname>` — what does function/method call? (outgoing edges)
- `fn-rdeps <qname>` — what functions call this one? (incoming edges)
- `fn-central [--top N]` — most-called functions globally (default top 10)
- `fn-blast <qname>` — transitive reverse-call BFS with depth levels

Use `module::function` format for qname, e.g. `mypackage.auth::validate_token`. Requires v3 index — v2 returns clear upgrade prompt.

NOT for: explicit/large or monorepo (`--root`) rebuilds (use `/codemap:scan-codebase`); writing symbol output to project files (Write is in allowed-tools for output routing only — never use it to modify project source). All query subcommands are **read-only on project source** — they never modify `.py` files. The skill DOES auto-materialize/refresh its own derived index cache (`.cache/codemap/`, fully regenerable) as a Step 0 pre-flight; that is the one permitted write. File injection into skills/agents belongs to `/codemap:integration`. Ambiguous prompts like "show me the call graph" that imply read → query-code is correct; "update the call graph" → scan-codebase. If subcommand roster expands significantly, run `/foundry:calibrate routing` (requires `foundry` plugin) to verify no routing collisions.

</objective>

<workflow>

## Step 0: Ensure index present + fresh (once per task)

Run this pre-flight **once per task**, before the first query. Skip entirely if Step 0 already ran earlier this turn.

Resolve the index path (same helper `/codemap:integration` uses):

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
if [ -n "$INDEX" ]; then
    [ -f "$INDEX" ] && STATE="present" || STATE="missing"
else
    STATE="unresolved"
fi
echo "$STATE" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index-state"
echo "INDEX_STATE=$STATE"
```

Read `INDEX_STATE` from stdout OR from `$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index-state")` in subsequent steps, then branch:

- **`missing`** — build before querying. The index is created only by `scan-index`; call the builder skill (explicit `Skill()` works despite its `disable-model-invocation`):
  ```text
  Skill(skill="codemap:scan-codebase")
  ```
  If the build fails or the repo is non-Python, surface scan-codebase's own message and stop — do not fall through to grep.

- **`present`** — refresh only SHA-changed files (cheap; re-parses just what changed since last scan):
  ```bash
  scan-index --incremental  # timeout: 5000 — ~0.5s flat
  ```

- **`unresolved`** — `resolve_index_env.py` could not resolve (no git root / python missing); surface the error and stop.

> Full scan (`scan-index` without `--incremental`) is only needed after large structural moves — the `missing` branch already runs a full build via `/codemap:scan-codebase`.

## Step 1: Run the query

**deps vs rdeps — choose before calling:**

| Task asks for... | Use | Why |
| --- | --- | --- |
| "which modules import X?" | `rdeps X` | callers, blast radius |
| "what imports X?" | `rdeps X` | callers |
| "modules affected if X changes?" | `rdeps X` | blast radius = reverse deps |
| "blast radius of X" | `rdeps X` | reverse deps |
| "what does X import?" | `deps X` | forward deps |
| "dependencies of X" | `deps X` | forward deps |

**Common mistake — direction matters**: "which modules need updating if X changes?" = `rdeps` (callers), NOT `deps`. `deps` returns wrong direction — 0% recall.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--top\`, \`--exclude-tests\`, \`--limit\`, \`--index\`, \`--exhaustive\`; \`--with-imports\` applies to \`symbol\` subcommand only.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Symbol staleness contract**: every `symbol` result includes `"stale": bool`. When `stale: true`:
- Do NOT use `source` — it may be wrong (function moved since last scan)
- `stale_reason` explains why: `"file deleted"`, `"line range past EOF"`, `"symbol name not in slice header"`
- Fall back: `Read(<result["path"]>)` — path is still valid even when content is stale
- Fix: run `scan-index --incremental` then retry

**Symbol vs Read — access pattern decision:**

| Need | Use |
| --- | --- |
| Single known function/method body | `symbol Module.fn` |
| Body + module-level imports (type context) | `symbol --with-imports Module.fn` |
| >2 symbols in same file | `Read` on file |
| Module-level constants / `__all__` | `Read` on file |
| Discover functions matching a concept | `find-symbol <pattern>` → `symbol` (N≤2 hits only) |
| Non-Python file | `Read` |

**Qualified names reduce ambiguity**: `symbol MyClass.method` returns one result; bare `symbol authenticate` may return N matches across modules. Prefer qualified form when module path known.

Index freshness is handled by Step 0 — do not re-run `scan-index` here.

**Missing binary**: if `scan-query` not found on PATH, use `locate_scan_query.py` three-tier fallback (same as `/codemap:integration check`):
```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
```
Then invoke via `$SQ` instead of bare `scan-query`. If still not found: print `! scan-query not found — install codemap plugin: claude plugin install codemap@borda-ai-rig` and stop.

Run `scan-query` via Bash, assembling arguments from the table below. Example forms — always use quoted module names/qnames:

```bash
# module-level query example
scan-query rdeps "mypackage.auth"  # timeout: 5000
# function-level query example
scan-query fn-rdeps "mypackage.auth::validate_token"  # timeout: 5000
# fn-blast example
scan-query fn-blast "mypackage.auth::validate_token"  # timeout: 5000
```

Replace subcommand and arguments per task:

| Goal | Command |
| --- | --- |
| reverse deps | `rdeps <module>` |
| forward deps | `deps <module>` |
| central modules | `central --top 10` |
| coupling rank | `coupled --top 10` |
| import path | `path <from> <to>` |
| symbol source (body only) | `symbol <name>` |
| symbol source + imports | `symbol <name> --with-imports` |
| module symbols | `symbols <module>` |
| symbol search | `find-symbol <pattern>` |
| list modules | `list` |
| outgoing calls | `fn-deps module::function` |
| incoming calls | `fn-rdeps module::function` |
| most-called functions | `fn-central --top 10` |
| transitive callers | `fn-blast module::function` |

`scan-query` on PATH via locate_scan_query.py fallback (see above). Do not fall through to grep/bash fallback.

Symbol names accept: bare name (`authenticate`), qualified name (`MyClass.authenticate`), or case-insensitive substring fallback. Function qnames use `module::function` format (e.g. `mypackage.auth::validate_token`). Step 0 keeps the index current; if a stale warning still appears, files changed mid-task — re-run `scan-index --incremental` and retry.

`find-symbol` pattern is a **Python regex** applied against the full qualified name — `auth` matches any symbol containing "auth" as a substring; `^Auth.*Handler$` matches only symbols starting with "Auth" and ending with "Handler". For exact match use anchors: `^MyClass.method$`. Bare substring (no anchors) = broad match — prefer anchored patterns for precision.

## Budget and stop rules

**Query budget**:
- Default: max **3** calls per task. Stop after 3 even if not exhaustive — report what found.
- Exhaustive mode: when user explicitly requests exhaustive traversal, budget extends to **6** calls. Best declared before first call so budget applies from the start — if declared mid-task, apply remaining budget up to 6 total from that point.
- `path` or `fn-blast` with `--exhaustive` flag: budget extends to **6** calls (same as exhaustive mode). These subcommands traverse the graph internally; `--exhaustive` is the explicit signal to allow deeper exploration.

**exhaustive: true — STOP ALL TOOL CALLS:** When `rdeps`, `deps`, or `fn-rdeps` result has `result["index"]["exhaustive"] == true`, list is complete and authoritative for the **unfiltered** index. Check the `index.exhaustive` field specifically (not any top-level field). Note: if `--exclude-tests` used, exhaustive reflects unfiltered coverage — filtered results may omit callers; state caveat if relevant. Write answer immediately. Do NOT call codemap again. Do NOT run grep, bash, or Glob passes to verify or extend. **Caveat**: when result count equals the default limit (20) and `--limit 0` was not passed, the list may be truncated even if `exhaustive: true` — re-run with `--limit 0` to confirm. In the response, explicitly note: "Result is complete and authoritative for the unfiltered index." If `--exclude-tests` was used, add: "Note: filtered results may omit some callers — unfiltered list is complete."

**Non-exhaustive result — convergence rule**: after budget calls still non-exhaustive, stop and report what found. Do NOT switch to grep/bash — index covers what it covers.

**`--exclude-tests` + exhaustive**: when `--exclude-tests` is used and `index.exhaustive == true`, the exhaustive flag reflects unfiltered coverage (the index was fully searched). The STOP rule still applies — do NOT make additional calls. The caveat is informational: filtered results may omit callers that are in test files. State the caveat in the response but do not make additional non-filtered calls to compensate.

## Step 2: Parse JSON output and format

`scan-query` always emits JSON object — parse before rendering. Stale-index detection has two channels: (1) stderr: if contains `[stale]` or `⚠ codemap index stale` — surface warning; (2) JSON field `index.stale` (boolean) — check `result.index.stale`; if `true`, the index went stale after Step 0 (files changed mid-task) — re-run `scan-index --incremental` and retry rather than telling the user to build manually. Check `index.degraded` in result; if `> 0`, caveat that some modules unparsable — for `path` queries, note that intermediate nodes may be missing and the path result may be incomplete.

| Command | JSON key to use | Render as |
| --- | --- | --- |
| `rdeps` / `deps` | `imported_by` / `direct_imports` | list modules, one per line |
| `central` | `central` array | `name — N importers (high blast radius)`, one per line |
| `coupled` | `coupled` array | `name — N imports (high coupling)`, one per line |
| `path` | `path` array (or `null`) | chain `A → B → C → D`; if `null` → "No import path found." (`--exclude-tests` not supported on `path`) |
| `symbol` | `symbols[].source` | fenced code block; caption = module + line range; if `source` is empty string → render `[source not available — re-run /codemap:scan-codebase]` instead of empty block |
| `symbols` | `symbols` array | `type name (lines start–end)`, one per line |
| `find-symbol` | `matches` array | `module:qualified_name (type)`, one per line |
| `list` | `modules` array | `module (path)`, one per line |
| `fn-deps` / `fn-rdeps` | `calls` / `called_by` | `module::function (resolution)`, one per line |
| `fn-central` | `fn_central` array | `count module::function`, one per line |
| `fn-blast` | `blast_radius` array | `depth module::function` (if depth key present), sorted by depth then name; if `depth` key absent (older index format) → render `module::function` without depth prefix, note "depth unavailable — re-run /codemap:scan-codebase to upgrade index" |
| stale check | `index.stale` (boolean) | if true → index changed since Step 0; re-run `scan-index --incremental` and retry |

`{"error": "..."}`: surface error. A residual `Index not found` here means Step 0's auto-build failed — report the build failure plainly (do not just suggest a manual rebuild). Other errors (unknown module, bad regex) surface as-is.

**Partial JSON handling**: if output is truncated (does not parse as complete JSON object — e.g., ends mid-value or missing closing `}`), log `⚠ partial JSON response — results may be incomplete`. Attempt recovery using `jq` with `--stream` mode if available; do not fall back to line-matching (structural keys like `imported_by`, `stale` would surface as false module names). Surface whatever was recovered; do not silently discard partial results. If recovery produces zero items, report `⚠ could not recover partial results — re-run the query` and stop.

**Output routing** — if result count ≥ 5 items: write full rendered output to `.temp/output-codemap-query-<branch>-<YYYY-MM-DD>.md` via Write tool. Output file must begin with YAML header block:
```yaml
---
codemap:query-code — <subcommand> <module-or-qname>
Date:       <YYYY-MM-DD>
Scope:      <project name>
Focus:      structural index query
Agents:     codemap:query-code
Outcome:    <N results returned | exhaustive: true/false>
Confidence: 0.N — <key gap if any>
Next steps: /codemap:query-code <follow-up subcommand> or /codemap:rename-refs if renaming
Path:       → .temp/output-codemap-query-<branch>-<YYYY-MM-DD>.md
---
```
Then print terminal summary (YAML header + path + top-5 items). Skip file write for ≤ 4 items — terminal only. Applies to: `rdeps`, `deps`, `central`, `coupled`, `fn-rdeps`, `fn-central`, `fn-deps`, `fn-blast`, `list`. For `fn-blast` on widely-called functions (>10 entries), always route to file — print file path and top-5 entries only to terminal to avoid burying the follow-up gate.

**Follow-up gate** (after output routing): invoke `AskUserQuestion` — (a) Run another query (specify subcommand), (b) Done. Skip when invoked from inside another skill's pipeline.

**Flags available on multiple commands** (`--exclude-tests`, `--limit`, `--index`):
- `--exclude-tests` — drop test modules from results; applies to: `rdeps`, `central`, `coupled`, `symbol`, `find-symbol`, `fn-rdeps`, `fn-central`; **not supported on `path`** — if user passes `path ... --exclude-tests`, print `! --exclude-tests is not supported for path queries — flag ignored` and proceed without it
- `--limit N` (default 20, use `0` for all) — caps results on `symbol`, `find-symbol`, `rdeps`, `deps`, `fn-rdeps`, and other list-type commands; **always pass `--limit 0` when counting or ranking** to avoid silent truncation at 20 items; output-routing count check and exhaustive assertions should be made only after `--limit 0` or confirmed item count is below 20
- `--index <path>` — explicit index file path (bypasses auto-discovery; useful for monorepos or comparing two indexes)

</workflow>
