---
name: review
description: "Multi-agent code review of local Python files, directories, or the current git diff covering architecture, tests, performance, docs, lint, security, and API design. Scope: Python source files in local working tree. Python-file-free targets (pure JS/TS/Go/Rust projects) are out of scope."
argument-hint: "[python-file|dir] [--no-challenge] [--codemap] [--semble]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
effort: high
---

<objective>

Comprehensive code review of local files or working-tree diff. Spawn specialized sub-agents in parallel, consolidate findings into structured feedback with severity levels.

NOT for: GitHub PR review (use `/oss:review <PR#>` (requires oss plugin)); GitHub thread analysis or PR reply drafting (use `/oss:analyse <PR#>` (requires oss plugin)); implementation (use `/develop:feature` or `/develop:fix`); `.claude/` config changes (use `/foundry:manage` (requires foundry plugin) or `/foundry:audit` (requires foundry plugin)); non-Python-only projects (zero Python source files — pure JS/TS/Go/Rust) — review toolchain assumes Python/pytest; for polyglot projects with Python source, reviews Python files only.

</objective>

<inputs>

- **$ARGUMENTS**: optional file path or directory to review.
  - Path given: review those files
  - Omitted: review current git diff (`git diff HEAD` — staged + unstaged vs HEAD)
  - **Scope**: Python source only. Non-Python file (YAML, JSON, shell script, etc.) → state out of scope, suggest appropriate tool. No findings.
  - `--no-challenge`: skip adversarial review (challenger runs by default)
  - `--codemap`: enable structural context from codemap index (off by default)
  - `--semble`: enable semble semantic search companion (off by default)

**Integer detection gate** (execute BEFORE Step 1): if `$ARGUMENTS` is positive integer or matches `#\d+`:

```bash
if [[ "$ARGUMENTS" =~ ^#?[0-9]+$ ]] && [ ! -e "$ARGUMENTS" ]; then
    echo "Integer argument detected — checking oss plugin availability"
    [ -f "$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/review/SKILL.md 2>/dev/null | head -1)" ] && OSS_AVAILABLE=true || OSS_AVAILABLE=false  # timeout: 5000
fi
```

If `$OSS_AVAILABLE` is `true`: call `AskUserQuestion` tool: "Looks like you passed a PR/issue number. Did you mean to run `/oss:review $ARGUMENTS` (requires oss plugin) to review that PR?" Options: (a) "Yes — launch `/oss:review $ARGUMENTS`" → call `Skill(skill="oss:review", args="$ARGUMENTS")`; (b) "No — review local code at a path instead" → ask for path to review.

If `$OSS_AVAILABLE` is `false`: call `AskUserQuestion` tool: "Looks like you passed a PR/issue number, but the oss plugin is not installed — `/oss:review` unavailable. Did you mean to review local code instead?" Options: (a) "Yes — provide a local file or directory path to review"; (b) "I need oss plugin" → inform user: install with `claude plugin install oss@borda-ai-rig`.

</inputs>

<constants>

CHALLENGE_ENABLED=true  # set to false via --no-challenge
CODEMAP_ENABLED=false   # set to true via --codemap
SEMBLE_ENABLED=false    # set to true via --semble

</constants>

<workflow>

<!-- Shared pattern with oss:review — coordinate on agent spawn logic, file-handoff, consolidation changes -->

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (mounted by develop plugin init) -->

## Agent Resolution

```bash
_PATHS=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev-shared-resolve.sh" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:solution-architect`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Flag parsing

Strip flags from `$ARGUMENTS` before using as path:

```bash
REVIEW_ARGS="$ARGUMENTS"
[[ "$REVIEW_ARGS" == *"--no-challenge"* ]] && { CHALLENGE_ENABLED=false; REVIEW_ARGS="${REVIEW_ARGS//--no-challenge/}"; }
[[ "$REVIEW_ARGS" == *"--codemap"* ]]      && { CODEMAP_ENABLED=true;    REVIEW_ARGS="${REVIEW_ARGS//--codemap/}"; }
[[ "$REVIEW_ARGS" == *"--semble"* ]]       && { SEMBLE_ENABLED=true;     REVIEW_ARGS="${REVIEW_ARGS//--semble/}"; }
REVIEW_ARGS="${REVIEW_ARGS#"${REVIEW_ARGS%%[![:space:]]*}"}"  # trim leading whitespace
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

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

If `SEMBLE_ENABLED=true`: verify `mcp__semble__search` in available tools. If not: print `! --semble requested but semble MCP server not configured. Configure: claude mcp add semble -s user -- uvx --from "semble[mcp]" semble` and stop.

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

Filter to Python files only. No Python files → report "no Python files to review" and stop.

**Non-Python impact check**: after filtering, scan diff for high-impact non-Python changes, warn in report header:
- `pyproject.toml`, `setup.cfg`, `requirements*.txt` → "⚠ dependency changes detected — not reviewed; verify Python imports still resolve"
- `Dockerfile`, `docker-compose*.yml` → "⚠ container config changes detected — not reviewed"
- `*.yaml`, `*.toml`, `*.json` in config directories → "⚠ config changes detected — not reviewed"

Out of scope but must be flagged — dependency removal can silently break reviewed Python code.

### Scope pre-check

Before spawning agents, classify diff:

- Count files changed, lines added/removed, new classes/modules introduced
- Classify: **FIX** (\<3 files, \<50 lines), **REFACTOR** (no new public API), **FEATURE** (new public API or module), **MIXED**
- **Complexity smell**: 8+ files changed → note in report header

Skip optional agents by classification:

- FIX → skip Agent 3 (perf-optimizer) and Agent 6 (solution-architect)
- REFACTOR → skip Agent 6 (solution-architect)
- FEATURE/MIXED → spawn all agents

### Structural context (codemap — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`.**

Extended scan for changed modules:

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
CODEMAP_CONTEXT=""
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/scan/${PROJ}.json" ]; then
    CHANGED_MODS=$(git diff HEAD --name-only | grep '\.py$' | sed 's|^src/||;s|\.py$||;s|/|.|g' | grep -v '__init__$')  # timeout: 3000
    # Note: this derivation assumes src-layout (files under src/). Files outside src/ (e.g.
    # scripts/, tools/) produce module names that may not be valid importable modules.
    # scan-query will return empty for these — not an error, just no structural context.
    # flat-layout fallback: if src/-strip yields nothing, try without strip
    if [ -z "$CHANGED_MODS" ]; then
        CHANGED_MODS=$(git diff HEAD --name-only | grep '\.py$' | sed 's|/[^/]*\.py$||' | sort -u | head -10)
    fi
    for mod in $CHANGED_MODS; do
        OUT=$(scan-query rdeps "$mod" 2>/dev/null)  # timeout: 5000
        [ -n "$OUT" ] && CODEMAP_CONTEXT="${CODEMAP_CONTEXT}${OUT}"$'\n'
    done
fi
```

Codemap returns results → prepend `## Structural Context (codemap)` block to **Agent 1 (foundry:sw-engineer)** spawn prompt. Include:

- Each changed module's `rdep_count` — label **high risk** (>20), **moderate** (5–20), **low** (\<5)
- `central --top 5` for project-wide blast-radius reference

Agent 1 uses this to prioritize: high `rdep_count` modules warrant deeper scrutiny on API compatibility, error handling, behavioural correctness — downstream callers outside diff not otherwise visible.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt:

> If `mcp__semble__search` is available in your tools and any changed module's codemap result was non-exhaustive (`"exhaustive": false`) or no codemap index found: call `mcp__semble__search` with varied queries and `repo=<git_root>`, `top_k=20`. Stop per module when two consecutive queries return no new importers. Merge with codemap results.

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

If Codex available:

```bash
CODEX_OUT="$RUN_DIR/codex.md"
```

If `$_FOUNDRY_SHARED/codex-prepass.md` exists, read it for Codex pass instructions — use those instructions as the spawn prompt; inline prompt below is fallback when shared file absent.

Spawn `codex:codex-rescue` agent: "Adversarial review of $TARGET: look for bugs, missed edge cases, incorrect logic, and inconsistencies with existing code patterns. Read-only: do not apply fixes. Write findings to $RUN_DIR/codex.md."

After Codex writes `$RUN_DIR/codex.md`, extract compact seed list (≤10 items, `[{"loc":"file:line","note":"..."}]`) to inject into agent prompts in Step 3 as pre-flagged issues to verify or dismiss. Codex skipped or found nothing → proceed with empty seed.

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
# Guard: jq required for checklist path resolution
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

Launch agents simultaneously with Agent tool (security augmentation folded into Agent 1 — not separate spawn; Agent 6 optional). Every agent prompt must end with:

> "Write your FULL findings (all sections, Confidence block) to `$RUN_DIR_LITERAL/<agent-name>.md` using the Write tool — where `<agent-name>` is e.g. `sw-engineer`, `qa-specialist`, `perf-optimizer`, `doc-scribe`, `linting-expert`, `solution-architect`. Then return to the caller ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"findings\":N,\"severity\":{\"critical\":0,\"high\":1,\"medium\":2,\"low\":0},\"file\":\"$RUN_DIR_LITERAL/<agent-name>.md\",\"confidence\":0.88}`"

**Agent 1 — foundry:sw-engineer**: Review architecture, SOLID adherence, type safety, error handling, code structure. Check Python anti-patterns (bare `except:`, `import *`, mutable defaults). Flag blocking issues vs suggestions.

**Error path analysis** (new/changed code in diff): For each error-handling path introduced or modified, produce table:

| Location | Exception/Error | Caught? | Action if caught | User-visible? |
| --- | --- | --- | --- | --- |

Flag rules:

- Caught=No + User-visible=Silent → **HIGH** (unhandled error path)
- Caught=Yes + Action=`pass` or bare `except` → **MEDIUM** (swallowed error)
- Cap at 15 rows. New/changed paths only, not entire codebase.

Read review checklist (Read tool → `$REVIEW_CHECKLIST`) — apply CRITICAL/HIGH patterns as severity anchors. Respect suppressions list.

**Agent 2 — foundry:qa-specialist**: Audit test coverage. Identify untested paths, missing edge cases, test quality issues. Check ML-specific issues (non-deterministic tests, missing seed pinning). List top 5 missing tests. Explicitly check for missing tests in these patterns (GT-level findings, not afterthoughts):

- Concurrent access to shared state (locks or shared variables present)
- Error paths: calling methods in wrong order (e.g., `log()` before `start()`)
- Resource cleanup on exception (file handles, database connections)
- Boundary conditions for division, empty collections, zero-count inputs
- Type-coercion boundary inputs: functions parsing/converting strings to typed values (`int()`, `float()`, `datetime`) — test near-valid inputs (float strings for int parsers, empty strings, very large values, `None`) — common omissions.

**Consolidation rule**: Each test gap = one finding with concise list of test scenarios, not separate findings per scenario. Format: "Missing tests for `parse_numeric()`: empty string, None, very large integers, float-string for int parser." Keeps test coverage section actionable, prevents exceeding 5 items.

**Agent 3 — foundry:perf-optimizer**: Analyze performance issues. Algorithmic complexity, Python loops that should be NumPy/torch ops, repeated computation, unnecessary I/O. ML code: check DataLoader config, mixed precision. Prioritize by impact.

**Agent 4 — foundry:doc-scribe**: Check documentation completeness. Public APIs without docstrings, missing Google style sections, outdated README, CHANGELOG gaps. Verify examples run.

- **Algorithmic accuracy check**: Functions computing mathematical results (moving averages, statistics, transforms, distances) — verify docstring behavioral claims match implementation. Deviation from conventional definition → MEDIUM; docstring must document deviation, not state standard definition. **Deprecation check**: Check deprecated stdlib usage in public API surface only — skip private functions, classes, constants, and modules starting with `_`. E.g., `datetime.utcnow()` deprecated in 3.12, `os.path` vs `pathlib`. Flag deprecated stdlib as MEDIUM with replacement.

**Agent 5 — foundry:linting-expert**: Static analysis audit. Check ruff and mypy pass. Type annotation gaps on public APIs, suppressed violations without explanation, missing pre-commit hooks. Flag mismatched target Python version.

**Security augmentation (conditional — fold into Agent 1 prompt, not separate spawn)**: Target touches authentication, user input handling, dependency updates, or serialization → add to foundry:sw-engineer prompt (Agent 1): check SQL injection, XSS, insecure deserialization, hardcoded secrets, missing input validation. If dependency files changed: check pip-audit availability first — `if ! command -v pip-audit >/dev/null 2>&1; then echo "⚠ pip-audit not found — dependency vulnerability check skipped"; else <run pip-audit>; fi`. Skip for purely internal refactoring.

**Agent 6 — foundry:solution-architect (optional, for changes touching public API boundaries)**: Target touches `__init__.py` exports, adds/modifies Protocols or ABCs, changes module structure, or introduces new public classes → evaluate API design quality, coupling impact, backward compatibility. Skip for internal implementation changes.

**Agent 7 — foundry:challenger (skip if `CHALLENGE_ENABLED=false`)**: Adversarial review of design decisions in diff. Attacks assumptions, missing edge cases, security risks, architectural concerns, complexity creep with mandatory refutation step. File-handoff: write full findings to `$RUN_DIR_LITERAL/challenger.md`. Return JSON: `{"status":"done","findings":N,"severity":{"critical":0,"high":0,"medium":0,"low":0},"file":"$RUN_DIR_LITERAL/challenger.md","confidence":0.88}`. Severity mapping: blockers → `high`; concerns → `medium`.

**Challenger severity propagation**: when consolidator (Step 5) reads `challenger.md`, map challenger severity labels to review severity labels before merging — CRITICAL → `critical`, HIGH → `high`, MEDIUM → `medium`, LOW → `low`. Do not drop severity; if challenger uses non-standard labels (e.g. "blocker", "concern"), apply the mapping: blockers → `high`, concerns → `medium`.

**Health monitoring**: Agent calls are synchronous — framework awaits each response natively. No Bash checkpoint polling possible during active Agent call. If an agent returns partial results or errors, use Read tool on `$RUN_DIR/<agent-name>.md` for details. Mark agents that returned empty or error with ⏱ in final report. Never silently omit agents that failed.

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

> "Read all finding files in `$RUN_DIR/` (agent files: `sw-engineer.md`, `qa-specialist.md`, `perf-optimizer.md`, `doc-scribe.md`, `linting-expert.md`, `solution-architect.md`, and `codex.md` if present — skip missing). Read `$REVIEW_CHECKLIST` using Read tool and apply consolidation rules (signal-to-noise filter, annotation completeness, section caps). **If `$REVIEW_CHECKLIST` is empty or unset:** insert top-level note into consolidated report Findings section: 'Review checklist not applied (oss plugin not available) — severity anchors may be inconsistent.' Check `$RUN_DIR_LITERAL/cross-validation.md` — if it contains "Cross-Validation: SKIPPED", prepend "⚠ Critical findings unverified — cross-validation protocol unavailable." to the YAML `---` header as `Cross-validation: skipped` field and to the report executive summary. Apply precision gate: only include findings with concrete, actionable location (function, line range, or variable name). Apply finding density rule: modules under 100 lines → aim ≤10 total findings. Rank findings within each section by impact (blocking > critical > high > medium > low). For `codex.md`: include unique findings under `### Codex Co-Review` section; deduplicate against agent findings (same file:line raised by both → keep agent version, mark 'also flagged by Codex'). Parse each agent's `confidence` from its envelope; assign `codex` fixed confidence of 0.75. Write consolidated report to `$REPORT_DIR_LITERAL/review-report.md` using Write tool. After the `## Confidence` block, append `## Source Files` section: use `Glob(pattern="*.md", path="$RUN_DIR")` to list every handover file present (paths relative to repo root, one per line). Return ONLY one-line summary: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=$REPORT_DIR_LITERAL/review-report.md`"

Main context receives only one-liner verdict.

**Consolidator-unavailable fallback**: if `Agent` tool deferred or consolidator times out — read each agent finding file from `$RUN_DIR/` directly, apply same precision gate and density rules, synthesize consolidated report, write to `$REPORT_DIR/review-report.md` using Write tool.

Report format — resolve template path first:

```bash
_REVIEW_TEMPLATE=$(ls ~/.claude/plugins/cache/borda-ai-rig/develop/*/skills/review/templates/review-report.md 2>/dev/null | head -1)
[ -z "$_REVIEW_TEMPLATE" ] && _REVIEW_TEMPLATE="plugins/develop/skills/review/templates/review-report.md"
```

Pass `$_REVIEW_TEMPLATE` (pre-expanded literal) into consolidator spawn prompt: "Read `<resolved-template-path>` and use it as output structure."

After parsing confidence scores: any agent scored < 0.7 → prepend **⚠ LOW CONFIDENCE** to that agent's findings section, state gap explicitly. Never silently drop uncertain findings.

Print terminal block: read `---` header from top of `$REPORT_DIR/review-report.md` (lines 1–12, up to and including closing `---`), append `→ saved to $REPORT_DIR/review-report.md`, print to terminal. Report file already contains block — no separate prepend needed.

## Step 6: Delegate implementation follow-up (optional)

Skip if `$CODEX_OUT` is empty (set in Step 2 when Codex available and wrote output); proceed only when `CODEX_OUT` has a file path.

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

**Confidence block (NEVER SKIP):** end response with `## Confidence` block per CLAUDE.md output standards.

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
