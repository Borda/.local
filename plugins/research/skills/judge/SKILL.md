---
name: judge
description: "Research-supervisor review of program.md — validates experimental methodology (hypothesis clarity, measurement validity, control adequacy, scope, strategy fit), emits APPROVED / NEEDS-REVISION / BLOCKED verdict before expensive run loop."
argument-hint: "[<program.md>] [--skip-validation]"
effort: medium
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Research-supervisor review of `program.md` — validates experimental methodology, emits APPROVED / NEEDS-REVISION / BLOCKED verdict before expensive run loop. Read-only; never modifies code or state.

NOT for: running experiments (use `/research:run`); designing hypotheses (use `research:scientist` agent); config quality (`/foundry:audit` (requires `foundry` plugin)).

</objective>

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents: `foundry:solution-architect`, `research:scientist`.

| Agent | Fallback if absent |
| --- | --- |
| `foundry:solution-architect` | `general-purpose` (methodology review quality reduced — **⚠ general-purpose agent may not emit `methodology_rating` in required format; verdict defaults to NEEDS-REVISION**) |
| `research:scientist` | `general-purpose` (scientific rigor review quality reduced — **⚠ general-purpose agent may not emit `scientific_rating`; verdict defaults to NEEDS-REVISION**) |

## Judge Mode (Steps J1–J6)

Triggered by `judge` or `judge <file.md>`.

**Task tracking**: create tasks for J1, J2, J3, J4, J5 (includes J5a + J5b sub-steps), J6 at start — before any tool calls.

## Step J1: Locate and parse program.md

**Flag parsing** (first action):

```bash
SKIP_VALIDATION=false
[[ "$ARGUMENTS" == *"--skip-validation"* ]] && SKIP_VALIDATION=true
ARGUMENTS="${ARGUMENTS/--skip-validation/}"  # strip flag from args
ARGUMENTS="${ARGUMENTS#"${ARGUMENTS%%[![:space:]]*}"}"  # trim leading whitespace
```

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--skip-validation\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Input resolution** (priority order):

1. Explicit argument: `/research:judge path/to/plan.md`
2. Auto-detect: `program.md` at project root
3. Latest state: scan `.experiments/state/*/state.json` for most recent with `status: running` and non-null `program_file` field
4. If nothing found: stop with error:
   ```text
   No program.md found. Run /research:plan <goal> first, or provide a path: /research:judge <path.md>
   ```

**Parsing** — find `## <Section>` headings in program.md, extract first fenced code block per section, parse as `key: value` lines, warn on unrecognized keys. `--skip-validation` and `colab_hw` judge-specific, extracted independently.

**Placeholder substitution** — after parsing, apply same substitution as R1: resolve all `{field_name}` tokens in `metric_cmd` and `guard_cmd` using `## Config` fields, fallback to declared default. No `clarification_prompt` in judge — skip clarification-override step.

Extract `<program_title>` from `# Program: <title>` line for reports (fallback `# Campaign: <title>` for legacy files).

## Step J2: Completeness audit

Check 12 items. Produce findings list with severity. Each finding has: `id`, `check`, `status` (pass/fail/warn), `severity`, `detail`.

| ID | Check | Severity if failing | Description |
| --- | --- | --- | --- |
| C1 | `## Goal` present and non-empty | critical | Campaign cannot run without a goal |
| C2 | `## Metric` has `command` field | critical | No metric = no feedback loop |
| C3 | `## Metric` has `direction` field (higher/lower) | critical | Cannot decide keep/revert without direction |
| C4 | `## Guard` has `command` field | critical | Without guard, regressions go undetected. Note: a command field containing only `echo 0`, `true`, or `exit 0` is equivalent to no guard (always exits 0 regardless of test state) — flag as critical with detail "guard command is a no-op; add real regression detection". |
| C5 | `scope_files` present in `## Config` | high | Without scope, ideation agent modifies arbitrary files |
| C6 | Each `scope_files` path exists on disk (glob match) | high | Non-matching patterns = ideation agent has nothing to work with. If filesystem unavailable, flag `warn` unless path name signals non-existence (e.g., `nonexistent`, `placeholder`, `todo`, `legacy_v1`, `deprecated`, `old`, `removed`). |
| C7 | `target` set in `## Metric` | medium | Without target, campaign runs to max_iterations — may waste compute |
| C8 | `max_iterations` in bounds (1–50) | medium | Missing defaults to 20 (acceptable); >50 violates SKILL.md constants. Additionally: if value is within bounds but >20 AND combined with risk factors (C4 fails / guard empty, OR C6 fails / scope non-existent), add a separate `low` finding: "max_iterations=N is elevated; with no functioning guard/scope, runaway iterations amplify risk — consider reducing to ≤15 until guard/scope is fixed" |
| C9 | `agent_strategy` is valid (`auto`/`perf`/`code`/`ml`/`arch`) | medium | Invalid value silently falls back to `auto` |
| C10 | `compute` is valid (`local`/`colab`/`docker`) | low | Invalid defaults to `local` |
| C11 | `colab_hw` valid (if present) | low | `colab_hw` absent OR is one of `H100, L4, T4, A100, V100, A10G, TPUv2, TPUv3, TPUv4` — fail detail: `"colab_hw '<value>' is not in known set {H100, L4, T4, A100, V100, A10G, TPUv2, TPUv3, TPUv4} — may cause GPU identity check failure in run mode"`. Note: this check is a minimum-capability floor — new Colab hardware tiers may exist beyond this list; unknown values are flagged for user verification, not blocked. |
| C12 | `## Notes` section present | low | Notes optional but improve ideation quality |

**Scope adequacy sub-rule (C6b)** — after C6 passes, assess whether `scope_files` is *sufficient* for the stated goal. If the goal type implies known bottleneck locations outside the declared scope, add a `medium` finding:
- Test-speed goal + scope limited to `tests/` only → flag: "conftest.py, fixtures, and test infrastructure outside tests/ are common levers for test runtime; scope may be too narrow"
- Throughput/latency goal + scope limited to single-layer path (e.g., `src/serving/`) → flag: "serving bottlenecks often span middleware, connection pooling, or database layers outside declared scope"
- Any goal where the stated scope excludes a widely-known dependency class → emit medium finding with location `## Config / scope_files`, suggested broader pattern as fix

This is distinct from C6 (path existence) — C6b fires even when the path exists but is likely insufficient.

**Severity summary**: count findings per severity. Any critical finding = verdict cannot be APPROVED. **Enumeration rule**: check ALL 12 items before stopping — do not short-circuit after finding the first critical issue. A program.md can have multiple independent flaws across different severity levels; the Required Changes section must list all of them, not just the verdict-determining one.

**Placeholder token check (C2, C4 sub-rule)** — after confirming `command` present in `## Metric` (C2) and `## Guard` (C4), scan each command for `{...}` tokens. Verify each token's field name exists in `## Config`. Token with no matching field = unresolvable — add `high` finding. Don't flag `{field_name}` tokens as malformed; valid when resolvable.

**Goodhart's Law check (C2b)** — after confirming metric `command` present (C2 passes), assess whether the command operationalizes the stated `## Goal` or measures a proxy. If the metric could improve while the actual goal is NOT achieved, add a `critical` finding:
- metric measures test pass rate but goal is latency reduction → critical: "metric is a correctness proxy, not a latency measure"
- metric measures lint error count but goal is bug density reduction → critical: "pylint score is a gameable proxy; agent can suppress warnings without improving actual quality"
- metric measures a format/style score but goal is functional improvement → critical: "metric does not operationalize the stated goal"

Goodhart findings are `critical` (not just methodology notes) because a broken metric invalidates the entire feedback loop — equivalent impact to C2 (missing command).

**Command feasibility**: J2 validates command fields statically (presence, format). Executability deferred to J4. If `$SKIP_VALIDATION` is `true`, J4 skipped, commands unverified — report as "validation skipped — commands unverified."

## Step J3: Methodology review

Pre-compute run dir before spawning:

```bash
RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/make_run_dir.py" "judge" ".experiments" 2>/dev/null)  # timeout: 5000
```

**Health monitoring** (CLAUDE.md §8) — create both checkpoints BEFORE dispatching any agents:

```bash
_HM_ARCH=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health_monitor_start.py" "judge-architect" 2>/dev/null)  # timeout: 5000
LAUNCH_AT=$(echo "$_HM_ARCH" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT=$(echo "$_HM_ARCH" | grep '^SENTINEL=' | cut -d= -f2)
_HM_SCI=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health_monitor_start.py" "judge-scientist" 2>/dev/null)  # timeout: 5000
LAUNCH_AT_SCI=$(echo "$_HM_SCI" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT_SCI=$(echo "$_HM_SCI" | grep '^SENTINEL=' | cut -d= -f2)
```

Then dispatch both agents (architect + scientist) in a single response.

Before constructing the J3 prompts, expand all bash variables into concrete paths — never pass literal `<path_to_program.md>` or `<RUN_DIR>` placeholders to agents:

```bash
PROGRAM_PATH=$(realpath "$PROGRAM_FILE" 2>/dev/null || echo "$PROGRAM_FILE")
# RUN_DIR was assigned earlier in J3 via make_run_dir.py
J3_ARCH_PROMPT="Act as a research supervisor reviewing a PhD student's experimental protocol.
Your job is NOT to predict whether the experiment will succeed — it is to judge whether the experimental design is methodologically sound and whether the student should be allowed to proceed.

Read the campaign program file at ${PROGRAM_PATH}.
Also read the codebase (Glob **/*.py, **/*.ts, **/*.js at project root, limit 50 files) for structural context.

(Remainder of architect prompt follows verbatim — see prompt template below for the full text; substitute ${RUN_DIR} for each <RUN_DIR> token in the template.)"
```

Spawn `foundry:solution-architect` via `Agent(subagent_type="foundry:solution-architect", prompt=$J3_ARCH_PROMPT)` (uses `opusplan`). The full prompt template (expand `${PROGRAM_PATH}` and `${RUN_DIR}` before passing):

```markdown
Act as a research supervisor reviewing a PhD student's experimental protocol.
Your job is NOT to predict whether the experiment will succeed — it is to judge whether the experimental design is methodologically sound and whether the student should be allowed to proceed.

Read the campaign program file at ${PROGRAM_PATH}.
Also read the codebase (Glob **/*.py, **/*.ts, **/*.js at project root, limit 50 files) for structural context.

Review the experimental protocol across seven dimensions:

1. **Hypothesis clarity**: Is the `## Goal` a clear, testable hypothesis? Can you tell what constitutes success vs failure? Vague goals produce unfocused experiments — flag if the hypothesis is ambiguous.
2. **Measurement validity**: Does `<metric_cmd>` correctly operationalize the hypothesis? Does it measure what the goal actually intends? Could the metric move in the right direction while the underlying goal is NOT achieved (Goodhart's Law)? Could noise dominate signal at the expected delta scale? **Goodhart's Law is a verdict-level issue** — if this metric could improve while the actual goal is NOT achieved, rate `methodology_rating` as `fundamentally-flawed`, not `needs-refinement`.
3. **Control adequacy**: Does `<guard_cmd>` serve as a valid control condition? Does it catch regressions that an ideation agent could inadvertently introduce? Is it too strict (would block valid improvements) or too permissive (would miss real breakage)? **Exit-code check**: verify that the guard command's exit code actually depends on test outcomes. Commands using awk with print (not exit), grep -c piped to a shell ignoring the count, or other patterns where exit code is always 0 = critical guard flaw regardless of semantic intent. Flag as critical, not medium.
4. **Experimental scope**: Do the `scope_files` define a coherent experimental boundary? Are there known dependencies outside scope that could confound results? Is the scope too broad (unfocused changes) or too narrow (the real lever is outside scope)?
5. **Protocol consistency**: Is `agent_strategy: <strategy>` logically consistent with the hypothesis type? (e.g., using `perf` strategy to improve code quality is a methodology mismatch — flag it)
6. **Stopping criteria**: Is the termination condition well-defined? A missing `target` means the experiment runs until budget exhaustion — flag if the goal implies a natural stopping point that is not encoded.
7. **Reproducibility concerns**: What aspects of the protocol could produce non-reproducible results across runs? (Flaky tests, non-deterministic metrics, environment-sensitive commands)

Also identify up to 3 **protocol gaps** — specific changes to `program.md` that would make the experiment more rigorous.

Write your full review to `<RUN_DIR>/methodology.md` using the Write tool.
Include a `## Verdict` section with a `methodology_rating`: `sound` (no significant design flaws), `needs-refinement` (fixable issues found), or `fundamentally-flawed` (a core design problem that would invalidate the experiment).
Include a `## Confidence` block per quality-gates.md.
Return ONLY a compact JSON envelope on your final line — nothing else after it:
{"status":"done","review_dimensions":7,"methodology_rating":"sound|needs-refinement|fundamentally-flawed","protocol_gaps":N,"file":"<RUN_DIR>/methodology.md","confidence":0.N,"summary":"<one-line verdict>"}
```

Poll architect every 5 min: `find <RUN_DIR> -newer "$CHECKPOINT" -type f | wc -l` — new files = alive; zero = stalled.

- **Hard cutoff: 15 min** no file activity → timed out
- **One extension (+5 min)**: if `tail -20 <RUN_DIR>/methodology.md` shows active progress, grant one extension; second stall = hard cutoff
- **On timeout**: read `tail -100 <RUN_DIR>/methodology.md`; if file missing or empty, set `methodology_rating = "timed_out"`, continue to J6. Surface with ⏱ in report.

Poll scientist every 5 min: `find <RUN_DIR> -name "scientific-review.md" -newer "$CHECKPOINT_SCI" | wc -l` — file present = alive; zero = stalled.

- **Hard cutoff: 15 min** no file activity → timed out
- **One extension (+5 min)**: if `tail -20 <RUN_DIR>/scientific-review.md` shows active progress, grant one extension; second stall = hard cutoff
- **On timeout**: set `scientific_rating = "timed_out"`, continue to J6; surface with ⏱ in Scientific Rigor section.

Use `methodology_rating` from returned envelope for verdict computation in J6:

- `sound` → supports APPROVED
- `needs-refinement` → supports NEEDS-REVISION
- `fundamentally-flawed` → supports BLOCKED

Also spawn `research:scientist` in parallel (dispatch both at start of J3) to review scientific rigor:

```markdown
Act as an ML research peer reviewer assessing experimental protocol rigor.

Read the campaign program file at <path_to_program.md>.

Review across four dimensions:
1. **Hypothesis falsifiability**: Is the goal precisely stated — can you tell unambiguously when the experiment has succeeded or failed?
2. **Goodhart's Law**: Could the metric improve while the actual goal is NOT achieved? Name any specific proxy-gaming risks. **If yes, rate `scientific_rating` as `fundamentally-flawed`** — a Goodhart metric invalidates the entire feedback loop, equivalent to having no metric at all.
3. **Missing baselines**: What standard controls, ablations, or baselines would a peer reviewer expect that are absent?
4. **Reproducibility risks**: List concrete factors that could produce non-reproducible results (randomness seeds, dataset splits, flaky tests, environment dependencies).

Write findings to `<RUN_DIR>/scientific-review.md`.
Return ONLY: {"status":"done","scientific_rating":"sound|needs-refinement|fundamentally-flawed","issues":N,"file":"<RUN_DIR>/scientific-review.md","confidence":0.N,"summary":"<one-line>"}
```

Use `scientific_rating` as **advisory** in J6 report under **Scientific Rigor** — informs but does not override verdict. Exception: `scientific_rating == "fundamentally-flawed"` (exact match) elevates verdict to BLOCKED.

**Source precedence for `scientific_rating`** (mandatory when both are present):

1. **File-parsed value** from `<RUN_DIR>/scientific-review.md` (read after agent completes) — authoritative
2. **Health-monitor / envelope value** from the agent's returned JSON — advisory only

File-parsed value takes priority over the health monitor value; use the file-parsed value when both are present. Same precedence applies to `methodology_rating` parsed from `<RUN_DIR>/methodology.md` vs the envelope value. Use envelope value only when the file is missing or unparsable (e.g., timeout with no output).

## Step J4: Local validation

> Skip if `$SKIP_VALIDATION` is `true` (parsed in J1). Print: `→ Validation skipped (--skip-validation passed)` and continue to J5. Add a `high` finding: "Executability unverified — metric_cmd and guard_cmd not tested on local machine." This finding persists into J6 — APPROVED is not achievable when `--skip-validation` is set (high > 0 → NEEDS-REVISION at best).

Execute each command once. **Non-blocking** — failures become `critical` findings, not hard stops.

**Substitution invariant** — `metric_cmd` and `guard_cmd` fully resolved in J1. No `{...}` tokens should remain. If any `{field_name}` token still present, add `critical` finding: "Unresolved placeholder `{field_name}` in `<metric_cmd|guard_cmd>` — substitution failed in J1" and skip execution.

```bash
# Metric validation — captures baseline value
# Substitute ${metric_cmd} with the resolved command from J1 before execution
${metric_cmd} 2>&1  # timeout: 360000
```

Parse stdout for float. If found, record as `baseline_value`. If not found or non-zero exit: add critical finding: "Metric command failed or produced no numeric output".

```bash
# Guard validation
# Substitute ${guard_cmd} with the resolved command from J1 before execution
${guard_cmd}  # timeout: 360000
```

If guard exits non-zero: add critical finding: "Guard command exited non-zero (exit <code>): \<first 3 lines of output>".

Record validation results for J6 report.

**Note**: J4 executes on current machine. For cross-machine workflows, pass `--skip-validation`.

## Step J5: Codex adversarial review

Check Codex availability:

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex'
```

**If available**: invoke adversarial review on top 3 critical/high gaps from J2 and J3. Example (replace `<top finding N>` with actual findings):

```text
# codex:codex-rescue = dispatchable adversarial agent; codex:adversarial-review is user-only (/codex:adversarial-review slash command)
Agent(subagent_type="codex:codex-rescue", prompt="Adversarial review of run program: check <top finding 1>, <top finding 2>, and <top finding 3> in the program.md. Read-only: do not apply fixes.")
```

Incorporate Codex findings into overall findings list with `source: "codex"`.

**If unavailable**: print one line and continue:

```text
note: codex plugin not installed — skipping adversarial review (Claude-only judge)
```

## Step J5b: Resolve rating source

Apply rating source precedence before J6 verdict computation — fixes ambiguity when envelope and file-parsed ratings disagree.

For each rating (`methodology_rating`, `scientific_rating`):

1. If `<RUN_DIR>/methodology.md` (or `scientific-review.md`) is present AND parsable, use file-parsed value — authoritative.
2. Else use envelope value from the agent's returned JSON — fallback.
3. Log source used: print `→ methodology_rating source: file | envelope` and `→ scientific_rating source: file | envelope` before entering J6.

Resolved rating values feed directly into J6 verdict table — no further source disambiguation in J6.

## Step J6: Verdict and report

<!-- Confidence threshold: 0.85 per quality-gates.md — update here if quality-gates.md changes -->
<!-- Scoring weight constants (any/critical/high/methodology_rating) are duplicated inline below; if quality-gates.md thresholds change, sync this section too. -->

**Verdict computation** (deterministic — design soundness, not outcome prediction):

Top-to-bottom; **first match wins**. BLOCKED takes precedence — stop at first match.

| Condition | Verdict |
| --- | --- |
| any critical (J2) — exact `critical` severity match | BLOCKED |
| `methodology_rating == "fundamentally-flawed"` (exact string match, J3) | BLOCKED |
| `scientific_rating == "fundamentally-flawed"` (exact string match, J3) | BLOCKED |
| J3 agent timed out (`methodology_rating == "timed_out"` — exact match — or null; note: `timed_out` does **not** trigger BLOCKED — it falls to NEEDS-REVISION) | NEEDS-REVISION |
| 0 critical AND (high > 0 OR `methodology_rating == "needs-refinement"`) | NEEDS-REVISION |
| 0 critical AND 0 high AND `methodology_rating == "sound"` | APPROVED |

**Verdict matching rules**: all `*_rating` comparisons require exact string match. Reject partial/substring matches — e.g., `timed_out_partial` does NOT match `timed_out`; `flawed` does NOT match `fundamentally-flawed`. Use `==` equality only; never `=~`, `startswith`, or pattern matching.

**Goodhart consolidation rule**: Goodhart's Law findings can surface via two paths — J2 C2b (static, produces `critical` finding) and J3 agents (dynamic review, produces `methodology_rating` or `scientific_rating`). Before applying the verdict table, apply this rule: if J3 architect or scientist explicitly flags Goodhart's Law as an issue AND J2 did not already flag it as `critical`, promote it to a `critical` finding in the J2 list (source: "J3-Goodhart"). This ensures both paths produce BLOCKED for Goodhart issues. The architect and scientist prompts already instruct `fundamentally-flawed` for Goodhart — this consolidation handles edge cases where the rating falls below `fundamentally-flawed` but Goodhart is still mentioned.

**Pre-compute**:

```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
```

**Write full report** (never overwrite — use counter loop):
```bash
mkdir -p .reports/research  # timeout: 3000
BASE=".reports/research/judge-$BRANCH-$(date +%Y-%m-%d).md"
OUT="$BASE"; COUNT=2
while [ -f "$OUT" ]; do OUT="${BASE%.md}-${COUNT}.md"; ((COUNT++)); done
```

```markdown
---
Judge — [program_title]
Date:          [YYYY-MM-DD]
Scope:         [path to program.md]
Focus:         experimental protocol validation
Agents:        foundry:solution-architect (J3), research:scientist (J3)
Outcome:       APPROVED | NEEDS-REVISION | BLOCKED
Methodology:   sound | needs-refinement | fundamentally-flawed
Findings:      [N] critical · [N] high · [N] medium · [N] low
Protocol gaps: [N]
Confidence:    [score] — [key gaps]
Next steps:    /research:run <path>  [APPROVED] | fix protocol, re-run /research:judge  [otherwise]
Path:          → .reports/research/judge-<branch>-<date>.md
---

## Judge Report: <program_title>

**Program**: <path to program.md>
**Date**: <date>
**Verdict**: APPROVED | NEEDS-REVISION | BLOCKED

### Completeness Audit
| ID | Check | Status | Severity | Detail |
|----|-------|--------|----------|--------|

### Methodology Review
**Rating**: sound | needs-refinement | fundamentally-flawed | timed-out
Read full review: <RUN_DIR>/methodology.md

- Hypothesis clarity: <one-line finding>
- Measurement validity: <one-line finding>
- Control adequacy: <one-line finding>
- Experimental scope: <one-line finding>
- Protocol consistency: <one-line finding>
- Stopping criteria: <one-line finding>
- Reproducibility: <one-line finding>

**Protocol gaps** (specific improvements to program.md):
1. <gap>
2. <gap>

### Scientific Rigor (advisory)
**Rating**: sound | needs-refinement | fundamentally-flawed | timed-out
Read full review: `<RUN_DIR>/scientific-review.md`

- Hypothesis falsifiability: <one-line finding>
- Goodhart's Law risk: <one-line finding>
- Missing baselines: <one-line finding>
- Reproducibility risks: <one-line finding>

### Dry-Run Results
| Command | Status | Output |
|---------|--------|--------|
| metric_cmd | pass/fail | <baseline value or first error line> |
| guard_cmd | pass/fail | exit 0 or exit N: <first error line> |

(Skipped — `--skip-validation`) [if applicable]

### Codex Review
<findings from Codex adversarial review, annotated with source: "codex">
(Skipped — codex plugin not installed) [if unavailable]

### Required Changes
<ordered list of specific fixes for each non-pass finding, critical first; include exact edits to program.md>

### Supervisor Decision
[APPROVED] Experimental protocol is sound. Proceed: `/research:run <path>`
[NEEDS-REVISION] Refine the protocol (see Required Changes above), then re-submit: `/research:judge <path>`
[BLOCKED] Fundamental design flaw — the experiment as designed cannot produce valid results. Fix items 1-N before proceeding.

## Confidence
**Score**: 0.N — [high|moderate|low]
**Gaps**:
- [specific limitation]
```

**Terminal summary** (compact):

```text
---
Judge — <program_title>
Verdict:      APPROVED | NEEDS-REVISION | BLOCKED
Methodology:  sound | needs-refinement | fundamentally-flawed
Scientific:   sound | needs-refinement | fundamentally-flawed | timed-out  (advisory)
Findings:     <N> critical · <N> high · <N> medium · <N> low
Protocol gaps: <N>
Validation:   metric=<value> guard=pass|fail  (or "skipped — --skip-validation")
Codex:        reviewed | skipped
→ saved to .reports/research/judge-<branch>-<date>.md
---
Next: /research:run <path>                         [APPROVED]
Next: fix protocol, re-run /research:judge <path>      [NEEDS-REVISION or BLOCKED]
```

</workflow>

<notes>

- Judge read-only — never modifies code, commits, or writes to `.experiments/state/`
- `.experiments/judge-<timestamp>/` stores methodology agent's full output
- Validation executes on current machine — use `--skip-validation` for cross-machine workflows
- Verdict deterministic (finding counts + methodology_rating); not inferred from prose
- Re-run judge after editing `program.md` to confirm fixes
- Judge run dirs don't write `result.jsonl` — exempt from automated 30-day TTL cleanup (per `.claude/rules/artifact-lifecycle.md` TTL policy — no `result.jsonl` = cleanup skipped); remove manually (`rm -rf .experiments/judge-*/`)

</notes>
