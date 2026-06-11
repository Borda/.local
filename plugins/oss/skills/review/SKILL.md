---
name: review
description: "Multi-agent code review of GitHub Pull Requests (Python source, documentation (Markdown/RST), and CI/CD config PRs) covering architecture, tests, performance, docs, lint, security, and API design."
when_to_use: |
  TRIGGER when: user provides a GitHub PR number (e.g. `42`, `#42`) and asks to review/audit/check it, or provides a saved review-report path with `--reply` to draft a contributor-facing comment; phrases: "review PR 123", "audit this pull request", "look at PR #42", "draft a reply for this review report".
  SKIP: local file or current git diff review (use `/develop:review` (requires `develop` plugin)); non-Python source PRs without Python files (TypeScript-only, Go-only, Rust-only); standalone issue/discussion thread analysis (use `oss:analyse`).
argument-hint: "[PR number|path/to/report.md] [--reply] [--no-challenge] [--codemap] [--semble]"
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
model: sonnet
effort: high
---

<objective>

Spawn specialized sub-agents in parallel. Consolidate findings into structured feedback with severity levels.

NOT for local file review or current git diff — use `/develop:review` (requires `develop` plugin). NOT for non-Python source PRs (TypeScript, Go, Rust, etc.) unless they include Python files — docs-only and CI/CD-only PRs are in scope. NOT for standalone GitHub issue analysis or thread summarization — use `oss:analyse`. **Draft PRs** (GitHub `isDraft=true`) are work-in-progress; reviewing them spends the multi-agent fan-out on findings the contributor has not yet addressed — pass an explicit PR number anyway if you want the draft reviewed. Note: oss:review performs inline linked-issue analysis (root-cause alignment check in Step 1) as part of PR review — within scope, no conflict.

</objective>

<inputs>

- **$ARGUMENTS**: PR number or report path.
  - Number given (e.g. `42` or `#42`): review PR diff
  - `--reply`: spawn oss:shepherd to draft contributor-facing PR comment. Path ending in `.md` → spawn oss:shepherd from that report, skip new review.
  - **Scope**: Python source only. Non-Python file → state out of scope, suggest tool, no findings.
  - **Local files**: use `/develop:review` (requires `develop` plugin) for local files or current git diff.
  - `--codemap`: enable structural context from codemap index (off by default; requires codemap plugin installed)
  - `--semble`: enable semble semantic search companion (off by default; requires semble MCP server configured)
- **--plan handoff not supported** — skill does not accept plan-mode output from `/develop:plan` (requires `develop` plugin).

</inputs>

<constants>

CHALLENGE_ENABLED=true  # set to false via --no-challenge
CODEMAP_ENABLED=false   # set to true via --codemap
SEMBLE_ENABLED=false    # set to true via --semble
<!-- Background agent health monitoring (CLAUDE.md §6) — applies to Step 3 parallel agent spawns -->
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay

</constants>

<workflow>

<!-- Agent resolution: see _OSS_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
# loads: oss-shared-resolver.md
# loads: review-section-taxonomy.md
# Cold-start fallback (sets $_OSS_SHARED — run this first):
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
# Then: Read $_OSS_SHARED/oss-shared-resolver.md and execute its contents
# $_OSS_SHARED is required by --reply mode (Step 8 reads shepherd-reply-protocol.md). For non-reply
# flows the helpers are nice-to-have but not load-bearing — degrade gracefully instead of exiting.
if [ ! -d "$_OSS_SHARED" ]; then
    if [[ "$ARGUMENTS" == *--reply* ]]; then
        echo "⛔ _OSS_SHARED resolved to '$_OSS_SHARED' but dir absent — --reply requires oss plugin shared dir; verify oss plugin installed"
        exit 1
    else
        echo "⚠ _OSS_SHARED resolved to '$_OSS_SHARED' but dir absent — continuing with degraded functionality (oss skill-specific shared helpers unavailable; --reply mode will not work in this run)"
    fi
fi
```

Read `$_OSS_SHARED/agent-resolution.md`. Agents: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`, `oss:cicd-steward`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:perf-optimizer → general-purpose, foundry:doc-scribe → general-purpose, foundry:linting-expert → general-purpose, foundry:solution-architect → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. Each found task:

- `completed` if work done
- `deleted` if orphaned / irrelevant
- `in_progress` only if genuinely continuing

**Task tracking**: TaskCreate each major phase. Mark in_progress/completed throughout. Loop retry or scope change → new task.

Create these tasks **before** starting Step 1 (in order, all at once):

- **"Step 1: Scope and context detection"** — TaskUpdate(in_progress) at Step 1 start; TaskUpdate(completed) when all scope vars set (SCOPE, REPLY_MODE, mode flags)
- **"Steps 2–3: Agent launch + post-agent checks"** — TaskUpdate(in_progress) before spawning agents; TaskUpdate(completed) when all agent output files collected (or timed out); per task-lifecycle.md: TaskUpdate BEFORE long output blocks
- **"Step 4: Cross-validate critical findings"** — TaskUpdate(in_progress) before spawning verifier agents; TaskUpdate(completed) when all verdicts received; **skip task creation entirely** when no critical/blocking findings exist after Step 3
- **"Step 5: Consolidate findings"** — TaskUpdate(in_progress) before spawning consolidator; TaskUpdate(completed) before printing terminal block (per task-lifecycle.md: before long output)
- **"Step 8: Contributor reply draft"** — create only when REPLY_MODE=true, before spawning oss:shepherd; TaskUpdate(in_progress) immediately after creation; TaskUpdate(completed) when shepherd output written

## Step 1: Identify scope and context (run in parallel for PR mode)

Parse `$ARGUMENTS` flags (applied directly — no subprocess):

| Flag | Variable | Present | Absent |
| --- | --- | --- | --- |
| `--reply` | `REPLY_MODE` | `true` | `false` |
| `--no-challenge` | `CHALLENGE_ENABLED` | `false` | `true` |
| `--codemap` | `CODEMAP_ENABLED` | `true` | `false` |
| `--semble` | `SEMBLE_ENABLED` | `true` | `false` |

`CLEAN_ARGS`: `$ARGUMENTS` with matched flags removed, leading whitespace stripped, leading `#` stripped.

```bash
# Preflight: fail early if requested tool not available
if [ "$CODEMAP_ENABLED" = "true" ]; then
    if ! command -v scan-query >/dev/null 2>&1; then
        printf "! --codemap requested but codemap plugin not installed.\n  Install: claude plugin install codemap@borda-ai-rig\n"; exit 1
    fi
    _PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename)  # timeout: 3000
    if [ ! -f ".cache/scan/${_PROJ}.json" ]; then
        printf "! --codemap requested but no index found for project '%s'.\n  Build index: /codemap:scan-codebase\n" "$_PROJ"; exit 1
    fi
fi
```

If `SEMBLE_ENABLED=true`: proceed — semble MCP tool availability verified at first use. If `mcp__semble__search` is unavailable when called, it fails with a clear error; do not preemptively exit here.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. Found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--reply\`, \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
DIRECT_PATH_MODE=false
if [[ "$CLEAN_ARGS" == *.md ]]; then
    # Guard: reject plan files — shepherd must not draft replies from plan content
    if [[ "$CLEAN_ARGS" == .plans/* ]] || [[ "$CLEAN_ARGS" == *todo_*.md ]]; then
        echo "Error: plan files cannot be used as review report input. Pass a review report from .reports/review/<timestamp>/review-report.md or a PR number."
        exit 1
    fi
    # Validate file looks like a review report — guards against vitality reports, research reports,
    # arbitrary markdown. Required markers: at least one of `## Summary`, `verdict:`, or a
    # `APPROVED|NEEDS_WORK|REQUEST_CHANGES` token in the header region. If validation fails, warn
    # and fall back to normal review path (treat $CLEAN_ARGS as PR number — will fail the numeric
    # check below with a clear error if it isn't one).
    if [ -f "$CLEAN_ARGS" ] && grep -qE '(^## Summary|^verdict:|APPROVED|NEEDS_WORK|REQUEST_CHANGES)' "$CLEAN_ARGS" 2>/dev/null; then  # timeout: 5000
        DIRECT_PATH_MODE=true
        REVIEW_FILE="$CLEAN_ARGS"
    else
        echo "⚠ $CLEAN_ARGS is a .md file but lacks review-report markers (## Summary | verdict: | APPROVED|NEEDS_WORK|REQUEST_CHANGES) — refusing direct-path fast-path; continuing with normal review path which expects a PR number."
    fi
fi
```

```bash
FOUNDRY_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null)  # timeout: 5000
if [ -z "$FOUNDRY_SHARED" ]; then
    # Fallback to bare path so downstream Steps 5/7/consolidator don't fail on un-expanded variable;
    # they degrade gracefully when the file actually missing on disk via per-read guards.
    FOUNDRY_SHARED="plugins/foundry/skills/_shared"
    echo "⚠ Could not resolve FOUNDRY_SHARED via cache lookup — using bare fallback path '$FOUNDRY_SHARED'; foundry plugin may be absent — Steps 5/7/consolidator will degrade (per-file guards still fire)"
fi
```

```bash
if [ "$DIRECT_PATH_MODE" = "false" ]; then
    # $CLEAN_ARGS must be a non-empty numeric PR number:
    if [ -z "$CLEAN_ARGS" ] || ! [[ "$CLEAN_ARGS" =~ ^[0-9]+$ ]]; then
        echo "Error: PR number required. Usage: /oss:review <PR number> [--reply] [--no-challenge]"
        exit 1
    fi
    # Run all four in parallel:
    CHANGED_FILES=$(gh pr diff $CLEAN_ARGS --name-only 2>/dev/null)  # cache for reuse in codemap block # timeout: 6000
    gh pr view $CLEAN_ARGS                                            # PR description and metadata       # timeout: 6000
    gh pr checks $CLEAN_ARGS                                          # CI status — don't review if CI is red # timeout: 15000
    gh pr view $CLEAN_ARGS --json reviews,labels,milestone            # timeout: 6000
fi
```

**CI STATUS** (PR mode only): parse `gh pr checks` output → extract failing required check names into `CI_FAILING_CHECKS`. Any failing: set `CI_RED=true`, print `⚠ CI is red: [list failing check names] — review proceeds; status noted in report header.` Continue to Steps 2–8 regardless. Expand `$CI_RED` and `$CI_FAILING_CHECKS` to literal values in the consolidator spawn prompt (Step 5).

### File scope detection

```bash
if [ "$DIRECT_PATH_MODE" = "false" ]; then
    PY_FILES=$(echo "$CHANGED_FILES" | grep '\.py$' || true)
    DOC_FILES=$(echo "$CHANGED_FILES" | grep -E '\.(md|rst)$' || true)
    CICD_FILES=$(echo "$CHANGED_FILES" | grep -E '\.github/(workflows|actions)/|azure-pipelines\.yml|\.circleci/config\.yml|Jenkinsfile|\.travis\.yml|\.gitlab-ci\.yml' || true)
    if [ -z "$PY_FILES" ] && [ -z "$DOC_FILES" ] && [ -z "$CICD_FILES" ]; then
        echo "No Python, documentation, or CI/CD files changed in PR #$CLEAN_ARGS — skipping review (oss:review covers Python source, docs, and CI/CD config)"
        exit 0
    fi
    # Single-domain "only" modes
    [ -z "$PY_FILES" ] && [ -z "$DOC_FILES" ] && [ -n "$CICD_FILES" ] && CICD_ONLY_MODE=true || CICD_ONLY_MODE=false
    [ -z "$PY_FILES" ] && [ -z "$CICD_FILES" ] && [ -n "$DOC_FILES" ] && DOCS_ONLY_MODE=true || DOCS_ONLY_MODE=false
    # Mixed docs+CI/CD (no Python) — keep both lanes alive without falling through to full Python mode
    if [ -z "$PY_FILES" ] && [ -n "$DOC_FILES" ] && [ -n "$CICD_FILES" ]; then
        DOCS_CICD_MODE=true
    else
        DOCS_CICD_MODE=false
    fi
    # Persist mode flags to temp file — bash state lost between SKILL.md code blocks;
    # Step 2 EXPECTED_FILE construction (different bash block) reads these back.
    echo "$CLEAN_ARGS" > "${TMPDIR:-/tmp}/oss-review-pr-tag"  # persist PR identifier for cross-block file path reconstruction
    _REVIEW_MODE_FILE="${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}"
    {
        echo "CICD_ONLY_MODE=$CICD_ONLY_MODE"
        echo "DOCS_ONLY_MODE=$DOCS_ONLY_MODE"
        echo "DOCS_CICD_MODE=$DOCS_CICD_MODE"
    } > "$_REVIEW_MODE_FILE"
fi
```

### Scope pre-check

**CI/CD-only mode** (`CICD_ONLY_MODE=true`): PR changes only CI/CD config files (`.github/workflows/`, `.github/actions/`, `azure-pipelines.yml`, `.circleci/config.yml`, `Jenkinsfile`, etc.), no `.py` or `.md`/`.rst`. Spawn `oss:cicd-steward` + Agent 1 (sw-engineer) + Agent 7 (challenger, if `CHALLENGE_ENABLED=true`) + Codex (if available); skip Agents 2, 3, 4, 5, 6. Skip scope classification below — proceed directly to agent launch.

**Docs-only mode** (`DOCS_ONLY_MODE=true`): PR changes only `.md`/`.rst` files, no `.py`. **foundry:doc-scribe (Agent 4) leads** — it owns the docs domain and is the canonical reviewer here. **foundry:sw-engineer (Agent 1) is explicitly skipped** per its `NOT for docs` clause; spawning it in DOCS_ONLY_MODE produces wrong-domain analysis. Spawn: Agent 4 (foundry:doc-scribe), Agent 7 (challenger, if `CHALLENGE_ENABLED=true`), and Codex (if available). Skip Agents 1, 2, 3, 5, 6. Skip scope classification below — proceed directly to agent launch. Note: linked-issue spawns also skip Agent 1 in DOCS_ONLY_MODE — see linked-issue analysis block below.

**Docs + CI/CD mode** (`DOCS_CICD_MODE=true`): PR changes only `.md`/`.rst` and CI/CD config — no Python source. Spawn `oss:cicd-steward` (Agent 8) + `foundry:doc-scribe` (Agent 4) only; optionally `foundry:challenger` (Agent 7) when `CHALLENGE_ENABLED=true`. Skip Agents 1, 2, 3, 5, 6 — there is no Python source to analyse. Skip scope classification below — proceed directly to agent launch. The 7-agent Python fan-out is incorrect for CI+docs PRs and would produce mostly empty findings.

Before spawning agents (Python mode only — `CICD_ONLY_MODE`, `DOCS_ONLY_MODE`, `DOCS_CICD_MODE` all false), classify diff:

- Count files changed, lines added/removed, new classes/modules
- Classify: **FIX** (\<3 files, \<50 lines), **REFACTOR** (internal restructure, no new public API), **FEATURE** (new public API or module), **CHORE** (deps, config, tooling — no logic changes), or **MIXED**
- **Caveat — short-diff multi-concern refactors**: the FIX heuristic ("\<3 files, \<50 lines") classifies by diff size, not intent. A short-diff change can still be REFACTOR when it spans multiple concerns: PR labels include `perf`, `performance`, `optimization`, `refactor`, `architecture`, or `cleanup`; commit message keywords `refactor:`, `perf:`, `rewrite`; or the diff touches different modules (e.g. `core/` + `api/`). Detect via PR labels/title (`gh pr view --json labels,title`) — if any signal present, **override FIX → REFACTOR** so perf-optimizer (Agent 3) and solution-architect (Agent 6) still run. Small-diff perf refactors (list-comprehension → generator on a hot path) are exactly the case FIX would silently mishandle.
- **Complexity smell**: 8+ files changed OR `PY_LOC_DELTA >400` → note in report header

H6 — assign `SCOPE` shell variable so the `EXPECTED` array (Step 2 health monitor) can branch on it without comparing to an undefined value:

```bash
# Count Python files + total Python LOC delta for the classification heuristic
PY_FILE_COUNT=$(echo "$PY_FILES" | grep -c . 2>/dev/null || echo 0)
# PY_LOC_DELTA = total churn (added + deleted lines), NOT net delta (added − deleted).
# Pure rename refactors (e.g. delete 24 + add 24) produce PY_LOC_DELTA=48 even though the
# net change is 0; this can mis-route as FIX. The label/keyword override above (REFACTOR
# escape hatch) is the intended mitigation; classify churn-bias as a known limitation.
PY_LOC_DELTA=$(gh pr diff $CLEAN_ARGS 2>/dev/null | grep -E '^[+-][^+-]' | grep -vE '^[+-]{3}' | wc -l | tr -d ' ')  # timeout: 6000

# Detect new public API surface: added lines in src/**/__init__.py
NEW_API_LINES=$(gh pr diff $CLEAN_ARGS -- ':(glob)src/**/__init__.py' 2>/dev/null | grep -c '^+[^+]' || echo 0)  # timeout: 6000

# Detect pure config/deps changes (no .py logic changes)
NON_CONFIG_PY=$(echo "$PY_FILES" | grep -vE '(pyproject\.toml|setup\.cfg|setup\.py|requirements.*\.txt|conftest\.py)' || true)

SCOPE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/classify_pr_scope.py" --py-files "$PY_FILE_COUNT" --loc-delta "$PY_LOC_DELTA" --new-api-lines "$NEW_API_LINES" --labels "$PR_LABELS" --title "$PR_TITLE" 2>/dev/null)  # timeout: 10000
echo "→ SCOPE=$SCOPE (py_files=$PY_FILE_COUNT, py_loc=$PY_LOC_DELTA, new_api=$NEW_API_LINES)"

# Persist SCOPE and CHORE_DEPS flags alongside mode flags — Step 2 EXPECTED_FILE
# construction is in a separate bash block; without persistence these expand empty.
# CHORE_DEPS detection mirrors the conditional below (CHORE + dependency files exception).
echo "$CHANGED_FILES" | grep -qE '(^|/)(requirements.*\.txt|pyproject\.toml|package.*\.json|Pipfile|poetry\.lock|setup\.cfg|.*\.lock)$' && CHORE_DEPS=true || CHORE_DEPS=false
_REVIEW_SCOPE_FILE="${TMPDIR:-/tmp}/oss-review-scope-${CLEAN_ARGS}"
{
    echo "SCOPE=$SCOPE"
    echo "CHORE_DEPS=$CHORE_DEPS"
} > "$_REVIEW_SCOPE_FILE"
```

Skip optional agents by classification:

- FIX scope → skip Agent 3 (perf-optimizer), Agent 6 (solution-architect)
- REFACTOR scope → keep all agents; perf-optimizer runs to verify new structure isn't slower
- FEATURE/MIXED → spawn all agents
- CHORE scope → spawn Agents 1 (sw-engineer), 4 (doc-scribe), 5 (linting-expert), 7 (challenger, if `CHALLENGE_ENABLED=true`), Codex (if available); skip Agents 2, 3, 6
  - **CHORE + dependency files exception**: diff includes any of `requirements*.txt`, `pyproject.toml`, `package*.json`, `Pipfile`, `poetry.lock`, `setup.cfg`, `*.lock` → keep Agent 2 (qa-specialist) — its OWASP Top 10 check is calibrated for dependency CVE risk that sw-engineer is not. Detect via: `echo "$CHANGED_FILES" | grep -qE '(^|/)(requirements.*\.txt|pyproject\.toml|package.*\.json|Pipfile|poetry\.lock|setup\.cfg|.*\.lock)$' && CHORE_DEPS=true || CHORE_DEPS=false`. CHORE + non-deps (pure tooling/config) → skip qa-specialist per default CHORE behavior.

### Structural context (codemap — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`.**

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/scan/${PROJ}.json" ]; then
    # Reuse $CHANGED_FILES cached from the gh pr diff call above — no redundant fetch
    CHANGED_MODS=$(echo "$CHANGED_FILES" | grep '\.py$' | sed 's|^src/||;s|\.py$||;s|/|.|g' | grep -v '__init__$')
    scan-query central --top 5 2>/dev/null  # timeout: 5000
    for mod in $CHANGED_MODS; do scan-query rdeps "$mod" 2>/dev/null; done  # timeout: 5000
fi
```

Codemap returns results: prepend `## Structural Context (codemap)` block to **Agent 1 (foundry:sw-engineer)** spawn prompt. Include:

- Each changed module's `imported_by` count — label **high risk** (>20), **moderate** (5–20), or **low** (\<5)
- `central --top 5` for project-wide blast-radius reference

Agent 1 uses this to prioritize: high `imported_by` modules warrant deeper scrutiny on API compat, error handling, correctness — downstream callers outside diff not otherwise visible.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt:

> If `mcp__semble__search` available in tools and any changed module's codemap result was non-exhaustive (`"exhaustive": false`) or codemap absent: call `mcp__semble__search` with `query="<module> import"` and `repo=<git_root>`, `top_k=20` per module. Stop per module when two consecutive queries return no new importers. Merge with codemap results. Skip if all codemap results exhaustive.

### Linked issue analysis (PR mode only)

Parse PR body (`gh pr view $CLEAN_ARGS`) for issue refs (`Closes #N`, `Fixes #N`, `Resolves #N`, `refs #N` — case-insensitive). Extract to `ISSUE_NUMS`. Cap 3.

`ISSUE_NUMS` non-empty AND `DOCS_CICD_MODE != true`: spawn one **foundry:sw-engineer** per issue in Step 2 alongside Codex — all launch simultaneously in one message batch; no sequential hold between Codex and issue agents. Step 2's unified wait covers all outputs before Step 3. **Skip linked-issue sw-engineer spawn when `DOCS_CICD_MODE=true`** — DOCS_CICD_MODE has no Python source for an sw-engineer to analyse, and the mode's contract is to skip Agent 1. Each issue agent:

- Fetch issue: `gh issue view <N> --json title,body,comments,state,labels`
- Fetch comments: `gh issue view <N> --comments`
- Produce `/oss:analyse`-style output: Summary, Root Cause Hypotheses table (top 3), Code Evidence for top hypothesis
- Write full analysis to `$RUN_DIR/issue-<N>.md` (file-handoff protocol)
- Return compact JSON envelope only: `{"status":"done","issue":N,"root_cause":"<one-line summary>","file":"$RUN_DIR/issue-<N>.md","confidence":0.N}`

`ISSUE_NUMS` empty → skip issue checks downstream.

### Direct report fast-path

`DIRECT_PATH_MODE=true`:

- `REPLY_MODE=false` → use `AskUserQuestion`: "A report path was passed without `--reply`. Did you mean `/review <path.md> --reply`?" Options: (a) "Yes — continue with `--reply` mode" → set `REPLY_MODE=true`; then re-check: `[ ! -f "$REVIEW_FILE" ] && echo "Error: review file not found at $REVIEW_FILE" && exit 1`; proceed; (b) "No — review a PR instead" → print usage hint (`/review <N> | path/to/dir`) and stop.
- `REPLY_MODE=true` and `[ ! -f "$REVIEW_FILE" ]` → print `Error: report not found: $REVIEW_FILE` and stop.
- `REPLY_MODE=true` and file exists → print `[direct] using $REVIEW_FILE` → **skip to Step 8**. Skip Steps 2–7.

## Step 2: Codex + parallel agent launch

Set up run directory (shared by all agents) and resolve skill paths:

```bash
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".temp/review/$TIMESTAMP"
mkdir -p "$RUN_DIR" # timeout: 5000
REPORT_DIR=".reports/review/$TIMESTAMP"
mkdir -p "$REPORT_DIR" # timeout: 5000
```

**Resolve `REVIEW_SKILL_DIR`**: run `find ~/.claude/plugins -path "*/oss/skills/review" -type d 2>/dev/null`; if non-empty use that as the literal value, otherwise fall back to `plugins/oss/skills/review`. This resolved literal is `REVIEW_SKILL_DIR` — substitute it into every Agent spawn prompt below.

**File-based handoff**: read `$FOUNDRY_SHARED/file-handoff-protocol.md`. File absent → warn: "file-handoff protocol not found — verify foundry plugin installed (`claude plugin list`); continuing without it." Then continue without it.

**IMPORTANT**: Replace `$RUN_DIR`, `$REPORT_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, and `$DATE` with actual literal computed values in every Agent spawn prompt below. Do NOT pass as shell variables — agents receive text, not shell context. Un-expanded `$RUN_DIR` creates directory literally named `$RUN_DIR` in project root.

Check Codex availability:

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && CODEX_AVAILABLE=1 && echo "codex (openai-codex) available" || { CODEX_AVAILABLE=0; echo "⚠ codex (openai-codex) not found — skipping co-review"; } # timeout: 15000
```

Every agent prompt must end with:

> "Write your FULL findings (all sections, Confidence block) to `$RUN_DIR/<agent-slug>.md` using the Write tool — where `<agent-slug>` uses hyphen separator (no colon), e.g. `foundry--sw-engineer.md`, `foundry--qa-specialist.md`, `foundry--perf-optimizer.md`, `foundry--doc-scribe.md`, `foundry--linting-expert.md`, `foundry--solution-architect.md`. Colons invalid in macOS filenames. Return to caller ONLY compact JSON envelope on final line — nothing else after it: `{\"status\":\"done\",\"findings\":N,\"severity\":{\"critical\":0,\"high\":1,\"medium\":2},\"file\":\"$RUN_DIR/<agent-slug>.md\",\"confidence\":0.88}`"

**Agent 1 — foundry:sw-engineer**: Review architecture, SOLID, type safety, error handling, code structure. Check Python anti-patterns (bare `except:`, `import *`, mutable defaults). Flag blocking vs suggestions.

**Reuse audit**: Before accepting any new helper, utility, or class introduced in the diff, search for existing equivalents: use `Grep` with semantic function-name patterns across `src/` (e.g. `grep -r "def <name_root>" src/`); if `SEMBLE_ENABLED=true`, also call `mcp__semble__search(query="<function purpose>", repo=<git_root>, top_k=10)`. Near-duplicate found → flag as MEDIUM: "existing utility at `<path>` covers this — reuse or extend instead of reimplementing."

**Error path analysis** (new/changed code): For each error-handling path introduced or modified, produce table:

| Location | Exception/Error | Caught? | Action if caught | User-visible? |
| --- | --- | --- | --- | --- |

Flag rules:

- Caught=No + User-visible=Silent → **HIGH** (unhandled error path)
- Caught=Yes + Action=`pass` or bare `except` → **MEDIUM** (swallowed error)
- Cap 15 rows. New/changed paths only.

Read `$REVIEW_SKILL_DIR/checklist.md` — apply CRITICAL/HIGH patterns as severity anchors. Respect suppressions.

`ISSUE_NUMS` non-empty: read `$RUN_DIR/issue-*.md`. Evaluate whether changes address root cause, not just symptom. PR addresses symptom only → `[blocking] HIGH — root cause misalignment`. PR description diverges from issue problem → `HIGH — PR/issue scope divergence`.

**Agent 2 — foundry:qa-specialist**: Audit test coverage and run quick security/vulnerability scan. Find untested paths, missing edge cases, test quality issues. Check ML-specific issues (non-deterministic tests, missing seed pinning). List top 5 missing tests.

**Security scan (runs on every PR — not conditional)**: Check OWASP Top 10 — SQL injection, XSS, insecure deserialization, hardcoded secrets/tokens, missing input validation, path traversal. Run `pip-audit` if `requirements*.txt`, `pyproject.toml`, or any `*.lock` in diff. Surface dep CVEs as HIGH; secrets as CRITICAL.

Also check explicitly (GT-level findings, not afterthoughts):

- Concurrent access to shared state (when locks or shared variables present)
- Error paths: calling methods in wrong order (e.g., `log()` before `start()`)
- Resource cleanup on exception (file handles, database connections)
- Boundary conditions for division, empty collections, zero-count inputs
- Type-coercion boundary inputs: `int()`, `float()`, `datetime` parsers — test near-valid inputs (float strings for int parsers, empty strings, very large values, None)

**Consolidation rule**: One finding per test gap with concise scenario list, not separate findings. Format: "Missing tests for `parse_numeric()`: empty string, None, very large integers, float-string for int parser." Keeps section actionable, ≤5 items.

`ISSUE_NUMS` non-empty: read `$RUN_DIR/issue-*.md`. Check tests cover linked issue reproduction scenario. Issue has minimal repro/trace not covered by tests → `HIGH — issue reproduction not tested`.

**Agent 3 — foundry:perf-optimizer**: Find perf issues. Algorithmic complexity, Python loops that should be NumPy/torch ops, repeated computation, unnecessary I/O. ML code: DataLoader config, mixed precision. Prioritize by impact.

**Agent 4 — foundry:doc-scribe**: Check doc completeness. Public APIs without docstrings, missing Google style sections, outdated README, CHANGELOG gaps. Verify examples run.

- **Algorithmic accuracy check**: Functions computing math results — verify docstring claims match implementation. Output shape/length match? Standard name (e.g. "moving average") match behavior (expanding vs sliding window)? Deviates from convention → MEDIUM (docstring must document deviation). **Deprecation check**: Check stdlib deprecated usage in public API surface only (skip private functions, classes, constants, and modules starting with `_`). E.g., `datetime.utcnow()` deprecated since Python 3.12 (use `datetime.now(datetime.UTC)` on Python 3.11+ or `datetime.now(tz=timezone.utc)` for all versions), `os.path` vs `pathlib`. Flag deprecated usage as MEDIUM with replacement. Route to `foundry:linting-expert` if ruff/mypy can catch automatically — avoid duplicate findings.

**Agent 5 — foundry:linting-expert**: Static analysis. Check ruff/mypy pass. Type annotation gaps on public APIs, suppressed violations without explanation, missing pre-commit hooks. Flag mismatched Python version.

**Security scan ownership**: Agent 2 (foundry:qa-specialist) owns all security/vulnerability scanning — runs on every PR unconditionally. Agent 1 (sw-engineer) adds supplementary security scrutiny only when diff explicitly touches auth, input parsing, or serialization logic: flag insecure implementation patterns (e.g. string-formatted SQL, raw `eval()`). No separate security agent spawn.

**Agent 6 — foundry:solution-architect**: Spawns for FEATURE, MIXED, and REFACTOR scope. Public-API PRs (diff touches `__init__.py` exports, Protocols/ABCs, new public classes): evaluate API design, coupling, backward compat. **Backward-compat caveat for removals**: only flag a removed export as requiring a deprecation period if it was present in the latest published release (`git describe --tags --abbrev=0`). Exports added after the latest tag were never released — clean removal is acceptable and must NOT be flagged as a breaking change or deprecation gap. REFACTOR-scope PRs (internal restructure, no new public API): evaluate module boundaries, coupling/cohesion, and whether restructuring introduces new architectural debt — even without public API changes, structural decisions affect maintainability.

**Agent 7 — foundry:challenger (skip only if `CHALLENGE_ENABLED=false` — pass `--no-challenge` to opt out)**: Adversarial review of design decisions. Attacks assumptions, missing edge cases, security risks, architectural concerns, complexity creep with mandatory refutation step. File-handoff: per preamble above (output to `foundry--challenger.md`). Severity mapping: Blockers → critical/high; Concerns → medium; Nitpicks → low.

**Agent 8 — oss:cicd-steward (CI/CD-only mode and docs+CI/CD mode)**: Review CI/CD config changes. Check: correctness (valid YAML/syntax, correct job ordering, trigger expressions), security (pinned SHA for third-party actions, no secret exposure in logs, `permissions:` scopes minimal), best practices (cache keys, matrix strategy, workflow topology), and breaking changes to existing CI behavior (removed jobs, changed required checks). Write findings to `$RUN_DIR/oss--cicd-steward.md`.

**Health monitoring** (CLAUDE.md §6): Create checkpoint BEFORE spawning agents — timing starts from first spawn:

```bash
REVIEW_CHECKPOINT="${TMPDIR:-/tmp}/review-check-$(date +%s)"
touch "$REVIEW_CHECKPOINT"
# Persist checkpoint path — the poll block (separate bash invocation) reads it back.
# Without this persistence the poll block expands $REVIEW_CHECKPOINT empty and
# `find -newer ""` errors out, masking stalled agents.
echo "$REVIEW_CHECKPOINT" > "${TMPDIR:-/tmp}/oss-review-checkpoint"
```

Launch Codex, issue agents, and all review agents in one message batch — zero hold between Codex and review agents:

```bash
CODEX_OUT="$RUN_DIR/foundry--codex.md"
# All Agent() calls below go in a SINGLE response turn — Codex + all review agents start simultaneously:
# [if CODEX_AVAILABLE=1] Agent(subagent_type="codex:codex-rescue", prompt="Adversarial review: look for bugs, missed edge cases, incorrect logic, and inconsistencies with existing code patterns. Read-only: do not apply fixes. Write findings to $RUN_DIR/foundry--codex.md.")
# [skip entire issue-agent block if DOCS_CICD_MODE=true] [for each N in ISSUE_NUMS] — for each issue number N, substitute $RUN_DIR (literal computed path) and N (literal number) into prompt BEFORE Agent() call; agents receive text, not shell context:
# Agent(subagent_type="foundry:sw-engineer", prompt="<issue N prompt — see Step 1 issue agent spec>. Write to <expanded-RUN_DIR>/issue-<N>.md")
# Agent(subagent_type="foundry:sw-engineer", ...) ← Agent 1
# Agent(subagent_type="foundry:qa-specialist", ...) ← Agent 2
# Agent(subagent_type="foundry:perf-optimizer", ...) ← Agent 3
# Agent(subagent_type="foundry:doc-scribe", ...) ← Agent 4
# Agent(subagent_type="foundry:linting-expert", ...) ← Agent 5
# [optional] Agent(subagent_type="foundry:solution-architect", ...) ← Agent 6
# [skip if CHALLENGE_ENABLED=false] Agent(subagent_type="foundry:challenger", ...) ← Agent 7
# [if CICD_ONLY_MODE=true OR DOCS_CICD_MODE=true] Agent(subagent_type="oss:cicd-steward", ...) ← Agent 8
```

**Ordering — authoritative**: agent spawns in Step 2 issue in a single message batch and run **concurrently**. The "wait" below is a polling phase, not a sequential gate: orchestrator polls every `$MONITOR_INTERVAL` for expected output files. Step 3 post-agent checks (3a ecosystem, 3b OSS) may issue in the same response turn as the final Step 2 polls — they depend only on `$PR_BASE` being bound (computed at the top of Step 3), not on Step 2 agents completing. Do not block Step 3 on Step 2 outputs.

Poll for expected output files per `$MONITOR_INTERVAL` / `$HARD_CUTOFF` until all present or each hits hard cutoff.

Write expected paths to file (Bash arrays don't persist across tool invocations — file-based handoff lets later poll blocks read the same list):

```bash
# Restore mode flags + SCOPE persisted in Step 1 (each SKILL.md bash block runs in a
# fresh shell — without this rehydration, CICD_ONLY_MODE/DOCS_ONLY_MODE/DOCS_CICD_MODE/SCOPE
# expand empty here and EXPECTED_FILE branches on wrong values).
_PR_TAG=$(cat "${TMPDIR:-/tmp}/oss-review-pr-tag" 2>/dev/null || echo "unknown")
_REVIEW_MODE_FILE="${TMPDIR:-/tmp}/oss-review-mode-flags-${_PR_TAG}"
_REVIEW_SCOPE_FILE="${TMPDIR:-/tmp}/oss-review-scope-${_PR_TAG}"
[ -f "$_REVIEW_MODE_FILE" ] && . "$_REVIEW_MODE_FILE"
[ -f "$_REVIEW_SCOPE_FILE" ] && . "$_REVIEW_SCOPE_FILE"

POLL_START=$(date +%s)
EXPECTED_FILE="$RUN_DIR/.expected-files"
: >"$EXPECTED_FILE"  # truncate / create empty
[ "$CODEX_AVAILABLE" = "1" ] && echo "$RUN_DIR/foundry--codex.md" >>"$EXPECTED_FILE"
[ "$DOCS_CICD_MODE" != "true" ] && for N in $ISSUE_NUMS; do echo "$RUN_DIR/issue-$N.md" >>"$EXPECTED_FILE"; done
# cicd-steward runs in CI/CD-only mode AND in docs+CI/CD mode
{ [ "$CICD_ONLY_MODE" = "true" ] || [ "$DOCS_CICD_MODE" = "true" ]; } && echo "$RUN_DIR/oss--cicd-steward.md" >>"$EXPECTED_FILE"
# sw-engineer (Agent 1) runs in Python modes only; skipped for docs-only (foundry:doc-scribe handles docs) and docs+CI/CD (no Python source)
[ "$DOCS_CICD_MODE" != "true" ] && [ "$DOCS_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--sw-engineer.md" >>"$EXPECTED_FILE"
{ [ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && { [ "$SCOPE" != "CHORE" ] || [ "$CHORE_DEPS" = "true" ]; }; } && echo "$RUN_DIR/foundry--qa-specialist.md" >>"$EXPECTED_FILE"
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && [ "$SCOPE" != "CHORE" ] && [ "$SCOPE" != "FIX" ] && echo "$RUN_DIR/foundry--perf-optimizer.md" >>"$EXPECTED_FILE"
# doc-scribe runs whenever docs exist (DOCS_ONLY, DOCS_CICD, Python with docs) — only skipped in pure CI/CD-only mode
[ "$CICD_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--doc-scribe.md" >>"$EXPECTED_FILE"
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--linting-expert.md" >>"$EXPECTED_FILE"
[ "$CHALLENGE_ENABLED" = "true" ] && echo "$RUN_DIR/foundry--challenger.md" >>"$EXPECTED_FILE"
# solution-architect spawned for FEATURE/MIXED/REFACTOR Python-mode PRs (not FIX, CHORE, or single-domain modes)
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && [ "$SCOPE" != "FIX" ] && [ "$SCOPE" != "CHORE" ] && echo "$RUN_DIR/foundry--solution-architect.md" >>"$EXPECTED_FILE"
```

Later poll blocks read paths back via `while read -r path; do [ -f "$path" ] || PENDING=1; done <"$EXPECTED_FILE"` — no in-memory array required.

Every `$MONITOR_INTERVAL` seconds, in the poll bash block, rehydrate the checkpoint path first (separate bash invocations don't share variables): `REVIEW_CHECKPOINT=$(cat "${TMPDIR:-/tmp}/oss-review-checkpoint" 2>/dev/null)` then `find $RUN_DIR -newer "$REVIEW_CHECKPOINT" -type f | wc -l` — non-zero = agents alive (refresh checkpoint: `touch "$REVIEW_CHECKPOINT"`); zero since last refresh for `$HARD_CUTOFF` seconds = stalled. One `$EXTENSION` if `tail -20` output file explains delay; second stall = cutoff. On timeout: read partial results from stalled agent's file; surface with ⏱ in report. Never omit timed-out agents.

After all outputs collected (or timed out), proceed to post-agent checks.

```bash
ls "$RUN_DIR/"*.md 2>/dev/null || echo "⚠ No agent output files found in $RUN_DIR — check that $RUN_DIR was expanded correctly in spawn prompts"
```

## Step 3: Post-agent checks (concurrent with Step 2 — after PR_BASE available)

`PR_BASE` is computed in this step from `git merge-base`, but Step 3a/3b reference it for diff scopes against the PR base. Order: compute `TRUNK` + `PR_BASE` first (Bash block below), then Step 3a (ecosystem) and Step 3b (OSS) `Agent()` / bash `grep` / git-diff calls may run concurrently with the still-executing Step 2 agent spawns — issue them in the same response turn as any remaining Step 2 operations that do not depend on `PR_BASE` (the long-running Agent() polls and `find $RUN_DIR -newer` checks). Do NOT issue Step 3a/3b calls before `PR_BASE` is bound — they would diff against the wrong base.

```bash
TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}') # timeout: 6000  # shared by 3a and 3b

# Shallow-clone guard: git merge-base fails silently on shallow clones, returning empty output
# that looks like "nothing changed" — causes false-negative in security scan and ecosystem check.
IS_SHALLOW=$(git rev-parse --is-shallow-repository 2>/dev/null || echo "unknown")
if [ "$IS_SHALLOW" = "true" ]; then
    echo "⚠ Shallow clone detected — running: git fetch --unshallow to enable merge-base checks"
    git fetch --unshallow 2>/dev/null || echo "⚠ git fetch --unshallow failed — Step 3 checks may be incomplete"
fi
PR_BASE=$(git merge-base HEAD "origin/${TRUNK:-main}" 2>/dev/null || echo "origin/${TRUNK:-main}")
```

### 3a: Ecosystem impact check (for libraries with downstream users)

> **Scope disclosure**: check searches public GitHub code globally. Results may include unrelated projects using same symbol names — treat as signal, not proof. Rate-limited responses (HTTP 429, empty results) may indicate limitation, not absence of usage.

```bash
# Check if changed APIs are used by downstream projects
# Rate-limit guard: if gh api returns HTTP 429, wait 10 seconds and retry once.
# If still rate-limited, log "rate-limited — downstream search may be incomplete" and continue.
CHANGED_EXPORTS=$(gh pr diff $CLEAN_ARGS -- ':(glob)src/**/__init__.py' 2>/dev/null | grep "^[-+]" | grep -v "^[-+][-+]" | grep -oP '\w+' | sort -u) # timeout: 6000
for export in $CHANGED_EXPORTS; do
    echo "=== $export ==="
    gh api "search/code" --field "q=$export language:python" --jq '.items[:5] | .[].repository.full_name' 2>/dev/null # timeout: 30000
    # Note: GitHub code search API is rate-limited (~30 req/min); empty results may indicate rate limiting, not absence of usage
done

# Check if deprecated APIs have migration guides
gh pr diff $CLEAN_ARGS 2>/dev/null | grep -A2 "deprecated" # timeout: 6000
```

### 3b: OSS checks

```bash
OSS_SIGNALS="${TMPDIR:-/tmp}/oss-review-signals-${CLEAN_ARGS}.json"
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || gh release list --limit 1 --json tagName --jq '.[0].tagName' 2>/dev/null || echo "")  # timeout: 6000
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/check_oss_pr_signals.py" --clean-args "$CLEAN_ARGS" --latest-tag "$LATEST_TAG" --output-file "$OSS_SIGNALS"  # timeout: 30000
cat "$OSS_SIGNALS" 2>/dev/null
```

## Step 4: Cross-validate critical/blocking findings

Read `$FOUNDRY_SHARED/cross-validation-protocol.md`. File absent → warn: "cross-validation protocol not found — verify foundry plugin installed (`claude plugin list`); skipping Step 4." Then skip Step 4.

**Independence requirement**: cross-validation must run as separate spawned agent — same type as finding's origin (e.g., `foundry:sw-engineer` verifies `foundry:sw-engineer` critical finding). Do NOT validate in orchestrator context; in-context verification violates independence.

**Spawn cap: max 3 verifier agents.** If critical/blocking findings > 3, group into batches of ≤2 findings per verifier agent; note grouped IDs in the rationale. This prevents runaway spawn cost on large PRs.

Spawn verifier agent per critical/blocking finding (or per batch when capped). Agent reads relevant finding file from `$RUN_DIR` and referenced code. Each verifier must write full rationale to `$RUN_DIR/verify-<finding-id>.md` using the Write tool, then return ONLY: `{"finding_id":"<id>","verdict":"CONFIRMED|REFUTED","rationale":"<one sentence>","file":"$RUN_DIR/verify-<finding-id>.md"}`. REFUTED → downgrade finding severity or remove before consolidation.

## Step 5: Consolidate findings

Before output path, extract:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
DATE=$(date -u +%Y-%m-%d)  # timeout: 5000
```

**IMPORTANT**: expand `$RUN_DIR`, `$REPORT_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, `$DATE`, `$CI_RED`, and `$CI_FAILING_CHECKS` to literal values before inserting into the spawn prompt — same rule as Step 2. Un-expanded variables create wrong paths. **Special attention**: the `## Source Files` footnote below contains a `Glob(... path="<EXPANDED_RUN_DIR>")` invocation — its path must also be expanded to the literal `$RUN_DIR` value, otherwise the consolidator's Glob silently matches nothing.

Spawn **foundry:sw-engineer** consolidator agent with prompt:

> **Task:** Read all finding files in `$RUN_DIR/` (agent files: `foundry--sw-engineer.md`, `foundry--qa-specialist.md`, `foundry--perf-optimizer.md`, `foundry--doc-scribe.md`, `foundry--linting-expert.md`, `foundry--solution-architect.md`, `foundry--challenger.md` if present, and `foundry--codex.md` if present — skip missing). Read `$REVIEW_SKILL_DIR/checklist.md` using Read tool and apply consolidation rules (signal-to-noise filter, annotation completeness, section caps). Read `$_OSS_SHARED/review-section-taxonomy.md` for canonical section header strings and agent-to-section ownership — use Section header column for `###` headers in the report, Owner agent column to attribute findings. Include only findings that passed Step 4 cross-validation (verdict=CONFIRMED or un-cross-validated medium/low). For `foundry--challenger.md`: map severity keys Blockers → critical/high, Concerns → medium, Nitpicks → low when aggregating counts.
>
> **Filtering rules:**
> - Precision gate: only include findings with concrete, actionable location (function, line range, or variable name).
> - Finding density: modules under 100 lines → aim ≤10 total findings.
> - Ranking: within each section, order by impact (blocking > critical > high > medium > low).
> - Codex deduplication: include `foundry--codex.md` unique findings under `### Codex Co-Review`; same file:line raised by both agent and Codex → keep agent version, mark 'also flagged by Codex'.
>
> **Issue alignment (when `issue-*.md` files exist in `$RUN_DIR`):** Include `### Issue Root Cause Alignment` section placed immediately after `### [blocking] Critical`. Per linked issue: state root cause hypothesis, whether PR addresses it (yes / partially / no), whether PR description diverges from issue's stated problem, whether reproduction scenario tested. Any `root cause misalignment` or `scope divergence` finding is at least HIGH severity.
> **PR description drift**: PR descriptions routinely diverge from actual implementation — reviewers request changes mid-review that get implemented but not reflected in PR body. Before flagging `scope divergence`, cross-check PR thread and review comments to determine what was actually agreed upon; description diverges from *thread consensus* (not original description) is the signal worth flagging.
>
> **CI status:** If `CI_RED=true` (literal value expanded by orchestrator): set report header `CI:` field to `failing — [CI_FAILING_CHECKS literal list]`. Otherwise set to `passing` or `pending` per `gh pr checks` output.
>
> **Confidence parsing:** Parse each agent's `confidence` from JSON envelope. Assign `codex` fixed confidence 0.75 (moderate — static analysis, no runtime context).
>
> **Write to:** `$REPORT_DIR/review-report.md` using Write tool.
>
> **Source Files footnote**: after the `## Confidence` block, append `## Source Files` section. Use `Glob(pattern="*.md", path="<EXPANDED_RUN_DIR>")` to list every handover file present (paths relative to repo root, one per line) — lets reviewers locate raw subagent outputs without knowing the run timestamp. Orchestrator MUST substitute `<EXPANDED_RUN_DIR>` with the literal `$RUN_DIR` value (e.g. `.temp/review/2026-05-24T21-16-33Z`) before sending this prompt to the consolidator — spawned agent receives text, not shell context, so an un-expanded `$RUN_DIR` makes the Glob call silently match nothing.
>
> **Return ONLY** one-liner summary: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=$REPORT_DIR/review-report.md`

Main context receives only the one-liner verdict. Proceed with that summary for terminal output.

**Consolidator unavailable fallback** — `Agent` tool deferred/not loaded and consolidator cannot be spawned:
1. Read each `$RUN_DIR/*.md` agent finding file using Read tool before synthesizing — do not rely solely on JSON envelope counts. Synthesize verdict one-liner: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=$REPORT_DIR/review-report.md`
2. Write consolidated report to `$REPORT_DIR/review-report.md` using Write tool. Include all sections and Confidence block
3. Print terminal block using `$FOUNDRY_SHARED/terminal-summaries.md` template — **never silently skip terminal output**

Report format: read `templates/review-report.md` in skill directory and use as output structure.

After parsing confidence: agent < 0.7 → prepend **⚠ LOW CONFIDENCE** to findings section, state gap explicitly. Never drop uncertain findings.

Print terminal block: read `---` header from top of `$REPORT_DIR/review-report.md` (lines 1–12, up to and including closing `---`), append `→ saved to $REPORT_DIR/review-report.md`, print to terminal. Report file already contains the block — no separate prepend step needed.

## Step 6: Delegate implementation follow-up (optional)

After consolidating, identify tasks Codex can implement — not style violations (pre-commit handles those), but meaningful code/doc work grounded in actual implementation.

**Delegate to Codex when you can write accurate, specific brief:**

- Public functions with no docstrings — read implementation first, describe what each does so Codex writes real 6-section docstring
- Missing test coverage for concrete, well-defined behavior — describe exact scenario
- Consistent rename across files — name old/new symbol and reason

**Do not delegate — require human judgment:**

- Architectural issues, logic errors, security vulnerabilities, or behavioural changes
- Any task where you cannot write precise description without guessing

Read `$FOUNDRY_SHARED/codex-delegation.md`. File absent → warn: "codex-delegation criteria not found — verify foundry plugin installed (`claude plugin list`); skipping Step 6 delegation." Then skip Step 6.

Example prompt: `"Add a test for StreamReader.read_chunk() in tests/test_reader.py — the method should raise ValueError when called after close(), currently no test covers this path."`

Print `### Codex Delegation` only when tasks delegated — omit if nothing delegated. Don't rewrite output file.

## Step 7: Reply gate — STOP CHECK

**Confidence block ownership**: `REPLY_MODE=true` → Confidence block written by Step 8 (always last). `REPLY_MODE=false` → Confidence block written here in Step 7b (Step 8 not reached).

`REPLY_MODE=true`: proceed to Step 8 — no Confidence block here.

`REPLY_MODE=false` — do NOT proceed to Step 8. Execute both sub-steps below:

### 7a — Follow-up gate

Check `oss:resolve` availability first — match shepherd availability pattern (Step 8 line ~556). `oss:resolve` is a skill not an agent, so check the installed skill path directly rather than via `check_agent.py`:

```bash
# Cannot use _OSS_SHARED as signal: its bare-path fallback is always non-empty even when oss plugin absent
if ls ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/resolve/SKILL.md >/dev/null 2>&1; then  # timeout: 5000
    RESOLVE_AVAILABLE=true
else
    RESOLVE_AVAILABLE=false
fi
```

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text before or instead of tool call. Map options directly into tool call arguments. AskUserQuestion is capped at 4 options per call — when `$RESOLVE_AVAILABLE=true` the three `/oss:resolve` variants are merged into a single option whose description enumerates the variants; ask one follow-up only when the user picks that merged option. Option set depends on `$RESOLVE_AVAILABLE`:

**When `$RESOLVE_AVAILABLE = true`** (merged option list — 3 options):
- question: "What next?"
- (a) label: `/oss:resolve …` — description: launch oss:resolve in one of three variants (pick which after this question): `/oss:resolve $CLEAN_ARGS` (fix this PR) · `/oss:resolve report` (resolve from full report) · `/oss:resolve $CLEAN_ARGS report` (fix PR + resolve from report)
- (b) label: `walk through findings` — description: go through each finding interactively
- (c) label: `skip` — description: no action

When the user selects (a), invoke a second `AskUserQuestion` to pick the variant — keeps the per-call cap satisfied while preserving all three flows:
- question: "Which /oss:resolve variant?"
- (a) label: `/oss:resolve $CLEAN_ARGS` — description: fix this PR
- (b) label: `/oss:resolve report` — description: resolve from full report
- (c) label: `/oss:resolve $CLEAN_ARGS report` — description: fix PR + resolve from report

**When `$RESOLVE_AVAILABLE = false`** (oss plugin missing or resolve skill absent): omit the resolve option entirely (offering an unavailable command misleads the user):
- question: "What next?"
- (a) label: `walk through findings` — description: go through each finding interactively
- (b) label: `skip` — description: no action

`oss:resolve` has `disable-model-invocation: true` — `Skill()` invocation blocked (exempt from follow-up gate rule in `quality-gates.md`). After both AskUserQuestion calls return:
- Resolve variant chosen: acknowledge selection; present chosen label as command user must run manually (e.g. `Run: /oss:resolve $CLEAN_ARGS`); no `Skill()` call
- `walk through findings` / `skip`: handle inline or stop

### 7b — Confidence block

End with `## Confidence` block per CLAUDE.md output standards.

## Step 8: Draft contributor reply (only when --reply)

`REPLY_MODE` not set → skip.

```bash
# Check oss:shepherd availability — verify installed cache path specifically
# Cannot use _OSS_SHARED as signal: its bare-path fallback is always non-empty even when oss plugin absent
SHEPHERD_AVAILABLE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/check_agent.py" oss shepherd 2>/dev/null)  # timeout: 5000
```

`$SHEPHERD_AVAILABLE` equals `false`: print `⚠ oss:shepherd not available — skipping contributor reply draft. Install the oss plugin to enable --reply.` and skip shepherd spawn.

`$SHEPHERD_AVAILABLE` equals `true`: read `$_OSS_SHARED/shepherd-reply-protocol.md` — apply invocation pattern and terminal summary format.

Spawn with:
- Report path: review output file from Step 5
- PR number and contributor handle: from Step 1 `gh pr view` output
- Output path: `.temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md`

End with `## Confidence` block per CLAUDE.md. Always last thing, regardless of `--reply`.

</workflow>

<calibration>

Scenarios:
1. FIX scope: single bug-fix PR with 1 changed file → scope=FIX, 2 agents skipped: perf-optimizer (scope), solution-architect (scope). Remaining: sw-engineer, qa-specialist, doc-scribe, linting-expert, challenger (unless `--no-challenge`) = 5 agents run (+ Codex if installed).
2. FEATURE scope: new feature PR with API changes → scope=FEATURE, all 7 agents run
3. --reply mode: existing review report + --reply flag → skip to Step 8, no agents spawned

</calibration>

<notes>

- **PR review acceptance criteria — canonical here**: oss:shepherd cross-references these criteria; do not duplicate them in shepherd. Shepherd defers to this file for acceptance thresholds and severity definitions.
- Critical issues always surfaced regardless of scope
- Skip sections with no issues — no padding. Isolated code without git context → skip OSS Checks and Performance Concerns unless evidence of perf issues (nested loops, I/O in tight loops) or OSS concerns (hardcoded secrets, new deps).
- **Signal-to-noise gate**: Function/class ≤50 lines with 1–2 critical/high issues → max 2 additional medium/low findings. Rest as `[nit]` in "Minor Observations". First 3 findings reader sees = most impactful.
- PR mode: check CI first — red → report without full review
- Blocking issues need explicit `[blocking]` prefix
- Follow-up chains:
  - `[blocking]` bugs or regressions → `/develop:fix` (requires `develop` plugin) to reproduce with test and apply targeted fix
  - Structural or quality issues → `/develop:refactor` (requires `develop` plugin) for test-first improvements
  - Security findings in auth/input/deps → run `pip-audit` for dep CVEs; address OWASP issues via `/develop:fix` (requires `develop` plugin)
  - Mechanical issues beyond Step 5 → dispatch internally: `Agent(subagent_type="codex:codex-rescue", prompt="<task>")`
  - Docstrings, type annotations, renames → dispatch `Agent(subagent_type="codex:codex-rescue", prompt="<task description>")` per finding
  - PR feedback for contributor → `--reply` to auto-draft via oss:shepherd, or invoke oss:shepherd manually for custom framing

</notes>
