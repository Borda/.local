---
name: scan-codebase
description: "Scan the Python codebase and build a structural JSON index (import graph + blast-radius metrics)."
argument-hint: "[--root <path>] [--incremental]"
allowed-tools: Bash, Write, AskUserQuestion
model: haiku
disable-model-invocation: true
effort: low
---

<objective>

**Python only** — uses `ast.parse` to extract import graph + symbol metadata across all `.py` files; non-Python files not indexed. Writes `.cache/scan/<project>.json`. No external deps. Zero-Python project (no `.py` files): index writes but empty — downstream queries return no results.

Index captures per module: import graph, blast-radius metrics, **symbol list** (classes, functions, methods with line ranges). Symbol data enables `scan-query symbol` / `find-symbol` to return target function source instead of full file reads.

Agents + develop skills query index via `scan-query` for module deps, blast radius, coupling, symbol source before editing.

NOT for querying existing index (use `/codemap:query-code`); NOT for integration health checks or injection (use `/codemap:integration`).

</objective>

<workflow>

## Step 1: Run the scanner

Parse `$ARGUMENTS` to build invocation. Pass `--root <path>` if provided; pass `--incremental` if provided. Construct args conditionally — never pass literal placeholder strings:

```bash
# scan-index handles v2→v3 fallback internally
SCAN_BIN="${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index"
SCAN_ARGS_RAW="$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/parse_scan_args.py" "$ARGUMENTS")"  # timeout: 5000 — parse_scan_args.py validates $ARGUMENTS (allowlist: --root, --incremental); word-splitting safe because output is controlled flag tokens only
# Persist for usage block — fresh shell per Bash() call loses bash variables
echo "$SCAN_BIN" > "${TMPDIR:-/tmp}/codemap-scan-bin"
echo "$SCAN_ARGS_RAW" > "${TMPDIR:-/tmp}/codemap-scan-args"

# Pre-scan warning: if --incremental requested but no prior index, log fallback BEFORE starting scan
if [[ " $ARGUMENTS " == *" --incremental "* ]]; then
    PROJ_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")
    if [ ! -f ".cache/scan/${PROJ_NAME}.json" ]; then
        echo "[codemap] No prior index: falling back to full scan"
    fi
fi
```

**Unsupported flag check** — after supported flags extracted, scan `$ARGUMENTS` for `--` prefixed tokens other than `--root` and `--incremental`. If any remain: print `! Unknown flag(s): \`--<token>\`. Supported: \`--root\`, \`--incremental\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
# timeout: 360000
SCAN_BIN=$(cat "${TMPDIR:-/tmp}/codemap-scan-bin")
SCAN_ARGS_RAW=$(cat "${TMPDIR:-/tmp}/codemap-scan-args")
# Word-splitting safe: parse_scan_args.py output is controlled flag tokens only
# Unquoted expansion intentional to preserve word boundaries between flags
timeout 360 "$SCAN_BIN" $SCAN_ARGS_RAW
```

Scanner writes to `<root>/.cache/scan/<project>.json` and prints summary line:

```text
[codemap] ✓ .cache/scan/<project>.json
[codemap]   N modules indexed, M degraded
```

## Step 2: Report

After scan, read index and report compact summary:

```bash
# Pass $ARGUMENTS via env var — never interpolate into script path or args.
# SCAN_ARGS provides root-path context for stats script to resolve relative module paths.
# CLAUDE_PLUGIN_ROOT is set automatically by Claude Code when plugin is active.
# timeout: 15000
SCAN_ARGS="$ARGUMENTS" python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-stats.py"
```

Degraded count reported — `scan-stats.py` reports module counts only, no per-file list. Not failure — index still useful.

If `--incremental` passed and scan-stats reports 0 modules indexed (or same count as before), note: `--incremental` no-op when no existing index — full scan ran instead.

## Step 3: Suggest next step

```text
Index ready. Query it with:
  /codemap:query-code central --top 10
  /codemap:query-code deps <module>
  /codemap:query-code rdeps <module>
  /codemap:query-code coupled --top 10
  # see /codemap:query-code for full list of subcommands
```

</workflow>
