---
name: integration
description: "Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in."
argument-hint: "check | init [--approve]  # --approve: non-interactive; auto-applies High+Medium recs for files under $CLAUDE_PLUGIN_ROOT and installs post-commit hook"
effort: medium
when_to_use: "After first install (init) or when checking health of codemap integration across installed skills/agents."
allowed-tools: Read, Write, Edit, Bash, Glob, Skill, Agent, AskUserQuestion
model: sonnet
---

<objective>

Two modes: use `init` first-time to onboard, then `check` regularly to verify. Default (no args) → `check`.

- **`check`** — fast diagnostic: finds `scan-query`, verifies index exists and fresh, runs smoke test, audits which skill files have injection block. Prints `✓`/`✗`/`⚠` per check with one-line remediation hints. Pure bash — no model reasoning needed for happy path.
- **`init`** — interactive onboarding: builds index if missing, discovers all installed skills and agents, scores by how much codemap would help, presents recommendation table, asks which to wire in, inserts correct injection block into each selected file.

NOT for: building or rebuilding index (use `/codemap:scan-codebase`); running structural query (use `/codemap:query-code`).

Arguments: `check` (no flags) or `init [--approve]` — `--approve` auto-applies all High+Medium injection recommendations for files under `$CLAUDE_PLUGIN_ROOT`, installs the post-commit hook, and skips interactive prompts. Files from other plugins still require interactive confirmation.

</objective>

<inputs>

- **$ARGUMENTS**: optional — one of:
  - Omitted or `check` — run diagnostic; print health status for all codemap integration points
  - `init` — interactive onboarding: build index if missing, discover skills/agents, recommend injection sites, wire in selected files
  - `init --approve` — non-interactive; auto-applies all High+Medium injection recommendations for files under `$CLAUDE_PLUGIN_ROOT` and installs post-commit hook without prompting. Files from other plugins require explicit interactive confirmation even under `--approve`. **⚠ Scope warning**: injects into cache files (see I2/I5 warning) — overwritten on next plugin upgrade. Recommended: run `init` (interactive) first to review the candidate list before using `--approve` for subsequent runs.

</inputs>

<workflow>

## Mode detection

Parse `$ARGUMENTS` (case-insensitive):

- Starts with `check` or empty → run **check mode** (Steps C1–C5)
- Starts with `init` → run **init mode** (Steps I0–I6 (I5 has sub-steps I5a, I5b))
- Anything else → use `AskUserQuestion`: "Unrecognized command `$ARGUMENTS`. Which operation did you want?" Options: (a) `check` — audit integration health, (b) `init` — onboard codemap interactively, (c) `init --approve` — onboard non-interactively (auto-applies all High+Medium recommendations without prompting)

## CHECK MODE (Steps C1–C5)

### C1 — Locate scan-query

Three-tier fallback (PATH → CLAUDE_PLUGIN_ROOT → newest cache install) handled by `bin/locate_scan_query.py`.

```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || true)  # timeout: 5000
if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "✓ scan-query: %s\n" "$SQ"
    # Cross-block status persistence (fresh shell per Bash() call — vars don't survive)
    echo "ok" > "${TMPDIR:-/tmp}/codemap-c1-status"
else
    printf "✗ scan-query: not found\n"
    printf "  → Install: claude plugin install codemap@borda-ai-rig\n"
    echo "failed" > "${TMPDIR:-/tmp}/codemap-c1-status"
    exit 1
fi
```

### C2 — PROJ and index existence

```bash
# timeout: 5000
# Skip if C1 failed — fresh shell loses C1's exit status, so check sentinel file
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c1-status" 2>/dev/null || echo "ok")
if [ "$C1_STATUS" = "failed" ]; then
    echo "C1 failed — skipping this step."
    exit 0
fi
# PROJ/INDEX resolution + existence check — also used in Step I1 (init mode, without --check-exists).
# Stderr captured to tempfile so eval only sees KEY=value stdout (never mixed stderr).
# Script always emits PROJ/INDEX on stdout regardless of exit code — no second invocation needed.
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" --check-exists 2>/dev/null  # timeout: 5000
_resolve_rc=$?
PROJ=$(cat "${TMPDIR:-/tmp}/codemap-resolve-proj" 2>/dev/null || echo "")
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-resolve-index" 2>/dev/null || echo "")
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-index"
if [ "$_resolve_rc" -eq 0 ]; then
    printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
    printf "✓ index: exists\n"
else
    printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
    if [ -z "$INDEX" ] || [ ! -f "$INDEX" ]; then
        printf "✗ index: not found\n"
        printf "  → Run /codemap:scan-codebase to build the index\n"
    else
        printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"
    fi
    echo "failed" > "${TMPDIR:-/tmp}/codemap-c2-status"
    exit 1
fi
```

### C3 — Index freshness (calendar age)

```bash
# timeout: 10000
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c1-status" 2>/dev/null || echo "ok")
C2_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c2-status" 2>/dev/null || echo "ok")
if [ "$C1_STATUS" = "failed" ] || [ "$C2_STATUS" = "failed" ]; then
    echo "C1/C2 failed — skipping this step."
    exit 0
fi
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-index")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_freshness.py" "$INDEX"
```

`check_index_freshness.py` prints a human-readable age line (e.g. `  index age: 30h`) for informational context only; stale enforcement (threshold comparison + warning) is handled in C4.

### C4 — Smoke test and mtime-staleness check

`smoke_test_index.py` validates that the index file is loadable JSON and reports mtime age vs `--max-age-hours` (default 24).

```bash
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c1-status" 2>/dev/null || echo "ok")
C2_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c2-status" 2>/dev/null || echo "ok")
if [ "$C1_STATUS" = "failed" ] || [ "$C2_STATUS" = "failed" ]; then
    echo "C1/C2 failed — skipping this step."
    exit 0
fi
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-index")
SMOKE_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" --index-path "$INDEX")  # timeout: 10000
command -v jq >/dev/null 2>&1 || { printf "✗ jq not found — required for smoke test; install via brew install jq or apt-get install jq\n"; exit 1; }
_TSV=$(printf '%s' "$SMOKE_JSON" | jq -r '[.ok, .stale, .age_hours, (.error // "unknown")] | @tsv')
OK=$(echo "$_TSV" | cut -f1); STALE=$(echo "$_TSV" | cut -f2); AGE=$(echo "$_TSV" | cut -f3); ERR=$(echo "$_TSV" | cut -f4)
if [ "$OK" != "true" ]; then
    printf "✗ smoke test: %s\n  → Re-run /codemap:scan-codebase to rebuild index\n" "$ERR"
else
    printf "✓ smoke test: index valid (mtime-age=%sh)\n" "$AGE"
    [ "$STALE" = "true" ] && printf "  ⚠ Index older than freshness threshold — run /codemap:scan-codebase to update\n"
fi
```

### C5 — Skill injection audit

```bash
# timeout: 20000
command -v jq >/dev/null 2>&1 || { printf "⚠ jq not found — C5 injection audit requires jq; install via brew install jq or apt-get install jq\n"; }
# Pass installed plugin cache root (not just $CLAUDE_PLUGIN_ROOT) so check_injection.py scans all installed plugins
# including foundry:sw-engineer, foundry:qa-specialist, and other high-value targets
PLUGIN_CACHE=$(ls -td ~/.claude/plugins/cache/*/ 2>/dev/null | head -1 | xargs dirname 2>/dev/null || echo "$HOME/.claude/plugins/cache")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" "$CLAUDE_PLUGIN_ROOT" --cache-root "$PLUGIN_CACHE"
```

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

`--approve` in `$ARGUMENTS` → auto-apply all High+Medium injection recommendations for files under `$CLAUDE_PLUGIN_ROOT` without `AskUserQuestion`; files from other plugins still require interactive confirmation per I5. Print `[--approve] applying recommended options` in place of each skipped question. All subsequent `AskUserQuestion` calls for in-scope files follow this automatically.

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
# PROJ/INDEX resolution — shared with Step C2 (check mode); both call resolve_index_env.py.
# Stderr to tempfile so eval only sees KEY=value stdout.
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" 2>/dev/null  # timeout: 5000
PROJ=$(cat "${TMPDIR:-/tmp}/codemap-resolve-proj" 2>/dev/null || echo "")
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-resolve-index" 2>/dev/null || echo "")
[ -n "$PROJ" ] || { printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"; exit 1; }
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-init-index"
```

Index exists: report and proceed. Index missing:

If `--approve` active and index missing: auto-select option (a) — skip `AskUserQuestion`, proceed directly to build. Print `[--approve] building index for: $PROJ`. **Note**: auto-build runs `scan-index` from the current directory; monorepo subdirectory scans (requiring `--root`) are not supported under `--approve` — use interactive `init` to pass `--root` explicitly.

Use `AskUserQuestion`:

```text
No codemap index found for project: $PROJ

a) Build now ★ — scans all .py files via ast.parse (Python only), <60s on most projects
b) Skip — I'll run /codemap:scan-codebase later (recommendations will be generic, no module-count weighting)
```

If **a** (or auto-approved): verify binary exists first, then run scanner:

```text
# Delegate to codemap:scan-codebase skill — runs scan-index with correct timeout handling,
# binary validation, --root/--incremental handling, and stats reporting. Reimplementing
# the invocation here drifts from scan-codebase's contract; call the skill instead.
Skill(skill="codemap:scan-codebase")
```

Report result (module count, degraded count). If **b**: note "Proceeding without index — recommendations based on skill purpose only, not module count."

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` (Claude Code internal plugin registry — format may change across versions; fallback: glob `~/.claude/plugins/cache/*/*/` if file absent or unreadable). For each plugin entry, check `installPath` key present before accessing; if absent, log `installPath field missing — plugin manifest format may have changed` and fall back gracefully to cache-glob discovery for that entry. For each plugin's `installPath`, glob:

> **⚠ Cache-mutation warning**: files discovered via `installPath` are in the plugin cache (`~/.claude/plugins/cache/`). Edits made by I5 to these files are overwritten on the next `claude plugin install` or upgrade for that plugin. For durable injection that survives upgrades, create a project-local override in `.claude/agents/` or `.claude/skills/` first, then inject into the override copy.

- `skills/*/SKILL.md` — skill files
- `agents/*.md` — agent files

Per file: extract from frontmatter: `name`, `description`, `allowed-tools` (skills) or `description` body (agents). Extract first sentence of `<objective>` section.

For each plugin discovered, set `CACHE` to its resolved `installPath` value. Flag files with injection block:

```bash
# timeout: 10000
# $CACHE = installPath value resolved per plugin in discovery loop above
find "$CACHE" -name "SKILL.md" -exec grep -l "command -v scan-query" {} \; 2>/dev/null
```

Build two lists: `ALREADY_INJECTED` and `CANDIDATES`.

### I3 — Score and rank candidates

Classify each candidate by value tier. For skill files: use `<objective>` text and `allowed-tools`. For agent files: use `<role>` text and `tools` frontmatter field (agents use `<role>`, not `<objective>`).

| Tier | Signal | Recommendation |
| --- | --- | --- |
| **High** | `allowed-tools` includes `Edit` or `Write`; `<objective>` mentions spawning `foundry:sw-engineer` (requires `foundry` plugin) or `foundry:qa-specialist` (requires `foundry` plugin); performs code changes | "Strongly recommend — agent starts with blast-radius context" |
| **Medium** | analysis or planning skills; spawns read-only agents; multi-file review without edits | "Moderate value — centrality context speeds structural decisions" |
| **Low** | documentation, release, communication; no code traversal | "Low value — structural context unlikely to help" |
| **Check/Warn** | release-orchestration skills (e.g. `oss:release`) — canonical injection sites per `check_injection.py`; surface as CHECK not SKIP | "Check — injection expected per check_injection.py rubric" |
| **Skip** | config-only, single-file, non-Python purpose (e.g. shell, YAML, JS) | "Skip — not applicable for Python import graphs" |

If index built and `total_modules < 20`: downgrade all tiers one level (small project = less value).

### I4 — Present recommendations and ask user

Print candidate table:

```text
Codemap injection candidates for: $PROJ

  Status  Skill/Agent          Tier    Notes
  ──────────────────────────────────────────────────────────────────
  a)      develop:refactor     MEDIUM  restructures code; reads module deps for target
  b)      oss:cicd-steward     MEDIUM  diagnoses failures; reads code structure for context
  —       foundry:doc-scribe   LOW     writes docstrings; skip
  ⚠check  oss:release          CHECK   expected injection site per check_injection.py — check manually
```

CHECK-tier items shown with `⚠check` prefix are informational only — not selectable via letter; verify injection status manually using `/codemap:integration check`.

Call `AskUserQuestion` tool with:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

<!-- branch outcomes: letters/all → proceed to I5 with selected file list; none → skip I5, proceed directly to I5a -->

### I5 — Wire in the injection block

**⚠ --approve scope guard**: when running in `--approve` mode, restrict auto-injection to files under `$CLAUDE_PLUGIN_ROOT` only — skip files from other plugins in `~/.claude/plugins/cache/` that appear in the candidate list. Files from other plugins require explicit interactive confirmation; `--approve` is scoped to the current project's plugin only. In interactive mode, present all candidates but highlight cache-path files with ⚠ to remind user they affect all projects.

**Write-permission probe + rollback log** — before any mutation under `~/.claude/plugins/cache/` (or any `INSTALL_PATH` discovered via I2):

```bash
# Probe write permission before mutating cache files
# INSTALL_PATH must be set from I2 installPath discovery — do NOT fall back to broad $HOME/.claude/plugins/cache
# If INSTALL_PATH empty (I2 discovery failed), abort rather than granting broad write permission
[ -n "$INSTALL_PATH" ] || { echo "Error: INSTALL_PATH not set — I2 discovery may have failed; re-run init"; exit 1; }
[ -w "$INSTALL_PATH" ] || { echo "Error: no write permission to $INSTALL_PATH"; exit 1; }
# Rollback log — record every file edited for this run
ROLLBACK_LOG="$(mktemp "${TMPDIR:-/tmp}/codemap-init-rollback-XXXXXX.log")"
echo "[codemap init] rollback log: $ROLLBACK_LOG"
# Append one entry per edit: "<timestamp>\t<file>\t<original-sha>"
```

For each file edited, append `printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$FILE" >> "$ROLLBACK_LOG"` before writing the edit.

**On failure**: previous state is preserved; no partial write leaves cache in inconsistent state. Each edit is atomic (single `Edit` tool call); rollback log identifies every touched file. **Limitation**: `~/.claude/plugins/cache/` is not a git repo — `git checkout` cannot restore individual files. Rollback options: (1) re-run `claude plugin install codemap@borda-ai-rig` to restore the plugin from registry; (2) manually re-edit files listed in `$ROLLBACK_LOG` to remove the injection block. The rollback log records file paths only (no original content) — this is informational, not a full snapshot restore.

Per selected file, determine insertion point and content:

**For SKILL.md files** — find the first step that spawns an agent (first `Agent(` call or first `spawn` instruction in the workflow). If multiple agent spawn steps exist, inject before the **first** one only. Insert hardened soft-check block immediately before that step, blank line before and after.

> **No Agent() spawn step in target SKILL.md?** Inject the block as a **pre-step before the first tool call** in the workflow (typically at the top of `<workflow>` or right after Project Detection / Flag parsing). Structural context still informs subsequent reasoning even when no agent is spawned.

```bash
# Structural context (codemap — Python projects only, silent skip if absent)
# TARGET_MODULE — derive from $ARGUMENTS (e.g. strip leading ./ and .py suffix from file path argument)
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    scan-query --timeout 5 central --top 3
fi
# If results returned: prepend a ## Structural Context (codemap) block to the agent spawn prompt.
# Also add: "For targeted analysis run: scan-query rdeps <module> or scan-query fn-blast module::function"
```

For skills where target module derives from `$ARGUMENTS` (refactor, fix with module path, review), also add after `central` — **derive `TARGET_MODULE` first**; without it calls run as `scan-query rdeps ""` and return nothing:

Derive `TARGET_MODULE` from `$ARGUMENTS`: strip leading `./`; strip leading `src/`; strip trailing `.py`; replace `/` → `.`. If result empty, use `Path($ARGUMENTS).stem`. Example: `src/foo/bar.py` → `foo.bar`.

If `TARGET_MODULE` non-empty, substitute derived value and run:

```bash
scan-query --timeout 5 rdeps "<TARGET_MODULE>" 2>/dev/null
scan-query --timeout 5 deps  "<TARGET_MODULE>" 2>/dev/null
```

**For agent `.md` files** — append to last workflow instruction paragraph, before closing section or final notes. Agents have no `$ARGUMENTS` — derive `TARGET_MODULE` from user's input prompt:

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/codemap/<project>.json` exists (or `$CODEMAP_INDEX_DIR/<project>.json` when set), run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known — derive target from user's task description, not `$ARGUMENTS`) **before** any Glob/Grep exploration for structural information. Skip silently if the index is absent.
```

Report each edit: `✓ injected: <plugin>/<skill-or-agent> at line N`

### I5a — Offer git post-commit hook

If `--approve` active: auto-select (a) Install, skip `AskUserQuestion`, proceed directly to I5b.

Otherwise use `AskUserQuestion`:

```text
Install post-commit git hook for automatic incremental rebuild?

a) Install ★ — runs scan-index --incremental in background after every commit; index stays current with zero developer action
b) Skip — I'll run /codemap:scan-codebase or /codemap:scan-codebase --incremental manually
```

<!-- branch outcomes: a → proceed to I5b (write hook file); b → skip I5b, proceed to I6 (summary) -->

### I5b — Write hook file

If arriving from I5a with user's **a** selection (or auto-approved via `--approve` at I5a): skip further confirmation — I5a answer is sufficient. Proceed directly to hook write. On **b** (Skip): report `✓ post-commit hook skipped` and proceed to I6.

Then write `.git/hooks/post-commit`. Idempotent — check for `# codemap: incremental` marker before writing.

> **Path-baking note**: the hook bakes `CLAUDE_PLUGIN_ROOT` at install time. After a codemap version upgrade (`claude plugin install codemap@borda-ai-rig`), the baked path becomes stale — the hook falls back to `command -v scan-index` in that case. Re-run `/codemap:integration init` after upgrading codemap to refresh the hook path.

```bash
# timeout: 5000
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/install_post_commit_hook.py" --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

Report: `✓ post-commit hook installed: <path>` or `✓ already installed` if marker present. Hook logs to `${TMPDIR:-/tmp}/codemap-hook.log` — failures and version-upgrade full scans visible there.

### I6 — Summary report

Print:

```text
--- init complete ---

Injected codemap into N skill(s)/agent(s):
  ✓ develop:refactor → <path>   (requires develop plugin)
  ✓ ...

Already integrated (no change):
  • develop:fix, develop:feature, ...

Skipped:
  • foundry:doc-scribe — LOW value
  • oss:release — CHECK (canonical injection site per check_injection.py)

Post-commit hook: installed / skipped

Note: N injected file(s) are in plugin cache (~/.claude/plugins/cache/) and will be
overwritten on the next `claude plugin install` or plugin upgrade. For durable injection,
create project-local overrides in .claude/agents/ or .claude/skills/ and re-run init.

Next: run /codemap:integration check to verify all injection blocks are wired correctly.
```

</workflow>
