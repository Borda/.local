---
name: scan-codebase
description: "Scan the Python codebase and build a structural JSON index (import graph + blast-radius metrics)."
argument-hint: "[--root <path>] [--incremental]"
allowed-tools: Bash, Write, AskUserQuestion
disable-model-invocation: true
effort: low
---

<objective>

**Python only** — uses `ast.parse` to extract import graph + symbol metadata across all `.py` files; non-Python files not indexed. Writes `.cache/scan/<project>.json`. No external deps. Zero-Python project (no `.py` files): index writes but empty — downstream queries return no results.

Index captures per module: import graph, blast-radius metrics, **symbol list** (classes, functions, methods with line ranges). Symbol data enables `scan-query symbol` / `find-symbol` to return target function source instead of full file reads.

Agents + develop skills query index via `scan-query` for module deps, blast radius, coupling, symbol source before editing.

NOT for querying existing index (use `/codemap:query-code`); NOT for integration health checks or injection (use `/codemap:integration`); NOT for first-time codemap onboarding or injection into skill files (use `/codemap:integration init`).

</objective>

<workflow>

## Step 1: Run the scanner

Parse `$ARGUMENTS` to build invocation. Pass `--root <path>` if provided; pass `--incremental` if provided. Construct args conditionally — never pass literal placeholder strings:

**Unsupported flag check** — scan `$ARGUMENTS` for `--` prefixed tokens other than `--root` and `--incremental`. If any remain: print `! Unknown flag(s): \`--<token>\`. Supported: \`--root\`, \`--incremental\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop. Run this check BEFORE invoking `parse_scan_args.py`.

```bash
# scan-index handles v2→v3 fallback internally
SCAN_BIN="${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index"
# Validate binary exists before invoking — avoids cryptic "command not found" on bad installs
[ -x "$SCAN_BIN" ] || { printf "! scan-index binary not found at %s — reinstall: claude plugin install codemap@borda-ai-rig\n" "$SCAN_BIN"; exit 1; }
SCAN_ARGS_RAW="$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/parse_scan_args.py" "$ARGUMENTS")" || { printf "! parse_scan_args.py failed — check Python availability and plugin installation\n"; exit 1; }  # timeout: 5000
# Use project-unique tmp paths — prevents race when two parallel scans run in different projects
# Include hostname to reduce collision risk across same-named projects on different machines sharing tmp
PROJ_SLUG="$(hostname -s 2>/dev/null | tr -cd '[:alnum:]-')-$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")" | tr -cd '[:alnum:]-')"
echo "$SCAN_BIN" > "${TMPDIR:-/tmp}/codemap-scan-bin-${PROJ_SLUG}"
echo "$SCAN_ARGS_RAW" > "${TMPDIR:-/tmp}/codemap-scan-args-${PROJ_SLUG}"
echo "$PROJ_SLUG" > "${TMPDIR:-/tmp}/codemap-proj-slug"

# --root changes which project name scan-index uses for the index file path.
# When --root provided, PROJ_NAME derives from --root basename, NOT from git top-level.
if [[ " $ARGUMENTS " == *" --root "* ]]; then
    # Extract --root value: take token after --root
    ROOT_ARG=$(echo "$ARGUMENTS" | grep -oP '(?<=--root\s)\S+')
    PROJ_NAME=$(basename "$ROOT_ARG")
else
    PROJ_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")
fi
echo "$PROJ_NAME" > "${TMPDIR:-/tmp}/codemap-proj-name-${PROJ_SLUG}"

# Pre-scan warning: if --incremental requested but no prior index, log fallback BEFORE starting scan
# Note: if scan fails after sentinel is set, sentinel persists until next successful run.
if [[ " $ARGUMENTS " == *" --incremental "* ]]; then
    if [ ! -f ".cache/scan/${PROJ_NAME}.json" ]; then
        echo "[codemap] No prior index: falling back to full scan"
        touch "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}"
    fi
fi
```

```bash
# timeout: 360000
PROJ_SLUG=$(cat "${TMPDIR:-/tmp}/codemap-proj-slug" 2>/dev/null || basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")" | tr -cd '[:alnum:]-')
SCAN_BIN=$(cat "${TMPDIR:-/tmp}/codemap-scan-bin-${PROJ_SLUG}")
SCAN_ARGS_RAW=$(cat "${TMPDIR:-/tmp}/codemap-scan-args-${PROJ_SLUG}")
# parse_scan_args.py uses shlex.quote for paths with spaces — use eval set to expand safely
eval set -- "$SCAN_ARGS_RAW"
"$SCAN_BIN" --timeout 360 "$@" || { printf "! scan-index failed (exit %d) — index may be stale or incomplete\n" "$?"; exit 1; }
```

Scanner writes to `<root>/.cache/scan/<project>.json` and prints summary line:

```text
[codemap] ✓ .cache/scan/<project>.json
[codemap]   N modules indexed, M degraded
```

## Step 2: Report

After scan, read index and report compact summary:

```bash
# Only report if index exists — Step 1 may have failed (binary missing, Python unavailable)
# Pass $ARGUMENTS via env var — never interpolate into script path or args.
# SCAN_ARGS provides root-path context for stats script to resolve relative module paths.
# CLAUDE_PLUGIN_ROOT is set automatically by Claude Code when plugin is active.
# timeout: 15000
PROJ_SLUG=$(cat "${TMPDIR:-/tmp}/codemap-proj-slug" 2>/dev/null || basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")" | tr -cd '[:alnum:]-')
PROJ_NAME=$(cat "${TMPDIR:-/tmp}/codemap-proj-name-${PROJ_SLUG}" 2>/dev/null || basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")
if [ -f ".cache/scan/${PROJ_NAME}.json" ]; then
    SCAN_ARGS="$ARGUMENTS" python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-stats.py"
    # Check if --incremental was requested but fell back to full scan (sentinel set in Step 1)
    if [ -f "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}" ]; then
        echo "[codemap] Note: --incremental had no prior index — full scan ran instead"
        rm -f "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}"
    fi
else
    echo "[codemap] Skipping stats — no index found (Step 1 may have failed)"
fi
```

Degraded count reported — `scan-stats.py` reports module counts only, no per-file list. Not failure — index still useful.

If `--incremental` passed and no prior index existed, Step 1 sets a sentinel file (`codemap-incremental-noop-${PROJ_SLUG}`) before the scan starts. Step 2 detects and removes it after stats, logging: `--incremental had no prior index — full scan ran instead`. If scan fails, the sentinel persists until the next successful scan run — this is expected and not auto-cleanable.

Zero-Python project: Step 3 suggestions will return no results — the index is valid but empty.

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
