---
name: review
description: Multi-agent code review of GitHub Pull Requests (Python PRs only) covering architecture, tests, performance, docs, lint, security, and API design.
argument-hint: '[PR number|path/to/report.md] [--reply] [--no-challenge] [--codemap] [--semble]'
allowed-tools: Read, Write, Edit, Bash, Grep, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
model: opus
effort: high
when_to_use: 'Use when the user asks to review a GitHub Pull Request (Python PRs only), wants multi-agent code review feedback, or needs a structured review with severity-graded findings.'
---

<objective>

Spawn specialized sub-agents in parallel. Consolidate findings into structured feedback with severity levels.

NOT for local file review or current git diff — use `/develop:review` (requires `develop` plugin). NOT for non-Python PRs (TypeScript, Go, etc.) — state out of scope, stop. NOT for standalone GitHub issue analysis or thread summarization — use `oss:analyse`. Note: oss:review performs inline linked-issue analysis (root-cause alignment check in Step 1) as part of PR review — within scope, no conflict.

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
<!-- Background agent health monitoring (CLAUDE.md §8) — applies to Step 3 parallel agent spawns -->
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay

</constants>

<workflow>

<!-- Agent Resolution: canonical table at plugins/oss/skills/_shared/agent-resolution.md -->

## Agent Resolution

# Read $_OSS_SHARED/oss-shared-resolver.md and execute its contents
# Cold-start fallback (if shared resolver unreadable):
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
# Verify $_OSS_SHARED is resolved before any step that uses it (Step 9 reads shepherd-reply-protocol.md)
[ -z "$_OSS_SHARED" ] && echo "⚠ Could not resolve _OSS_SHARED — Step 9 --reply will fail; verify oss plugin installed" || true

Read `$_OSS_SHARED/agent-resolution.md`. Agents: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:perf-optimizer → general-purpose, foundry:doc-scribe → general-purpose, foundry:linting-expert → general-purpose, foundry:solution-architect → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. Each found task:

- `completed` if work done
- `deleted` if orphaned / irrelevant
- `in_progress` only if genuinely continuing

**Task tracking**: TaskCreate each major phase. Mark in_progress/completed throughout. Loop retry or scope change → new task.

## Step 1: Identify scope and context (run in parallel for PR mode)

```bash
# Parse flags (--reply, --no-challenge, --codemap, --semble); strips leading '#' from remaining args
[ -f "${CLAUDE_PLUGIN_ROOT}/bin/parse-review-args.sh" ] || { echo "Error: parse-review-args.sh not found — verify oss plugin installation (CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-unset})"; exit 1; }  # timeout: 5000
eval "$(bash "${CLAUDE_PLUGIN_ROOT}/bin/parse-review-args.sh" "$ARGUMENTS")"  # timeout: 5000
```

```bash
# Preflight: fail early if requested tool not available
if [ "$CODEMAP_ENABLED" = "true" ]; then
    if ! command -v scan-query >/dev/null 2>&1; then
        printf "! --codemap requested but codemap plugin not installed.\n  Install: claude plugin install codemap@borda-ai-rig\n"; exit 1
    fi
    _PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename)  # timeout: 3000
    if [ ! -f ".cache/scan/${_PROJ}.json" ]; then
        printf "! --codemap requested but no index found for project '%s'.\n  Build index: /codemap:scan\n" "$_PROJ"; exit 1
    fi
fi
```

`SEMBLE_ENABLED=true`: verify `mcp__semble__search` in available tools. Not found: print `! --semble requested but semble MCP server not configured. Configure: claude mcp add semble -s user -- uvx --from "semble[mcp]" semble` and stop.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. Found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--reply\`, \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
DIRECT_PATH_MODE=false
if [[ "$CLEAN_ARGS" == *.md ]]; then
    # Guard: reject plan files — shepherd must not draft replies from plan content
    if [[ "$CLEAN_ARGS" == .plans/* ]] || [[ "$CLEAN_ARGS" == *todo_*.md ]]; then
        echo "Error: plan files cannot be used as review report input. Pass a review report from .temp/output-review-*.md or a PR number."
        exit 1
    fi
    DIRECT_PATH_MODE=true
    REVIEW_FILE="$CLEAN_ARGS"
fi
```

```bash
FOUNDRY_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | sort -V | tail -1); [ -z "$FOUNDRY_SHARED" ] && FOUNDRY_SHARED="$(git rev-parse --show-toplevel 2>/dev/null || echo .)/.claude/skills/_shared"
[ -z "$FOUNDRY_SHARED" ] && echo "⚠ Could not resolve FOUNDRY_SHARED — Steps 5/7/consolidator will fail; verify foundry plugin installed" || true
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

**CI RED GATE** (PR mode only): `gh pr checks` shows failing required check → print `⛔ CI is red — skipping full review. Fix failing CI first, then re-run /oss:review.` and `exit 0`. Do NOT proceed to Steps 2–8.

### Python file pre-check

```bash
if [ "$DIRECT_PATH_MODE" = "false" ]; then
    PY_FILES=$(echo "$CHANGED_FILES" | grep '\.py$' || true)
    if [ -z "$PY_FILES" ]; then
        echo "No Python files changed in PR #$CLEAN_ARGS — skipping Python-specific review (oss:review is Python-only)"
        exit 0
    fi
fi
```

### Scope pre-check

Before spawning agents, classify diff:

- Count files changed, lines added/removed, new classes/modules
- Classify: **FIX** (\<3 files, \<50 lines), **REFACTOR** (no new public API), **FEATURE** (new public API or module), or **MIXED**
- **Complexity smell**: 8+ files changed → note in report header

Skip optional agents by classification:

- FIX scope → skip Agent 3 (perf-optimizer), Agent 6 (solution-architect), Agent 7 (challenger — low value for targeted fixes)
- REFACTOR scope → skip Agent 6 (solution-architect)
- FEATURE/MIXED → spawn all agents

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

- Each changed module's `rdep_count` — label **high risk** (>20), **moderate** (5–20), or **low** (\<5)
- `central --top 5` for project-wide blast-radius reference

Agent 1 uses this to prioritize: high `rdep_count` modules warrant deeper scrutiny on API compat, error handling, correctness — downstream callers outside diff not otherwise visible.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt:

> If `mcp__semble__search` available in tools and any changed module's codemap result was non-exhaustive (`"exhaustive": false`) or codemap absent: call `mcp__semble__search` with `query="<module> import"` and `repo=<git_root>`, `top_k=20` per module. Stop per module when two consecutive queries return no new importers. Merge with codemap results. Skip if all codemap results exhaustive.

### Linked issue analysis (PR mode only)

Parse PR body (`gh pr view $CLEAN_ARGS`) for issue refs (`Closes #N`, `Fixes #N`, `Resolves #N`, `refs #N` — case-insensitive). Extract to `ISSUE_NUMS`. Cap 3.

`ISSUE_NUMS` non-empty: spawn one **foundry:sw-engineer** per issue in Step 2 alongside Codex — all launch simultaneously in one message batch; no sequential hold between Codex and issue agents. Step 2's unified wait covers all outputs before Step 3. Each issue agent:

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
- `REPLY_MODE=true` and file exists → print `[direct] using $REVIEW_FILE` → **skip to Step 9**. Skip Steps 2–8.

## Step 2: Codex + parallel agent launch

Set up run directory (shared by all agents) and resolve skill paths:

```bash
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".reports/review/$TIMESTAMP"
mkdir -p "$RUN_DIR" # timeout: 5000
```

```bash
# find exit code lost through pipe; fallback guard below covers empty result
REVIEW_SKILL_DIR="$(find ~/.claude/plugins -path "*/oss/skills/review" -type d 2>/dev/null)"
[ -z "$REVIEW_SKILL_DIR" ] && REVIEW_SKILL_DIR="plugins/oss/skills/review"
```

**File-based handoff**: read `$FOUNDRY_SHARED/file-handoff-protocol.md`. File absent → warn: "file-handoff protocol not found — verify foundry plugin installed (`claude plugin list`); continuing without it." Then continue without it.

**IMPORTANT**: Replace `$RUN_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, and `$DATE` with actual literal computed values in every Agent spawn prompt below. Do NOT pass as shell variables — agents receive text, not shell context. Un-expanded `$RUN_DIR` creates directory literally named `$RUN_DIR` in project root.

Check Codex availability:

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && CODEX_AVAILABLE=1 && echo "codex (openai-codex) available" || { CODEX_AVAILABLE=0; echo "⚠ codex (openai-codex) not found — skipping co-review"; } # timeout: 15000
```

Every agent prompt must end with:

> "Write your FULL findings (all sections, Confidence block) to `$RUN_DIR/<agent-slug>.md` using the Write tool — where `<agent-slug>` uses hyphen separator (no colon), e.g. `foundry--sw-engineer.md`, `foundry--qa-specialist.md`, `foundry--perf-optimizer.md`, `foundry--doc-scribe.md`, `foundry--linting-expert.md`, `foundry--solution-architect.md`. Colons invalid in macOS filenames. Return to caller ONLY compact JSON envelope on final line — nothing else after it: `{\"status\":\"done\",\"findings\":N,\"severity\":{\"critical\":0,\"high\":1,\"medium\":2},\"file\":\"$RUN_DIR/<agent-slug>.md\",\"confidence\":0.88}`"

**Agent 1 — foundry:sw-engineer**: Review architecture, SOLID, type safety, error handling, code structure. Check Python anti-patterns (bare `except:`, `import *`, mutable defaults). Flag blocking vs suggestions.

**Error path analysis** (new/changed code): For each error-handling path introduced or modified, produce table:

| Location | Exception/Error | Caught? | Action if caught | User-visible? |
| --- | --- | --- | --- | --- |

Flag rules:

- Caught=No + User-visible=Silent → **HIGH** (unhandled error path)
- Caught=Yes + Action=`pass` or bare `except` → **MEDIUM** (swallowed error)
- Cap 15 rows. New/changed paths only.

Read `$REVIEW_SKILL_DIR/checklist.md` — apply CRITICAL/HIGH patterns as severity anchors. Respect suppressions.

`ISSUE_NUMS` non-empty: read `$RUN_DIR/issue-*.md`. Evaluate whether changes address root cause, not just symptom. PR addresses symptom only → `[blocking] HIGH — root cause misalignment`. PR description diverges from issue problem → `HIGH — PR/issue scope divergence`.

**Agent 2 — foundry:qa-specialist**: Audit test coverage. Find untested paths, missing edge cases, test quality issues. Check ML-specific issues (non-deterministic tests, missing seed pinning). List top 5 missing tests. Also check explicitly (GT-level findings, not afterthoughts):

- Concurrent access to shared state (when locks or shared variables present)
- Error paths: calling methods in wrong order (e.g., `log()` before `start()`)
- Resource cleanup on exception (file handles, database connections)
- Boundary conditions for division, empty collections, zero-count inputs
- Type-coercion boundary inputs: `int()`, `float()`, `datetime` parsers — test near-valid inputs (float strings for int parsers, empty strings, very large values, None)

**Consolidation rule**: One finding per test gap with concise scenario list, not separate findings. Format: "Missing tests for `parse_numeric()`: empty string, None, very large integers, float-string for int parser." Keeps section actionable, ≤5 items.

`ISSUE_NUMS` non-empty: read `$RUN_DIR/issue-*.md`. Check tests cover linked issue reproduction scenario. Issue has minimal repro/trace not covered by tests → `HIGH — issue reproduction not tested`.

**Agent 3 — foundry:perf-optimizer**: Find perf issues. Algorithmic complexity, Python loops that should be NumPy/torch ops, repeated computation, unnecessary I/O. ML code: DataLoader config, mixed precision. Prioritize by impact.

**Agent 4 — foundry:doc-scribe**: Check doc completeness. Public APIs without docstrings, missing Google style sections, outdated README, CHANGELOG gaps. Verify examples run.

- **Algorithmic accuracy check**: Functions computing math results — verify docstring claims match implementation. Output shape/length match? Standard name (e.g. "moving average") match behavior (expanding vs sliding window)? Deviates from convention → MEDIUM (docstring must document deviation). **Deprecation check**: Check stdlib deprecated (e.g., `datetime.utcnow()` deprecated since Python 3.12 (use `datetime.now(UTC)` instead), `os.path` vs `pathlib`). Flag deprecated usage as MEDIUM with replacement. Route to `foundry:linting-expert` if ruff/mypy can catch automatically — avoid duplicate findings.

**Agent 5 — foundry:linting-expert**: Static analysis. Check ruff/mypy pass. Type annotation gaps on public APIs, suppressed violations without explanation, missing pre-commit hooks. Flag mismatched Python version.

**Security augmentation (conditional — fold into Agent 1, not separate spawn)**: Diff touches auth, user input, deps, or serialization → add to Agent 1 prompt: check SQL injection, XSS, insecure deserialization, hardcoded secrets, missing input validation. Run `pip-audit` if dep files changed. Skip if purely internal refactoring.

**Agent 6 — foundry:solution-architect (optional, PRs touching public API boundaries)**: Diff touches `__init__.py` exports, adds/modifies Protocols/ABCs, changes module structure, or new public classes → evaluate API design, coupling, backward compat. Skip if internal only.

**Agent 7 — foundry:challenger (skip if `CHALLENGE_ENABLED=false` or FIX scope)**: Adversarial review of design decisions. Attacks assumptions, missing edge cases, security risks, architectural concerns, complexity creep with mandatory refutation step. File-handoff: per preamble above (output to `foundry--challenger.md`). Severity mapping: Blockers → critical/high; Concerns → medium; Nitpicks → low.

**Health monitoring** (CLAUDE.md §8): Create checkpoint BEFORE spawning agents — timing starts from first spawn:

```bash
REVIEW_CHECKPOINT="/tmp/review-check-$(date +%s)"
touch "$REVIEW_CHECKPOINT"
```

Launch Codex, issue agents, and all review agents in one message batch — zero hold between Codex and review agents:

```bash
CODEX_OUT="$RUN_DIR/foundry--codex.md"
# All Agent() calls below go in a SINGLE response turn — Codex + all review agents start simultaneously:
# [if CODEX_AVAILABLE=1] Agent(subagent_type="codex:codex-rescue", prompt="Adversarial review: look for bugs, missed edge cases, incorrect logic, and inconsistencies with existing code patterns. Read-only: do not apply fixes. Write findings to $RUN_DIR/foundry--codex.md.")
# [for each N in ISSUE_NUMS] Agent(subagent_type="foundry:sw-engineer", prompt="<issue N prompt — see Step 1 issue agent spec>. Write to $RUN_DIR/issue-N.md")
# Agent(subagent_type="foundry:sw-engineer", ...) ← Agent 1
# Agent(subagent_type="foundry:qa-specialist", ...) ← Agent 2
# Agent(subagent_type="foundry:perf-optimizer", ...) ← Agent 3
# Agent(subagent_type="foundry:doc-scribe", ...) ← Agent 4
# Agent(subagent_type="foundry:linting-expert", ...) ← Agent 5
# [optional] Agent(subagent_type="foundry:solution-architect", ...) ← Agent 6
# [conditional] Agent(subagent_type="foundry:challenger", ...) ← Agent 7
```

Unified wait — poll until all expected outputs present or each hits hard cutoff:

```bash
POLL_START=$(date +%s)
EXPECTED=()
[ "$CODEX_AVAILABLE" = "1" ] && EXPECTED+=("$RUN_DIR/foundry--codex.md")
for N in $ISSUE_NUMS; do EXPECTED+=("$RUN_DIR/issue-$N.md"); done
EXPECTED+=("$RUN_DIR/foundry--sw-engineer.md")
EXPECTED+=("$RUN_DIR/foundry--qa-specialist.md")
EXPECTED+=("$RUN_DIR/foundry--perf-optimizer.md")
EXPECTED+=("$RUN_DIR/foundry--doc-scribe.md")
EXPECTED+=("$RUN_DIR/foundry--linting-expert.md")
# solution-architect and challenger added conditionally when spawned

for EXPECTED_FILE in "${EXPECTED[@]}"; do
    until [ -f "$EXPECTED_FILE" ]; do
        sleep 15
        ELAPSED=$(( $(date +%s) - POLL_START ))
        if [ "$ELAPSED" -gt "$HARD_CUTOFF" ]; then
            printf "⏱ %s timed out after %ds — proceeding without it\n" "$(basename "$EXPECTED_FILE")" "$ELAPSED"
            break
        fi
    done
done
```

Every `$MONITOR_INTERVAL` seconds: `find $RUN_DIR -newer "$REVIEW_CHECKPOINT" -type f | wc -l` — non-zero = agents alive (refresh checkpoint: `touch "$REVIEW_CHECKPOINT"`); zero since last refresh for `$HARD_CUTOFF` seconds = stalled. Refreshing checkpoint after each successful poll ensures stalls detected relative to last activity, not launch. One `$EXTENSION` if `tail -20` output file explains delay; second stall = cutoff. On timeout: read partial results from stalled agent's file; surface with ⏱ in report. Never omit timed-out agents.

After all outputs collected (or timed out), proceed to post-agent checks.

```bash
ls "$RUN_DIR/"*.md 2>/dev/null || echo "⚠ No agent output files found in $RUN_DIR — check that $RUN_DIR was expanded correctly in spawn prompts"
```

## Step 3: Post-agent checks and consolidation setup

Run Steps 3 and 4 concurrently with agent execution started in Step 2 — do not wait for Step 2 agents to complete before beginning these checks.

## Step 4: Post-agent checks (begin after Step 2 agent spawns launch — do not wait for Step 2 completion)

Run these two checks concurrently with Step 2 agent execution:

```bash
TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}') # timeout: 6000  # shared by 4a and 4b

# Shallow-clone guard: git merge-base fails silently on shallow clones, returning empty output
# that looks like "nothing changed" — causes false-negative in security scan and ecosystem check.
IS_SHALLOW=$(git rev-parse --is-shallow-repository 2>/dev/null || echo "unknown")
if [ "$IS_SHALLOW" = "true" ]; then
    echo "⚠ Shallow clone detected — running: git fetch --unshallow to enable merge-base checks"
    git fetch --unshallow 2>/dev/null || echo "⚠ git fetch --unshallow failed — Step 4 checks may be incomplete"
fi
PR_BASE=$(git merge-base HEAD "origin/${TRUNK:-main}" 2>/dev/null || echo "origin/${TRUNK:-main}")
```

### 4a: Ecosystem impact check (for libraries with downstream users)

> **Scope disclosure**: check searches public GitHub code globally. Results may include unrelated projects using same symbol names — treat as signal, not proof. Rate-limited responses (HTTP 429, empty results) may indicate limitation, not absence of usage.

```bash
# Check if changed APIs are used by downstream projects
# Rate-limit guard: if gh api returns HTTP 429, wait 10 seconds and retry once.
# If still rate-limited, log "rate-limited — downstream search may be incomplete" and continue.
CHANGED_EXPORTS=$(git diff $PR_BASE HEAD -- ':(glob)src/**/__init__.py' | grep "^[-+]" | grep -v "^[-+][-+]" | grep -oP '\w+' | sort -u) # timeout: 3000
for export in $CHANGED_EXPORTS; do
    echo "=== $export ==="
    gh api "search/code" --field "q=$export language:python" --jq '.items[:5] | .[].repository.full_name' 2>/dev/null # timeout: 30000
    # Note: GitHub code search API is rate-limited (~30 req/min); empty results may indicate rate limiting, not absence of usage
done

# Check if deprecated APIs have migration guides
git diff $PR_BASE HEAD | grep -A2 "deprecated" # timeout: 3000
```

### 4b: OSS checks

```bash
# Check for new dependencies — license compatibility
git diff $PR_BASE HEAD -- pyproject.toml requirements*.txt # timeout: 3000

# Check for secrets accidentally committed — scoped to .py files only (oss:review is Python-only)
git diff $PR_BASE HEAD -- '*.py' | grep -iE "(password|secret|api_key|token|private_key|auth_token)\s*[=:]\s*['\"]?[A-Za-z0-9+/._-]{8,}['\"]?" # timeout: 3000

# Check for API stability: are public APIs being removed without deprecation?
git diff $PR_BASE HEAD -- ':(glob)src/**/__init__.py' # timeout: 3000

# Check CHANGELOG was updated
git diff $PR_BASE HEAD -- CHANGELOG.md CHANGES.md # timeout: 3000
```

## Step 5: Cross-validate critical/blocking findings

Read `$FOUNDRY_SHARED/cross-validation-protocol.md`. File absent → warn: "cross-validation protocol not found — verify foundry plugin installed (`claude plugin list`); skipping Step 5." Then skip Step 5.

**Independence requirement**: cross-validation must run as separate spawned agent — same type as finding's origin (e.g., `foundry:sw-engineer` verifies `foundry:sw-engineer` critical finding). Do NOT validate in orchestrator context; in-context verification violates independence.

Spawn verifier agent per critical/blocking finding. Agent reads relevant finding file from `$RUN_DIR` and referenced code. Each verifier must write full rationale to `$RUN_DIR/verify-<finding-id>.md` using the Write tool, then return ONLY: `{"finding_id":"<id>","verdict":"CONFIRMED|REFUTED","rationale":"<one sentence>","file":"$RUN_DIR/verify-<finding-id>.md"}`. REFUTED → downgrade finding severity or remove before consolidation.

## Step 6: Consolidate findings

Before output path, extract:
```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-')
[ -z "$BRANCH" ] && BRANCH="main"  # fallback: detached HEAD or empty slug
DATE=$(date +%Y-%m-%d)
```

**IMPORTANT**: expand `$RUN_DIR`, `$REVIEW_SKILL_DIR`, `$BRANCH`, and `$DATE` to literal values before inserting into the spawn prompt — same rule as Step 3. Un-expanded variables create wrong paths.

Spawn **foundry:sw-engineer** consolidator agent with prompt:

> **Task:** Read all finding files in `$RUN_DIR/` (agent files: `foundry--sw-engineer.md`, `foundry--qa-specialist.md`, `foundry--perf-optimizer.md`, `foundry--doc-scribe.md`, `foundry--linting-expert.md`, `foundry--solution-architect.md`, `foundry--challenger.md` if present, and `foundry--codex.md` if present — skip missing). Read `$REVIEW_SKILL_DIR/checklist.md` using Read tool and apply consolidation rules (signal-to-noise filter, annotation completeness, section caps). Include only findings that passed Step 5 cross-validation (verdict=CONFIRMED or un-cross-validated medium/low). For `foundry--challenger.md`: map severity keys Blockers → critical/high, Concerns → medium, Nitpicks → low when aggregating counts.
>
> **Filtering rules:**
> - Precision gate: only include findings with concrete, actionable location (function, line range, or variable name).
> - Finding density: modules under 100 lines → aim ≤10 total findings.
> - Ranking: within each section, order by impact (blocking > critical > high > medium > low).
> - Codex deduplication: include `foundry--codex.md` unique findings under `### Codex Co-Review`; same file:line raised by both agent and Codex → keep agent version, mark 'also flagged by Codex'.
>
> **Issue alignment (when `issue-*.md` files exist in `$RUN_DIR`):** Include `### Issue Root Cause Alignment` section placed immediately after `### [blocking] Critical`. Per linked issue: state root cause hypothesis, whether PR addresses it (yes / partially / no), whether PR description diverges from issue's stated problem, whether reproduction scenario tested. Any `root cause misalignment` or `scope divergence` finding is at least HIGH severity.
>
> **Confidence parsing:** Parse each agent's `confidence` from JSON envelope. Assign `codex` fixed confidence 0.75 (moderate — static analysis, no runtime context).
>
> **Write to:** compute output path first, then guard against overwrite:
> ```bash
> OUT=".temp/output-review-$BRANCH-$DATE.md"
> n=2; while [ -f "$OUT" ]; do OUT=".temp/output-review-$BRANCH-$DATE-${n}.md"; n=$((n+1)); done
> ```
> Write full report to `$OUT` using Write tool.
>
> **Return ONLY** one-liner summary: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=.temp/output-review-$BRANCH-$DATE.md`

Main context receives only the one-liner verdict. Proceed with that summary for terminal output.

**Consolidator unavailable fallback** — `Agent` tool deferred/not loaded and consolidator cannot be spawned:
1. Read each `$RUN_DIR/*.md` agent finding file using Read tool before synthesizing — do not rely solely on JSON envelope counts. Synthesize verdict one-liner: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=.temp/output-review-$BRANCH-$DATE.md`
2. Compute output path then guard: `OUT=".temp/output-review-$BRANCH-$DATE.md"; n=2; while [ -f "$OUT" ]; do OUT=".temp/output-review-$BRANCH-$DATE-${n}.md"; n=$((n+1)); done` — write consolidated report to `$OUT` using Write tool. Include all sections and Confidence block
3. Print terminal block using `$FOUNDRY_SHARED/terminal-summaries.md` template — **never silently skip terminal output**

Report format: read `templates/review-report.md` in skill directory and use as output structure.

After parsing confidence: agent < 0.7 → prepend **⚠ LOW CONFIDENCE** to findings section, state gap explicitly. Never drop uncertain findings.

Print terminal block: read `---` header from top of `.temp/output-review-$BRANCH-$DATE.md` (lines 1–12, up to and including closing `---`), append `→ saved to .temp/output-review-$BRANCH-$DATE.md`, print to terminal. Report file already contains the block — no separate prepend step needed.

## Step 7: Delegate implementation follow-up (optional)

After consolidating, identify tasks Codex can implement — not style violations (pre-commit handles those), but meaningful code/doc work grounded in actual implementation.

**Delegate to Codex when you can write accurate, specific brief:**

- Public functions with no docstrings — read implementation first, describe what each does so Codex writes real 6-section docstring
- Missing test coverage for concrete, well-defined behavior — describe exact scenario
- Consistent rename across files — name old/new symbol and reason

**Do not delegate — require human judgment:**

- Architectural issues, logic errors, security vulnerabilities, or behavioural changes
- Any task where you cannot write precise description without guessing

Read `$FOUNDRY_SHARED/codex-delegation.md`. File absent → warn: "codex-delegation criteria not found — verify foundry plugin installed (`claude plugin list`); skipping Step 7 delegation." Then skip Step 7.

Example prompt: `"Add a test for StreamReader.read_chunk() in tests/test_reader.py — the method should raise ValueError when called after close(), currently no test covers this path."`

Print `### Codex Delegation` only when tasks delegated — omit if nothing delegated. Don't rewrite output file.

## Step 8: Reply gate — STOP CHECK

**Confidence block ownership**: `REPLY_MODE=true` → Confidence block written by Step 9 (always last). `REPLY_MODE=false` → Confidence block written here in Step 8b (Step 9 not reached).

`REPLY_MODE=true`: proceed to Step 9 — no Confidence block here.

`REPLY_MODE=false` — do NOT proceed to Step 9. Execute both sub-steps below:

### 8a — Follow-up gate

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text before or instead of tool call. Map options directly into tool call arguments:
- question: "What next?"
- (a) label: `/oss:resolve $CLEAN_ARGS` — description: fix this PR
- (b) label: `/oss:resolve report` — description: resolve from full report
- (c) label: `/oss:resolve $CLEAN_ARGS report` — description: fix PR + resolve from report
- (d) label: `walk through findings` — description: go through each finding interactively
- (e) label: `skip` — description: no action

`oss:resolve` has `disable-model-invocation: true` — `Skill()` invocation blocked (exempt from follow-up gate rule in `quality-gates.md`). After AskUserQuestion returns:
- Options (a)/(b)/(c): acknowledge selection; present chosen label as command user must run manually (e.g. `Run: /oss:resolve $CLEAN_ARGS` for option a); no `Skill()` call
- Options (d)/(e): handle inline or stop

### 8b — Confidence block

End with `## Confidence` block per CLAUDE.md output standards.

## Step 9: Draft contributor reply (only when --reply)

`REPLY_MODE` not set → skip.

```bash
# Check oss:shepherd availability — verify installed cache path specifically
# Cannot use _OSS_SHARED as signal: its bare-path fallback is always non-empty even when oss plugin absent
SHEPHERD_AVAILABLE=0
ls ~/.claude/plugins/cache/borda-ai-rig/oss/*/agents/shepherd.md 2>/dev/null | grep -q . && SHEPHERD_AVAILABLE=1
[ -f ".claude/agents/shepherd.md" ] && SHEPHERD_AVAILABLE=1
```

`$SHEPHERD_AVAILABLE` equals 0: print `⚠ oss:shepherd not available — skipping contributor reply draft. Install the oss plugin to enable --reply.` and skip shepherd spawn.

`$SHEPHERD_AVAILABLE` equals 1: read `$_OSS_SHARED/shepherd-reply-protocol.md` — apply invocation pattern and terminal summary format.

Spawn with:
- Report path: review output file from Step 6
- PR number and contributor handle: from Step 1 `gh pr view` output
- Output path: `.temp/output-reply-<PR#>-$(date -u +%Y-%m-%d).md`

End with `## Confidence` block per CLAUDE.md. Always last thing, regardless of `--reply`.

</workflow>

<calibration>

Scenarios:
1. FIX scope: single bug-fix PR with 1 changed file → scope=FIX, 3 agents skipped: perf-optimizer (scope), solution-architect (scope), challenger skipped by scope rule (FIX); also always skipped when `--no-challenge` passed (independent flag path). Remaining: sw-engineer, qa-specialist, doc-scribe, linting-expert = 4 agents run.
2. FEATURE scope: new feature PR with API changes → scope=FEATURE, all 7 agents run
3. --reply mode: existing review report + --reply flag → skip to Step 9, no agents spawned

</calibration>

<notes>

- Critical issues always surfaced regardless of scope
- Skip sections with no issues — no padding. Isolated code without git context → skip OSS Checks and Performance Concerns unless evidence of perf issues (nested loops, I/O in tight loops) or OSS concerns (hardcoded secrets, new deps).
- **Signal-to-noise gate**: Function/class ≤50 lines with 1–2 critical/high issues → max 2 additional medium/low findings. Rest as `[nit]` in "Minor Observations". First 3 findings reader sees = most impactful.
- PR mode: check CI first — red → report without full review
- Blocking issues need explicit `[blocking]` prefix
- Follow-up chains:
  - `[blocking]` bugs or regressions → `/develop:fix` (requires `develop` plugin) to reproduce with test and apply targeted fix
  - Structural or quality issues → `/develop:refactor` (requires `develop` plugin) for test-first improvements
  - Security findings in auth/input/deps → run `pip-audit` for dep CVEs; address OWASP issues via `/develop:fix` (requires `develop` plugin)
  - Mechanical issues beyond Step 6 → dispatch internally: `Agent(subagent_type="codex:codex-rescue", prompt="<task>")`
  - Docstrings, type annotations, renames → dispatch `Agent(subagent_type="codex:codex-rescue", prompt="<task description>")` per finding
  - PR feedback for contributor → `--reply` to auto-draft via oss:shepherd, or invoke oss:shepherd manually for custom framing

</notes>
