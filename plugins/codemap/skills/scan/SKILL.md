---
name: scan
description: Scan the Python codebase and build a structural JSON index (import graph + blast-radius metrics).
argument-hint: '[--root <path>] [--incremental]'
effort: medium
allowed-tools: Bash, AskUserQuestion
---

<objective>

**Python only** — uses `ast.parse` to extract import graph and symbol metadata across all `.py` files; non-Python files not indexed. Writes `.cache/scan/<project>.json`. No external deps required. Zero-Python project (no `.py` files): index writes successfully but is empty — downstream queries return no results.

Index captures per module: import graph, blast-radius metrics, and **symbol list** (classes, functions, methods with line ranges). Symbol data enables `scan-query symbol` / `find-symbol` to return just the target function source instead of full file reads.

Agents and develop skills query index via `scan-query` to understand module dependencies, blast radius, coupling, and individual symbol source before editing code.

NOT for: querying existing index (use `/codemap:query`).

</objective>

<workflow>

## Step 1: Run the scanner

Parse `$ARGUMENTS` to build the invocation. Pass `--root <path>` if provided; pass `--incremental` if provided. Construct args conditionally — never pass the literal placeholder strings:

```bash
# timeout: 360000
# scan-index handles v2→v3 fallback internally
# NOTE: if --incremental is passed but no existing index found, falls back to full scan silently — no user warning
SCAN_BIN="${CLAUDE_PLUGIN_ROOT}/bin/scan-index"
SCAN_ARGS=()
if echo "$ARGUMENTS" | grep -q -- '--root'; then
    # Extract --root value; handle single-quoted, double-quoted, and unquoted paths (space-safe)
    ROOT_VAL=$(echo "$ARGUMENTS" | sed "s/.*--root[[:space:]]\+'\\([^']*\\)'.*/\\1/;t;s/.*--root[[:space:]]\\+\"\\([^\"]*\\)\".*/\\1/;t;s/.*--root[[:space:]]\\+\\([^[:space:]]*\\).*/\\1/")
    SCAN_ARGS+=(--root "$ROOT_VAL")
fi
echo "$ARGUMENTS" | grep -q -- '--incremental' && SCAN_ARGS+=(--incremental)
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--root\`, \`--incremental\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
# timeout: 360000
"$SCAN_BIN" "${SCAN_ARGS[@]}"
```

Scanner writes to `<root>/.cache/scan/<project>.json` and prints summary line:

```text
[codemap] ✓ .cache/scan/<project>.json
[codemap]   N modules indexed, M degraded
```

## Step 2: Report

After scan completes, read index and report compact summary:

```bash
# Pass $ARGUMENTS via env var — never interpolate into script path or args.
# SCAN_ARGS provides root-path context for stats script to resolve relative module paths.
# CLAUDE_PLUGIN_ROOT is set automatically by Claude Code when plugin is active.
# timeout: 15000
SCAN_ARGS="$ARGUMENTS" python3 "${CLAUDE_PLUGIN_ROOT}/bin/scan-stats.py"
```

Degraded files exist: list with reason. Not failure — index still useful.

If `--incremental` was passed and scan-stats reports 0 modules indexed (or the summary line shows the same count as before), note: `--incremental` is a no-op when no existing index exists — a full scan ran instead.

## Step 3: Suggest next step

```text
Index ready. Query it with:
  /codemap:query central --top 10
  /codemap:query deps <module>
  /codemap:query rdeps <module>
  /codemap:query coupled --top 10
  # see /codemap:query for full list of subcommands
```

</workflow>
