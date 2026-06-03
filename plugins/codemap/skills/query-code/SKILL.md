---
name: query-code
description: |
  Query the codemap structural index — central, coupled, deps, rdeps, import path, symbol-level source extraction, and function-level call graph (fn-deps, fn-rdeps, fn-central, fn-blast).
  TRIGGER when: user asks about module relationships, dependency graph, callers/callees, or blast radius; phrases: "what depends on", "who calls", "imports of", "dependency graph", "blast radius of".
  SKIP: codemap index not built (skill self-checks and no-ops gracefully); simple grep would suffice; non-Python repo.
argument-hint: "<central [--top N] [--exclude-tests] | coupled [--top N] [--exclude-tests] | deps <module> | rdeps <module> [--exclude-tests] | path <from> <to> | symbol <name> [--limit N] [--exclude-tests] | symbols <module> | find-symbol <pattern> [--limit N] [--exclude-tests] | list | fn-deps <qname> | fn-rdeps <qname> [--exclude-tests] | fn-central [--top N] [--exclude-tests] | fn-blast <qname> [--index <path>]> [--exhaustive]"
allowed-tools: Bash, Write, AskUserQuestion
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

**Symbol-level queries** (use instead of reading full files — ~94% token reduction):
- `symbol <name>` — get source of function/class/method by name
- `symbols <module>` — list all symbols in module (no file I/O)
- `find-symbol <pattern>` — regex search across all symbol names in index

**Function-level call graph queries** (v3 index — requires `/codemap:scan-codebase` with call graph):
- `fn-deps <qname>` — what does function/method call? (outgoing edges)
- `fn-rdeps <qname>` — what functions call this one? (incoming edges)
- `fn-central [--top N]` — most-called functions globally (default top 10)
- `fn-blast <qname>` — transitive reverse-call BFS with depth levels

Use `module::function` format for qname, e.g. `mypackage.auth::validate_token`. Requires v3 index — v2 returns clear upgrade prompt.

NOT for: building or rebuilding index (use `/codemap:scan-codebase`). All query subcommands are **read-only** — any request that modifies the index or project files belongs to `/codemap:scan-codebase` (index writes) or `/codemap:integration` (file injection). Ambiguous prompts like "show me the call graph" that imply read → query-code is correct; "update the call graph" → scan-codebase. If subcommand roster expands significantly, run `/foundry:calibrate routing` (requires `foundry` plugin) to verify no routing collisions.

</objective>

<workflow>

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

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--top\`, \`--exclude-tests\`, \`--limit\`, \`--index\`, \`--exhaustive\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

Run `scan-query` via Bash:

```bash
# timeout: 20000
scan-query <QUERY_ARGS>
```

Replace `<QUERY_ARGS>`:

| Goal | Command |
| --- | --- |
| reverse deps | `rdeps <module>` |
| forward deps | `deps <module>` |
| central modules | `central --top 10` |
| coupling rank | `coupled --top 10` |
| import path | `path <from> <to>` |
| symbol source | `symbol <name>` |
| module symbols | `symbols <module>` |
| symbol search | `find-symbol <pattern>` |
| list modules | `list` |
| outgoing calls | `fn-deps module::function` |
| incoming calls | `fn-rdeps module::function` |
| most-called functions | `fn-central --top 10` |
| transitive callers | `fn-blast module::function` |

`scan-query` on PATH, locates index via git root — no setup. Missing index prints clear error.

Symbol names accept: bare name (`authenticate`), qualified name (`MyClass.authenticate`), or case-insensitive substring fallback. Function qnames use `module::function` format (e.g. `mypackage.auth::validate_token`). Index must be current — re-run `/codemap:scan-codebase` if stale warning appears.

## Budget and stop rules

**Query budget**: max 3 calls per task. Stop after 3 even if not exhaustive — report what found. Exception: explicit exhaustive multi-target analysis requests — state exhaustive intent before first call, budget extends to 6. Declaring exhaustive intent after the first call has already been made is invalid — treat that run as non-exhaustive (budget=3).

**Exhaustive path/fn-blast traversal** — `path` and `fn-blast` queries traverse the graph internally and may require deeper exploration than 3 surface calls allow. For these subcommands, increase budget to **10 calls** when `--exhaustive` flag is present in `$ARGUMENTS`. Without `--exhaustive`, path/fn-blast still capped at 6 (exhaustive-mode default).

**exhaustive: true — STOP ALL TOOL CALLS:** When `rdeps` or `deps` result contains `"exhaustive": true`, list complete and authoritative for **unfiltered** index. Note: if `--exclude-tests` used, exhaustive reflects unfiltered coverage — filtered results may omit callers; state caveat if relevant. Write answer immediately. Do NOT call codemap again. Do NOT run grep, bash, or Glob passes to verify or extend. No exceptions.

**Non-exhaustive result — convergence rule**: after budget calls still non-exhaustive, stop and report what found. Do NOT switch to grep/bash — index covers what it covers.

## Step 2: Parse JSON output and format

`scan-query` always emits JSON object — parse before rendering. Stale-index detection has two channels: (1) stderr: if contains `[stale]` or `⚠ codemap index stale` — surface warning; (2) JSON field `index.stale` (boolean) — check `result.index.stale`; if `true`, warn user to re-run `/codemap:scan-codebase`. Check `index.degraded` in result; if `> 0`, caveat that some modules unparsable.

| Command | JSON key to use | Render as |
| --- | --- | --- |
| `rdeps` / `deps` | `imported_by` / `direct_imports` | list modules, one per line |
| `central` / `coupled` | `central` / `coupled` array | list name + count with brief note |
| `path` | `path` array (or `null`) | chain `A → B → C → D`; if `null` → "No import path found." (`--exclude-tests` not supported on `path`) |
| `symbol` | `symbols[].source` | fenced code block; caption = module + line range |
| `symbols` | `symbols` array | `type name (lines start–end)`, one per line |
| `find-symbol` | `matches` array | `module:qualified_name (type)`, one per line |
| `list` | `modules` array | `module (path)`, one per line |
| `fn-deps` / `fn-rdeps` | `calls` / `called_by` | `module::function (resolution)`, one per line |
| `fn-central` | `fn_central` array | `count module::function`, one per line |
| `fn-blast` | `blast_radius` array | `depth module::function` (if depth key present), sorted by depth then name |
| stale check | `index.stale` (boolean) | if true → warn "index stale — run /codemap:scan-codebase" |

`{"error": "..."}`: surface error, suggest re-running `/codemap:scan-codebase`.

**Partial JSON handling**: if output is truncated (does not parse as complete JSON object — e.g., ends mid-value or missing closing `}`), log `⚠ partial JSON response — results may be incomplete` and attempt to parse only complete top-level fields present before truncation. Surface whatever was recovered; do not silently discard partial results.

**Output routing** — if result count ≥ 5 items (applies to: `rdeps`, `deps`, `central`, `coupled`, `fn-rdeps`, `fn-central`, `list` on medium+ projects): write full rendered output to `.temp/output-codemap-query-<branch>-<YYYY-MM-DD>.md` via Write tool, then print terminal summary (YAML header + path + top-5 items). Skip file write for ≤ 4 items — terminal only.

**Flags available on multiple commands** (`--exclude-tests`, `--limit`, `--index`):
- `--exclude-tests` — drop test modules from results; applies to: `rdeps`, `central`, `coupled`, `symbol`, `find-symbol`, `fn-rdeps`, `fn-central`; **not supported on `path`** (see `path` row in table above)
- `--limit N` (default 20, use `0` for all) — caps results on `symbol` and `find-symbol`; pass `--limit 0` before counting or ranking to avoid silent truncation
- `--index <path>` — explicit index file path (bypasses auto-discovery; useful for monorepos or comparing two indexes)

</workflow>
