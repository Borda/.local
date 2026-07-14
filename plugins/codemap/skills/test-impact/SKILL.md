---
name: test-impact
description: "Identify which tests need rerunning after a code change — traces static call graph (function-level) or import graph (module-level) to find affected test files, then emits a ready-to-run pytest command. TRIGGER when: user asks which tests are affected by a change; phrases: \"which tests are affected\", \"what tests cover this\", \"test impact of\", \"what tests to rerun\"."
argument-hint: "<module::symbol | module> [--no-mocks]"
allowed-tools: Bash, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>

Identifies minimal test set affected by changing a function or module. Uses codemap static analysis — no test execution needed. Result: ready-to-run `pytest` command covering only impacted tests.

Two input modes:

- **Function-level** (`module::symbol`) — BFS over reverse call graph; finds every test calling changed function, directly or transitively. Includes tests mocking the symbol (`mock_patches`).
- **Module-level** (bare `module`) — BFS over reverse import graph; finds every test importing module through any chain. Includes tests mocking any symbol in module.

`not_covered`: dynamic dispatch, hook callbacks, string-dispatch callers — same blind spot as `fn-blast`. Surface caveat, log gap.

NOT for: finding all callers of a function (use `/codemap:query-code fn-blast <module::symbol>`); querying module deps or blast radius (use `/codemap:query-code`); running/executing tests (identified here, not executed).

</objective>

<inputs>

- **$ARGUMENTS**: `<qname> [--no-mocks]`
  - `qname` — `module::symbol` (function-level) or bare dotted module (module-level)
  - `--no-mocks` — exclude mock-only test files (no call/import path)
  - Omitted → AskUserQuestion in Step 1

</inputs>

<workflow>

## Step 0 — Ensure index

```bash
# timeout: 10000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
INDEX="${_IDX}/${_CM_PROJ}.json"

SQ=$(python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null)
[ -z "$SQ" ] && { echo "scan-query not found — install codemap plugin first"; exit 1; }
echo "$SQ" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-sq"

[ ! -f "$INDEX" ] && echo "No index found — will build via codemap:scan-codebase"
```

Auto-build opt-out via `SCAN_NO_AUTOBUILD=1` (index used exactly as-is — no refresh, no full build); build wall-time echoed when it runs, keeps build cost separable from query cost.

If `$INDEX` not found:
- `SCAN_NO_AUTOBUILD=1` set → print `! codemap index missing and SCAN_NO_AUTOBUILD=1 — refusing to auto-build. Build it manually first: /codemap:scan-codebase` and exit 1.
- otherwise → `Skill(skill="codemap:scan-codebase")` then continue.

If index already exists:

```bash
# timeout: 30000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if [ "${SCAN_NO_AUTOBUILD:-0}" = "1" ]; then
    echo "[codemap] SCAN_NO_AUTOBUILD=1 — using existing index as-is (no refresh)"
else
    _CM_BUILD_T0=$(date +%s)
    # forward CODEMAP_INDEX_DIR; ensures scan-index writes to same path as INDEX
    CODEMAP_INDEX_DIR="${_IDX}" "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental \
        && echo "[codemap] index built in $(( $(date +%s) - _CM_BUILD_T0 ))s" \
        || printf "⚠ scan-index --incremental failed — index may be stale; continuing\n"
fi
```

After Skill() or incremental refresh, re-verify index still present:
```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
INDEX="${_IDX}/${_CM_PROJ}.json"
[ -f "$INDEX" ] || { printf "! Index not found after refresh at %s — check CODEMAP_INDEX_DIR or re-run /codemap:scan-codebase\n" "$INDEX"; exit 1; }
```

## Step 1 — Parse arguments

Extract `QNAME` and `NO_MOCKS` flag from `$ARGUMENTS`.

```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
ARGS="${ARGUMENTS:-}"
QNAME=$(echo "$ARGS" | awk '{print $1}')
MOCKS_FLAG=$(echo "$ARGS" | grep -q -- "--no-mocks" && echo "--no-mocks" || echo "")
echo "$QNAME" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname"
echo "$MOCKS_FLAG" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-mocks"
```

If `$ARGUMENTS` empty → `AskUserQuestion`: "Which function or module changed?" Options: (a) Enter `module::symbol` for function-level · (b) Enter bare module name for module-level · (c) Cancel — exit without running test-impact analysis. After the user answers, set `QNAME` from the answer and write it to the tmpfile before proceeding to Step 2:
```bash
# timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
QNAME="<answer from AskUserQuestion>"
echo "$QNAME" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname"
```

**Multi-symbol guard**: `$ARGUMENTS` may contain multiple space-separated tokens (e.g. `mypackage.auth::validate mypackage.auth::parse`). `awk '{print $1}'` silently truncates to first. If `$ARGUMENTS` has more than one token after stripping `--no-mocks`, print `⚠ test-impact accepts one symbol at a time — using first token only: $QNAME. Run separately for each remaining symbol.`

## Step 2 — Run test-impact query

```bash
# timeout: 10000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$PWD")
QNAME=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-qname" 2>/dev/null)
MOCKS_FLAG=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-mocks" 2>/dev/null)
SQ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-sq" 2>/dev/null)
RESULT=$("$SQ" test-impact "$QNAME" $MOCKS_FLAG 2>/dev/null)
NOT_COVERED=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('index',{}).get('not_covered',[])))" 2>/dev/null || echo "[]")
HINT=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('index',{}).get('hint',''))" 2>/dev/null || echo "")
TOTAL=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('test_files',[])))" 2>/dev/null || echo "0")
PYTEST_CMD=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pytest_cmd',''))" 2>/dev/null || echo "")
echo "$NOT_COVERED" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-not-covered"
echo "$HINT"        > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-hint"
echo "$TOTAL"       > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-total"
echo "$PYTEST_CMD"  > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-ti-pytest-cmd"
```

Parse JSON output from `$RESULT`:
- `test_files` — list of test file paths
- `pytest_cmd` — ready-to-run command
- `via_call` / `via_mock` — breakdown of how tests were found
- `index.not_covered` — surface as caveat if non-empty
- `index.hint` — include as suggestion

**haiku JSON parse guard**: `scan-query` JSON output may be prefixed/suffixed with log/warning lines under haiku model. Always extract JSON via `python3 -c "import sys,json; ..."` piping stdin — never assume raw output valid JSON. Parsing fails (ValueError/JSONDecodeError) → print `! scan-query returned non-JSON output — try /codemap:scan-codebase to rebuild index` and exit 1.

## Step 3 — Output

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
