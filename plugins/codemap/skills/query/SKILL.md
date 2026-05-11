---
name: query
description: Query the codemap structural index — central, coupled, deps, rdeps, import path, symbol-level source extraction, and function-level call graph (fn-deps, fn-rdeps, fn-central, fn-blast).
argument-hint: '<central [--top N] [--exclude-tests] | coupled [--top N] [--exclude-tests] | deps <module> | rdeps <module> [--exclude-tests] | path <from> <to> | symbol <name> [--limit N] [--exclude-tests] | symbols <module> | find-symbol <pattern> [--limit N] [--exclude-tests] | list | fn-deps <qname> | fn-rdeps <qname> [--exclude-tests] | fn-central [--top N] [--exclude-tests] | fn-blast <qname>> [--index <path>]'
allowed-tools: Bash, AskUserQuestion
effort: low
---

<objective>

Query codemap structural index for import-graph analysis, symbol-level source extraction, and function-level call graph traversal. **Python projects only** — index covers `.py` files; queries on non-Python projects return empty or error. `scan-query` on PATH (installed by the codemap plugin).

**Module-level queries** (import graph):
- `central [--top N]` — most-imported modules (highest blast radius, default top 10)
- `coupled [--top N]` — modules with most imports (highest coupling, default top 10)
- `deps <module>` — what module imports
- `rdeps <module>` — what imports module
- `path <from> <to>` — shortest import path between two modules

**Symbol-level queries** (use instead of reading full files — ~94% token reduction):
- `symbol <name>` — get source of a function/class/method by name
- `symbols <module>` — list all symbols in a module (no file I/O)
- `find-symbol <pattern>` — regex search across all symbol names in index

**Function-level call graph queries** (v3 index — requires `/codemap:scan` with call graph):
- `fn-deps <qname>` — what does this function/method call? (outgoing edges)
- `fn-rdeps <qname>` — what functions call this one? (incoming edges)
- `fn-central [--top N]` — most-called functions globally (default top 10)
- `fn-blast <qname>` — transitive reverse-call BFS with depth levels

Use `module::function` format for qname, e.g. `mypackage.auth::validate_token`. Requires v3 index — if index is v2, commands return a clear upgrade prompt.

NOT for: building or rebuilding index (use `/codemap:scan`). If subcommand roster expands significantly, run `/foundry:calibrate routing` to verify no routing collisions introduced.

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

**Common mistake — direction matters**: "which modules need updating if X changes?" = `rdeps` (callers), NOT `deps`. `deps` returns the wrong direction — 0% recall.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--top\`, \`--exclude-tests\`, \`--limit\`, \`--index\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

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

Symbol names accept: bare name (`authenticate`), qualified name (`MyClass.authenticate`), or case-insensitive substring fallback. Function qnames use `module::function` format (e.g. `mypackage.auth::validate_token`). Index must be current — re-run `/codemap:scan` if stale warning appears.

## Budget and stop rules

**Query budget**: max 3 calls per task. Stop after 3 even if not exhaustive — report what you found. Exception: for explicit exhaustive multi-target analysis requests, state exhaustive intent before the first call — budget extends to 6.

**exhaustive: true — STOP ALL TOOL CALLS:** When `rdeps` or `deps` result contains `"exhaustive": true`, the list is complete and authoritative for the **unfiltered** index. Note: if `--exclude-tests` was used, exhaustive reflects unfiltered coverage — filtered results may omit callers; state this caveat if relevant. Write your answer immediately. Do NOT call codemap again. Do NOT run grep, bash, or Glob passes to verify or extend it. No exceptions.

**Non-exhaustive result — convergence rule**: if after budget calls the result is still non-exhaustive, stop and report what you have. Do NOT switch to grep/bash to continue — the index covers what it covers.

## Step 2: Parse JSON output and format

`scan-query` always emits a JSON object — parse it before rendering. Stale-index detection has two channels: (1) stderr: if it contains `[stale]` or `⚠ codemap index stale` — surface the warning; (2) JSON field `index.stale` (boolean) — check `result.index.stale`; if `true`, warn user to re-run `/codemap:scan`. Check `index.degraded` in the result; if `> 0`, caveat that some modules were unparsable.

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
| stale check | `index.stale` (boolean) | if true → warn "index stale — run /codemap:scan" |

`{"error": "..."}`: surface error, suggest re-running `/codemap:scan`.

**Flags available on multiple commands** (`--exclude-tests`, `--limit`, `--index`):
- `--exclude-tests` — drop test modules from results; applies to: `rdeps`, `central`, `coupled`, `symbol`, `find-symbol`, `fn-rdeps`, `fn-central`
- `--limit N` (default 20, use `0` for all) — caps results on `symbol` and `find-symbol`; pass `--limit 0` before counting or ranking to avoid silent truncation
- `--index <path>` — explicit index file path (bypasses auto-discovery; useful for monorepos or comparing two indexes)

</workflow>
