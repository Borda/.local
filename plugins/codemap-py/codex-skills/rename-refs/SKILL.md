---
name: rename-refs
description: |
  Atomic rename of Python symbols or modules via the structural index — static callers, import sites, `__all__`
  re-exports, Sphinx cross-refs; optional deprecated alias (`--deprecate`) or hard-delete
  (`--remove-if-no-callers`). Trigger with `$codemap-py:rename-refs symbol <old> <new> [flags]` or
  `$codemap-py:rename-refs module <old_path> <new_path> [--dry-run]` for: "rename X to Y" (function/class/method/
  module), "move module X to Y", "update all references to X".
  Skip for: non-Python; index not built (run `$codemap-py:scan-codebase` first); local-variable rename; grep-only
  rename wanted; 1:N symbol splits; package directory rename (use `git mv` directly).
---

# Rename Refs

Renames a Python symbol or module atomically. Coverage:

- Definition site (`def`/`class` line)
- `__all__` re-exports in `__init__.py` files
- Import call sites across all callers (`fn-rdeps` + symbol line-range narrowing)
- Sphinx docstring cross-refs across `.py` and `.rst`
- Optional `@deprecated` alias via pyDeprecate (`--deprecate`; requires `pyDeprecate` installed)
- Optional hard-delete when the caller graph is exhaustive and callers = 0

**Subcommands**:

- `symbol <old_qname> <new_qname>` — function, class, or method. qname = bare (`MyClass`), qualified
  (`MyClass.method`), or full (`mypackage.auth::validate_token`)
- `module <old_module_path> <new_module_path>` — dotted path (`mypackage.old_name`). Renames the file and every
  import line.

**Flags**:

- `--dry-run` — print sites that would change; no edits
- `--deprecate[=<decorator>]` — symbol only: keep the old name as a pyDeprecate `@deprecated` wrapper → new name;
  requires `pyDeprecate`
- `--since <ver>` / `--removed-in <ver>` — passed to the deprecation decorator; default `"?"`
- `--remove-if-no-callers` — symbol only: delete the definition when the caller graph is exhaustive and callers = 0

`--deprecate` and `--remove-if-no-callers` are incompatible (one aliases, the other deletes) — reject the
combination before doing any analysis.

**Hard limits** (static-analysis boundary — not fixable):

- `getattr(obj, "old_name")` — string not statically bound; emit a search advisory in the final summary
- Cross-repo callers — out of scope; use `--deprecate` + a semver bump for public APIs

NOT for: building the index (`$codemap-py:scan-codebase`); querying without rename intent
(`$codemap-py:query-code`); non-Python files; renaming symbols in ABCs/Protocols where subclass overrides exist —
overrides are not tracked by static import analysis, review `fn-rdeps` manually and rename overrides explicitly.
No `--index <path>` support — always uses the default project index. Monorepo: run
`$codemap-py:scan-codebase --root <pkg>` first, then rename.

## Runtime note

Codex has no `bin/` PATH entry and no `$CLAUDE_PLUGIN_ROOT`-equivalent environment variable. Resolve this skill's
installed plugin-root path once, substitute it for `PLUGIN_ROOT` below, and keep it in reasoning — shell state does
not persist across tool calls. Codex has no `AskUserQuestion` tool: every confirmation gate below means "state the
options in chat and wait for the user's next message before proceeding."

## Workflow

### Step 0: Parse arguments

Extract subcommand, old/new refs, and flags from the invocation text. Reject any `--` token outside
`--dry-run`, `--deprecate[=...]`, `--since`, `--removed-in`, `--remove-if-no-callers` with an unknown-flag error and
stop. Reject `--deprecate` + `--remove-if-no-callers` together.

### Step 1: Validate index freshness

```bash
PLUGIN_ROOT/bin/codemap-py query find-symbol "<old_ref>" --limit 0
```

If the index is stale, ask in chat: (a) proceed anyway (callers may be incomplete), or (b) abort and re-run
`$codemap-py:scan-codebase` first. If freshness cannot be determined, warn and proceed with caution — never
silently treat unknown as fresh.

### Step 2: Resolve targets

**Symbol subcommand**:

```bash
PLUGIN_ROOT/bin/codemap-py query find-symbol "<old_ref>" --limit 0
```

`find-symbol` returns a `matches` array — each entry: `{name, qualified_name, type, module, path, start_line,
end_line, source}`. Use `path`/`start_line`/`end_line` for edits, `qualified_name` for exact-match filtering.

- 0 matches → report "Symbol '<old_ref>' not found" and stop.
- Multiple matches → list candidates (name, type, module, path) in chat and ask which to rename; wait for the
  reply.

Full qname: `<module>::<qualified_name>`. Then:

```bash
PLUGIN_ROOT/bin/codemap-py query fn-rdeps "<module>::<qualified_name>"
```

Returns `{qname, called_by:[{caller, module, path}], count, index:{exhaustive,...}}`. `called_by` entries have no
line numbers — resolve each caller's line range with `query symbol <caller>` in Step 4. `exhaustive: false` →
note in the blast-radius report.

**Module subcommand**:

```bash
PLUGIN_ROOT/bin/codemap-py query rdeps "<old_module_path>"
```

Returns `{imported_by:[...], index:{exhaustive,...}}`. `--remove-if-no-callers` is honored only when explicitly
passed and the caller graph is exhaustive.

### Step 3: Blast-radius report and confirmation gate

Print old → new, type, definition location (for symbol), static caller count and files, a note that docstring refs
are grepped in Step 4, and hard-limit caveats (`getattr` dynamic dispatch, cross-repo consumers). If not
exhaustive, add: "index non-exhaustive — some callers may not appear above."

**Caller count > 50**: write the full caller list to
`.reports/codex/codemap-py/rename-refs-blast-<YYYY-MM-DD>.md`, print the path, apply edits for the first 50 only,
and note the remainder require manual edit (listed in that file). Step 6's summary must call these out as
"skipped callers", not missed dynamic references.

**`--remove-if-no-callers` guards** (evaluated before any rename edit):

- callers found → report the count and stop the entire rename — remove all callers first or drop the flag.
- caller graph not exhaustive → report that exhaustive coverage is required (`$codemap-py:scan-codebase` first)
  and stop the entire rename.
- 0 callers and exhaustive → ask in chat: (a) delete the definition — no callers confirmed, or (b) abort. On
  delete: verify the line at `start_line` actually names the expected symbol before editing (mismatch → index may
  be stale, abort without deleting); then remove the definition block (including preceding `@decorator` lines) and
  skip Step 4, going straight to Step 6.
- otherwise: proceed with the normal rename flow.

**`--dry-run`**: write the would-change site list to `.reports/codex/codemap-py/rename-refs-dry-<YYYY-MM-DD>.md`,
print the path, ask in chat whether to apply for real (re-invoke without `--dry-run`) or stop, and wait.

Otherwise, ask in chat: (a) apply edits, or (b) abort. On abort, stop.

### Step 4: Apply edits — symbol rename

Skip to Step 5 if the subcommand is `module`.

1. **Definition site** — edit `def old_name(` / `class OldName(...)`/`class OldName:` at `start_line`. Method:
   match `def old_method(self` inside the class body.
   - **`@property` descriptors**: `find-symbol` returns only the getter. After renaming it, search the same class
     body for `@old_name.setter`/`@old_name.deleter` and rename those too — an unrenamed setter/deleter after the
     getter is renamed raises `AttributeError` at class-definition time.
   - **`@typing.overload` stubs**: after renaming the implementation, search the same file and any sibling `.pyi`
     stub for `@overload`-decorated `def old_name(` — these are not returned by `find-symbol` and must be renamed
     too.
2. **`__all__` re-exports** — search `__init__.py` files under the symbol's package directory for the quoted old
   name inside an `__all__` list and edit each hit.
3. **Import call sites** — per caller from `called_by`, resolve its line range with
   `PLUGIN_ROOT/bin/codemap-py query symbol "<caller_qname>"`, then within that range: fix module-level import
   lines first (whole-file scope, once per file — track which files already got their import line fixed so a file
   with 3 callers isn't edited 3 times), then qualified calls `X.old_name(`, then bare calls `old_name(` — never
   bare-replace outside the confirmed caller's line range. A caller not found in the index → warn and skip it,
   don't fail the whole rename.
4. **Sphinx docstring cross-refs** — search `.py` and `.rst` for `:func:`/`:class:`/`:meth:`/`:mod:`/`:attr:` roles
   containing the old name; before editing, verify the role string's module context matches the renamed symbol's
   module to avoid touching an unrelated same-named symbol elsewhere.
5. **Deprecation wrapper** (`--deprecate`) — after step 1, generate the wrapper via
   `PLUGIN_ROOT/bin/gen_deprecation_wrapper.py` (type→decorator: `class` → `@deprecated_class(target=NewName,
   ...)`, preserving `isinstance`; `function`/`method` → `@deprecated(target=new_fn, ...)`), insert it immediately
   after the new definition. Requires `pyDeprecate` installed in the target project — if absent, the inserted
   import raises `ImportError` at import time; surface that as an advisory in Step 6.
6. **Hard-delete** — handled entirely in Step 3's zero-caller/exhaustive branch; no separate action here.

### Step 5: Apply edits — module rename

1. **File rename** — refuse if not a git repo, if the file is untracked (`git add` it first), or if it has
   uncommitted changes (commit/stash first). Then `git mv <old_file_path> <new_file_path>` — prefer the index's
   recorded file path over dotted-path-to-filesystem-path conversion, which can be wrong under `src/` layouts. A
   package directory (has `__init__.py`) is out of scope here — report the direct `git mv` command instead of
   attempting it.
2. **Direct imports** — `import mypackage.old_name` / `import mypackage.old_name as X` → new dotted path.
3. **From-imports** — `from mypackage.old_name import ...` → new dotted path.
4. **`__init__.py` relative re-exports** — `from .old_name import ...` inside the same package directory → new
   basename; verify the match is in the expected package directory before editing.
5. **`pyproject.toml` / `setup.cfg`** — search for the full old dotted path (not the bare basename — too broad,
   e.g. `utils`) and edit `packages`/`install_requires` entries if found.
6. **Sphinx `:mod:` refs** — search for the full dotted path first, falling back to basename-only matches with a
   module-context check before editing.

### Step 6: Re-scan and verify

```bash
PLUGIN_ROOT/bin/codemap-py index --incremental
PLUGIN_ROOT/bin/codemap-py query find-symbol "<old_ref>" --limit 0    # symbol
PLUGIN_ROOT/bin/codemap-py query rdeps "<old_ref>"                     # module
```

Re-scan failure → report it but continue; verification results become advisory rather than authoritative in that
case. Expected: the old name is absent (or present only as the deprecated alias, for `--deprecate` symbol renames).
Any other residual hit → list the file(s) as advisory in Step 7 (hard-limit case: dynamic refs, string refs in
templates, config strings outside scanned scope).

### Step 7: Summary

```text
✓ Renamed: <old_ref> → <new_ref>
  Files changed: N
  Call sites updated: M
  Docstring refs updated: K
  [if --deprecate] Deprecation alias added at: <path>:<line>

Advisory — check manually (outside static analysis coverage):
  - getattr("<old_name>") dynamic dispatch: search src/ for the literal string
  [if cross-repo public API and --deprecate not used]
  - External consumers: update CHANGELOG; use --deprecate alias until the next major release
  [if caller count was capped at 50]
  - Skipped callers (51–N): edit these manually — listed in the blast-radius report from Step 3
  [if residual hits from Step 6 re-scan]
  - Residual index hits (likely dynamic/string refs): <file>:<line>
```
