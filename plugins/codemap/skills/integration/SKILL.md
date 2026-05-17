---
name: integration
description: "Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in."
when_to_use: "Use when setting up or configuring codemap integration for a project repository. SKIP when codemap is already configured."
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
  - `init --approve` — non-interactive; auto-applies all High+Medium injection recommendations and installs post-commit hook without prompting

</inputs>

<workflow>

## Mode detection

Parse `$ARGUMENTS` (case-insensitive):

- Starts with `check` or empty → run **check mode** (Steps C1–C5)
- Starts with `init` → run **init mode** (Steps I0–I6 (I5 has sub-steps I5a, I5b))
- Anything else → use `AskUserQuestion`: "Unrecognized command `$ARGUMENTS`. Which operation did you want?" Options: (a) `check` — audit integration health, (b) `init` — onboard codemap interactively (add `--approve` to auto-apply all recommendations without prompting)

## CHECK MODE (Steps C1–C5)

### C1 — Locate scan-query

Three-tier fallback: PATH → plugin root → cache glob.

```bash
# timeout: 5000
if command -v scan-query >/dev/null 2>&1; then
    SQ=$(command -v scan-query); SRC="PATH"
elif [ -x "${CLAUDE_PLUGIN_ROOT}/bin/scan-query" ]; then
    SQ="${CLAUDE_PLUGIN_ROOT}/bin/scan-query"; SRC="CLAUDE_PLUGIN_ROOT"
else
    SQ=$(ls "$HOME/.claude/plugins/cache"/*/codemap/*/bin/scan-query 2>/dev/null | sort -V | tail -1)
    SRC="cache glob"
fi
if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "✓ scan-query: %s (via %s)\n" "$SQ" "$SRC"
else
    printf "✗ scan-query: not found\n"
    printf "  → Install: claude plugin install codemap@borda-ai-rig\n"
    exit 1
fi
```

### C2 — PROJ and index existence

```bash
# timeout: 5000
# PROJ/INDEX resolution — also used in Step I1 (init mode); keep in sync
# NOTE: uses single-strategy basename lookup; scan-query uses three-strategy walk-up
# If index not found here but scan-query works, run with explicit --index flag or re-run /codemap:scan from project root
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
PROJ=${GIT_ROOT:+$(basename "$GIT_ROOT")}; PROJ=${PROJ:-$(basename "$PWD")}
INDEX="${GIT_ROOT:-.}/.cache/scan/${PROJ}.json"
printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
if [ -f "$INDEX" ]; then
    printf "✓ index: exists\n"
else
    printf "✗ index: not found\n"
    printf "  → Run /codemap:scan to build the index\n"
    exit 1
fi
```

### C3 — Index freshness (calendar age)

```bash
# timeout: 10000
SCANNED_AT=$(jq -r '.scanned_at // empty' "$INDEX" 2>/dev/null)
if [ -z "$SCANNED_AT" ]; then
    printf "⚠ freshness: scanned_at missing — index may be corrupted\n  → Re-run /codemap:scan\n"
else
    SCANNED_AT_CLEAN=$(echo "$SCANNED_AT" | cut -c1-19)
    SCAN_EPOCH=$(date -d "$SCANNED_AT_CLEAN" +%s 2>/dev/null || date -jf "%Y-%m-%dT%H:%M:%S" "$SCANNED_AT_CLEAN" +%s 2>/dev/null)
    if [ -z "$SCAN_EPOCH" ]; then
        printf "⚠ freshness: could not parse scanned_at timestamp (%s) — run /codemap:scan\n" "$SCANNED_AT"
    else
        NOW_EPOCH=$(date +%s)
        AGE_DAYS=$(( (NOW_EPOCH - SCAN_EPOCH) / 86400 ))
        SCAN_DATE="${SCANNED_AT:0:10}"
        if [ "$AGE_DAYS" -gt 7 ]; then
            printf "⚠ freshness: %s day(s) ago (%s)\n  → Run /codemap:scan to refresh\n" "$AGE_DAYS" "$SCAN_DATE"
        else
            printf "✓ freshness: %s day(s) ago (%s)\n" "$AGE_DAYS" "$SCAN_DATE"
        fi
    fi
fi
```

### C4 — Smoke test and git-staleness check

```bash
# timeout: 15000
OUT=$("$SQ" central --top 3 2>/tmp/cmc_err); RC=$?
if [ $RC -ne 0 ]; then
    printf "✗ smoke test: exit %s\n" "$RC"
    [ -s /tmp/cmc_err ] && printf "  stderr: %s\n" "$(cat /tmp/cmc_err)"
    printf "  → Check index with: %s list\n" "$SQ"
else
    STALE=$(echo "$OUT" | jq -r '.index.stale // false' 2>/dev/null)
    printf "✓ smoke test: central query OK (git-stale=%s)\n" "$STALE"
    if [ "$STALE" = "true" ]; then
        printf "  ⚠ Python files changed since scan — run /codemap:scan to update\n"
    fi
fi
rm -f /tmp/cmc_err
```

### C5 — Skill injection audit

```bash
# timeout: 20000
if [ -z "$CLAUDE_PLUGIN_ROOT" ]; then
    printf "⚠ CLAUDE_PLUGIN_ROOT unset — falling back to installed cache discovery\n"
    CLAUDE_PLUGIN_ROOT=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap/*/skills/integration 2>/dev/null | head -1)
    if [ -z "$CLAUDE_PLUGIN_ROOT" ]; then
        printf "✗ Could not locate codemap plugin — injection audit skipped. Run: claude plugin install codemap@borda-ai-rig\n"
        # degrade gracefully — skip C5 without aborting full skill run
    fi
fi
[ -z "$CLAUDE_PLUGIN_ROOT" ] && { printf "  Skipping injection audit.\n"; } || {
CACHE=$(dirname "$(dirname "$CLAUDE_PLUGIN_ROOT")")
printf "\n--- Skill injection audit (cache: %s) ---\n" "$CACHE"
FILES=$(find "$CACHE" -name "SKILL.md" -exec grep -l "command -v scan-query" {} \; 2>/dev/null | sort)
COUNT=$(echo "$FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$COUNT" -eq 0 ]; then
    printf "⚠ 0 SKILL.md files have injection block — codemap not integrated into any skill\n"
    printf "  → Run /codemap:integration init to add injection\n"
else
    printf "✓ %s SKILL.md file(s) have the injection block:\n" "$COUNT"
    echo "$FILES" | while read -r f; do
        [ -n "$f" ] && printf "  • %s\n" "${f#$CACHE/}"
    done
fi
# keep this list in sync with develop, oss, and research plugin skill directories
# NOTE: grep uses regex — glob '*' becomes '.*'; list must be maintained when plugins add skills
# cicd-steward and shepherd are agents (agents/*.md), not skills — no SKILL.md to check; omitted intentionally
for exp in "develop/.*/skills/fix" "develop/.*/skills/feature" "develop/.*/skills/refactor" "develop/.*/skills/plan" "develop/.*/skills/review" "develop/.*/skills/debug" "oss/.*/skills/review" "oss/.*/skills/resolve" "oss/.*/skills/analyse" "oss/.*/skills/release" "research/.*/skills/run" "research/.*/skills/topic"; do
    echo "$FILES" | grep -q "$exp" \
        || printf "  ⚠ missing injection in: %s/SKILL.md\n" "$exp"
done
AGENT_FILES=$(find "$CACHE" -name "*.md" -path "*/agents/*" -exec grep -l "Structural context (codemap" {} \; 2>/dev/null | sort)
AGENT_COUNT=$(echo "$AGENT_FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$AGENT_COUNT" -eq 0 ]; then
    printf "  ⚠ 0 agent .md files have codemap injection block\n"
else
    printf "✓ %s agent file(s) have codemap injection block\n" "$AGENT_COUNT"
fi

printf "\n--- check complete ---\n"
printf "If any check failed:\n"
printf "  • /codemap:scan    — build or refresh the index\n"
printf "  • /codemap:integration init — add injection to more skills/agents\n"
printf "  • /codemap:integration check — re-run after fixes\n"
}  # end CLAUDE_PLUGIN_ROOT guard
```

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

`--approve` in `$ARGUMENTS` → skip all `AskUserQuestion` calls, auto-select ★ option for every prompt. Print `[--approve] applying recommended options` in place of each question. Reasoning instruction — no bash variable needed. All subsequent `AskUserQuestion` calls follow this automatically.

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
# PROJ/INDEX resolution (mirrors block in Step C2 — keep in sync)
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
PROJ=${GIT_ROOT:+$(basename "$GIT_ROOT")}; PROJ=${PROJ:-$(basename "$PWD")}
INDEX="${GIT_ROOT:-.}/.cache/scan/${PROJ}.json"
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
[ -x "${CLAUDE_PLUGIN_ROOT}/bin/scan-index" ] || { printf "✗ scan-index not found at ${CLAUDE_PLUGIN_ROOT}/bin/scan-index\nTry: /codemap:scan to install and rebuild.\n"; exit 1; }
# timeout: 360000
${CLAUDE_PLUGIN_ROOT}/bin/scan-index
```

Report result (module count, degraded count). If **b**: note "Proceeding without index — recommendations based on skill purpose only, not module count."

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` (fallback: glob `~/.claude/plugins/cache/*/*/` if file absent). For each plugin's `installPath`, glob:

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
  —       oss:release          SKIP    release artifact; no code traversal
```

Use `AskUserQuestion`:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

### I5 — Wire in the injection block

Per selected file, determine insertion point and content:

**For SKILL.md files** — find step that first spawns agent. Insert hardened soft-check block immediately before it, blank line before and after:

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

```bash
# Derive TARGET_MODULE from the file/path argument (e.g. src/foo/bar.py → foo.bar)
# Fall back to a basename-only module if the argument is not under src/.
TARGET_MODULE=$(printf '%s\n' "$ARGUMENTS" | sed 's|^\./||;s|^src/||;s|\.py$||;s|/|.|g')
[ -z "$TARGET_MODULE" ] && TARGET_MODULE=$(basename "${ARGUMENTS%.py}" 2>/dev/null || echo "")
if [ -z "$TARGET_MODULE" ]; then
    echo "⚠ TARGET_MODULE empty — skipping rdeps/deps soft-check"
else
    scan-query rdeps "$TARGET_MODULE" 2>/dev/null  # timeout: 5000
    scan-query deps  "$TARGET_MODULE" 2>/dev/null  # timeout: 5000
fi
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

If **a** (or auto-approved): write `.git/hooks/post-commit`. Idempotent — check for `# codemap: incremental` marker before writing:

```bash
# timeout: 5000
# Detect hooks dir — respect core.hooksPath override if set
HOOKS_DIR=$(git config core.hooksPath 2>/dev/null || echo ".git/hooks")
HOOK_FILE="$HOOKS_DIR/post-commit"
if grep -qF '# codemap: incremental' "$HOOK_FILE" 2>/dev/null; then
    printf "✓ post-commit hook: already installed (%s)\n" "$HOOK_FILE"
elif [ -f "$HOOK_FILE" ]; then
    # Marker absent, file exists — check shebang before appending
    # Only append if shebang is sh/bash/zsh compatible; warn if unusual interpreter
    SHEBANG=$(head -1 "$HOOK_FILE" 2>/dev/null || echo "")
    case "$SHEBANG" in
        "#!/bin/sh"|"#!/bin/bash"|"#!/usr/bin/env bash"|"#!/usr/bin/env sh"|"#!/bin/zsh"|"#!/usr/bin/env zsh"|"")
            # Compatible shebang or no shebang — safe to append
            ;;
        *)
            printf "⚠ post-commit hook uses unusual interpreter: %s — appending anyway; verify compatibility\n" "$SHEBANG"
            ;;
    esac
    # Note: this append is confirmed by user in Step I5a (AskUserQuestion option a)
    cat >> "$HOOK_FILE" << 'HOOKEOF'

# codemap: incremental index rebuild — do not remove this line
if command -v scan-index >/dev/null 2>&1; then
    scan-index --incremental >> /tmp/codemap-hook.log 2>&1 &
fi
HOOKEOF
    printf "✓ post-commit hook: appended to %s\n" "$HOOK_FILE"
else
    # File does not exist — create
    cat > "$HOOK_FILE" << 'HOOKEOF'
#!/bin/sh
# codemap: incremental index rebuild — do not remove this line
if command -v scan-index >/dev/null 2>&1; then
    scan-index --incremental >> /tmp/codemap-hook.log 2>&1 &
fi
HOOKEOF
    chmod +x "$HOOK_FILE"
    printf "✓ post-commit hook: created %s\n" "$HOOK_FILE"
fi
```

Report: `✓ post-commit hook installed: <path>` or `✓ already installed` if marker present. Hook logs to `/tmp/codemap-hook.log` — failures and version-upgrade full scans visible there.

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
  • oss:release — SKIP

Post-commit hook: installed / skipped

Next: run /codemap:integration check to verify all injection blocks are wired correctly.
```

</workflow>
