## Project Detection — Test Runner

Detect test runner once at skill start:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
if [ -f "uv.lock" ] || grep -q '\[tool\.uv\]' pyproject.toml 2>/dev/null; then TEST_CMD="uv run pytest"
elif [ -f "poetry.lock" ] || grep -q '\[tool\.poetry\]' pyproject.toml 2>/dev/null; then TEST_CMD="poetry run pytest"
elif [ -f "tox.ini" ]; then TEST_CMD="tox -q"  # avoids hard-coded py3 env name
elif [ -f "Makefile" ] && grep -q '^test:' Makefile 2>/dev/null; then TEST_CMD="make test"
else TEST_CMD="python -m pytest"; fi
echo "$TEST_CMD" > "${TMPDIR:-/tmp}/dev-test-cmd-${CSID}"
```

Use `$TEST_CMD` for full suite runs.

```bash
# tox/make reject --tb and ::node selectors — derive unwrapped PYTEST_CMD
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r TEST_CMD < "${TMPDIR:-/tmp}/dev-test-cmd-${CSID}" 2>/dev/null || TEST_CMD="python -m pytest"
case "$TEST_CMD" in
    tox*|"make test")
        if command -v uv >/dev/null 2>&1; then PYTEST_CMD="uv run pytest"
        else PYTEST_CMD="python -m pytest"; fi ;;
    *) PYTEST_CMD="$TEST_CMD" ;;
esac
echo "$PYTEST_CMD" > "${TMPDIR:-/tmp}/dev-pytest-cmd-${CSID}"
echo "TEST_CMD=$TEST_CMD PYTEST_CMD=$PYTEST_CMD"
```

Use `$PYTEST_CMD` for single test file/node with pytest-specific flags (`--tb`, `::test_name`); `$TEST_CMD` for full suite.

**Both values are persisted, and every later block must re-read them** — bash state is lost between Bash() calls, so a bare `$PYTEST_CMD` in a later block expands to the empty string and the command silently becomes `--tb=... -v` → `command not found` → exit 127, which downstream exit-code checks misread as a genuine test failure. Read back with:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r PYTEST_CMD < "${TMPDIR:-/tmp}/dev-pytest-cmd-${CSID}" 2>/dev/null || PYTEST_CMD=""
IFS= read -r TEST_CMD   < "${TMPDIR:-/tmp}/dev-test-cmd-${CSID}"   2>/dev/null || TEST_CMD=""
```

Guard on emptiness before running — never let an unresolved command reach the shell.
