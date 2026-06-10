---
name: rename-refs
description: |
  Atomic rename of Python symbols (functions, classes, methods) or modules using the structural index. Finds all static callers, import sites, __all__ re-exports, and Sphinx docstring cross-refs (:func:, :class:, :meth:, :mod:, :attr:). Optional: keep old name as deprecated alias via pydeprecate (--deprecate) or hard-delete when zero callers (--remove-if-no-callers).
  TRIGGER when: user asks to rename a Python function, class, method, or module; phrases: "rename X to Y", "rename function", "rename class", "rename module", "move module X to Y", "refactor symbol X into Y", "update all references to X".
  SKIP: non-Python project; codemap index not built (run /codemap:scan-codebase first); renaming a local variable (not a symbol definition or module path); user explicitly wants grep-only rename without index verification; user performing rename via IDE/LSP and only wants advisory coverage (use --dry-run).
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
- Optional `@deprecated` alias for old name (pydeprecate with `warnings.warn` fallback)
- Optional hard-delete when exhaustive=true and zero callers

**Subcommands**:
- `symbol <old_qname> <new_qname>` — function, class, or method. qname = bare name (`MyClass`), qualified (`MyClass.method`), or full (`mypackage.auth::validate_token`)
- `module <old_module_path> <new_module_path>` — dotted path (`mypackage.old_name`). Renames file + all import lines.

**Flags**:
- `--dry-run` — print all sites that would change; no edits
- `--deprecate` — symbol only: keep old name as `@deprecated` wrapper pointing to new name
- `--since <ver>` / `--removed-in <ver>` — passed to deprecation decorator; optional, defaults to `"?"`
- `--remove-if-no-callers` — symbol only: delete definition when exhaustive=true + zero callers; requires explicit confirmation

**Hard limits** (static analysis boundary — not fixable):
- `getattr(obj, "old_name")` — string not statically bound to symbol; Step 6 emits grep advisory
- Cross-repo callers — out of scope by definition; use `--deprecate` + semver bump for public APIs

NOT for: building index (`/codemap:scan-codebase`); querying without rename intent (`/codemap:query-code`); non-Python files; renaming symbols in abstract base classes or Protocol definitions where subclass overrides exist — subclass method overrides are not tracked by static import analysis; review `fn-rdeps` output manually and rename overrides explicitly.

</objective>

<workflow>

## Step 0: Parse arguments

Extract from `$ARGUMENTS`:
- `SUBCOMMAND` — first token: `symbol` or `module`
- `OLD_REF` — second token
- `NEW_REF` — third token
- `DRY_RUN` — true if `--dry-run` present
- `DEPRECATE` — true if `--deprecate` or `--deprecate=<value>` present (symbol only)
- `DEPRECATE_DECORATOR` — value after `--deprecate=` (empty if bare `--deprecate`); when non-empty, used as explicit decorator line passed to `gen_deprecation_wrapper.py --decorator`; example: `--deprecate="@deprecated(target=bar, deprecated_in='1.0', remove_in='2.0')"`
- `SINCE_VER` — value after `--since` (empty if absent)
- `REMOVED_IN_VER` — value after `--removed-in` (empty if absent)
- `REMOVE_IF_ZERO` — true if `--remove-if-no-callers` present (symbol only)

If `SUBCOMMAND` absent or not `symbol`/`module`: print usage hint and stop.

Derive bare names for grep patterns:
- `OLD_NAME="${OLD_REF##*::}"` — strip module prefix, e.g. `mypackage.auth::validate_token` → `validate_token`
- `NEW_NAME="${NEW_REF##*::}"`
- For module subcommand, `OLD_NAME="${OLD_REF##*.}"` (last dotted component) and `NEW_NAME="${NEW_REF##*.}"`

Parse `--deprecate` — may be bare flag or carry a decorator value:
```bash
DEPRECATE=false; DEPRECATE_DECORATOR=""
if echo "$ARGUMENTS" | grep -qE -- '--deprecate=[^ ]+'; then
    DEPRECATE=true
    DEPRECATE_DECORATOR=$(echo "$ARGUMENTS" | grep -oE -- '--deprecate=[^ ]+' | head -1 | sed 's/--deprecate=//')
    DEPRECATE_DECORATOR=$(echo "$DEPRECATE_DECORATOR" | sed "s/^['\"]//;s/['\"]$//")  # strip surrounding quotes
elif echo "$ARGUMENTS" | grep -q -- '--deprecate'; then
    DEPRECATE=true
fi
```

Unsupported flag check — scan `$ARGUMENTS` for `--` tokens not in allowlist (`--dry-run`, `--deprecate`, `--since`, `--removed-in`, `--remove-if-no-callers`). If found: print `! Unknown flag(s): --<token>. Supported flags: --dry-run, --deprecate[=<decorator>], --since, --removed-in, --remove-if-no-callers. Re-invoke with corrected flags.` and stop — do not invoke AskUserQuestion (fail-fast keeps the worst-case AQQ path at 4 calls: STALE-index, multiple-matches, apply/dry-run, hard-delete confirmation).

## Step 1: Validate index

```bash
# timeout: 5000
# resolve_proj_index.py outputs 2 lines: PROJ name on line 1, INDEX path on line 2
# Capture line 2 only (index path) — do not use bare $() which would combine both lines
INDEX=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_proj_index.py" 2>/dev/null | sed -n '2p')
[ -n "$INDEX" ] || { echo "! index not found — run /codemap:scan-codebase first"; exit 1; }
SMOKE_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" --index-path "$INDEX")  # timeout: 10000
STALE=$(echo "$SMOKE_JSON" | jq -r '.stale // "unknown"' 2>/dev/null || echo "unknown")
```

If `STALE=true` → invoke `AskUserQuestion` — (a) Proceed anyway (callers may be incomplete) · (b) Abort (re-run /codemap:scan-codebase first). On Abort: print "Run `/codemap:scan-codebase` then re-invoke" and stop.
If `STALE=unknown` (jq absent or JSON parse failed) → print `⚠ Could not determine index freshness — proceeding but callers may be incomplete` and continue with caution; do not silently treat as fresh.

## Step 2: Resolve targets

**Symbol subcommand**:

```bash
FIND_SYMBOL_JSON=$(scan-query --timeout 20 find-symbol "$OLD_REF" --limit 0)  # timeout: 25000
```

`find-symbol` returns `matches` array — each entry: `{name, qualified_name, type, module, path, start_line, end_line, source}`. The `source` field (symbol source text) is also present — same schema as `query-code` `symbol` command result. Use `path`, `start_line`, `end_line` for edits; use `qualified_name` for exact-match filtering when multiple results returned. Capture as `FIND_SYMBOL_JSON` — Step 4e reads `.matches[0].type` from it.

- 0 matches → `! Symbol '$OLD_REF' not found. Verify with: scan-query find-symbol <pattern>` and stop.
- Multiple matches → invoke `AskUserQuestion` listing candidates (name, type, module, path) — ask which to rename.

Construct full qname: `<module>::<qualified_name>` (e.g. `mypackage.auth::validate_token`).

```bash
scan-query --timeout 20 fn-rdeps "<MODULE>::<QUALIFIED_NAME>"
```

`fn-rdeps` returns `{qname, called_by:[{caller, module, path}], count, index:{exhaustive,...}}`.
- `called_by` entries have **no line numbers** — use `scan-query symbol <caller>` per entry in Step 4c to get line range.
- Extract `EXHAUSTIVE` from `result["index"]["exhaustive"]`.
- If `exhaustive: false` → note in blast-radius report.

**Module subcommand**:

```bash
scan-query --timeout 20 rdeps "$OLD_REF"
```

Returns `{imported_by:[...], index:{exhaustive,...}}`. Extract `EXHAUSTIVE`.

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

**Budget gate**: if caller count > 50 → write full caller list to `.temp/output-rename-refs-blast-<branch>-<YYYY-MM-DD>.md`, print path + summary count to terminal, then print `⚠ >50 callers — capping edit pass at first 50. Remainder listed as manual advisories in Step 6.` Proceed with first 50 only. Print the file path before the AskUserQuestion gate so user can review the full list.

**`--remove-if-no-callers` guards**:
- Caller count > 0 → print `! --remove-if-no-callers: N callers found. Remove all callers first or omit flag.` and stop the **entire rename operation** (not just the deletion step).
- `EXHAUSTIVE=false` → print `! --remove-if-no-callers requires exhaustive=true. Run /codemap:scan-codebase to ensure full coverage.` and stop the **entire rename operation**.
- When guards pass (0 callers + exhaustive): proceed with rename in Steps 4a–4d, then the deletion confirmation in Step 4f applies to the **definition site only** — all import/call sites have already been cleaned by 4b–4c.

**`--dry-run`**: derive branch first, then write report:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')
```
Write report to `.temp/output-rename-refs-dry-${BRANCH}-<YYYY-MM-DD>.md` via Write, print path, then invoke `AskUserQuestion` — (a) Apply for real (re-invoke without --dry-run) · (b) Done. Stop.

Otherwise, invoke `AskUserQuestion` — (a) Apply edits · (b) Abort. On Abort: stop.

## Step 4: Apply edits — symbol rename

Skip to Step 5 if `SUBCOMMAND=module`.

**4a — Rename definition site**:
Read `path` from find-symbol result. Edit the definition line at `start_line`:
- `def old_name(` → `def new_name(`
- `class OldName(` / `class OldName:` → `class NewName(` / `class NewName:`
- Method: match `def old_method(self` pattern within the class body
- **`@typing.overload` stubs**: after renaming the implementation, grep the same file for `@overload` decorated stubs with `def old_name(` — `find-symbol` returns the implementation only, not overload stubs. Rename all overload stubs in the same file to `new_name` to keep signatures consistent.

**4b — `__all__` re-exports**:

```bash
grep -rn "\"$OLD_NAME\"\|'$OLD_NAME'" --include="__init__.py" .  # timeout: 5000
```

For each hit inside an `__all__` list: Edit string entry `"old_name"` → `"new_name"`.

**4c — Import call sites** (per caller from `called_by`):
For each caller entry (`called_by[i].caller` is already `module::function` format — pass directly to scan-query):
1. `scan-query symbol "<caller_qname>"` — timeout: 10000 — result shape: `{symbols:[{path, start_line, end_line, qualified_name, ...}]}`
   - 0 matches → log `⚠ symbol not found for caller <caller_qname> — skipping caller` and continue to next entry
   - Filter `symbols[]` by `qualified_name` matching the expected caller name (exact match preferred); if no exact match, use first entry
   - Use the matched entry's `path`, `start_line`, `end_line` for step 2
2. Within the caller's line range in `path`:
   - **Priority order**: (1) module-level import lines (whole-file scope, safe to apply once per file — may be above `start_line`); (2) qualified calls `X.old_name(` within start_line–end_line; (3) bare calls `old_name(` within start_line–end_line only
   - Edit bare calls `old_name(` → `new_name(` **only** within start_line–end_line range — never bare-replace outside confirmed caller scope
   - Module-level imports edited once per file (not per caller) — deduplicate if multiple callers are in the same file

Module-level import fix (whole-file scope, safe to apply once per file):

```bash
# Use fully-qualified module path in from-import grep to avoid matching same-named symbols from unrelated modules
grep -n "from ${OLD_MODULE_PATH} import .*\b${OLD_NAME}\b\|from .*\.${OLD_MODULE_PATH##*.} import .*\b${OLD_NAME}\b\|^import .*\b${OLD_NAME}\b" "<file>"  # timeout: 3000
```

Edit each matched import line. Verify the `from <module>` clause references the expected module path before editing — skip imports of `OLD_NAME` from unrelated modules.

**4d — Sphinx docstring cross-refs**:

```bash
grep -rn ":func:\`[^']*$OLD_NAME[^']*\`\|:class:\`[^']*$OLD_NAME[^']*\`\|:meth:\`[^']*$OLD_NAME[^']*\`\|:mod:\`[^']*$OLD_NAME[^']*\`\|:attr:\`[^']*$OLD_NAME[^']*\`" --include="*.py" --include="*.rst" .  # timeout: 10000
```

Edit each match: replace `old_name`/`OldName` within the backtick-delimited role string.

**4e — Deprecation wrapper** (if `DEPRECATE=true`, after 4a):

Call `gen_deprecation_wrapper.py` to produce the Python code string, then insert it immediately after the new definition block in the same file.

```bash
# FIND_SYMBOL_JSON captured in Step 2 — extract type for auto mode
SYMBOL_TYPE=$(echo "$FIND_SYMBOL_JSON" | jq -r '.matches[0].type // "function"')  # timeout: 3000

if [ -n "$DEPRECATE_DECORATOR" ]; then
    # Explicit mode — user supplied full decorator line via --deprecate="@deprecated(...)"
    DEPRECATION_CODE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/gen_deprecation_wrapper.py" \
        --decorator "$DEPRECATE_DECORATOR" \
        --old-name "$OLD_NAME" \
        ${REMOVED_IN_VER:+--removed-in "$REMOVED_IN_VER"})  # timeout: 5000
else
    # Auto mode — derive decorator from symbol type + names + versions
    DEPRECATION_CODE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/gen_deprecation_wrapper.py" \
        --type "$SYMBOL_TYPE" \
        --old-name "$OLD_NAME" \
        --new-name "$NEW_NAME" \
        ${SINCE_VER:+--since "$SINCE_VER"} \
        ${REMOVED_IN_VER:+--removed-in "$REMOVED_IN_VER"})  # timeout: 5000
fi
[ $? -eq 0 ] || { echo "! gen_deprecation_wrapper failed — check symbol type and names"; exit 1; }
```

Insert `$DEPRECATION_CODE` as a new block immediately after the end of the new definition (after `end_line` from Step 2). Requires pyDeprecate installed in the target project; if absent, the inserted `from deprecate import ...` will raise `ImportError` at import time — surface this in the Step 6 summary advisory.

Type→decorator mapping:
- `"class"` → `@deprecated_class(target=NewName, ...)` — preserves `isinstance` via transparent proxy
- `"function"` / `"method"` → `@deprecated(target=new_fn, ...)` — `...` body; pydeprecate handles call forwarding

**4f — Hard-delete definition** (if `REMOVE_IF_ZERO=true`):
Note: steps 4a–4e have already renamed the definition. The deletion here removes the **new-name** definition (which has zero callers as confirmed in Step 3).
Invoke `AskUserQuestion` listing: file path, start_line–end_line, definition source (showing new name). Options: (a) Confirm delete (0 callers confirmed — safe to remove) · (b) Keep definition (skip deletion). On Keep: skip deletion; the new-name definition remains in place.
On Confirm: Edit to remove the definition block (start_line through end_line, inclusive of any decorator lines immediately above).

## Step 5: Apply edits — module rename

**5a — File rename**:

```bash
git status --porcelain "<old_file_path>"  # timeout: 3000
```

If output contains `??` prefix: print `! File is untracked — add to git first: git add "<old_file_path>"` and stop.
If output contains any other non-empty prefix (M, A, D, R, C, U): print `! File has uncommitted changes — commit or stash before module rename.` and stop.
If output is empty (clean tracked file): proceed.

Derive `old_file_path` from `old_module_path` (replace `.` with `/`, append `.py`) relative to project root.

```bash
git mv "<old_file_path>" "<new_file_path>"  # timeout: 5000
```

**5b — Direct imports**:

```bash
grep -rn "^import ${OLD_MODULE_PATH}\b\|^import ${OLD_MODULE_PATH} as " --include="*.py" .  # timeout: 5000
```

Edit each: `import mypackage.old_name` → `import mypackage.new_name`.

**5c — From-imports**:

```bash
grep -rn "^from ${OLD_MODULE_PATH} import\|^from ${OLD_MODULE_PATH} as " --include="*.py" .  # timeout: 5000
```

Edit each: `from mypackage.old_name import` → `from mypackage.new_name import`.

**5d — `__init__.py` relative re-exports**:

```bash
OLD_BASENAME="${OLD_MODULE_PATH##*.}"  # last component of dotted path
# Restrict grep to __init__.py files within the same package directory to avoid false-positive
# matches on same-named modules in unrelated packages (e.g. utils.py in multiple packages)
OLD_PKG_DIR=$(echo "${OLD_MODULE_PATH%.*}" | tr '.' '/')
# Pattern covers: .old_name, ..old_name, ...old_name, .subpkg.old_name (all relative import depths)
grep -rn "from \.*[^.]*\.${OLD_BASENAME} import\|from \.${OLD_BASENAME} import\|from \.${OLD_BASENAME} as " --include="__init__.py" "${OLD_PKG_DIR:-.}" 2>/dev/null  # timeout: 5000
```

Edit each match: `from .old_name import` → `from .new_name import`. Verify match is in the expected package directory before editing — skip matches in unrelated packages.

**5e — pyproject.toml / setup.cfg**:

```bash
# Use OLD_MODULE_PATH (dotted full path) for pyproject.toml/setup.cfg to avoid false-positive matches
# on OLD_BASENAME alone (e.g. "utils" matches unrelated config strings)
grep -rn "${OLD_MODULE_PATH}" pyproject.toml setup.cfg 2>/dev/null  # timeout: 3000
```

Edit `packages` / `install_requires` entries matching old module path if found. Do NOT use bare `OLD_BASENAME` for this grep — too broad.

**5f — Sphinx docstring `:mod:` refs**:

```bash
grep -rn ":mod:\`[^']*${OLD_BASENAME}[^']*\`" --include="*.py" --include="*.rst" .  # timeout: 5000
```

Edit each `:mod:` reference to use new module path.

## Step 6: Re-scan + verify

```bash
# --incremental: re-parses only files changed since last scan — sufficient for post-rename verification
# scan-index with no extra args scans from git root (default behavior, same as /codemap:scan-codebase)
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental --timeout 360 || { printf "! scan-index --incremental failed — run /codemap:scan-codebase for full rebuild\n"; }
scan-query --timeout 20 find-symbol "$OLD_REF" --limit 0
```

For `module`: `scan-query --timeout 20 rdeps "$OLD_REF"`

Expected: old name absent from results (or present only as deprecated alias for symbol with `--deprecate`).

If old name still found outside deprecated alias: list residual hit files — surface as advisory in Step 6. These are hard-limit cases (dynamic refs, string refs in templates, config strings outside scanned scope).

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
  [if residual hits from Step 5]
  - Residual index hits (likely dynamic/string refs):
      <file>:<line>
```

</workflow>
