---
name: integration
description: "Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in."
argument-hint: "check | init [--approve]  # --approve: non-interactive, auto-applies all High+Medium injection recommendations and installs post-commit hook"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
model: sonnet
---

<objective>

Two modes: use `init` first-time to onboard, then `check` regularly to verify. Default (no args) → `check`.

- **`check`** — fast diagnostic: finds `scan-query`, verifies index exists and fresh, runs smoke test, audits which skill files have injection block. Prints `✓`/`✗`/`⚠` per check with one-line remediation hints. Pure bash — no model reasoning needed for happy path.
- **`init`** — interactive onboarding: builds index if missing, discovers all installed skills and agents, scores by how much codemap would help, presents recommendation table, asks which to wire in, inserts correct injection block into each selected file.

NOT for: building or rebuilding index (use `/codemap:scan`); running structural query (use `/codemap:query`).

Arguments: `check` (no args) or `init [--approve]` — `--approve` auto-applies all ★ recommendations non-interactively.

</objective>

<inputs>

- **$ARGUMENTS**: optional — one of:
  - Omitted or `check` — run diagnostic; print health status for all codemap integration points
  - `init` — interactive onboarding: build index if missing, discover skills/agents, recommend injection sites, wire in selected files
  - `init --approve` — non-interactive; auto-applies all High+Medium injection recommendations and installs post-commit hook without prompting. **⚠ Scope warning**: injects into ALL High+Medium-scored files across all installed plugins (cache files — see I2/I5 warning). Recommended: run `init` (interactive) first to review the candidate list before using `--approve` for subsequent runs.

</inputs>

<workflow>

## Mode detection

Parse `$ARGUMENTS` (case-insensitive):

- Starts with `check` or empty → run **check mode** (Steps C1–C5)
- Starts with `init` → run **init mode** (Steps I0–I6 (I5 has sub-steps I5a, I5b))
- Anything else → use `AskUserQuestion`: "Unrecognized command `$ARGUMENTS`. Which operation did you want?" Options: (a) `check` — audit integration health, (b) `init` — onboard codemap interactively (add `--approve` to auto-apply all recommendations without prompting)

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
# PROJ/INDEX resolution — also used in Step I1 (init mode); keep in sync
# NOTE: uses single-strategy basename lookup; scan-query uses three-strategy walk-up
# If index not found here but scan-query works, run with explicit --index flag or re-run /codemap:scan from project root
# bash 3.2 compatible — mapfile is bash 4+ only; macOS ships bash 3.2
_idx=()
while IFS= read -r line; do
    _idx+=("$line")
done < <(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_proj_index.py")
PROJ="${_idx[0]:-}"
INDEX="${_idx[1]:-}"
# Persist for C3/C4 — fresh shell per Bash() call loses bash variables
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-index"
echo "$PROJ" > "${TMPDIR:-/tmp}/codemap-proj"
printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
if [ -f "$INDEX" ]; then
    printf "✓ index: exists\n"
else
    printf "✗ index: not found\n"
    printf "  → Run /codemap:scan to build the index\n"
    echo "failed" > "${TMPDIR:-/tmp}/codemap-c1-status"
    exit 1
fi
```

### C3 — Index freshness (calendar age)

```bash
# timeout: 10000
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c1-status" 2>/dev/null || echo "ok")
if [ "$C1_STATUS" = "failed" ]; then
    echo "C1/C2 failed — skipping this step."
    exit 0
fi
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-index")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_freshness.py" "$INDEX"
```

### C4 — Smoke test and mtime-staleness check

`smoke_test_index.py` validates that the index file is loadable JSON and reports mtime age vs `--max-age-hours` (default 24).

```bash
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-c1-status" 2>/dev/null || echo "ok")
if [ "$C1_STATUS" = "failed" ]; then
    echo "C1/C2 failed — skipping this step."
    exit 0
fi
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-index")
SMOKE_RESULT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/smoke_test_index.py" --index-path "$INDEX")  # timeout: 10000
OK=$(echo "$SMOKE_RESULT" | jq -r '.ok')
STALE=$(echo "$SMOKE_RESULT" | jq -r '.stale')
AGE=$(echo "$SMOKE_RESULT" | jq -r '.age_hours')
if [ "$OK" != "true" ]; then
    ERR=$(echo "$SMOKE_RESULT" | jq -r '.error // "unknown"')
    printf "✗ smoke test: %s\n" "$ERR"
    printf "  → Re-run /codemap:scan to rebuild index\n"
else
    printf "✓ smoke test: index valid (mtime-age=%sh)\n" "$AGE"
    if [ "$STALE" = "true" ]; then
        printf "  ⚠ Index older than freshness threshold — run /codemap:scan to update\n"
    fi
fi
```

### C5 — Skill injection audit

```bash
# timeout: 20000
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" "$CLAUDE_PLUGIN_ROOT"
```

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

`--approve` in `$ARGUMENTS` → skip all `AskUserQuestion` calls, auto-select ★ option for every prompt. Print `[--approve] applying recommended options` in place of each question. Reasoning instruction — no bash variable needed. All subsequent `AskUserQuestion` calls follow this automatically.

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
# PROJ/INDEX resolution (mirrors block in Step C2 — keep in sync)
# bash 3.2 compatible — mapfile is bash 4+ only; macOS ships bash 3.2
_idx=()
while IFS= read -r line; do
    _idx+=("$line")
done < <(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_proj_index.py")
PROJ="${_idx[0]:-}"
INDEX="${_idx[1]:-}"
```

Index exists: report and proceed. Index missing:

Use `AskUserQuestion`:

```text
No codemap index found for project: $PROJ

a) Build now ★ — scans all .py files via ast.parse (Python only), <60s on most projects
b) Skip — I'll run /codemap:scan later (recommendations will be generic, no module-count weighting)
```

If **a** (or auto-approved): verify binary exists first, then run scanner:

```bash
# timeout: 5000
[ -x "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" ] || { printf "✗ scan-index not found at ${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index\nTry: /codemap:scan to install and rebuild.\n"; exit 1; }
# timeout: 360000
${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index
```

Report result (module count, degraded count). If **b**: note "Proceeding without index — recommendations based on skill purpose only, not module count."

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` (Claude Code internal plugin registry — format may change across versions; fallback: glob `~/.claude/plugins/cache/*/*/` if file absent or unreadable). For each plugin entry, check `installPath` key present before accessing; if absent, log `installPath field missing — plugin manifest format may have changed` and fall back gracefully to cache-glob discovery for that entry. For each plugin's `installPath`, glob:

> **⚠ Cache-mutation warning**: files discovered via `installPath` are in the plugin cache (`~/.claude/plugins/cache/`). Edits made by I5 to these files are overwritten on the next `claude plugin install` or upgrade for that plugin. For durable injection that survives upgrades, create a project-local override in `.claude/agents/` or `.claude/skills/` first, then inject into the override copy.

- `skills/*/SKILL.md` — skill files
- `agents/*.md` — agent files

Per file: extract from frontmatter: `name`, `description`, `allowed-tools` (skills) or `description` body (agents). Extract first sentence of `<objective>` section.

Flag files with injection block:

```bash
# timeout: 10000
find "$CACHE" -name "SKILL.md" -exec grep -l "command -v scan-query" {} \; 2>/dev/null
```

Build two lists: `ALREADY_INJECTED` and `CANDIDATES`.

### I3 — Score and rank candidates

Classify each candidate by value tier using `<objective>` text and `allowed-tools`:

| Tier | Signal | Recommendation |
| --- | --- | --- |
| **High** | `allowed-tools` includes `Edit` or `Write`; `<objective>` mentions spawning `foundry:sw-engineer` or `foundry:qa-specialist`; performs code changes | "Strongly recommend — agent starts with blast-radius context" |
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
  —       oss:release          CHECK   canonical injection site per check_injection.py
```

Call `AskUserQuestion` tool with:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

### I5 — Wire in the injection block

**⚠ --approve scope guard**: when running in `--approve` mode, restrict auto-injection to files under `$CLAUDE_PLUGIN_ROOT` only — skip files from other plugins in `~/.claude/plugins/cache/` that appear in the candidate list. Files from other plugins require explicit interactive confirmation; `--approve` is scoped to the current project's plugin only. In interactive mode, present all candidates but highlight cache-path files with ⚠ to remind user they affect all projects.

**Write-permission probe + rollback log** — before any mutation under `~/.claude/plugins/cache/` (or any `INSTALL_PATH` discovered via I2):

```bash
# Probe write permission before mutating cache files
INSTALL_PATH="${INSTALL_PATH:-$HOME/.claude/plugins/cache}"
[ -w "$INSTALL_PATH" ] || { echo "Error: no write permission to $INSTALL_PATH"; exit 1; }
# Rollback log — record every file edited for this run
ROLLBACK_LOG="$(mktemp "${TMPDIR:-/tmp}/codemap-init-rollback-XXXXXX.log")"
echo "[codemap init] rollback log: $ROLLBACK_LOG"
# Append one entry per edit: "<timestamp>\t<file>\t<original-sha>"
```

For each file edited, append `printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$FILE" "$(git hash-object "$FILE" 2>/dev/null || echo none)" >> "$ROLLBACK_LOG"` before writing the edit.

**On failure**: previous state is preserved; no partial write leaves cache in inconsistent state. Each edit is atomic (single `Edit` tool call); rollback log identifies every touched file so user can `git -C $INSTALL_PATH checkout -- <file>` (when cache is a git repo) or re-run `claude plugin install` to restore.

Per selected file, determine insertion point and content:

**For SKILL.md files** — find step that first spawns agent. Insert hardened soft-check block immediately before it, blank line before and after.

> **No Agent() spawn step in target SKILL.md?** Inject the block as a **pre-step before the first tool call** in the workflow (typically at the top of `<workflow>` or right after Project Detection / Flag parsing). Structural context still informs subsequent reasoning even when no agent is spawned.

```bash
# Structural context (codemap — Python projects only, silent skip if absent)
# TARGET_MODULE — derive from $ARGUMENTS (e.g. strip leading ./ and .py suffix from file path argument)
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/scan/${PROJ}.json" ]; then
    scan-query central --top 3  # timeout: 5000
fi
# If results returned: prepend a ## Structural Context (codemap) block to the agent spawn prompt.
# Also add: "For targeted analysis run: scan-query rdeps <module> or scan-query fn-blast module::function"
```

For skills where target module derives from `$ARGUMENTS` (refactor, fix with module path, review), also add after `central` — **derive `TARGET_MODULE` first**; without it calls run as `scan-query rdeps ""` and return nothing:

Derive `TARGET_MODULE` from `$ARGUMENTS`: strip leading `./`; strip leading `src/`; strip trailing `.py`; replace `/` → `.`. If result empty, use `Path($ARGUMENTS).stem`. Example: `src/foo/bar.py` → `foo.bar`.

If `TARGET_MODULE` non-empty, substitute derived value and run:

```bash
scan-query rdeps "<TARGET_MODULE>" 2>/dev/null  # timeout: 5000
scan-query deps  "<TARGET_MODULE>" 2>/dev/null  # timeout: 5000
```

**For agent `.md` files** — append to last workflow instruction paragraph, before closing section or final notes. Agents have no `$ARGUMENTS` — derive `TARGET_MODULE` from user's input prompt:

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/scan/<project>.json` exists, run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known — derive target from user's task description, not `$ARGUMENTS`) **before** any Glob/Grep exploration for structural information. Skip silently if the index is absent.
```

Report each edit: `✓ injected: <plugin>/<skill-or-agent> at line N`

### I5a — Offer git post-commit hook

Use `AskUserQuestion`:

```text
Install post-commit git hook for automatic incremental rebuild?

a) Install ★ — runs scan-index --incremental in background after every commit; index stays current with zero developer action
b) Skip — I'll run /codemap:scan or /codemap:scan --incremental manually
```

### I5b — Write hook file

If **a** (or auto-approved): before writing, check `--approve` flag. If `--approve` active (set at I0): skip `AskUserQuestion` and proceed directly to hook write — I0 already disables all confirmation gates. If `--approve` not active: invoke `AskUserQuestion`: "Install post-commit hook to `<path>`? This modifies `.git/hooks/` which is outside artifact dirs." Options: (a) **Install** · (b) **Skip**. On Skip: report `✓ post-commit hook skipped` and proceed to I6.

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
  ✓ research:plan    → <path>
  ✓ ...

Already integrated (no change):
  • develop:fix, develop:feature, ...

Skipped:
  • foundry:doc-scribe — LOW value
  • oss:release — CHECK (canonical injection site per check_injection.py)

Post-commit hook: installed / skipped

Next: run /codemap:integration check to verify all injection blocks are wired correctly.
```

</workflow>
