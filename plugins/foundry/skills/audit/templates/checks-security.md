<!-- file: checks-security.md — consumers: audit/SKILL.md Step 4 -->
<!-- Quick-reference: Check 35 ($ARGUMENTS injection), Check 36 (eval-unsafe output), Check 37 (hardcoded secrets). -->
<!-- security findings appear in a dedicated Security Findings section of the audit report, before functional findings. -->

## Check 35 — $ARGUMENTS shell injection risk security

Bash blocks in any SKILL.md that interpolate `$ARGUMENTS`, `$SCAN_ARGS`, or `$SCAN_QUERY` (or any unvalidated env var representing user-supplied input) directly into a shell string without sanitization.

**Safe patterns** (allow-list — any of these satisfies Check 35):
- `shlex.split(os.environ.get("ARGUMENTS", ""))` — Python-side splitting
- `EXEC_ARGS="${ARGUMENTS#prefix}"` then `shlex.quote $EXEC_ARGS` before interpolation
- Passing as positional arg to a Python bin/ script (`python ... "$ARGUMENTS"`) which handles shlex internally
- `[[ "$ARGUMENTS" =~ ^safe-pattern$ ]]` guard before use

**Unsafe patterns** (flag as security):
- `` eval "cmd $ARGUMENTS" `` or `` bash -c "... $ARGUMENTS ..." `` (direct shell eval)
- `python -c "... $ARGUMENTS ..."` (inline python with injected argument)
- Unquoted `$ARGUMENTS` in heredoc expansion position

Scan all `*/SKILL.md` and `*/skills/*/SKILL.md` files in scope. Flag any bash code block containing `$ARGUMENTS` (or env-var aliases like `$SCAN_ARGS`, `$SCAN_QUERY`) where none of the safe patterns above appear in the same or preceding line.

```bash
printf "=== Check 35: \$ARGUMENTS shell injection risk ===\n"
# Use Grep to find SKILL.md files containing ARGUMENTS interpolation
# then inspect each for safe-pattern presence in surrounding context
# Flag: any file where $ARGUMENTS appears unguarded in a bash block
```

**Severity**: `security` — direct shell injection vector.
Fix: route env-var user input through a bin/ script with proper shlex-safe argument parsing (see `plugins/codemap/bin/parse_scan_args.py` as reference).

## Check 36 — eval-unsafe bin/ output security

Python bin/ scripts that produce shell variable assignments intended for `eval $()` in a calling SKILL.md must quote all dynamic values with `shlex.quote`. Unquoted values allow injection via crafted env var content.

**Safe pattern (required for eval-consumed output)**:
```python
import shlex
print(f"VAR={shlex.quote(value)}")
```

**Unsafe pattern (flag)**:
```python
print(f"VAR={value}")  # unquoted — injection risk if value contains shell metacharacters
```

Scan: for each Python script in `plugins/*/bin/` that produces lines of the form `VAR=value` (detectable via `print(f"VAR=` or `print("VAR=` in source), verify `shlex.quote` wraps the value. Flag scripts with bare `print(f"... = {` patterns in assignment position without `shlex.quote`.

Exempt scripts that produce only JSON output (no shell assignment format).

```bash
printf "=== Check 36: eval-unsafe bin/ output ===\n"
grep -rn 'print(f"[A-Z_]*=' plugins/*/bin/*.py 2>/dev/null \
  | grep -v 'shlex.quote' \
  | grep -v '\.json' \
  | while IFS= read -r hit; do
      printf "R36-WARN: potential eval-unsafe output: %s\n" "$hit"
    done  # timeout: 5000
```

**Severity**: `security` — exploitable only when calling SKILL.md passes crafted env var through the eval-consumed bin/ script.
Fix: wrap dynamic values in `shlex.quote()` before printing assignment strings.

## Check 37 — Hardcoded secrets in config security

Any hardcoded API key, token, password, or bearer credential in plugin `.md` files, `settings.json`, or hook `.js` files.

```bash
printf "=== Check 37: Hardcoded secrets in config ===\n"
grep -rniE '(api[-_]?key|token|secret|password|bearer)\s*[=:]\s*["'"'"'][a-zA-Z0-9+/=_-]{16,}["'"'"']' \
    plugins/ .claude/settings.json .claude/hooks/*.js 2>/dev/null \
    | grep -v '# example\|# placeholder\|YOUR_\|<your\|XXXXXX\|example.com'  # timeout: 5000
```

Any hit that is not an example/placeholder pattern → `security` finding.

**Severity**: `security` — immediate secret rotation required.
Fix: remove secret from config; use env var reference (`$MY_API_KEY`) or system keychain; never commit secrets to plugin files.
