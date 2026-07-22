---
name: scan-codebase
description: "Scan the Python codebase and build a structural JSON index (import graph + blast-radius metrics). TRIGGER when: user asks to build, refresh, or rebuild the codemap index; user mentions stale index, missing symbols, or re-indexing after significant project changes; phrases: \"build codemap\", \"scan codebase\", \"refresh structural index\", \"rebuild import graph\"."
argument-hint: "[--root <path>] [--incremental]"
allowed-tools: Bash
disable-model-invocation: true
effort: low
---

<objective>

**Python only** — uses `ast.parse` to extract import graph + symbol metadata across all `.py` files; non-Python files not indexed. Writes `.cache/codemap/<project>.json`. No external deps. Zero-Python project (no `.py` files): index writes but empty — downstream queries return no results.

Index captures per module: import graph, blast-radius metrics, **symbol list** (classes, functions, methods with line ranges). Symbol data enables `scan-query symbol` / `find-symbol` to return target function source instead of full file reads.

Agents + develop skills query index via `scan-query` for module deps, blast radius, coupling, symbol source before editing.

NOT for: querying existing index (use `/codemap:query-code`); integration health checks or injection (use `/codemap:integration`); first-time codemap onboarding or injection into skill files (use `/codemap:integration init`).

</objective>

<workflow>

## Step 1: Run the scanner

Parse `$ARGUMENTS` to build invocation. Pass `--root <path>` if provided; pass `--incremental` if provided. Construct args conditionally — never pass literal placeholder strings:

**Unsupported flag check** — scan `$ARGUMENTS` for `--` prefixed tokens other than `--root` and `--incremental`. If any remain: print `! Unknown flag(s): \`--<token>\`. Supported: \`--root\`, \`--incremental\`.` then exit 1 — do not invoke AskUserQuestion (disable-model-invocation:true makes AskUserQuestion structurally unreachable). Run this check BEFORE invoking `parse_scan_args.py`.

```bash
# timeout: 10000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_ARGS_UNSUPPORTED=0; _SKIP_NEXT=0
# unquoted $ARGUMENTS word-splits; parse_scan_args.py handles quoted paths
for _FLAG in $ARGUMENTS; do
  [ "$_SKIP_NEXT" -eq 1 ] && { _SKIP_NEXT=0; continue; }
  case "$_FLAG" in
    --root)        _SKIP_NEXT=1 ;;
    --incremental) ;;
    --*) printf "! Unsupported flag: %s\nSupported: --root <path>, --incremental\n" "$_FLAG" >&2; _ARGS_UNSUPPORTED=1 ;;
  esac
done
[ "$_ARGS_UNSUPPORTED" -eq 0 ] || exit 1
SETUP_STDERR="${TMPDIR:-/tmp}/codemap-setup-err-$$-${CSID}"
SCAN_STATE_FILE=$(bash "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/setup_scan_env.sh" --arguments "$ARGUMENTS" 2>"$SETUP_STDERR")
if [ $? -ne 0 ] || [ -z "$SCAN_STATE_FILE" ]; then
  printf "! setup_scan_env.sh failed"; [ -s "$SETUP_STDERR" ] && printf ": %s" "$(cat "$SETUP_STDERR")"; printf "\n"; exit 1
fi
printf '%s' "$SCAN_STATE_FILE" > "${TMPDIR:-/tmp}/codemap-state-ref-${CSID}"  # subsequent blocks read without knowing PID
```

```bash
# timeout: 360000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r SCAN_STATE_FILE < "${TMPDIR:-/tmp}/codemap-state-ref-${CSID}" 2>/dev/null || SCAN_STATE_FILE=""
[ -n "$SCAN_STATE_FILE" ] && [ -f "$SCAN_STATE_FILE" ] || { printf "! codemap state missing — re-run from the beginning\n"; exit 1; }
# shellcheck source=/dev/null
. "$SCAN_STATE_FILE"
# NUL-delimited args file avoids eval; produced by parse_scan_args.py
_ARGS_FILE="${TMPDIR:-/tmp}/codemap-scan-args-nul-$$-${CSID}"
python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/parse_scan_args.py" "$SCAN_ARGS_RAW" --nul-output "$_ARGS_FILE"
SCAN_ARGS=()
while IFS= read -r -d '' _arg; do
  SCAN_ARGS+=("$_arg")
done < "$_ARGS_FILE"
rm -f "$_ARGS_FILE"
if ! "$SCAN_BIN" --timeout 360 "${SCAN_ARGS[@]}"; then
    printf "! scan-index failed (exit %d) — index may be stale or incomplete\n" "$?"
    # remove sentinel on failure; stale sentinel misleads Step 2
    rm -f "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}-${CSID}"
    exit 1
fi
```

**`--root` naming note**: when `--root <path>` given, index named after `basename(<path>)` — differs from default project index (uses git root's basename). Prior queries/edits against default index: `--root` index separate, queries won't see it unless same `--root` used consistently. Run `resolve_index_env.py` to verify index path after custom-root scan.

Scanner writes to `<root>/.cache/codemap/<project>.json` (or `$CODEMAP_INDEX_DIR/<project>.json` when set) and prints summary line:

```text
[codemap] ✓ .cache/codemap/<project>.json
[codemap]   N modules indexed, M degraded
```

## Step 2: Report

After scan, read index and report compact summary:

```bash
# timeout: 15000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# only report if index exists; Step 1 may have failed
IFS= read -r SCAN_STATE_FILE < "${TMPDIR:-/tmp}/codemap-state-ref-${CSID}" 2>/dev/null || SCAN_STATE_FILE=""
[ -n "$SCAN_STATE_FILE" ] && [ -f "$SCAN_STATE_FILE" ] || { printf "! codemap state missing — re-run /codemap:scan-codebase\n"; exit 1; }
# shellcheck source=/dev/null
. "$SCAN_STATE_FILE"
PROJ_NAME="${PROJ_NAME:-$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")}"
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if [ -f "${_IDX}/${PROJ_NAME}.json" ]; then
    # scan-stats.py reads SCAN_ARGS env var (e.g. "--root src/mypackage") to resolve project root
    SCAN_ARGS="$SCAN_ARGS_RAW" python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-stats.py"
    # --incremental noop check; sentinel set in Step 1 on fallback to full scan
    if [ -f "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}-${CSID}" ]; then
        echo "[codemap] Note: --incremental had no prior index — full scan ran instead"
        rm -f "${TMPDIR:-/tmp}/codemap-incremental-noop-${PROJ_SLUG}-${CSID}"
    fi
else
    echo "[codemap] Skipping stats — no index found (Step 1 may have failed)"
fi
```

Degraded count reported — `scan-stats.py` reports module counts only, no per-file list. Not failure — index still useful.

If `--incremental` passed and no prior index existed, Step 1 sets sentinel file (`codemap-incremental-noop-${PROJ_SLUG}-${CSID}`) before scan starts. Step 2 detects + removes it after stats, logging: `--incremental had no prior index — full scan ran instead`. If scan fails, Step 1 removes sentinel to avoid misleading state next run.

**Sentinel hostname limitation**: `PROJ_SLUG` includes machine hostname short-name. Docker containers/cloud instances with dynamic/random hostnames: sentinel key changes between runs — incremental-noop detection won't fire even with stale sentinel present. Known limitation; affects only Step 2 informational message, not scan correctness.

Zero-Python project: Step 3 suggestions return no results — index valid but empty.

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
