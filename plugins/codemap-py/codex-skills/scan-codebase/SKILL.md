---
name: scan-codebase
description: Scan the Python codebase and build a structural JSON index (import graph + blast-radius metrics + symbol table). Explicit invocation only via `$codemap-py:scan-codebase [--root <path>] [--incremental]` — never auto-trigger this from conversation reasoning. Use when the index is missing, stale, or after significant project changes.
---

# Scan Codebase

Python only — `ast.parse` extracts import graph + symbol metadata (classes, functions, methods with line ranges) across every `.py` file; non-Python files are not indexed. Writes `.cache/codemap/<project>.json`. No external dependencies. Zero-Python project (no `.py` files): index writes but empty — downstream queries return no results.

Symbol data lets `$codemap-py:query-code symbol`/`find-symbol` return target function source instead of a full file read (~70–94% token reduction vs `Read`).

NOT for: querying an existing index (use `$codemap-py:query-code`); integration health checks (use `$codemap-py:integration`).

**Explicit invocation only** — Codex has no `disable-model-invocation` frontmatter field, so this constraint is enforced by convention, not schema: never call this skill from autonomous reasoning; run it only in direct response to the user's literal `$codemap-py:scan-codebase` trigger.

## Runtime note

Codex has no `bin/` PATH entry and no `$CLAUDE_PLUGIN_ROOT`-equivalent environment variable. Resolve this skill's installed plugin-root path once, then substitute that literal path for `PLUGIN_ROOT` in every command below. Shell state (including exported variables) does not persist across tool calls — keep the resolved path in reasoning and paste it in literally rather than caching it in a shell variable or tmpfile.

## Workflow

### Step 1: Run the scanner

Parse the invocation text for `--root <path>` and `--incremental`. Any other `--`-prefixed token is unsupported: report `Unknown flag(s): --<token>. Supported: --root, --incremental.` and stop — do not guess at intent.

```bash
PLUGIN_ROOT/bin/codemap-py index [--root <path>] [--incremental]
```

On Windows, use `PLUGIN_ROOT\bin\codemap-py.cmd index ...` instead (native fallback launcher, plan §7.4).

`--root <path>` note: the index is named after `basename(<path>)` — this differs from the default project index (named after the git root's basename). Queries against the default index will not see a `--root` index unless the same `--root` is used consistently on every subsequent scan/query.

Scanner writes to `<root>/.cache/codemap/<project>.json` (or `$CODEMAP_INDEX_DIR/<project>.json` when set) and prints a summary line with modules indexed and degraded count. Non-zero exit → report the exit code and stop; do not retry silently (exit 1 = index/filesystem failure, 2 = bad syntax — plan §7.5).

### Step 2: Report and suggest next step

Report the printed module count and degraded count. Degraded count is informational, not failure — the index is still usable. Zero-Python project: report the index as valid but empty.

Suggest:

```text
Index ready. Query it with $codemap-py:query-code — central --top 10, deps/rdeps <module>, coupled --top 10.
See $codemap-py:query-code for the full subcommand list.
```
