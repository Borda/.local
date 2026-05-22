# plugins/ — Plugin Authoring & Behavior Reference

Authoritative reference for critical behaviors, permission model, known limitations, and user expectations across all 5 plugins. Read before editing plugin files or diagnosing unexpected behavior.

> Plugin inventory, install instructions, versioning policy, and cross-plugin dependency rules: see root `README.md` and `plugins/CLAUDE.md`. This file covers trust model, bin/ execution, and operational guarantees only.

______________________________________________________________________

## Permission Model

### Trust boundary is at install time, not invocation time

Installing a plugin = consenting to trust its bin/ scripts. Claude Code's allow list enforces this: once a plugin is installed, its bin/ executables run without per-invocation approval prompts.

### Scope of trust

`Bash(python:*)` matches any `python ...` invocation — not only `${CLAUDE_PLUGIN_ROOT}/bin/*.py`. This is by design: the same entry also covers `python -m pytest`, `python -m cProfile`, etc. The allow list is not path-restricted.

Additional trust boundaries to be aware of:

- **Integrity at install time only**: `claude plugin install` fetches code from the marketplace. Nothing verifies marketplace authenticity or pins a hash. If the marketplace is compromised at install time, the installed bin/ scripts run without prompts. For a personal dev tool this is the accepted threat model; it is not appropriate for multi-tenant environments.
- **Updates inherit prior consent**: if a plugin update ships new bin/\*.py code, it runs without re-consent. `/foundry:init` is re-run to sync settings, not to re-authorize.
- **No auto-revocation on uninstall**: `/foundry:init` merge is additive — it adds entries to `~/.claude/settings.json` but never removes them. Uninstalling a plugin does not remove its allow entries. Manual cleanup required.

### What is pre-approved (in `~/.claude/settings.json`)

All entries are merged from `plugins/foundry/.claude-plugin/permissions-allow.json` by `/foundry:init`. Key entries relevant to plugin execution:

| Entry                     | What it covers                                                   | Why                                                                                     |
| ------------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `Bash(python:*)`          | Plugin bin/ Python scripts (`bin/*.py`) and `python -m *` tools  | Install = consent; per-invocation prompts are security theater for trusted plugin infra |
| `Bash(eval:*)`            | `eval "$(python ...)"` patterns (arg parsing, health monitoring) | Required for shell variable injection from bin/ Python scripts                          |
| `Bash(find:*)`            | Path resolution, run-dir discovery                               | Core skill infrastructure                                                               |
| `Bash(node:*)`            | Hook files (`hooks/*.js`)                                        | All hooks are Node.js                                                                   |
| `Bash(git *:*)` (various) | Read-only git operations                                         | Standard dev workflow                                                                   |
| `Bash(gh *:*)` (various)  | GitHub CLI read operations                                       | OSS plugin workflows                                                                    |

### What deliberately prompts

| Entry                                       | Reason                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -c "..."` inline code               | `python -c` does not match `Bash(python:*)` — Claude Code's matcher tokenizes the full prefix; a separate `Bash(python -c:*)` entry would be required (intentionally absent). Check 23e is the policy enforcement; the prompt is a side-effect of matcher tokenization, not a designed security feature. |
| `Bash(python3:*)`                           | Standardized to `python`; `python3` invocations signal unconverted code                                                                                                                                                                                                                                  |
| `git push`                                  | Push requires explicit user confirmation per session — intentional friction                                                                                                                                                                                                                              |
| Any `python*` wildcard beyond bare `python` | Only bare `python:*` was added; `python3.11`, `python3.x` etc. still prompt                                                                                                                                                                                                                              |

### Check 23e — inline Python detector

`/audit` Check 23e scans all SKILL.md files for `python -c` and `python <<` patterns and flags them HIGH. The `Bash(python:*)` allow entry does **not** exempt inline code from this check — the matcher requires `Bash(python -c:*)` for that. If you see a Check 23e finding, fix it by extracting the logic to a `bin/*.py` script.

______________________________________________________________________

## bin/ Script Architecture

### `${CLAUDE_PLUGIN_ROOT}` and the fallback pattern

Every bin/ call uses `${CLAUDE_PLUGIN_ROOT:-plugins/<plugin>}`:

- **Installed** (normal use): `CLAUDE_PLUGIN_ROOT` set by Claude Code to the plugin's cache path (`~/.claude/plugins/cache/borda-ai-rig/<plugin>/<version>/`).
- **Dev/testing** (local tree, `CLAUDE_PLUGIN_ROOT` unset): falls back to `plugins/<plugin>` — the source tree location.

The fallback exists so skills work from both installed cache and local dev tree without configuration. Never use bare `plugins/<name>/` as the primary path — Check C32 flags it as a violation.

### Two call patterns

**Pattern A — Python scripts (`.py`) via subshell variable assignment:**

```bash
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null)  # timeout: 5000
RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/make_run_dir.py" "skill" ".reports" 2>/dev/null)         # timeout: 5000
```

The `VAR=$(...)` form is a shell variable assignment — Claude Code's permission matcher treats it as a shell builtin construct. The inner script is not separately matched against the allow list. **Note**: this is observed behavior, not a documented guarantee; a Claude Code update could change it. ~48 call sites across all plugin SKILL.md files depend on this behavior (see Known Limitations).

**Pattern B — Python scripts (`.py`) via direct call or subshell:**

```bash
# Side-effect call (writes a file, prints findings) — direct invocation
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_tag_symmetry.py" .claude/agents/*.md  # timeout: 10000

# Value-producing call — subshell
MEMORY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_memory_dir.py" 2>/dev/null)  # timeout: 5000
```

`Bash(python:*)` is in the allow list — both forms run without prompts.

### What NOT to do

```bash
# ✗ python3 — not standardized, triggers prompt
python3 "${CLAUDE_PLUGIN_ROOT}/bin/script.py" ...

# ✗ timeout S wrapper — redundant with # timeout: N annotation, adds subprocess fork
_FS=$(timeout 5 python "${CLAUDE_PLUGIN_ROOT}/bin/resolve_shared_path.py" foundry skills/_shared ...)  # timeout: 5000

# ✗ inline python — Check 23e HIGH violation, triggers prompt
RESULT=$(python -c "import json; ...")
```

### Timeout mechanism

Use Claude Code's `# timeout: N` annotation (N in milliseconds) on the Bash block line. This is the correct mechanism — it tells the Bash tool to hard-kill after N ms. The `timeout S cmd` shell wrapper is NOT needed in SKILL.md context (it's only valid for scripts invoked outside Claude Code, e.g. CI or standalone shell).

```bash
# ✓ correct
RESULT=$("${CLAUDE_PLUGIN_ROOT}/bin/script.sh" args 2>/dev/null || echo "fallback")  # timeout: 5000
python "${CLAUDE_PLUGIN_ROOT}/bin/script.py" args                                     # timeout: 10000
```

______________________________________________________________________

## Test Coverage & CI

Every `bin/` Python script ships with a `pytest` test suite in the plugin's `tests/` directory. Tests run on every PR and push to `main` via GitHub Actions (`ci-tests.yml`), across 6 matrix combinations (Ubuntu, macOS, Windows × Python 3.10, 3.12).

| Plugin    | Test files | Tests   |
| --------- | ---------- | ------- |
| foundry   | 12         | 250     |
| codemap   | 7          | 121     |
| oss       | 5          | 60      |
| develop   | 1          | 22      |
| research  | 1          | 13      |
| **Total** | **26**     | **466** |

Counts from `pytest --collect-only -q` run in `plugins/`; regenerate after test additions.

`/audit` Check 23e and Check C32 continuously verify that SKILL.md files don't introduce inline Python or bare `plugins/` path references — structural violations are caught before they reach users.

The CI matrix ensures bin/ scripts run correctly on the platforms users install plugins on. A green CI badge = all executables behave identically on Linux, macOS, and Windows with both Python 3.10 and 3.12.

______________________________________________________________________

## Known Limitations

### Pattern A passthrough is observed behavior, not a contract

Shell script calls inside `VAR=$(script.sh ...)` work without explicit allow entries. This is inferred from production behavior — Claude Code's permission matcher appears to treat the variable assignment as a shell builtin and not descend into `$(...)`. If Claude Code's matcher ever changes, ~48 `.sh` bin/ call sites across all plugins would require restructuring. Adding explicit allow entries is not a clean mitigation (paths are install-path-dependent). No test harness verifies this behavior.

______________________________________________________________________

## Settings Sync

`plugins/foundry/.claude-plugin/permissions-allow.json` is the canonical allow list for all entries that foundry needs. `/foundry:init` merges this into `~/.claude/settings.json` on install. The merge is **additive** — entries are never removed automatically. If you remove an entry from `permissions-allow.json`, manually remove it from `~/.claude/settings.json` as well.

If you add a new allow entry:

1. Edit `plugins/foundry/.claude-plugin/permissions-allow.json`
2. Run `/foundry:manage add perm "Bash(X:*)" "description" "use case"` OR manually update `~/.claude/settings.json` + `~/.claude/permissions-guide.md`
3. Re-run `/foundry:init` to sync symlinks and verify
