---
name: audit
description: "Full-sweep quality audit of .claude/ config — cross-references, permissions, inventory drift, model tiers, docs freshness. Scope tokens select what to audit; --upgrade applies docs-sourced improvements; --adversarial runs foundry:challenger + Codex adversarial review. Fix level chosen via always-fire follow-up gate after report."
argument-hint: '[<scope>...] [--local] [--upgrade | --adversarial] [--skip-gate]'
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
effort: high
when_to_use: Use for sweeping quality checks of .claude/ config or plugin source — NOT for creating/modifying agents (use manage) or measuring behavioral accuracy (use calibrate).
---

<objective>

Full-sweep audit of `.claude/` config + all `plugins/*/` files: agents, skills, rules, settings.json, hooks. Spawns `foundry:curator` per-file, aggregates system-wide for cross-file issues — infinite loops, inventory drift, missing permissions, interop breaks. Reports findings; fix level chosen from follow-up gate.

</objective>

<inputs>

- **$ARGUMENTS**: optional — parse `--flags` first, then resolve remaining tokens as scope

  **Flags** (order independent, any combination with scope):
  - `--local` — audit source tree (`plugins/*/`) not user setup (`.claude/` + installed cache); plugin-dev workflows where local edits not yet installed; sets `LOCAL_MODE=true`
  - `--upgrade` — fetch latest Claude Code docs, filter new features by genuine value, apply: **config** changes (apply + correctness check), **capability** changes (calibrate before → apply → calibrate after → accept if Δrecall ≥ 0 and ΔF1 ≥ 0). Skip to **Mode: upgrade**. Mutually exclusive with `--adversarial`.
  - `--adversarial` (alias: `--challenge`) — adversarial review of all agents + skills in scope using `foundry:challenger` (Phase A) + Codex adversarial pass (Phase B); surfaces issues beyond standard per-file audit; see **Mode: adversarial**. Mutually exclusive with `--upgrade`.
  - `--skip-gate` — suppress follow-up gate (for automation pipelines)

  **Legacy positional tokens** (`fix`, `upgrade`, `adversarial`, `challenge`, `ab`, `apply`, `fast`, `full`) — **hard error**: print migration hint and stop. Example: "`fix medium` removed — run `/audit` and pick fix level from gate, or pass `--upgrade` / `--adversarial` as flags."

  **Scope tokens** (positional, space-separated — resolve each token before Step 2):
  - No scope: full sweep — sources per `--local`: **without `--local`** covers `.claude/agents/`, `.claude/skills/`, `.claude/rules/`, hooks, settings, `~/.claude/plugins/cache/` installed; **with `--local`** covers `plugins/*/agents/`, `plugins/*/skills/` + `.claude/` secondary
  - `agents` — restrict sweep to agent files only
  - `skills` — restrict sweep to skill files only
  - `rules` — restrict sweep to rule files only
  - `communication` — restrict sweep to communication governance files: `rules/communication.md`, `rules/quality-gates.md`, `TEAM_PROTOCOL.md`, `skills/_shared/file-handoff-protocol.md`
  - `setup` — restrict to system-config files: `settings.json`, `permissions-guide.md`, hooks, `MEMORY.md`, `README.md`, plugin integration, post-install user state (Checks 1–11, 30, I1, I2, I3); Step 3: `init` SKILL.md only (one foundry:curator spawn); Checks I1–I3 read `~/.claude/` not `.claude/`
  - `plugin` — plugin integration only: codex plugin (Check 7), foundry plugin + init validation (Check 8, including 8g); Step 3: `init` SKILL.md only (one foundry:curator spawn)
  - `plugins` — full audit of all plugins: per-file audit of every `plugins/*/agents/*.md` and `plugins/*/skills/*/SKILL.md` + integration checks (7, 8) per plugin
  - `plugins <name>` — same as `plugins` scoped to one plugin: `plugins/<name>/agents/*.md` + `plugins/<name>/skills/*/SKILL.md` + integration checks; `<name>` must match dir under `plugins/` (e.g. `plugins foundry`, `plugins oss`, `plugins research`)
  - `<plugin-name>` — **tier 2 shorthand**: bare plugin dir name (e.g. `oss`, `foundry`, `research`, `develop`, `codemap`) auto-resolved when token matches dir under `plugins/`; equivalent to `plugins <name>`; no `plugins` prefix needed
  - `<agent-name>` — **tier 3**: name matches `plugins/*/agents/<name>.md` or `.claude/agents/<name>.md`; runs agent checks only (Checks 14, 15, 19, 20, 17, 12, 13, 25, 22, 26, 29); one file in Step 3
  - `<skill-name>` — **tier 3**: name matches `plugins/*/skills/<name>/SKILL.md` or `.claude/skills/<name>/SKILL.md`; runs skill checks only (Checks 14, 15, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29); one file in Step 3
  - Multiple scope tokens — space-separated, any combo; scope = union of resolved file sets: `agents skills`, `oss research`, `shepherd curator`, `review resolve`; check list = union (de-duplicated)

  **Scope token resolution** (each remaining token after flag-strip, resolved before Step 2): (1) reserved keywords (`agents`, `skills`, `rules`, `communication`, `setup`, `plugin`, `plugins`) → use as-is; (2) matches dir under `plugins/<token>/` → tier 2; (3) matches agent file in `plugins/*/agents/<token>.md` or `.claude/agents/<token>.md` → tier 3 agent; (4) matches skill dir `plugins/*/skills/<token>/` or `.claude/skills/<token>/` → tier 3 skill; (5) no match → error and stop

  **Valid combinations**: scope tokens + flags mix freely: `foundry --local`, `foundry --adversarial`, `agents skills --local`, `oss research --adversarial`. `--upgrade` and `--adversarial` mutually exclusive — error if both. `--local` compatible with all.

</inputs>

<constants>

<!-- Background agent health monitoring (CLAUDE.md §8) — applies to Step 3 foundry:curator spawns -->
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay
BATCH_SIZE=5           # max files per foundry:curator spawn in Step 3; keep small to avoid context compaction

</constants>

<workflow>

**Task hygiene**: Call `TaskList` before creating tasks. For each found task:

- status `completed` if work clearly done
- status `deleted` if orphaned / no longer relevant
- keep `in_progress` only if genuinely continuing

**Orchestration contract**: orchestrator is thin coordinator — issues Glob/Grep for inventory, spawns agents, reads JSON envelopes, aggregates findings. Must NOT read agent/skill/rule file bodies directly. Inline read of non-template file = protocol violation; causes context overflow at scale.

**Task tracking**: TaskCreate for each major phase; mark status live:

- Phase 1: setup + collect (Pre-flight + Steps 1–2) → in_progress on start, completed when file list ready
- Phase 2: per-file audit (Step 3) → in_progress on agent launch, completed when all reports received
- Phase 3: system-wide checks (Step 4) → in_progress on start, completed when all checks done
- **Phases 2 and 3 launch simultaneously** — mark both in_progress same update; independent, must not serialize
- Phase 4: aggregate + fix (Steps 5–10) → in_progress, completed when fixes land; **do NOT mark completed until EITHER: (a) follow-up gate fires (Step 7) AND fixes applied or user chose skip; OR (b) `--skip-gate` active — gate suppressed, complete after Step 5 aggregation; Step 5 aggregation alone does NOT complete Phase 4 in normal mode**
- Phase 5: final report (Step 11) → in_progress, completed before output
- On loop retry or scope change → new task; do not reuse completed task

Surface progress at milestones: after system-wide checks ("✓ Checks 1-21 complete, N findings so far — spawning per-file audits"), after agent reports ("Agent reports received — N medium, N low findings"), before each fix batch ("Fixing N medium findings in parallel").

## Pre-flight checks

**Context budget**: full audit (12+ agents, 14+ skills, 12 system checks) runs close to context limits. File-based handoff mandatory — every sub-agent writes full output to file, returns only compact JSON envelope. Sub-agent echoing findings to context = compaction before audit completes.

```bash
LOCAL_MODE=false; [[ "$ARGUMENTS" == *"--local"* ]] && LOCAL_MODE=true
ARGUMENTS="${ARGUMENTS//--local/}"
ARGUMENTS="${ARGUMENTS#"${ARGUMENTS%%[![:space:]]*}"}"

RED='\033[1;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

# Canonical source: plugins/foundry/skills/_shared/preflight-helpers.md
# Keep in sync with that file when updating
# From _shared/preflight-helpers.md — TTL 4 hours, keyed per binary
preflight_ok() {
    local f=".claude/state/preflight/$1.ok"
    [ -f "$f" ] && [ $(($(date +%s) - $(cat "$f"))) -lt 14400 ]
} # timeout: 5000
preflight_pass() {
    mkdir -p .claude/state/preflight
    date +%s >".claude/state/preflight/$1.ok"
} # timeout: 5000

# .claude/ directory must exist (not cached — filesystem state)
if [ ! -d ".claude" ]; then
    printf "${RED}! BREAKING${NC}: .claude/ directory not found — nothing to audit\n"
    exit 1
fi

# jq availability — Check 4 depends on it
if preflight_ok jq; then
    JQ_AVAILABLE=true
elif command -v jq &>/dev/null; then # timeout: 5000
    preflight_pass jq
    JQ_AVAILABLE=true
else
    printf "${YEL}⚠ MISSING${NC}: jq not found — Check 4 (permissions-guide drift) will be skipped\n"
    JQ_AVAILABLE=false
fi

# git availability — used in path portability check and baseline context
if ! preflight_ok git && ! command -v git &>/dev/null; then # timeout: 5000
    printf "${YEL}⚠ MISSING${NC}: git not found — path portability check may miss repo-root references\n"
else
    preflight_ok git || preflight_pass git
fi

# node availability — Check 10 (RTK prefix parsing) and upgrade mode (hook syntax check) depend on it
if preflight_ok node; then
    NODE_AVAILABLE=true
elif command -v node &>/dev/null; then # timeout: 5000
    preflight_pass node
    NODE_AVAILABLE=true
else
    printf "${YEL}⚠ MISSING${NC}: node not found — Check 10 (RTK hook parsing) and upgrade hook syntax check will be skipped\n"
    NODE_AVAILABLE=false
fi

# AUDIT_TPL path resolution — needed by Step 3 (curator-prompt.md) and Step 4 (scope check files)
# .claude/skills/audit/templates/ is populated by plugin system; if absent, fall back to plugin cache
AUDIT_TPL=".claude/skills/audit/templates"
if [ "$LOCAL_MODE" = "true" ] && [ -d "plugins/foundry/skills/audit/templates" ]; then
    AUDIT_TPL="plugins/foundry/skills/audit/templates"
elif [ -d "$AUDIT_TPL" ]; then
    : # keep .claude/ path
else
    AUDIT_TPL="$(find ${HOME}/.claude/plugins/cache -path "*/audit/templates" -type d 2>/dev/null | head -1)" # timeout: 5000
fi
[ -d "$AUDIT_TPL" ] || { printf "! BREAKING: audit/templates not found — run /foundry:init first\n"; exit 1; }
```

If `.claude/` missing, abort immediately. Missing `jq` is warning — audit continues with Check 4 skipped.

**Unsupported flag check** — after extracting supported flags (`--local`, `--upgrade`, `--adversarial`, `--skip-gate`), scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--local\`, \`--upgrade\`, \`--adversarial\`, \`--skip-gate\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Step 1: Run pre-commit (if configured)

```bash
# Check whether pre-commit is installed and a config exists
if (preflight_ok pre-commit || { command -v pre-commit &>/dev/null && preflight_pass pre-commit; }) &&
[ -f .pre-commit-config.yaml ]; then
    pre-commit run --all-files # timeout: 600000
fi
```

Files auto-corrected by pre-commit hooks are clean before structural audit. Note modified files — include in audit scope even if not originally targeted.

If pre-commit not configured, skip silently.

## Step 2: Collect all config files

Enumerate everything in scope with built-in tools. Run all Glob calls in parallel.

**Source selection by `LOCAL_MODE`**:
- **`LOCAL_MODE=false` (default — user setup)**: `.claude/` primary; `plugins/` skipped. Installed/active config only.
- **`LOCAL_MODE=true` (--local — project source)**: `plugins/` primary; `.claude/` secondary for rules/hooks/settings only.

**Without `--local` (`LOCAL_MODE=false`)**:
- **Agents**: Glob tool, pattern `agents/*.md`, path `.claude/`
- **Skills**: Glob tool, pattern `skills/*/SKILL.md`, path `.claude/`
- **Rules**: Glob tool, pattern `rules/*.md`, path `.claude/`
- **Communication**: Read tool on `rules/communication.md`, `rules/quality-gates.md`, `TEAM_PROTOCOL.md`, `skills/_shared/file-handoff-protocol.md`
- **Settings**: Read tool on `.claude/settings.json`
- **Hooks**: Glob tool, pattern `hooks/*`, path `.claude/`

**With `--local` (`LOCAL_MODE=true`)**:
- **Agents (source — primary)**: Glob tool, pattern `*/agents/*.md`, path `plugins/`
- **Skills (source — primary)**: Glob tool, pattern `*/skills/*/SKILL.md`, path `plugins/`
- **Agents (project-local — secondary)**: Glob tool, pattern `agents/*.md`, path `.claude/`
- **Skills (project-local — secondary)**: Glob tool, pattern `skills/*/SKILL.md`, path `.claude/`
- **Rules / Settings / Hooks**: same as without `--local` (`.claude/`)

Merge into single flat inventory. When `LOCAL_MODE=true` and same logical name in both `plugins/` and `.claude/`, prefer plugin source — skip `.claude/` duplicate. Record full paths — Step 3 cross-reference checks depend on current inventory. If MEMORY.md not updated since last agent/skill added/removed, run live disk scan, not cached roster. Stale inventory = primary cause of false-negative cross-reference findings.

**Scope filtering for Step 2** (applies on top of `LOCAL_MODE`):
- `agents` scope — collect agents from active source (`.claude/agents/` or `plugins/*/agents/` per `LOCAL_MODE`); skip skills, rules, hooks
- `skills` scope — collect skills from active source; skip agents, rules, hooks
- `plugins` scope — always reads `plugins/*/agents/*.md` + `plugins/*/skills/*/SKILL.md` regardless of `LOCAL_MODE`; forces `LOCAL_MODE=true`
- `plugins <name>` or `<plugin-name>` (tier 2) scope — collect `plugins/<name>/agents/*.md` + `plugins/<name>/skills/*/SKILL.md` only; forces `LOCAL_MODE=true`; also force `LOCAL_MODE=true` when any scope token matches `plugins` keyword or matches a `plugins/<name>/` directory even without explicit `--local` flag
- `<agent-name>` (tier 3) scope — single matching agent file; `LOCAL_MODE=false`: `.claude/agents/<name>.md`; `LOCAL_MODE=true`: `plugins/*/agents/<name>.md` first, then `.claude/agents/<name>.md`
- `<skill-name>` (tier 3) scope — single matching skill file; same `LOCAL_MODE` resolution as agent above
- Multiple scope tokens — union of all resolved file sets
- `setup`/`plugin` (bare) scope — no agent/skill collection from plugins; see setup/plugin notes below
- Full sweep (no scope) — collect per `LOCAL_MODE` source selection above

**Setup scope**: when `$SCOPE` is `setup`, also collect `plugins/foundry/skills/init/SKILL.md` for Step 3 foundry:curator spawn — only per-file spawn in setup scope. Checks I1–I3 (from `checks-install.md`) run in Step 4 against `~/.claude/` to validate post-install user state.

**`plugins <name>` scope**: verify `plugins/<name>/` exists — abort `! BREAKING: plugins/<name>/ not found` if absent. Collect `plugins/<name>/skills/init/SKILL.md` for Step 3 plus all agents/skills in that plugin. **`plugins` (no name)**: iterate all subdirs under `plugins/` with `agents/` or `skills/` dir.

## Step 3: Per-file audit via foundry:curator

**Context management** — 12+ agents and 14+ skills: accumulating full foundry:curator responses in context causes overflow before aggregation. Use file-based findings to keep main context lean.

**Hard rule — no pre-reading**: Never call Read on agent/skill file before spawning foundry:curator. Spawned agent does the reading. Orchestrator reads only returned JSON envelope. Pre-reading 41 KB files into main context = defeats delegation + causes context overflow at scale.

**Batching rule**: Group files into batches of up to `BATCH_SIZE` — never spawn one agent per file at scale; N parallel agents inflate coordinator context with JSON envelopes. One-per-file only when total files ≤ `BATCH_SIZE`.

**Grouping algorithm**: (1) sort by plugin origin (`plugins/<name>/` prefix); (2) assign each plugin's files to batches, fill to `BATCH_SIZE` before next — keeps same-plugin files together; (3) remaining files (`.claude/` and mixed) fill open slots. Grouping plugin-first, not strictly ordered — unconnected files assigned randomly to reach `BATCH_SIZE`.

**Scope-restricted runs**: fewer than `BATCH_SIZE` files → spawn one foundry:curator for ALL files in scope. Read only relevant template file(s) for active scope, not all 4.

Set up the run directory once before spawning any agents:

```bash
RUN_DIR=".reports/audit/$(date -u +%Y-%m-%dT%H-%M-%SZ)" # timeout: 5000
mkdir -p "$RUN_DIR"                                     # timeout: 5000
echo "Run dir: $RUN_DIR"
```

Spawn **foundry:curator** agents in batches of up to `BATCH_SIZE` (grouping algorithm above) — or one batch if scope ≤ `BATCH_SIZE`. Each spawn prompt must:

1. Include the content from `$AUDIT_TPL/curator-prompt.md`
2. Include the disk inventory from Step 2 (agent/skill list for cross-reference validation)
3. End with:

> "Write your FULL findings (all severity levels, Confidence block) to `<RUN_DIR>/<file-basename>.md` using the Write tool — where `<file-basename>` is the filename only (e.g. `shepherd.md`, `audit-SKILL.md`). Then return to the caller ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/<file-basename>.md\",\"findings\":N,\"severity\":{\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"<filename>: N critical, N high, N medium, N low\"}`"

Replace `<RUN_DIR>` with actual path, `<file-basename>` with filename only.

**Critical context discipline**: response body = JSON envelope on final line only. No other text, output summaries, or findings. All content to file.

> Template file = canonical per-file audit criteria. Disk inventory and RUN_DIR path = runtime values injected per spawn.

After spawns complete: short summaries in context; use to identify files with findings. Full content in run directory files.

**Health monitoring** (CLAUDE.md §8): after spawning all batches, create a checkpoint:

```bash
AUDIT_CHECKPOINT="/tmp/audit-check-$(date +%s)" # timeout: 5000
touch "$AUDIT_CHECKPOINT"                       # timeout: 5000
```

Every `$MONITOR_INTERVAL` seconds: `find $RUN_DIR -newer "$AUDIT_CHECKPOINT" -type f | wc -l` — new files = alive; zero for `$HARD_CUTOFF` seconds = stalled. One `$EXTENSION` extension if output file tail explains delay. On timeout: read partial output from stalled agent's file; surface with ⏱ in final report. Never omit timed-out agents.

## Step 4: System-wide checks

> **Full implementation instructions** are split across 4 scope files in `$AUDIT_TPL/` (resolved in Pre-flight). Read only the file(s) for the active scope at the start of this step — do not read all 4 files unless running a full sweep.
>
> | Scope | File(s) to read |
> | --- | --- |
> | `setup` | `checks-setup.md` + `checks-install.md` (Checks 1–11, I1–I3) |
> | `plugin` | `checks-setup.md` (Checks 7, 8 only) |
> | `plugins` | `checks-setup.md` (Checks 7, 8) + `checks-agents.md` + `checks-skills.md` + `checks-shared.md` (14, 15, 17, 12, 13, 25, 29) |
> | `plugins <name>` | same as `plugins` — scoped to one plugin directory |
> | `agents` | `checks-agents.md` + `checks-shared.md` (run only: 14, 15, 17, 12, 13, 25, 29) + `checks-skills.md` (Check 22 only) |
> | `skills` | `checks-skills.md` (21–24, 27, 28, 30, 31) + `checks-shared.md` (run only: 14, 15, 17, 12, 13, 25, 29) |
> | `rules` | `checks-shared.md` (run only: 18, 12, 13, 29) |
> | `communication` | `checks-shared.md` (run only: 15, 16, 12, 13, 29) |
> | No scope (full) | all 4 files |

**Delegation for full-sweep runs**: for full-sweep (no scope), spawn dedicated `foundry:curator` per scope group, passing template file path and RUN_DIR: agents-checks (reads `checks-agents.md` + relevant `checks-shared.md`), skills-checks (reads `checks-skills.md` + relevant `checks-shared.md`), shared-checks (reads `checks-shared.md`), setup-checks (reads `checks-setup.md` + `checks-install.md`). Each writes findings to `<RUN_DIR>/system-checks-<scope>.md`, returns only JSON envelope. Orchestrator does NOT read template files — passes path to spawned agent only.

Run checks below. Native tools first (Glob, Grep, Read); Bash only for pipeline ops native tools can't do.

**Agent roster consistency policy**: evaluate agent system as capability set, not just files. For every overlap in checks 20 or 17, explicit judgment:

- **keep** when both roles own meaningfully different acceptance criteria
- **sharpen** when both roles justified but descriptions/handoffs too fuzzy
- **merge/prune** when roles differ mostly by tone or examples, not decision surface

Don't leave overlap findings as vague "potential duplication." Audit must say which outcome applies and why.

**Context discipline for Step 4**: write all check findings to `$RUN_DIR/system-checks.md` (Write tool after checks complete), not main context. Keep one-line status per check in context:

- `✓ Check N — <one-line result>` (pass)
- `⚠ Check N — N findings` (issues)

**Scope filter**: when `$SCOPE` is set, run only checks listed for that scope; skip all others silently.

- `agents` — Checks 14, 15, 19, 20, 17, 12, 13, 25, 22, 26, 29 (files: `.claude/agents/*.md` + `plugins/*/agents/*.md`)
- `skills` — Checks 14, 15, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29 (files: `.claude/skills/*/SKILL.md` + `plugins/*/skills/*/SKILL.md`)
- `rules` — Checks 18, 12, 13, 29
- `communication` — Checks 15, 16, 12, 13, 29
- `setup` — Checks 1, 2, 3, 4, 5, 9, 10, 11, 7, 6, 8, 30, I1, I2, I3 (Step 3: one foundry:curator spawn for `init` SKILL.md only; I1–I3 read `~/.claude/`)
- `plugin` — Checks 7, 8 (Step 3: one foundry:curator spawn for `plugins/foundry/skills/init/SKILL.md` only)
- `plugins` — Checks 7, 8, 14, 15, 19, 20, 17, 12, 13, 25, 22, 26, 21, 23, 24, 27, 28, 29 (files: all `plugins/*/agents/*.md` + `plugins/*/skills/*/SKILL.md`; Step 3: foundry:curator batches for all plugin agents + skills + each plugin's init SKILL.md)
- `plugins <name>` or `<plugin-name>` (tier 2) — same check list as `plugins`, scoped to `plugins/<name>/` only
- `<agent-name>` (tier 3) — Checks 14, 15, 19, 20, 17, 12, 13, 25, 22, 26, 29 (one file only; no cross-plugin Checks 7/8)
- `<skill-name>` (tier 3) — Checks 14, 15, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29 (one file only)
- Multiple scope tokens — union of check lists for all resolved scope types; de-duplicate; run each check once against union file set
- No scope argument — run all checks

### Check summary
<!-- Full check implementations in `audit/templates/checks-*.md` — this table is the quick-reference index only. -->

| # | Name | Severity | Scope | Notes |
| --- | --- | --- | --- | --- |
| 1 | Inventory drift (MEMORY.md vs disk) | medium | setup | Agents + skills on disk vs MEMORY.md roster |
| 2 | README vs disk | medium | setup | Agent/skill table rows in README vs disk |
| 3 | settings.json permissions | medium | setup | Bash commands in skills vs allow list |
| 4 | permissions-guide.md drift | medium | setup | Every allow entry must have a guide row, and vice versa |
| 5 | Permission safety audit | critical/high | setup | Allow entries must be non-destructive, reversible, local-only |
| 6 | Stale settings.json allow entries | low | setup | Allow entries with no usage in any .claude/ file |
| 7 | codex plugin integration | medium | setup | Plugin installed and enabled; dispatches work |
| 8 | foundry plugin correctness | critical/high/med | setup | 8a manifest, 8b symlinks, 8c hook scripts, 8d hooks.json, 8e dry-run validate, 8f perms drift |
| 9 | Agent color drift | medium | setup | statusline COLOR_MAP vs agent frontmatter color: |
| 10 | RTK hook alignment | high/medium | setup | RTK_PREFIXES vs installed RTK subcommands - skip if rtk absent |
| 11 | Memory health | low | setup | 11a duplicate rules, 11b stale version pins, 11c absorbed feedback files |
| I1 | Plugin cache intact | high | setup | foundry in ~/.claude/plugins/installed_plugins.json; installPath exists |
| I2 | Settings merge complete | medium | setup | statusLine, permissions.allow, enabledPlugins.codex in ~/.claude/settings.json |
| I3 | Link health (conditional) | high | setup | Symlinks in ~/.claude/rules/ and ~/.claude/TEAM_PROTOCOL.md resolve; fix: /foundry:init |
| 12 | File length | medium | all | Agents ≈300 lines, skills ≈600 lines, rules ≈200 lines; report only — fix = remove content, never collapse lines |
| 13 | Heading hierarchy continuity | medium | all | Heading level jumps >1 (e.g. ## to ####) |
| 14 | Orphaned follow-up references | medium | agents/skills | Skill-name refs in SKILL.md vs disk inventory |
| 15 | Hardcoded user paths | high | agents/skills | /Users/ and /home/ in config files + settings.json |
| 16 | Example value vs. token cost | low | agents/skills | Inline examples: high-value vs. low-value (prose restatement) |
| 17 | Cross-file content duplication | medium | agents/skills | 40%+ consecutive step overlap; recommend canonical owner or merge path |
| 18 | Rules integrity | high/medium | rules | 18a inventory, 18b frontmatter, 18c redundancy, 18d cross-ref integrity |
| 19 | Model tier appropriateness | medium/high | agents | Tier policy: opusplan/opus/sonnet/haiku - report only |
| 20 | Agent description routing | medium/low | agents | 20a overlap pairs, 20b NOT-for coverage, 20c trigger specificity, 20d keep/sharpen/prune |
| 21 | Skill frontmatter conflicts | critical | skills | context:fork + disable-model-invocation:true is broken |
| 22 | Calibration coverage gap | medium/low | agents/skills | Unregistered calibratable skills/agents; stale domain table entries |
| 23 | Bash misuse / native tool substitution | medium | agents/skills | cat/grep/find/echo>/sed replaceable by native tools |
| 24 | Skill sequence compatibility | high/medium | skills | 24a target skill not on disk; 24b argument absent from argument-hint; scans skills, agents, READMEs |
| 25 | Implicit agent references | high | agents/skills | subagent_type without plugin prefix; exempt: built-in types |
| 26 | Symbol and shortcut consistency | medium/low | agents/skills | 26a same-concept emoji conflict, 26b slash notation mixed, 26c body contradicts legend |
| 27 | Cross-plugin shared-file ref integrity | critical/high/med | skills | 27a absent from foundry/\_shared/; 27b catch-22 (fallback needs foundry); 27c plugin-local \_shared/ unmounted |
| 28 | Cross-plugin agent dispatch fallback | high/medium | skills | 28a no fallback for cross-plugin dispatch; 28b fallback present but incomplete |
| 29 | LLM context minimality | medium/low | agents/skills/rules | Within-file repetition, prose inflation, obvious-consequence restatement — report only |
| 30 | Config token overhead | medium/low | setup | 30a CLAUDE.md + global + rules/ > 100 KB; 30b single rules file > 10 KB |
| 31 | Tool-body consistency | medium | skills | Skill `allowed-tools` must include every tool the workflow body invokes; see `checks-skills.md` for full spec |

### Claude Code docs freshness (within Step 4)

Spawn **foundry:web-explorer** to fetch current Claude Code docs. **File-based handoff**: writes full findings to `$RUN_DIR/docs-freshness.md`. Return ONLY compact JSON envelope: `{"status":"done","file":"$RUN_DIR/docs-freshness.md","findings":N,"deprecated":N,"new_features":N,"confidence":0.N,"summary":"N findings, N deprecated, N new features"}`

Validate local config against fetched docs:

- **Hook validation**: every hook event name and `type` in documented schema; no deprecated `decision:`/`reason:` fields
- **Agent frontmatter validation**: all fields in documented schema; `model` values are recognized short-names
- **Skill frontmatter validation**: all fields in documented schema
- **Improvement opportunities**: new features passing genuine-value filter → **Upgrade Proposals** table (max 5; classify `config` or `capability`)

Findings: deprecated/invalid = **high**; deprecated frontmatter field = **medium**; new feature not used = **Upgrade Proposals** (not LOW).

<!-- URLs fetched live by web-explorer at runtime; graceful degradation: if any 404, instruct navigation from code.claude.com homepage. -->

After checks complete: collect `⚠` lines, write full details to `$RUN_DIR/system-checks.md`, include only summary table in context.

## Step 5: Aggregate and classify findings

**Delegate aggregation** to consolidator agent to avoid flooding main context. Spawn **foundry:curator** consolidator:

> "Read all finding files in `<RUN_DIR>/` (\*.md files from Steps 3–4, including `docs-freshness.md` if present). Apply the severity classification from `plugins/foundry/skills/audit/severity-table.md`. Antipatterns that indicate severity under-classification are also in that file. Group all findings by severity (critical, high, medium, low). Apply the one-finding-per-issue rule: when a single location has multiple distinct problems at different severities, emit one finding entry per problem. Write the aggregated severity table to `<RUN_DIR>/aggregate.md` using the Write tool. Also write `<RUN_DIR>/summary.jsonl` — one compact JSON object per line, one line per finding: `{"file":"<basename>","sev":"high|medium|low","id":"H1","line":"<line number or null>","category":"<category>","one_line":"<finding description>"}`. This file is what the orchestrator will read; aggregate.md is for human review only. Return ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/aggregate.md\",\"findings\":N,\"severity\":{\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"N findings total: C critical, H high, M medium, L low\"}`"

Main context receives only that one-liner. Orchestrator MUST NOT read `aggregate.md` in full — 200–600 lines, overflows context on large audits. Use `$RUN_DIR/summary.jsonl` for all dispatch decisions in Steps 7 and 8.

## Step 6: Cross-validate critical findings

```bash
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/cross-validation-protocol.md" ] || { printf "⚠ WARNING: cross-validation-protocol.md not found at $_SHARED — skipping cross-validation\n"; }
```

Read and follow cross-validation protocol from `$_SHARED/cross-validation-protocol.md` (if exists).

**Skill-specific**: the verifier agent is always **foundry:curator**.

## Step 7: Report findings

Emit report (omit Upgrade Proposals if none passed genuine-value filter):

```markdown
## Audit Report

### Findings by Severity
#### Critical (N) | High (N) | Medium (N) | Low (N)
| File | Line | Issue | Category |
|---|---|---|---|
| agents/foo.md | 42 | References `bar-agent` which does not exist on disk | broken cross-ref |

### Summary
- Total: N (C critical, H high, M medium, L low)
- Fix via follow-up gate: (a) critical+high · (b) critical+high+medium · (c) all

### Upgrade Proposals (N — pick `/audit --upgrade` from gate to apply)
| # | Feature | Type | Rationale |
|---|---------|------|-----------|
```

After report → fire **Follow-up gate**. If user picks fix option (a–c), proceed inline to Step 8. Otherwise done.

## Step 8: Delegate fixes to subagents

> **HARD RULE — No inline fixes**: Orchestrator MUST NOT apply any fix directly via Edit or Write — not even single-line edits. Every fix at every severity level goes through sub-agent. Not optional. Spawning overhead always lower than context cost of 40+ inline Edit calls in `fix all` run.

**Fix Action Hierarchy** — before any fix:

1. **Reason** — finding correct? Flagged content genuinely wrong or just wrong place? Misidentified → discard, don't act.
2. **Relocate** — correct content, wrong location → move, not remove.
3. **Consolidate** — redundant with nearby content → merge into one clearer location.
4. **Minimize** — too long but valid → compress (tighten wording, remove restatements).
5. **Remove** — only if none above apply. Never remove solely because flagged as verbose.

Apply hierarchy to every fix at all severity levels.

**Adversarial pre-apply validation gate** — each proposed fix must clear two-agent gate before spawning fix agent:

1. Spawn **foundry:challenger** with finding text, file path, proposed fix — challenge: "Is this finding real? Is fix appropriate? Does it risk removing load-bearing behavioral content (runtime gates, behavioral invariants, execution constraints, `<notes>` checkpoints)?"
2. Spawn **foundry:curator** same context — validate: "Fix correct per Fix Action Hierarchy? Preserves behavioral integrity? Could silently remove load-bearing content even if appearing redundant or verbose?"
3. Both spawns in parallel per file. Each writes verdict to `<RUN_DIR>/gate-<file-basename>-<finding-id>.md`; returns only: `{"verdict":"approved"|"blocked","reason":"<one-line>","file":"<path>"}`
4. **Either** returns `blocked` → skip fix agent; add to `blocked_findings` with reason; surface as `⚠ GATE-BLOCKED — needs human review: <reason>`
5. **Both** `approved` → proceed to fix agent

Gate applies at every severity level. Skip only for inline-exception cases (settings.json, CLAUDE.md, dead loops, model tier).

Fix agent by file type:

- **`.claude/agents/*.md` and `.claude/skills/*/SKILL.md`** → spawn **foundry:curator** — domain expertise in config quality, has `Write`/`Edit` tools
- **Code files** (`.py`, `.js`, `.ts`, etc.) → spawn **foundry:sw-engineer**

**Phase 4 delegation rule**: edits touching >3 files → delegate to `foundry:sw-engineer` — pass findings list + target file paths; returns compact status JSON.

Spawn one agent per affected file, batch all findings per file into single prompt. Issue **all spawns in a single response** for parallelism.

Each subagent prompt: read from `$AUDIT_TPL/fix-prompt.md`, fill `<file path>` and findings list.

**Preferred orchestration pattern — audit-fix sub-agent**

<!-- Canonical multi-file orchestration template — intentionally inline; NOT derived from fix-prompt.md (per-file only). Keep both in sync when changing shared audit-fix behavior. -->

After gate fires (Step 7): finding count > 10 or user picked "Fix all" → use audit-fix sub-agent pattern below (handles Steps 8–10 in isolation); otherwise use inline batched pattern at end of this step.

**Gate authority**: sub-agent path → orchestrator Step 7 gate **skipped** — sub-agent runs own gate internally, authoritative. Inline batched path (≤10 findings) → orchestrator Step 7 gate authoritative, no sub-agent gate. Never double-gate.

Spawn a dedicated **audit-fix** sub-agent:

```markdown
Read `<RUN_DIR>/summary.jsonl` — this is the findings list (one JSON object per line).
Read `$AUDIT_TPL/fix-prompt.md` for the per-file fix prompt template.
**Adversarial pre-apply gate**: for each unique file in the findings list, spawn **foundry:challenger** AND **foundry:curator** in parallel — challenge/validate each finding batch: "Is each finding real? Is the fix appropriate? Does any fix risk removing load-bearing behavioral content?" Each writes verdict to `<RUN_DIR>/gate-<file-basename>.md`; return `{"verdict":"approved"|"blocked","reason":"<one-line>","file":"<path>"}`. If either returns `blocked`: mark findings for that file as blocked (add to `blocked_findings` list with reason); skip fix agent. Proceed to fix agent only if both return `approved`.
Issue all gate spawns in a single response (parallel). After gate verdicts received, issue all fix spawns in a single response (approved files only, parallel).
For each file that passed the gate, spawn one fix agent (foundry:curator for .md files, foundry:sw-engineer for .js/.py files) with all approved findings batched into a single prompt.
After all fix agents complete, spawn foundry:curator re-audit agents (one per changed file) to confirm fixes held.
Write a completion summary to `<RUN_DIR>/fix-summary.md`:
  - findings_total: N
  - fixed: N
  - blocked: N (gate-rejected; listed in blocked_findings)
  - failed: N
  - re_audit_clean: true|false
  - blocked_findings: [{id, file, reason}, ...]
Return ONLY: {"status":"done","file":"<RUN_DIR>/fix-summary.md","fixed":N,"blocked":N,"failed":N,"re_audit_clean":true|false,"confidence":0.N}
```

Orchestrator reads only compact JSON envelope. Does NOT read fix-summary.md unless `re_audit_clean: false` or `failed > 0`.

Finding count ≤ 10 and user picked "Fix critical+high" or "Fix critical+high+medium" (not "Fix all") → inline batched pattern (one fix-agent per file, all parallel) acceptable; no dedicated sub-agent.

**Findings that bypass fix-agent delegation (report-only):**

No Edit or Write tool calls performed in these cases — findings surfaced to user only.

- **settings.json permission missing**: report only — structural JSON edits risky to delegate
- **CLAUDE.md contradiction**: raise to user — do not auto-fix (CLAUDE.md takes precedence)
- **Dead loop**: flag for user review — human judgment needed on which link to break
- **Model tier mismatch**: report only — assignments may be intentional for cost/latency trade-offs; user decides

After subagents complete, collect results and proceed to Step 10.

**Low findings** (nits): fix only when `fix all` passed — otherwise collect in final report for optional manual cleanup.

## Step 9: Codex cross-file check

After Step 8 fix agents complete, before foundry:curator re-audit:

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
```

If `$CODEX_AVAILABLE` non-empty: read `$_SHARED/codex-prepass.md`, follow Codex pre-pass instructions applied to combined diff of Step 8 fixes. Otherwise: `echo "⚠ codex plugin not available — skipping codex pass"`

Treat findings as additional issues entering Step 10 re-audit scope. Skip if Step 8 touched only 1 file.

## Step 10: Re-audit modified files + confidence check

For every file changed in Step 8, spawn **foundry:curator** to confirm fix resolved finding and no new issues introduced. Write full re-audit findings to `<RUN_DIR>/<file-basename>-reaudit.md`; return ONLY compact JSON envelope: `{"status":"done","file":"<RUN_DIR>/<file-basename>-reaudit.md","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N,"summary":"<filename>: fix confirmed, N residual findings"}`

```bash
# Spot-check: confirm the previously broken reference no longer appears
grep -n "<broken-name>" <fixed-file>
```

**Confidence re-run**: apply per quality-gates.md standard protocol. Parse confidence scores from Step 3 and Step 10 summaries. **Score < 0.7**: re-spawn foundry:curator on that file with specific `Gaps:` field gap addressed; still < 0.7 after retry → flag with ⚠, include gap in final report. Recurring low-confidence gaps (same gap, same file, multiple runs) → candidate for foundry:curator `\<antipatterns_to_flag>` or agent instructions.

**Convergence loop**: re-audit surfaces new fixable findings within gate-selected severity threshold → loop back to Step 8. Repeat until:

- Zero fixable findings remain → mark fix pass complete, or
- Hard limit: **5 total fix passes** (including initial Step 8) — still not converged → surface all remaining fixable findings with `⚠ CONVERGENCE LIMIT` warning explaining which issues resisted fixing.

Track pass count with counter initialized to 1 at first Step 8. Increment before each re-entry. Never suppress findings to clean counter.

Audit-fix sub-agent (when used) must apply this loop internally — instruct to keep spawning fix agents and re-audit agents until clean or 5-pass limit.

**Cross-file re-validation**: after per-file re-audit, re-run Step 4 checks sensitive to modified files:

- Check 1 (inventory drift) — if any agent or skill file modified
- Check 2 (README vs disk) — if any agent or skill added, renamed, or deleted
- Check 14 (orphaned follow-up references) — if any skill file modified
- Check 17 (cross-file content duplication) — if 2+ files modified
- Check 25 (implicit agent references) — if any agent or skill file modified
- Check 27 (cross-plugin shared-file ref integrity) — if any skill file modified

Write findings to `<RUN_DIR>/crossfile-revalidation-pass<N>.md` where N is current pass count. Include new findings in convergence loop input for next Step 8 iteration.

## Step 11: Final report

Output complete audit summary. List each audited file by name in `### Files Audited` — from Step 2 inventory; counts alone insufficient.

```markdown
## Audit Complete — .claude/ config

### Files Audited
- **Agents** (N): name-1, name-2, ...
- **Skills** (N): name-1, name-2, ...
- **Rules** (N): name-1, name-2, ...
- **Hooks** (N): file-1.js, file-2.js, ...
- **Settings**: settings.json
- **Communication** (if in scope): communication.md, quality-gates.md, TEAM_PROTOCOL.md, file-handoff-protocol.md

### Findings
| Severity | Found | Fixed | Remaining |
|---|---|---|---|
| critical | N | N | 0 |
| high | N | N | 0 |
| medium | N | N | 0 |
| low | N | N ("Fix all" only) | N |

**Fix convergence**: Converged in N pass(es) — 0 fixable findings remain.
```

Or if limit hit:

```markdown
**Fix convergence**: ⚠ CONVERGENCE LIMIT reached (5 passes) — N fixable findings remain (see Remaining section).
```

(Omit fix convergence line when user picked "skip" from gate — only shown when fix option chosen.)

```markdown
### Fixes Applied

| File | Change |
| --- | --- |
| agents/foo.md | Replaced broken ref `old-agent` → `correct-agent` |

### Remaining (low/nits — auto-fixed only with 'fix all'; otherwise manual review optional)

- [low findings that were not auto-fixed]
- [any infinite loops flagged for user decision]

### Agent Confidence

| File | Score | Label | Gaps |
| --- | --- | --- | --- |
| agents/foo.md | 0.92 | high | — |
| skills/bar/SKILL.md | 0.64 | ⚠ low | no runtime data for bash validation |

Low-confidence files re-audited: N | Still uncertain after retry: N (see gaps above)

### Next Step

Run `/foundry:init` to propagate clean config to ~/.claude/

```

## Mode: upgrade

**Trigger**: `/audit --upgrade`

```bash
UPGRADE_MD=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/audit/modes/upgrade.md 2>/dev/null | head -1)  # timeout: 5000
[ -f "$UPGRADE_MD" ] || UPGRADE_MD="plugins/foundry/skills/audit/modes/upgrade.md"
```

Read and execute `$UPGRADE_MD`.

## Mode: adversarial (alias: --challenge)

**Trigger**: `/audit [<scope>...] --adversarial`

Adversarial review of all agents + skills in scope. Runs parallel with or after standard per-file audit (Step 3). Surfaces issues curator pass misses: subtle logic flaws, inconsistent claims, NOT-for gaps, scope leakage, cross-file contradictions.

**Phase A — Challenger sweep** (parallel with Phase B):

For each file in scope (Step 2 inventory; default all agents + skills if no explicit scope), spawn **foundry:challenger**:

> "Adversarially challenge this agent/skill. Do NOT accept claims at face value. Find: (1) unstated assumptions that will fail in edge cases, (2) NOT-for coverage gaps — tasks this agent will wrongly accept because exclusions are incomplete, (3) conflicting instructions that produce non-deterministic or contradictory behavior, (4) workflow steps that would route to the wrong sub-agent for the stated goal, (5) implicit scope that contradicts explicit NOT-for lines. Report every finding with specific evidence from the file."
> Write full findings to `<RUN_DIR>/challenger-<file-basename>.md`. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use same `BATCH_SIZE` grouping as Step 3 — same plugin-aware batching applies.

**Phase B — Codex adversarial pass** (parallel with Phase A):

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
```

If `[ -n "$CODEX_AVAILABLE" ]`: read `$_SHARED/codex-prepass.md`, run Codex pass on all in-scope files. Focus Codex on: cross-file inconsistencies, circular dispatch chains, agent description ambiguities causing routing failures, workflow steps assuming capabilities declared tools don't provide. Else: `echo "⚠ codex plugin not available — skipping codex adversarial pass"`.

Codex writes per-file findings to `<RUN_DIR>/codex-adversarial-<file-basename>.md`. Return compact JSON envelope per file.

**Phase C — Aggregate and deduplicate**:

Spawn **foundry:curator** consolidator to merge Phase A + Phase B findings. Cross-reference against standard audit `summary.jsonl` (same RUN_DIR). Surface only findings NOT already in standard audit — adversarial adds signal, not noise.

In adversarial-only mode (`--adversarial` flag without preceding standard audit), Steps 3–6 are skipped so no `summary.jsonl` exists in RUN_DIR. Dedup against most recent standard audit `summary.jsonl` within the same RUN_DIR or from any run within the last 24h (check `.reports/audit/` for recent dirs). If no standard audit found within 24h, skip dedup and surface all adversarial findings without overlap filtering.

Write deduplicated findings to `<RUN_DIR>/adversarial-aggregate.md` and `<RUN_DIR>/adversarial-summary.jsonl` (same JSONL format as Step 5). Return: `{"status":"done","new_findings":N,"overlapping":N,"severity":{"critical":N,"high":N,"medium":N,"low":N}}`

**Report format**:

```markdown
## Adversarial Audit — <date> — <scope>

| File | Challenger | Codex | New Findings | Top Issue |
|------|-----------|-------|--------------|-----------|
| agents/curator.md | 3 | 1 | 2 | NOT-for gap: accepts task X |
```

Adversarial findings feed into standard fix pipeline (Steps 7–10) when user picks fix level from follow-up gate.

**Adversarial-only runs** (no standard audit): skip Steps 3–6; run only Phases A–C above; report adversarial findings only.

**Flag aliases**: `--adversarial` and `--challenge` are identical — either triggers this mode.

## Follow-up gate

**Always fires** unless `--skip-gate` passed (programmatic callers). Call `AskUserQuestion` — do NOT write options as plain text first. Map options directly into tool call arguments.

When user picks fix option (a–c): run Steps 8–10 inline (state on disk in `summary.jsonl`); no recursive `/audit` call.

- question: "What next?" (include counts, e.g. "2 critical, 4 high, 3 medium, 1 low. What next?")
- (a) label: `Fix critical + high` — auto-fix critical and high findings
- (b) label: `Fix critical + high + medium` — auto-fix critical, high, and medium findings (recommended)
- (c) label: `Fix all` — auto-fix all findings including low
- (d) label: `/audit --upgrade` — fetch latest Claude Code docs and apply improvements
- (e) label: `/audit --adversarial` — adversarial review with foundry:challenger + Codex
- (f) label: `/foundry:init` — sync verified config to `~/.claude/`
- (g) label: `skip` — no action

After completing `--upgrade` or `--adversarial`: also fire this gate (omit option (d) or (e) respectively — no point repeating the mode just run).

</workflow>

<notes>

- **`!` Breaking findings**: when skill or agent completely non-functional (check #7, broken cross-refs, invalid hook events), prefix finding with `!` and state impact + fix in one place — don't bury in table row. Surfaces as **`! BREAKING`** in bash output and as prominent callout in final report.
- **Terminal color conventions** (used in Step 4 bash output):
  - `RED` (`\033[1;31m`) — breaking/critical: `! BREAKING`, `ERROR`
  - `YELLOW` (`\033[1;33m`) — warnings/medium: `⚠ MISSING`, `⚠ ORPHANED`, `⚠ DIFFERS`
  - `GREEN` (`\033[0;32m`) — pass status: `✓ OK`, `✓ IDENTICAL`
  - `CYAN` (`\033[0;36m`) — source agent name or fix hint
- **settings.json is hands-off**: missing permissions always reported, never auto-edited — structural JSON edits risk breaking Claude Code config loading
- **Dead loops need human judgment**: cycle in follow-up chains might be intentional (e.g., refactor → review → fix → refactor) — flag and explain, don't auto-remove
- **Convergence loop replaces cycle cap**: fix loop runs until zero fixable findings or 5-pass hard limit — see Step 10 for full protocol
- **Relationship to curator**: `foundry:curator` = single-file reactive audit; `/audit` = system-wide sweep running foundry:curator at scale + cross-file checks
- **Paths must be portable**: `.claude/` for project-relative, `~/` or `$HOME/` for home — never literal `/Users/<name>/` or `/home/<name>/` (anti-examples only); applies to ALL config files including `settings.json`
- **Bash error logging**: if bash block in Pre-flight or Step 4 fails unexpectedly, append JSONL line to `.claude/logs/audit-errors.jsonl` (`{"ts":"<ISO>","check":"<N>","error":"<message>"}`) for post-mortem — never swallow errors silently.
- **Parallel execution rule**: after Step 2, launch Steps 3 and 4 in same response — all foundry:curator spawns AND system-wide bash checks issued together. Do NOT run Step 3 first then Step 4. Aggregation (Step 5) waits for both. Docs-freshness web-explorer (within Step 4) launches in same parallel batch.
- **Token cost**: Step 3 (foundry:curator spawns) most expensive. For quick structural scan needing only cross-reference + inventory validation, Step 4 system-wide checks often sufficient. Run `/audit agents` or `/audit skills` to scope, or skip Step 3 for fast pass when per-file quality already trusted.
- **Skill-creator complement**: for testing whether skill trigger descriptions fire correctly (trigger accuracy, A/B testing), see Anthropic's official skill-creator utility. `/audit` checks structural quality; `skill-creator` validates right skill selected by Claude Code dispatcher when user types command.
- Follow-up chains:
  - Audit clean → pick `/foundry:init` from gate to propagate verified config to `~/.claude/`
  - Audit found structural issues → review flagged files manually before syncing; pick fix level from gate
  - Audit found many low items → pick "Fix all" from gate, or run `/develop:refactor` (requires `develop` plugin) for targeted cleanup
  - After fixing agent instructions (from audit gate) → `/calibrate <agent>` to verify fix improved recall and confidence calibration
  - Audit Check 20 found description overlap → `/calibrate routing` to verify behavioral routing impact; update descriptions for confused pairs based on routing report
  - Audit surfaced upgrade proposals → pick `/audit --upgrade` from gate to apply with correctness checks and calibrate A/B evidence for capability changes
  - `/audit --upgrade` reverted capability change → run `/calibrate <agent> --full` for deeper signal (N=10 vs N=3 used in upgrade mode)
  - Audit Check 22 found unregistered calibratable mode → update `calibrate/modes/skills.md` domain table and run `/calibrate skills` to verify new target works
  - Audit Check 22 found stale domain table entry → remove from `calibrate/modes/skills.md`

</notes>
