---
name: test-impact
description: |
  Identify which tests need rerunning after a code change — traces static call graph (function-level) or import graph (module-level) to find affected test files, then emits a ready-to-run pytest command.
  TRIGGER when: user asks which tests are affected by a change; phrases: "which tests are affected", "what tests cover this", "test impact of", "what tests to rerun".
  SKIP: user wants full test suite run; non-Python project; simple grep of test names would suffice.
argument-hint: "<module::symbol | module> [--no-mocks]"
allowed-tools: Bash, Read, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>

Identify the minimal set of tests affected by changing a function or module. Uses codemap static analysis — no test execution needed. Result: ready-to-run `pytest` command covering only the impacted tests.

Two input modes:

- **Function-level** (`module::symbol`) — BFS over reverse call graph; finds every test that calls the changed function, directly or transitively. Also includes tests that mock the symbol (`mock_patches`).
- **Module-level** (bare `module`) — BFS over reverse import graph; finds every test that imports the module through any chain. Also includes tests that mock any symbol in the module.

`not_covered`: dynamic dispatch, hook callbacks, string-dispatch callers — same blind spot as `fn-blast`. Surface caveat and log gap.

</objective>

<inputs>

- **$ARGUMENTS**: `<qname> [--no-mocks]`
  - `qname` — `module::symbol` (function-level) or bare dotted module (module-level)
  - `--no-mocks` — exclude mock-only test files (no call/import path)
  - Omitted → `AskUserQuestion`: "Which function or module changed? (e.g. `mypackage.utils::parse_config` or `mypackage.utils`)"

</inputs>

<workflow>

## Step 0 — Ensure index

```bash
# timeout: 10000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
INDEX="${_IDX}/${_CM_PROJ}.json"

SQ=$(python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null)
if [ -z "$SQ" ]; then
    echo "scan-query not found — install codemap plugin first"
    exit 1
fi
echo "$SQ" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-sq"

if [ ! -f "$INDEX" ]; then
    echo "No index found — will build via codemap:scan-codebase"
fi
```

If `$INDEX` not found → `Skill(skill="codemap:scan-codebase")` then continue.

If index already exists:

```bash
# timeout: 30000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental 2>/dev/null || true
```

## Step 1 — Parse arguments

Extract `QNAME` and `NO_MOCKS` flag from `$ARGUMENTS`.

If `$ARGUMENTS` empty → `AskUserQuestion`: "Which function or module changed?" Options: (a) Enter `module::symbol` for function-level · (b) Enter bare module name for module-level · (c) Cancel — exit without running test-impact analysis.

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
ARGS="${ARGUMENTS:-}"
QNAME=$(echo "$ARGS" | awk '{print $1}')
MOCKS_FLAG=""
if echo "$ARGS" | grep -q -- "--no-mocks"; then
    MOCKS_FLAG="--no-mocks"
fi
echo "$QNAME" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname"
echo "$MOCKS_FLAG" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-mocks"
```

## Step 2 — Run test-impact query

```bash
# timeout: 10000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
QNAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname" 2>/dev/null)
MOCKS_FLAG=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-mocks" 2>/dev/null)
SQ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-sq" 2>/dev/null)
"$SQ" test-impact "$QNAME" $MOCKS_FLAG 2>/dev/null
```

Parse JSON output:
- `test_files` — list of test file paths
- `pytest_cmd` — ready-to-run command
- `via_call` / `via_mock` — breakdown of how tests were found
- `index.not_covered` — surface as caveat if non-empty
- `index.hint` — include as suggestion

Write parsed values to tmpfiles:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
QNAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname" 2>/dev/null)
MOCKS_FLAG=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-mocks" 2>/dev/null)
SQ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-sq" 2>/dev/null)
RESULT=$("$SQ" test-impact "$QNAME" $MOCKS_FLAG 2>/dev/null)
NOT_COVERED=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('index',{}).get('not_covered',[])))" 2>/dev/null || echo "[]")
HINT=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('index',{}).get('hint',''))" 2>/dev/null || echo "")
echo "$NOT_COVERED" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-not-covered"
echo "$HINT" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-hint"
```

## Step 3 — Gap logging

When `index.not_covered` non-empty:

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
QNAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname" 2>/dev/null)
NOT_COVERED=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-not-covered" 2>/dev/null || echo "[]")
HINT=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-hint" 2>/dev/null || echo "")
mkdir -p .cache/codemap
printf '{"ts":"%s","cmd":"test-impact","target":"%s","not_covered":%s,"hint":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$QNAME" "$NOT_COVERED" "$HINT" \
    >> .cache/codemap/gaps.jsonl 2>/dev/null || true
```

## Step 4 — Output

**When `total == 0`**: report "No tests found via static analysis. Try full suite or check with `grep -rn <symbol_name> tests/`."

**When `total > 0`**:

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

Output routing: if `total >= 5` write to `.temp/output-test-impact-<branch>-<YYYY-MM-DD>.md`.

</workflow>
