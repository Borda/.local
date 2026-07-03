---
name: integration
description: "Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in, 'demo' runs end-to-end validation: plumbing check + plain-vs-codemap A/B on real tasks + telemetry diagnostic. TRIGGER when: 'check' — after upgrade or when codemap stops finding context; 'init' — after first plugin install or when adding new agents/skills; 'demo' — to validate end-to-end gains or debug telemetry pipeline."
argument-hint: "check | init [--approve] | demo [--repo <url|path>] [--public] [--keep-clone] [--output <path>]"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Glob, Skill, AskUserQuestion, Agent
model: sonnet
---

<objective>

Three modes: use `init` first-time to onboard, then `check` regularly to verify, then `demo` to validate end-to-end. Default (no args) → `check`.

- **`check`** — fast diagnostic: finds `scan-query`, verifies index exists and fresh, runs smoke test, audits which skill files have injection block. Prints `✓`/`✗`/`⚠` per check with one-line remediation hints. Pure bash — no model reasoning needed for happy path.
- **`init`** — interactive onboarding: builds index if missing, discovers all installed skills and agents, scores by how much codemap would help, presents recommendation table, asks which to wire in, inserts correct injection block into each selected file.
- **`demo`** — end-to-end validation: plumbing check + index build if missing + plain-vs-codemap A/B on real tasks + telemetry pipeline diagnostic. Proves expected gains on current repo or a gated public clone.

NOT for: running structural query (use `/codemap:query-code`); pure plumbing without gain proof (use `check`); explicitly requesting a standalone index rebuild (use `/codemap:scan-codebase` — note: `init` builds the index as a side-effect when missing, but that is not its primary purpose).

Arguments: `check` (no flags) or `init [--approve]` — `--approve` auto-applies all High+Medium injection recommendations for files within codemap's own installed plugin root (the `installPath` discovered for the codemap entry in `installed_plugins.json`), installs the post-commit hook, and skips interactive prompts. **`--approve` scope**: files belonging to other installed plugins always require interactive confirmation regardless of `--approve` — they are outside codemap's installPath. CHECK-tier items (prefixed `CHECK:`) are informational and are never auto-applied under `--approve`. If codemap's installPath cannot be determined from `installed_plugins.json`, `--approve` falls back to interactive confirmation for all candidates.

</objective>

<inputs>

- **$ARGUMENTS**: optional — one of:
  - Omitted or `check` — run diagnostic; print health status for all codemap integration points
  - `init` — interactive onboarding: build index if missing, discover skills/agents, recommend injection sites, wire in selected files
  - `init --approve` — non-interactive for files within codemap's own installed plugin root (`installPath` from `installed_plugins.json`); auto-applies all High+Medium injection recommendations and installs post-commit hook without prompting. Files from other plugins require explicit interactive confirmation even under `--approve`. CHECK-tier items (`CHECK:` prefix) are informational — never auto-applied. If codemap's installPath cannot be determined, falls back to interactive. **⚠ Scope warning**: injects into cache files (see I2/I5 warning) — overwritten on next plugin upgrade. Recommended: run `init` (interactive) first to review the candidate list before using `--approve` for subsequent runs. `init` without `--approve` is a guided interactive workflow; `init --approve` uses `bin/inject_codemap.py` for deterministic automation.
  - `demo [--repo <path|url>] [--public] [--anonymize] [--keep-clone] [--output <path>]` — end-to-end validation; all flags optional; see `modes/demo.md`

</inputs>

<workflow>

## Mode detection

Parse `$ARGUMENTS` (case-insensitive):

- Starts with `check` or empty → run **check mode** (Steps C1–C4)
- Starts with `init` → run **init mode** (Steps I0–I6 (I5 has sub-steps I5a, I5b))
- Starts with `demo` → run **demo mode**

> loads: modes/demo.md

- Anything else → use `AskUserQuestion`: "Unrecognized command `$ARGUMENTS`. Which operation did you want?" Options: (a) `check` — audit integration health, (b) `init` — onboard codemap interactively, (c) `init --approve` — onboard non-interactively (auto-applies all High+Medium recommendations without prompting), (d) `demo` — end-to-end validation with A/B gain proof

## CHECK MODE (Steps C1–C4)

### C1 — Locate scan-query

Three-tier fallback (PATH → CLAUDE_PLUGIN_ROOT → newest cache install) handled by `bin/locate_scan_query.py`.

```bash
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py")  # timeout: 5000
if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "✓ scan-query: %s\n" "$SQ"
    echo "ok" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status"
else
    printf "✗ scan-query: not found\n"
    printf "  → Install: claude plugin install codemap@borda-ai-rig\n"
    echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status"
    exit 1
fi
```

### C2 — PROJ and index existence

```bash
# timeout: 5000
# C1 failed check — fresh shell loses exit status; use project-scoped sentinel
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status" 2>/dev/null || echo "ok")
[ "$C1_STATUS" = "failed" ] && { echo "C1 failed — skipping this step."; echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status"; exit 0; }
# stderr to tempfile; eval sees KEY=value stdout only
# script emits PROJ/INDEX on stdout regardless of exit code
# --output-prefix scopes tmpfiles per-project; avoids concurrent collision
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --check-exists --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null  # timeout: 5000
_resolve_rc=$?
PROJ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-proj" 2>/dev/null || echo "")
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index"
printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
if [ "$_resolve_rc" -eq 0 ]; then
    printf "✓ index: exists\n"
else
    if [ -z "$INDEX" ] || [ ! -f "$INDEX" ]; then
        printf "✗ index: not found\n  → Run /codemap:scan-codebase to build the index\n"
    else
        printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"
    fi
    echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status"
    exit 1
fi
```

### C3 — Smoke test and currency check

`check_index_smoke.py` validates the index is loadable JSON and reports mtime age (informational). When valid, `check-index-currency` performs content-based staleness detection: Tier 1 uses git SHA comparison; Tier 2 uses per-file hashes from the stored `file_shas` field (covers non-git projects and pulls/branch switches that bypass the post-commit hook).

```bash
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
C1_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status" 2>/dev/null || echo "ok")
C2_STATUS=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status" 2>/dev/null || echo "ok")
[ "$C1_STATUS" = "failed" ] || [ "$C2_STATUS" = "failed" ] && { echo "C1/C2 failed — skipping this step."; exit 0; }
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index")
command -v jq >/dev/null 2>&1 || { printf "✗ jq not found — required for smoke test; install via brew install jq or apt-get install jq\n"; exit 1; }
SMOKE_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" --index-path "$INDEX")  # timeout: 10000
[ -n "$SMOKE_JSON" ] || { printf "⚠ check_index_smoke.py returned no output\n" >&2; exit 1; }
_TSV=$(printf '%s' "$SMOKE_JSON" | jq -r '[.ok, .stale, .age_hours, (.error // "unknown")] | @tsv')
OK=$(echo "$_TSV" | cut -f1); STALE=$(echo "$_TSV" | cut -f2); AGE=$(echo "$_TSV" | cut -f3); ERR=$(echo "$_TSV" | cut -f4)
if [ "$OK" != "true" ]; then
    printf "✗ smoke test: %s\n  → Re-run /codemap:scan-codebase to rebuild index\n" "$ERR"
else
    printf "✓ smoke test: index valid (mtime-age=%sh)\n" "$AGE"
    _CIC=$(command -v check-index-currency 2>/dev/null)
    if [ -n "$_CIC" ]; then
        _CC_OUT=$(python3 "$_CIC" --index-path "$INDEX" 2>/dev/null || echo '{"status":"error","reason":"check failed"}')
        _CC_STATUS=$(printf '%s' "$_CC_OUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status','current'))" 2>/dev/null || echo "current")
        _CC_REASON=$(printf '%s' "$_CC_OUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('reason',''))" 2>/dev/null || echo "")
        if [ "$_CC_STATUS" = "current" ]; then
            printf "✓ currency: index matches source tree\n"
        elif [ "$_CC_STATUS" = "stale" ]; then
            printf "  ⚠ currency: stale — %s\n  → Run /codemap:scan-codebase --incremental to refresh\n" "$_CC_REASON"
        fi
    else
        [ "$STALE" = "true" ] && printf "  ⚠ mtime age suggests stale — run /codemap:scan-codebase to update\n"
    fi
fi
```

### C4 — Skill injection and gate wiring audit

`check_injection.py` audits three things: (1) the codemap injection block (`scan-query` marker) in installed SKILL.md files; (2) `fn-rdeps` wiring in review skills; (3) Gate A/B wiring — either via `codemap-gates.md` shared file load or inline gate text — in all wired skills.

```bash
# timeout: 20000
# cache root: ~/.claude/plugins/cache/; ls -td handles multi-org layouts
PLUGIN_CACHE=$(ls -td ~/.claude/plugins/cache/ 2>/dev/null | head -1 || echo "$HOME/.claude/plugins/cache")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" "$CLAUDE_PLUGIN_ROOT" --cache-root "$PLUGIN_CACHE"
```

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

`--approve` in `$ARGUMENTS` → auto-apply all High+Medium injection recommendations for files within codemap's own `installPath` (resolved in I2 from `installed_plugins.json`) without `AskUserQuestion`. Files belonging to other installed plugins always require interactive confirmation even under `--approve` — those files are outside codemap's installPath. If codemap's installPath cannot be determined, fall back to interactive for all candidates and print `⚠ [--approve] codemap installPath unresolvable — falling back to interactive mode for all candidates`. CHECK-tier items are never auto-applied. Print `[--approve] applying recommended options` in place of each skipped question. `init` without `--approve` is a guided interactive workflow; `init --approve` delegates to `bin/inject_codemap.py` (`inject_codemap.py --apply`) for deterministic automation.

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
# stderr to tempfile; eval sees KEY=value stdout only (same as C2)
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null  # timeout: 5000
PROJ=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-proj" 2>/dev/null || echo "")
INDEX=$(cat "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index" 2>/dev/null || echo "")
[ -n "$PROJ" ] || { printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"; exit 1; }
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-init-index"
```

Index exists: report and proceed. Index missing:

If `--approve` active and index missing: first check for monorepo structure before auto-building:

```bash
_PYPROJECT_COUNT=$(find . -maxdepth 3 \( -name 'pyproject.toml' -o -name 'setup.py' \) 2>/dev/null | head -5 | wc -l)
```

> **Note**: `find -maxdepth 3` detects packages at up to 3 directory levels. Monorepos with packages at depth 4+ (e.g. `repo/workspace/group/package/pyproject.toml`) are not detected and will proceed to auto-build without the monorepo warning. If auto-build fails or produces an empty index, re-run `init` interactively and specify `--root <package_dir>` explicitly.

If `_PYPROJECT_COUNT` ≥ 2: downgrade to interactive — print `⚠ monorepo detected — cannot auto-build without --root; please run /codemap:scan-codebase --root <package_dir> first` and skip auto-build (proceed to `AskUserQuestion` below). Otherwise: auto-select option (b) — skip `AskUserQuestion`, proceed directly to build. Print `[--approve] building index for: $PROJ`. Auto-build delegates to `codemap:scan-codebase` via `Skill()` dispatch, which runs scan-index from the project git root.

Use `AskUserQuestion`:

```text
No codemap index found for project: $PROJ

a) Skip — I'll run /codemap:scan-codebase later (recommendations will be generic, no module-count weighting)
b) Build now ★ — scans all .py files via ast.parse (Python only), <60s on most projects
```

If **a** (Skip or unavailable): note "Proceeding without index — recommendations based on skill purpose only, not module count."

If **b** (or auto-approved): verify binary exists first, then run scanner:

```text
# Delegate to codemap:scan-codebase skill — runs scan-index with correct timeout handling,
# binary validation, --root/--incremental handling, and stats reporting. Reimplementing
# the invocation here drifts from scan-codebase's contract; call the skill instead.
Skill(skill="codemap:scan-codebase")
```

Report result (module count, degraded count).

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` (Claude Code internal plugin registry — format may change across versions; fallback: glob `~/.claude/plugins/cache/*/*/` if file absent or unreadable). After reading, count entries missing `installPath`; if >50% of entries lack `installPath`, print `⚠ installed_plugins.json schema may have changed — installPath absent on majority of entries; aborting I2` and exit with actionable message (suggest re-installing or manually specifying plugin path). Otherwise, for each plugin entry, check `installPath` key present before accessing; if absent on that entry, log `installPath field missing — plugin manifest format may have changed` and fall back gracefully to cache-glob discovery for that entry. For each plugin's `installPath`, glob:

> **⚠ Cache-mutation warning**: files discovered via `installPath` are in the plugin cache (`~/.claude/plugins/cache/`). Edits made by I5 to these files are overwritten on the next `claude plugin install` or upgrade for that plugin. For durable injection that survives upgrades, create a project-local override in `.claude/agents/` or `.claude/skills/` first, then inject into the override copy. **Scope guard**: in interactive mode, I5 skips any file whose resolved plugin root falls outside the current project root and `$CLAUDE_PLUGIN_ROOT` — injection is project-scoped by default.

- `skills/*/SKILL.md` — skill files
- `agents/*.md` — agent files

Per file: extract from frontmatter: `name`, `description`, `allowed-tools` (skills) or `description` body (agents). Extract first sentence of `<objective>` section.

For each plugin discovered, set `CACHE` to its resolved `installPath` value. (No shared tmpfile write — I5 derives `INSTALL_PATH` per-file from the actual target file path, making a shared last-plugin-wins tmpfile unnecessary and misleading.) Flag files with injection block:

```bash
# timeout: 10000
# $CACHE = installPath value resolved per plugin in discovery loop above
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
find "$CACHE" -name "SKILL.md" -exec grep -lE "command -v scan-query|codemap: integrated" {} \; 2>/dev/null  # SKILL.md injection marker
find "$CACHE" -name "*.md" -path "*/agents/*" -exec grep -l "Structural context (codemap" {} \; 2>/dev/null  # agent marker differs
```

For agent files, also extract intent from `<role>` block (not `<objective>`) when scoring in I3.

Build two lists: `ALREADY_INJECTED` and `CANDIDATES`.

### I3 — Score and rank candidates

Classify each candidate by value tier. For skill files: use `<objective>` text and `allowed-tools`. For agent files: use `<role>` text and `tools` frontmatter field (agents use `<role>`, not `<objective>`).

| Tier | Signal | Recommendation |
| --- | --- | --- |
| **High** | `allowed-tools` includes `Edit` or `Write`; `<objective>` mentions spawning `foundry:sw-engineer` (requires `foundry` plugin) or `foundry:qa-specialist` (requires `foundry` plugin); performs code changes. **Cross-plugin signal downgrade**: if the scoring criterion depends on an agent from another plugin (e.g. `foundry:sw-engineer`), first check if that plugin is installed — if absent, downgrade this criterion to zero (do not score High on a cross-plugin signal that can never fire). | "Strongly recommend — agent starts with blast-radius context" |
| **Medium** | analysis or planning skills; spawns read-only agents; multi-file review without edits | "Moderate value — centrality context speeds structural decisions" |
| **Low** | documentation, release, communication; no code traversal | "Low value — structural context unlikely to help" |
| **Check/Warn** | release-orchestration skills (e.g. `oss:release` (requires `oss` plugin)) — canonical injection sites per `check_injection.py`; surface as CHECK not SKIP | "Check — injection expected per check_injection.py rubric" |
| **Skip** | config-only, single-file, non-Python purpose (e.g. shell, YAML, JS) | "Skip — not applicable for Python import graphs" |

If index built and `total_modules` value is available and `total_modules < 20`: downgrade all tiers one level (small project = less value). Skip downgrade when index was not built (skip-build path) or when `total_modules` is absent/zero (empty Python project).

### I4 — Present recommendations and ask user

Print candidate table:

```text
Codemap injection candidates for: $PROJ

  Status  Skill/Agent          Tier    Notes
  ──────────────────────────────────────────────────────────────────
  a)      develop:refactor     MEDIUM  restructures code; reads module deps for target  (requires develop plugin)
  b)      oss:cicd-steward     MEDIUM  diagnoses failures; reads code structure for context  (requires oss plugin)
  —       foundry:doc-scribe   LOW     writes docstrings; skip  (requires foundry plugin)
  ⚠check  oss:release          CHECK   expected injection site per check_injection.py — check manually  (requires oss plugin)
```

CHECK-tier items shown with `⚠check` prefix are informational only — not selectable via letter. They are NOT included when user replies "all". Verify injection status manually using `/codemap:integration check`.

Call `AskUserQuestion` tool with:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

<!-- branch outcomes: letters/all → proceed to I5 with selected file list; none → skip I5, proceed directly to I5a -->

### I5 — Wire in the injection block

**`--approve` automation path**: when `--approve` is active, delegate injection to `bin/inject_codemap.py` for deterministic automation. `PLUGIN_ROOT` is the resolved `installPath` for the codemap plugin from `installed_plugins.json` (set during I2 discovery):

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/inject_codemap.py" --apply \
    --plugin-root "$PLUGIN_ROOT"  # timeout: 30000
```

`inject_codemap.py --apply` handles file writes, idempotency checks, rollback logging, and scope guard (codemap `installPath` only). In interactive mode (`init` without `--approve`), this step executes the guided per-file workflow below instead of delegating to the script.

**⚠ --approve scope guard**: when running in `--approve` mode, restrict auto-injection to files under codemap's own `installPath` (the per-entry path discovered from `installed_plugins.json` in I2 for the codemap plugin specifically) — skip all files from other plugins. If codemap's `installPath` cannot be determined from `installed_plugins.json` (field absent or file unreadable), fall back to interactive confirmation for all candidates rather than using the broader `$CLAUDE_PLUGIN_ROOT` (which may cover the entire `~/.claude/plugins/cache/borda-ai-rig/` tree and auto-inject into unintended plugins). In interactive mode, present all candidates but highlight cache-path files with ⚠ to remind user they affect all projects.

**Write-permission probe + rollback log** — once before the file loop, then per-file INSTALL_PATH is derived from the target file's own path (walk-up until a dir with `agents/` or `skills/` child is found) — avoids the I2 last-plugin-wins overwrite where a single shared tmpfile held only the last-discovered plugin's install path:

```bash
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
ROLLBACK_LOG="$(mktemp "${TMPDIR:-/tmp}/codemap-init-rollback-XXXXXX.log")"
echo "[codemap init] rollback log: $ROLLBACK_LOG"
```

Per target file, before editing:

```bash
# derive per target, not shared I2 tmpfile — avoids last-plugin-wins overwrite
TARGET_FILE="<path to the file being injected>"
INSTALL_PATH="$(dirname "$TARGET_FILE")"
while [ "$INSTALL_PATH" != "/" ] && [ "$INSTALL_PATH" != "$HOME" ]; do
    { [ -d "${INSTALL_PATH}/agents" ] || [ -d "${INSTALL_PATH}/skills" ]; } && break
    INSTALL_PATH=$(dirname "$INSTALL_PATH")
done
{ [ "$INSTALL_PATH" = "/" ] || [ "$INSTALL_PATH" = "$HOME" ]; } && { echo "Error: could not find plugin root for $TARGET_FILE"; exit 1; }
[ -w "$INSTALL_PATH" ] || { echo "Error: no write permission to $INSTALL_PATH — re-run with appropriate permissions"; exit 1; }
# scope guard: only inject within current project or CLAUDE_PLUGIN_ROOT
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")
case "$INSTALL_PATH" in
    "$PROJECT_ROOT"/*|"${CLAUDE_PLUGIN_ROOT:-plugins/codemap}"/*)
        :  # in scope
        ;;
    *)
        echo "! BLOCKED — $TARGET_FILE is outside current project scope ($PROJECT_ROOT); skipping. To inject into this plugin, run /codemap:integration init from the target project directory."
        continue
        ;;
esac
```

For each file edited, append `printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$FILE" >> "$ROLLBACK_LOG"` before writing the edit.

**On failure**: previous state is preserved; no partial write leaves cache in inconsistent state. Each edit is atomic (single `Edit` tool call); rollback log identifies every touched file. **Limitation**: `~/.claude/plugins/cache/` is not a git repo — `git checkout` cannot restore individual files. Rollback options: (1) re-run `claude plugin install codemap@borda-ai-rig` to restore the plugin from registry; (2) manually re-edit files listed in `$ROLLBACK_LOG` to remove the injection block. The rollback log records file paths only (no original content) — this is informational, not a full snapshot restore.

Per selected file, determine insertion point and content:

**For SKILL.md files** — find the first step that spawns an agent (first `Agent(` call or first `spawn` instruction in the workflow). If multiple agent spawn steps exist, inject before the **first** one only. Insert hardened soft-check block immediately before that step, blank line before and after.

> **No Agent() spawn step in target SKILL.md?** Inject the block as a **pre-step before the first tool call** in the workflow (typically at the top of `<workflow>` or right after Project Detection / Flag parsing). Structural context still informs subsequent reasoning even when no agent is spawned.

```bash
# Structural context (codemap — Python projects only; skip if absent or --no-codemap)
# Three-tier locate fallback: PATH → CLAUDE_PLUGIN_ROOT → newest cache install
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "scan-query")
case "${ARGUMENTS:-}" in
    *--no-codemap*) ;;
    *)  _GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")
        PROJ=$(basename "$_GIT_ROOT"); _IDX="${CODEMAP_INDEX_DIR:-${_GIT_ROOT}/.cache/codemap}"
        [ -x "$SQ" ] && [ -f "${_IDX}/${PROJ}.json" ] && "$SQ" --timeout 5 central --top 3 ;;
esac
# If results returned: prepend a ## Structural Context (codemap) block to the agent spawn prompt.
# Also add: "For targeted analysis run: $SQ rdeps <module> or $SQ fn-blast module::function"
```

For skills where target module derives from `$ARGUMENTS` (refactor, fix with module path, review), also add after `central` — **derive `TARGET_MODULE` first**; without it calls run as `"$SQ" rdeps ""` and return nothing:

Derive `TARGET_MODULE` from `$ARGUMENTS`: strip leading `./`; strip leading `src/`; strip trailing `.py`; replace `/` → `.`. If result empty, use `Path($ARGUMENTS).stem`. Example: `src/foo/bar.py` → `foo.bar`.

If `TARGET_MODULE` non-empty, substitute derived value and run:

```bash
"$SQ" --timeout 5 rdeps "<TARGET_MODULE>" 2>/dev/null
"$SQ" --timeout 5 deps  "<TARGET_MODULE>" 2>/dev/null
```

**For agent `.md` files** — append to last workflow instruction paragraph, before closing section or final notes. Agents have no `$ARGUMENTS` — derive `TARGET_MODULE` from user's input prompt:

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/codemap/<project>.json` exists (or `$CODEMAP_INDEX_DIR/<project>.json` when set), run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known — derive target from user's task description, not `$ARGUMENTS`) **before** any Glob/Grep exploration for structural information. Skip silently if the index is absent. Codemap is the primary navigation tool — do NOT re-verify returned results with grep. Results are authoritative when `exhaustive=true`, `stale=false`, and `not_covered` is empty. When `not_covered` is non-empty, surface a one-line scope caveat and use `index.hint` for explicit escalation if task requires completeness.
```

Report each edit: `✓ injected: <plugin>/<skill-or-agent> at line N`

### I5a — Offer git post-commit hook

First, verify this is a git repo before offering hook installation:

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || { printf "⚠ not a git repository — skipping post-commit hook installation\n"; }
```

If not a git repo: skip I5a/I5b entirely, proceed to I6.

If `--approve` active: auto-select (b) Install, skip `AskUserQuestion`, proceed directly to I5b.

Otherwise use `AskUserQuestion`:

```text
Install post-commit git hook for automatic incremental rebuild?

a) Skip — I'll run /codemap:scan-codebase or /codemap:scan-codebase --incremental manually
b) Install ★ — runs scan-index --incremental in background after every commit; index stays current with zero developer action
```

<!-- branch outcomes: b → proceed to I5b (write hook file); a → skip I5b, proceed to I6 (summary) -->

### I5b — Write hook file

If arriving from I5a with user's **b** selection (or auto-approved via `--approve` at I5a): skip further confirmation — I5a answer is sufficient. Proceed directly to hook write. On **a** (Skip): report `✓ post-commit hook skipped` and proceed to I6.

Then write `.git/hooks/post-commit`. Idempotent — check for `# codemap: incremental` marker before writing.

> **Path-baking note**: the hook bakes `CLAUDE_PLUGIN_ROOT` at install time. After a codemap version upgrade (`claude plugin install codemap@borda-ai-rig`), the baked path becomes stale — the hook falls back to `command -v scan-index` in that case. Re-run `/codemap:integration init` (interactive) to refresh the hook path; the idempotency marker is checked before writing so a second init safely overwrites the stale hook.

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
  • oss:release — CHECK (canonical injection site per check_injection.py)  (requires oss plugin)

Post-commit hook: installed / skipped

Note: N injected file(s) are in plugin cache (~/.claude/plugins/cache/) and will be
overwritten on the next `claude plugin install` or plugin upgrade. For durable injection,
create project-local overrides in .claude/agents/ or .claude/skills/ and re-run init.

Next: run /codemap:integration check to verify all injection blocks are wired correctly.
```

</workflow>
