# Install Checks — I1, I2, I3

Checks validate post-install state in `~/.claude/`. Operate on home dir, not project `.claude/`. Run via `/foundry:audit setup` (or `/audit setup` after `foundry:setup link`).

## Check I1 — Plugin cache intact

Verify foundry plugin installed and cache dir accessible.

```bash
printf "=== Check I1: foundry plugin cache ===\n"

REGISTRY="$HOME/.claude/plugins/installed_plugins.json"
if [ ! -f "$REGISTRY" ]; then
    printf "! HIGH: Check I1 — installed_plugins.json not found; plugin may not be installed\n"
else
    INSTALL_PATH=$(jq -r 'to_entries[] | select(.key | ascii_downcase | contains("foundry")) | .value.installPath // empty' \
        "$REGISTRY" 2>/dev/null | head -1)  # timeout: 5000
    if [ -z "$INSTALL_PATH" ]; then
        printf "! HIGH: Check I1 — foundry not found in installed_plugins.json\n"
        printf "  Fix: claude plugin marketplace add Borda/AI-Rig && claude plugin install foundry@borda-ai-rig\n"
    elif [ ! -d "$INSTALL_PATH" ]; then
        printf "! HIGH: Check I1 — install cache missing: %s\n" "$INSTALL_PATH"
        printf "  Fix: claude plugin install foundry@borda-ai-rig  (reinstall to rebuild cache)\n"
    else
        VERSION=$(jq -r 'to_entries[] | select(.key | ascii_downcase | contains("foundry")) | .value.version // "unknown"' \
            "$REGISTRY" 2>/dev/null | head -1)  # timeout: 5000
        printf "✓: Check I1 — foundry cache intact at %s (version: %s)\n" "$INSTALL_PATH" "$VERSION"
        echo "$INSTALL_PATH" >/tmp/audit_install_plugin_root  # pass to I2/I3
    fi
fi
```

**Severity**: missing/broken cache → **high** (plugin non-functional).

## Check I2 — Settings merge complete

Verify `foundry:setup` ran: `~/.claude/settings.json` has required entries, no stale hooks block.

```bash
printf "=== Check I2: ~/.claude/settings.json merge ===\n"

SETTINGS="$HOME/.claude/settings.json"

if [ ! -f "$SETTINGS" ]; then
    printf "! HIGH: Check I2 — ~/.claude/settings.json not found\n"
else
    FAIL=0

    # I2a — statusLine: must reference statusline.js (any path)
    if ! jq -e '(.statusLine.command // "") | contains("statusline.js")' "$SETTINGS" >/dev/null 2>&1; then  # timeout: 5000
        printf "⚠ MEDIUM: Check I2a — statusLine not set to statusline.js\n"
        printf "  Fix: run /foundry:setup\n"
        FAIL=$((FAIL + 1))
    else
        printf "✓: Check I2a — statusLine set\n"
    fi

    # I2b — permissions.allow: foundry entries merged? (>10 expected)
    if ! jq -e '(.permissions.allow // []) | length > 10' "$SETTINGS" >/dev/null 2>&1; then  # timeout: 5000
        printf "⚠ MEDIUM: Check I2b — permissions.allow appears empty or very short; foundry entries may not have been merged\n"
        printf "  Fix: run /foundry:setup\n"
        FAIL=$((FAIL + 1))
    else
        printf "✓: Check I2b — permissions.allow populated\n"
    fi

    # I2c — enabledPlugins: codex@openai-codex must be true
    if ! jq -e '.enabledPlugins["codex@openai-codex"] == true' "$SETTINGS" >/dev/null 2>&1; then  # timeout: 5000
        printf "⚠ MEDIUM: Check I2c — enabledPlugins.codex@openai-codex not set to true\n"
        printf "  Fix: run /foundry:setup\n"
        FAIL=$((FAIL + 1))
    else
        printf "✓: Check I2c — enabledPlugins.codex@openai-codex enabled\n"
    fi

    # I2d — stale hooks block (double-fires with plugin hooks.json)
    if jq -e 'has("hooks")' "$SETTINGS" >/dev/null 2>&1; then  # timeout: 5000
        printf "⚠ MEDIUM: Check I2d — 'hooks' key present in ~/.claude/settings.json; stale block from before plugin migration will cause double-firing\n"
        printf "  Fix: run /foundry:setup — it will offer to remove the stale hooks block\n"
        FAIL=$((FAIL + 1))
    else
        printf "✓: Check I2d — no stale hooks block\n"
    fi

    [ "$FAIL" -eq 0 ] && printf "✓: Check I2 — settings merge complete\n"
fi
```

**Severity**: missing entry or stale hooks block → **medium** per sub-check (non-blocking, degrades functionality). Fix: re-run `/foundry:setup` — idempotent.

## Check I3 — Link health (conditional)

Runs only if `~/.claude/agents/` or `~/.claude/skills/` contain symlinks pointing to plugin cache path. Checks staleness — symlinks break silently after plugin version upgrade changes cache path.

```bash
printf "=== Check I3: ~/.claude/ link health ===\n"

INSTALL_PATH=$(cat /tmp/audit_install_plugin_root 2>/dev/null)
LINKED=0
STALE=0

for f in "$HOME/.claude/agents/"*.md; do
    [ -e "$f" ] || continue
    if [ -L "$f" ]; then
        LINKED=$((LINKED + 1))
        [ ! -f "$f" ] && STALE=$((STALE + 1)) && \
            printf "! HIGH: Check I3 — broken symlink: %s -> %s\n" "$f" "$(readlink "$f" 2>/dev/null)"
    fi
done

for d in "$HOME/.claude/skills/"/*/; do
    [ -e "$d" ] || continue
    d="${d%/}"
    if [ -L "$d" ]; then
        LINKED=$((LINKED + 1))
        [ ! -d "$d" ] && STALE=$((STALE + 1)) && \
            printf "! HIGH: Check I3 — broken symlink: %s -> %s\n" "$d" "$(readlink "$d" 2>/dev/null)"
    fi
done

if [ "$LINKED" -eq 0 ]; then
    printf "✓: Check I3 — no foundry symlinks in ~/.claude/ (foundry:setup link not run; skipping)\n"
elif [ "$STALE" -eq 0 ]; then
    printf "✓: Check I3 — %d symlink(s) all resolve correctly\n" "$LINKED"
else
    printf "! HIGH: Check I3 — %d of %d symlink(s) broken (likely stale after plugin version upgrade)\n" "$STALE" "$LINKED"
    printf "  Fix: re-run /foundry:setup link — it will replace stale symlinks with the current cache path\n"
fi
```

**Severity**: broken symlinks → **high** (agents/skills silently unavailable at root namespace). Fix: re-run `/foundry:setup link` — detects and replaces stale symlinks.

## Check R1 — Computed path resolution (local + installed duality)

Root cause guard for the `adversarial.md` / `upgrade.md` silent-deletion class of bugs. Skill `.md` files construct file paths via variable substitution (`$AUDIT_TPL/../modes/upgrade.md`, `$_FS/task-hygiene.md`, `${CLAUDE_PLUGIN_ROOT:-plugins/<x>}/bin/<script>`). Those paths only exist as literal strings if the target filename appears somewhere visible to grep. A file that exists locally but was never copied to the installed plugin cache will silently fail for users who install the plugin.

**What it checks**: for every computed-path reference in `plugins/*/skills/*/SKILL.md`, `plugins/*/skills/*/modes/*.md`, and `plugins/*/agents/*.md` — verify the resolved target exists both locally (`plugins/<plugin>/...`) and in the installed cache (`~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/<path>`).

Skip if `LOCAL_MODE != true` (no plugin source tree to scan).

```bash
printf "=== Check R1: Computed path resolution (local + installed duality) ===\n"
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓: Check R1 skipped in non-local mode (no plugin source tree)\n"
else
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_routing_links.py" \
        --plugins-dir plugins \
        --installed-plugins-json ~/.claude/plugins/installed_plugins.json \
        --check R1  # timeout: 15000
fi
```

**Severity**:
- `R1-FAIL` (file exists locally but absent from installed cache) → **high** — users who install the plugin get broken dispatch at runtime; likely means file was added locally but plugin was not re-installed
- `R1-WARN` (file exists in installed cache but absent locally) → **medium** — stale installed copy; will break after plugin update
- `R1-INFO` (plugin not installed) → **low/info** — cannot verify installed state; note in report only

Fix: re-install plugin with `claude plugin install <plugin>@borda-ai-rig` to sync installed state with local source tree. For WARN: restore missing local file or remove reference.

## Check R2 — Grep-visible referencing (orphan-risk detection)

Structural guard: for every `.md` file in `plugins/*/skills/*/modes/`, `plugins/*/skills/*/templates/`, and `plugins/*/skills/_shared/` — verify its **basename** appears as a literal string in at least one consumer `.md` file in the same plugin.

**Scope**: `modes/`, `templates/`, `_shared/` only. SKILL.md and agent `.md` files themselves are covered by Check 32a (checks-skills.md); R2 is complementary — it covers subdirectories that 32a does not walk.

**Why**: grep-based dead-file checks (Check 32a, 32b) and agent zero-hit analysis work by searching for the filename. A file loaded exclusively via computed path (e.g. `$AUDIT_TPL/../modes/adversarial.md`) has zero literal-basename hits → grep tools conclude it is unreferenced → deletion risk.

Skip if `LOCAL_MODE != true`.

```bash
printf "=== Check R2: Grep-visible referencing (orphan-risk detection) ===\n"
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓: Check R2 skipped in non-local mode (no plugin source tree)\n"
else
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_routing_links.py" \
        --plugins-dir plugins \
        --check R2  # timeout: 15000
fi
```

**Severity**: `R2-ORPHAN-RISK` → **medium** — file is grep-invisible; any automated or agent-assisted dead-file sweep will incorrectly flag it as unreferenced and may delete it.

Fix: add a comment in the consumer `SKILL.md` that makes the basename a literal string, e.g.:
```
# loads: adversarial.md  (via $AUDIT_TPL/../modes/adversarial.md)
```
This single-line comment costs ~5 tokens and permanently protects the file from grep-based false-positive orphan detection.

## Check R3 — bin/ script reference integrity (reverse of Check 32d)

Check 32d walks `bin/` scripts and flags those unreferenced by any `.md` file (orphaned scripts). R3 is the reverse: for every `${CLAUDE_PLUGIN_ROOT:-plugins/<x>}/bin/<script>` reference in any plugin `.md` file, verify the script actually exists locally — catches typos, deleted scripts, and refactor leftovers that leave dangling references.

Skip if `LOCAL_MODE != true`.

```bash
printf "=== Check R3: bin/ script existence (local + installed) ===\n"
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓: Check R3 skipped in non-local mode (no plugin source tree)\n"
else
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_routing_links.py" \
        --plugins-dir plugins \
        --installed-plugins-json ~/.claude/plugins/installed_plugins.json \
        --check R3  # timeout: 15000
fi
```

**Severity**:
- `R3-FAIL` (script referenced but missing locally) → **high** — skill dispatch will fail immediately at the `python ...` call site
- `R3-WARN` (script exists locally but absent from installed cache) → **high** — same as R1-FAIL but for bin/ scripts; users get broken skill at runtime after install

Fix: create the missing script locally (FAIL) or re-install plugin to sync (WARN).

> **Convenience shortcut**: run all three checks together:
> ```bash
> python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_routing_links.py" \
>     --plugins-dir plugins \
>     --installed-plugins-json ~/.claude/plugins/installed_plugins.json  # timeout: 20000
> ```
> Omitting `--check` runs R1, R2, R3 in one pass.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| R1-FAIL — local-only file | resolved file exists locally but absent from installed cache | high | no — re-install plugin |
| R1-WARN — installed-only file | file exists in cache but missing locally | medium | no — restore local file or remove ref |
| R1-INFO — plugin not installed | cannot verify installed state | info | n/a |
| R2-ORPHAN-RISK — grep-invisible | basename not literal in any consumer .md file | medium | no — add `# loads: <basename>` comment |
| R3-FAIL — bin/ script missing locally | script referenced but local file absent | high | no — create script |
| R3-WARN — bin/ script missing from cache | script local but absent from installed cache | high | no — re-install plugin |

## Check R4 — bin/ Python test coverage

For every `plugins/<plugin>/bin/<script>.py`, verify a corresponding `plugins/<plugin>/tests/test_<script>.py` exists and is non-empty. Skip if `LOCAL_MODE != true`.

**Implementation note**: `check_orphaned_bin.py` does not yet have `--check-tests`; until that flag is added, run the check inline:

```bash
printf "=== Check R4: bin/ Python test coverage ===\n"
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓: Check R4 skipped in non-local mode\n"
else
    _FAIL=0
    while IFS= read -r script; do
        plugin_dir=$(dirname "$(dirname "$script")")
        base=$(basename "$script" .py)
        test_file="$plugin_dir/tests/test_${base}.py"
        if [ ! -f "$test_file" ]; then
            printf "R4-FAIL (no test file): %s → expected %s\n" "$script" "$test_file"
            _FAIL=1
        elif [ ! -s "$test_file" ]; then
            printf "R4-FAIL (empty test file): %s\n" "$test_file"
            _FAIL=1
        else
            # R4-THIN: non-empty file with zero def test_ functions
            test_fn_count=$(grep -c "^def test_" "$test_file" 2>/dev/null || echo 0)
            if [ "$test_fn_count" -eq 0 ]; then
                printf "R4-FAIL (no test functions): %s — has no def test_ functions\n" "$test_file"
                _FAIL=1
            else
                # R4-STUB: every test function body is only pass or ...
                non_stub=$(python -c "
import ast, sys
try:
    tree = ast.parse(open('$test_file').read())
except Exception:
    sys.exit(0)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
        stmts = node.body
        for s in stmts:
            if isinstance(s, ast.Pass):
                continue
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is ...:
                continue
            print('non-stub')
            sys.exit(0)
" 2>/dev/null)
                if [ -z "$non_stub" ] && [ "$test_fn_count" -gt 0 ]; then
                    printf "R4-FAIL (stub tests only): %s — all %s test function(s) are pass/... stubs\n" "$test_file" "$test_fn_count"
                    _FAIL=1
                fi
            fi
        fi
    done < <(find plugins -path "*/bin/*.py" -not -name "_*.py" 2>/dev/null | sort)  # timeout: 5000
    [ "$_FAIL" -eq 0 ] && printf "✓: all bin/ Python scripts have non-empty test files with real assertions\n"
fi
```

**Severity**:
- `R4-FAIL` (any sub-check) → **medium** — plugin policy violation; new bin/ scripts must ship with tests containing real assertions

Fix: create `tests/test_<basename>.py` with at minimum one test class covering the public API of the script.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| R4-FAIL — missing test file | `bin/*.py` with no matching `tests/test_*.py` | medium | no — write tests |
| R4-FAIL — empty test file | `tests/test_*.py` exists but has zero size | medium | no — populate test file |
| R4-FAIL — no test functions | test file non-empty but has zero `def test_` functions | medium | no — write tests |
| R4-FAIL — stub tests only | all `def test_` functions body is only `pass` or `...` | medium | no — implement assertions |

Note: the `_*.py` exclusion (e.g., `_schema.py`) is intentional only for files that are pure type-definition modules with no runnable logic. Files with `__name__ == "__main__"` guards must have tests regardless of leading underscore. Auditor should verify exclusion is appropriate per file when `_FAIL` reports are absent.

## Check R5 — Consumer→template orphan (reverse of R2)

Check R2 verifies every template file has its basename visible in a consumer `.md` file. R5 is the reverse: for every `<!-- loads: X -->` or `# loads: X` comment in any `.md` file, verify that `X` actually exists as a file on disk (locally or in the installed cache).

This catches deleted or renamed templates where the consumer `<!-- loads: -->` comment was not updated — silent runtime failure when audit tries to `Read $AUDIT_TPL/X`.

Skip if `LOCAL_MODE != true`.

```bash
printf "=== Check R5: Consumer→template orphan ===\n"
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓: Check R5 skipped in non-local mode\n"
else
    grep -rn "loads:\s\+\([a-zA-Z0-9_-]\+\.md\)" plugins/ \
        --include="*.md" -o 2>/dev/null \
    | sed 's/.*loads:[[:space:]]*//' \
    | sort -u \
    | while IFS= read -r target; do
        found=$(find plugins -name "$target" 2>/dev/null | head -1)
        if [ -z "$found" ]; then
            printf "R5-FAIL: loads: %s — file not found in plugins/ tree\n" "$target"
        fi
    done  # timeout: 10000
fi
```

**Severity**: medium — audit itself may crash at runtime trying to read missing template; silent breakage for users.
Fix: either restore the missing template file or remove/update the stale `<!-- loads: -->` comment in the consumer.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| R5-FAIL — missing template | `loads: X` comment but `X` not found on disk | medium | no — restore file or remove dead comment |
