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

NOT for: querying existing index (use `/codemap-py:query-code`); integration health checks or wiring consumer integration (use `/codemap-py:integration` — `check`/`plan`/`apply`).

</objective>

<workflow>

## Step 1: Run the scanner

Parse `$ARGUMENTS` to build invocation. Pass `--root <path>` if provided; pass `--incremental` if provided. Construct args conditionally — never pass literal placeholder strings:

**Unknown-flag check** — scan `$ARGUMENTS` for `--` prefixed tokens other than `--root` and `--incremental`. If any remain: print `! Unknown flag(s): <tokens>` followed by `Supported: --root <path>, --incremental`, then exit 1 — do not invoke AskUserQuestion (disable-model-invocation:true makes AskUserQuestion structurally unreachable). Run this check BEFORE invoking `parse_scan_args.py`. Both rosters and the shell below use the same `Unknown flag(s)` wording — never a second synonym. This pre-flight exits `1`, a skill-local shortcut recorded as accepted in `shared/capability-contract.md`; it does not redefine §7.5's `2` for the CLI's own syntax errors.

```bash
# timeout: 10000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# tr|awk, not for-loop — zsh doesn't word-split unquoted vars, for-loop saw whole string as one token, "--root <path>" always false-flagged unsupported
# awk skips token after --root same as old _SKIP_NEXT; parse_scan_args.py handles quoted paths
_ARGS_UNKNOWN=$(printf '%s\n' "$ARGUMENTS" | tr ' ' '\n' \
  | awk '/^--root$/{skip=1;next} skip{skip=0;next} /^--incremental$/{next} /^--/{print}' | tr '\n' ' ')
_ARGS_UNKNOWN="${_ARGS_UNKNOWN% }"
[ -z "$_ARGS_UNKNOWN" ] || { printf "! Unknown flag(s): %s\nSupported: --root <path>, --incremental\n" "$_ARGS_UNKNOWN" >&2; exit 1; }
SETUP_STDERR="${TMPDIR:-/tmp}/codemap-setup-err-$$-${CSID}"
SCAN_STATE_FILE=$(bash "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/setup_scan_env.sh" --arguments "$ARGUMENTS" 2>"$SETUP_STDERR")
if [ $? -ne 0 ] || [ -z "$SCAN_STATE_FILE" ]; then
  printf "! setup_scan_env.sh failed"; [ -s "$SETUP_STDERR" ] && printf ": %s" "$(cat "$SETUP_STDERR")"; printf "\n"; exit 1
fi
# project-scoped — bare CSID collides across concurrent repos in one session
_CM_PROJ_SLUG=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
printf '%s\n' "$SCAN_STATE_FILE" > "${TMPDIR:-/tmp}/codemap-state-ref-${_CM_PROJ_SLUG}-${CSID}"  # subsequent blocks read without knowing PID
```

```bash
# timeout: 400000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_CM_PROJ_SLUG=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
IFS= read -r SCAN_STATE_FILE < "${TMPDIR:-/tmp}/codemap-state-ref-${_CM_PROJ_SLUG}-${CSID}" 2>/dev/null || SCAN_STATE_FILE=""
[ -n "$SCAN_STATE_FILE" ] && [ -f "$SCAN_STATE_FILE" ] || { printf "! codemap state missing — re-run from the beginning\n"; exit 1; }
# -O owned-by-uid, ! -L not-symlink — defense-in-depth on mktemp; last check before sourcing (executed), fails closed on shared-TMPDIR collision
[ -O "$SCAN_STATE_FILE" ] && [ ! -L "$SCAN_STATE_FILE" ] || { printf "! codemap state file failed ownership/symlink check — aborting\n" >&2; exit 1; }
# shellcheck source=/dev/null
. "$SCAN_STATE_FILE"
# NUL-delimited — avoids eval; written by parse_scan_args.py
_ARGS_FILE="${TMPDIR:-/tmp}/codemap-scan-args-nul-$$-${CSID}"
python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/parse_scan_args.py" "$SCAN_ARGS_RAW" --nul-output "$_ARGS_FILE"
SCAN_ARGS=()
while IFS= read -r -d '' _arg; do
  SCAN_ARGS+=("$_arg")
done < "$_ARGS_FILE"
rm -f "$_ARGS_FILE"
# gated dispatcher, not the ungated scan-index alias — the writer lease lives only in `codemap-py index`. SCAN_BIN stays as setup_scan_env.sh's existence preflight (the dispatcher needs the same binary present).
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" index --timeout 360 "${SCAN_ARGS[@]}"
# capture rc BEFORE branching — inside `if ! cmd; then`, $? is the negated compound's status (always 0), never the scanner's
_SCAN_RC=$?
if [ "$_SCAN_RC" -ne 0 ]; then
    printf "! codemap-py index failed (exit %d) — index may be stale or incomplete\n" "$_SCAN_RC"
    # rm sentinel on failure — stale one misleads Step 2
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
# skip if Step 1 failed — index may not exist
_CM_PROJ_SLUG=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
IFS= read -r SCAN_STATE_FILE < "${TMPDIR:-/tmp}/codemap-state-ref-${_CM_PROJ_SLUG}-${CSID}" 2>/dev/null || SCAN_STATE_FILE=""
[ -n "$SCAN_STATE_FILE" ] && [ -f "$SCAN_STATE_FILE" ] || { printf "! codemap state missing — re-run /codemap-py:scan-codebase\n"; exit 1; }
# shellcheck source=/dev/null
. "$SCAN_STATE_FILE"
PROJ_NAME="${PROJ_NAME:-$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")}"
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if [ -f "${_IDX}/${PROJ_NAME}.json" ]; then
    # scan-stats.py reads SCAN_ARGS env (e.g. --root src/mypackage) for project root
    SCAN_ARGS="$SCAN_ARGS_RAW" python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/scan-stats.py"
    # --incremental noop check — sentinel set by Step 1 on fallback to full scan
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
  /codemap-py:query-code central --top 10
  /codemap-py:query-code deps <module>
  /codemap-py:query-code rdeps <module>
  /codemap-py:query-code coupled --top 10
  # see /codemap-py:query-code for full list of subcommands
```

</workflow>
