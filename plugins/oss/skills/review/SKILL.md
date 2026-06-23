---
name: review
description: "Multi-agent code review of GitHub Pull Requests (Python source, documentation (Markdown/RST), and CI/CD config PRs) covering architecture, tests, performance, docs, lint, security, and API design."
when_to_use: |
  TRIGGER when: user provides a GitHub PR number (e.g. `42`, `#42`) and asks to review/audit/check it, or provides a saved review-report path with `--reply` to draft a contributor-facing comment; phrases: "review PR 123", "audit this pull request", "look at PR #42", "draft a reply for this review report".
  SKIP: local file or current git diff review (use `/develop:review` (requires `develop` plugin)); non-Python source PRs without Python files (TypeScript-only, Go-only, Rust-only); standalone issue/discussion thread analysis (use `oss:analyse` (requires `oss` plugin)).
argument-hint: "[PR number|path/to/report.md] [--reply] [--no-challenge] [--codemap] [--semble]"
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
model: sonnet
effort: high
---

<objective>

Spawn specialized sub-agents in parallel. Consolidate findings into structured feedback with severity levels.

NOT for local file review or current git diff — use `/develop:review` (requires `develop` plugin). NOT for non-Python source PRs (TypeScript, Go, Rust, etc.) unless they include Python files — docs-only and CI/CD-only PRs are in scope. NOT for standalone GitHub issue analysis or thread summarization — use `oss:analyse`. **Draft PRs** (GitHub `isDraft=true`) are work-in-progress; pass an explicit PR number anyway if you want the draft reviewed. Note: oss:review performs inline linked-issue analysis (root-cause alignment check in Step 1) as part of PR review — within scope, no conflict.

</objective>

<inputs>

- **$ARGUMENTS**: PR number or report path.
  - Number given (e.g. `42` or `#42`): review PR diff
  - `--reply`: spawn oss:shepherd to draft contributor-facing PR comment. Path ending in `.md` → spawn oss:shepherd from that report, skip new review.
  - **Scope**: Python source only. Non-Python file → state out of scope, suggest tool, no findings.
  - **Local files**: use `/develop:review` (requires `develop` plugin) for local files or current git diff.
  - `--codemap`: strict mode — stop and report if codemap not installed (on by default when installed; use `--no-codemap` to opt out; requires codemap plugin installed)
  - `--semble`: enable semble semantic search companion (off by default; requires semble MCP server configured)
- **--plan handoff not supported** — skill does not accept plan-mode output from `/develop:plan` (requires `develop` plugin).

</inputs>

<constants>

CHALLENGE_ENABLED=true  # set to false via --no-challenge
CODEMAP_ENABLED=auto    # on by default if codemap installed + index found; --no-codemap = off; --codemap = strict (stop if not installed)
SEMBLE_ENABLED=false    # set to true via --semble
> Background agent health monitoring (CLAUDE.md §6) — applies to Step 3 parallel agent spawns
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

Read `$_OSS_SHARED/agent-resolution.md`. Agents: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`, `oss:cicd-steward`. <!-- Inline fallback (if unreadable): all → general-purpose. -->

**Task hygiene**: Call `TaskList` first. Each found task: `completed` if work done · `deleted` if orphaned · `in_progress` if genuinely continuing. TaskCreate each major phase; mark in_progress/completed throughout.

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
| `--no-codemap` | `CODEMAP_FORCE_OFF` | `true` | `false` |
| `--codemap` | `CODEMAP_STRICT` | `true` | `false` |
| `--semble` | `SEMBLE_ENABLED` | `true` | `false` |

`CLEAN_ARGS`: `$ARGUMENTS` with matched flags removed, leading whitespace stripped, leading `#` stripped.

```bash
# Codemap auto-detect: on by default if installed; --no-codemap to opt out; --codemap = strict (stop if not installed)
# loads: detect_codemap.py — consumers: resolve/SKILL.md, review/SKILL.md
_DETECT_CODEMAP="${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/detect_codemap.py"
[ "$CODEMAP_FORCE_OFF" = "true" ] && _DETECT_FLAGS="--force-off" || _DETECT_FLAGS=""
[ "$CODEMAP_STRICT" = "true" ] && _DETECT_FLAGS="$_DETECT_FLAGS --strict"
python "$_DETECT_CODEMAP" --prefix review $_DETECT_FLAGS 2>&1  # timeout: 5000
[ $? -ne 0 ] && exit 1
CODEMAP_ENABLED=$(cat "${TMPDIR:-/tmp}/review-codemap-enabled" 2>/dev/null || echo "false")
# codemap: integrated-via-shared
```

If `SEMBLE_ENABLED=true`: proceed — semble MCP tool availability verified at first use. If `mcp__semble__search` is unavailable when called, it fails with a clear error; do not preemptively exit here.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. Found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--reply\`, \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
DIRECT_PATH_MODE=false
if [[ "$CLEAN_ARGS" == *.md ]]; then
    # Guard: reject plan files — shepherd must not draft replies from plan content
    if [[ "$CLEAN_ARGS" == .plans/* ]] || [[ "$CLEAN_ARGS" == *todo_*.md ]]; then
        echo "Error: plan files cannot be used as review report input. Pass a review report from .reports/review/<timestamp>/review-report.md or a PR number."
        exit 1
    fi
    # Validate file looks like a review report — required markers: ## Summary, verdict:, or APPROVED|NEEDS_WORK|REQUEST_CHANGES in header region.
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
    FOUNDRY_SHARED="plugins/foundry/skills/_shared"
    echo "⚠ Could not resolve FOUNDRY_SHARED via cache lookup — using bare fallback path '$FOUNDRY_SHARED'; foundry plugin may be absent — Steps 5/7/consolidator will degrade (per-file guards still fire)"
fi
```

```bash
if [ "$DIRECT_PATH_MODE" = "false" ]; then
    if [ -z "$CLEAN_ARGS" ] || ! [[ "$CLEAN_ARGS" =~ ^[0-9]+$ ]]; then
        echo "Error: PR number required. Usage: /oss:review <PR number> [--reply] [--no-challenge]"
        exit 1
    fi
    # Run all four in parallel:
    CHANGED_FILES=$(gh pr diff $CLEAN_ARGS --name-only 2>/dev/null)  # cache for reuse in codemap block # timeout: 6000
    gh pr view $CLEAN_ARGS                                            # PR description and metadata       # timeout: 6000
    gh pr checks $CLEAN_ARGS                                          # CI status                        # timeout: 15000
    gh pr view $CLEAN_ARGS --json reviews,labels,milestone            # timeout: 6000
fi
```

**CI STATUS** (PR mode only): parse `gh pr checks` output → extract failing required check names into `CI_FAILING_CHECKS`. Any failing: set `CI_RED=true`, print `⚠ CI is red: [list failing check names] — review proceeds; status noted in report header.` Continue to Steps 2–8 regardless. Expand `$CI_RED` and `$CI_FAILING_CHECKS` to literal values in the consolidator spawn prompt (Step 5).

### File scope detection

<!-- loads: modes/scope-detection.md -->
Read `$REVIEW_SKILL_DIR/modes/scope-detection.md` and execute its bash blocks inside the `DIRECT_PATH_MODE = "false"` guard. Sets `PY_FILES`, `DOC_FILES`, `CICD_FILES`, `CICD_ONLY_MODE`, `DOCS_ONLY_MODE`, `DOCS_CICD_MODE`; persists flags to `${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}` for reload in Step 2.

### Scope pre-check

**CI/CD-only mode** (`CICD_ONLY_MODE=true`): no `.py`/`.md`/`.rst`. Spawn: `oss:cicd-steward` + Agent 1 + Agent 7 (if `CHALLENGE_ENABLED=true`) + Codex; skip Agents 2–6. Proceed directly to agent launch.

**Docs-only mode** (`DOCS_ONLY_MODE=true`): no `.py`. **foundry:doc-scribe (Agent 4) leads** — Agent 1 explicitly skipped (NOT for docs clause); linked-issue spawns also skip Agent 1. Spawn: Agent 4 + Agent 7 (if `CHALLENGE_ENABLED=true`) + Codex; skip Agents 1, 2, 3, 5, 6. Proceed directly to agent launch.

**Docs + CI/CD mode** (`DOCS_CICD_MODE=true`): no Python. Spawn: `oss:cicd-steward` (Agent 8) + `foundry:doc-scribe` (Agent 4) + Agent 7 (if `CHALLENGE_ENABLED=true`); skip Agents 1, 2, 3, 5, 6. Proceed directly to agent launch.

Before spawning agents (Python mode only — all three mode flags false), classify diff:

- Count files changed, lines added/removed, new classes/modules
- Classify: **FIX** (\<3 files, \<50 lines), **REFACTOR** (internal restructure, no new public API), **FEATURE** (new public API or module), **CHORE** (deps, config, tooling — no logic changes), or **MIXED**
- **Short-diff multi-concern refactors**: FIX heuristic classifies by diff size, not intent. Override FIX → REFACTOR when PR labels include `perf`, `performance`, `optimization`, `refactor`, `architecture`, `cleanup` OR commit message keywords `refactor:`, `perf:`, `rewrite` OR diff touches different modules. Detect via `gh pr view --json labels,title`. Small-diff perf refactors are exactly the case FIX would silently mishandle.
- **Complexity smell**: 8+ files changed OR `PY_LOC_DELTA >400` → note in report header

H6 — assign `SCOPE` shell variable so the `EXPECTED` array (Step 2 health monitor) can branch on it without comparing to an undefined value:

```bash
# Count Python files + total Python LOC delta for the classification heuristic
PY_FILE_COUNT=$(echo "$PY_FILES" | grep -c . 2>/dev/null || echo 0)
# PY_LOC_DELTA = total churn (added + deleted lines), NOT net delta.
# Pure rename refactors produce PY_LOC_DELTA>0 even when net change is 0; label/keyword override above is the intended mitigation.
PY_LOC_DELTA=$(gh pr diff $CLEAN_ARGS 2>/dev/null | grep -E '^[+-][^+-]' | grep -vE '^[+-]{3}' | wc -l | tr -d ' ')  # timeout: 6000

# Detect new public API surface: added lines in src/**/__init__.py
NEW_API_LINES=$(gh pr diff $CLEAN_ARGS -- ':(glob)src/**/__init__.py' 2>/dev/null | grep -c '^+[^+]' || echo 0)  # timeout: 6000

# Detect pure config/deps changes (no .py logic changes)
NON_CONFIG_PY=$(echo "$PY_FILES" | grep -vE '(pyproject\.toml|setup\.cfg|setup\.py|requirements.*\.txt|conftest\.py)' || true)

SCOPE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/classify_pr_scope.py" --py-files "$PY_FILE_COUNT" --loc-delta "$PY_LOC_DELTA" --new-api-lines "$NEW_API_LINES" --labels "$PR_LABELS" --title "$PR_TITLE" 2>/dev/null)  # timeout: 10000
echo "→ SCOPE=$SCOPE (py_files=$PY_FILE_COUNT, py_loc=$PY_LOC_DELTA, new_api=$NEW_API_LINES)"

# Persist SCOPE and CHORE_DEPS flags — Step 2 EXPECTED_FILE construction is in a separate bash block.
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
- CHORE scope → spawn Agents 1, 4, 5, 7 (challenger, if `CHALLENGE_ENABLED=true`), Codex (if available); skip Agents 2, 3, 6
  - **CHORE + dependency files exception**: diff includes `requirements*.txt`, `pyproject.toml`, `package*.json`, `Pipfile`, `poetry.lock`, `setup.cfg`, `*.lock` → keep Agent 2 (qa-specialist) for OWASP/CVE checks. Detect via `CHORE_DEPS` flag above. CHORE + non-deps → skip qa-specialist.

### Structural context + review pre-flight (codemap — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`** — sets `codemap_available=false` for downstream agent prompts; agents fall back to file reads.

```bash
codemap_available=false
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
# $RUN_DIR not yet created at Step 1 (happens in Step 2); stage to TMPDIR, Step 2 copies into $RUN_DIR/codemap-context.md.
CODEMAP_CONTEXT_STAGE="${TMPDIR:-/tmp}/oss-review-codemap-context-${CLEAN_ARGS}.md"
if [ "$CODEMAP_ENABLED" = "true" ] && command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    codemap_available=true
    CHANGED_MODS=$(echo "$CHANGED_FILES" | grep '\.py$' | sed 's|^src/||;s|\.py$||;s|/|.|g' | grep -v '__init__$')
    {
        echo "## Structural Context (codemap)"
        echo
        echo "### Global blast-radius baseline"
        scan-query --timeout 5 central --top 5 2>/dev/null
        echo
        for mod in $CHANGED_MODS; do
            echo "### Module: $mod"
            scan-query --timeout 5 rdeps        "$mod"          2>/dev/null  # importer count → high/moderate/low risk tier
            scan-query --timeout 5 fn-blast     "$mod"          2>/dev/null  # caller impact (v3)
            scan-query --timeout 5 mock-rdeps   "$mod"          2>/dev/null  # mock test coverage (v4.1)
            scan-query --timeout 5 uncovered    --top 20 "$mod" 2>/dev/null  # test gaps (v4.2)
            scan-query --timeout 5 xrefs --broken        "$mod" 2>/dev/null  # stale doc refs (v4.5)
            scan-query --timeout 5 undocumented "$mod" 2>/dev/null  # doc coverage (v4.4)
            echo
        done
    } > "$CODEMAP_CONTEXT_STAGE"
fi
echo "$codemap_available"      > "${TMPDIR:-/tmp}/oss-review-codemap-available-${CLEAN_ARGS}"
echo "$CODEMAP_CONTEXT_STAGE"  > "${TMPDIR:-/tmp}/oss-review-codemap-context-stage-${CLEAN_ARGS}"
```

`codemap_available=true`: Step 2 copies `$CODEMAP_CONTEXT_STAGE` to `$RUN_DIR/codemap-context.md` after `$RUN_DIR` is created. Every dimension-agent spawn prompt in Step 2 must then include a literal block (substituted from `$RUN_DIR/codemap-context.md`):

```text
## Structural Context (codemap, codemap_available=true)
<content of $RUN_DIR/codemap-context.md>

Read this section first. For symbols listed in `uncovered`/`mock-rdeps`/`undocumented`/`xrefs --broken`/`fn-blast`, trust the codemap output; skip redundant Grep/Read on the same data. Fall back to file reads only when codemap output is empty for a symbol you need or when verifying a specific finding.
```

`codemap_available=false`: omit the block; agents proceed with current file-read behaviour.

Tier annotation for Agent 1 (sw-engineer) only: label each module's `imported_by` count — **high risk** (>20), **moderate** (5–20), **low** (<5) — for blast-radius reference.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt: "If `mcp__semble__search` available and any codemap result non-exhaustive or codemap absent: call `mcp__semble__search(query='<module> import', repo=<git_root>, top_k=20)` per module; stop when two consecutive queries return no new importers; merge with codemap; skip if all results exhaustive."

### Linked issue analysis (PR mode only)

Parse PR body (`gh pr view $CLEAN_ARGS`) for issue refs (`Closes #N`, `Fixes #N`, `Resolves #N`, `refs #N` — case-insensitive). Extract to `ISSUE_NUMS`. Cap 3.

`ISSUE_NUMS` non-empty AND `DOCS_CICD_MODE != true`: spawn one **foundry:sw-engineer** per issue in Step 2 alongside Codex — all launch simultaneously. Each issue agent: fetch `gh issue view <N> --json title,body,comments,state,labels` + `gh issue view <N> --comments`; produce `/oss:analyse`-style output (Summary, Root Cause Hypotheses top 3, Code Evidence); write full analysis to `$RUN_DIR/issue-<N>.md`; return only `{"status":"done","issue":N,"root_cause":"<one-line>","file":"$RUN_DIR/issue-<N>.md","confidence":0.N}`.

`ISSUE_NUMS` empty → skip issue checks downstream.

### Direct report fast-path

`DIRECT_PATH_MODE=true`:

- `REPLY_MODE=false` → use `AskUserQuestion`: "A report path was passed without `--reply`. Did you mean `/oss:review <path.md> --reply`?" Options: (a) "Yes — continue with `--reply` mode" → set `REPLY_MODE=true`; then re-check: `[ ! -f "$REVIEW_FILE" ] && echo "Error: review file not found at $REVIEW_FILE" && exit 1`; proceed; (b) "No — review a PR instead" → print usage hint (`/oss:review <N> | path/to/dir`) and stop.
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

**File-based handoff**: read `$FOUNDRY_SHARED/file-handoff-protocol.md`. File absent → warn and continue without it.

**IMPORTANT**: Replace `$RUN_DIR`, `$REPORT_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, and `$DATE` with actual literal computed values in every Agent spawn prompt. Do NOT pass as shell variables — agents receive text, not shell context.

Check Codex availability:

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && CODEX_AVAILABLE=1 && echo "codex (openai-codex) available" || { CODEX_AVAILABLE=0; echo "⚠ codex (openai-codex) not found — skipping co-review"; } # timeout: 15000
```

<!-- loads: agent-prompts.md -->
Read `$REVIEW_SKILL_DIR/templates/agent-prompts.md`. Substitute `<RUN_DIR>` → `$RUN_DIR`, `<REVIEW_SKILL_DIR>` → `$REVIEW_SKILL_DIR` before using content in spawn prompts. All placeholders (`<RUN_DIR>`, `<REVIEW_SKILL_DIR>`) must be expanded to literal values — agents receive text, not shell variables.

**Codemap context propagation**: rehydrate `codemap_available` from Step 1 persist file, copy staged context into `$RUN_DIR/codemap-context.md`, substitute into every dimension-agent spawn prompt per the rules in the Structural-context block above. Block omitted when `codemap_available=false`.

```bash
_PR_TAG=$(cat "${TMPDIR:-/tmp}/oss-review-pr-tag" 2>/dev/null || echo "$CLEAN_ARGS")
codemap_available=$(cat "${TMPDIR:-/tmp}/oss-review-codemap-available-${_PR_TAG}" 2>/dev/null || echo "false")
CODEMAP_CONTEXT_STAGE=$(cat "${TMPDIR:-/tmp}/oss-review-codemap-context-stage-${_PR_TAG}" 2>/dev/null || echo "")
if [ "$codemap_available" = "true" ] && [ -n "$CODEMAP_CONTEXT_STAGE" ] && [ -f "$CODEMAP_CONTEXT_STAGE" ]; then
    cp "$CODEMAP_CONTEXT_STAGE" "$RUN_DIR/codemap-context.md"
fi
```

**Health monitoring** (CLAUDE.md §6): Create checkpoint BEFORE spawning agents:

```bash
REVIEW_CHECKPOINT="${TMPDIR:-/tmp}/review-check-$(date +%s)"
touch "$REVIEW_CHECKPOINT"
# Persist checkpoint path — the poll block (separate bash invocation) reads it back.
echo "$REVIEW_CHECKPOINT" > "${TMPDIR:-/tmp}/oss-review-checkpoint"
```

Launch Codex, issue agents, and all review agents in one message batch — zero hold between Codex and review agents. All `Agent()` calls issue in a SINGLE response turn — substitute `$RUN_DIR` (literal) and issue numbers before spawning. Agent lineup: `codex:codex-rescue` (if `CODEX_AVAILABLE=1`) · per-issue `foundry:sw-engineer` (skip if `DOCS_CICD_MODE=true`) · Agents 1–8 per scope/mode rules above.

Poll for expected output files per `$MONITOR_INTERVAL` / `$HARD_CUTOFF` until all present or each hits hard cutoff.

Write expected paths to file (Bash arrays don't persist across tool invocations):

```bash
# Restore mode flags + SCOPE persisted in Step 1 (each SKILL.md bash block runs in a fresh shell).
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
{ [ "$CICD_ONLY_MODE" = "true" ] || [ "$DOCS_CICD_MODE" = "true" ]; } && echo "$RUN_DIR/oss--cicd-steward.md" >>"$EXPECTED_FILE"
[ "$DOCS_CICD_MODE" != "true" ] && [ "$DOCS_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--sw-engineer.md" >>"$EXPECTED_FILE"
{ [ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && { [ "$SCOPE" != "CHORE" ] || [ "$CHORE_DEPS" = "true" ]; }; } && echo "$RUN_DIR/foundry--qa-specialist.md" >>"$EXPECTED_FILE"
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && [ "$SCOPE" != "CHORE" ] && [ "$SCOPE" != "FIX" ] && echo "$RUN_DIR/foundry--perf-optimizer.md" >>"$EXPECTED_FILE"
[ "$CICD_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--doc-scribe.md" >>"$EXPECTED_FILE"
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && echo "$RUN_DIR/foundry--linting-expert.md" >>"$EXPECTED_FILE"
[ "$CHALLENGE_ENABLED" = "true" ] && echo "$RUN_DIR/foundry--challenger.md" >>"$EXPECTED_FILE"
[ "$DOCS_ONLY_MODE" = "false" ] && [ "$DOCS_CICD_MODE" = "false" ] && [ "$CICD_ONLY_MODE" != "true" ] && [ "$SCOPE" != "FIX" ] && [ "$SCOPE" != "CHORE" ] && echo "$RUN_DIR/foundry--solution-architect.md" >>"$EXPECTED_FILE"
```

Later poll blocks read paths back via `while read -r path; do [ -f "$path" ] || PENDING=1; done <"$EXPECTED_FILE"` — no in-memory array required.

Every `$MONITOR_INTERVAL` seconds, in the poll bash block, rehydrate the checkpoint path first: `REVIEW_CHECKPOINT=$(cat "${TMPDIR:-/tmp}/oss-review-checkpoint" 2>/dev/null)` then `find $RUN_DIR -newer "$REVIEW_CHECKPOINT" -type f | wc -l` — non-zero = agents alive (refresh checkpoint: `touch "$REVIEW_CHECKPOINT"`); zero since last refresh for `$HARD_CUTOFF` seconds = stalled. One `$EXTENSION` if `tail -20` output file explains delay; second stall = cutoff. On timeout: read partial results from stalled agent's file; surface with ⏱ in report. Never omit timed-out agents.

After all outputs collected (or timed out):

```bash
ls "$RUN_DIR/"*.md 2>/dev/null || echo "⚠ No agent output files found in $RUN_DIR — check that $RUN_DIR was expanded correctly in spawn prompts"
```

## Step 3: Post-agent checks (concurrent with Step 2 — after PR_BASE available)

Step 3a/3b may run concurrently with still-executing Step 2 agents — issue in same response turn as final Step 2 polls. Do NOT issue before `PR_BASE` is bound.

```bash
TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}') # timeout: 6000

# Shallow-clone guard: git merge-base fails silently on shallow clones.
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

**Independence requirement**: cross-validation must run as separate spawned agent — same type as finding's origin. Do NOT validate in orchestrator context.

**Spawn cap: max 3 verifier agents.** Critical/blocking findings > 3 → group into batches of ≤2 findings per verifier; note grouped IDs in rationale.

Spawn verifier agent per critical/blocking finding (or per batch when capped). Agent reads relevant finding file from `$RUN_DIR` and referenced code. Each verifier must write full rationale to `$RUN_DIR/verify-<finding-id>.md` using the Write tool, then return ONLY: `{"finding_id":"<id>","verdict":"CONFIRMED|REFUTED","rationale":"<one sentence>","file":"$RUN_DIR/verify-<finding-id>.md"}`. REFUTED → downgrade finding severity or remove before consolidation.

## Step 5: Consolidate findings

Before output path, extract:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
DATE=$(date -u +%Y-%m-%d)  # timeout: 5000
```

**IMPORTANT**: expand `$RUN_DIR`, `$REPORT_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, `$DATE`, `$CI_RED`, and `$CI_FAILING_CHECKS` to literal values before inserting into the spawn prompt. Un-expanded variables create wrong paths. The `## Source Files` footnote `Glob(... path="<EXPANDED_RUN_DIR>")` path must also be expanded to the literal `$RUN_DIR` value.

Spawn **foundry:sw-engineer** consolidator agent with prompt:

<!-- loads: consolidator-prompt.md -->
Read `$REVIEW_SKILL_DIR/templates/consolidator-prompt.md`. Substitute `<RUN_DIR>`, `<REPORT_DIR>`, `<REVIEW_SKILL_DIR>`, `<_OSS_SHARED>`, `<DATE>`, `<CHANGED_FILES>`, `<SCOPE>`, `<CI_FAILING_CHECKS>` with literal expanded values. Spawn: `Agent(subagent_type="foundry:sw-engineer", prompt=<substituted consolidator-prompt.md content>)`

Main context receives only the one-liner verdict. **Consolidator unavailable fallback** — `Agent` tool deferred/not loaded:
Print: `⛔ BLOCKED — Agent tool not loaded; consolidator cannot run. Re-invoke /oss:review to retry. If persistent, run /foundry:setup (requires foundry plugin) to verify session config.`
Do NOT read agent finding files inline — floods main context (~16–32K tokens per run), produces unreliable synthesis.

After parsing confidence: agent < 0.7 → prepend **⚠ LOW CONFIDENCE** to findings section, state gap explicitly. Never drop uncertain findings.

Print terminal block: read the `---` header from top of `$REPORT_DIR/review-report.md` (all fields from opening `---` up to and including closing `---` — `Title:`, `Date:`, `PR Type:`, `Scope:`, `Focus:`, `Agents:`, `CI:`, `Outcome:`, `Summary:`, `Confidence:`, `Next steps:`, `Path:`), append `→ saved to $REPORT_DIR/review-report.md`, print to terminal.

**This `---` block IS the reply header — hard rule** (universal: quality-gates.md §Report File Format): print it verbatim as the FIRST content of the reply, wrapped in a ` ```text ` … ` ``` ` fenced code block so the literal `---` delimiters survive markdown rendering — without the fence a chat renderer parses the leading `---` as YAML frontmatter and the closing `---` flush under `Path:` as a setext heading underline, mangling the header into a single `---Title:` line with no closing fence. The fenced block still IS the reply header — do NOT wrap the reply in a `╔═╗` Re:Anchor box (communication.md exempts quality-gates `---` report headers — the box would shadow the YAML). Never emit both a box header and this `---` block. Print all 12 fields from the file verbatim — do NOT substitute the `·`-separated one-line fallback; that fallback is permitted ONLY when the `$REPORT_DIR/review-report.md` read genuinely fails (file absent/unreadable). If the read fails, state `⚠ could not read report header — verify $REPORT_DIR` before the fallback line rather than silently degrading.

## Step 6: Delegate implementation follow-up (optional)

Identify tasks Codex can implement — meaningful code/doc work grounded in actual implementation.

**Delegate**: public functions with no docstrings (read impl first, describe so Codex writes real 6-section docstring) · missing test coverage for concrete well-defined behavior · consistent rename across files. **Do not delegate**: architectural issues, logic errors, security vulns, or any task requiring human judgment.

Read `$FOUNDRY_SHARED/codex-delegation.md`. File absent → warn: "codex-delegation criteria not found — verify foundry plugin installed (`claude plugin list`); skipping Step 6 delegation." Then skip Step 6.

Print `### Codex Delegation` only when tasks delegated — omit otherwise. Don't rewrite output file.

## Step 7: Reply gate — STOP CHECK

**Confidence block ownership**: `REPLY_MODE=true` → block in Step 8. `REPLY_MODE=false` → block in Step 7b.

`REPLY_MODE=true`: proceed to Step 8 — no Confidence block here. `REPLY_MODE=false` — do NOT proceed to Step 8. Execute both sub-steps below:

### 7a — Follow-up gate

Check `oss:resolve` availability:

```bash
RESOLVE_AVAILABLE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/check_agent.py" oss resolve 2>/dev/null || echo "false")  # timeout: 5000
# check_agent.py checks ~/.claude/plugins/cache/borda-ai-rig/oss/*/agents/resolve.md and .claude/agents/resolve.md
# Note: resolve is a skill not an agent — check_agent.py returns false for skills; check skill path directly:
if [ "$RESOLVE_AVAILABLE" = "false" ]; then
    ls "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/skills/resolve/SKILL.md" >/dev/null 2>&1 && RESOLVE_AVAILABLE=true || RESOLVE_AVAILABLE=false
fi
```

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text. Option set depends on `$RESOLVE_AVAILABLE`:

**When `$RESOLVE_AVAILABLE = true`** (single call — all options in one):
- question: "What next?"
- (a) label: `/oss:resolve $CLEAN_ARGS` — description: fix this PR (implement review findings, resolve conflicts, push)
- (b) label: `/oss:resolve report` — description: resolve from full review report only (no GitHub re-fetch)
- (c) label: `/oss:resolve $CLEAN_ARGS report` — description: fix PR + resolve from full review report in one pass
- (d) label: `walk through findings` — description: go through each finding interactively
- (e) label: `skip` — description: no action

**When `$RESOLVE_AVAILABLE = false`**: omit the resolve options:
- question: "What next?"
- (a) label: `walk through findings` — description: go through each finding interactively
- (b) label: `skip` — description: no action

`oss:resolve` has `disable-model-invocation: true` — `Skill()` invocation blocked. After AskUserQuestion returns:
- Resolve variant chosen (a/b/c when available): present chosen label as command user must run manually (e.g. `Run: /oss:resolve $CLEAN_ARGS`); no `Skill()` call
- `walk through findings` / `skip`: handle inline or stop

### 7b — Confidence block

End with `## Confidence` block per CLAUDE.md output standards.

<!-- Steps 5–7 defined in Step 5 (consolidate), Step 6 (Codex delegation), Step 7 (reply gate) blocks above — numbered sequentially from Step 1; Step 4 (cross-validate) precedes them; no gap: 4→5→6→7→8 -->

## Step 8: Draft contributor reply (only when --reply)

`REPLY_MODE` not set → skip.

```bash
# Check oss:shepherd availability
SHEPHERD_AVAILABLE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/check_agent.py" oss shepherd 2>/dev/null)  # timeout: 5000
```

`false`: print `⚠ oss:shepherd not available — skipping contributor reply draft. Install the oss plugin to enable --reply.` and skip. `true`: read `$_OSS_SHARED/shepherd-reply-protocol.md` — apply invocation pattern and terminal summary format.

Spawn with:
- Report path: review output file from Step 5
- PR number and contributor handle: from Step 1 `gh pr view` output
- Output path: `.temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md`

**Part 2 compliance gate** (after shepherd returns — do NOT trust the return line alone):

```bash
# fires only when review findings reference file:line — true LGTM has no such findings
REPLY_OUT=".temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md"  # timeout: 5000
grep -qE '^\| *Importance *\| *Confidence *\| *File *\| *Line' "$REPLY_OUT" && echo "PART2_PRESENT=true" || echo "PART2_PRESENT=false"
```

`PART2_PRESENT=false` while the Step 5 report has ≥1 file:line finding → reply is non-compliant (findings folded into prose). Re-spawn `oss:shepherd` once with the same inputs plus: `"Part 2 table is MANDATORY — every file:line finding from the report must be its own row in the | Importance | Confidence | File | Line | Comment | table; do not fold file:line findings into Part 1 prose."` Re-check; if still absent, surface `⚠ Part 2 table missing — findings remain in prose` in the terminal summary.

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
