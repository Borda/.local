---
name: test-impact
description: |
  Identify which tests need rerunning after a code change — traces static call graph (function-level) or import
  graph (module-level) to find affected test files, then emits a ready-to-run pytest command. Trigger with
  `$codemap-py:test-impact <module::symbol | module> [--no-mocks]` for: "which tests are affected", "what tests
  cover this", "test impact of", "what tests to rerun".
---

# Test Impact

Identifies the minimal test set affected by changing a function or module, using codemap-py static analysis — no
test execution needed. Result: a ready-to-run `pytest` command covering only impacted tests.

Two input modes:

- **Function-level** (`module::symbol`) — BFS over the reverse call graph; finds every test calling the changed
  function, directly or transitively. Includes tests mocking the symbol (`mock_patches`).
- **Module-level** (bare `module`) — BFS over the reverse import graph; finds every test importing the module
  through any chain. Includes tests mocking any symbol in the module.

`not_covered`: dynamic dispatch, hook callbacks, string-dispatch callers — same blind spot as `fn-blast`. Surface as
a caveat, do not silently drop it.

NOT for: finding all callers of a function (use `$codemap-py:query-code fn-blast <module::symbol>`); querying
module deps or blast radius (use `$codemap-py:query-code`); running/executing tests (identified here, not
executed).

## Runtime note

Codex has no `bin/` PATH entry and no `$CLAUDE_PLUGIN_ROOT`-equivalent environment variable. Resolve this skill's
installed plugin-root path once, substitute it for `PLUGIN_ROOT` below, and keep it in reasoning — shell state does
not persist across tool calls.

## Inputs

`<qname> [--no-mocks]`:

- `qname` — `module::symbol` (function-level) or a bare dotted module (module-level)
- `--no-mocks` — exclude mock-only test files (no call/import path)
- Omitted → ask in chat which function or module changed, offering: (a) enter `module::symbol` for function-level,
  (b) enter a bare module name for module-level, (c) cancel. Wait for the reply before proceeding.

Multi-symbol guard: the invocation text may contain multiple space-separated tokens. Use only the first token as
`qname`; if more than one remains after stripping `--no-mocks`, warn that test-impact accepts one symbol at a time
and that the remaining tokens need a separate invocation each.

## Workflow

### Step 0 — Ensure index

```bash
PLUGIN_ROOT/bin/codemap-py query test-impact "<qname>" [--no-mocks]
```

If the index is missing:

- `SCAN_NO_AUTOBUILD=1` set → report `codemap index missing and SCAN_NO_AUTOBUILD=1 — refusing to auto-build. Build
  it manually first: $codemap-py:scan-codebase` and stop.
- otherwise → run `PLUGIN_ROOT/bin/codemap-py index --incremental` in the foreground first, then retry the query
  above once.

### Step 1 — Parse the JSON result

- `test_files` — list of test file paths
- `pytest_cmd` — ready-to-run command
- `via_call` / `via_mock` — breakdown of how tests were found
- `index.not_covered` — surface as a caveat if non-empty
- `index.hint` — include as a suggestion

Parse JSON explicitly from the CLI's stdout — do not assume the first line of output is the JSON body; log lines
may precede or follow it.

### Step 2 — Output

**`total == 0`**: report "No tests found via static analysis. Try the full suite or search for the symbol name
directly under `tests/`."

**`total > 0`**:

```
## Test impact: <qname>

**Affected tests** (<total> files, <via_call> via call/import graph, <via_mock> via mocks):
<test_files as bullet list>

**Run:**
```
<pytest_cmd>
```

<if not_covered non-empty>
**Caveat:** dynamic-dispatch / hook-callback callers are not in the static graph — <hint>.
</if>
```

Output routing: if `total >= 5`, write the same content to
`.reports/codex/codemap-py/test-impact-<YYYY-MM-DD>.md` and print the path.
