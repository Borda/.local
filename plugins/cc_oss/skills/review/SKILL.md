---
name: review
description: "Multi-agent code review of GitHub Pull Requests (Python source, documentation (Markdown/RST), and CI/CD config PRs) covering architecture, tests, performance, docs, lint, security, and API design. TRIGGER when: user provides a GitHub PR number (e.g. 42, #42) and asks to review/audit/check it, or provides a saved review-report path with --reply to draft a contributor-facing comment; phrases: 'review PR 123', 'audit this pull request', 'look at PR #42', 'draft a reply for this review report'. SKIP: local file or current git diff review (use /develop:review (requires 'develop' plugin)); non-Python source PRs without Python files (TypeScript-only, Go-only, Rust-only); standalone issue/discussion thread analysis (use /oss:analyse)."
argument-hint: "[PR number|path/to/report.md] [--reply] [--no-challenge] [--codemap] [--semble] [--worktree] [--full] [--keep \"<items>\"]"
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion, EnterWorktree, ExitWorktree
model: sonnet
effort: high
---

<objective>

Spawn specialized sub-agents in parallel. Consolidate findings into structured feedback with severity levels.

NOT for local file review or current git diff — use `/develop:review` (requires `develop` plugin). NOT for non-Python source PRs (TypeScript, Go, Rust, etc.) unless they include Python files — docs-only and CI/CD-only PRs in scope. NOT for standalone GitHub issue analysis or thread summarization — use `oss:analyse`. **Draft PRs** (GitHub `isDraft=true`) are work-in-progress; pass explicit PR number anyway to review draft. Note: oss:review performs inline linked-issue analysis (root-cause alignment check in Step 1) as part of PR review — within scope, no conflict.

</objective>

<inputs>

- **$ARGUMENTS**: PR number or report path.
  - Number given (e.g. `42` or `#42`): review PR diff
  - `--reply`: spawn oss:shepherd to draft contributor-facing PR comment. Path ending in `.md` → spawn oss:shepherd from that report, skip new review.
  - **Scope**: Python source only. Non-Python file → state out of scope, suggest tool, no findings.
  - **Local files**: use `/develop:review` (requires `develop` plugin) for local files or current git diff.
  - `--codemap`: strict mode — stop, report if codemap not installed (on by default when installed; use `--no-codemap` to opt out; requires codemap plugin installed)
  - `--semble`: enable semble semantic search companion (off by default; requires semble MCP server configured)
  - `--full`: run **every** dimension the scope preselected, instead of only the `FANOUT_MAX` most relevant of them. Never widens the preselection itself — a dimension the scope ruled out stays out. **Not free**: each extra agent costs ~120,851 tok of fixed overhead however little work it does. Default stays capped; pass this when depth matters more than cost.
- **--plan handoff not supported** — skill doesn't accept plan-mode output from `/develop:plan` (requires `develop` plugin).

</inputs>

<constants>

FANOUT_MAX=4            # default: top-N most relevant of the scope-preselected dimensions
                        # --full runs ALL scope-preselected dimensions instead — no numeric cap
AGENT_CALL_BUDGET=55    # target tool-calls per agent; past ~60 they stall without returning an envelope
CHALLENGE_ENABLED=true  # set to false via --no-challenge
CODEMAP_ENABLED=auto    # on by default if codemap installed + index found; --no-codemap = off; --codemap = strict (stop if not installed)
SEMBLE_ENABLED=false    # set to true via --semble
> Background agent health monitoring (CLAUDE.md §6) — applies to Step 3 parallel agent spawns
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay

</constants>

<compaction>

Key boundary: end of Step 2 — parallel review-agent fan-out outputs collected, before Step 5 consolidation.
Second boundary: end of Step 5 — consolidated report written, before Step 8 --reply.
Preserve at boundary 1: RUN_DIR, REPORT_DIR, PR# (CLEAN_ARGS), per-agent finding file paths.
Preserve at boundary 2: final report path, PR#, reply-mode flag.

</compaction>

<workflow>

<!-- Agent resolution: see _OSS_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# loads: oss-shared-resolver.md
# loads: review-section-taxonomy.md
# loads: compaction-contract.md
# cold-start fallback (sets $_OSS_SHARED)
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
# --reply needs $_OSS_SHARED (Step8 shepherd-reply-protocol.md); else degrades gracefully
if [ ! -d "$_OSS_SHARED" ]; then
    if [[ "$ARGUMENTS" == *--reply* ]]; then
        echo "⛔ _OSS_SHARED resolved to '$_OSS_SHARED' but dir absent — --reply requires oss plugin shared dir; verify oss plugin installed"
        exit 1
    else
        echo "⚠ _OSS_SHARED resolved to '$_OSS_SHARED' but dir absent — continuing with degraded functionality (oss skill-specific shared helpers unavailable; --reply mode will not work in this run)"
    fi
fi
echo "$_OSS_SHARED" > "${TMPDIR:-/tmp}/review-oss-shared-${CSID}"  # cross-block (Check 41)
[ -d "$_OSS_SHARED" ] && cat "$_OSS_SHARED/agent-resolution.md"  # timeout: 5000

REVIEW_SKILL_DIR="${CLAUDE_PLUGIN_ROOT:-}/skills/review"
[ -d "$REVIEW_SKILL_DIR" ] || REVIEW_SKILL_DIR=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/review 2>/dev/null | head -1)
[ -z "$REVIEW_SKILL_DIR" ] && REVIEW_SKILL_DIR="plugins/cc_oss/skills/review"
echo "$REVIEW_SKILL_DIR" > "${TMPDIR:-/tmp}/review-skill-dir-${CSID}"  # cross-block (Check 41)
```

Agents: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`, `oss:cicd-steward`. <!-- Inline fallback (if unreadable): all → general-purpose. -->

**`REVIEW_SKILL_DIR`** (resolved above) — substitute into every Agent spawn prompt and every `cat "$REVIEW_SKILL_DIR/..."` call below.

**Task hygiene**: Call `TaskList` first. Each found task: `completed` if work done · `deleted` if orphaned · `in_progress` if genuinely continuing. TaskCreate each major phase; mark in_progress/completed throughout.

Create these tasks **before** starting Step 1 (in order, all at once):

- **"Step 1: Scope and context detection"** — TaskUpdate(in_progress) at Step 1 start; TaskUpdate(completed) when all scope vars set (SCOPE, REPLY_MODE, mode flags)
- **"Step 2: Agent launch"** — TaskUpdate(in_progress) before spawning agents; TaskUpdate(completed) when all Agent() calls issued
- **"Step 3: Post-agent checks"** — TaskUpdate(in_progress) before post-agent checks run; TaskUpdate(completed) when all agent output files collected (or timed out); per task-lifecycle.md: TaskUpdate BEFORE long output blocks
- **"Step 4: Cross-validate critical findings"** — TaskUpdate(in_progress) before spawning verifier agents; TaskUpdate(completed) when all verdicts received; **TaskUpdate(deleted) when no critical/blocking findings exist after Step 3** (always created upfront)
- **"Step 5: Consolidate findings"** — TaskUpdate(in_progress) before spawning consolidator; TaskUpdate(completed) when consolidator returns its one-liner (Write to `review-report.md` done) — **do NOT mark completed for the terminal print, that's a separate task below**
- **"Step 5b: Print report header"** — created **blockedBy** "Step 5: Consolidate findings"; TaskUpdate(in_progress) immediately after the consolidator's one-liner returns; TaskUpdate(completed) only once the `---` header table has actually appeared in this response's output (not merely queued/intended). The consolidator's one-liner (`verdict=... | findings=N | file=<path>`) is NOT this table — it is a routing signal for the orchestrator, never a substitute for reading `$REPORT_DIR/review-report.md` and printing its header. **Step 7a's `AskUserQuestion` must not fire while this task is `pending`/`in_progress`** — a real skip incident showed the hard-enforced tool call (`AskUserQuestion`) firing correctly while this prose-only print step got silently dropped; the dedicated task exists specifically to make the print step as trackable/enforceable as the tool calls around it.
- **"Step 8: Contributor reply draft"** — create only when REPLY_MODE=true, before spawning oss:shepherd; TaskUpdate(in_progress) immediately after creation; TaskUpdate(completed) when shepherd output written

## Step 0: Parse flags and content-type pre-classification

Parse `$ARGUMENTS` flags first (via `bin/parse-skill-flags.py`, C5) — this sets `CLEAN_ARGS`, the mode flags, and `DIRECT_PATH_MODE` **before** any step below references them (the pre-classification and Step 1 both read them):

| Flag | Variable | Present | Absent |
| --- | --- | --- | --- |
| `--reply` | `REPLY_MODE` | `true` | `false` |
| `--no-challenge` | `CHALLENGE_ENABLED` | `false` | `true` |
| `--no-codemap` | `CODEMAP_FORCE_OFF` | `true` | `false` |
| `--codemap` | `CODEMAP_STRICT` | `true` | `false` |
| `--semble` | `SEMBLE_ENABLED` | `true` | `false` |
| `--worktree` | `WT_ENABLED` | `true` | `false` |
| `--full` | `FANOUT_CAP` | `0` — no cap, all preselected | `4` (`FANOUT_MAX`) |
| `--keep "<items>"` | `KEEP_ITEMS` | value string | `""` |

`CLEAN_ARGS`: `$ARGUMENTS` with matched flags removed (including `--keep "<items>"` and its quoted value), leading whitespace stripped, leading `#` stripped.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# parses --reply/--no-challenge/--semble/--worktree/--keep; codemap flags detected-only, re-derived independently below
# shared flag/--keep parser (C5; also resolve/analyse SKILL.md)
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/parse-skill-flags.py" --flags reply,no-challenge,no-codemap,codemap,semble,worktree,full "$ARGUMENTS")"  # timeout: 5000
FANOUT_CAP=4; [ "$FLAG_FULL" = "true" ] && FANOUT_CAP=0  # 0 = no cap: all scope-preselected dimensions
REPLY_MODE="$FLAG_REPLY"
SEMBLE_ENABLED="$FLAG_SEMBLE"
WT_ENABLED="$FLAG_WORKTREE"
[ "$FLAG_NO_CHALLENGE" = "true" ] && CHALLENGE_ENABLED=false || CHALLENGE_ENABLED=true
# stale contract, crashed prior run (compaction-contract.md §Lifecycle)
rm -f .temp/state/skill-contract.md  # timeout: 5000

# flags sentinel; CHALLENGE_ENABLED kept separate — scope-detection.md:34-38 truncates this file
{
    echo "REPLY_MODE=$REPLY_MODE"
    echo "WT_ENABLED=$WT_ENABLED"
    echo "SEMBLE_ENABLED=$SEMBLE_ENABLED"
} > "${TMPDIR:-/tmp}/oss-review-flags-${CSID}"
echo "$CHALLENGE_ENABLED" > "${TMPDIR:-/tmp}/oss-review-challenge-enabled-${CSID}"
echo "$CLEAN_ARGS" > "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}"
echo "$KEEP_ITEMS" > "${TMPDIR:-/tmp}/oss-review-keep-items-${CSID}"  # timeout: 5000
```

Then set direct-report fast-path mode (a review-report `.md` path passed instead of a PR number):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
DIRECT_PATH_MODE=false
if [[ "$CLEAN_ARGS" == *.md ]]; then
    # reject plan files — no replies drafted from plan content
    if [[ "$CLEAN_ARGS" == .plans/* ]] || [[ "$CLEAN_ARGS" == *todo_*.md ]]; then
        echo "Error: plan files cannot be used as review report input. Pass a review report from .reports/review/<timestamp>/review-report.md or a PR number."
        exit 1
    fi
    if [ -f "$CLEAN_ARGS" ] && grep -qE '(^## Summary|^verdict:|APPROVED|NEEDS_WORK|REQUEST_CHANGES)' "$CLEAN_ARGS" 2>/dev/null; then  # timeout: 5000
        DIRECT_PATH_MODE=true
        REVIEW_FILE="$CLEAN_ARGS"
    else
        echo "⚠ $CLEAN_ARGS is a .md file but lacks review-report markers (## Summary | verdict: | APPROVED|NEEDS_WORK|REQUEST_CHANGES) — refusing direct-path fast-path; continuing with normal review path which expects a PR number."
    fi
fi
{
    echo "DIRECT_PATH_MODE=$DIRECT_PATH_MODE"
    [ "$DIRECT_PATH_MODE" = "true" ] && echo "REVIEW_FILE=$REVIEW_FILE"
} >> "${TMPDIR:-/tmp}/oss-review-flags-${CSID}"
```

**Content-type pre-classification (PR mode only)** — skip when `DIRECT_PATH_MODE=true`.

Classify PR from changed file patterns. Default `PR_TYPE=CODE`; override only when unambiguous.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
[ -f "${TMPDIR:-/tmp}/oss-review-flags-${CSID}" ] && . "${TMPDIR:-/tmp}/oss-review-flags-${CSID}"
PR_TYPE="CODE"
DOCS_TYPING_MODE=false; TESTS_CI_MODE=false
if [ "$DIRECT_PATH_MODE" = "false" ] && [[ "$CLEAN_ARGS" =~ ^[0-9]+$ ]]; then
    _CHANGED=$(gh pr diff $CLEAN_ARGS --name-only 2>/dev/null)  # timeout: 6000
    # no `|| echo 0`: grep -c already prints 0 & exits 1 — fallback would double it to "0\n0", breaking `-eq 0` tests below
    _PY_LOGIC_COUNT=$(echo "$_CHANGED" | grep -E '\.py$' | grep -cvE '(test_|_test\.py|conftest\.py|\.pyi$)' 2>/dev/null)
    _ALL_COUNT=$(echo "$_CHANGED" | grep -c . 2>/dev/null)
    _DOC_COUNT=$(echo "$_CHANGED" | grep -cE '\.(md|rst|txt|ipynb)$' 2>/dev/null)
    _TEST_CI_COUNT=$(echo "$_CHANGED" | grep -cE '(test_|_test\.py|conftest\.py|\.ya?ml$|\.github/|tox\.ini|Makefile)' 2>/dev/null)

    if [ "${_PY_LOGIC_COUNT:-0}" -eq 0 ] && [ "${_ALL_COUNT:-0}" -gt 0 ]; then
        if [ "$_DOC_COUNT" -ge "$_ALL_COUNT" ]; then
            PR_TYPE="DOCS_TYPING"; DOCS_TYPING_MODE=true
        elif [ "$(( _TEST_CI_COUNT + _DOC_COUNT ))" -ge "$_ALL_COUNT" ]; then
            PR_TYPE="TESTS_CI"; TESTS_CI_MODE=true
        fi
    fi
    echo "→ PR_TYPE=$PR_TYPE (_py_logic=$_PY_LOGIC_COUNT, _all=$_ALL_COUNT)"
fi
# persist PR_TYPE/mode flags (Check 41) — reloaded by challenge-skip, Steps 2/5
{
    echo "PR_TYPE=$PR_TYPE"
    echo "DOCS_TYPING_MODE=$DOCS_TYPING_MODE"
    echo "TESTS_CI_MODE=$TESTS_CI_MODE"
} > "${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}-${CSID}"
```

**Challenge skip** — challenger adds no value for non-logic PRs:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
IFS= read -r CHALLENGE_ENABLED < "${TMPDIR:-/tmp}/oss-review-challenge-enabled-${CSID}" 2>/dev/null; [ "$CHALLENGE_ENABLED" = "false" ] || CHALLENGE_ENABLED=true
# reload PR_TYPE (Check 41)
[ -f "${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}-${CSID}" ] && . "${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}-${CSID}"
if [ "$PR_TYPE" = "DOCS_TYPING" ] || [ "$PR_TYPE" = "TESTS_CI" ]; then
    CHALLENGE_ENABLED=false
fi
echo "$CHALLENGE_ENABLED" > "${TMPDIR:-/tmp}/oss-review-challenge-enabled-${CSID}"
```

Agent lineup — `PR_TYPE != CODE` overrides scope-based rules in Step 1:

| `PR_TYPE` | Agents | Challenger | Consolidator |
| --- | --- | --- | --- |
| `DOCS_TYPING` | `foundry:linting-expert` only | skip | `foundry:linting-expert` |
| `TESTS_CI` | `foundry:qa-specialist` + `foundry:linting-expert` | skip | `foundry:qa-specialist` |
| `CODE` | full scope-based lineup | per `--no-challenge` | `foundry:sw-engineer` |

When `DOCS_TYPING_MODE=true` or `TESTS_CI_MODE=true`: skip Step 1 file-scope detection and SCOPE classification; proceed directly to Step 2 agent launch.

## Step 1: Identify scope and context (run in parallel for PR mode)

Flags, `CLEAN_ARGS`, and `DIRECT_PATH_MODE` were parsed in Step 0 — reuse those values here.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# loads: detect_codemap.py — consumers: resolve/SKILL.md, review/SKILL.md
_DETECT_CODEMAP="${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/detect_codemap.py"
# codemap flags parsed here only (resolve/SKILL.md:141-143 idiom)
CODEMAP_FORCE_OFF=false; CODEMAP_STRICT=false
[[ " $ARGUMENTS " == *" --no-codemap "* ]] && CODEMAP_FORCE_OFF=true
[[ " $ARGUMENTS " == *" --codemap "* ]] && [[ " $ARGUMENTS " != *" --no-codemap "* ]] && CODEMAP_STRICT=true
[ "$CODEMAP_FORCE_OFF" = "true" ] && _DETECT_FLAGS="--force-off" || _DETECT_FLAGS=""
[ "$CODEMAP_STRICT" = "true" ] && _DETECT_FLAGS="$_DETECT_FLAGS --strict"
python "$_DETECT_CODEMAP" --prefix review $_DETECT_FLAGS 2>&1  # timeout: 5000
[ $? -ne 0 ] && { echo "! BLOCKED — codemap strict mode requested but codemap not installed or index missing"; exit 1; }
IFS= read -r CODEMAP_ENABLED < "${TMPDIR:-/tmp}/review-codemap-enabled-${CSID}" 2>/dev/null || CODEMAP_ENABLED="false"
IFS= read -r CODEMAP_CURRENCY < "${TMPDIR:-/tmp}/review-codemap-currency-${CSID}" 2>/dev/null || CODEMAP_CURRENCY="off"
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""  # reload (Check 41)
[ "$CODEMAP_FORCE_OFF" = "false" ] && cat "$_OSS_SHARED/codemap-gates.md"  # timeout: 5000
```

**Codemap gates** — when `CODEMAP_FORCE_OFF=false`, run (from `codemap-gates.md`, loaded above): **Gate A** if `CODEMAP_ENABLED=false` (missing index → offer to build); **Gate B** if `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`. On a build choice, after `codemap:scan-codebase` set `CODEMAP_ENABLED=true`. Skip both gates when `CODEMAP_FORCE_OFF=true` (`--no-codemap`).

If `SEMBLE_ENABLED=true`: proceed — semble MCP tool availability verified at first use. If `mcp__semble__search` is unavailable when called, it fails with a clear error; do not preemptively exit here.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. Found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--reply\`, \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--semble\`, \`--worktree\`, \`--keep\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Worktree isolation** — when `WT_ENABLED=true` **and** this is a PR review (not `--reply` / direct-report `.md` mode): run the review in an isolated git worktree so no dimension agent can mutate main sources. Load and follow the oss worktree protocol (§Enter now, §review deliverable routing, §Exit at the follow-up gate):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED="$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)"  # timeout: 5000
[ -f "${TMPDIR:-/tmp}/oss-review-flags-${CSID}" ] && . "${TMPDIR:-/tmp}/oss-review-flags-${CSID}"
[ "$WT_ENABLED" = "true" ] || WT_ENABLED=false
[ "$WT_ENABLED" = "true" ] && [ -f "$_OSS_SHARED/worktree-isolation.md" ] && cat "$_OSS_SHARED/worktree-isolation.md"  # timeout: 5000
```

`WT_ENABLED=true` → follow §Enter (base off HEAD, `EnterWorktree(path=…)`) before Step 1; the report is routed to the main tree (§review). Else skip — run in main tree.

> `file-handoff-protocol.md`, `cross-validation-protocol.md` and `codex-delegation.md` (Steps 5/7/consolidator) ship in **this** plugin's `_shared`, kept identical to foundry's canonical by `propagate_shared.py`. No separate resolution needed — `$_OSS_SHARED` from Step 0 covers them, and none of those steps degrade when foundry is absent.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
[ -f "${TMPDIR:-/tmp}/oss-review-flags-${CSID}" ] && . "${TMPDIR:-/tmp}/oss-review-flags-${CSID}"
if [ "$DIRECT_PATH_MODE" = "false" ]; then
    if [ -z "$CLEAN_ARGS" ] || ! [[ "$CLEAN_ARGS" =~ ^[0-9]+$ ]]; then
        echo "Error: PR number required. Usage: /oss:review <PR number> [--reply] [--no-challenge]"
        exit 1
    fi
    # four in parallel:
    CHANGED_FILES=$(gh pr diff $CLEAN_ARGS --name-only 2>/dev/null)  # reused by codemap block # timeout: 6000
    gh pr view $CLEAN_ARGS                                            # timeout: 6000
    gh pr checks $CLEAN_ARGS                                          # timeout: 15000
    gh pr view $CLEAN_ARGS --json reviews,labels,milestone            # timeout: 6000
    # scope-detection.md/SCOPE block run in fresh shells — w/o these sentinels: empty inputs, file-scope guard aborts, FIX→REFACTOR override never fires
    PR_LABELS=$(gh pr view $CLEAN_ARGS --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null)  # timeout: 6000
    PR_TITLE=$(gh pr view $CLEAN_ARGS --json title --jq .title 2>/dev/null)                            # timeout: 6000
    printf '%s\n' "$CHANGED_FILES" > "${TMPDIR:-/tmp}/oss-review-changed-files-${CSID}"
    printf '%s\n' "$PR_LABELS" > "${TMPDIR:-/tmp}/oss-review-pr-labels-${CSID}"
    printf '%s\n' "$PR_TITLE" > "${TMPDIR:-/tmp}/oss-review-pr-title-${CSID}"
fi
```

**CI STATUS** (PR mode only): parse `gh pr checks` output → extract failing required check names into `CI_FAILING_CHECKS`. Any failing: set `CI_RED=true`, print `⚠ CI is red: [list failing check names] — review proceeds; status noted in report header.` Continue to Steps 2–8 regardless. Expand `$CI_RED` and `$CI_FAILING_CHECKS` to literal values in the consolidator spawn prompt (Step 5).

### File scope detection

<!-- loads: modes/scope-detection.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload REVIEW_SKILL_DIR (Check 41: fresh shell)
IFS= read -r REVIEW_SKILL_DIR < "${TMPDIR:-/tmp}/review-skill-dir-${CSID}" 2>/dev/null || REVIEW_SKILL_DIR=""
cat "$REVIEW_SKILL_DIR/modes/scope-detection.md"  # timeout: 5000
```
Follow above and execute its bash blocks inside the `DIRECT_PATH_MODE = "false"` guard. Sets `PY_FILES`, `DOC_FILES`, `CICD_FILES`, `CICD_ONLY_MODE`, `DOCS_ONLY_MODE`, `DOCS_CICD_MODE`; persists flags to `${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}-${CSID}` for reload in Step 2.

### Scope pre-check

**DOCS_TYPING mode** (`DOCS_TYPING_MODE=true`): annotation-only .py changes (no logic). Spawn: `foundry:linting-expert` only; challenger disabled by Step 0; skip all other agents. Proceed directly to agent launch.

**TESTS_CI mode** (`TESTS_CI_MODE=true`): test files and CI config only. Spawn: `foundry:qa-specialist` + `foundry:linting-expert`; challenger disabled by Step 0; skip all other agents. Proceed directly to agent launch.

**CI/CD-only mode** (`CICD_ONLY_MODE=true`): no `.py`/`.md`/`.rst`. Spawn: `oss:cicd-steward` + Agent 1 + Agent 7 (if `CHALLENGE_ENABLED=true`) + Codex; skip Agents 2–6. Proceed directly to agent launch.

**Docs-only mode** (`DOCS_ONLY_MODE=true`): no `.py`. **foundry:doc-scribe (Agent 4) leads** — Agent 1 explicitly skipped (NOT for docs clause); linked-issue spawns also skip Agent 1. Spawn: Agent 4 + Agent 7 (if `CHALLENGE_ENABLED=true`) + Codex; skip Agents 1, 2, 3, 5, 6. Proceed directly to agent launch.

**Docs + CI/CD mode** (`DOCS_CICD_MODE=true`): no Python. Spawn: `oss:cicd-steward` (Agent 8) + `foundry:doc-scribe` (Agent 4) + Agent 7 (if `CHALLENGE_ENABLED=true`) + Codex; skip Agents 1, 2, 3, 5, 6. Proceed directly to agent launch.

Before spawning agents (Python mode only — all three mode flags false), classify diff:

- Count files changed, lines added/removed, new classes/modules
- Classify: **FIX** (\<3 files, \<50 lines), **REFACTOR** (internal restructure, no new public API), **FEATURE** (new public API or module), **CHORE** (deps, config, tooling — no logic changes), or **MIXED**
- **Short-diff multi-concern refactors**: FIX heuristic classifies by diff size, not intent. Override FIX → REFACTOR when PR labels include `perf`, `performance`, `optimization`, `refactor`, `architecture`, `cleanup` OR commit message keywords `refactor:`, `perf:`, `rewrite` OR diff touches different modules. Detect via `gh pr view --json labels,title`. Small-diff perf refactors are exactly the case FIX would silently mishandle.
- **Complexity smell**: 8+ files changed OR `PY_LOC_DELTA >400` → note in report header

Assign `SCOPE` shell variable so the `EXPECTED` array (Step 2 health monitor) can branch on it without comparing to an undefined value:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
# rehydrate Step1 inputs (Check 41) — PY_FILES lived in scope-detection.md's shell
CHANGED_FILES=$(cat "${TMPDIR:-/tmp}/oss-review-changed-files-${CSID}" 2>/dev/null)
PY_FILES=$(echo "$CHANGED_FILES" | grep '\.py$' || true)
IFS= read -r PR_LABELS < "${TMPDIR:-/tmp}/oss-review-pr-labels-${CSID}" 2>/dev/null || PR_LABELS=""
IFS= read -r PR_TITLE < "${TMPDIR:-/tmp}/oss-review-pr-title-${CSID}" 2>/dev/null || PR_TITLE=""
PY_FILE_COUNT=$(echo "$PY_FILES" | grep -c . 2>/dev/null)
# PY_LOC_DELTA = total churn, not net — renames give >0 at net 0; label/keyword override handles it
PY_LOC_DELTA=$(gh pr diff $CLEAN_ARGS 2>/dev/null | grep -E '^[+-][^+-]' | grep -vE '^[+-]{3}' | wc -l | tr -d ' ')  # timeout: 6000

# new API surface: added lines in __init__.py
NEW_API_LINES=$(gh pr diff $CLEAN_ARGS -- ':(glob)src/**/__init__.py' 2>/dev/null | grep -c '^+[^+]')  # no `|| echo 0` — see PR_TYPE block # timeout: 6000

# pure config/deps changes (no .py logic changes)
NON_CONFIG_PY=$(echo "$PY_FILES" | grep -vE '(pyproject\.toml|setup\.cfg|setup\.py|requirements.*\.txt|conftest\.py)' || true)

SCOPE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/classify_pr_scope.py" --py-files "$PY_FILE_COUNT" --loc-delta "$PY_LOC_DELTA" --new-api-lines "$NEW_API_LINES" --labels "$PR_LABELS" --title "$PR_TITLE" 2>/dev/null)  # timeout: 10000
echo "→ SCOPE=$SCOPE (py_files=$PY_FILE_COUNT, py_loc=$PY_LOC_DELTA, new_api=$NEW_API_LINES)"

# persist — Step2 EXPECTED_FILE runs in separate block
echo "$CHANGED_FILES" | grep -qE '(^|/)(requirements.*\.txt|pyproject\.toml|package.*\.json|Pipfile|poetry\.lock|setup\.cfg|.*\.lock)$' && CHORE_DEPS=true || CHORE_DEPS=false
_REVIEW_SCOPE_FILE="${TMPDIR:-/tmp}/oss-review-scope-${CLEAN_ARGS}-${CSID}"
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

### Structural context + review pre-flight (codemap-py — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`** — sets `codemap_available=false` for downstream agent prompts; agents fall back to file reads.

<!-- loads: modes/codemap-context.md -->
> loads: modes/codemap-context.md

`CODEMAP_ENABLED=true`:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload REVIEW_SKILL_DIR (Check 41: fresh shell)
IFS= read -r REVIEW_SKILL_DIR < "${TMPDIR:-/tmp}/review-skill-dir-${CSID}" 2>/dev/null || REVIEW_SKILL_DIR=""
cat "$REVIEW_SKILL_DIR/modes/codemap-context.md"  # timeout: 5000
```
Follow above and execute its contents — stages `codemap_available` and `$CODEMAP_CONTEXT_STAGE` to TMPDIR (Step 2 copies into `$RUN_DIR/codemap-context.md`) and defines the Step-2 spawn-prompt substitution rules + semble companion. `CODEMAP_ENABLED=false`: skip; agents fall back to file reads.

### Linked issue analysis (PR mode only)

Parse PR body (`gh pr view $CLEAN_ARGS`) for issue refs (`Closes #N`, `Fixes #N`, `Resolves #N`, `refs #N` — case-insensitive). Extract to `ISSUE_NUMS`. Cap 3.

`ISSUE_NUMS` non-empty AND `DOCS_CICD_MODE != true`: spawn one **foundry:doc-scribe** per issue in Step 2 alongside Codex — all launch simultaneously. Each issue agent: fetch `gh issue view <N> --json title,body,comments,state,labels` + `gh issue view <N> --comments`; produce `/oss:analyse`-style output (Summary, Root Cause Hypotheses top 3, Code Evidence); write full analysis to `$RUN_DIR/issue-<N>.md`; return only `{"status":"done","issue":N,"root_cause":"<one-line>","file":"$RUN_DIR/issue-<N>.md","confidence":0.N}`.

`ISSUE_NUMS` empty → skip issue checks downstream.

### Direct report fast-path

`DIRECT_PATH_MODE=true`:

- `REPLY_MODE=false` → use `AskUserQuestion`: "A report path was passed without `--reply`. Did you mean `/oss:review <path.md> --reply`?" Options: (a) "Yes — continue with `--reply` mode" → set `REPLY_MODE=true`; then re-check: `[ ! -f "$REVIEW_FILE" ] && echo "Error: review file not found at $REVIEW_FILE" && exit 1`; proceed; (b) "No — review a PR instead" → print usage hint (`/oss:review <N> | path/to/dir`) and stop.
- `REPLY_MODE=true` and `[ ! -f "$REVIEW_FILE" ]` → print `Error: report not found: $REVIEW_FILE` and stop.
- `REPLY_MODE=true` and file exists → print `[direct] using $REVIEW_FILE` → **skip to Step 8**. Skip Steps 2–7.

## Step 2: Codex + parallel agent launch

Set up run directory (shared by all agents) and resolve skill paths:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".temp/review/$TIMESTAMP"
mkdir -p "$RUN_DIR" # timeout: 5000
# persisted for cat resolve — hand-typing caused leading-dot drops → stray temp/review/ dirs
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"
# deliverable → main tree (worktree-isolation.md §review): --worktree sets orig-root at §Enter, else pwd — report stays reachable outside worktree; RUN_DIR stays worktree-local
IFS= read -r _REPORT_BASE < "${TMPDIR:-/tmp}/oss-review-orig-root-${CSID}" 2>/dev/null || _REPORT_BASE="$(pwd)"
[ -n "$_REPORT_BASE" ] || _REPORT_BASE="$(pwd)"
REPORT_DIR="$_REPORT_BASE/.reports/review/$TIMESTAMP"
mkdir -p "$REPORT_DIR" # timeout: 5000
echo "$REPORT_DIR" > "${TMPDIR:-/tmp}/oss-review-report-dir-${CSID}"  # persist for contract-write
```

**File-based handoff**:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload _OSS_SHARED (Check 41: fresh shell)
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""
cat "$_OSS_SHARED/file-handoff-protocol.md"  # timeout: 5000
```
Follow above. File absent → warn and continue without it.

**IMPORTANT**: Replace `$REPORT_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, and `$DATE` with actual literal computed values in every Agent spawn prompt. Do NOT pass as shell variables — agents receive text, not shell context. **Exception — `$RUN_DIR`**: never hand-substitute it; agents self-resolve via `export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"; cat "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"` per the run-dir preamble in `agent-prompts.md` (eliminates leading-dot transcription slips).

Check Codex availability:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && CODEX_AVAILABLE=1 && echo "codex (openai-codex) available" || { CODEX_AVAILABLE=0; echo "⚠ codex (openai-codex) not found — skipping co-review"; } # timeout: 15000
echo "$CODEX_AVAILABLE" > "${TMPDIR:-/tmp}/oss-review-codex-available-${CSID}"
```

<!-- loads: agent-prompts.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload REVIEW_SKILL_DIR (Check 41: fresh shell)
IFS= read -r REVIEW_SKILL_DIR < "${TMPDIR:-/tmp}/review-skill-dir-${CSID}" 2>/dev/null || REVIEW_SKILL_DIR=""
cat "$REVIEW_SKILL_DIR/templates/agent-prompts.md"  # timeout: 5000
```
Template (loaded above). Substitute `<REVIEW_SKILL_DIR>` → `$REVIEW_SKILL_DIR` before using content in spawn prompts. Leave `$RUN_DIR` literal in the prompt text — agents resolve it themselves via the run-dir preamble (`cat "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"`); the orchestrator must NOT retype the run-dir path.

**Codemap context propagation**: rehydrate `codemap_available` from Step 1 persist file, copy staged context into `$RUN_DIR/codemap-context.md`, substitute into every dimension-agent spawn prompt per the rules in the Structural-context block above. Block omitted when `codemap_available=false`.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || RUN_DIR=""
[ -n "$RUN_DIR" ] || { echo "! BLOCKED — run-dir sentinel empty; refusing to copy codemap context to a root-relative path"; exit 1; }
IFS= read -r _PR_TAG < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || _PR_TAG="$CLEAN_ARGS"
IFS= read -r codemap_available < "${TMPDIR:-/tmp}/oss-review-codemap-available-${_PR_TAG}-${CSID}" 2>/dev/null || codemap_available="false"
IFS= read -r CODEMAP_CONTEXT_STAGE < "${TMPDIR:-/tmp}/oss-review-codemap-context-stage-${_PR_TAG}-${CSID}" 2>/dev/null || CODEMAP_CONTEXT_STAGE=""
if [ "$codemap_available" = "true" ] && [ -n "$CODEMAP_CONTEXT_STAGE" ] && [ -f "$CODEMAP_CONTEXT_STAGE" ]; then
    cp "$CODEMAP_CONTEXT_STAGE" "$RUN_DIR/codemap-context.md"
fi
```

**Health monitoring** (CLAUDE.md §6): Create checkpoint BEFORE spawning agents:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
REVIEW_CHECKPOINT="${TMPDIR:-/tmp}/review-check-$(date +%s)-${CSID}"
touch "$REVIEW_CHECKPOINT"
# read back by poll block (separate invocation)
echo "$REVIEW_CHECKPOINT" > "${TMPDIR:-/tmp}/oss-review-checkpoint-${CSID}"
```

**Spawn-count gate — apply before spawning anything.** Each agent costs ~120,851 tok of fixed overhead regardless of how little work it does, i.e. ~73 tool-calls' worth, plus ~12.0 s/call. Measured on a real PR review: 11 agents, ~55% of the whole bill. Rules, all mandatory:

Two stages, in order — never collapse them:

1. **Scope preselection** (always): the scope/mode rules above decide which dimensions are *relevant at all*. A dimension with no changed file in its territory is out here and never comes back, at any flag.
2. **Relevance ranking** (default only): rank the survivors by evidence — changed files and lines in that dimension's territory, what Step 1 pre-classification found, what the structural context flagged — and spawn the top `FANOUT_MAX` (4). With `--full` (`FANOUT_CAP=0`) skip this stage and spawn every survivor of stage 1.

- More work → give each agent more, never add agents.
- **Spawn the fewest that keep each near `AGENT_CALL_BUDGET`** — not the most the cap allows. Total work under ~73 calls → do it inline and spawn nothing.
- **Merge before you split**: two dimensions whose files overlap go to one agent, not two.
- Every spawn prompt states the budget and requires an envelope even on exhaustion — `partial: true` plus what was finished. An agent that stalls past ~60 calls without an envelope forces full disk reconstruction.
- Dimensions dropped by the cap are listed in the report; never silently skipped.

Launch Codex, issue agents, and all review agents in one message batch — zero hold between Codex and review agents. All `Agent()` calls issue in a SINGLE response turn — substitute `$RUN_DIR` (literal) and issue numbers before spawning. Agent lineup: `codex:codex-rescue` (if `CODEX_AVAILABLE=1` **and** DOCS_TYPING_MODE/TESTS_CI_MODE both false) · per-issue `foundry:sw-engineer` (skip if `DOCS_CICD_MODE=true`) · Agents 1–8 per scope/mode rules above — that is stage 1. Then stage 2: unless `--full` was passed, rank the survivors and spawn only the top `FANOUT_MAX`, merging adjacent dimensions into shared agents where their files overlap; name every dropped or merged dimension in the report.

Poll for expected output files per `$MONITOR_INTERVAL` / `$HARD_CUTOFF` until all present or each hits hard cutoff.

Write expected paths to file (Bash arrays don't persist across tool invocations):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# restore — each SKILL.md bash block runs in fresh shell
IFS= read -r RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || RUN_DIR=""
# unbound RUN_DIR → EXPECTED_FILE="/.expected-files" (unwritable) — §6 monitor polls empty list, misses stalls
[ -n "$RUN_DIR" ] || { echo "! BLOCKED — run-dir sentinel empty; agent health monitoring cannot be armed"; exit 1; }
IFS= read -r _PR_TAG < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || _PR_TAG="unknown"
_REVIEW_MODE_FILE="${TMPDIR:-/tmp}/oss-review-mode-flags-${_PR_TAG}-${CSID}"
_REVIEW_SCOPE_FILE="${TMPDIR:-/tmp}/oss-review-scope-${_PR_TAG}-${CSID}"
[ -f "$_REVIEW_MODE_FILE" ] && . "$_REVIEW_MODE_FILE"
[ -f "$_REVIEW_SCOPE_FILE" ] && . "$_REVIEW_SCOPE_FILE"
IFS= read -r CHALLENGE_ENABLED < "${TMPDIR:-/tmp}/oss-review-challenge-enabled-${CSID}" 2>/dev/null; [ "$CHALLENGE_ENABLED" = "false" ] || CHALLENGE_ENABLED=true
IFS= read -r CODEX_AVAILABLE < "${TMPDIR:-/tmp}/oss-review-codex-available-${CSID}" 2>/dev/null || CODEX_AVAILABLE=0

POLL_START=$(date +%s)
EXPECTED_FILE="$RUN_DIR/.expected-files"
: >"$EXPECTED_FILE"

# Step 0 simplified modes — short-circuit full agent lineup
if [ "${DOCS_TYPING_MODE:-false}" = "true" ]; then
    echo "$RUN_DIR/foundry--linting-expert.md" >>"$EXPECTED_FILE"
elif [ "${TESTS_CI_MODE:-false}" = "true" ]; then
    echo "$RUN_DIR/foundry--qa-specialist.md" >>"$EXPECTED_FILE"
    echo "$RUN_DIR/foundry--linting-expert.md" >>"$EXPECTED_FILE"
else
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
fi
```

Later poll blocks read paths back via `while read -r path; do [ -f "$path" ] || PENDING=1; done <"$EXPECTED_FILE"` — no in-memory array required.

Every `$MONITOR_INTERVAL` seconds, in the poll bash block, rehydrate both the run dir and the checkpoint path first (fresh shell — an unbound `$RUN_DIR` makes the `find` scan `/`): `IFS= read -r RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || RUN_DIR=""` and `IFS= read -r REVIEW_CHECKPOINT < "${TMPDIR:-/tmp}/oss-review-checkpoint-${CSID}" 2>/dev/null || REVIEW_CHECKPOINT=""` then `find "$RUN_DIR" -newer "$REVIEW_CHECKPOINT" -type f | wc -l` — non-zero = agents alive (refresh checkpoint: `touch "$REVIEW_CHECKPOINT"`); zero since last refresh for `$HARD_CUTOFF` seconds = stalled. One `$EXTENSION` if `tail -20` output file explains delay; second stall = cutoff. On timeout: read partial results from stalled agent's file; surface with ⏱ in report. Never omit timed-out agents.

After all outputs collected (or timed out):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || RUN_DIR=""
ls "$RUN_DIR/"*.md 2>/dev/null || echo "⚠ No agent output files found in $RUN_DIR — check that $RUN_DIR was expanded correctly in spawn prompts"
```

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# boundary1: post-fanout, pre-consolidation (compaction-contract.md §Lifecycle)
IFS= read -r _RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || _RUN_DIR=""
IFS= read -r _PR_TAG < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || _PR_TAG="unknown"
IFS= read -r _REPORT_DIR < "${TMPDIR:-/tmp}/oss-review-report-dir-${CSID}" 2>/dev/null || _REPORT_DIR=""
IFS= read -r _KEEP < "${TMPDIR:-/tmp}/oss-review-keep-items-${CSID}" 2>/dev/null || _KEEP=""
_FINDING_FILES=$(ls "$_RUN_DIR/"*.md 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
_PRESERVE="run-dir=$_RUN_DIR, report-dir=$_REPORT_DIR, pr=$_PR_TAG, finding-files=$_FINDING_FILES"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .temp/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: oss:review · phase: consolidation (after parallel review-agent fan-out)"
    echo "- run-dir: $_RUN_DIR"
    echo "- preserve: $_PRESERVE"
    echo "- next: consolidate findings → final report (→ draft --reply if reply-mode)"
} > .temp/state/skill-contract.md
```

## Step 3: Post-agent checks (concurrent with Step 2 — after PR_BASE available)

Step 3a/3b may run concurrently with still-executing Step 2 agents — issue in same response turn as final Step 2 polls. Do NOT issue before `PR_BASE` is bound.

```bash
TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}') # timeout: 6000

# shallow-clone guard — merge-base fails silently on shallow clones
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
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
# rate-limit guard: on 429, retry once after 10s, else log+continue
CHANGED_EXPORTS=$(gh pr diff $CLEAN_ARGS -- ':(glob)src/**/__init__.py' 2>/dev/null | grep "^[-+]" | grep -v "^[-+][-+]" | grep -oP '\w+' | sort -u) # timeout: 6000
for export in $CHANGED_EXPORTS; do
    echo "=== $export ==="
    gh api "search/code" --method GET --field "q=$export language:python" --jq '.items[:5] | .[].repository.full_name' 2>/dev/null # timeout: 30000
done

gh pr diff $CLEAN_ARGS 2>/dev/null | grep -A2 "deprecated" # timeout: 6000
```

### 3b: OSS checks

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
OSS_SIGNALS="${TMPDIR:-/tmp}/oss-review-signals-${CLEAN_ARGS}-${CSID}.json"
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || gh release list --limit 1 --json tagName --jq '.[0].tagName' 2>/dev/null || echo "")  # timeout: 6000
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/check_oss_pr_signals.py" --clean-args "$CLEAN_ARGS" --latest-tag "$LATEST_TAG" --output-file "$OSS_SIGNALS"  # timeout: 30000
cat "$OSS_SIGNALS" 2>/dev/null
```

## Step 4: Cross-validate critical/blocking findings

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload _OSS_SHARED (Check 41: fresh shell)
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""
cat "$_OSS_SHARED/cross-validation-protocol.md"  # timeout: 5000
```
Follow above. File absent → warn: "cross-validation protocol not found — verify foundry plugin installed (`claude plugin list`); skipping Step 4." Then skip Step 4.

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

Select consolidator agent by `PR_TYPE` (lighter model for non-logic PRs):
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || CLEAN_ARGS=""
_REVIEW_MODE_FILE="${TMPDIR:-/tmp}/oss-review-mode-flags-${CLEAN_ARGS}-${CSID}"
[ -f "$_REVIEW_MODE_FILE" ] && . "$_REVIEW_MODE_FILE"
case "${PR_TYPE:-CODE}" in
    DOCS_TYPING) CONSOLIDATOR_AGENT="foundry:linting-expert" ;;
    TESTS_CI)    CONSOLIDATOR_AGENT="foundry:qa-specialist" ;;
    *)           CONSOLIDATOR_AGENT="claude" ;;
esac
```

Spawn `$CONSOLIDATOR_AGENT` consolidator agent with prompt:

<!-- loads: consolidator-prompt.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload REVIEW_SKILL_DIR (Check 41: fresh shell)
IFS= read -r REVIEW_SKILL_DIR < "${TMPDIR:-/tmp}/review-skill-dir-${CSID}" 2>/dev/null || REVIEW_SKILL_DIR=""
cat "$REVIEW_SKILL_DIR/templates/consolidator-prompt.md"  # timeout: 5000
```
Template (loaded above). Prepend the run-dir resolution preamble from `agent-prompts.md` so the consolidator self-resolves `$RUN_DIR` (`cat "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"`). Substitute `<REPORT_DIR>`, `<REVIEW_SKILL_DIR>`, `<_OSS_SHARED>`, `<DATE>`, `<CHANGED_FILES>`, `<SCOPE>`, `<CI_FAILING_CHECKS>` with literal expanded values; leave `$RUN_DIR` literal (agent self-resolves). Spawn: `Agent(subagent_type="$CONSOLIDATOR_AGENT", prompt=<substituted consolidator-prompt.md content>)`

Main context receives only the one-liner verdict. **Consolidator unavailable fallback** — `Agent` tool deferred/not loaded:
Print: `⛔ BLOCKED — Agent tool not loaded; consolidator cannot run. Re-invoke /oss:review to retry. If persistent, run /foundry:setup (requires foundry plugin) to verify session config.`
Do NOT read agent finding files inline — floods main context (~16–32K tokens per run), produces unreliable synthesis.

After parsing confidence: agent < 0.7 → prepend **⚠ LOW CONFIDENCE** to findings section, state gap explicitly. Never drop uncertain findings.

TaskUpdate "Step 5b: Print report header" → `in_progress`.

**MANDATORY, not optional narration** — the consolidator's returned one-liner is a routing signal only; it is never printed to the user and never satisfies this step. Perform, in this exact order, in this same turn, before any other Step 5/6/7 text:
1. Read `$REPORT_DIR/review-report.md` (Read tool).
2. Extract every field from the opening `---` up to and including the closing `---` — `Title:`, `Date:`, `PR Type:`, `Scope:`, `Focus:`, `Agents:`, `CI:`, `Outcome:`, `Summary:`, `Confidence:`, `Next steps:`, `Path:`.
3. Render those 12 fields as a two-column Markdown table (`Field | Value`, one row per key, file order) per quality-gates.md §Report File Format's Universal terminal-print rule — never print the raw `---`-delimited block. Append `→ saved to $REPORT_DIR/review-report.md`.
4. TaskUpdate "Step 5b: Print report header" → `completed` (only once the table has actually appeared in this response).

This table IS the reply header — print/omit-box handling per quality-gates.md §Report File Format (universal rule); omit the `╔═╗` Re:Anchor box (communication.md exempts quality-gates `---` report headers — the box would shadow the table). Never emit both a box header and this table. **Historical note**: an earlier revision of this step printed the raw `---`-delimited block verbatim inside a ` ```text ` fence to dodge markdown misparsing the literal `---` (leading `---` read as YAML frontmatter, closing `---` under `Path:` read as a setext heading) — that predates quality-gates.md's table rule and is superseded by it: converting to a table drops the raw `---` delimiters entirely, so the misparse risk the fence was guarding against does not arise. Render all 12 fields verbatim as table rows; use the `·`-separated one-line fallback ONLY when the `$REPORT_DIR/review-report.md` read genuinely fails — then state `⚠ could not read report header — verify $REPORT_DIR` before the fallback line rather than silently degrading, and still mark the task `completed` (the fallback line satisfies the step).

**Why this step is enforced twice over** (empirically motivated — a prior run genuinely skipped it): a prior run spawned the consolidator, received its one-liner, and jumped straight to Step 7's `AskUserQuestion` + confidence block — skipping this print entirely, even though `AskUserQuestion` itself (a hard tool call) fired correctly; do not treat "Step 5: Consolidate findings" completing as covering this step, they are separate tasks for that reason. **Runtime backstop**: `hooks/enforce-review-header.js` (PreToolUse on `AskUserQuestion`) denies Step 7a's call while `$REPORT_DIR/review-report.md` is missing or empty — a denial reading `oss:review report gate` means Step 5 never produced the report; spawn the consolidator, print the header, then re-issue the question. The hook can't see whether the print happened, only whether the report exists — the task above remains the actual check for the print itself.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# boundary2: post-consolidation, pre-reply (compaction-contract.md §Lifecycle)
IFS= read -r _PR_TAG < "${TMPDIR:-/tmp}/oss-review-pr-tag-${CSID}" 2>/dev/null || _PR_TAG="unknown"
IFS= read -r _REPORT_DIR < "${TMPDIR:-/tmp}/oss-review-report-dir-${CSID}" 2>/dev/null || _REPORT_DIR=""
IFS= read -r _RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || _RUN_DIR=""
{
    echo "## Active Skill Contract"
    echo "- skill: oss:review · phase: reply (after consolidation)"
    echo "- run-dir: $_RUN_DIR"
    echo "- preserve: final-report=$_REPORT_DIR/review-report.md, pr=$_PR_TAG"
    echo "- next: draft contributor reply (--reply) or stop at Step 7"
} > .temp/state/skill-contract.md
```

## Step 6: Delegate implementation follow-up (optional)

Identify tasks Codex can implement — meaningful code/doc work grounded in actual implementation.

**Delegate**: public functions with no docstrings (read impl first, describe so Codex writes real 6-section docstring) · missing test coverage for concrete well-defined behavior · consistent rename across files. **Do not delegate**: architectural issues, logic errors, security vulns, or any task requiring human judgment.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload _OSS_SHARED (Check 41: fresh shell)
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""
cat "$_OSS_SHARED/codex-delegation.md"  # timeout: 5000
```
Follow above. File absent → warn: "codex-delegation criteria not found — verify foundry plugin installed (`claude plugin list`); skipping Step 6 delegation." Then skip Step 6.

Print `### Codex Delegation` only when tasks delegated — omit otherwise. Don't rewrite output file.

## Step 7: Reply gate — STOP CHECK

**Worktree exit** — if `WT_ENABLED=true` and a worktree was entered at Step 0: the report already lives in the main tree (§review). Follow `worktree-isolation.md` §Exit — capture branch, call `ExitWorktree(action="keep")`, append the `Worktree` block. Exit **before** the follow-up gate so any follow-up runs in the main tree. Never auto-merge.

**Hard gate**: check "Step 5b: Print report header" task status before anything else in this step. Not `completed` → the header table has not actually been printed yet — go back and do it now (see Step 5), then mark the task `completed`, before calling `AskUserQuestion` below.

**Confidence block ownership**: `REPLY_MODE=true` → block in Step 8. `REPLY_MODE=false` → block in Step 7b.

`REPLY_MODE=true`: proceed to Step 8 — no Confidence block here. `REPLY_MODE=false` — do NOT proceed to Step 8. Execute both sub-steps below:

### 7a — Follow-up gate

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text. Single call — all options in one:
- question: "What next?"
- (a) label: `/oss:resolve $CLEAN_ARGS` — description: fix this PR (implement review findings, resolve conflicts, push)
- (b) label: `/oss:resolve report` — description: resolve from full review report only (no GitHub re-fetch)
- (c) label: `/oss:resolve $CLEAN_ARGS report` — description: fix PR + resolve from full review report in one pass
- (d) label: `walk through findings` — description: go through each finding interactively
- (e) label: `skip` — description: no action

`oss:resolve` has `disable-model-invocation: true` — `Skill()` invocation blocked. After AskUserQuestion returns:
- Resolve variant chosen (a/b/c when available): present chosen label as command user must run manually (e.g. `Run: /oss:resolve $CLEAN_ARGS`); no `Skill()` call
- `walk through findings` / `skip`: handle inline or stop

### 7b — Confidence block

End with `## Confidence` block per CLAUDE.md output standards.

```bash
rm -f .temp/state/skill-contract.md  # skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

<!-- Steps 5–7 defined in Step 5 (consolidate), Step 6 (Codex delegation), Step 7 (reply gate) blocks above — numbered sequentially from Step 1; Step 4 (cross-validate) precedes them; no gap: 4→5→6→7→8 -->

## Step 8: Draft contributor reply (only when --reply)

`REPLY_MODE` not set → skip.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/review-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""  # reload (Check 41)
cat "$_OSS_SHARED/shepherd-reply-protocol.md"  # timeout: 5000
```

`shepherd-reply-protocol.md` (loaded above) — apply invocation pattern and terminal summary format.

Spawn with:
- Report path: review output file from Step 5
- PR number and contributor handle: from Step 1 `gh pr view` output
- Output path: `.temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md`

**Part 2 compliance gate** (after shepherd returns — do NOT trust the return line alone):

```bash
# only when findings reference file:line — true LGTM has none
REPLY_OUT=".temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md"  # timeout: 5000
grep -qE '^\| *Importance *\| *Confidence *\| *File *\| *Line' "$REPLY_OUT" && echo "PART2_PRESENT=true" || echo "PART2_PRESENT=false"
```

`PART2_PRESENT=false` while the Step 5 report has ≥1 file:line finding → reply is non-compliant (findings folded into prose). Re-spawn `oss:shepherd` once with the same inputs plus: `"Part 2 table is MANDATORY — every file:line finding from the report must be its own row in the | Importance | Confidence | File | Line | Comment | table; do not fold file:line findings into Part 1 prose."` Re-check; if still absent, surface `⚠ Part 2 table missing — findings remain in prose` in the terminal summary.

End with `## Confidence` block per CLAUDE.md. Always last thing, regardless of `--reply`.

```bash
rm -f .temp/state/skill-contract.md  # skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

</workflow>

<calibration>

Scenarios:
1. FIX scope: single bug-fix PR with 1 changed file → scope=FIX, 2 agents skipped: perf-optimizer (scope), solution-architect (scope). Remaining: sw-engineer, qa-specialist, doc-scribe, linting-expert, challenger (unless `--no-challenge`) = 5 agents run (+ Codex if installed).
2. FEATURE scope: new feature PR with API changes → scope=FEATURE, all 7 agents run
3. --reply mode: existing review report + --reply flag → skip to Step 8, no agents spawned
4. DOCS_TYPING scope: PR with only annotation-type .py changes (no logic) → Step 0 sets PR_TYPE=DOCS_TYPING, CHALLENGE_ENABLED=false, CONSOLIDATOR_AGENT=foundry:linting-expert; only linting-expert spawned; Step 5 uses linting-expert consolidator.
5. TESTS_CI scope: PR with only test files + CI config → Step 0 sets PR_TYPE=TESTS_CI, CHALLENGE_ENABLED=false, CONSOLIDATOR_AGENT=foundry:qa-specialist; qa-specialist + linting-expert spawned; Step 5 uses qa-specialist consolidator.

</calibration>

<notes>

- **PR review acceptance criteria — canonical here**: oss:shepherd cross-references these criteria; don't duplicate in shepherd. Shepherd defers to this file for acceptance thresholds, severity definitions.
- Critical issues always surfaced regardless of scope
- Skip sections with no issues — no padding. Isolated code without git context → skip OSS Checks and Performance Concerns unless evidence of perf issues (nested loops, I/O in tight loops) or OSS concerns (hardcoded secrets, new deps).
- **Signal-to-noise gate**: Function/class ≤50 lines with 1–2 critical/high issues → max 2 additional medium/low findings. Rest as `[nit]` in "Minor Observations". First 3 findings reader sees = most impactful.
- PR mode: check CI first — red → report without full review
- Blocking issues need explicit `[blocking]` prefix
- Follow-up chains:
  - `[blocking]` bugs or regressions → `/develop:fix` (requires `develop` plugin) to reproduce with test, apply targeted fix
  - Structural or quality issues → `/develop:refactor` (requires `develop` plugin) for test-first improvements
  - Security findings in auth/input/deps → run `pip-audit` for dep CVEs; address OWASP issues via `/develop:fix` (requires `develop` plugin)
  - Mechanical issues beyond Step 5 → dispatch internally: `Agent(subagent_type="codex:codex-rescue", prompt="<task>")`
  - Docstrings, type annotations, renames → dispatch `Agent(subagent_type="codex:codex-rescue", prompt="<task description>")` per finding
  - PR feedback for contributor → `--reply` to auto-draft via oss:shepherd, or invoke oss:shepherd manually for custom framing

</notes>
