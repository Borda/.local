---
name: sweep
description: "Non-interactive end-to-end pipeline — auto-configure program.md (accept defaults), run judge+refine loop (up to 3 iterations), then run the campaign. Single command from goal to result."
argument-hint: '"<goal>" [--team] [--compute=local|colab|docker] [--colab[=H100|L4|T4|A100]] [--codex] [--researcher] [--architect] [--journal] [--hypothesis <path>] [--skip-validation] [--out <path>]'
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
effort: high
disable-model-invocation: true
---

<objective>

Non-interactive end-to-end research pipeline: auto-plan → judge gate → run. Single command from goal to result. Accepts goal string, passes all run/colab/team flags.

NOT for: interactive planning (use `/research:plan`); methodology review only (use `/research:judge`); running already-approved plan (use `/research:run`).

</objective>

<workflow>

## Agent Resolution

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

```bash
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`.

Sweep delegates to plan (S2), judge (S3), run (S5) — see each skill's Agent Resolution for fallback handling.

## Steps S1–S5

Triggered by `sweep "goal" [--flags]`. Non-interactive end-to-end: auto-plan → judge gate → run.

**Shared path resolution** (always runs before S1):

`_RESEARCH_SHARED` already resolved above (Agent Resolution block); reuse it here. Additionally resolve `_RESEARCH_SKILLS`:
```bash
_RESEARCH_SKILLS=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/research/*/skills 2>/dev/null | head -1)
[ -z "$_RESEARCH_SKILLS" ] && _RESEARCH_SKILLS="$(git rev-parse --show-toplevel 2>/dev/null)/plugins/research/skills"
```

**Task tracking**: create tasks for S1–S5 at start.

### Step S1: Parse arguments

**Existing program.md guard** — sweep creates a new program.md; if one already exists at the output path (default: `program.md` at project root, or `--out <path>` if provided), invoke `AskUserQuestion` immediately — do NOT silently overwrite, do NOT hard-stop without recovery:

- question: "program.md already exists at `<output path>` — how to proceed?"
- (a) label: `Overwrite and re-sweep` — description: overwrite existing program.md, run plan+judge+run pipeline from scratch
- (b) label: `Abort — use existing program` — description: stop sweep; use `/research:run <program.md>` to execute the existing program

On (a): proceed to flag extraction below. On (b): print follow-up hint and stop. Check AFTER extracting `--out` flag so the correct output path is known before checking. (This is the single overwrite gate — S2 P-P3 is bypassed for sweep since the decision was already made here.)

Extract `<goal>` — first positional argument (quoted or unquoted string describing optimization target).

Extract flags:

- `--colab[=HW]` — passed to plan (Config.compute) and run; if `=HW` present, extract `colab_hw`
- `--compute=local|colab|docker` — passed through
- `--team` — passed through to run
- `--codex` — passed through to run
- `--researcher` — passed through to run; combine with `--architect` for dual-agent SOTA + architectural hypothesis pipeline
- `--architect` — passed through to run; enables architectural hypothesis pass via `foundry:solution-architect`
- `--journal` — passed through to run when present; preserves per-iteration journal entries (requires `--researcher` or `--architect` — enforced by run R2)
- `--hypothesis <path>` — passed through to run when present; preloads hypothesis queue from the given file
- `--skip-validation` — passed to judge step (S3)
- `--out <path>` — optional: write program.md here instead of project root. **`.md` output target is determined solely by `--out` (or the default project-root `program.md`)** — never infer the output path by scanning `<goal>` text for `.md` substrings; the goal string is prose describing the optimization target, not a path argument.

**`--out` validation**: if `--out <path>` provided, validate path BEFORE any extraction or file write:

```bash
# POSIX-compatible path-traversal check (avoids bash-specific [[ ]])
case "$OUT" in
  *..*)
    if [ -n "$OUT" ]; then
      echo "sweep: invalid --out path (path traversal not allowed): $OUT" >&2
      exit 2
    fi
    ;;
esac

# Verify resolved path stays within project root (defense in depth; macOS-compatible)
if [ -n "$OUT" ]; then
    _PROJ_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
    if ! python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/check_output_within_root.py" "$OUT" "$_PROJ_ROOT" 2>/dev/null; then  # timeout: 5000
        echo "sweep: --out path escapes project root: $OUT" >&2
        exit 2
    fi
fi
```

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--team\`, \`--compute\`, \`--colab\`, \`--codex\`, \`--researcher\`, \`--architect\`, \`--journal\`, \`--hypothesis\`, \`--skip-validation\`, \`--out\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

If `<goal>` missing or empty, stop:

```text
⚠ sweep requires a goal prompt.
Usage: /research:sweep "goal description" [--flags]
```

If extracted `<goal>` starts with `--`, treat as flag misparse — stop with `! Misparse: goal starts with '--'. Did you forget to quote the goal or omit it? Usage: /research:sweep "goal description" [--flags]`

### Step S2: Non-interactive plan

First, `Read $_RESEARCH_SKILLS/plan/SKILL.md` to load the plan mode step definitions, then execute steps **P-P1, P-P2, P-P2b and P-P3** from `$_RESEARCH_SKILLS/plan/SKILL.md` (`$_RESEARCH_SKILLS` resolved above S1) (P-P0 skipped — `<goal>` always text string) with overrides:

> Include P-P2b analysis in S2 synthesis — P-P2b findings are scoped hypotheses that need consolidation into the program.md written by P-P3; skipping P-P2b drops hypothesis context from the generated program.

**Mandatory P-P1 codebase scan** — sweep MUST execute P-P1 to derive `metric_cmd` and `guard_cmd` from the codebase. Skipping P-P1 produces a program.md with placeholder commands that fail at run-time. If P-P1 cannot complete (no detectable test runner, no benchmark scripts, no metric command candidates): mark the program as **INCOMPLETE**, do NOT proceed to S3 — print `! sweep: P-P1 codebase scan could not derive metric_cmd/guard_cmd from <project-root>. Program marked INCOMPLETE — manual configuration required. Run /research:plan "<goal>" interactively to configure.` and stop.

- **P-P2 (config presentation)**: Accept all auto-detected defaults without prompting. Print proposed config as informational block prefixed `sweep: auto-config →` — do NOT wait for confirmation.
- If `--colab[=HW]` or `--compute=colab` passed, write `compute: colab` (and `colab_hw: <HW>` if provided) into Config block.
- **scope_files**: derive from goal string — extract domain-relevant file patterns (e.g. goal mentioning "neural network" → `["*.py", "models/**", "train*.py"]`; goal mentioning "config" or "YAML" → `["*.yaml", "*.yml", "*.json"]`). Default `["**/*.py"]` only when goal provides no domain signals. **Multiple keyword matches**: merge (union) all matched patterns. Always include the derived `scope_files` in the `sweep: auto-config →` printout so users can verify before run — users cannot correct silently wrong scope without seeing it.
- **agent_strategy**: set to a value accepted by judge C9 (`auto` / `perf` / `code` / `ml` / `arch`). Map flags to the strategy that matches the **primary ideation agent** run will dispatch (per run/SKILL.md constants table): `--researcher` (with or without `--architect`) → `"ml"` (`research:scientist` is the primary ideation agent for paper-rooted hypotheses); `--architect` alone (no `--researcher`) → `"arch"` (`foundry:solution-architect`); `--team` alone → `"auto"` (team mode generates per-axis hypotheses); no flags → `"auto"`. Never write `"dual-agent: ..."`, `"team"`, `"researcher"`, or `"default"` — those values fail C9. Record the flag combination and dual-agent dispatch intent separately in `## Notes` (e.g. `dispatch: dual-agent (researcher primary + architect feasibility filter)`) so the orchestration intent is preserved without overriding the validated `agent_strategy` field.
- **P-P3 (write program.md)**: Write to `<--out path>` if provided; else `program.md` at project root.
  - If output path exists: enforce the P-P3 AskUserQuestion overwrite gate — sweep does NOT bypass it. The gate's pipeline-mode exemption applies to non-interactive CI pipelines, not user-initiated sweeps. Invoke `AskUserQuestion`: (a) **Overwrite** — proceed; (b) **Abort** — stop. On Abort: print follow-up hint and stop.

Print on completion:

```text
sweep: plan → <output path> ✓
```

### Step S3: Judge + refinement loop

> `$_RESEARCH_SKILLS` resolved in S2 — in scope throughout S3–S5.

Initialize `REFINE_ITER = 0`, `MAX_REFINE = 3`, `NO_FIXES_ITER = 0`.

Repeat up to `MAX_REFINE` times:

1. Increment `REFINE_ITER`. Run judge mode (J1–J6 from `$_RESEARCH_SKILLS/judge/SKILL.md`) against program file.

   - Pass `--skip-validation` if user provided it; else include validation (J4).
   - Capture J6 verdict and judge report path (`JUDGE_REPORT`).

2. Print: `` sweep: judge iteration `REFINE_ITER`/`MAX_REFINE` → `VERDICT`  ``

3. **If `APPROVED`** — exit loop, outcome `approved`.

4. **If `BLOCKED`** — exit loop, outcome `blocked`. No fix attempt — BLOCKED = fundamental design flaw requiring human redesign.

5. **If `NEEDS-REVISION`**:

   - If `REFINE_ITER < MAX_REFINE`:
     - Read `JUDGE_REPORT`. Extract `### Required Changes` section.
     - If `### Required Changes` section absent: increment `NO_FIXES_ITER`. If `NO_FIXES_ITER >= 2` (two consecutive judge runs returning NEEDS-REVISION without a `### Required Changes` section): exit loop with outcome `judge-report-malformed` and print `! sweep: judge emitted NEEDS-REVISION but report contains no Required Changes section in 2 consecutive iterations — possible judge formatting issue. Inspect <JUDGE_REPORT>.` Invoke `AskUserQuestion` — (a) `proceed to run anyway` · (b) `abort`. On (a): proceed to S5. On (b): print follow-up hint and stop. Otherwise (NO_FIXES_ITER < 2): print `sweep: judge report missing Required Changes section — re-judging without edits (NO_FIXES_ITER=N)` and continue loop (re-judge with unchanged file).
     - If present: reset `NO_FIXES_ITER = 0`. Apply each fix to program file via Edit tool. **Always re-read the program file before each sequential Edit call; never assume file content is stable between tool calls** — earlier Edits in this batch may have shifted line offsets or modified surrounding context, so a stale `old_string` from the judge report may no longer match. Count applied fixes as `N_FIXES`; track failures as `N_FAILS`. If any Edit call fails (old_string not found or not unique): increment `N_FAILS`, continue remaining fixes. After all fixes attempted: if `N_FAILS > 0`, print `⚠ N_FAILS edit(s) failed — file may have changed since judge run; re-judging with partial fixes (N_FIXES applied)`. If `N_FIXES == 0` AND `N_FAILS > 0`: print `! All edits failed — re-judging without changes (edit conflict; check program file manually)`. Print: `sweep: applied N_FIXES fix(es) to <program path> — re-judging`
     - Continue next iteration (loop item #1 will re-judge).
   - If `REFINE_ITER == MAX_REFINE` — exit loop, outcome `unresolved`.

> **Safety net**: loop edits modify `program.md` in place; the P-P3 overwrite gate ensures user-authorized overwrite before S2 writes. Recover the prior file from git if needed.

### Step S4: Gate on loop outcome

| Outcome | Action |
| --- | --- |
| `approved` | Print `sweep: plan approved (REFINE_ITER/MAX_REFINE iteration(s)) ✓` → proceed to S5 |
| `blocked` | Print `sweep: judge → BLOCKED ✗`; show all critical findings from report; print follow-up hint; stop |
| `unresolved` | Print `sweep: judge unresolved after MAX_REFINE iterations ✗`; show remaining Required Changes from last report; call `AskUserQuestion` tool — do NOT write options as plain text: question "Unresolved — how to proceed?", (a) label `proceed to run anyway`, (b) label `fix manually then re-run`, (c) label `abort` — if `a`, proceed to S5; if `b` or `c`, print follow-up hint and stop |
| `judge-report-malformed` | S3 already invoked `AskUserQuestion` with (a) proceed / (b) abort and handled the answer — S4 is a no-op for this outcome (S3 already proceeded to S5 or stopped). |

Follow-up hint (blocked or unresolved):

```text
Fix the issues above in <program path>, then:
  /research:judge <program path>          ← re-validate
  /research:run <program path>            ← run when approved
  /research:sweep "revised goal" [flags]  ← re-sweep from scratch
```

### Step S5: Run

Run Default Mode (R1–R7 from `$_RESEARCH_SKILLS/run/SKILL.md`) passing program file from S2 as the first positional argument, plus all flags:

- `--colab[=HW]` / `--compute`
- `--team`
- `--codex`
- `--researcher` / `--architect` (combine for dual-agent pipeline)
- `--journal` — forward when present in the original sweep invocation
- `--hypothesis <path>` — forward when present in the original sweep invocation

> **Flag-forwarding invariant**: any of `--journal` / `--hypothesis` set at sweep entry MUST appear in the S5 run invocation. Dropping them silently breaks resume continuity and the hypothesis queue.

> **`--team` and interactivity**: when `--team` passed, sweep semi-interactive — run mode Phase B presents user confirmation gate before Phase C. Gate cannot be bypassed from sweep context; sweep pauses and waits. Expected behavior.

On completion, standard R6 terminal summary printed. Also prepend:

```text
sweep: complete — plan → judge → run pipeline finished
```

</workflow>

<notes>

- **Overwrite gate** (S2): when output path exists, sweep enforces the P-P3 AskUserQuestion gate — no silent `.bak` rename + overwrite. Pipeline exemption applies to non-interactive CI pipelines only, not user-initiated sweeps. Use git to recover the prior file if needed.
- **`--journal` and `--hypothesis` forwarded when present**: both flags pass through to S5 verbatim; sweep does not strip them. `--journal` requires `--researcher` or `--architect` (validated at run R2). `--hypothesis <path>` preloads the hypothesis queue.
- **`--team` and interactivity**: sweep non-interactive except when `--team` active. Team mode Phase B presents user confirmation gate before Phase C — sweep pauses and waits. Expected; sweep cannot bypass Phase B gate. In automated/CI contexts where interaction is impossible, avoid `--team` flag or pre-confirm via the gate prompt manually; there is no `--auto` flag to suppress Phase B — this is by design (Phase B reviews potentially risky parallel agent decisions).
- **`--skip-validation`**: passes through to judge step (S3). Useful for cross-machine workflows where metric/guard commands run only on target machine.
- **Metric direction conventions** (S2 auto-config): minimize for loss/error/latency metrics (loss, error_rate, mse, mae, latency, time); maximize for quality metrics (accuracy, f1, precision, recall, auc, throughput). When goal string is ambiguous, default to `minimize` and note assumption in config comment.

</notes>
