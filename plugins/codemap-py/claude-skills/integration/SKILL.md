---
name: integration
description: "Manage codemap integration — 'check' audits installation health (scan-query reachable, index fresh, injection present), 'init' onboards codemap by discovering skills/agents, recommending injection sites, and wiring them in, 'demo' runs end-to-end validation: plumbing check + plain-vs-codemap A/B on real tasks + telemetry diagnostic. TRIGGER when: 'check' — after upgrade or when codemap stops finding context; 'init' — after first plugin install or when adding new agents/skills; 'demo' — to validate end-to-end gains or debug telemetry pipeline."
argument-hint: "check | init [--approve] | demo [--repo <url|path>] [--probe-skill <name>] [--public] [--keep-clone] [--output <path>]"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Glob, Skill, AskUserQuestion, Agent
model: sonnet
---

<objective>

Three modes: `init` first-time onboard, `check` regularly to verify, `demo` end-to-end validation. Default (no args) → `check`.

- **`check`** — fast diagnostic: find `scan-query`, verify index exists + fresh, run smoke test, audit which skill files have injection block. Prints `✓`/`✗`/`⚠` per check + one-line remediation. Pure bash — no model reasoning for happy path.
- **`init`** — interactive onboarding: build index if missing, discover installed skills/agents, score by codemap-value, present recommendation table, ask which to wire, insert injection block into each selected file.
- **`demo`** — end-to-end validation: plumbing check + index build if missing + plain-vs-codemap A/B on real tasks + telemetry diagnostic.

NOT for: running structural query (use `/codemap-py:query-code`); pure plumbing without gain proof (use `check`); explicit standalone index rebuild (use `/codemap-py:scan-codebase` — `init` builds index as side-effect when missing, but not its purpose).

**`--approve`** (init): auto-applies all High+Medium injection recommendations for files within codemap-py's own installed plugin root (`installPath` for codemap-py entry in `installed_plugins.json`), installs post-commit hook, skips interactive prompts. **Scope**: files belonging to other plugins always require interactive confirmation regardless of `--approve` — outside codemap-py's installPath. CHECK-tier items (`CHECK:` prefix) informational — never auto-applied. Codemap-py's installPath undeterminable from `installed_plugins.json` → `--approve` falls back to interactive for all candidates.

</objective>

<inputs>

- **$ARGUMENTS**: optional — one of:
  - Omitted or `check` — run diagnostic; print health status for all codemap integration points
  - `init` — interactive onboarding: build index if missing, discover skills/agents, recommend injection sites, wire in selected files
  - `init --approve` — non-interactive for files within codemap-py's own `installPath`; auto-applies all High+Medium recommendations + installs post-commit hook without prompting. Other plugins' files require interactive confirmation even under `--approve`. CHECK-tier items never auto-applied. installPath undeterminable → falls back to interactive. **⚠ Scope warning**: injects into cache files (see I2/I5 warning) — wiped on next plugin upgrade; re-run `check` after any upgrade, re-inject what it reports MISSING/OUTDATED. Recommended: run `init` (interactive) first to review candidates before `--approve`. `init` without `--approve` = guided interactive workflow; `init --approve` = `bin/inject_codemap.py` deterministic automation.
  - `demo [--repo <path|url>] [--public] [--anonymize] [--keep-clone] [--output <path>]` — end-to-end validation; all flags optional; see `modes/demo.md`

</inputs>

<workflow>

## Mode detection

Parse `$ARGUMENTS` (case-insensitive):

- Starts with `check` or empty → **check mode** (Steps C1–C4)
- Starts with `init` → **init mode** (Steps I0–I6; I5 has sub-steps I5a, I5b)
- Starts with `demo` → **demo mode**

> loads: modes/demo.md

- Anything else → `AskUserQuestion`: "Unrecognized command `$ARGUMENTS`. Which operation?" Options: (a) `check` — audit integration health, (b) `init` — onboard interactively, (c) `init --approve` — onboard non-interactively (auto-applies all High+Medium without prompting), (d) `demo` — end-to-end validation with A/B gain proof

## CHECK MODE (Steps C1–C4)

### C1 — Locate scan-query

Three-tier fallback (PATH → CLAUDE_PLUGIN_ROOT → newest cache install) handled by `bin/locate_scan_query.py`.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"  # timeout: 5000
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/locate_scan_query.py")  # timeout: 5000
if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "✓ scan-query: %s\n" "$SQ"
    echo "ok" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status-${CSID}"
else
    printf "✗ scan-query: not found\n"
    printf "  → Install: claude plugin install codemap@borda-ai-rig\n"
    echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status-${CSID}"
    exit 1
fi
```

### C2 — PROJ and index existence

```bash
# timeout: 5000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# C1 failed check — fresh shell loses exit status; use project-scoped sentinel
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
IFS= read -r C1_STATUS < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status-${CSID}" 2>/dev/null || C1_STATUS="ok"
[ "$C1_STATUS" = "failed" ] && { echo "C1 failed — skipping this step."; echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status-${CSID}"; exit 0; }
# stderr to tempfile; eval sees KEY=value stdout only. script emits PROJ/INDEX on stdout regardless of exit code
# --output-prefix scopes tmpfiles per-project; avoids concurrent collision
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/resolve_index_env.py" \
    --check-exists --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null  # timeout: 5000
_resolve_rc=$?
IFS= read -r PROJ < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-proj-${CSID}" 2>/dev/null || PROJ=""
IFS= read -r INDEX < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index-${CSID}" 2>/dev/null || INDEX=""
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index-${CSID}"
printf "  project: %s\n  index:   %s\n" "$PROJ" "$INDEX"
if [ "$_resolve_rc" -eq 0 ]; then
    printf "✓ index: exists\n"
else
    if [ -z "$INDEX" ] || [ ! -f "$INDEX" ]; then
        printf "✗ index: not found\n  → Run /codemap-py:scan-codebase to build the index\n"
    else
        printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"
    fi
    echo "failed" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status-${CSID}"
    exit 1
fi
```

`resolve_index_env.py` delegates project/index-path derivation to `resolve_proj_index.py`.

### C3 — Smoke test and currency check

`check_index_smoke.py` validates index is loadable JSON, reports mtime age by wrapping `smoke_test_index.py` (informational). When valid, `check-index-currency` does content-based staleness detection: Tier 1 uses git SHA comparison; Tier 2 uses per-file hashes from stored `file_shas` field (covers non-git projects and pulls/branch switches bypassing post-commit hook).

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
IFS= read -r C1_STATUS < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c1-status-${CSID}" 2>/dev/null || C1_STATUS="ok"
IFS= read -r C2_STATUS < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-c2-status-${CSID}" 2>/dev/null || C2_STATUS="ok"
[ "$C1_STATUS" = "failed" ] || [ "$C2_STATUS" = "failed" ] && { echo "C1/C2 failed — skipping this step."; exit 0; }
IFS= read -r INDEX < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-index-${CSID}" 2>/dev/null || INDEX=""
command -v jq >/dev/null 2>&1 || { printf "✗ jq not found — required for smoke test; install via brew install jq or apt-get install jq\n"; exit 1; }
SMOKE_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/check_index_smoke.py" --index-path "$INDEX")  # timeout: 10000
[ -n "$SMOKE_JSON" ] || { printf "⚠ check_index_smoke.py returned no output\n" >&2; exit 1; }
_TSV=$(printf '%s' "$SMOKE_JSON" | jq -r '[.ok, .stale, .age_hours, (.error // "unknown")] | @tsv')
OK=$(echo "$_TSV" | cut -f1); STALE=$(echo "$_TSV" | cut -f2); AGE=$(echo "$_TSV" | cut -f3); ERR=$(echo "$_TSV" | cut -f4)
if [ "$OK" != "true" ]; then
    printf "✗ smoke test: %s\n  → Re-run /codemap-py:scan-codebase to rebuild index\n" "$ERR"
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
            printf "  ⚠ currency: stale — %s\n  → Run /codemap-py:scan-codebase --incremental to refresh\n" "$_CC_REASON"
        fi
    else
        [ "$STALE" = "true" ] && printf "  ⚠ mtime age suggests stale — run /codemap-py:scan-codebase to update\n"
    fi
fi
```

### C4 — Skill injection and gate wiring audit

`check_injection.py` audits: (1) codemap injection block (`scan-query` marker) in installed SKILL.md files, reporting each as **current** or **OUTDATED** by comparing its `codemap-block: vN` stamp against shipped block version — a wired file whose block is wiped by plugin upgrade reports **MISSING**; (2) `fn-rdeps` wiring in review skills; (3) Gate A/B wiring — via `codemap-gates.md` shared-file load or inline gate text — in all wired skills. Per-project `.cache/codemap/integration.json` exists (written by `init`) → its recorded sites — including personal skills under `.claude/skills` — drive canonical-site audit; otherwise borda-ai-rig default list used when those plugins installed.

```bash
# timeout: 20000
# cache root: ~/.claude/plugins/cache/; ls -td handles multi-org layouts
PLUGIN_CACHE=$(ls -td ~/.claude/plugins/cache/ 2>/dev/null | head -1 || echo "$HOME/.claude/plugins/cache")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/check_injection.py" "$CLAUDE_PLUGIN_ROOT" --cache-root "$PLUGIN_CACHE"
```

`check_injection.py` resolves project `integration.json` from `$CODEMAP_INDEX_DIR` or `<cwd>/.cache/codemap` automatically; pass `--integration-dir <path>` to override. Reports OUTDATED or MISSING blocks → re-run `/codemap-py:integration init` to re-inject current block.

## INIT MODE (Steps I0–I6)

### I0 — Detect --approve

`--approve` in `$ARGUMENTS` → auto-apply all High+Medium injection recommendations for files within codemap-py's own `installPath` (resolved in I2 from `installed_plugins.json`) without `AskUserQuestion`. Other plugins' files always require interactive confirmation even under `--approve` — outside codemap-py's installPath. Codemap-py's installPath undeterminable → fall back to interactive for all candidates, print `⚠ [--approve] codemap-py installPath unresolvable — falling back to interactive mode for all candidates`. CHECK-tier items never auto-applied. Print `[--approve] applying recommended options` in place of each skipped question. `init` without `--approve` = guided interactive; `init --approve` delegates to `bin/inject_codemap.py` (`inject_codemap.py --apply`).

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>`. Found → print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### I1 — Verify or build the index

```bash
# timeout: 5000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# stderr to tempfile; eval sees KEY=value stdout only (same as C2)
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/resolve_index_env.py" \
    --output-prefix "codemap-${_CM_PROJ}" 2>/dev/null  # timeout: 5000
IFS= read -r PROJ < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-proj-${CSID}" 2>/dev/null || PROJ=""
IFS= read -r INDEX < "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-resolve-index-${CSID}" 2>/dev/null || INDEX=""
[ -n "$PROJ" ] || { printf "✗ resolve_index_env.py failed — check that python is on PATH and CLAUDE_PLUGIN_ROOT is set\n"; exit 1; }
echo "$INDEX" > "${TMPDIR:-/tmp}/codemap-${_CM_PROJ}-init-index-${CSID}"
```

Index exists: report, proceed. Index missing:

`--approve` active and index missing: first check for monorepo structure before auto-building:

```bash
_PYPROJECT_COUNT=$(find . -maxdepth 3 \( -name 'pyproject.toml' -o -name 'setup.py' \) 2>/dev/null | head -5 | wc -l)
```

> **Note**: `find -maxdepth 3` detects packages up to 3 dir levels. Monorepos with packages at depth 4+ (e.g. `repo/workspace/group/package/pyproject.toml`) not detected, proceed to auto-build without monorepo warning. Auto-build fails or produces empty index → re-run `init` interactively with `--root <package_dir>`.

`_PYPROJECT_COUNT` ≥ 2: downgrade to interactive — print `⚠ monorepo detected — cannot auto-build without --root; please run /codemap-py:scan-codebase --root <package_dir> first`, skip auto-build (proceed to `AskUserQuestion` below). Otherwise: auto-select option (b) — skip `AskUserQuestion`, proceed to build. Print `[--approve] building index for: $PROJ`. Auto-build delegates to `codemap-py:scan-codebase` via `Skill()`, runs scan-index from project git root.

Use `AskUserQuestion`:

```text
No codemap index found for project: $PROJ

a) Skip — I'll run /codemap-py:scan-codebase later (recommendations generic, no module-count weighting)
b) Build now ★ — scans all .py files via ast.parse (Python only), <60s on most projects
```

**a** (Skip or unavailable): note "Proceeding without index — recommendations based on skill purpose only, not module count."

**b** (or auto-approved): verify binary exists first, then run the scanner in the foreground:

```bash
# scan-index binary directly — the codemap-py:scan-codebase skill is disable-model-invocation:true
# (user-slash-only), so the model cannot Skill()-call it; this is the same binary the skill wraps
# and the same mechanism codemap-py's inject-preamble.js hook uses to build on demand.
command -v scan-index >/dev/null 2>&1 && scan-index || echo "! scan-index not on PATH — codemap-py plugin bin dir missing"  # timeout: 600000
```

Report result (module count, degraded count).

### I2 — Discover installed skills and agents

Read `~/.claude/plugins/installed_plugins.json` (Claude Code internal plugin registry — format may change across versions; fallback: glob `~/.claude/plugins/cache/*/*/` if file absent/unreadable). After reading, count entries missing `installPath`; >50% lack `installPath` → print `⚠ installed_plugins.json schema may have changed — installPath absent on majority of entries; aborting I2`, exit with actionable message (suggest re-installing or manually specifying plugin path). Otherwise, per plugin entry, check `installPath` key present before accessing; absent on that entry → log `installPath field missing — plugin manifest format may have changed`, fall back to cache-glob discovery for that entry. For each plugin's `installPath`, glob:

> **⚠ Cache-mutation warning**: files discovered via `installPath` are in plugin cache (`~/.claude/plugins/cache/`). I5 edits to these files wiped on next `claude plugin install` or upgrade for that plugin — Claude Code has no mechanism for project-local file to override single file inside installed plugin, plugin skills namespace-isolated, so `.claude/skills/` copy never invoked in place of plugin's own skill. **Durability comes from version-check + re-inject loop, not override file**: after plugin upgrade wipes cache injection, `check` reports it MISSING (or OUTDATED when block version changed), `init` re-injects it. **Prefer durable targets**: personal skills/agents under `.claude/skills/`, `~/.claude/skills/`, `.claude/agents/` are project/user files, not cache files — survive upgrades untouched, so when same skill exists both as plugin cache file and personal `.claude` file, wire personal copy. **Scope guard**: in interactive mode, I5 skips any file whose resolved plugin root falls outside current project root and `$CLAUDE_PLUGIN_ROOT` — injection project-scoped by default.

- `skills/*/SKILL.md` — skill files
- `agents/*.md` — agent files

Also discover **personal** skills/agents living outside any plugin (durable — not wiped by plugin upgrades). Glob these in addition to per-plugin cache globs:

- `.claude/skills/*/SKILL.md` — project-local personal skills
- `~/.claude/skills/*/SKILL.md` — user-level personal skills
- `.claude/agents/*.md` — project-local personal agents

`bin/inject_codemap.py` performs this personal discovery automatically (project root + user home) in `--approve` mode; interactive path globs them here.

Per file: extract from frontmatter `name`, `description`, `allowed-tools` (skills) or `description` body (agents). Extract first sentence of `<objective>`.

Per plugin discovered, set `CACHE` to its resolved `installPath`. (No shared tmpfile write — I5 derives `INSTALL_PATH` per-file from actual target path, making shared last-plugin-wins tmpfile unnecessary and misleading.) Flag files with injection block:

```bash
# timeout: 10000
# $CACHE = installPath value resolved per plugin in discovery loop above
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
find "$CACHE" -name "SKILL.md" -exec grep -lE "command -v scan-query|codemap: integrated" {} \; 2>/dev/null  # SKILL.md injection marker
find "$CACHE" -name "*.md" -path "*/agents/*" -exec grep -l "Structural context (codemap" {} \; 2>/dev/null  # agent marker differs
```

For agent files, also extract intent from `<role>` block (not `<objective>`) when scoring in I3.

Build two lists: `ALREADY_INJECTED`, `CANDIDATES`.

### I3 — Score and rank candidates

Classify each candidate by value tier. Skill files: use `<objective>` text and `allowed-tools`. Agent files: use `<role>` text and `tools` frontmatter field (agents use `<role>`, not `<objective>`).

| Tier | Signal | Recommendation |
| --- | --- | --- |
| **High** | `allowed-tools` includes `Edit`/`Write`; `<objective>` mentions spawning `foundry:sw-engineer` (requires `foundry` plugin) or `foundry:qa-specialist` (requires `foundry` plugin); performs code changes. **Cross-plugin signal downgrade**: criterion depends on agent from another plugin (e.g. `foundry:sw-engineer`) → check if plugin installed first — absent → downgrade criterion to zero (don't score High on cross-plugin signal that can never fire). | "Strongly recommend — agent starts with blast-radius context" |
| **Medium** | analysis/planning skills; spawns read-only agents; multi-file review without edits | "Moderate value — centrality context speeds structural decisions" |
| **Low** | documentation, release, communication; no code traversal | "Low value — structural context unlikely to help" |
| **Check/Warn** | release-orchestration skills (e.g. `oss:release` (requires `oss` plugin)) — canonical injection sites per `check_injection.py`; surface as CHECK not SKIP | "Check — injection expected per check_injection.py rubric" |
| **Skip** | config-only, single-file, non-Python purpose (e.g. shell, YAML, JS) | "Skip — not applicable for Python import graphs" |

Index built, `total_modules` available, `total_modules < 20`: downgrade all tiers one level (small project = less value). Skip downgrade when index not built (skip-build path) or `total_modules` absent/zero (empty Python project).

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

CHECK-tier items shown with `⚠check` prefix informational only — not selectable via letter. NOT included when user replies "all". Verify injection status manually via `/codemap-py:integration check`.

Call `AskUserQuestion` tool with:

```text
Which skills/agents should I add codemap injection to?

Reply with letters (e.g. "a b"), "all" (all High+Medium), or "none".
```

<!-- branch outcomes: letters/all → proceed to I5 with selected file list; none → skip I5, proceed directly to I5a -->

### I5 — Wire in the injection block

**`--approve` automation path**: when `--approve` is active, delegate injection to `bin/inject_codemap.py` for deterministic automation. `PLUGIN_ROOT` is the resolved `installPath` for the codemap-py plugin from `installed_plugins.json` (set during I2 discovery):

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/inject_codemap.py" --apply \
    --plugin-root "$PLUGIN_ROOT"  # timeout: 30000
```

`inject_codemap.py --apply` handles file writes, idempotency checks, rollback logging, scope guard (codemap `installPath` only). In interactive mode (`init` without `--approve`), this step executes guided per-file workflow below instead of delegating.

**⚠ --approve scope guard**: in `--approve` mode, restrict auto-injection to files under codemap-py's own `installPath` (per-entry path discovered from `installed_plugins.json` in I2 for codemap-py plugin specifically) — skip all files from other plugins. Codemap-py's `installPath` undeterminable (field absent or file unreadable) → fall back to interactive confirmation for all candidates rather than using broader `$CLAUDE_PLUGIN_ROOT` (may cover entire `~/.claude/plugins/cache/borda-ai-rig/` tree, auto-inject into unintended plugins). In interactive mode, present all candidates but highlight cache-path files with ⚠ to remind user they affect all projects.

**Write-permission probe + rollback log** — once before file loop; then per-file INSTALL_PATH derived from target file's own path (walk-up until dir with `agents/` or `skills/` child found) — avoids I2 last-plugin-wins overwrite where single shared tmpfile held only last-discovered plugin's install path:

```bash
_CM_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || echo "cm")
ROLLBACK_LOG="$(mktemp "${TMPDIR:-/tmp}/codemap-init-rollback-XXXXXX.log")"  # tmpdir-exempt: mktemp
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
    "$PROJECT_ROOT"/*|"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}"/*)
        :  # in scope
        ;;
    *)
        echo "! BLOCKED — $TARGET_FILE is outside current project scope ($PROJECT_ROOT); skipping. To inject into this plugin, run /codemap-py:integration init from the target project directory."
        continue
        ;;
esac
```

For each file edited, append `printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$FILE" >> "$ROLLBACK_LOG"` before writing the edit.

**On failure**: previous state preserved; no partial write leaves cache inconsistent. Each edit atomic (single `Edit` call); rollback log identifies every touched file. **Limitation**: `~/.claude/plugins/cache/` not a git repo — `git checkout` can't restore individual files. Rollback options: (1) re-run `claude plugin install codemap@borda-ai-rig` to restore plugin from registry; (2) manually re-edit files listed in `$ROLLBACK_LOG` to remove injection block. Rollback log records file paths only (no original content) — informational, not full snapshot restore.

Per selected file, determine insertion point and content:

**For SKILL.md files** — find first step spawning an agent (first `Agent(` call or first `spawn` instruction). Multiple agent-spawn steps exist → inject before **first** one only. Insert canonical block immediately before that step, blank line before and after.

> **No Agent() spawn step in target SKILL.md?** Inject block as **pre-step before first tool call** in workflow (typically top of `<workflow>` or right after Project Detection / Flag parsing). Structural context still informs subsequent reasoning even when no agent spawned.

Block text is single source of truth in `bin/_injection_block.py` (`BLOCK` constant) — don't hand-write variant here. Emit verbatim (init/check import it, so hand-edited copy would drift and fail `check`):

```bash
# timeout: 5000
python -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin'); import _injection_block as b; sys.stdout.write(b.BLOCK)"
```

Block detects index with `command -v scan-query`, runs `central --top 3` plus `fn-rdeps`/`rdeps` query when target set, prints `codemap_evidence:` line. Full query map: `skills/_shared/codemap-context.md`.

For skills where target module derives from `$ARGUMENTS` (refactor, fix with module path, review), set `TARGET_MODULE` (and `TARGET_FN` when symbol known) **before** block so targeted query fires; without them only `central` baseline runs.

Derive `TARGET_MODULE` from `$ARGUMENTS`: strip leading `./`; strip leading `src/`; strip trailing `.py`; replace `/` → `.`. Result empty → use `Path($ARGUMENTS).stem`. Example: `src/foo/bar.py` → `foo.bar`.

**For agent `.md` files** — append to last workflow instruction paragraph, before closing section or final notes. Agents have no `$ARGUMENTS` — derive `TARGET_MODULE` from user's input prompt:

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/codemap/<project>.json` exists (or the index dir named by the CODEMAP_INDEX_DIR env var when set), run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known — derive target from user's task description) **before** any Glob/Grep exploration for structural information. Skip silently if the index is absent. Codemap is the primary navigation tool — do NOT re-verify returned results with grep. Results are authoritative when `exhaustive=true`, `stale=false`, and `not_covered` is empty. When `not_covered` is non-empty, surface a one-line scope caveat and use `index.hint` for explicit escalation if task requires completeness.
```

Report each edit: `✓ injected: <plugin>/<skill-or-agent> at line N`

**Persist discovered sites** — record injected site paths to `<project>/.cache/codemap/integration.json` so `check` audits exactly sites this project wired (personal skills included), not hardcoded plugin list. `--approve` automation path writes this record automatically as part of `bin/inject_codemap.py --apply` (its JSON report names written record under `integration_record`). In interactive mode, after all edits, append wired site paths (project-relative) with:

```bash
# timeout: 10000
python -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin'); from pathlib import Path; import _injection_block as b; b.save_integration_sites(Path('.cache/codemap'), sys.argv[1:])" <wired-path-1> <wired-path-2>
```

### I5a — Offer git post-commit hook

First verify this is a git repo before offering hook installation:

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || { printf "⚠ not a git repository — skipping post-commit hook installation\n"; }
```

Not a git repo → skip I5a/I5b entirely, proceed to I6.

`--approve` active → auto-select (b) Install, skip `AskUserQuestion`, proceed to I5b.

Otherwise use `AskUserQuestion`:

```text
Install post-commit git hook for automatic incremental rebuild?

a) Skip — I'll run /codemap-py:scan-codebase or /codemap-py:scan-codebase --incremental manually
b) Install ★ — runs scan-index --incremental in background after every commit; index stays current with zero developer action
```

<!-- branch outcomes: b → proceed to I5b (write hook file); a → skip I5b, proceed to I6 (summary) -->

### I5b — Write hook file

Arriving from I5a with user's **b** (or auto-approved via `--approve` at I5a): skip further confirmation — I5a answer sufficient. Proceed to hook write. On **a** (Skip): report `✓ post-commit hook skipped`, proceed to I6.

Then write `.git/hooks/post-commit`. Idempotent — check for `# codemap: incremental` marker before writing.

> **Path-baking note**: hook bakes `CLAUDE_PLUGIN_ROOT` at install time. After codemap version upgrade (`claude plugin install codemap@borda-ai-rig`), baked path becomes stale — hook falls back to `command -v scan-index`. Re-run `/codemap-py:integration init` (interactive) to refresh hook path; idempotency marker checked before writing so second init safely overwrites stale hook.

```bash
# timeout: 5000
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/install_post_commit_hook.py" --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

Report: `✓ post-commit hook installed: <path>` or `✓ already installed` if marker present. Hook logs to `${TMPDIR:-/tmp}/codemap-hook-$$.log` <!-- tmpdir-exempt: git-hook-boundary --> — failures and version-upgrade full scans visible.

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

Note: N injected file(s) are in plugin cache (~/.claude/plugins/cache/) and wiped on the
next `claude plugin install` or plugin upgrade. Durability is the check + re-inject loop, not
an override file (plugin skills are namespace-isolated — a .claude/ copy never overrides them):
after any upgrade run /codemap-py:integration check — reports wiped blocks MISSING (or OUTDATED
when block version changed) — then re-run init to re-inject. Injected file(s) under
.claude/skills/, ~/.claude/skills/, or .claude/agents/ are project/user files, not cache — they
survive upgrades untouched.

Next: run /codemap-py:integration check to verify all injection blocks are wired correctly.
```

</workflow>
