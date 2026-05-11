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

Run a full-sweep quality audit of the `.claude/` configuration and all `plugins/*/` agent and skill files: every agent file, every skill file, every rule file, settings.json, and hooks. Spawns `foundry:curator` for per-file analysis, then aggregates findings system-wide to catch issues that only surface across files — infinite loops, inventory drift, missing permissions, and cross-file interoperability breaks. Reports all findings; fix level chosen from the always-fire follow-up gate after the report.

</objective>

<inputs>

- **$ARGUMENTS**: optional — parse `--flags` first, then resolve remaining tokens as scope

  **Flags** (order independent, any combination with scope):
  - `--local` — audit source tree (`plugins/*/`) rather than user setup (`.claude/` + installed cache); for plugin-dev workflows where local edits aren't yet installed; sets `LOCAL_MODE=true`
  - `--upgrade` — fetch latest Claude Code docs, filter new features by genuine value, then apply: **config** changes (apply + correctness check), **capability** changes (calibrate before → apply → calibrate after → accept if Δrecall ≥ 0 and ΔF1 ≥ 0). Skip to **Mode: upgrade**. Mutually exclusive with `--adversarial`.
  - `--adversarial` (alias: `--challenge`) — adversarial review of all agents + skills in scope using `foundry:challenger` (Phase A) + Codex adversarial pass (Phase B); surfaces issues beyond standard per-file audit; see **Mode: adversarial**. Mutually exclusive with `--upgrade`.
  - `--skip-gate` — suppress the follow-up gate; for programmatic callers (e.g. `/manage` step 9)

  **Legacy positional tokens** (`fix`, `upgrade`, `adversarial`, `challenge`, `ab`, `apply`, `fast`, `full`) — **hard error**: print migration hint and stop. Example: "`fix medium` removed — run `/audit` and pick fix level from gate, or pass `--upgrade` / `--adversarial` as flags."

  **Scope tokens** (positional, space-separated — resolve each token before Step 2):
  - No scope: full sweep — file sources determined by `--local` flag: **without `--local`** covers user setup (`.claude/agents/`, `.claude/skills/`, `.claude/rules/`, hooks, settings, `~/.claude/plugins/cache/` installed versions); **with `--local`** covers project source tree (`plugins/*/agents/`, `plugins/*/skills/`) + `.claude/` as secondary
  - `agents` — restrict sweep to agent files only
  - `skills` — restrict sweep to skill files only
  - `rules` — restrict sweep to rule files only
  - `communication` — restrict sweep to communication governance files: `rules/communication.md`, `rules/quality-gates.md`, `TEAM_PROTOCOL.md`, `skills/_shared/file-handoff-protocol.md`
  - `setup` — restrict sweep to system-configuration files: `settings.json`, `permissions-guide.md`, hooks, `MEMORY.md`, `README.md`, plugin integration, and post-install user state (Checks 1–11, 30, I1, I2, I3); Step 3 runs for `init` SKILL.md only (one foundry:curator spawn); Checks I1–I3 read `~/.claude/` not `.claude/`
  - `plugin` — restrict sweep to plugin integration only: codex plugin (Check 7), foundry plugin + init validation (Check 8, including 8g); Step 3 runs for `init` SKILL.md only (one foundry:curator spawn)
  - `plugins` — full audit of all plugins: per-file audit of every `plugins/*/agents/*.md` and `plugins/*/skills/*/SKILL.md` + integration checks (7, 8) for each plugin found
  - `plugins <name>` — same as `plugins` but scoped to one plugin: per-file audit of `plugins/<name>/agents/*.md` and `plugins/<name>/skills/*/SKILL.md` + integration checks; `<name>` must match a directory under `plugins/` (e.g. `plugins foundry`, `plugins oss`, `plugins research`)
  - `<plugin-name>` — **tier 2 shorthand**: bare plugin directory name (e.g. `oss`, `foundry`, `research`, `develop`, `codemap`) auto-resolved when token matches a directory under `plugins/`; equivalent to `plugins <name>`; no `plugins` prefix needed
  - `<agent-name>` — **tier 3**: name matches `plugins/*/agents/<name>.md` or `.claude/agents/<name>.md`; runs agent checks only (Checks 14, 15, 19, 20, 17, 12, 13, 25, 22, 26, 29); one file in Step 3
  - `<skill-name>` — **tier 3**: name matches `plugins/*/skills/<name>/SKILL.md` or `.claude/skills/<name>/SKILL.md`; runs skill checks only (Checks 14, 15, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29); one file in Step 3
  - Multiple scope tokens — any combination space-separated; scope = union of resolved file sets: `agents skills`, `oss research`, `shepherd curator`, `review resolve`; check list = union of per-scope check lists (de-duplicated)

  **Scope token resolution** (each remaining token after flag-strip, resolved before Step 2): (1) reserved scope keywords (`agents`, `skills`, `rules`, `communication`, `setup`, `plugin`, `plugins`) → use as-is; (2) token matches directory under `plugins/<token>/` → tier 2; (3) token matches agent file in `plugins/*/agents/<token>.md` or `.claude/agents/<token>.md` → tier 3 agent; (4) token matches skill dir `plugins/*/skills/<token>/` or `.claude/skills/<token>/` → tier 3 skill; (5) no match → error and stop

  **Valid combinations**: scope tokens and flags can be mixed freely: `foundry --local`, `foundry --adversarial`, `agents skills --local`, `oss research --adversarial`. `--upgrade` and `--adversarial` mutually exclusive — error if both passed. `--local` compatible with all other flags.

</inputs>

<constants>

<!-- Background agent health monitoring (CLAUDE.md §8) — applies to Step 3 foundry:curator spawns -->
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay
BATCH_SIZE=5           # max files per foundry:curator spawn in Step 3; keep small to avoid context compaction

</constants>

<workflow>

**Task hygiene**: Before creating tasks, call `TaskList`. For each found task:

- status `completed` if the work is clearly done
- status `deleted` if orphaned / no longer relevant
- keep `in_progress` only if genuinely continuing

**Orchestration contract**: the audit orchestrator is a thin coordinator — it issues Glob/Grep calls for inventory, spawns agents, reads JSON envelopes, and aggregates findings. It must NOT read agent/skill/rule file bodies directly. Any inline read of a non-template file is a protocol violation and will cause context overflow at scale.

**Task tracking**: create tasks (TaskCreate) for each major phase; mark status live:

- Phase 1: setup + collect (Pre-flight + Steps 1–2) → mark in_progress when starting, completed when file list is ready
- Phase 2: per-file audit (Step 3) → mark in_progress when agents launch, completed when all reports received
- Phase 3: system-wide checks (Step 4) → mark in_progress when checks start, completed when all checks done
- **Phases 2 and 3 launch simultaneously** — mark both in_progress in the same update; they are independent and must not be serialized
- Phase 4: aggregate + fix (Steps 5–10) → mark in_progress, then completed when fixes land; **do NOT mark completed until EITHER: (a) follow-up gate fires (Step 7) AND fixes applied or user chose skip; OR (b) `--skip-gate` mode active — gate is suppressed, complete after Step 5 aggregation; completing Step 5 aggregation alone does NOT complete Phase 4 in normal mode**
- Phase 5: final report (Step 11) → mark in_progress, then completed before output
- On loop retry or scope change → create a new task; do not reuse the completed task

Surface progress to the user at natural milestones: after system-wide checks ("✓ Checks 1-21 complete, N findings so far — spawning per-file audits"), after agent reports ("Agent reports received — N medium, N low findings"), and before each fix batch ("Fixing N medium findings in parallel").

## Pre-flight checks

**Context budget**: the full audit (12+ agents, 14+ skills, 12 system checks) runs close to context limits. Strict file-based handoff is mandatory — every sub-agent writes its full output to a file and returns only a compact JSON envelope. Any sub-agent that echoes findings back to context will cause compaction before the audit completes.

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
[ -d "$AUDIT_TPL" ] || AUDIT_TPL="$(find ${HOME}/.claude/plugins/cache -path "*/audit/templates" -type d 2>/dev/null | head -1)" # timeout: 5000
[ -d "$AUDIT_TPL" ] || { printf "! BREAKING: audit/templates not found — run /foundry:init first\n"; exit 1; }
```

If `.claude/` is missing, abort immediately. Missing `jq` is a warning — the audit continues with Check 4 skipped.

**Unsupported flag check** — after all supported flags extracted (`--local`, `--upgrade`, `--adversarial`, `--skip-gate`), scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--local\`, \`--upgrade\`, \`--adversarial\`, \`--skip-gate\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Step 1: Run pre-commit (if configured)

```bash
# Check whether pre-commit is installed and a config exists
if (preflight_ok pre-commit || { command -v pre-commit &>/dev/null && preflight_pass pre-commit; }) &&
[ -f .pre-commit-config.yaml ]; then
    pre-commit run --all-files # timeout: 600000
fi
```

Any files auto-corrected by pre-commit hooks (formatters, linters, whitespace fixers) are now clean before the structural audit begins. Note which files were modified — include them in the audit scope even if they were not originally targeted.

If pre-commit is not configured, skip this step silently.

## Step 2: Collect all config files

Enumerate everything in scope using built-in tools. Run all Glob calls in parallel.

**Source selection by `LOCAL_MODE`**:
- **`LOCAL_MODE=false` (default — user setup)**: `.claude/` is primary; `plugins/` is skipped. Collects installed/active config only.
- **`LOCAL_MODE=true` (--local — project source)**: `plugins/` is primary; `.claude/` is secondary for rules/hooks/settings only.

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

Merge into single flat inventory. When `LOCAL_MODE=true` and same logical name appears in both `plugins/` and `.claude/`, prefer plugin source — skip `.claude/` duplicate. Record full paths — cross-reference checks in Step 3 depend on this inventory being current. If MEMORY.md has not been updated since the last agent or skill was added or removed, run a live disk scan now rather than relying on the cached roster. Stale inventory is the primary cause of false-negative cross-reference findings.

**Scope filtering for Step 2** (applies on top of `LOCAL_MODE` source selection):
- `agents` scope — collect agents from active source (`.claude/agents/` or `plugins/*/agents/` per `LOCAL_MODE`); skip skills, rules, hooks
- `skills` scope — collect skills from active source; skip agents, rules, hooks
- `plugins` scope — always reads `plugins/*/agents/*.md` + `plugins/*/skills/*/SKILL.md` regardless of `LOCAL_MODE`; implies `LOCAL_MODE=true` for file collection
- `plugins <name>` or `<plugin-name>` (tier 2) scope — collect agents from `plugins/<name>/agents/*.md` + skills from `plugins/<name>/skills/*/SKILL.md` only; implies `LOCAL_MODE=true` for file collection
- `<agent-name>` (tier 3) scope — collect single matching agent file; when `LOCAL_MODE=false`: `.claude/agents/<name>.md`; when `LOCAL_MODE=true`: `plugins/*/agents/<name>.md` first, then `.claude/agents/<name>.md`
- `<skill-name>` (tier 3) scope — collect single matching skill file; same `LOCAL_MODE` resolution as agent above
- Multiple scope tokens — union of all resolved file sets; collect everything matched by any token
- `setup`/`plugin` (bare) scope — no agent/skill collection from plugins; see setup/plugin notes below
- Full sweep (no scope) — collect per `LOCAL_MODE` source selection above

**Setup scope**: when `$SCOPE` is `setup`, also collect `plugins/foundry/skills/init/SKILL.md` for the Step 3 foundry:curator spawn — this is the only per-file spawn in setup scope. Checks I1–I3 (from `checks-install.md`) run in Step 4 against `~/.claude/` to validate post-install user state.

**`plugins <name>` scope**: verify `plugins/<name>/` exists before proceeding — abort with `! BREAKING: plugins/<name>/ not found` if absent. Collect `plugins/<name>/skills/init/SKILL.md` for Step 3 in addition to all agents and skills in that plugin. **`plugins` (no name)**: iterate all subdirectories under `plugins/` that contain an `agents/` or `skills/` directory.

## Step 3: Per-file audit via foundry:curator

**Context management** — with 12+ agents and 14+ skills, accumulating full foundry:curator responses in context causes overflow before aggregation. Use file-based findings to keep the main context lean.

**Hard rule — no pre-reading**: Never call Read on an agent or skill file before spawning foundry:curator on it. The spawned agent does the reading. The orchestrator only reads the returned JSON envelope. Pre-reading 41 KB agent/skill files into main context before spawning defeats the entire purpose of delegation and will cause context overflow at scale.

**Batching rule**: Group files into batches of up to `BATCH_SIZE` — never spawn one agent per file at scale, as this creates N parallel agents each inflating the coordinator context with their JSON envelope. One-per-file spawning acceptable only when total files ≤ `BATCH_SIZE`.

**Grouping algorithm**: (1) sort files by plugin origin (`plugins/<name>/` prefix); (2) assign each plugin's files to batches filling each to `BATCH_SIZE` before starting next — keeps cross-ref-related files (same plugin) together; (3) remaining files (`.claude/` and mixed) fill any open batch slots. Grouping is plugin-first, not strictly ordered — files with no inter-connections can be assigned randomly to reach `BATCH_SIZE`.

**Scope-restricted runs**: for a scoped run targeting fewer than `BATCH_SIZE` files, spawn one foundry:curator for ALL files in scope. Read only the relevant template file(s) for the active scope (not all 4 template files).

Set up the run directory once before spawning any agents:

```bash
RUN_DIR=".reports/audit/$(date -u +%Y-%m-%dT%H-%M-%SZ)" # timeout: 5000
mkdir -p "$RUN_DIR"                                     # timeout: 5000
echo "Run dir: $RUN_DIR"
```

Spawn **foundry:curator** agents in batches of up to `BATCH_SIZE` files, using the grouping algorithm above — or one batch for all files if scope ≤ `BATCH_SIZE` files. The spawn prompt for each agent must:

1. Include the content from `$AUDIT_TPL/curator-prompt.md`
2. Include the disk inventory from Step 2 (agent/skill list for cross-reference validation)
3. End with:

> "Write your FULL findings (all severity levels, Confidence block) to `<RUN_DIR>/<file-basename>.md` using the Write tool — where `<file-basename>` is the filename only (e.g. `shepherd.md`, `audit-SKILL.md`). Then return to the caller ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/<file-basename>.md\",\"findings\":N,\"severity\":{\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"<filename>: N critical, N high, N medium, N low\"}`"

Replace `<RUN_DIR>` with the actual directory path and `<file-basename>` with just the filename.

**Critical context discipline**: do NOT include any other text, tool output summaries, or findings in the response body — only the JSON envelope on the final line. All content goes to the file.

> The template file is canonical for the per-file audit criteria. The disk inventory and RUN_DIR path injected here are runtime values added to each agent spawn.

After all spawns complete, you will have a list of short summaries in context. Use these to identify which files have findings. The full content is in the run directory files.

**Health monitoring** (CLAUDE.md §8): after spawning all batches, create a checkpoint:

```bash
AUDIT_CHECKPOINT="/tmp/audit-check-$(date +%s)" # timeout: 5000
touch "$AUDIT_CHECKPOINT"                       # timeout: 5000
```

Every `$MONITOR_INTERVAL` seconds, run `find $RUN_DIR -newer "$AUDIT_CHECKPOINT" -type f | wc -l` — new files = agents alive; zero new files for `$HARD_CUTOFF` seconds = stalled. Grant one `$EXTENSION` extension if the output file tail explains the delay. On timeout: read partial output from the stalled agent's file; surface it with ⏱ in the final report. Never silently omit timed-out agents.

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

**Delegation for full-sweep runs**: for full-sweep runs (no scope restriction), spawn a dedicated `foundry:curator` agent to execute Step 4 checks for each scope group, passing the relevant template file path and RUN_DIR. Use one agent per scope group: agents-checks (reads `checks-agents.md` + relevant `checks-shared.md` entries), skills-checks (reads `checks-skills.md` + relevant `checks-shared.md` entries), shared-checks (reads `checks-shared.md`), and setup-checks (reads `checks-setup.md` + `checks-install.md`). Each agent writes its findings to `<RUN_DIR>/system-checks-<scope>.md` and returns only a JSON envelope. The orchestrator does NOT read the template files itself in this case — it passes only the file path to the spawned agent.

Run the following checks. Use native tools first (Glob, Grep, Read); Bash only for pipeline operations the native tools cannot do.

**Agent roster consistency policy**: evaluate the agent system as a set of capabilities, not just files. For every overlap surfaced in checks 20 or 17, make an explicit judgment:

- **keep** when both roles own meaningfully different acceptance criteria
- **sharpen** when both roles are justified but one or both descriptions/handoffs are too fuzzy
- **merge/prune** when the roles differ mostly by tone or examples rather than by decision surface

Do not leave overlap findings as vague "potential duplication" notes. The audit must say which of the three outcomes applies and why.

**Context discipline for Step 4**: write all check findings to `$RUN_DIR/system-checks.md` (using Write tool after all checks complete), not to the main conversation context. Keep only a one-line status per check in context:

- `✓ Check N — <one-line result>` (pass)
- `⚠ Check N — N findings` (issues)

**Scope filter**: when `$SCOPE` is set, run only the checks listed for that scope; skip all others silently.

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
- Multiple scope tokens — union of check lists for all resolved scope types; de-duplicate; run each check once against the union file set
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

Spawn a **foundry:web-explorer** agent to fetch current Claude Code documentation. **File-based handoff**: foundry:web-explorer writes full findings to `$RUN_DIR/docs-freshness.md` using the Write tool. Return ONLY a compact JSON envelope: `{"status":"done","file":"$RUN_DIR/docs-freshness.md","findings":N,"deprecated":N,"new_features":N,"confidence":0.N,"summary":"N findings, N deprecated, N new features"}`

Validate the local config against fetched docs:

- **Hook validation**: every hook event name and `type` exists in documented schema; no deprecated `decision:`/`reason:` fields
- **Agent frontmatter validation**: all fields in documented schema; `model` values are recognized short-names
- **Skill frontmatter validation**: all fields in documented schema
- **Improvement opportunities**: new features passing the genuine-value filter → **Upgrade Proposals** table (max 5; classify as `config` or `capability`)

Findings: deprecated/invalid = **high**; deprecated frontmatter field = **medium**; new feature not used = **Upgrade Proposals** (not a LOW finding).

<!-- URLs fetched live by web-explorer at runtime; graceful degradation: if any 404, instruct navigation from code.claude.com homepage. -->

After all checks complete: collect all `⚠` lines, write the full details to `$RUN_DIR/system-checks.md`, and include only the summary table in the conversation context.

## Step 5: Aggregate and classify findings

**Delegate aggregation to a consolidator agent** to avoid flooding the main context with all agent findings. Spawn a **foundry:curator** consolidator agent with this prompt:

> "Read all finding files in `<RUN_DIR>/` (\*.md files from Steps 3–4, including `docs-freshness.md` if present). Apply the severity classification from `plugins/foundry/skills/audit/severity-table.md`. Antipatterns that indicate severity under-classification are also in that file. Group all findings by severity (critical, high, medium, low). Apply the one-finding-per-issue rule: when a single location has multiple distinct problems at different severities, emit one finding entry per problem. Write the aggregated severity table to `<RUN_DIR>/aggregate.md` using the Write tool. Also write `<RUN_DIR>/summary.jsonl` — one compact JSON object per line, one line per finding: `{"file":"<basename>","sev":"high|medium|low","id":"H1","one_line":"<finding description>"}`. This file is what the orchestrator will read; aggregate.md is for human review only. Return ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/aggregate.md\",\"findings\":N,\"severity\":{\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"N findings total: C critical, H high, M medium, L low\"}`"

Main context receives only that one-liner. The orchestrator MUST NOT read `aggregate.md` in full — it is 200–600 lines and would overflow context on large audits. Instead, use `$RUN_DIR/summary.jsonl` for all dispatch decisions in Steps 7 and 8.

## Step 6: Cross-validate critical findings

```bash
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/cross-validation-protocol.md" ] || { printf "⚠ WARNING: cross-validation-protocol.md not found at $_SHARED — skipping cross-validation\n"; }
```

Read and follow the cross-validation protocol from `$_SHARED/cross-validation-protocol.md` (if it exists).

**Skill-specific**: the verifier agent is always **foundry:curator**.

## Step 7: Report findings

Emit report (omit Upgrade Proposals section if none passed genuine-value filter):

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

After emitting report → fire **Follow-up gate** (Step 7 follow-up). If user picks a fix option (a–c), proceed inline to Step 8. Otherwise done.

## Step 8: Delegate fixes to subagents

> **HARD RULE — No inline fixes**: The orchestrator MUST NOT apply any fix directly using Edit or Write tools — not even single-line edits. Every fix at every severity level goes through a sub-agent. This is not optional. The overhead of spawning is always lower than the context cost of 40+ inline Edit calls accumulated across a `fix all` run.

**Fix Action Hierarchy** — before applying any fix, reason through this order:

1. **Reason** — is the finding actually correct? Is the flagged content genuinely wrong, or just in the wrong place? A misidentified finding should be discarded, not acted on.
2. **Relocate** — if the content is correct but in the wrong location, move it rather than removing it.
3. **Consolidate** — if the content is redundant with something nearby, merge into one clearer location.
4. **Minimize** — if the content is too long but otherwise valid, compress it (tighten wording, remove restatements).
5. **Remove** — only if none of the above apply. Never remove solely because something was flagged as verbose.

Apply this hierarchy to every fix action at all severity levels.

**Adversarial pre-apply validation gate** — before spawning any fix agent, each proposed fix must clear a two-agent gate:

1. Spawn **foundry:challenger** with the finding text, file path, and proposed fix action — challenge: "Is this finding real? Is the fix appropriate? Does it risk removing load-bearing behavioral content (runtime gates, behavioral invariants, execution constraints, `<notes>` checkpoints)?"
2. Spawn **foundry:curator** with the same context — validate: "Is this fix correct given the Fix Action Hierarchy? Does it preserve behavioral integrity? Could it silently remove content that is load-bearing even if it appears redundant or verbose?"
3. Issue both spawns in parallel per file. Each writes a verdict to `<RUN_DIR>/gate-<file-basename>-<finding-id>.md` and returns only: `{"verdict":"approved"|"blocked","reason":"<one-line>","file":"<path>"}`
4. If **either** returns `blocked` → skip fix agent for that finding; add to `blocked_findings` list with reason; surface in final report as `⚠ GATE-BLOCKED — needs human review: <reason>`
5. Only if **both** return `approved` → proceed to spawn fix agent

Gate applies to every finding at every severity level. Skip only for the inline-exception cases listed below (settings.json, CLAUDE.md, dead loops, model tier).

Choose the fix agent based on file type:

- **`.claude/agents/*.md` and `.claude/skills/*/SKILL.md`** → spawn **foundry:curator** — it has domain expertise in config quality and has `Write`/`Edit` tools
- **Code files** (`.py`, `.js`, `.ts`, etc.) → spawn **foundry:sw-engineer**

**Phase 4 delegation rule**: fix-phase edits that touch >3 files should be delegated to a `foundry:sw-engineer` agent rather than applied inline — pass it the list of findings and target file paths; it applies Edit calls and returns a compact status JSON.

Spawn one agent per affected file, batching all findings for that file into a single subagent prompt. Issue **all spawns in a single response** for parallelism.

Each subagent prompt template: Read the fix prompt template from `$AUDIT_TPL/fix-prompt.md` and use it, filling in `<file path>` and the list of findings.

**Preferred orchestration pattern — audit-fix sub-agent**

<!-- Canonical multi-file orchestration template — intentionally inline; NOT derived from fix-prompt.md (per-file only). Keep both in sync when changing shared audit-fix behavior. -->

After the gate fires (Step 7): if finding count > 10 or user picked "Fix all", use the audit-fix sub-agent pattern below (handles Steps 8–10 in isolation); otherwise use the inline batched pattern at the end of this step.

**Gate authority**: when the sub-agent path is used, the orchestrator Step 7 gate (below) is **skipped** — the sub-agent runs its own gate internally and is the authoritative gatekeeper. When the inline batched path is used (≤10 findings), the orchestrator Step 7 gate is authoritative and no sub-agent gate runs. Never double-gate.

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

The orchestrator (main context) then reads only the compact JSON envelope. It does NOT read fix-summary.md unless `re_audit_clean: false` or `failed > 0`.

When finding count ≤ 10 and the user picked "Fix critical+high" or "Fix critical+high+medium" (not "Fix all") from the gate, the inline batched pattern (one fix-agent per file, all spawned in parallel) is acceptable without the dedicated orchestrator sub-agent.

**Exceptions — handle inline without subagents (note in report):**

- **settings.json permission missing**: report only — structural JSON edits are risky to delegate
- **CLAUDE.md contradiction**: raise to user — do not auto-fix (CLAUDE.md takes precedence)
- **Dead loop**: flag for user review — requires human judgment on which link to break
- **Model tier mismatch**: report only — model assignments may be intentional for cost/latency trade-offs; user decides whether to adjust

After all subagents complete, collect their results and proceed to Step 10.

**Low findings** (nits): fix only when `fix all` was passed — otherwise collect in the final report for optional manual cleanup.

## Step 9: Codex cross-file check

After all Step 8 fix agents complete and before foundry:curator re-audit:

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
```

If `$CODEX_AVAILABLE` is non-empty: Read `$_SHARED/codex-prepass.md` and follow the Codex pre-pass instructions it contains, applied to the combined diff of all fixes from Step 8. Otherwise: `echo "⚠ codex plugin not available — skipping codex pass"`

Treat any findings as additional issues entering Step 10's re-audit scope. Skip if Step 8 touched only 1 file.

## Step 10: Re-audit modified files + confidence check

For every file changed in Step 8, spawn **foundry:curator** again to confirm the fix resolved the finding and no new issues were introduced. Use the same file-based approach as Step 3 — write full re-audit findings to `<RUN_DIR>/<file-basename>-reaudit.md` and return ONLY a compact JSON envelope: `{"status":"done","file":"<RUN_DIR>/<file-basename>-reaudit.md","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N,"summary":"<filename>: fix confirmed, N residual findings"}`

```bash
# Spot-check: confirm the previously broken reference no longer appears
grep -n "<broken-name>" <fixed-file>
```

**Confidence re-run**: See quality-gates.md Confidence Block requirements — apply per standard protocol. Parse each confidence score from the one-line summaries (Step 3) and re-audit summaries (Step 10). For any file where **Score < 0.7**: re-spawn foundry:curator on that file with the specific gap from the `Gaps:` field addressed in the prompt; if still < 0.7 after one retry: flag to user with ⚠ and include the gap in the final report. Recurring low-confidence gaps (same gap on same file across multiple audit runs) → candidate for adding to foundry:curator's `\<antipatterns_to_flag>` or the agent's own instructions.

**Convergence loop**: if the re-audit surfaces new fixable findings within the gate-selected severity threshold, loop back to Step 8. Repeat until:

- Zero fixable findings remain (convergence achieved) → mark fix pass complete, or
- Hard limit: **5 total fix passes** (including the initial Step 8 pass) — if still not converged, surface all remaining fixable findings to the user with a `⚠ CONVERGENCE LIMIT` warning explaining which issues resisted fixing.

Track pass count with a counter initialized to 1 at the first Step 8 execution. Increment before each re-entry into Step 8. Never suppress findings to make the counter appear clean.

The audit-fix sub-agent (when used) must also apply this loop internally — its prompt should instruct it to keep spawning fix agents and re-audit agents until clean or 5-pass limit reached.

**Cross-file re-validation**: after per-file re-audit completes for this pass, re-run the subset of system-wide checks (Step 4) that are sensitive to the files modified in this pass:

- Check 1 (inventory drift) — if any agent or skill file was modified
- Check 2 (README vs disk) — if any agent or skill was added, renamed, or deleted
- Check 14 (orphaned follow-up references) — if any skill file was modified
- Check 17 (cross-file content duplication) — if two or more files were modified
- Check 25 (implicit agent references) — if any agent or skill file was modified
- Check 27 (cross-plugin shared-file ref integrity) — if any skill file was modified

Write cross-file re-validation findings to `<RUN_DIR>/crossfile-revalidation-pass<N>.md` where N is the current pass count. Include any new findings in the convergence loop input for the next Step 8 iteration.

## Step 11: Final report

Output the complete audit summary: List each audited file by name in the `### Files Audited` section — names are drawn from the Step 2 inventory; counts alone are insufficient.

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

(Omit the fix convergence line when user picked "skip" from gate — only shown when a fix option was chosen.)

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

Adversarial review of all agents + skills in scope. Runs in parallel with or after standard per-file audit (Step 3). Surfaces issues the curator pass misses: subtle logic flaws, inconsistent claims, NOT-for gaps, scope leakage, and cross-file contradictions.

**Phase A — Challenger sweep** (parallel with Phase B):

For each file in scope (use standard Step 2 inventory; default to all agents + skills if no explicit scope), spawn **foundry:challenger** with this instruction:

> "Adversarially challenge this agent/skill. Do NOT accept claims at face value. Find: (1) unstated assumptions that will fail in edge cases, (2) NOT-for coverage gaps — tasks this agent will wrongly accept because exclusions are incomplete, (3) conflicting instructions that produce non-deterministic or contradictory behavior, (4) workflow steps that would route to the wrong sub-agent for the stated goal, (5) implicit scope that contradicts explicit NOT-for lines. Report every finding with specific evidence from the file."
> Write full findings to `<RUN_DIR>/challenger-<file-basename>.md`. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use the same `BATCH_SIZE` grouping as Step 3 — same plugin-aware batching applies.

**Phase B — Codex adversarial pass** (parallel with Phase A):

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_SHARED" ] && _SHARED="plugins/foundry/skills/_shared"
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
```

If `[ -n "$CODEX_AVAILABLE" ]`: read `$_SHARED/codex-prepass.md` and run Codex pass on all in-scope files. Focus Codex on: cross-file inconsistencies, circular dispatch chains, agent description ambiguities that cause routing failures, and workflow steps that assume capabilities the declared tools don't provide. Else: `echo "⚠ codex plugin not available — skipping codex adversarial pass"`.

Codex writes per-file findings to `<RUN_DIR>/codex-adversarial-<file-basename>.md`. Return compact JSON envelope per file.

**Phase C — Aggregate and deduplicate**:

Spawn **foundry:curator** consolidator to merge Phase A + Phase B findings. Cross-reference against standard audit `summary.jsonl` if present (same RUN_DIR). Surface only findings NOT already reported in standard audit — adversarial mode adds signal, not noise.

Write deduplicated findings to `<RUN_DIR>/adversarial-aggregate.md` and `<RUN_DIR>/adversarial-summary.jsonl` (same JSONL format as Step 5). Return: `{"status":"done","new_findings":N,"overlapping":N,"severity":{"critical":N,"high":N,"medium":N,"low":N}}`

**Report format**:

```markdown
## Adversarial Audit — <date> — <scope>

| File | Challenger | Codex | New Findings | Top Issue |
|------|-----------|-------|--------------|-----------|
| agents/curator.md | 3 | 1 | 2 | NOT-for gap: accepts task X |
```

Adversarial findings feed into the standard fix pipeline (Steps 7–10) when user picks a fix level from the follow-up gate.

**Adversarial-only runs** (no standard audit): skip Steps 3–6; run only Phases A–C above; report adversarial findings only.

**Flag aliases**: `--adversarial` and `--challenge` are identical — either triggers this mode.

## Follow-up gate

**Always fires** unless `--skip-gate` was passed (programmatic callers). Call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into the tool call arguments.

When user picks fix option (a–c): run Steps 8–10 inline within this invocation (state already on disk in `summary.jsonl`); no recursive `/audit` call needed.

- question: "What next?" (include finding counts in question, e.g. "2 critical, 4 high, 3 medium, 1 low. What next?")
- (a) label: `Fix critical + high` — description: auto-fix critical and high findings
- (b) label: `Fix critical + high + medium` — description: auto-fix critical, high, and medium findings (recommended)
- (c) label: `Fix all` — description: auto-fix all findings including low
- (d) label: `/audit --upgrade` — description: fetch latest Claude Code docs and apply improvements
- (e) label: `/audit --adversarial` — description: adversarial review with foundry:challenger + Codex
- (f) label: `/foundry:init` — description: sync verified config to `~/.claude/`
- (g) label: `skip` — description: no action

After completing `--upgrade` or `--adversarial` mode: also fire this gate (omit options (d) or (e) respectively — no point repeating the mode just run).

</workflow>

<notes>

- **`!` Breaking findings**: when a skill or agent is completely non-functional (check #7, broken cross-refs, invalid hook events), prefix the finding with `!` and state the impact + fix in one place — don't bury it as a table row. These surface as **`! BREAKING`** in bash output and as prominent callouts in the final report.
- **Terminal color conventions** (used in Step 4 bash output):
  - `RED` (`\033[1;31m`) — breaking/critical: `! BREAKING`, `ERROR`
  - `YELLOW` (`\033[1;33m`) — warnings/medium: `⚠ MISSING`, `⚠ ORPHANED`, `⚠ DIFFERS`
  - `GREEN` (`\033[0;32m`) — pass status: `✓ OK`, `✓ IDENTICAL`
  - `CYAN` (`\033[0;36m`) — source agent name or fix hint
- **settings.json is hands-off**: missing permissions are always reported, never auto-edited — structural JSON edits risk breaking Claude Code's config loading
- **Dead loops need human judgment**: a cycle in follow-up chains might be intentional (e.g., refactor → review → fix → refactor) — flag and explain, don't auto-remove
- **Convergence loop replaces cycle cap**: the fix loop runs until zero fixable findings remain or the 5-pass hard limit is hit — see Step 10 for the full protocol
- **Relationship to curator**: `foundry:curator` is a single-file reactive audit; `/audit` is the system-wide sweep that runs foundry:curator at scale and adds cross-file checks
- **Paths must be portable**: `.claude/` for project-relative paths, `~/` or `$HOME/` for home paths — never a literal `/Users/<name>/` or `/home/<name>/` path (shown here as anti-examples only); this rule applies to ALL config files including `settings.json`
- **Bash error logging**: if a bash block in Pre-flight checks or Step 4 fails unexpectedly, append a JSONL line to `.claude/logs/audit-errors.jsonl` (`{"ts":"<ISO>","check":"<N>","error":"<message>"}`) for post-mortem — do not swallow errors silently.
- **Parallel execution rule**: After Step 2 (file collection), launch Steps 3 and 4 in the same response — all foundry:curator agent spawns AND all system-wide bash checks must be issued together. Do NOT run Step 3 first and Step 4 second. Aggregation (Step 5) waits for both to complete. The docs-freshness web-explorer (within Step 4) also launches in that same parallel batch.
- **Token cost**: Step 3 (foundry:curator spawns) is the most expensive part of the audit. For a quick structural scan where you mainly need cross-reference and inventory validation, the system-wide checks in Step 4 are often sufficient on their own. Consider running `/audit agents` or `/audit skills` to scope the sweep, or skip Step 3 entirely for a fast pass when you already trust per-file quality.
- **Skill-creator complement**: For testing whether skill trigger descriptions fire correctly (trigger accuracy, A/B description testing), see the official skill-creator utility from Anthropic. `/audit` checks structural quality; `skill-creator` validates that the right skill is selected by Claude Code's dispatcher when the user types a command.
- Follow-up chains:
  - Audit clean → pick `/foundry:init` from gate to propagate verified config to `~/.claude/`
  - Audit found structural issues → review flagged files manually before syncing; pick fix level from gate
  - Audit found many low items → pick "Fix all" from gate, or run `/develop:refactor` (requires `develop` plugin) for targeted cleanup
  - After fixing agent instructions (from audit gate) → `/calibrate <agent>` to verify fix improved recall and confidence calibration
  - Audit Check 20 found description overlap → `/calibrate routing` to verify behavioral routing impact; update descriptions for confused pairs based on the routing report
  - Audit surfaced upgrade proposals → pick `/audit --upgrade` from gate to apply with correctness checks and calibrate A/B evidence for capability changes
  - `/audit --upgrade` reverted a capability change → run `/calibrate <agent> --full` for deeper signal (N=10 vs N=3 used in upgrade mode)
  - Audit Check 22 found unregistered calibratable mode → update `calibrate/modes/skills.md` domain table and run `/calibrate skills` to verify the new target works
  - Audit Check 22 found stale domain table entry → remove it from `calibrate/modes/skills.md`

</notes>
