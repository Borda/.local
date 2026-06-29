## Project Detection — Test Runner

Detect test runner once at skill start:

```bash
if [ -f "uv.lock" ] || grep -q '\[tool\.uv\]' pyproject.toml 2>/dev/null; then TEST_CMD="uv run pytest"
elif [ -f "poetry.lock" ] || grep -q '\[tool\.poetry\]' pyproject.toml 2>/dev/null; then TEST_CMD="poetry run pytest"
elif [ -f "tox.ini" ]; then TEST_CMD="tox -q"  # avoids hard-coded py3 env name
elif [ -f "Makefile" ] && grep -q '^test:' Makefile 2>/dev/null; then TEST_CMD="make test"
else TEST_CMD="python -m pytest"; fi
```

Use `$TEST_CMD` for full suite runs.

```bash
# tox/make reject --tb and ::node selectors — derive unwrapped PYTEST_CMD
case "$TEST_CMD" in
    tox*|"make test")
        if command -v uv >/dev/null 2>&1; then PYTEST_CMD="uv run pytest"
        else PYTEST_CMD="python -m pytest"; fi ;;
    *) PYTEST_CMD="$TEST_CMD" ;;
esac
```

Use `$PYTEST_CMD` for single test file/node with pytest-specific flags (`--tb`, `::test_name`). Use `$TEST_CMD` for full suite.
