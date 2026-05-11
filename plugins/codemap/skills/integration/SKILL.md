---
name: integration
description: Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in.
argument-hint: 'check | init [--approve]  # --approve: non-interactive, auto-applies all High+Medium injection recommendations and installs post-commit hook'
effort: medium
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
model: sonnet
---

<objective>

Two modes: use `init` first-time to onboard, then `check` regularly to verify. Default (no args) dispatches to `check`.

- **`check`** — fast diagnostic: finds `scan-query`, verifies index exists and fresh, runs smoke test, audits which skill files have injection block. Prints `✓`/`✗`/`⚠` per check with one-line remediation hints. Pure bash — no model reasoning needed for happy path.
- **`init`** — interactive onboarding: builds index if missing, discovers all installed skills and agents, scores by how much codemap would help, presents recommendation table, asks which to wire in, inserts correct injection block into each selected file.

NOT for: building or rebuilding index (use `/codemap:scan`); running structural query (use `/codemap:query`).

Arguments: `check` (no args) or `init [--approve]` — `--approve` auto-applies all ★ recommendations non-interactively.

</objective>

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
GRN='\033[0;32m'; RED='\033[1;31m'; YEL='\033[1;33m'; NC='\033[0m'
if command -v scan-query >/dev/null 2>&1; then
    SQ=$(command -v scan-query); SRC="PATH"
elif [ -x "${CLAUDE_PLUGIN_ROOT}/bin/scan-query" ]; then
    SQ="${CLAUDE_PLUGIN_ROOT}/bin/scan-query"; SRC="CLAUDE_PLUGIN_ROOT"
else
    SQ=$(ls "$HOME/.claude/plugins/cache"/*/codemap/*/bin/scan-query 2>/dev/null | sort -V | tail -1)
    SRC="cache glob"
fi
if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "${GRN}✓${NC} scan-query: %s (via %s)\n" "$SQ" "$SRC"
else
    printf "${RED}✗${NC} scan-query: not found\n"
    printf "  → Install: claude plugin install codemap@borda-ai-rig\n"
    exit 1
fi
```

### C2 — PROJ and index existence

```bash
# timeout: 5000
# NOTE: uses single-strategy basename lookup; scan-query uses three-strategy walk-up
# If index not found here but scan-query works, run with explicit --index flag or re-run /codemap:scan from project root
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
PROJ=${GIT_ROOT:+$(basename "$GIT_ROOT")}; PROJ=${PROJ:-$(basename "$PWD")}
INDEX="${GIT_ROOT:-.}/.cache/scan/${PROJ}.json"
printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
if [ -f "$INDEX" ]; then
    printf "${GRN}✓${NC} index: exists\n"
else
    printf "${RED}✗${NC} index: not found\n"
    printf "  → Run /codemap:scan to build the index\n"
    exit 1
fi
```

### C3 — Index freshness (calendar age)

```bash
# timeout: 10000
SCANNED_AT=$(jq -r '.scanned_at // empty' "$INDEX" 2>/dev/null)
if [ -z "$SCANNED_AT" ]; then
    printf "${YEL}⚠${NC} freshness: scanned_at missing — index may be corrupted\n  → Re-run /codemap:scan\n"
else
    SCANNED_AT_CLEAN=$(echo "$SCANNED_AT" | cut -c1-19)
    SCAN_EPOCH=$(date -d "$SCANNED_AT_CLEAN" +%s 2>/dev/null || date -jf "%Y-%m-%dT%H:%M:%S" "$SCANNED_AT_CLEAN" +%s 2>/dev/null)
    if [ -z "$SCAN_EPOCH" ]; then
        printf "${YEL}⚠${NC} freshness: could not parse scanned_at timestamp (%s) — run /codemap:scan\n" "$SCANNED_AT"
    else
        NOW_EPOCH=$(date +%s)
        AGE_DAYS=$(( (NOW_EPOCH - SCAN_EPOCH) / 86400 ))
        SCAN_DATE="${SCANNED_AT:0:10}"
        if [ "$AGE_DAYS" -gt 7 ]; then
            printf "${YEL}⚠${NC} freshness: %s day(s) ago (%s)\n  → Run /codemap:scan to refresh\n" "$AGE_DAYS" "$SCAN_DATE"
        else
            printf "${GRN}✓${NC} freshness: %s day(s) ago (%s)\n" "$AGE_DAYS" "$SCAN_DATE"
        fi
    fi
fi
```

### C4 — Smoke test and git-staleness check

```bash
# timeout: 15000
OUT=$("$SQ" central --top 3 2>/tmp/cmc_err); RC=$?
if [ $RC -ne 0 ]; then
    printf "${RED}✗${NC} smoke test: exit %s\n" "$RC"
    [ -s /tmp/cmc_err ] && printf "  stderr: %s\n" "$(cat /tmp/cmc_err)"
    printf "  → Check index with: %s list\n" "$SQ"
else
    STALE=$(echo "$OUT" | jq -r '.index.stale // false' 2>/dev/null)
    printf "${GRN}✓${NC} smoke test: central query OK (git-stale=%s)\n" "$STALE"
    if [ "$STALE" = "true" ]; then
        printf "  ${YEL}⚠${NC} Python files changed since scan — run /codemap:scan to update\n"
    fi
fi
rm -f /tmp/cmc_err
```

### C5 — Skill injection audit

```bash
# timeout: 20000
[ -z "$CLAUDE_PLUGIN_ROOT" ] && { printf "${RED}✗${NC} CLAUDE_PLUGIN_ROOT unset — cannot audit injection\n"; exit 1; }
CACHE=$(dirname "$(dirname "$CLAUDE_PLUGIN_ROOT")")
printf "\n--- Skill injection audit (cache: %s) ---\n" "$CACHE"
FILES=$(find "$CACHE" -name "SKILL.md" -exec grep -l "command -v scan-query" {} \; 2>/dev/null | sort)
COUNT=$(echo "$FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$COUNT" -eq 0 ]; then
    printf "${YEL}⚠${NC} 0 SKILL.md files have injection block — codemap not integrated into any skill\n"
    printf "  → Run /codemap:integration init to add injection\n"
else
    printf "${GRN}✓${NC} %s SKILL.md file(s) have the injection block:\n" "$COUNT"
    echo "$FILES" | while read -r f; do
        [ -n "$f" ] && printf "  • %s\n" "${f#$CACHE/}"
    done
fi
# keep this list in sync with develop, oss, and research plugin skill directories
# NOTE: grep uses regex — glob '*' becomes '.*'; list must be maintained when plugins add skills
# cicd-steward and shepherd are agents (agents/*.md), not skills — no SKILL.md to check; omitted intentionally
for exp in "develop/.*/skills/fix" "develop/.*/skills/feature" "develop/.*/skills/refactor" "develop/.*/skills/plan" "develop/.*/skills/review" "develop/.*/skills/debug" "oss/.*/skills/review" "oss/.*/skills/resolve" "oss/.*/skills/analyse" "oss/.*/skills/release" "research/.*/skills/run" "research/.*/skills/topic"; do
    echo "$FILES" | grep -q "$exp" \
        || printf "  ${YEL}⚠${NC} missing injection in: %s/SKILL.md\n" "$exp"
done
AGENT_FILES=$(find "$CACHE" -name "*.md" -path "*/agents/*" -exec grep -l "Structural context (codemap" {} \; 2>/dev/null | sort)
AGENT_COUNT=$(echo "$AGENT_FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$AGENT_COUNT" -eq 0 ]; then
    printf "  ${YEL}⚠${NC} 0 agent .md files have codemap injection block\n"
else
    printf "${GRN}✓${NC} %s agent file(s) have codemap injection block\n" "$AGENT_COUNT"
fi

printf "\n--- check complete ---\n"
printf "If any check failed:\n"
printf "  • /codemap:scan    — build or refresh the index\n"
printf "  • /codemap:integration init — add injection to more skills/agents\n"
printf "  • /codemap:integration check — re-run after fixes\n"
```

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

If `--approve` is present in `$ARGUMENTS` (case-insensitive), skip all `AskUserQuestion` calls in this workflow and auto-select the ★ option for every prompt. Print `[--approve] applying recommended options` in place of each question. This is a reasoning instruction — do not set a bash variable. All subsequent `AskUserQuestion` calls in this workflow follow this rule automatically — no per-step check needed.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
PROJ=${GIT_ROOT:+$(basename "$GIT_ROOT")}; PROJ=${PROJ:-$(basename "$PWD")}
INDEX="${GIT_ROOT:-.}/.cache/scan/${PROJ}.json"
```

Index exists: report and proceed. Index missing:

Use `AskUserQuestion` to present:

```text
No codemap index found for project: $PROJ

a) Build now ★ — scans all .py files via ast.parse (Python only), <60s on most projects
b) Skip — I'll run /codemap:scan later (recommendations will be generic, no module-count weighting)
```

If **a** (or auto-approved): run scanner — verify binary exists first:

```bash
# timeout: 5000
[ -x "${CLAUDE_PLUGIN_ROOT}/bin/scan-index" ] || { printf "${RED}✗${NC} scan-index not found at ${CLAUDE_PLUGIN_ROOT}/bin/scan-index\nTry: /codemap:scan to install and rebuild.\n"; exit 1; }
# timeout: 360000
${CLAUDE_PLUGIN_ROOT}/bin/scan-index
```

Report result (module count, degraded count). If **b**: note "Proceeding without index — recommendations based on skill purpose only, not module count."

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` to find all installed plugins (fallback: if file absent, glob `~/.claude/plugins/cache/*/*/` to discover install paths). For each plugin's `installPath`, glob for:

- `skills/*/SKILL.md` — skill files
- `agents/*.md` — agent files

For each file: extract from frontmatter: `name`, `description`, `allowed-tools` (skills) or `description` body (agents). Extract first sentence of `<objective>` section.

Flag which files already have injection block:

```bash
# timeout: 10000
find "$CACHE" -name "SKILL.md" -exec grep -l "command -v scan-query" {} \; 2>/dev/null
```

Build two lists: `ALREADY_INJECTED` and `CANDIDATES` (not yet injected).

### I3 — Score and rank candidates

For each candidate skill/agent, classify by value tier using `<objective>` text and `allowed-tools`:

| Tier | Signal | Recommendation |
| --- | --- | --- |
| **High** | `allowed-tools` includes `Edit` or `Write`; `<objective>` mentions spawning `foundry:sw-engineer` or `foundry:qa-specialist`; performs code changes | "Strongly recommend — agent starts with blast-radius context" |
| **Medium** | analysis or planning skills; spawns read-only agents; multi-file review without edits | "Moderate value — centrality context speeds structural decisions" |
| **Low** | documentation, release, communication; no code traversal | "Low value — structural context unlikely to help" |
| **Skip** | config-only, single-file, non-Python purpose (e.g. shell, YAML, JS) | "Skip — not applicable for Python import graphs" |

If index built and `total_modules < 20`: downgrade all tiers one level (small project = less value from structural context).

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

Use `AskUserQuestion` to ask:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

### I5 — Wire in the injection block

For each selected file, determine insertion point and content:

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

For skills where target module can be derived from `$ARGUMENTS` (refactor, fix with module path, review), also add after `central` — **derive `TARGET_MODULE` first**; without it the calls run as `scan-query rdeps ""` and return nothing:

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

**For agent `.md` files** — append to last workflow instruction paragraph, before closing section or final notes. Note: agents do not have `$ARGUMENTS` — derive `TARGET_MODULE` from the user's input prompt (e.g., extract the module or file name mentioned in the task description):

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/scan/<project>.json` exists, run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known — derive target from user's task description, not `$ARGUMENTS`) **before** any Glob/Grep exploration for structural information. Skip silently if the index is absent.
```

Report each edit: `✓ injected: <plugin>/<skill-or-agent> at line N`

### I5a — Offer git post-commit hook

Use `AskUserQuestion` to present option:

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
    printf "${GRN}✓${NC} post-commit hook: already installed (%s)\n" "$HOOK_FILE"
elif [ -f "$HOOK_FILE" ]; then
    # Marker absent, file exists — append
    cat >> "$HOOK_FILE" << 'HOOKEOF'

# codemap: incremental index rebuild — do not remove this line
if command -v scan-index >/dev/null 2>&1; then
    scan-index --incremental >> /tmp/codemap-hook.log 2>&1 &
fi
HOOKEOF
    printf "${GRN}✓${NC} post-commit hook: appended to %s\n" "$HOOK_FILE"
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
    printf "${GRN}✓${NC} post-commit hook: created %s\n" "$HOOK_FILE"
fi
```

Report: `✓ post-commit hook installed: <path>` or `✓ already installed` if marker was already present. Hook logs to `/tmp/codemap-hook.log` — failures and version-upgrade full scans are visible there.

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
