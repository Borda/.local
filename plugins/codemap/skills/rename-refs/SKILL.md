---
name: rename-refs
description: |
  Atomic rename of Python symbols (functions, classes, methods) or modules using the structural index. Finds all static callers, import sites, __all__ re-exports, and Sphinx docstring cross-refs (:func:, :class:, :meth:, :mod:, :attr:). Optional: keep old name as deprecated alias via pydeprecate (--deprecate) or hard-delete when zero callers (--remove-if-no-callers).
  TRIGGER when: user asks to rename a Python function, class, method, or module; phrases: "rename X to Y", "rename function", "rename class", "rename module", "move module X to Y", "update all references to X".
  SKIP: non-Python project; codemap index not built (run /codemap:scan-codebase first); renaming a local variable (not a symbol definition or module path); user explicitly wants grep-only rename without index verification; user performing rename via IDE/LSP and only wants to preview coverage (invoke this skill with --dry-run to get the advisory list without applying edits); splitting one symbol into multiple (this skill handles 1:1 renames only); renaming a package directory (has __init__.py) — use git mv on the directory directly.
argument-hint: "symbol <old_qname> <new_qname> [--dry-run] [--deprecate[=\"@deprecated(...)\"|\"@deprecated_class(...)\"]] [--since <ver>] [--removed-in <ver>] [--remove-if-no-callers] | module <old_module_path> <new_module_path> [--dry-run]"
allowed-tools: Bash, Read, Edit, Write, AskUserQuestion
model: sonnet
effort: medium
---

<objective>

Rename Python symbol or module atomically. Coverage:
- Definition site (def/class line)
- `__all__` re-exports in `__init__.py` files
- Import call sites across all callers (located via fn-rdeps + symbol line-range narrowing)
- Sphinx docstring cross-refs across `.py` and `.rst`
- Optional `@deprecated` alias for old name via pyDeprecate (`--deprecate` inserts a pyDeprecate `@deprecated` wrapper; requires `pyDeprecate` installed)
- Optional hard-delete when exhaustive=true and zero callers

**Subcommands**:
- `symbol <old_qname> <new_qname>` — function, class, or method. qname = bare name (`MyClass`), qualified (`MyClass.method`), or full (`mypackage.auth::validate_token`)
- `module <old_module_path> <new_module_path>` — dotted path (`mypackage.old_name`). Renames file + all import lines.

**Flags**:
- `--dry-run` — print all sites that would change; no edits
- `--deprecate` — symbol only: keep old name as pyDeprecate `@deprecated` wrapper pointing to new name; requires `pyDeprecate` installed
- `--since <ver>` / `--removed-in <ver>` — passed to deprecation decorator; optional, defaults to `"?"`
- `--remove-if-no-callers` — symbol only: delete definition when exhaustive=true + zero callers; requires explicit confirmation

**Hard limits** (static analysis boundary — not fixable):
- `getattr(obj, "old_name")` — string not statically bound to symbol; Step 6 emits grep advisory
- Cross-repo callers — out of scope by definition; use `--deprecate` + semver bump for public APIs

NOT for: building index (`/codemap:scan-codebase`); querying without rename intent (`/codemap:query-code`); non-Python files; renaming symbols in abstract base classes or Protocol definitions where subclass overrides exist — subclass method overrides are not tracked by static import analysis; review `fn-rdeps` output manually and rename overrides explicitly. **Note**: this skill does not support `--index <path>` for alternate index selection — blast-radius and rename queries always use the default project index. For monorepos requiring a specific root, run `/codemap:scan-codebase --root <pkg>` first to build the correct index, then rename.

</objective>

<workflow>

## Step 0: Parse arguments

Parse `$ARGUMENTS` in a single Bash block and write all tokens to project-qualified tmpfiles — subsequent steps read from tmpfiles rather than using shell variables (which die at each Bash() call boundary):

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")

# Parse core positional args
SUBCOMMAND=$(echo "$ARGUMENTS" | awk '{print $1}')
OLD_REF=$(echo "$ARGUMENTS" | awk '{print $2}')
NEW_REF=$(echo "$ARGUMENTS" | awk '{print $3}')

# Parse boolean flags
echo "$ARGUMENTS" | grep -q -- '--dry-run'            && DRY_RUN="true"  || DRY_RUN="false"
echo "$ARGUMENTS" | grep -q -- '--remove-if-no-callers' && REMOVE_IF_ZERO="true" || REMOVE_IF_ZERO="false"

# Parse version flags (POSIX sed — avoids PCRE lookbehind, works on macOS BSD grep)
SINCE_VER=$(echo "$ARGUMENTS" | sed -n 's/.*--since \([^ ]*\).*/\1/p' || echo "")
REMOVED_IN_VER=$(echo "$ARGUMENTS" | sed -n 's/.*--removed-in \([^ ]*\).*/\1/p' || echo "")

# Validate subcommand before proceeding
case "$SUBCOMMAND" in
    symbol|module) ;;
    *) printf "Usage: /codemap:rename-refs symbol <old> <new> [flags] | module <old_path> <new_path> [--dry-run]\n" >&2; exit 1 ;;
esac

# Conflicting flags guard — --deprecate + --remove-if-no-callers are incompatible
echo "$ARGUMENTS" | grep -q -- '--deprecate' && [ "$REMOVE_IF_ZERO" = "true" ] && { printf "⚠ conflicting flags: --deprecate creates alias, --remove-if-no-callers deletes target; these are incompatible\n" >&2; exit 1; }

# Write to project-qualified tmpfiles
printf '%s' "$SUBCOMMAND"     > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-SUBCOMMAND"
printf '%s' "$OLD_REF"        > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF"
printf '%s' "$NEW_REF"        > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-NEW_REF"
printf '%s' "$DRY_RUN"        > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-DRY_RUN"
printf '%s' "$REMOVE_IF_ZERO" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVE_IF_ZERO"
printf '%s' "$SINCE_VER"      > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-SINCE_VER"
printf '%s' "$REMOVED_IN_VER" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVED_IN_VER"

# Bare names for grep patterns
OLD_NAME="${OLD_REF##*::}"; [ "$SUBCOMMAND" = "module" ] && OLD_NAME="${OLD_REF##*.}"
NEW_NAME="${NEW_REF##*::}"; [ "$SUBCOMMAND" = "module" ] && NEW_NAME="${NEW_REF##*.}"
printf '%s' "$OLD_NAME" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME"
printf '%s' "$NEW_NAME" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-NEW_NAME"
```

Parse `--deprecate` — may be bare flag or carry a decorator value:
```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
PARSE_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/parse_deprecate_args.py" --arguments="$ARGUMENTS" 2>"${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-parse-deprecate-err") || { _PARSE_RC=$?; printf "! parse_deprecate_args.py failed (exit %d): %s\n" "$_PARSE_RC" "$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-parse-deprecate-err" 2>/dev/null)" >&2; exit 1; }
FLAG_FILE=$(printf '%s\n' "$PARSE_OUT" | sed -n 1p)   # pid-qualified path printed by the script (SEC-M7)
DEC_FILE=$(printf '%s\n' "$PARSE_OUT" | sed -n 2p)
[ -n "$FLAG_FILE" ] || { printf "! parse_deprecate_args.py returned no paths\n" >&2; exit 1; }
DEPRECATE=$(cat "$FLAG_FILE" 2>/dev/null || echo "false")
DEPRECATE_DECORATOR=$(cat "$DEC_FILE" 2>/dev/null || echo "")
printf '%s' "$DEPRECATE"           > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-DEPRECATE"
printf '%s' "$DEPRECATE_DECORATOR" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-DEPRECATE_DECORATOR"
```

Unsupported flag check — scan `$ARGUMENTS` for `--` tokens not in allowlist (`--dry-run`, `--deprecate`, `--since`, `--removed-in`, `--remove-if-no-callers`). If found: print `! Unknown flag(s): --<token>. Supported flags: --dry-run, --deprecate[=<decorator>], --since, --removed-in, --remove-if-no-callers. Re-invoke with corrected flags.` and stop — do not invoke AskUserQuestion (fail-fast keeps the worst-case AQQ path at 4 calls: STALE-index, multiple-matches, apply/dry-run, hard-delete confirmation).

## Step 1: Validate index

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
# Stderr to tempfile so eval only sees KEY=VAL pairs (shared with integration/SKILL.md C2/I1).
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null  # timeout: 5000
PROJ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-proj" 2>/dev/null || echo "")
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
[ -n "$PROJ" ] || { printf "! resolve_index_env.py failed — check Python availability and CLAUDE_PLUGIN_ROOT\n"; exit 1; }
[ -n "$INDEX" ] || { echo "! index not found — run /codemap:scan-codebase first"; exit 1; }
SMOKE_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" --index-path "$INDEX")  # timeout: 10000
# jq absent — warn and abort (consistent with integration/SKILL.md C4; stale index produces missed call sites)
command -v jq >/dev/null 2>&1 || { printf "! jq not found — required for rename-refs index validation; install via brew install jq or apt-get install jq\n"; exit 1; }
STALE=$(echo "$SMOKE_JSON" | jq -r '.stale // "unknown"' 2>/dev/null || echo "unknown")
```

If `STALE=true` → invoke `AskUserQuestion` — (a) Proceed anyway (callers may be incomplete) · (b) Abort (re-run /codemap:scan-codebase first). On Abort: print "Run `/codemap:scan-codebase` then re-invoke" and stop.
If `STALE=unknown` (JSON parse failed) → print `⚠ Could not determine index freshness — proceeding but callers may be incomplete` and continue with caution; do not silently treat as fresh.

## Step 2: Resolve targets

Locate scan-query binary (three-tier fallback — same as integration/SKILL.md C1):
```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")  # timeout: 5000
```
Use `$SQ` instead of bare `scan-query` in all subsequent Bash blocks.

**Symbol subcommand**:

```bash
# timeout: 25000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
OLD_REF=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF")
FIND_SYMBOL_JSON=$("$SQ" --timeout 20 find-symbol "$OLD_REF" --limit 0)
printf '%s' "$FIND_SYMBOL_JSON" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-find-symbol-json"
```

`find-symbol` returns `matches` array — each entry: `{name, qualified_name, type, module, path, start_line, end_line, source}`. The `source` field (symbol source text) is also present — same schema as `query-code` `symbol` command result. Use `path`, `start_line`, `end_line` for edits; use `qualified_name` for exact-match filtering when multiple results returned. Capture as `FIND_SYMBOL_JSON` — Step 4e reads `.matches[0].type` from it.

- 0 matches → `! Symbol '$OLD_REF' not found. Verify with: scan-query find-symbol <pattern>` and stop.
- Multiple matches → invoke `AskUserQuestion` listing candidates (name, type, module, path) — ask which to rename.

Construct full qname: `<module>::<qualified_name>` (e.g. `mypackage.auth::validate_token`).

```bash
# timeout: 25000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
FIND_SYMBOL_JSON=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-find-symbol-json" 2>/dev/null || echo "{}")
SYM_MODULE=$(echo "$FIND_SYMBOL_JSON" | jq -r '.matches[0].module // ""' 2>/dev/null || echo "")
SYM_QNAME=$(echo "$FIND_SYMBOL_JSON" | jq -r '.matches[0].qualified_name // ""' 2>/dev/null || echo "")
printf '%s' "$SYM_MODULE" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-sym-module"
printf '%s' "$SYM_QNAME"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-sym-qname"
[ -n "$SYM_MODULE" ] && [ -n "$SYM_QNAME" ] || { printf "! could not extract module/qualified_name from find-symbol result\n" >&2; exit 1; }
RDEPS_JSON=$("$SQ" --timeout 20 fn-rdeps "$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-sym-module")::$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-sym-qname")")
RDEP_COUNT=$(echo "$RDEPS_JSON" | jq -r '.count // 0' 2>/dev/null || echo "0")
EXHAUSTIVE=$(echo "$RDEPS_JSON" | jq -r '.index.exhaustive // false' 2>/dev/null || echo "false")
printf '%s' "$RDEP_COUNT"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rdep-count"
printf '%s' "$EXHAUSTIVE"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-EXHAUSTIVE"
```

`fn-rdeps` returns `{qname, called_by:[{caller, module, path}], count, index:{exhaustive,...}}`.
- `called_by` entries have **no line numbers** — use `scan-query symbol <caller>` per entry in Step 4c to get line range.
- Extract `EXHAUSTIVE` from `result["index"]["exhaustive"]`.
- If `exhaustive: false` → note in blast-radius report.

**Module subcommand**:

```bash
# timeout: 25000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
OLD_REF=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF")
OLD_MODULE_PATH="$OLD_REF"
printf '%s' "$OLD_MODULE_PATH" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH"
RDEPS_JSON=$("$SQ" --timeout 20 rdeps "$OLD_REF")
RDEP_COUNT=$(echo "$RDEPS_JSON" | jq -r '.imported_by | length' 2>/dev/null || echo "0")
EXHAUSTIVE=$(echo "$RDEPS_JSON" | jq -r '.index.exhaustive // false' 2>/dev/null || echo "false")
printf '%s' "$RDEP_COUNT"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rdep-count"
printf '%s' "$EXHAUSTIVE"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-EXHAUSTIVE"
# Safety: module subcommand does not support --remove-if-no-callers unless explicitly passed AND exhaustive
REMOVE_IF_ZERO_ARG=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVE_IF_ZERO" 2>/dev/null || echo "false")
[ "$REMOVE_IF_ZERO_ARG" = "true" ] && [ "$EXHAUSTIVE" != "true" ] && printf '%s' "false" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVE_IF_ZERO"
```

Returns `{imported_by:[...], index:{exhaustive,...}}`. Extract `RDEP_COUNT` and `EXHAUSTIVE`.

## Step 3: Blast-radius report + confirmation gate

Print:

```
Rename: <OLD_REF> → <NEW_REF>
Type: symbol | module
[symbol] Definition: <path>:<start_line>-<end_line>

Static callers: N (across N files)
  - src/foo/bar.py   (caller: module::fn)
  - src/foo/baz.py   (caller: module::other_fn)
  - tests/test_foo.py

Docstring refs: (will grep :func:/:class:/:meth:/:mod:/:attr: in Step 4d)

[if DEPRECATE]
Deprecation wrapper: <OLD_REF> kept as @deprecated alias → <NEW_REF>

⚠ Not covered (hard limits — grep advisories in Step 8):
  - getattr("old_name") dynamic dispatch
  - Cross-repo consumers
[if not EXHAUSTIVE]
⚠ Index non-exhaustive — some callers may not appear above
```

**Budget gate**: if caller count > 50 → derive BRANCH first:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
```
Write full caller list to `.temp/output-rename-refs-blast-${BRANCH}-<YYYY-MM-DD>.md`. File must begin with YAML header:
```yaml
---
Title:      rename-refs blast-radius — <OLD_REF>
Date:       <YYYY-MM-DD>
Scope:      <project name>
Focus:      caller enumeration (capped at 50 for edit pass)
Agents:     codemap:rename-refs
Outcome:    <N callers found; exhaustive: true/false>
Confidence: <exhaustive|partial>
Next steps: apply edits for callers 1–50; callers 51–N in this file require manual edit
Path:       → .temp/output-rename-refs-blast-<branch>-<YYYY-MM-DD>.md
---
```
Print path + summary count to terminal, then print `⚠ >50 callers — capping edit pass at first 50. Callers 51–N listed in blast file as manual advisories.` Proceed with first 50 only. **Note**: Step 7 summary will show residual old-name hits for callers 51–N as "skipped callers" — these are expected, not missed dynamic references.

**`--remove-if-no-callers` guards** — evaluated BEFORE any rename edits:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
REMOVE_IF_ZERO=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVE_IF_ZERO" 2>/dev/null || echo "false")
RDEP_COUNT=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rdep-count" 2>/dev/null || echo "0")
EXHAUSTIVE=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-EXHAUSTIVE" 2>/dev/null || echo "false")
```

- `REMOVE_IF_ZERO=true` AND `RDEP_COUNT > 0` → print `! --remove-if-no-callers: N callers found. Remove all callers first or omit flag.` and stop the **entire rename operation**.
- `REMOVE_IF_ZERO=true` AND `EXHAUSTIVE=false` → print `! --remove-if-no-callers requires exhaustive=true. Run /codemap:scan-codebase to ensure full coverage.` and stop the **entire rename operation**.
- `REMOVE_IF_ZERO=true` AND `RDEP_COUNT == 0` AND `EXHAUSTIVE=true` → invoke `AskUserQuestion` — (a) Delete `$OLD_REF` — no callers confirmed, remove definition · (b) Abort — keep file. On Abort: stop. On Delete: use find-symbol to locate the definition line range, then use `Read` to confirm the block bounds, then `Edit` to remove the definition block (from the `def`/`class` line through the final line of the function body, including any immediately preceding `@decorator` lines). Skip Steps 4a–4d. Print `ℹ Symbol had no callers — removed $OLD_REF without rename` and go to Step 6.
- Otherwise (`REMOVE_IF_ZERO=false`): proceed with normal rename flow.

**`--dry-run`**: derive branch first, then write report:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
```
Write report to `.temp/output-rename-refs-dry-${BRANCH}-<YYYY-MM-DD>.md` via Write. Report must begin with YAML header:
```yaml
---
Title:      rename-refs dry-run — <OLD_REF> → <NEW_REF>
Date:       <YYYY-MM-DD>
Scope:      <project name>
Focus:      dry-run: sites that would be changed
Agents:     codemap:rename-refs
Outcome:    DRY_RUN — no edits applied; <N callers, M import sites, K docstring refs>
Confidence: <exhaustive|partial>
Next steps: re-invoke without --dry-run to apply; or abort
Path:       → .temp/output-rename-refs-dry-<branch>-<YYYY-MM-DD>.md
---
```
Print path, then invoke `AskUserQuestion` — (a) Apply for real (re-invoke without --dry-run) · (b) Done. Stop.

Otherwise, invoke `AskUserQuestion` — (a) Apply edits · (b) Abort. On Abort: stop.

## Step 4: Apply edits — symbol rename

Skip to Step 5 if `SUBCOMMAND=module`.

**4a — Rename definition site**:
Read `path` from find-symbol result. Edit the definition line at `start_line`:
- `def old_name(` → `def new_name(`
- `class OldName(` / `class OldName:` → `class NewName(` / `class NewName:`
- Method: match `def old_method(self` pattern within the class body
- **`@property` descriptors**: when the symbol is a property, `find-symbol` returns only the getter. After renaming the getter, grep the same class body for `@old_name.setter` and `@old_name.deleter` decorators — rename them to `@new_name.setter` / `@new_name.deleter` to avoid a broken descriptor (`@old_name.setter` after getter renamed to `new_name` would raise `AttributeError` at class definition time):
  ```bash
  _CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
  OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
  grep -n "@${OLD_NAME}\.setter\|@${OLD_NAME}\.deleter" "<path>"  # timeout: 3000
  ```
- **`@typing.overload` stubs**: after renaming the implementation, grep the same file AND any sibling `.pyi` stub file for `@overload` decorated stubs with `def old_name(` — `find-symbol` returns the implementation only, not overload stubs or stub files. Rename all overload stubs to `new_name` to keep signatures consistent:
  ```bash
  _CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
  OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
  grep -n "@overload" "<path>" "<path%.py>.pyi" 2>/dev/null | grep -A1 "def $OLD_NAME("  # timeout: 3000
  ```

**4b — `__all__` re-exports**:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
FIND_SYMBOL_JSON=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-find-symbol-json" 2>/dev/null || echo "{}")
# scope to pkg tree — avoid same-named symbol false positives
OLD_FILE_PATH=$(echo "$FIND_SYMBOL_JSON" | jq -r '.matches[0].path // "."' 2>/dev/null || echo ".")
PKG_DIR=$(dirname "$OLD_FILE_PATH")
printf '%s' "$PKG_DIR" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-pkg-dir"
_GREP_SCOPE="${PKG_DIR:-.}"
grep -rn "\"$OLD_NAME\"\|'$OLD_NAME'" --include="__init__.py" "$_GREP_SCOPE"
```

For each hit inside an `__all__` list: Edit string entry `"old_name"` → `"new_name"`.

**4c — Import call sites** (per caller from `called_by`):

Track `PROCESSED_IMPORT_FILES` set via tmpfile (files already had import-line edits) — a file with 3 callers needs import-line edit exactly once. Initialize before the import-edit loop:

```bash
# timeout: 3000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
printf '' > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-processed-import-files"
```

Before each import edit for a caller file, check and mark:
```bash
# timeout: 3000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
TARGET_FILE="<caller_path>"
grep -qxF "$TARGET_FILE" "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-processed-import-files" && SKIP_IMPORT="true" || SKIP_IMPORT="false"
[ "$SKIP_IMPORT" = "false" ] && echo "$TARGET_FILE" >> "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-processed-import-files"
```

Only apply import-line edits when `SKIP_IMPORT=false`.

For each caller entry (`called_by[i].caller` is already `module::function` format — pass directly to scan-query):
1. Re-resolve SQ before each caller block (shell var does not persist across Bash() calls):
   ```bash
   # timeout: 5000
   SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
   ```
   Then: `"$SQ" symbol "<caller_qname>"` — timeout: 10000 — result shape: `{symbols:[{path, start_line, end_line, qualified_name, ...}]}`
   - 0 matches → log `⚠ symbol not found for caller <caller_qname> — skipping caller` and continue to next entry
   - Filter `symbols[]` by `qualified_name` matching the expected caller name (exact match preferred); if no exact match, use first entry
   - Use the matched entry's `path`, `start_line`, `end_line` for step 2
2. Within the caller's line range in `path`:
   - **Priority order**: (1) module-level import lines (whole-file scope, safe to apply once per file — may be above `start_line`); (2) qualified calls `X.old_name(` within start_line–end_line; (3) bare calls `old_name(` within start_line–end_line only
   - Edit bare calls `old_name(` → `new_name(` **only** within start_line–end_line range — never bare-replace outside confirmed caller scope
   - **Import dedup**: if `path` already in the `processed-import-files` tmpfile (`SKIP_IMPORT=true`), skip the import-line edit for this caller; only edit call sites within the caller's line range

Module-level import fix (whole-file scope, safe to apply once per file):

```bash
# timeout: 3000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH" 2>/dev/null || echo "")
# SYMBOL subcommand: derive OLD_MODULE_PATH from OLD_REF; keep dotted form — grep matches Python import syntax, not fs paths
if [ -z "$OLD_MODULE_PATH" ]; then
    OLD_REF=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF" 2>/dev/null || echo "")
    OLD_MODULE_PATH=$(echo "$OLD_REF" | sed 's/::.*//')
    printf '%s' "$OLD_MODULE_PATH" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH"
fi
# escape dots — must match literally, not any-char
_OLD_MODULE_GREP=$(printf '%s' "$OLD_MODULE_PATH" | sed 's/\./\\./g')
_OLD_BASENAME_GREP=$(printf '%s' "${OLD_MODULE_PATH##*.}" | sed 's/\./\\./g')
grep -n "from ${_OLD_MODULE_GREP} import .*\b${OLD_NAME}\b\|from .*\\.${_OLD_BASENAME_GREP} import .*\b${OLD_NAME}\b\|^import .*\b${OLD_NAME}\b" "<file>"
```

Edit each matched import line. Verify the `from <module>` clause references the expected module path before editing — skip imports of `OLD_NAME` from unrelated modules. The `processed-import-files` tmpfile is already updated by the dedup block above.

**4d — Sphinx docstring cross-refs**:

```bash
# timeout: 10000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
# Use fully-qualified module prefix where known to avoid false positives on same bare name in unrelated packages
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH" 2>/dev/null || echo "")
# Pattern matches bare name anywhere in role string — verify hit belongs to expected module before editing
grep -rn ":func:\`[^']*$OLD_NAME[^']*\`\|:class:\`[^']*$OLD_NAME[^']*\`\|:meth:\`[^']*$OLD_NAME[^']*\`\|:mod:\`[^']*$OLD_NAME[^']*\`\|:attr:\`[^']*$OLD_NAME[^']*\`" --include="*.py" --include="*.rst" .
```

Edit each match: replace `old_name`/`OldName` within the backtick-delimited role string. Before editing, verify the role string includes the expected module path (`${OLD_MODULE_PATH}` or qualified form) to avoid renaming cross-refs to unrelated packages with the same symbol name.

**4e — Deprecation wrapper** (if `DEPRECATE=true`, after 4a):

Call `gen_deprecation_wrapper.py` to produce the Python code string, then insert it immediately after the new definition block in the same file.

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
FIND_SYMBOL_JSON=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-find-symbol-json" 2>/dev/null || echo "{}")
SYMBOL_TYPE=$(echo "$FIND_SYMBOL_JSON" | jq -r '.matches[0].type // "function"')

OLD_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_NAME")
NEW_NAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-NEW_NAME")
DEPRECATE_DECORATOR=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-DEPRECATE_DECORATOR" 2>/dev/null || echo "")
SINCE_VER=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-SINCE_VER" 2>/dev/null || echo "")
REMOVED_IN_VER=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-REMOVED_IN_VER" 2>/dev/null || echo "")
if [ -n "$DEPRECATE_DECORATOR" ]; then
    DEPRECATION_CODE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/gen_deprecation_wrapper.py" \
        --decorator "$DEPRECATE_DECORATOR" \
        --old-name "$OLD_NAME" \
        ${REMOVED_IN_VER:+--removed-in "$REMOVED_IN_VER"}) || { echo "! gen_deprecation_wrapper failed — check symbol type and names"; exit 1; }
else
    DEPRECATION_CODE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/gen_deprecation_wrapper.py" \
        --type "$SYMBOL_TYPE" \
        --old-name "$OLD_NAME" \
        --new-name "$NEW_NAME" \
        ${SINCE_VER:+--since "$SINCE_VER"} \
        ${REMOVED_IN_VER:+--removed-in "$REMOVED_IN_VER"}) || { echo "! gen_deprecation_wrapper failed — check symbol type and names"; exit 1; }
fi
```

Insert `$DEPRECATION_CODE` as a new block immediately after the end of the new definition (after `end_line` from Step 2). Requires pyDeprecate installed in the target project; if absent, the inserted `from deprecate import ...` will raise `ImportError` at import time — surface this in the Step 6 summary advisory.

Type→decorator mapping:
- `"class"` → `@deprecated_class(target=NewName, ...)` — preserves `isinstance` via transparent proxy
- `"function"` / `"method"` → `@deprecated(target=new_fn, ...)` — `...` body; pydeprecate handles call forwarding

**4f — Hard-delete definition** (if `REMOVE_IF_ZERO=true`):
The zero-caller + exhaustive path is handled entirely in Step 3 — when `REMOVE_IF_ZERO=true` and `RDEP_COUNT == 0`, Step 3 deletes the OLD definition directly and exits before reaching Steps 4a–4d. This step is therefore a **no-op** when reached via normal rename flow: if execution reaches Step 4f, `REMOVE_IF_ZERO` is either `false` or the guards in Step 3 blocked the flow. No action required here.

## Step 5: Apply edits — module rename

**5a — File rename**:

```bash
# timeout: 3000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
git rev-parse --is-inside-work-tree 2>/dev/null || { printf "⚠ not a git repo — cannot use git mv; rename file manually\n" >&2; exit 1; }
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH")
# prefer index path — avoids dotted-path conversion errors on src/ layouts
SMOKE_INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
INDEX_PATH=""
if [ -n "$SMOKE_INDEX" ] && command -v jq >/dev/null 2>&1; then
    INDEX_PATH=$(jq -r --arg m "$OLD_MODULE_PATH" '.modules[$m].path // ""' "$SMOKE_INDEX" 2>/dev/null || echo "")
fi
if [ -n "$INDEX_PATH" ]; then
    old_file_path="$INDEX_PATH"
else
    # dotted-path conversion: may be wrong for src/ layouts or custom --root scans — verify path before git mv
    old_file_path=$(echo "$OLD_MODULE_PATH" | tr '.' '/').py
fi
if [ ! -f "$old_file_path" ] && [ -f "$(echo "$OLD_MODULE_PATH" | tr '.' '/')/__init__.py" ]; then  # MED-15: package dir
    printf "! %s is a package directory — use 'git mv %s %s' directly\n" \
        "$OLD_MODULE_PATH" \
        "$(echo "$OLD_MODULE_PATH" | tr '.' '/')" \
        "$(echo "$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-NEW_REF")" | tr '.' '/')" >&2
    exit 1
fi
[ -f "$old_file_path" ] || { printf "! File not found: %s\n" "$old_file_path" >&2; exit 1; }
printf '%s' "$old_file_path" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-old-file-path"
git status --porcelain "$old_file_path"
```

If output contains `??` prefix: print `! File is untracked — add to git first: git add "<old_file_path>"` and stop.
If output contains any other non-empty prefix (M, A, D, R, C, U): print `! File has uncommitted changes — commit or stash before module rename.` and stop.
If output is empty (clean tracked file): proceed.

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
old_file_path=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-old-file-path")
NEW_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-NEW_REF")
# Derive new file path using the same strategy as old_file_path: prefer index-stored path to avoid
# src/-layout mismatches (tr '.' '/' produces wrong path for src/mypackage/old_name.py).
SMOKE_INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
new_file_path=""
if [ -n "$SMOKE_INDEX" ] && command -v jq >/dev/null 2>&1; then
    new_file_path=$(jq -r --arg m "$NEW_MODULE_PATH" '.modules[$m].path // ""' "$SMOKE_INDEX" 2>/dev/null || echo "")
fi
if [ -z "$new_file_path" ]; then
    # Fallback: dotted-to-path conversion. For src/ layouts, old_file_path gives the correct prefix pattern.
    _OLD_PREFIX=$(dirname "$old_file_path" | sed "s/$(echo "${OLD_MODULE_PATH%.*}" | tr '.' '\/')$//")
    new_file_path="${_OLD_PREFIX}$(echo "$NEW_MODULE_PATH" | tr '.' '/').py"
fi
git mv "$old_file_path" "$new_file_path"
```

**5b — Direct imports**:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH")
# Escape dots so mypackage.old_name matches literally, not any-char.old_name
_OLD_MODULE_GREP=$(printf '%s' "$OLD_MODULE_PATH" | sed 's/\./\\./g')
grep -rn "^import ${_OLD_MODULE_GREP}\b\|^import ${_OLD_MODULE_GREP} as " --include="*.py" .
```

Edit each: `import mypackage.old_name` → `import mypackage.new_name`.

**5c — From-imports**:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH")
# Escape dots so mypackage.old_name matches literally, not any-char.old_name
_OLD_MODULE_GREP=$(printf '%s' "$OLD_MODULE_PATH" | sed 's/\./\\./g')
grep -rn "^from ${_OLD_MODULE_GREP} import\|^from ${_OLD_MODULE_GREP} as " --include="*.py" .
```

Edit each: `from mypackage.old_name import` → `from mypackage.new_name import`.

**5d — `__init__.py` relative re-exports**:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH" 2>/dev/null || echo "")
OLD_BASENAME="${OLD_MODULE_PATH##*.}"  # last component of dotted path
# Restrict to same package dir to avoid false-positive matches on same-named modules elsewhere
OLD_PKG_DIR=$(echo "${OLD_MODULE_PATH%.*}" | tr '.' '/')
grep -rn "from \.*[^.]*\.${OLD_BASENAME} import\|from \.${OLD_BASENAME} import\|from \.${OLD_BASENAME} as " --include="__init__.py" "${OLD_PKG_DIR:-.}" 2>/dev/null
```

Edit each match: `from .old_name import` → `from .new_name import`. Verify match is in the expected package directory before editing — skip matches in unrelated packages.

**5e — pyproject.toml / setup.cfg**:

```bash
# timeout: 3000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH" 2>/dev/null || echo "")
# Use full dotted path (not OLD_BASENAME) to avoid false-positive matches on common names like "utils"
grep -rn "${OLD_MODULE_PATH}" pyproject.toml setup.cfg 2>/dev/null
```

Edit `packages` / `install_requires` entries matching old module path if found. Do NOT use bare `OLD_BASENAME` for this grep — too broad.

**5f — Sphinx docstring `:mod:` refs**:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
OLD_MODULE_PATH=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_MODULE_PATH")
OLD_BASENAME="${OLD_MODULE_PATH##*.}"
# Use full dotted module path first to narrow scope; fall back to basename only when no full-path match
grep -rn ":mod:\`[^']*${OLD_MODULE_PATH}[^']*\`" --include="*.py" --include="*.rst" . 2>/dev/null || \
grep -rn ":mod:\`[^']*${OLD_BASENAME}[^']*\`" --include="*.py" --include="*.rst" .
```

Edit each `:mod:` reference to use new module path. For basename-only matches, verify the surrounding module context matches the expected package before editing to avoid renaming unrelated `:mod:` refs with the same short name.

## Step 6: Re-scan + verify

```bash
# timeout: 400000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
# --incremental re-parses only changed files — sufficient post-rename
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental --timeout 360
_scan_rc=$?
if [ "$_scan_rc" -ne 0 ]; then
    printf "! scan-index --incremental failed — verification may be incomplete; run /codemap:scan-codebase for full rebuild\n"
    # Do not skip verification — attempt find-symbol on stale index; results are advisory only
fi
OLD_REF=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF")
"$SQ" --timeout 20 find-symbol "$OLD_REF" --limit 0  # timeout: 25000
```

For `module`:
```bash
# timeout: 25000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
OLD_REF=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-rename-OLD_REF")
"$SQ" --timeout 20 rdeps "$OLD_REF"
```

Expected: old name absent from results (or present only as deprecated alias for symbol with `--deprecate`).

If old name still found outside deprecated alias: list residual hit files — surface as advisory in Step 7. These are hard-limit cases (dynamic refs, string refs in templates, config strings outside scanned scope).

## Step 7: Summary

Print:

```
✓ Renamed: <OLD_REF> → <NEW_REF>
  Files changed: N
  Call sites updated: M
  Docstring refs updated: K
  [if DEPRECATE] Deprecation alias added at: <path>:<line>

Advisory — check manually (outside static analysis coverage):
  - getattr("<old_name>") dynamic dispatch: grep -rn '"<old_name>"' src/
  [if cross-repo public API and DEPRECATE not used]
  - External consumers: update CHANGELOG; use --deprecate alias until next major release
  [if caller count was capped at 50]
  - Skipped callers (51–N): edit these manually — listed in .temp/output-rename-refs-blast-* file (see blast-radius report from Step 3)
  [if residual hits from Step 6 re-scan]
  - Residual index hits (likely dynamic/string refs):
      <file>:<line>
```

</workflow>
