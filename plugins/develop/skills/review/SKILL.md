---
name: review
description: "Multi-agent code review of local Python files, directories, or the current git diff covering architecture, tests, performance, docs, lint, security, and API design. Scope: Python source files in local working tree. Python-file-free targets (pure JS/TS/Go/Rust projects) are out of scope."
argument-hint: "[python-file|dir] [--no-challenge] [--codemap] [--no-codemap] [--semble]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
effort: high
---

<objective>

Comprehensive code review of local files or working-tree diff. Spawn specialized sub-agents in parallel, consolidate findings into structured feedback with severity levels.

NOT for: GitHub PR review (use `/oss:review <PR#>` (requires oss plugin)); GitHub thread analysis or PR reply drafting (use `/oss:analyse <PR#>` (requires oss plugin)); implementation (use `/develop:feature` or `/develop:fix`); `.claude/` config changes (use `/foundry:manage` (requires foundry plugin) or `/foundry:audit` (requires foundry plugin)); non-Python-only projects (zero Python source files — pure JS/TS/Go/Rust) — review toolchain assumes Python/pytest; Python test-only targets where diff contains only test files (no `src/` or top-level `.py` source outside `tests/`) — review will be uninformative; for polyglot projects with Python source, reviews Python files only.

</objective>

<inputs>

- **$ARGUMENTS**: optional file path or directory to review.
  - Path given: review those files
  - Omitted: review current git diff (`git diff HEAD` — staged + unstaged vs HEAD)
  - **Scope**: Python source only. Non-Python file (YAML, JSON, shell script, etc.) → state out of scope, suggest appropriate tool. No findings.
  - `--no-challenge`: skip adversarial review (challenger runs by default)
  - `--codemap`: strict mode — stop and report if codemap not installed (on by default when installed; use `--no-codemap` to opt out)
  - `--semble`: enable semble semantic search companion (off by default)

**PR#/filename disambiguation gate** (execute BEFORE Step 1): tighten classification — valid PR# is positive integer with no extension and no existing file at that path. Filenames that look like numbers (e.g. `42.py`) must NOT trigger PR mode.

```bash
TOKEN="$ARGUMENTS"
if [[ "$TOKEN" =~ ^[0-9]+$ ]] && [ ! -e "$TOKEN" ]; then
    # Strict PR mode: bare positive integer, no extension, no existing path
    echo "PR number detected — checking oss plugin availability"
    [ -f "$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/review/SKILL.md 2>/dev/null | head -1)" ] && OSS_AVAILABLE=true || OSS_AVAILABLE=false  # timeout: 5000
elif [ -f "$TOKEN" ]; then
    # File mode: valid path, even if it looks numeric (e.g. `42.py`)
    OSS_AVAILABLE=skip
elif [[ "$TOKEN" =~ ^#[0-9]+$ ]] && [ ! -e "$TOKEN" ]; then
    # `#NNN` form — also PR-like
    echo "PR number detected — checking oss plugin availability"
    [ -f "$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/review/SKILL.md 2>/dev/null | head -1)" ] && OSS_AVAILABLE=true || OSS_AVAILABLE=false  # timeout: 5000
else
    OSS_AVAILABLE=skip
fi
```

If `$OSS_AVAILABLE` is `skip`: proceed to Step 1 normally (path / diff / dir mode).

If `$OSS_AVAILABLE` is `true`: call `AskUserQuestion` tool: "Looks like you passed a PR/issue number. Did you mean to run `/oss:review $ARGUMENTS` (requires oss plugin) to review that PR?" Options: (a) "Yes — launch `/oss:review $ARGUMENTS`" → strip develop-specific flags (`--team`, `--issue`, `--dry-run`, `--local`) from `$ARGUMENTS` before forwarding; call `Skill(skill="oss:review", args="<stripped-args>")`; (b) "No — review local code" → call `AskUserQuestion` immediately: "Provide the file path or directory to review:" — use the user's response as `$REVIEW_ARGS` and proceed to Step 1.

If `$OSS_AVAILABLE` is `false`: call `AskUserQuestion` tool: "Looks like you passed a PR/issue number, but the oss plugin is not installed — `/oss:review` unavailable. Did you mean to review local code instead?" Options: (a) "Yes — review local code" → call `AskUserQuestion` again immediately: "Provide the file path or directory to review:" — use the user's response as `$REVIEW_ARGS` and proceed to Step 1; (b) "I need oss plugin" → inform user: install with `claude plugin install oss@borda-ai-rig`.

</inputs>

<constants>

CHALLENGE_ENABLED=true  # set to false via --no-challenge
CODEMAP_ENABLED=auto    # on by default if codemap installed + index found; --no-codemap = off; --codemap = strict (stop if not installed)
SEMBLE_ENABLED=false    # set to true via --semble

</constants>

<workflow>

<!-- Shared pattern with oss:review — coordinate on agent spawn logic, file-handoff, consolidation changes -->

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (mounted by develop plugin init) -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
[ -z "$_DEV_SHARED" ] && _DEV_SHARED="plugins/develop/skills/_shared"
[ -z "$_FOUNDRY_SHARED" ] && _FOUNDRY_SHARED="plugins/foundry/skills/_shared"
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

After Step 1 completes (scope and `TARGET` known), create these tasks **before any agent spawns** (in order, all at once):

- **"Step 1: Identify scope"** — mark `in_progress` at Step 1 start; mark `completed` when `TARGET` and `SCOPE` set and Python file check passes
- **"Step 2: Codex co-review"** — create before Step 2 (skip task if Codex unavailable); mark `in_progress` before Codex spawn; mark `completed` when codex seed extracted (or timed out)
- **"Step 3: Spawn review agents"** — mark `in_progress` before agents launch; mark `completed` when all agent output files collected (or health-monitoring cutoff reached)
- **"Step 4: Cross-validate critical findings"** — mark `in_progress` before verifier spawns; mark `completed` when all verdicts received; **skip task creation when no critical/blocking findings exist after Step 3**
- **"Step 5: Consolidate findings"** — mark `in_progress` before spawning consolidator; mark `completed` before printing terminal block (per task-lifecycle.md: `TaskUpdate(completed)` BEFORE long output)

## Flag parsing

Strip flags from `$ARGUMENTS` before using as path:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" --skill review --write-files "$ARGUMENTS"
# Values written to: ${TMPDIR:-/tmp}/dev-review-{no-challenge,semble,codemap} (per-skill) + legacy paths
# CLEAN_ARGS (flags stripped) written to ${TMPDIR:-/tmp}/dev-review-clean-args
REVIEW_ARGS=$(cat "${TMPDIR:-/tmp}/dev-review-clean-args" 2>/dev/null || echo "$ARGUMENTS")
CHALLENGE_ENABLED=$(cat "${TMPDIR:-/tmp}/dev-review-challenge-enabled" 2>/dev/null || echo "true")
SEMBLE_ENABLED=$(cat "${TMPDIR:-/tmp}/dev-review-semble-enabled" 2>/dev/null || echo "false")
CODEMAP_RAW=$(cat "${TMPDIR:-/tmp}/dev-review-codemap-enabled" 2>/dev/null || echo "auto")
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

```bash
# Codemap auto-detection — normalize CODEMAP_RAW to true/false; strict exits on unavailability  # timeout: 5000
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_RAW")
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    [ "$CODEMAP_RAW" = "strict" ] && exit 1
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED" > ${TMPDIR:-/tmp}/dev-review-codemap-enabled
# codemap: integrated-via-shared
```

> loads: codemap-gates.md

Read `$_DEV_SHARED/codemap-gates.md` — follow Gate A and Gate B.

If `SEMBLE_ENABLED=true`: verify `mcp__semble__search` in available tools. DMI skill — stop enforced via bash exit when semble not configured:

```bash
# timeout: 5000
SEMBLE_ENABLED=$(cat ${TMPDIR:-/tmp}/dev-review-semble-enabled 2>/dev/null || echo false)
if [ "$SEMBLE_ENABLED" = "true" ]; then
    # Semble MCP availability cannot be reliably verified in bash — check must be done in LLM context.
    # If mcp__semble__search is NOT available in your tools when you reach this point:
    #   echo "! --semble requested but semble MCP server not configured. Configure: claude mcp add semble -s user -- uvx --from 'semble[mcp]' semble"
    #   exit 1
    echo "⚠ --semble enabled: verify mcp__semble__search is available in your tools before proceeding; if absent, abort with error above"
fi
```

Use `$REVIEW_ARGS` (not `$ARGUMENTS`) as path for rest of workflow.

## Step 1: Identify scope

```bash
if [ -n "$REVIEW_ARGS" ]; then
    # Path given directly — collect Python files under it
    TARGET="$REVIEW_ARGS"
    echo "Reviewing: $TARGET"
else
    # No argument — review current working-tree diff vs HEAD
    git diff HEAD --name-only  # timeout: 3000
    TARGET="working-tree diff ($(git diff HEAD --name-only 2>/dev/null | grep '\.py$' | wc -l | tr -d ' ') Python files)"  # timeout: 3000
fi
```

**Non-Python impact check** (runs BEFORE early exit — ensures warning always emits when relevant): scan diff for high-impact non-Python changes; collect warnings for report header:

```bash
# timeout: 5000
NON_PY_WARNINGS=""
git diff --name-only HEAD 2>/dev/null | grep -qE '(pyproject\.toml|setup\.cfg|requirements.*\.txt)' && NON_PY_WARNINGS="${NON_PY_WARNINGS}⚠ dependency changes detected — not reviewed; verify Python imports still resolve\n"
git diff --name-only HEAD 2>/dev/null | grep -qE '(Dockerfile|docker-compose.*\.yml)' && NON_PY_WARNINGS="${NON_PY_WARNINGS}⚠ container config changes detected — not reviewed\n"
```

If `$NON_PY_WARNINGS` non-empty: include in report header regardless of whether Python files exist.

Filter to Python files only. No Python files → exit early (DMI skill — prose "stop" not executable; bash exit is the only enforceable mechanism):

```bash
# timeout: 5000
if [ -n "$REVIEW_ARGS" ]; then
    PYTHON_FILES=$(find "$REVIEW_ARGS" -name '*.py' -type f 2>/dev/null | head -1)
else
    PYTHON_FILES=$(git diff --name-only HEAD 2>/dev/null | grep '\.py$' | head -1)
fi
if [ -z "$PYTHON_FILES" ]; then
    echo "! Diff contains non-Python files only. This skill is scoped to Python. For other languages, use a general-purpose code reviewer."
    [ -n "$NON_PY_WARNINGS" ] && printf "$NON_PY_WARNINGS"
    exit 0
fi
```

### Scope pre-check

Before spawning agents, classify diff:

- Count files changed, lines added/removed, new classes/modules introduced
- Classify: **FIX** (corrects wrong behavior), **REFACTOR** (same behavior restructured), **FEATURE** (new public API or capability), **CHORE** (config/deps, no logic), **MIXED** — classify by intent, not file count
- **Complexity smell**: 8+ files changed → note in report header

Skip optional agents by classification:

- FIX → skip Agent 3 (perf-optimizer) and Agent 6 (solution-architect)
- REFACTOR → skip Agent 6 (solution-architect)
- FEATURE/MIXED → spawn all agents

### Structural context + review pre-flight (codemap — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`** — sets `codemap_available=false` for downstream agent prompts; agents fall back to file reads.

Extended scan for changed modules — runs the v4 pre-flight queries per module, persists structured output to `$RUN_DIR/codemap-context.md`, and sets `codemap_available` flag for Step 3 agent spawns:

```bash
codemap_available=false
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
CODEMAP_ENABLED=$(cat ${TMPDIR:-/tmp}/dev-review-codemap-enabled 2>/dev/null || echo false)
if [ "$CODEMAP_ENABLED" = "true" ]; then
    codemap_available=true
    # src-layout assumed; files outside src/ (scripts/, tools/) may not be valid importable modules — scan-query returns empty, not error
    CHANGED_MODS=$(git diff HEAD --name-only | grep '\.py$' | sed 's|^src/||;s|\.py$||;s|/|.|g' | grep -v '__init__$')  # timeout: 3000
    if [ -z "$CHANGED_MODS" ]; then
        CHANGED_MODS=$(git diff HEAD --name-only | grep '\.py$' | sed 's|/[^/]*\.py$||' | sort -u | head -10)
    fi
    # RUN_DIR not yet created (happens in Step 2); stage to TMPDIR; orchestrator copies into $RUN_DIR/codemap-context.md after mkdir.
    # scan-query PATH guarantee: CODEMAP_ENABLED=true only after codemap-resolve confirmed scan-query on PATH (via bin/codemap-resolve). Bare `scan-query` invocations below are safe.
    CODEMAP_CONTEXT_STAGE="${TMPDIR:-/tmp}/dev-review-codemap-context.md"
    {
        echo "## Structural Context (codemap)"
        echo
        echo "### Global blast-radius baseline"
        scan-query --timeout 5 central --top 5 2>/dev/null
        echo
        for mod in $CHANGED_MODS; do
            echo "### Module: $mod"
            scan-query --timeout 5 rdeps        "$mod"          2>/dev/null  # importer count → high/moderate/low risk tier
            scan-query --timeout 5 fn-rdeps    "$mod" --exclude-tests 2>/dev/null  # direct callers
            scan-query --timeout 5 fn-blast     "$mod"          2>/dev/null  # caller impact (v3)
            scan-query --timeout 5 mock-rdeps   "$mod"          2>/dev/null  # mock test coverage (v4.1)
            scan-query --timeout 5 uncovered    --top 20 "$mod" 2>/dev/null  # test gaps (v4.2)
            scan-query --timeout 5 xrefs --broken        "$mod" 2>/dev/null  # stale doc refs (v4.5)
            scan-query --timeout 5 undocumented "$mod" 2>/dev/null  # doc coverage (v4.4)
            echo
        done
    } > "$CODEMAP_CONTEXT_STAGE"
fi
echo "$codemap_available" > "${TMPDIR:-/tmp}/dev-review-codemap-available"
```

Codemap context propagation in Step 3:

- `codemap_available=true` → copy `$CODEMAP_CONTEXT_STAGE` to `$RUN_DIR/codemap-context.md` once `$RUN_DIR` exists (Step 2). Every dimension-agent spawn prompt (Agents 1–6) must include a literal block:
  ```text
  ## Structural Context (codemap, codemap_available=true)
  <content of $RUN_DIR/codemap-context.md>

  Read this section first. For symbols listed in `uncovered`/`mock-rdeps`/`undocumented`/`xrefs --broken`/`fn-blast`, trust the codemap output; skip redundant Grep/Read on the same data. Fall back to file reads only when codemap output is empty for a symbol you need or when verifying a specific finding.
  ```
- `codemap_available=false` → omit the block; agents proceed with current file-read behaviour.

Tier annotation for Agent 1 (sw-engineer) only: label each module's `imported_by` count — **high risk** (>20), **moderate** (5–20), **low** (<5). Agent 1 uses this to prioritize: high `imported_by` modules warrant deeper scrutiny on API compatibility, error handling, behavioural correctness — downstream callers outside diff not otherwise visible.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt:

> If `mcp__semble__search` is available in your tools and any changed module's codemap result was non-exhaustive (`"exhaustive": false`) or no codemap index found: call `mcp__semble__search` with varied queries and `repo=<git_root>`, `top_k=20`. Stop per module when two consecutive queries return no new importers. Merge with codemap results. If `mcp__semble__search` is NOT available (MCP not activated in this session): use Grep and Glob tools as fallback for code search — search for import references and usages of changed modules using `Grep(pattern="from <module>|import <module>", path=".")`.

## Step 2: Codex co-review

Set up run directory:

```bash
TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".temp/review/$TIMESTAMP"
mkdir -p "$RUN_DIR"  # timeout: 5000
RUN_DIR_LITERAL="$RUN_DIR"
REPORT_DIR=".reports/review/$TIMESTAMP"
mkdir -p "$REPORT_DIR"  # timeout: 5000
REPORT_DIR_LITERAL="$REPORT_DIR"
```

Check availability:

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && echo "codex (openai-codex) available" || echo "⚠ codex (openai-codex) not found — skipping co-review"  # timeout: 15000
```

Materialize codemap context into the run directory (`$RUN_DIR` now exists):

```bash
codemap_available=$(cat "${TMPDIR:-/tmp}/dev-review-codemap-available" 2>/dev/null || echo "false")
if [ "$codemap_available" = "true" ] && [ -f "${TMPDIR:-/tmp}/dev-review-codemap-context.md" ]; then
    cp "${TMPDIR:-/tmp}/dev-review-codemap-context.md" "$RUN_DIR/codemap-context.md"
fi
```

If Codex available:

```bash
CODEX_OUT="$RUN_DIR/codex.md"
echo "$CODEX_OUT" > ${TMPDIR:-/tmp}/dev-review-codex-out  # persist for Step 6 — Bash() state lost between calls
```

If `$_FOUNDRY_SHARED/codex-prepass.md` exists, read it for Codex pass instructions — use those instructions as the spawn prompt; inline prompt below is fallback when shared file absent.

Spawn `codex:codex-rescue` agent (requires `codex` plugin): "Adversarial review of $TARGET: look for bugs, missed edge cases, incorrect logic, and inconsistencies with existing code patterns. Read-only: do not apply fixes. Write findings to $RUN_DIR/codex.md."

Note: Agent spawns are synchronous and cannot be timeout-wrapped via Bash `timeout:`. If hang risk is unacceptable, spawn with `run_in_background=true` — when doing so, implement health-monitoring per CLAUDE.md §6: create sentinel file, poll every 5 min for file activity in `$RUN_DIR`, hard cutoff 15 min. Without background spawning, move on after a reasonable wait (observe if Codex output file grows; no growth after ~2 min → treat as timed out).

After Codex writes `$RUN_DIR/codex.md` (or times out), extract compact seed list (≤10 items, `[{"loc":"file:line","note":"..."}]`) to inject into agent prompts in Step 3 as pre-flagged issues to verify or dismiss. Codex skipped, timed out, or found nothing → proceed with empty seed.

**Cap-disclosure**: count total Codex findings before truncating. If ≥10, surface in consolidated report header:

```text
Codex: first 10 items seeded to review agents; full list in $RUN_DIR/codex.md (N total) — review codex.md directly for complete coverage.
```

Pass notice through to consolidator (Step 5) so it appears in final report header, not just terminal scratch.

## Step 3: Spawn sub-agents in parallel

**File-based handoff**: read `$_FOUNDRY_SHARED/file-handoff-protocol.md`. Run directory created in Step 2 (`$RUN_DIR`).

<!-- $RUN_DIR pre-expanded into $RUN_DIR_LITERAL, $REPORT_DIR into $REPORT_DIR_LITERAL — substitute literal vars (never bare $RUN_DIR/$REPORT_DIR) in Agent spawn prompt strings. -->

Use `$RUN_DIR_LITERAL` in spawn prompts below — substitute expanded value before building each Agent call.

Resolve develop:review checklist path (version-agnostic):

```bash
if ! command -v jq >/dev/null 2>&1; then
    echo "⚠ jq not available — oss:review checklist path resolution skipped; Agent 1 will proceed without checklist"
    REVIEW_CHECKLIST=""
fi
```

```bash
if command -v jq >/dev/null 2>&1; then
    OSS_ROOT=$(jq -r 'to_entries[] | select(.key | test("oss@")) | .value.installPath' ${HOME}/.claude/plugins/installed_plugins.json 2>/dev/null | head -1) || OSS_ROOT=""  # timeout: 5000; jq parse failure → empty string, handled below
    if [ -z "$OSS_ROOT" ]; then
        echo "⚠ oss plugin checklist unavailable — review will proceed without severity anchors; install oss plugin for full coverage"
        REVIEW_CHECKLIST=""
    else
        REVIEW_CHECKLIST="${OSS_ROOT}/skills/review/checklist.md"
        if [ ! -f "$REVIEW_CHECKLIST" ]; then
            echo "⚠ oss plugin checklist unavailable — review will proceed without severity anchors; install oss plugin for full coverage"
            REVIEW_CHECKLIST=""
        else
            echo "Checklist: $REVIEW_CHECKLIST"
        fi
    fi
fi
```

Replace `$REVIEW_CHECKLIST` in Agent 1 and consolidator spawn prompts with resolved path. **If empty, omit checklist instruction from those prompts entirely** — do not pass empty path.

**Pre-expansion required**: `$REVIEW_CHECKLIST` must be substituted with literal resolved value before inserting into any Agent spawn prompt string — same as `$RUN_DIR_LITERAL`. Never pass bare variable name `$REVIEW_CHECKLIST` inside quoted Agent prompt; subshell won't expand it.

**Visible-degradation rule** — `$REVIEW_CHECKLIST` empty → print `⚠ REVIEW_CHECKLIST is empty — review scope undefined` at the TOP of the review output (before Findings), and consolidator prompt (Step 5) **must** insert into the report header (YAML `---` block or first line before Findings): "Review checklist not applied (oss plugin not available) — severity anchors may be inconsistent." Silent degradation hides gap from reviewers, makes severity drift invisible.

**Finding evidence standard — applies to every agent, every finding:**

- Every finding must cite specific `file:line` from the diff as primary evidence — "I know this typically causes issues" without a diff citation is not a valid finding
- Training knowledge and memory are never sufficient evidence — read the actual code in the diff
- Claims referencing external standards (OWASP, PEP, language spec, CVE) must cite the specific authoritative document — official spec, CVE entry, PEP text; a blog post or Stack Overflow answer referencing the standard is Tier 2 only
- Tier 2 sources (blog, tutorial, forum, memory) require ≥3 genuinely independent sources OR experimental validation before the claim becomes a finding; independent means different authors, different primary research with distinct origins — N posts all citing the same original = 1 source
- Citation tracing mandatory: for each Tier 2 source, follow its citations one level; if tracing reveals a Tier 1 source (official doc, CVE, spec) that confirms the claim, treat as Tier 1 verified; if multiple Tier 2 sources share one origin, merge them into one; count distinct origins only
- When only Tier 2 available, distinct-origin count < 3, and no experiment run: downgrade finding to LOW or drop it; never raise MEDIUM/HIGH/CRITICAL on Tier 2 alone

Launch agents simultaneously with Agent tool (security augmentation folded into Agent 1 — not separate spawn; Agent 6 optional). Every agent prompt must end with:

> "Write your FULL findings (all sections, Confidence block) to `$RUN_DIR_LITERAL/<agent-name>.md` using the Write tool — where `<agent-name>` is e.g. `sw-engineer`, `qa-specialist`, `perf-optimizer`, `doc-scribe`, `linting-expert`, `solution-architect`. Then return to the caller ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"findings\":N,\"severity\":{\"critical\":0,\"high\":1,\"medium\":2,\"low\":0},\"file\":\"$RUN_DIR_LITERAL/<agent-name>.md\",\"confidence\":0.88}`"

**Codemap context preamble (substituted by orchestrator)**: rehydrate `codemap_available=$(cat ${TMPDIR:-/tmp}/dev-review-codemap-available 2>/dev/null || echo false)`. When `codemap_available=true`, every dimension-agent prompt (Agents 1–6) is prefixed with the `## Structural Context (codemap, codemap_available=true)` block from `$RUN_DIR/codemap-context.md` per the propagation rules in Step 1. Agents must read that block first and skip redundant Grep/Read on symbols already covered by codemap output. Block absent → fall back to current file-read behaviour. Challenger (Agent 7) is unchanged.

**Agent 1 — foundry:sw-engineer**: Review architecture, SOLID adherence, type safety, error handling, code structure. Check Python anti-patterns (bare `except:`, `import *`, mutable defaults). Flag blocking issues vs suggestions. `codemap_available=true`: read `fn-blast` first — skip caller-walk Reads on listed callers; verify only when needed for a specific finding.

**Error path analysis** (new/changed code in diff): For each error-handling path introduced or modified, produce table:

| Location | Exception/Error | Caught? | Action if caught | User-visible? |
| --- | --- | --- | --- | --- |

Flag rules:

- Caught=No + User-visible=Silent → **HIGH** (unhandled error path)
- Caught=Yes + Action=`pass` or bare `except` → **MEDIUM** (swallowed error)
- Cap at 15 rows. New/changed paths only, not entire codebase.

Read review checklist (Read tool → `$REVIEW_CHECKLIST`) — apply CRITICAL/HIGH patterns as severity anchors. Respect suppressions list.

**Agent 2 — foundry:qa-specialist**: Audit test coverage. Identify untested paths, missing edge cases, test quality issues. Check ML-specific issues (non-deterministic tests, missing seed pinning). List top 5 missing tests. `codemap_available=true`: read `uncovered` + `mock-rdeps` sections from the codemap context block first — symbols listed in `uncovered` lack any test rdep; symbols listed in `mock-rdeps` are tested via mock (not falsely "untested"). Skip manual grep/Read of `tests/` for symbols codemap already classifies; fall back to file reads only when codemap output is empty for a symbol you need or when verifying a specific finding. Explicitly check for missing tests in these patterns (GT-level findings, not afterthoughts):

- Concurrent access to shared state (locks or shared variables present)
- Error paths: calling methods in wrong order (e.g., `log()` before `start()`)
- Resource cleanup on exception (file handles, database connections)
- Boundary conditions for division, empty collections, zero-count inputs
- Type-coercion boundary inputs: functions parsing/converting strings to typed values (`int()`, `float()`, `datetime`) — test near-valid inputs (float strings for int parsers, empty strings, very large values, `None`) — common omissions.

**Consolidation rule**: Each test gap = one finding with concise list of test scenarios, not separate findings per scenario. Format: "Missing tests for `parse_numeric()`: empty string, None, very large integers, float-string for int parser." Keeps test coverage section actionable, prevents exceeding 5 items.

**Agent 3 — foundry:perf-optimizer**: Analyze performance issues. Algorithmic complexity, Python loops that should be NumPy/torch ops, repeated computation, unnecessary I/O. ML code: check DataLoader config, mixed precision. Prioritize by impact.

**Agent 4 — foundry:doc-scribe**: Check documentation completeness. Public APIs without docstrings, missing Google style sections, outdated README, CHANGELOG gaps. Verify examples run. `codemap_available=true`: read `undocumented` + `xrefs --broken` sections from the codemap context block first — `undocumented` enumerates symbols missing docstrings; `xrefs --broken` enumerates stale Sphinx refs. Skip docstring-scan Reads on listed symbols; fall back to file reads only when codemap output is empty for a symbol you need or when verifying a specific finding.

- **Algorithmic accuracy check**: Functions computing mathematical results (moving averages, statistics, transforms, distances) — verify docstring behavioral claims match implementation. Deviation from conventional definition → MEDIUM; docstring must document deviation, not state standard definition. **Deprecation check**: Check deprecated stdlib usage in public API surface only — skip private functions, classes, constants, and modules starting with `_`. E.g., `datetime.utcnow()` deprecated in 3.12, `os.path` vs `pathlib`. Flag deprecated stdlib as MEDIUM with replacement.

**Agent 5 — foundry:linting-expert**: Static analysis audit. Check ruff and mypy pass. Type annotation gaps on public APIs, suppressed violations without explanation, missing pre-commit hooks. Flag mismatched target Python version.

**Security augmentation (conditional — fold into Agent 1 prompt, not separate spawn)**: Target touches authentication, user input handling, dependency updates, or serialization → add to foundry:sw-engineer prompt (Agent 1): check SQL injection, XSS, insecure deserialization, hardcoded secrets, missing input validation. If dependency files changed: check pip-audit availability first — `if ! command -v pip-audit >/dev/null 2>&1; then echo "⚠ pip-audit not found — dependency vulnerability check skipped"; else <run pip-audit>; fi`. Skip for purely internal refactoring.

**Agent 6 — foundry:solution-architect (optional, for changes touching public API boundaries)**: Target touches `__init__.py` exports, adds/modifies Protocols or ABCs, changes module structure, or introduces new public classes → evaluate API design quality, coupling impact, backward compatibility. Skip for internal implementation changes.

**Agent 7 — foundry:challenger (skip if `CHALLENGE_ENABLED=false`)**: Adversarial review of design decisions in diff. Attacks assumptions, missing edge cases, security risks, architectural concerns, complexity creep with mandatory refutation step. File-handoff: write full findings to `$RUN_DIR_LITERAL/challenger.md`. Return JSON: `{"status":"done","findings":N,"severity":{"critical":0,"high":0,"medium":0,"low":0},"file":"$RUN_DIR_LITERAL/challenger.md","confidence":0.88}`. Severity mapping: blockers → `high`; concerns → `medium`.

**Challenger severity propagation**: when consolidator (Step 5) reads `challenger.md`, map challenger severity labels to review severity labels before merging — CRITICAL → `critical`, HIGH → `high`, MEDIUM → `medium`, LOW → `low`. Do not drop severity; if challenger uses non-standard labels (e.g. "blocker", "concern"), apply the mapping: blockers → `high`, concerns → `medium`.

**Health monitoring**: Agent calls are synchronous — framework awaits each response natively. No Bash checkpoint polling possible during active Agent call. If an agent returns partial results or errors, use Read tool on `$RUN_DIR/<agent-name>.md` for details. Mark agents that returned empty or error with ⏱ in final report. Never silently omit agents that **failed** (returned error/partial) — they must appear with ⏱ marker. Agents that are **not spawned** (skipped due to mode flags, docs-only, CHORE mode) may be absent from RUN_DIR; consolidator "skip missing" applies only to legitimately-not-spawned agents.

## Step 4: Cross-validate critical/blocking findings

```bash
if [ ! -f "$_FOUNDRY_SHARED/cross-validation-protocol.md" ]; then
    echo "⚠ cross-validation-protocol.md not found at $_FOUNDRY_SHARED — Step 4 skipped; critical findings are unverified. Install foundry plugin or verify _FOUNDRY_SHARED path."
    echo "## Cross-Validation: SKIPPED" >> "$RUN_DIR/cross-validation.md"
    echo "**Reason**: _FOUNDRY_SHARED unavailable — cross-validation protocol not executed." >> "$RUN_DIR/cross-validation.md"
fi
```

If file present: read and follow cross-validation protocol from `$_FOUNDRY_SHARED/cross-validation-protocol.md`. File absent → skip Step 4 (warning printed above).

**Skill-specific**: use **same agent type** that raised finding as verifier (e.g., foundry:sw-engineer verifies foundry:sw-engineer's critical finding).

## Step 5: Consolidate findings

Extract branch and date before constructing output path: `BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')` `DATE=$(date +%Y-%m-%d)`

Spawn **foundry:sw-engineer** consolidator:

<!-- loads: consolidator-prompt.md -->
Read `${CLAUDE_PLUGIN_ROOT:-plugins/develop}/skills/review/templates/consolidator-prompt.md` for full consolidator instructions. Summary: read all finding files in `$RUN_DIR_LITERAL/` (pre-expanded), apply consolidation rules, write report to `$REPORT_DIR_LITERAL/review-report.md`. **Pre-expansion required**: substitute `$RUN_DIR_LITERAL`, `$REPORT_DIR_LITERAL`, `$DATE`, and `$REVIEW_CHECKLIST` with literal resolved values before inserting into spawn prompt — bare variable names will not expand inside Agent prompt strings. Return ONLY compact JSON envelope: `{"status":"done","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"file":"$REPORT_DIR_LITERAL/review-report.md","confidence":0.N,"summary":"<one-line verdict>"}`

Main context receives only one-liner verdict.

**Consolidator-unavailable fallback**: if `Agent` tool deferred or consolidator times out — read each agent finding file from `$RUN_DIR/` directly, apply same precision gate and density rules, synthesize consolidated report, write to `$REPORT_DIR/review-report.md` using Write tool.

Report format — resolve template path first:

```bash
_REVIEW_TEMPLATE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/develop/*/skills/review/templates 2>/dev/null | head -1); [ -z "$_REVIEW_TEMPLATE" ] && _REVIEW_TEMPLATE="${CLAUDE_PLUGIN_ROOT:-plugins/develop}/skills/review/templates"
_REVIEW_TEMPLATE="$_REVIEW_TEMPLATE/review-report.md"
```

Pass `$_REVIEW_TEMPLATE` (pre-expanded literal) into consolidator spawn prompt: "Read `<resolved-template-path>` and use it as output structure."

After parsing confidence scores: any agent scored < 0.7 → prepend **⚠ LOW CONFIDENCE** to that agent's findings section, state gap explicitly. Never silently drop uncertain findings.

Print terminal block (universal rule — quality-gates.md §Report File Format): read `---` header from top of `$REPORT_DIR/review-report.md` (lines 1–15, up to and including closing `---`) and print verbatim as FIRST content of reply. Append `→ saved to $REPORT_DIR/review-report.md`. Report file already contains block — no separate prepend needed. Omit `╔═╗` Re:Anchor box.

## Step 6: Delegate implementation follow-up (optional)

Re-hydrate `CODEX_OUT` from persisted temp file (Bash() state does not survive between calls): `CODEX_OUT=$(cat ${TMPDIR:-/tmp}/dev-review-codex-out 2>/dev/null || echo "")`. Skip Step 6 if `$CODEX_OUT` is empty or the file at that path does not exist.

After consolidating, identify tasks Codex can implement directly — not style violations (pre-commit handles those), but work requiring meaningful code or documentation grounded in actual implementation.

**Delegate to Codex when you can write accurate, specific brief:**

- Public functions with no docstrings — read implementation first, describe what each does so Codex writes real 6-section docstring, not placeholder
- Missing test coverage for concrete, well-defined behaviour — describe exact scenario to test
- Consistent rename across multiple files — name old and new symbol and why flagged

**Do not delegate — require human judgment:**

- Architectural issues, logic errors, security vulnerabilities, behavioural changes
- Any task where accurate description requires guessing

Read `$_FOUNDRY_SHARED/codex-delegation.md`, apply delegation criteria defined there.

Print `### Codex Delegation` section to terminal only when tasks actually delegated — omit entirely if nothing delegated.

**Follow-up gate (NEVER SKIP)** — Call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "What next?"
- (a) label: `/develop:fix` — description: fix identified issues
- (b) label: `/develop:refactor` — description: refactor to address structural findings
- (c) label: `walk through findings` — description: go through each finding interactively
- (d) label: `skip` — description: no action

**Confidence block** — emitted by the consolidator agent in `$REPORT_DIR/review-report.md`, not at skill level (DMI skill: top-level model invocation is disabled, so any skill-level instruction would be unreachable).

</workflow>

<notes>

- Critical issues always surfaced regardless of scope
- Skip sections with no issues — no padding with "looks good". Reviewing isolated code without git context → skip Performance Concerns unless code itself shows performance issues.
- **Signal-to-noise gate**: Function or class ≤50 lines with only 1–2 ground-level issues (critical/high) → no more than 2 medium/low findings beyond them. Remainder as `[nit]` in dedicated "Minor Observations" section — not elevated to same tier as high-severity findings.
- **Follow-up chains**:
  - `[blocking]` bugs or regressions → `/develop:fix` to reproduce with test and apply targeted fix
  - Structural or quality issues → `/develop:refactor` for test-first improvements
  - Security findings in auth/input/deps → run `pip-audit` for dependency CVEs; address OWASP issues inline via `/develop:fix`
  - Mechanical issues beyond Step 5 findings → `/codex:codex-rescue <task>` to delegate (requires `codex` plugin)
  - Contributor-facing review of GitHub PR → use `/oss:review <PR#>` (requires oss plugin) instead
- **Parallel agent cleanup**: after all 7 agents complete, review `TaskList` — delete any tasks created by sub-agents (not by lead orchestrator). Sub-agent task creation is unintended, can leave zombie tasks.

</notes>
