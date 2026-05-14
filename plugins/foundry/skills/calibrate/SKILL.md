---
name: calibrate
description: Calibration testing for agents and skills. Generates synthetic problems with known outcomes (quasi-ground-truth), runs targets against them, measures recall, precision, confidence calibration — reveals whether self-reported confidence scores track actual quality.
when_to_use: Run to measure agent/skill routing accuracy, validate confidence calibration, or A/B test agent changes after editing descriptions or workflows.
argument-hint: '[<scope>...] [--fast | --full] [--ab-test | --apply] [--skip-gate]'
disable-model-invocation: true
allowed-tools: Read, Write, Bash, Agent, Glob, Grep, Skill, TaskCreate, TaskUpdate, AskUserQuestion
effort: high
---

<objective>

Validate agents and skills by measuring outputs against synthetic problems with defined ground truth. Primary signal: **calibration bias** — gap between self-reported confidence and actual recall. Well-calibrated agent reports 0.9 when it finds ~90% of issues. Miscalibrated: reports 0.9, finds 60%.

Calibration data drives improvement loop: systematic gaps → instruction updates; persistent overconfidence → adjusted re-run thresholds in MEMORY.md.

NOT for: static routing overlap analysis (use /foundry:audit); manually reviewing skill output quality (use /develop:review).

</objective>

<inputs>

- **$ARGUMENTS**: parse `--flags` first, then resolve remaining tokens as scope targets

  **Flags** (order independent):
  - `--fast` — 3 problems per target (default when neither pace flag passed)
  - `--full` — 10 problems per target; mutually exclusive with `--fast`
  - `--ab-test` — also run `general-purpose` baseline and report delta metrics; requires benchmark (default `--fast` if no pace flag); mutually exclusive with `--apply`
  - `--apply` — apply proposals: with `--fast`/`--full`: run benchmark then immediately apply; without pace flag: skip benchmark, apply proposals from most recent past run; mutually exclusive with `--ab-test`
  - `--skip-gate` — suppress follow-up gate; for programmatic callers
  - `--local` — resolve target agent/skill files from source tree (`plugins/*/`) instead of installed plugin cache; for plugin-dev workflows where local edits aren't yet installed; sets `LOCAL_MODE=true` in all pipeline spawns

  **Mutual exclusion validation** (check before any work):
  - `--ab-test` + `--apply` together → hard error: "`--ab-test` and `--apply` are mutually exclusive. Pass one or neither."
  - `--fast` + `--full` together → hard error: "Pass `--fast` or `--full`, not both."
  - `--ab-test` without pace flag → default `--fast` silently (no error)

  **Unsupported flag check** — after all supported flags extracted (`--fast`, `--full`, `--ab-test`, `--apply`, `--skip-gate`, `--local`), scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--fast\`, \`--full\`, \`--ab-test\`, \`--apply\`, \`--skip-gate\`, \`--local\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

  **Legacy positional tokens** (`ab`, `apply`, `fast`, `full`) — **hard error**: print migration hint and stop. Example: "`ab` removed — use `--ab-test` flag: `/calibrate curator --ab-test`."

  **Scope tokens** (positional, space-separated — defaults to `all`):
    - `all` — all agents + relevant skills + routing + communication + all rules
    - `agents` — all agents only (full agent list in `modes/agents.md`)
    - `skills` — calibratable skills only (`/audit` and others per `modes/skills.md`; `/oss:review` excluded — requires live GitHub PR)
    - `routing` — routing accuracy test: measures how accurately `general-purpose` orchestrator selects correct `subagent_type` for synthetic task prompts (not per-agent quality benchmark; included in `all`)
    - `communication` — handover + team protocol compliance: runs `foundry:curator` against synthetic agent responses and team transcripts with injected protocol violations (missing JSON envelope, missing `summary`, AgentSpeak v2 breaches); included in `all`
    - `rules` — rule adherence test: for each global rule file (no `paths:`) and each path-scoped rule when matching file is in context, generates synthetic tasks that should trigger rule's key directives, measures whether `general-purpose` agent with rule loaded correctly applies them; reports rules that are ignored, misapplied, or redundant; included in `all`
    - `plugins` — all agents + calibratable skills from all `plugins/*/` directories (union of all plugin-namespaced agents and calibratable skills)
    - `<plugin-name>` — **tier 2**: bare plugin directory name (e.g. `oss`, `foundry`, `research`, `develop`) auto-resolved when token matches `plugins/<name>/` directory; calibrates all agents + calibratable skills in that plugin
    - `<agent-name>` — **tier 3**: single agent (e.g., `foundry:sw-engineer`); also accepts bare name (e.g. `sw-engineer`) and resolves via `plugins/*/agents/<name>.md`
    - `/audit` — single skill (pass any calibratable skill name; `/oss:review` accepted but excluded per `modes/skills.md`)
    - Multiple scope tokens — space-separated; calibrates union of resolved targets: `oss research`, `agents skills`, `curator shepherd`; each token resolved through same tier hierarchy as `/audit` scope tokens (reserved keywords first, then plugin-dir lookup, then agent/skill file search)

  Every invocation surfaces report: benchmark runs print new results; `--apply` without pace flag prints saved report from last run before applying.

</inputs>

<constants>

- FAST_N: 3 problems per target
- FULL_N: 10 problems per target
- RECALL_THRESHOLD: 0.70 (below → agent needs instruction improvement)
- CALIBRATION_BORDERLINE: ±0.10 (|bias| within this → calibrated; between 0.10 and 0.15 → borderline)
- CALIBRATION_WARN: ±0.15 (bias beyond this → confidence decoupled from quality)
- CALIBRATE_LOG: `.claude/logs/calibrations.jsonl`
- AB_ADVANTAGE_THRESHOLD: 0.10 (delta recall or F1 above this → meaningful advantage; below → marginal or none)
- PHASE_TIMEOUT_MIN: 5 (per-phase budget — if spawned subagents haven't all returned, collect partial results and continue)
- PIPELINE_TIMEOUT_MIN: 10 (hard cutoff — pipeline not notified within 10 min of launch is timed out; extendable if agent explains delay) # tighter than global 15-min cutoff from CLAUDE.md §8 — intentional for calibrate
- HEALTH_CHECK_INTERVAL_MIN: 5 (orchestrator polls each running pipeline every 5 min for liveness) # = global default (CLAUDE.md §8)
- EXTENSION_MIN: 5 # = global default (CLAUDE.md §8)
- ROUTING_ACCURACY_THRESHOLD: 0.90 (below → agent descriptions need improvement)
- ROUTING_HARD_THRESHOLD: 0.80 (below → high-overlap pair descriptions need disambiguation)
- CODEX_PROBLEM_RATIO: 0.6 (fraction of in-scope problems generated by Codex — agents/skills modes only)
- CODEX_SCORER_WEIGHT: 0.49 (Codex scorer weight; Claude = 0.51 — Claude has last word on disagreements)
- SCORER_AGREEMENT_WARN: 0.70 (scorer agreement below this → flag ambiguous ground truth ⚠)
- CODEX_MODES: ["agents", "skills"] (modes where Codex is active; routing/communication/rules excluded — test Claude-specific internals)
- PIPELINE_TIMEOUT_MIN_DUAL: 15 (hard cutoff when Codex active — replaces PIPELINE_TIMEOUT_MIN=10 for dual-source runs)

Domain tables per mode: see `modes/agents.md`, `modes/skills.md`, `modes/routing.md`, `modes/communication.md`, `modes/rules.md`.

</constants>

<workflow>

**Task hygiene**: Before creating tasks, call `TaskList`. For each found task:

- status `completed` if work clearly done
- status `deleted` if orphaned / no longer relevant
- keep `in_progress` only if genuinely continuing

**Task tracking**: create tasks at start of execution (Step 1) for each phase that will run:

- "Calibrate agents" — Step 2 (benchmark mode, when target includes agents)
- "Calibrate skills" — Step 2 (benchmark mode, when target includes skills)
- "Calibrate routing" — Step 2 (benchmark mode, when target includes routing)
- "Calibrate communication" — Step 2 (benchmark mode, when target includes communication)
- "Analyse and report" — Steps 3–5 (benchmark mode)
- "Apply findings" — Step 6 (apply mode only) Mark each in_progress when starting, completed when done. On loop retry or scope change, create new task.

## Step 1: Parse targets and create run directory

From `$ARGUMENTS`, determine:

- **Strip flags first**: extract `--fast`, `--full`, `--ab-test`, `--apply`, `--skip-gate`, `--local` before scope resolution; validate mutual exclusion (error and stop on conflict). Strip all flags from ARGUMENTS before scope token resolution:
  ```bash
  LOCAL_MODE=false; [[ "$ARGUMENTS" == *"--local"* ]] && LOCAL_MODE=true
  ARGUMENTS="${ARGUMENTS//--fast/}"
  ARGUMENTS="${ARGUMENTS//--full/}"
  ARGUMENTS="${ARGUMENTS//--ab-test/}"
  ARGUMENTS="${ARGUMENTS//--apply/}"
  ARGUMENTS="${ARGUMENTS//--skip-gate/}"
  ARGUMENTS="${ARGUMENTS//--local/}"
  ARGUMENTS="${ARGUMENTS#"${ARGUMENTS%%[![:space:]]*}"}"
  ```
- **Target list** — remaining tokens after flag-strip; union of resolved targets:
  - `all` or omitted → all agents + `/audit` + routing + communication + all rules
  - `agents` → all agents (full agent list in `modes/agents.md`)
  - `skills` → `/audit` only (and other non-live-PR skills in `modes/skills.md`; `/oss:review` excluded)
  - `routing` → routing accuracy test only
  - `communication` → handover + team protocol compliance only
  - `rules` → rule adherence test (all rule files in `.claude/rules/`) only
  - `plugins` → all agents + calibratable skills from all `plugins/*/` directories
  - `<plugin-name>` matching `plugins/<name>/` directory → tier 2: all agents + calibratable skills in that plugin
  - Any other token → tier 3: single agent or skill name; search `plugins/*/agents/<name>.md`, `.claude/agents/<name>.md`, `plugins/*/skills/<name>/SKILL.md`, `.claude/skills/<name>/SKILL.md`; error if no match
  - Multiple tokens → union: e.g. `oss research`, `curator shepherd`; each resolved independently

**Empty resolution guard**: after resolving all scope tokens to target list, if list is empty (e.g. plugin matched but contains no calibratable agents/skills, such as `/calibrate codemap`), stop with:

```text
! No calibratable agents/skills found for scope: <input-scope>
Verify: (a) plugin name spelled correctly, (b) plugin has agents/*.md or calibratable skills (see modes/skills.md domain table)
```

Do not proceed to Step 2 — silent no-op produces no report and confuses callers.

- **Pace**: `--full` → 10 problems; `--fast` → 3 problems; neither → default `--fast`
- **A/B flag**: `--ab-test` → also spawn `general-purpose` baseline per problem
- **Apply flag**:
  - `--apply` without pace flag → pure apply mode: skip Steps 2–5; go to Step 6
  - `--apply` with `--fast`/`--full` → benchmark + auto-apply: run Steps 2–5 then continue to Step 6

If benchmark will run (i.e., `--fast` or `--full` present, with or without `--apply`): generate timestamp `YYYY-MM-DDTHH-MM-SSZ` (UTC, e.g. `2026-03-03T13-44-48Z`) via `date -u +%Y-%m-%dT%H-%M-%SZ`. All run dirs use this timestamp.

Create tasks before proceeding:

- Benchmark only (no `--apply`): TaskCreate "Calibrate agents" (if target includes agents), TaskCreate "Calibrate skills" (if target includes skills), TaskCreate "Calibrate routing" (if target includes routing), TaskCreate "Calibrate communication" (if target includes communication), TaskCreate "Calibrate rules" (if target includes rules), TaskCreate "Analyse and report"
- Benchmark + auto-apply (`--fast`/`--full` + `--apply`): TaskCreate "Calibrate agents" (if target includes agents), TaskCreate "Calibrate skills" (if target includes skills), TaskCreate "Calibrate routing" (if target includes routing), TaskCreate "Calibrate communication" (if target includes communication), TaskCreate "Calibrate rules" (if target includes rules), TaskCreate "Analyse and report", TaskCreate "Apply findings"
- Pure apply mode (only `--apply`, no pace flag): TaskCreate "Apply findings" only

## Step 2: Spawn pipeline subagents

> **Pre-flight**: mode files at `<plugin-cache>/foundry/<v>/skills/calibrate/modes/` — resolve via plugin cache scan below.
> `/foundry:init` does NOT symlink these (only `rules/*.md` and `TEAM_PROTOCOL.md`); if not found, re-install foundry plugin.
> ```bash
> CALIB_MODES_DIR="$(find ${HOME}/.claude/plugins/cache -path "*/calibrate/modes" -type d 2>/dev/null | head -1)" # timeout: 5000
> [ -d "$CALIB_MODES_DIR" ] || { printf "! BREAKING: calibrate/modes/ not found — re-install foundry plugin: claude plugin install foundry@borda-ai-rig\n"; exit 1; }
> ```

For each target mode in resolved target list, read corresponding mode file and execute spawn instructions. Issue ALL spawns in **single response** — modes are independent and run concurrently.

| Target mode | Mode file | Task to mark in_progress |
| --- | --- | --- |
| agents | `$CALIB_MODES_DIR/agents.md` | "Calibrate agents" |
| skills | `$CALIB_MODES_DIR/skills.md` | "Calibrate skills" |
| routing | `$CALIB_MODES_DIR/routing.md` | "Calibrate routing" |
| communication | `$CALIB_MODES_DIR/communication.md` | "Calibrate communication" |
| rules | `$CALIB_MODES_DIR/rules.md` | "Calibrate rules" |
| plugins or `<plugin-name>` (tier 2) | expand to per-agent + per-skill pipelines: glob `plugins/<name>/agents/*.md` and calibratable `plugins/<name>/skills/*/SKILL.md`; spawn one pipeline per resolved target using appropriate mode file (agents.md for agents, skills.md for calibratable skills); task name "Calibrate <plugin-name>" | "Calibrate <plugin-name>" |
| `<agent-name>` / `<skill-name>` (tier 3) | single-file pipeline: use agents.md or skills.md mode file with `<TARGET>` = resolved name; task name "Calibrate <name>" | "Calibrate <name>" |

For multiple tokens, merge resolved targets into per-mode groups before spawning — one pipeline per unique mode file needed, each carrying full target list.

Before spawning **any** pipeline (when target includes `agents`, `skills`, or `all`), check cross-plugin availability:
```bash
OSS_AVAILABLE=$(find ~/.claude/plugins/cache -name "oss" -type d 2>/dev/null | head -1)  # timeout: 5000
RESEARCH_AVAILABLE=$(find ~/.claude/plugins/cache -name "research" -type d 2>/dev/null | head -1)  # timeout: 5000
CODEMAP_AVAILABLE=$(find ~/.claude/plugins/cache -name "codemap" -type d 2>/dev/null | head -1)  # timeout: 5000
DEVELOP_AVAILABLE=$(find ~/.claude/plugins/cache -name "develop" -type d 2>/dev/null | head -1)  # timeout: 5000
```

- **`agents` pipeline**: exclude `oss:cicd-steward` and `oss:shepherd` (requires `oss` plugin) if `$OSS_AVAILABLE` empty; exclude `research:data-steward` and `research:scientist` (requires `research` plugin) if `$RESEARCH_AVAILABLE` empty. Log: "oss/research plugin not installed — skipping <agent> calibration"
- **`skills` pipeline**: exclude `/oss:review` (requires `oss` plugin) always (requires live GitHub PR — not calibratable with synthetic input; see `modes/skills.md`); exclude `/codemap:*` skills (requires `codemap` plugin) if `$CODEMAP_AVAILABLE` empty; exclude `/research:plan`, `/research:judge`, `/research:verify` (requires `research` plugin) if `$RESEARCH_AVAILABLE` empty; exclude `/develop:review` (requires `develop` plugin) if `$DEVELOP_AVAILABLE` empty. Log skip message per excluded skill.

Fallback role descriptions for cross-plugin agents (if ever substituted with `general-purpose`) — see `skills/_shared/agent-resolution.md`.

Each mode file defines `<TARGET>`, `<DOMAIN>`, any N overrides, and extra instructions for pipeline subagent. Pipeline template lives at `$CALIB_MODES_DIR/../templates/pipeline-prompt.md`. **N override**: `communication` caps at fast=3 / full=5 (not global FULL_N=10) to prevent pipeline context overflow — read `$CALIB_MODES_DIR/communication.md` for details. **`rules` mode** spawns one `general-purpose` subagent per rule file (not standard pipeline template) — read `$CALIB_MODES_DIR/rules.md` for direct-spawn approach.

## Step 3: Collect results and print combined report

**Health monitoring** — follow CLAUDE.md §8 protocol. Run dir for liveness checks: `.reports/calibrate/<TIMESTAMP>/<TARGET>/`. Skill-specific constants (tighter than global defaults — see `<constants>` block): `PIPELINE_TIMEOUT_MIN`, `PIPELINE_TIMEOUT_MIN_DUAL` (when Codex active in CODEX_MODES), `HEALTH_CHECK_INTERVAL_MIN`, `EXTENSION_MIN`.

Per-target checkpoint init after all spawns:
```bash
LAUNCH_AT=$(date +%s)
for batch_target in $SPACE_SEPARATED_TARGETS; do touch /tmp/calibrate-check-$batch_target; done
```

Poll every `$HEALTH_CHECK_INTERVAL_MIN` minutes: `find .reports/calibrate/$TIMESTAMP/$batch_target/ -newer /tmp/calibrate-check-$batch_target -type f | wc -l` — new files = alive; use Read tool (limit=20) on `pipeline.jsonl` to check for PROGRESS:/HEARTBEAT: if stalled; apply `$PIPELINE_TIMEOUT_MIN_DUAL` instead of `$PIPELINE_TIMEOUT_MIN` for dual-source (Codex-active) targets.

**On timeout**: read `tail -100 <output_file>` for partial JSON; if none use: `{"target":"<TARGET>","verdict":"timed_out","mean_recall":null,"gaps":["pipeline timed out — re-run individually with /calibrate <target> fast"]}`. Timed-out targets appear in report with ⏱ prefix and null metrics.

After all pipeline subagents complete or time out: mark "Calibrate agents", "Calibrate skills", "Calibrate routing", "Calibrate communication", "Calibrate rules" completed (whichever ran). Mark "Analyse and report" in_progress. Parse compact JSON summary from each.

For any pipeline that returned without a compact JSON, use Glob (pattern `*/result.jsonl`, base `.reports/calibrate/<TIMESTAMP>/`) to check whether a result file was written. If `result.jsonl` exists, parse it as the compact JSON for that target. If neither compact JSON nor `result.jsonl` exists, synthesize: `{"target":"<TARGET>","verdict":"incomplete","mean_recall":null,"calibration_bias":null,"gaps":["pipeline returned no output — re-run: /calibrate <TARGET> --fast"]}` and mark that target with ⏱ in the report table.

Print combined benchmark report:

```markdown
## Calibrate — <date> — <MODE>

| Target           | Recall | SevAcc | Fmt  | Confidence | Bias    | F1   | Scope | Verdict    | Top Gap              |
|------------------|--------|--------|------|------------|---------|------|-------|------------|----------------------|
| sw-engineer      | 0.83   | 0.91   | 0.87 | 0.85       | +0.02 ✓ | 0.81 | 0 ✓   | calibrated | async error paths    |
| ...              |        |        |      |            |         |      |       |            |                      |

*Recall: in-scope issues found / total. SevAcc: severity match rate for found issues (±1 tier) — high recall + low SevAcc = issues found but misprioritized. Fmt: fraction of found issues with location + severity + fix (actionability). Bias: confidence − recall (+ = overconfident). Scope: FP on out-of-scope input (0 ✓).*
```

**If AB mode**, add `ΔRecall`, `ΔSevAcc`, `ΔFmt`, `ΔTokens`, and `AB Verdict` columns after F1. ΔTokens = token_ratio − 1.0 (negative = specialist more concise).

```markdown
| Target      | Recall | SevAcc | Fmt  | Bias    | F1   | ΔRecall | ΔSevAcc | ΔFmt  | ΔTokens | Scope | AB Verdict |
|-------------|--------|--------|------|---------|------|---------|---------|-------|---------|-------|------------|
| sw-engineer | 0.83   | 0.91   | 0.87 | +0.02 ✓ | 0.81 | +0.05 ~ | +0.12 ✓ | +0.15 ✓ | −0.18 ✓ | 0 ✓ | marginal ~ |

*ΔRecall/ΔSevAcc/ΔFmt: specialist − general (positive = specialist better). ΔTokens: token_ratio − 1.0 (negative = more focused). AB Verdict covers ΔRecall and ΔF1 only; use ΔSevAcc and ΔFmt as supplementary evidence for agents where ΔRecall ≈ 0.*
```

**If target is `routing`**: read `modes/routing.md` "Report format" section and use that table instead. Mark "Calibrate routing" completed.

Flag targets where recall < 0.70 or |bias| > 0.15 with ⚠.

After table, print full content of each `proposal.md` for targets where `proposed_changes > 0`.

If `--apply` **not** set: after printing proposals, fire **Follow-up gate** (unless `--skip-gate` passed):

Call `AskUserQuestion` — do NOT write options as plain text. Map options directly:
- question: "Proposals ready. What next?" (include summary, e.g. "3 targets with proposals, 1 calibrated.")
- (a) label: `Apply proposals` — description: run `/calibrate <targets> --apply`
- (b) label: `Re-run full depth` — description: run `/calibrate <targets> --full` for 10 problems per target
- (c) label: `Re-run full + A/B` — description: run `/calibrate <targets> --full --ab-test` with general-purpose baseline
- (d) label: `skip` — description: review proposal files manually at `.reports/calibrate/<TIMESTAMP>/<TARGET>/proposal.md`

If `--apply` **was** set (benchmark + auto-apply mode), print `→ Auto-applying proposals now…` and proceed to Step 6.

Targets with verdict `calibrated` and no proposed changes get single line: `✓ <target> — no instruction changes needed`.

## Step 4: Concatenate JSONL logs

Append each target's result line to `.claude/logs/calibrations.jsonl` using native tools (no Bash needed):

1. Use Glob (pattern `*/result.jsonl`, path `.reports/calibrate/<TIMESTAMP>/`) to find all result files
2. Read each result file with Read tool
3. Read `.claude/logs/calibrations.jsonl` (if exists; use empty string if missing)
4. Append new lines and Write combined content back to `.claude/logs/calibrations.jsonl`

## Step 5: Surface improvement signals

For each flagged target (recall < 0.70 or |bias| > 0.15):

- **Recall < 0.70**: `→ Update <target> <antipatterns_to_flag> for: <gaps from result>`
- **Bias > 0.15**: `→ Raise effective re-run threshold for <target> in MEMORY.md (default 0.70 → ~<mean_confidence>)`
- **Bias < −0.15**: `→ <target> is conservative; threshold can stay at default`

Proposals shown in Step 3 already surface actionable signals. Follow-up gate fires in Step 3 (unless `--skip-gate`). Mark "Analyse and report" completed. If `--apply` was set: proceed to Step 6.

## Step 6: Apply proposals (apply mode)

Mark "Apply findings" in_progress.

**Determine run directory**:

- Benchmark + auto-apply mode (`--fast`/`--full` + `--apply`): use TIMESTAMP already generated in Step 1 — proposals just written by Steps 2–5.
- Pure apply mode (only `--apply`, no pace flag): find most recent run:

```bash
LATEST=$(find .reports/calibrate -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort -Vr | head -1)
TIMESTAMP=$(basename "$LATEST")
```

For each target in target list, check whether `.reports/calibrate/<TIMESTAMP>/<target>/proposal.md` exists. Collect targets with proposal (`found`) and without (`missing`).

For each **missing** target: hard error — do not auto-trigger benchmark. Print:
`! No prior run for <target> — re-run with --fast --apply to benchmark+apply, or --fast to benchmark only.`
Stop. `--apply` without pace flag is documented as "skip benchmark, apply proposals from most recent past run"
(see `<inputs>`); auto-triggering would contradict that contract.

**Print run's report before applying**: for each found target, read and print `.reports/calibrate/<TIMESTAMP>/<target>/report.md` verbatim so user sees benchmark basis before any file changes.

**Spawn one `foundry:curator` subagent per found target (`.md` files — agents and skills). Issue ALL spawns in single response — no waiting between spawns.**

**`<AGENT_FILE>` and `<PROPOSAL_PATH>` resolution**: before spawning, resolve file paths for each target. Project-local override first, then plugin cache, then source-tree fallback (plugin-dev only):
```bash
# Agent target — parse plugin prefix from target name (<plugin>:<agent> pattern)
# e.g. "oss:shepherd" → plugin="oss", agent="shepherd"; bare "curator" → plugin="foundry" (default)
PLUGIN_PREFIX=$(echo "<name>" | grep -o '^[^:]*:' | tr -d ':')
AGENT_BARE=$(echo "<name>" | sed 's/^[^:]*://')
[ -z "$PLUGIN_PREFIX" ] && PLUGIN_PREFIX="foundry"
AGENT_FILE=".claude/agents/$AGENT_BARE.md"
[ -f "$AGENT_FILE" ] || AGENT_FILE="$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/$PLUGIN_PREFIX" -maxdepth 4 -name "$AGENT_BARE.md" -path "*/agents/*" 2>/dev/null | sort -Vr | head -1)"
[ -n "$AGENT_FILE" ] && [ -f "$AGENT_FILE" ] || AGENT_FILE="plugins/$PLUGIN_PREFIX/agents/$AGENT_BARE.md"
# Skill target — substitute skills/<name>/SKILL.md in the same pattern (plugin prefix applies equally)

# Proposal path (same TIMESTAMP used throughout skill)
PROPOSAL_PATH=".reports/calibrate/$TIMESTAMP/<name>/proposal.md"
```

Each subagent receives this self-contained prompt (substitute `<TARGET>`, `<PROPOSAL_PATH>`, `<AGENT_FILE>` — resolved paths from above):

Read proposal file at `<PROPOSAL_PATH>` and apply each "Change N" block to `<AGENT_FILE>` (path to agent or skill file for this target).

For each change:

1. Print: `Applying Change N to <file> [<section>]`
2. Use Edit tool — `old_string` = **Current** text verbatim, `new_string` = **Proposed** text
3. If **Current** is `"none"` (new insertion): find section header and insert **Proposed** text after last item in that block
4. Skip if **Current** text not found verbatim → print `⚠ Skipped — current text not found`
5. Skip if **Proposed** text already present → print `✓ Already applied — skipped`

After processing all changes return **only** this compact JSON:

`{"status":"done","target":"<TARGET>","applied":N,"skipped":N,"file":"<AGENT_FILE>","summary":"Applied N, skipped N changes to <AGENT_FILE>"}`

After all subagents complete, collect JSON results and print final summary:

```markdown
## Fix Apply — <date>

| Target      | File                          | Applied | Skipped |
|-------------|-------------------------------|---------|---------|
| sw-engineer | .claude/agents/sw-engineer.md | 2       | 0       |

→ Run /calibrate <targets> to verify improvement.
```

Mark "Apply findings" completed.

End response with `## Confidence` block per CLAUDE.md output standards.

</workflow>

<notes>

- **Timeout handling**: phase and pipeline budgets (see constants block) prevent nested subagent hangs from cascading. Extension granted once if pipeline explains delay in output file — second unexplained stall still triggers cutoff. Timed-out pipelines appear with ⏱ prefix and `verdict:"timed_out"`; re-run individually with `/calibrate <target> --fast` after session.
- **Context safety**: each target runs in own pipeline subagent — only compact JSON (~200 bytes) returns to main context. `all --full --ab-test` with all targets returns ~5KB total, well within limits.
- **Scorer delegation**: Phase 3a delegates scoring to per-problem `general-purpose` subagents. Each scorer reads response files from disk, returns ~200 bytes. Phase 3b runs Codex scorers sequentially via Bash (writes per-problem files). Phase 3c merges both into `scores.json`. Pipeline holds only compact JSONs regardless of N or A/B mode — no context budget concern.
- **Nesting depth**: main → pipeline subagent → target/scorer agents (2 levels). Pipeline spawns target agents (Phase 2), Claude scorer agents (Phase 3a), Codex scoring Bash calls (Phase 3b) at same depth — no additional nesting.
- `general-purpose` is built-in Claude Code agent type (no `.claude/agents/general-purpose.md` needed) — no custom system prompt, all tools available.
- **Quasi-ground-truth limitation**: partially addressed by cross-model generation (Claude + Codex) — two model families produce independent ground truth, reducing same-family blind spots. Adversarial and ceiling-difficulty problems included in every run (see difficulty distribution rules in `templates/pipeline-prompt.md` Phase 1a) to test false-positive discipline and reveal upper-bound limits. Remaining gap: synthetically generated adversarial problems weaker than expert-authored ones; `generator_recall_delta` surfaces whether one generator's problems are systematically easier or harder. `ceiling_recall` (reported separately from `mean_recall`) is primary signal for upper-bound performance — partial recall (0.4–0.7) on ceiling problems expected and does not affect calibration verdict.
- **Dual evaluation and scorer agreement**: Phase 3a (Claude) and Phase 3b (Codex) score each response independently. Phase 3c merges with Claude as 51% tiebreaker. `scorer_agreement` measures fraction of issues where both scorers agreed — low agreement (< SCORER_AGREEMENT_WARN=0.70) flags ambiguous ground truth or scorer blind spots. Severity disputes (scorers disagree >1 tier) excluded from SevAcc aggregate.
- **File-based Codex handoff**: Codex writes all output (problem JSON, score JSON) directly to run dir. Avoids bash stdout corruption when capturing large JSON from shell subprocesses. Pipeline reads from disk, never from stdout capture.
- **Historical comparability**: `result.jsonl` includes `"scoring":"dual|single"` and `"source_mode":"dual|claude-only"`. When analyzing trends in `calibrations.jsonl`, filter by these fields — dual-scored results not directly comparable to single-scored baselines.
- **Calibration bias is key signal**: positive bias (overconfident) → raise agent's effective re-run threshold in MEMORY.md. Negative bias (underconfident) → confidence conservative, no action needed. Near-zero → confidence trustworthy.
- **Do NOT use real project files**: benchmark only against synthetic inputs — no sensitive data and real files have no ground truth.
- **Skill benchmarks** run skill as subagent against synthetic config or code; scored identically to agent benchmarks.
- **Improvement loop**: systematic gaps → `<antipatterns_to_flag>` | consistent low recall → consider model tier upgrade (sonnet → opus) | large calibration bias → document adjusted threshold in MEMORY.md | re-calibrate after instruction changes to quantify improvement.
- **Report always**: every invocation surfaces report — benchmark runs print new results table; `--apply` without pace flag prints saved report from last run before applying, so user always sees basis for changes before files touched.
- **`--apply` semantics**: `--fast --apply` / `--full --apply` = run fresh benchmark then auto-apply new proposals. `--apply` alone = apply proposals from most recent past run without re-running benchmark.
- **Stale proposals**: `--apply` uses verbatim text matching (`old_string` = **Current** from proposal). If agent file edited between benchmark run and `--apply`, any change whose **Current** text no longer matches is skipped with warning — no silent clobbering of intermediate edits.
- **`routing` target vs `/audit` Check 12**: `/audit` Check 12 performs static analysis of description overlap (finds potential confusion zones); `/calibrate routing` tests behavioral impact — generates real routing decisions and measures whether descriptions actually disambiguate. Run in sequence: `/audit` first (fast, structural), then `/calibrate routing` (behavioral, slower). Complementary, not redundant.
- **`routing`, `communication`, `rules` in `all`**: see `all` entry in `<inputs>` for authoritative definition — use explicit targets only when running single mode in isolation.
- Follow-up chains:
  - Recall < 0.70 or borderline → pick "Apply proposals" from gate → `/calibrate <agent>` to verify improvement — stop and escalate to user if recall still < 0.70 after this cycle (max 1 apply cycle per run)
  - Calibration bias > 0.15 → add adjusted threshold to MEMORY.md → note in next audit
  - Routing accuracy < 0.90 or hard accuracy < 0.80 → update descriptions for confused pairs → `/calibrate routing` to verify improvement
  - Recommended cadence: run before and after any significant agent instruction change; run `/calibrate routing` after any agent description change; run `/calibrate communication` after any protocol or handoff change
- **Internal Quality Loop suppressed during benchmarking**: Phase 2 prompt explicitly tells target agents not to self-review before answering. Ensures calibration measures raw instruction quality — not `(agent + loop)` composite. Loop enabled → inflates recall and confidence by unknown ratio, masks real instruction gaps, makes improvement attribution impossible.
- **Skill-creator complement**: trigger accuracy and A/B description testing not yet implemented — future skill-creator skill from Anthropic would own this domain; run `/calibrate` for quality and recall.
- **A/B interpretation**: every specialized agent adds system-prompt tokens — if `general-purpose` subagent matches recall and F1, specialization adds no value. `ab` mode quantifies gap per-target. `significant` (Δ>0.10) confirms agent's domain depth earns cost; `marginal` (0.05–0.10) suggests instruction improvements may help; `none` (\<0.05) signals agent's current instructions add no measurable lift over vanilla agent. Token cost informational (logged in scores.json) but not part of verdict — prioritize recall/F1 delta as primary signal. Role-specificity caveat: for agents whose domain is well-covered by general training data, `none` ΔRecall does NOT mean "retire agent" — specialization shows up in ΔSevAcc, ΔFmt, ΔTokens even when ΔRecall ≈ 0; positive ΔSevAcc/ΔFmt combined with negative ΔTokens still confirms specialist earns cost.
- **AB mode nesting**: Phase 2b spawns `general-purpose` baseline agents inside pipeline subagent. Phase 3 spawns `general-purpose` scorer agents inside same pipeline subagent. All at 2 levels (main → pipeline → agents) — no additional depth.
- **Mode files**: domain tables and mode-specific spawn instructions live in `modes/agents.md`, `modes/skills.md`, `modes/routing.md`, `modes/communication.md`, `modes/rules.md`. Add new target mode by creating new file in `modes/` and adding row to Step 2 dispatch table.

</notes>
