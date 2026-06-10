---
name: investigate
description: 'Systematic diagnosis for unknown failures — local environment, tool setup, CI vs local divergence, hook misbehavior, and runtime anomalies. Gathers signals broadly, ranks hypotheses, uses adversarial review (Codex or foundry:challenger) for ambiguous cases, probes each, and reports root cause with a recommended next action. NOT for known code bugs (/develop:debug (requires `develop` plugin)) or config quality (/foundry:audit). TRIGGER when: unknown failure with no Python traceback — hook not firing, CI passes locally but fails remotely, background agent stalled, behavior inconsistent with config; phrases: "not working but config looks right", "hook not triggering", "why isn''t X running". SKIP: Python traceback present (use develop:debug (requires `develop` plugin)); known code bug with repro (use develop:fix (requires `develop` plugin)); pure config quality check (use foundry:audit).'
argument-hint: "<symptom, question, or failing command> [--fast]"
when_to_use: "Use when something is broken or misbehaving with no clear Python traceback — hook not firing, CI/local divergence, background agent stalled, config looks right but behavior is wrong."
allowed-tools: Read, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
model: opusplan
effort: high
---

<objective>

Diagnose unknown failures: broken local setup, environment mismatch, tool misbehavior, hook problems, CI vs local divergence, permission errors, runtime anomalies. Gather signals broadly, eliminate hypotheses systematically, report confirmed root cause + recommended next skill. No fixes — diagnosis only.

NOT for: known Python test failures with traceback (use `/develop:debug` (requires `develop` plugin)); `.claude/` config quality sweep (use `/foundry:audit`).

</objective>

<inputs>

- **$ARGUMENTS**: required — symptom, question, or failing command, e.g.:
  - `"hooks not firing on Save"`
  - `"codex:codex-rescue agent exits 127 on this machine"`
  - `"/calibrate times out every run"`
  - `"CI fails but passes locally"`
  - `"uv run pytest can't find conftest.py"`

- **`--fast`**: optional flag — skip Step 4 adversarial Codex review; use when speed matters more than thoroughness or Codex unavailable.

If $ARGUMENTS empty or too vague, use AskUserQuestion: "What exactly is failing or behaving unexpectedly? Include the command and any error output you can share."

</inputs>

<workflow>

**Task hygiene**:
```bash
# audit-skip: resilience-replication
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
```
Read `$_FS/task-hygiene.md` — follow task hygiene protocol.

**Task tracking**: TaskCreate tasks for Gather, Hypothesise, Probe, Report; mark in_progress/completed as you go.

## Step 1: Parse symptom and scope

From $ARGUMENTS extract:

- **What**: specific failure or anomaly
- **Where**: local / CI / both; which tool or command; which skill or hook if applicable
- **When**: started recently (after change) or always broken; intermittent or consistent

**Unsupported flag check** — after all supported flags extracted (`--fast`), scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--fast\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Step 2: Gather signals

**Initialise run directory unconditionally at start of Step 2** — `$INVESTIGATE_RUN` must be set even when Step 4 is skipped (`--fast` path), so Step 6's read of `$INVESTIGATE_RUN/*-review.md` does not expand to `/codex-review.md` or an unset reference. Step 4 will only create review files when adversarial review runs; Step 6 must guard reads with `[ -f <path> ]`.

```bash
# timeout: 5000
INVESTIGATE_RUN=".temp/investigate/$(date -u +%Y-%m-%dT%H-%M-%SZ)"
mkdir -p "$INVESTIGATE_RUN"
echo "$INVESTIGATE_RUN" > "${TMPDIR:-/tmp}/investigate-run-path"  # persist for re-resolution in later steps
echo "INVESTIGATE_RUN=$INVESTIGATE_RUN"  # capture this stdout — bash vars do not persist across Bash tool calls
```

Collect evidence in parallel — do NOT form hypotheses yet.

**Tool versions and PATH**:

```bash
which python && python --version                                                                   # timeout: 5000
which uv 2>/dev/null && uv --version 2>/dev/null || echo "uv: not found"                             # timeout: 5000
node --version 2>/dev/null || echo "node: not found"                                                 # timeout: 5000
CODEX_STATUS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_codex.py" 2>/dev/null || echo "false"); echo "codex (openai-codex): $CODEX_STATUS"  # timeout: 5000
```

```bash
env | grep -E 'PATH|VIRTUAL_ENV|UV_|CLAUDE|HOME|SHELL|NODE' | grep -v -E '(_TOKEN|_KEY|_SECRET|_PASSWORD|_PASS)=' | sort # timeout: 5000
```

**Recent changes**:

```bash
git log --oneline -10        # timeout: 3000
git diff HEAD~3..HEAD --stat # timeout: 3000
```

**Config state** (when symptom involves Claude Code, hooks, or skills):

Use Read to check `.claude/settings.json` — look for hook registrations, allow entries relevant to failing command, and `enabledMcpjsonServers`. For `~/.claude/settings.json` (outside allowed Read paths), use Bash:

```bash
jq . ~/.claude/settings.json  # timeout: 5000
```

**Logs** (when symptom involves skill run, background agent, or hook):

Use Grep with pattern `ERROR|WARN|failed|not found|exit` across `.claude/logs/`, `/tmp/`, or relevant `.reports/<skill>/` run dirs. Read last 50 lines of any relevant log file.

Capture all output before Step 3.

After gathering evidence, capture top signals as working notes for Step 4 spawn prompts AND persist them to disk so the values survive the bash-state reset between Steps 2 → 3 → 4:

- `SYMPTOM_DESCRIPTION` — verbatim from `$ARGUMENTS`
- `KEY_SIGNALS` — write 3–5 bullet-point sentences summarizing the most diagnostic signals found above (tool versions, missing binaries, config anomalies, recent changes)

Use the Write tool (NOT a `echo > $INVESTIGATE_RUN/...` heredoc, which loses bash variable state across tool calls) to write the captured values to disk so Step 4 spawn prompts can instruct subagents to Read them rather than relying on inline interpolation:

- `Write(file_path="<INVESTIGATE_RUN>/symptom.txt", content=<SYMPTOM_DESCRIPTION>)` — substitute `<INVESTIGATE_RUN>` with the path printed in the Step 2 bash output above
- `Write(file_path="<INVESTIGATE_RUN>/signals.md", content=<KEY_SIGNALS>)`

Step 4 spawn prompts must instruct the subagent to Read these files (not rely on inline `${SYMPTOM_DESCRIPTION}` interpolation, which the LLM can paraphrase or truncate under context pressure).

## Step 3: Rank hypotheses

List candidate root causes ranked by probability, drawing only from gathered evidence:

| Rank | Hypothesis | Supporting evidence | Ruling-out test |
| --- | --- | --- | --- |
| 1 | … | … | … |
| 2 | … | … | … |
| 3 | … | … | … |

Capture the ranked hypothesis table as `HYPOTHESIS_TABLE` and persist it to disk before Step 4 — use the Write tool:

- `Write(file_path="<INVESTIGATE_RUN>/hypotheses.md", content=<HYPOTHESIS_TABLE>)`

This avoids LLM-paraphrase risk when inlining a long table into a spawn prompt. Step 4 spawn prompts will instruct the subagent to Read this file.

Common categories:

- **Environment mismatch** — tool version differs; wrong virtualenv active; PATH missing entry
- **Missing dependency** — binary not on PATH; package not installed; module import fails
- **Config / permission error** — settings.json allow entry missing; hook path wrong; settings.local.json override
- **State pollution** — stale lock file, leftover tmp artifact, or cached state conflicts with current run
- **Recent change regression** — git commit or config edit introduced issue (check `git log`)
- **Sync drift** — project `.claude/` and `~/.claude/` diverged; compare manually or `/foundry:audit setup`
- **External service** — network unavailable, API rate-limited, or remote tool unreachable

## Step 4: Auxiliary review (optional)

**Skip entirely** when `--fast` passed, or top hypothesis has strong direct evidence. (`foundry:challenger` is always available as part of foundry plugin, so the skip condition simplifies to: skip when `--fast` passed.) Skip → proceed to Step 5.

When `--fast`: mark Step 4 task as `deleted` (not completed — it was skipped).

Otherwise, set up adversarial review. The run dir was already created in Step 2; re-resolve the path string here (bash state does not persist):

```bash
# timeout: 5000
INVESTIGATE_RUN=$(cat "${TMPDIR:-/tmp}/investigate-run-path" 2>/dev/null)
# fallback: pick most recent under .temp/investigate/ if the path file is absent
[ -z "$INVESTIGATE_RUN" ] && INVESTIGATE_RUN=$(find .temp/investigate -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort -Vr | head -1)
CODEX_OUT="$INVESTIGATE_RUN/codex-review.md"
echo "INVESTIGATE_RUN=$INVESTIGATE_RUN"
echo "CODEX_OUT=$CODEX_OUT"  # capture both stdout lines for spawn-prompt substitution below
```

> **Step 2 must also append the resolved run path to `${TMPDIR:-/tmp}/investigate-run-path`** so this resolution succeeds. Add after the `mkdir -p` line in Step 2: `echo "$INVESTIGATE_RUN" > "${TMPDIR:-/tmp}/investigate-run-path"`.

Re-check Codex availability at point of use (bash variables don't persist across tool calls) and **echo the result so the next prose decision can read it**:

```bash
CODEX_AVAILABLE=false
# (1) plugin installed
jq -e 'to_entries[] | select(.key | contains("codex")) | .value[].installPath' ~/.claude/plugins/installed_plugins.json 2>/dev/null | grep -q . && CODEX_AVAILABLE=true  # timeout: 5000
# (2) honor user opt-out — explicit `false` in enabledPlugins disables codex even when installed
if [ "$CODEX_AVAILABLE" = "true" ] && jq -e '.enabledPlugins["codex@openai-codex"] == false' ~/.claude/settings.json >/dev/null 2>&1; then
    CODEX_AVAILABLE=false
    printf "  codex plugin installed but disabled in ~/.claude/settings.json — skipping codex review\n"
fi
echo "CODEX_AVAILABLE=$CODEX_AVAILABLE"  # capture this stdout line — bash vars do not persist across Bash tool calls; the branch decision below MUST read this value, not rely on shell state
```

**Read `CODEX_AVAILABLE=…` from the bash stdout above** (NOT shell state). If the printed value was `true`: spawn Codex; else spawn `foundry:challenger`. The spawn prompts below instruct the subagent to Read the persisted symptom/signals/hypotheses files (written in Steps 2 and 3) — this is more reliable than inlining the values, which the LLM can paraphrase under context pressure.

If Codex available — substitute concrete path strings for `<INVESTIGATE_RUN>` and `<CODEX_OUT>` before constructing the prompt:

```text
Agent(subagent_type="codex:codex-rescue", prompt="Adversarial review of hypothesis quality. Read these files for full context: <INVESTIGATE_RUN>/symptom.txt, <INVESTIGATE_RUN>/signals.md, <INVESTIGATE_RUN>/hypotheses.md. Challenge the top hypothesis, identify blindspots, and surface alternative root causes. Read-only. Write full findings to <CODEX_OUT> using the Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}")
```

Else (Codex unavailable) — substitute `<INVESTIGATE_RUN>` with the printed run-dir path:

```text
Agent(subagent_type="foundry:challenger", prompt="Adversarial review of hypothesis quality. Read these files for full context: <INVESTIGATE_RUN>/symptom.txt, <INVESTIGATE_RUN>/signals.md, <INVESTIGATE_RUN>/hypotheses.md. Challenge the top hypothesis, identify blindspots, and surface alternative root causes. Read-only analysis only. Write full findings to <INVESTIGATE_RUN>/challenger-review.md using the Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}")
```

Verification before issuing the call: scan the constructed prompt string for any remaining `<` or `>` characters — if present, substitution is incomplete; resolve before spawning.

- Add challenger alternative hypotheses as new rows in Step 3 table
- Re-rank if challenger gives stronger evidence for lower-ranked candidate
- If challenger finds category not in common list, add it

## Step 5: Probe top hypotheses

One targeted test per hypothesis — clear confirm/rule-out signal. Run independent probes in parallel.

```bash
# Example probes — adapt to the actual symptom

# Environment mismatch: check active interpreter
python --version  # timeout: 3000

# Missing allow entry: check home settings.json allow list
jq -r '.permissions.allow[]' ~/.claude/settings.json

# Hook path wrong: verify hook file exists
ls -la ~/.claude/hooks/

# Sync drift: compare project vs home settings
diff <(jq -S . .claude/settings.json) <(jq -S . ~/.claude/settings.json) | head -40
```

Per probe: mark **Confirmed**, **Ruled out**, or **Inconclusive**.

Stop when one hypothesis confirmed with clear evidence, or top-3 all ruled out (expand to lower-ranked candidates).

## Step 6: Report findings

Re-resolve `$INVESTIGATE_RUN` from the persisted path file (`cat "${TMPDIR:-/tmp}/investigate-run-path"`). Then guard each read with `[ -f <path> ]`: if `$INVESTIGATE_RUN/codex-review.md` exists, read it; if `$INVESTIGATE_RUN/challenger-review.md` exists, read it. Either or both may be absent (Step 4 was skipped via `--fast`, or the spawned agent failed silently). Incorporate any new hypotheses or blindspots from existing files into the Evidence section below; skip the read entirely if neither file is present — do NOT block on missing review files.

```markdown
## Investigation: <symptom>

**Root cause**: <confirmed cause, or "inconclusive — suspects narrowed to X, Y">

**Evidence**:
- <key finding that confirmed the diagnosis>
- <secondary supporting evidence>

**Ruled out**: <hypotheses eliminated and why>

**Recommended next action**: <one of:>
  - `/develop:fix` — code regression confirmed (application code only — NOT for `.claude/` changes) (requires `develop` plugin — check plugin availability before following this recommendation)
  - `/foundry:manage update <name> "<change directive>"` — `.claude/` agent/skill content needs adding or updating (NOT for structural/quality sweeps — use `/foundry:audit` for that)
  - `/foundry:audit` — structural/quality issue in `.claude/` config confirmed (e.g. broken cross-refs, missing blocks, tag imbalance); NOT for content additions — use `/manage update` for those
  - `/foundry:setup` — propagate project `.claude/` to `~/.claude/` (foundry plugin is the distribution path)
  - Manual step: <exact command to run>
  - Further investigation needed: <what additional info would resolve it>
```

End with a `## Confidence` block:

```markdown
## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [e.g., root cause unconfirmed — probe was inconclusive; external service logs inaccessible]

**Refinements**: N passes.
- Pass 1: [gap addressed]
```

Invoke `AskUserQuestion` as follow-up gate:
(a) Invoke recommended next action (from Recommended next action field above)
(b) Run additional investigation with narrowed hypothesis
(c) Skip — diagnosis complete

</workflow>

<notes>

- **Diagnosis only** — never apply fixes; hand off with specific recommended action
- **Scope vs `/develop:debug`**: `/develop:debug` (requires `develop` plugin) needs known test failure, runs TDD fix loop. `/investigate` = "something wrong, don't know what" — cause may not be in application code
- **Scope vs `/foundry:audit`**: `/foundry:audit` = scheduled quality sweep of `.claude/`. `/investigate` = triggered by live failure; two complement each other (investigate finds config symptom → audit confirms structural issue)
- **Follow-up**: `/develop:fix` (requires `develop` plugin) for implementing resolution once root cause confirmed
- **Broad first**: always complete Step 2 before hypothesising — premature anchoring = most common investigation failure
- **Parallel probes**: run independent probes in single response, avoid serial latency
- **Inconclusiveness valid**: report what ruled out and what info would close remaining gap — don't fabricate root cause to appear decisive
- **Root-cause discipline**: drill to confirmed root cause before handoff — never hand off "likely cause"; if fix applied and symptoms persist, re-invoke investigate with residual symptom to continue the loop; full protocol in `rules/debugging.md`

</notes>
