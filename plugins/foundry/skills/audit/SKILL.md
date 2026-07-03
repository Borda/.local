---
name: audit
description: "Full-sweep quality audit of .claude/ config — cross-references, permissions, inventory drift, model tiers, docs freshness. Scope tokens select what to audit; --upgrade applies docs-sourced improvements; --adversarial runs foundry:challenger + Codex adversarial review; --efficiency sweeps model tiers, token bloat, spawn patterns, boilerplate duplication, and bin/ extraction candidates (extraction performed separately via /distill executables). Fix level chosen via always-fire follow-up gate after report."
argument-hint: "[<scope>...] [--local] [--upgrade | --adversarial | --efficiency] [--skip-gate] [--keep \"<items>\"]"
disable-model-invocation: true
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, WebFetch, Skill, TaskCreate, TaskUpdate, TaskList, AskUserQuestion
effort: high
---

<objective>

Full-sweep audit of `.claude/` config + all `plugins/*/` files: agents, skills, rules, settings.json, hooks. Spawns `foundry:curator` per-file, aggregates system-wide for cross-file issues — infinite loops, inventory drift, missing permissions, interop breaks. Reports findings; fix level chosen from follow-up gate.

</objective>

<inputs>

- **$ARGUMENTS**: optional — parse `--flags` first, then resolve remaining tokens as scope

  **Flags** (order independent, any combination with scope):
  - `--local` — audit source tree (`plugins/*/`) not user setup (`.claude/` + installed cache); plugin-dev workflows where local edits not yet installed; sets `LOCAL_MODE=true`
  - `--upgrade` — fetch latest Claude Code docs, filter new features by genuine value, apply: **config** changes (apply + correctness check), **capability** changes (calibrate before → apply → calibrate after → accept if Δrecall ≥ 0 and ΔF1 ≥ 0). Skip to **Mode: upgrade**. Mutually exclusive with `--adversarial` and `--efficiency` — error if combined with either.
  - `--adversarial` (alias: `--challenge`) — adversarial review of all agents + skills in scope using `foundry:challenger` (Phase A) + Codex adversarial pass (Phase B); surfaces issues beyond standard per-file audit; see **Mode: adversarial**. Mutually exclusive with `--upgrade` only; combinable with `--efficiency`.
  - `--efficiency` — cost and efficiency sweep: model tier validation, token bloat detection, unbounded spawn patterns, cross-file boilerplate duplication, missing model declarations, dead model specs, bin/ extraction candidates (Check 33). Generates prioritized cost-reduction plan with estimated savings. Detection only — run `/distill executables` to act on extraction candidates. Skip to **Mode: efficiency**. Mutually exclusive with `--upgrade` only; combinable with `--adversarial`.
  - `--skip-gate` — suppress follow-up gate (for automation pipelines)

  **Legacy positional tokens** (`fix`, `upgrade`, `adversarial`, `challenge`, `ab`, `apply`, `fast`, `full`) — **hard error**: print migration hint and stop. Example: "`fix medium` removed — run `/audit` and pick fix level from gate, or pass `--upgrade` / `--adversarial` as flags."

  **Scope tokens** (positional, space-separated — resolve each token before Step 2):
  - No scope: full sweep — sources per `--local`: **without `--local`** covers `.claude/agents/`, `.claude/skills/`, `.claude/rules/`, hooks, settings, `~/.claude/plugins/cache/` installed; **with `--local`** covers `plugins/*/agents/`, `plugins/*/skills/` + `.claude/` secondary
  - `agents` — restrict sweep to agent files only
  - `skills` — restrict sweep to skill files only
  - `rules` — restrict sweep to rule files only
  - `communication` — restrict sweep to communication governance files: `rules/communication.md`, `rules/quality-gates.md`, `TEAM_PROTOCOL.md`, `skills/_shared/file-handoff-protocol.md`
  - `setup` — restrict to system-config files: `settings.json`, `permissions-guide.md`, hooks, `MEMORY.md`, `README.md`, plugin integration, post-install user state (Checks 1–11, 30, I1, I2, I3); Step 3: `setup` SKILL.md only (one foundry:curator spawn); Checks I1–I3 read `~/.claude/` not `.claude/`
  - `plugin` — plugin integration only: codex plugin (Check 7), foundry plugin + init validation (Check 8, including 8g); Step 3: `setup` SKILL.md only (one foundry:curator spawn)
  - `plugins` — full audit of all plugins: per-file audit of every `plugins/*/agents/*.md` and `plugins/*/skills/*/SKILL.md` + integration checks (7, 8) per plugin
  - `plugins <name>` — same as `plugins` scoped to one plugin: `plugins/<name>/agents/*.md` + `plugins/<name>/skills/*/SKILL.md` + integration checks; `<name>` must match dir under `plugins/` (e.g. `plugins foundry`, `plugins oss`, `plugins research`)
  - `<plugin-name>` — **tier 2 shorthand**: bare plugin dir name (e.g. `oss`, `foundry`, `research`, `develop`, `codemap`) auto-resolved when token matches dir under `plugins/`; equivalent to `plugins <name>`; no `plugins` prefix needed
  - `<agent-name>` — **tier 3**: name matches `plugins/*/agents/<name>.md` or `.claude/agents/<name>.md`; runs agent checks only (Checks 14a, 14b, 15, 19, 20, 17, 12, 13, 25, 22, 26, 29); one file in Step 3
  - `<skill-name>` — **tier 3**: name matches `plugins/*/skills/<name>/SKILL.md` or `.claude/skills/<name>/SKILL.md`; runs skill checks only (Checks 14a, 14b, 15, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29); one file in Step 3
  - Multiple scope tokens — space-separated, any combo; scope = union of resolved file sets: `agents skills`, `oss research`, `shepherd curator`, `review resolve`; check list = union (de-duplicated)

  **Scope token resolution** (each remaining token after flag-strip, resolved before Step 2): (1) reserved keywords (`agents`, `skills`, `rules`, `communication`, `setup`, `plugin`, `plugins`) → use as-is; (2) matches dir under `plugins/<token>/` → tier 2; (3) matches agent file in `plugins/*/agents/<token>.md` or `.claude/agents/<token>.md` → tier 3 agent; (4) matches skill dir `plugins/*/skills/<token>/` or `.claude/skills/<token>/` → tier 3 skill; (5) no match → error and stop

  **Valid combinations**: scope tokens + flags mix freely: `foundry --local`, `foundry --adversarial`, `agents skills --local`, `oss research --adversarial`, `foundry --efficiency`, `plugins --efficiency`, `foundry --adversarial --efficiency`, `plugins --local --adversarial --efficiency`. `--upgrade` mutually exclusive with `--adversarial` and `--efficiency` — error if combined with either. `--local` compatible with all. When `--adversarial` and `--efficiency` both present: run adversarial Phases A–C then efficiency Phases A–C sequentially; merge findings; single follow-up gate.

</inputs>

<constants>

BATCH_SIZE_MIN=5       # minimum files per batch; ensures curator gets sufficient context per spawn
MAX_BATCHES=10         # total batch cap; EFFECTIVE_BATCH = max(BATCH_SIZE_MIN, ceil(total / MAX_BATCHES))
ADVERSARIAL_BATCH_SIZE=2  # adversarial phases (A, A-prime) use smaller batches for deeper per-file attention; override with --batch-size N

</constants>

<compaction>

Key boundary 1: after Steps 3+4 fan-out (curator spawns + system-wide checks complete), before Step 5 aggregate.
Key boundary 2: after Step 5 aggregate (aggregate.md + summary.jsonl written), before Step 7 report.
Preserve at boundary 1: RUN_DIR, per-batch finding file paths, static-findings.jsonl path.
Preserve at boundary 2: RUN_DIR, aggregate.md path, summary.jsonl path, finding counts.

</compaction>

<workflow>

**Task hygiene**:
```bash
# loads: compaction-contract.md
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
```
Read `$_FS/task-hygiene.md` — follow task hygiene protocol.

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
KEEP_ITEMS=""
if [[ "$ARGUMENTS" =~ --keep[[:space:]]\"([^\"]+)\" ]]; then
    KEEP_ITEMS="${BASH_REMATCH[1]}"
fi
ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--keep "[^"]*"//g')
rm -f .claude/state/skill-contract.md  # clear stale contract (compaction-contract.md §Lifecycle)  # timeout: 5000
LOCAL_MODE=false;       [[ " $ARGUMENTS " == *" --local "* ]]       && LOCAL_MODE=true
ADVERSARIAL_MODE=false; [[ " $ARGUMENTS " == *" --adversarial "* ]] && ADVERSARIAL_MODE=true; [[ " $ARGUMENTS " == *" --challenge "* ]] && ADVERSARIAL_MODE=true
EFFICIENCY_MODE=false;  [[ " $ARGUMENTS " == *" --efficiency "* ]]  && EFFICIENCY_MODE=true
UPGRADE_MODE=false;     [[ " $ARGUMENTS " == *" --upgrade "* ]]     && UPGRADE_MODE=true
SKIP_GATE=false;        [[ " $ARGUMENTS " == *" --skip-gate "* ]]   && SKIP_GATE=true
ARGUMENTS=" $ARGUMENTS "
ARGUMENTS="${ARGUMENTS// --local / }"; ARGUMENTS="${ARGUMENTS// --adversarial / }"
ARGUMENTS="${ARGUMENTS// --efficiency / }"; ARGUMENTS="${ARGUMENTS// --upgrade / }"
ARGUMENTS="${ARGUMENTS// --skip-gate / }"; ARGUMENTS="${ARGUMENTS// --challenge / }"
ARGUMENTS=$(echo "$ARGUMENTS" | tr -s ' '); ARGUMENTS="${ARGUMENTS# }"; ARGUMENTS="${ARGUMENTS% }"

if [ "$UPGRADE_MODE" = "true" ] && { [ "$ADVERSARIAL_MODE" = "true" ] || [ "$EFFICIENCY_MODE" = "true" ]; }; then
    printf "! --upgrade is mutually exclusive with --adversarial and --efficiency\n"
    exit 1
fi

# preflight helpers defined inline — fresh shell per Bash() call; sourced functions unavailable
preflight_ok()   { local f=".claude/state/preflight/$1.ok"; [ -f "$f" ] && [ $(($(date +%s) - $(cat "$f"))) -lt 14400 ]; }
preflight_pass() { mkdir -p .claude/state/preflight; date +%s >".claude/state/preflight/$1.ok"; }

if [ ! -d ".claude" ]; then
    printf "! BREAKING: .claude/ directory not found — nothing to audit\n"
    exit 1
fi

# jq — Check 4 depends on it
if preflight_ok jq; then
    JQ_AVAILABLE=true
elif command -v jq &>/dev/null; then # timeout: 5000
    preflight_pass jq
    JQ_AVAILABLE=true
else
    printf "⚠ MISSING: jq not found — Check 4 (permissions-guide drift) will be skipped\n"
    JQ_AVAILABLE=false
fi

if ! preflight_ok git && ! command -v git &>/dev/null; then # timeout: 5000
    printf "⚠ MISSING: git not found — path portability check may miss repo-root references\n"
else
    preflight_ok git || preflight_pass git
fi

# node — Check 10 (RTK prefix parsing) + upgrade hook syntax check depend on it
if preflight_ok node; then
    NODE_AVAILABLE=true
elif command -v node &>/dev/null; then # timeout: 5000
    preflight_pass node
    NODE_AVAILABLE=true
else
    printf "⚠ MISSING: node not found — Check 10 (RTK hook parsing) and upgrade hook syntax check will be skipped\n"
    NODE_AVAILABLE=false
fi

AUDIT_TPL=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_skill_subdir.py" audit templates $( [ "$LOCAL_MODE" = true ] && echo "--local" )) || { printf "! BREAKING: audit/templates not found — run /foundry:setup first\n"; exit 1; }  # timeout: 5000

# Persist LOCAL_MODE + AUDIT_TPL — fresh-shell state loss
# Re-derive at each Step start — see ADV-M1
mkdir -p "${TMPDIR:-/tmp}/audit-state"
echo "$LOCAL_MODE" > "${TMPDIR:-/tmp}/audit-state/local-mode"
echo "$AUDIT_TPL"  > "${TMPDIR:-/tmp}/audit-state/audit-tpl"
echo "$KEEP_ITEMS" > "${TMPDIR:-/tmp}/audit-state/keep-items"
```

If `.claude/` missing, abort immediately. Missing `jq` is warning — audit continues with Check 4 skipped.

**State re-derivation across Bash blocks** — Claude Code spawns a fresh shell per Bash() call; variables set in pre-flight are LOST in Steps 2–11. Every Bash block in subsequent steps that uses `LOCAL_MODE` or `AUDIT_TPL` must re-read them from the persisted state files:

```bash
LOCAL_MODE=$(cat "${TMPDIR:-/tmp}/audit-state/local-mode" 2>/dev/null || echo false)
AUDIT_TPL=$(cat "${TMPDIR:-/tmp}/audit-state/audit-tpl" 2>/dev/null || python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_skill_subdir.py" audit templates $( [ "$LOCAL_MODE" = true ] && echo "--local" ))
```

Place these two lines at the top of every Bash block in Steps 2–11 that references either variable.

**Unsupported flag check** — after extracting supported flags (`--local`, `--upgrade`, `--adversarial`, `--efficiency`, `--skip-gate`, `--keep`), scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--local\`, \`--upgrade\`, \`--adversarial\`, \`--efficiency\`, \`--skip-gate\`, \`--keep\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Step 1: Run pre-commit (if configured)

```bash
preflight_ok()   { local f=".claude/state/preflight/$1.ok"; [ -f "$f" ] && [ $(($(date +%s) - $(cat "$f"))) -lt 14400 ]; }
preflight_pass() { mkdir -p .claude/state/preflight; date +%s >".claude/state/preflight/$1.ok"; }

if (preflight_ok pre-commit || { command -v pre-commit &>/dev/null && preflight_pass pre-commit; }) &&
[ -f .pre-commit-config.yaml ]; then
    timeout 600 pre-commit run --all-files # timeout: 600000
fi
```

Files auto-corrected by pre-commit hooks are clean before structural audit. Note modified files — include in audit scope even if not originally targeted.

If pre-commit not configured, skip silently.

## Step 1b: Layer-1 deterministic static pass

Run the zero-LLM checker driver — the same deterministic checkers pre-commit enforces, aggregated into one reproducible findings file. These results are **authoritative** for their check classes: Steps 3–4 (LLM curator + judgment checks) must NOT re-derive them in prose — treat them as already-verified and spend model tokens only on judgment.

```bash
LOCAL_MODE=$(cat "${TMPDIR:-/tmp}/audit-state/local-mode" 2>/dev/null || echo false)
STATIC_SCOPE=$( [ "$LOCAL_MODE" = true ] && echo plugins || echo .claude )
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/audit_static.py" --scan-dir "$STATIC_SCOPE" \
    --jsonl "${TMPDIR:-/tmp}/audit-state/static-findings.jsonl"  # timeout: 120000
```

Covered deterministically by the driver (map to legacy check IDs — do NOT re-run these as prose): **14a** tag symmetry · **14b** fence symmetry · **14c** README drift · **14d** mode-dispatch integrity · **14e** cross-plugin shared-file drift · **41** bash-variable persistence · **42** spawn-prompt `$VAR` · **32d** orphaned bin/ scripts · **R3** bin/computed-path reference integrity. The whole-repo checks (orphaned-bin, routing-links, shared-drift) always scope to `plugins/` regardless of `STATIC_SCOPE`; the driver is most complete in `--local` mode. Step 5 merges `static-findings.jsonl` into the aggregate.

> **Layer-1 recall is benchmarked** — `tests/test_audit_static.py` plants a known defect per scope-aware class and asserts the driver catches every one (100% mechanical recall), so this pass is trusted, not assumed.

## Step 1c: Layer-3 recurrence signal (attention weighting)

Read a compact git-churn signal so audit attention follows *measured* churn — the files and change-classes that keep being re-fixed are where the next defect most likely hides. Report the dominant recurring-fix class, not only point findings.

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/audit_churn.py" --limit 300 --path plugins \
    > "${TMPDIR:-/tmp}/audit-state/churn-signal.json" 2>/dev/null  # timeout: 20000
```

Use `churn-signal.json` (`commit_types`, `top_churn`, `recurring_hint`) to: (1) prioritize per-file audits toward the most-churned files first in Step 3 batching; (2) add a **Recurring fix class** line to the Step 7 report naming the dominant theme (e.g. "version-bump churn — candidate for automation"). Zero-LLM, best-effort; skip silently if git is unavailable.

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

**Setup scope**: when `$SCOPE` is `setup`, also collect `${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/skills/setup/SKILL.md` for Step 3 foundry:curator spawn — only per-file spawn in setup scope. Checks I1–I3 (from `checks-install.md`) run in Step 4 against `~/.claude/` to validate post-install user state.

**`plugins <name>` scope**: verify `plugins/<name>/` exists — abort `! BREAKING: plugins/<name>/ not found` if absent. Collect `plugins/<name>/skills/setup/SKILL.md` for Step 3 plus all agents/skills in that plugin. **`plugins` (no name)**: iterate all subdirs under `plugins/` with `agents/` or `skills/` dir.

## Step 3: Per-file audit via foundry:curator

**Context management** — 12+ agents and 14+ skills: accumulating full foundry:curator responses in context causes overflow before aggregation. Use file-based findings to keep main context lean.

**Hard rule — no pre-reading**: Never call Read on agent/skill file before spawning foundry:curator. Spawned agent does the reading. Orchestrator reads only returned JSON envelope. Pre-reading 41 KB files into main context = defeats delegation + causes context overflow at scale.

**Batching rule**: Always apply the grouping algorithm. Compute `EFFECTIVE_BATCH = max(BATCH_SIZE_MIN, ceil(total_files / MAX_BATCHES))` before grouping — caps total batches at `MAX_BATCHES` while guaranteeing `BATCH_SIZE_MIN` files per batch for adequate curator context. Group files into batches of up to `EFFECTIVE_BATCH`. Never spawn one agent per file. Total files ≤ `EFFECTIVE_BATCH` → one batch containing all files.

**Grouping algorithm**: (1) sort by plugin origin (`plugins/<name>/` prefix); (2) assign each plugin's files to batches, fill to `BATCH_SIZE` before next — keeps same-plugin files together; (3) remaining files (`.claude/` and mixed) fill open slots. Grouping plugin-first, not strictly ordered — unconnected files assigned randomly to reach `BATCH_SIZE`.

**Layer-2 — judgment by domain, not by file (plugin scope)**: when the scope is `plugins`, `plugins <name>`, or a tier-2 plugin name, override the batch cap and group **all of a plugin's files into ONE holistic batch** (one `foundry:curator` per plugin), even if that exceeds `EFFECTIVE_BATCH`. Whole-plugin context is what lets the curator catch cross-file breaks that per-file batching structurally misses — tool-grant mismatches (agent frontmatter vs skill dispatch), inter-skill contract splits (a constant clamped differently in two files), dead dispatch paths, and version/description drift within the plugin. The curator prompt for a holistic batch must say: "You have this plugin's ENTIRE file set — review it as one system: check that every `Agent(subagent_type=...)` dispatch targets an agent whose frontmatter grants the needed tools, that shared constants/contracts agree across files, and that no skill references a removed mode/file." The mechanical checks are already done in Step 1b — spend this holistic pass on cross-file judgment only. (Very large plugins may still split, but keep agents+their dispatching skills in the same batch.)

**Scope-restricted runs**: fewer than `EFFECTIVE_BATCH` files → one batch containing ALL files in scope (single foundry:curator spawn). Read only relevant template file(s) for active scope, not all 4.

Set up the run directory once before spawning any agents:

```bash
LOCAL_MODE=$(cat "${TMPDIR:-/tmp}/audit-state/local-mode" 2>/dev/null || echo false)
AUDIT_TPL=$(cat "${TMPDIR:-/tmp}/audit-state/audit-tpl" 2>/dev/null || python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_skill_subdir.py" audit templates $( [ "$LOCAL_MODE" = true ] && echo "--local" ))

RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/make_run_dir.py" .reports/audit)  # timeout: 5000
[ -z "$RUN_DIR" ] && { printf "! BREAKING: make_run_dir.py returned empty path — check Python availability and write permission on .reports/\n"; exit 1; }
echo "Run dir: $RUN_DIR"
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/audit-state/run-dir"
```

Spawn **foundry:curator** agents in batches of up to `BATCH_SIZE` (grouping algorithm above) — or one batch if scope ≤ `BATCH_SIZE`. Each spawn prompt must:

1. Include the content from `$AUDIT_TPL/curator-prompt.md`
2. Include the disk inventory from Step 2 (agent/skill list for cross-reference validation)
3. End with:

> "Write your FULL findings (all severity levels) to `<RUN_DIR>/<file-slug>.md` using the Write tool — where `<file-slug>` is a unique identifier combining plugin prefix and filename (e.g. `foundry-shepherd.md`, `oss-analyse-SKILL.md`, `develop-fix-SKILL.md`) to avoid collisions between cross-plugin files sharing the same basename. End your full findings file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Then return to the caller ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/<file-slug>.md\",\"findings\":N,\"severity\":{\"security\":N,\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"<filename>: N critical, N high, N medium, N low\"}`"

Replace `<RUN_DIR>` with actual path, `<file-slug>` with plugin-prefixed unique slug (e.g. `foundry-shepherd`, `oss-analyse-SKILL`, `develop-fix-SKILL`). Slug chars: `[a-zA-Z0-9-]` only — no slashes, spaces, or dots.

**Critical context discipline**: response body = JSON envelope on final line only. No other text, output summaries, or findings. All content to file.

> Template file = canonical per-file audit criteria. Disk inventory and RUN_DIR path = runtime values injected per spawn.

After spawns complete: short summaries in context; use to identify files with findings. Full content in run directory files.

**Health monitoring** (CLAUDE.md §6): apply the honest protocol in `$_FS/agent-spawn-protocol.md` — these curator batches return on completion; after each returns, read its `$RUN_DIR` output file. For a background probe, a single `find $RUN_DIR -newer "$SENTINEL" -type f | wc -l` per turn (`health_sentinel.py` §8b) — no sleep loop. On empty/missing output: mark `timed_out`, surface with ⏱ in final report. Never omit timed-out agents.

## Step 4: System-wide checks

> **Full implementation instructions** are split across 5 scope files in `$AUDIT_TPL/` (resolved in Pre-flight). Read only the file(s) for the active scope at the start of this step — do not read all 5 files unless running a full sweep.
>
> | Scope | File(s) to read |
> | --- | --- |
> | `setup` | `checks-setup.md` (Checks 1–11, 39) + `checks-install.md` (I1–I3) + `checks-security.md` (Check 37) |
> | `plugin` | `checks-setup.md` (Checks 7, 8 only) |
> | `plugins` | `checks-setup.md` (7, 8) + `checks-agents.md` + `checks-skills.md` + `checks-shared.md` (14a, 14b, 15, 17, 12, 13, 25, 26, 29, 41) + checks 32, 32d, 33, 38, 40 + `checks-install.md` (R1–R5 — LOCAL_MODE) + `checks-security.md` (35, 36, 37) |
> | `plugins <name>` | same as `plugins` — scoped to one plugin directory |
> | `agents` | `checks-agents.md` (19, 20) + `checks-shared.md` (run only: 14a, 14b, 15, 17, 12, 13, 25, 26, 29, 41) + `checks-skills.md` (22, 40 only) + `checks-security.md` (35, 36) |
> | `skills` | `checks-skills.md` (21–24, 27, 28, 30, 31, 32, 33, 38, 40) + `checks-shared.md` (run only: 14a, 14b, 15, 17, 12, 13, 25, 26, 29, 41) + `checks-security.md` (35–37) |
> | `rules` | `checks-shared.md` (run only: 18, 12, 13, 29, 41) + `checks-skills.md` (32c only) |
> | `communication` | `checks-shared.md` (run only: 15, 16, 12, 13, 29) |
> | No scope (full) | all 5 files |

**Delegation for full-sweep runs**: for full-sweep (no scope), spawn dedicated `foundry:curator` per scope group, passing template file path and RUN_DIR: agents-checks (reads `checks-agents.md` + relevant `checks-shared.md`), skills-checks (reads `checks-skills.md` + relevant `checks-shared.md`), shared-checks (reads `checks-shared.md`), setup-checks (reads `checks-setup.md` + `checks-install.md`), security-checks (reads `checks-security.md` — security findings land in separate Security Findings section of report). Each writes findings to `<RUN_DIR>/system-checks-<scope>.md`, returns only JSON envelope. Orchestrator does NOT read template files — passes path to spawned agent only.

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

- `agents` — Checks 14a, 14b, 15, 16, 19, 20, 17, 12, 13, 25, 22, 26, 29, 35, 36, 40, 41 (files: `.claude/agents/*.md` + `plugins/*/agents/*.md`)
- `skills` — Checks 14a, 14b, 15, 16, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 35, 36, 37, 38, 40, 41 (files: `.claude/skills/*/SKILL.md` + `plugins/*/skills/*/SKILL.md`)
- `rules` — Checks 18, 12, 13, 29, 32c, 41 (32d skipped — no plugin bin/ in rules scope)
- `communication` — Checks 15, 16, 12, 13, 29
- `setup` — Checks 1, 2, 3, 4, 5, 9, 10, 11, 7, 6, 8, 30, 37, 39, I1, I2, I3 (Step 3: one foundry:curator spawn for `setup` SKILL.md only; I1–I3 read `~/.claude/`)
- `plugin` — Checks 7, 8 (Step 3: one foundry:curator spawn for `${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/skills/setup/SKILL.md` only)
- `plugins` — Checks 7, 8, 14, 14b, 15, 16, 19, 20, 17, 12, 13, 25, 22, 26, 21, 23, 24, 27, 28, 29, 30, 31, 32, 32d, 33, 35, 36, 37, 38, 39, 40, 41, R1, R2, R3, R4, R5 (files: all `plugins/*/agents/*.md` + `plugins/*/skills/*/SKILL.md`; Step 3: foundry:curator batches for all plugin agents + skills + each plugin's setup SKILL.md; 32d, R1–R5 always LOCAL_MODE — skip in non-local)
- `plugins <name>` or `<plugin-name>` (tier 2) — same check list as `plugins`, scoped to `plugins/<name>/` only
- `<agent-name>` (tier 3) — Checks 14, 14b, 15, 16, 19, 20, 17, 12, 13, 25, 22, 26, 29, 35, 36, 40, 41 (one file only; no cross-plugin Checks 7/8)
- `<skill-name>` (tier 3) — Checks 14, 14b, 15, 16, 21, 17, 12, 23, 22, 13, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33a, 35, 36, 37, 38, 40, 41 (one file only)
- Multiple scope tokens — union of check lists for all resolved scope types; de-duplicate; run each check once against union file set
- No scope argument — run all checks

### Check summary

<!-- loads: checks-index.md -->
<!-- loads: checks-security.md -->
Read `$AUDIT_TPL/checks-index.md` for the full check index (Checks 1–41, I1–I3, R1–R5 with severity, scope, notes). Security checks (35–37) are implemented in `$AUDIT_TPL/checks-security.md`.

### Claude Code docs freshness (within Step 4)

```text
Agent(subagent_type="foundry:web-explorer", prompt="Fetch current Claude Code docs (https://code.claude.com/docs/en/). If that URL returns 404 or redirects, navigate from https://code.claude.com homepage to find the documentation section. If docs are entirely unavailable, return {\"status\":\"unavailable\",\"findings\":0}. Check: hook event names + type field vs documented schema (deprecated decision:/reason: fields); agent frontmatter fields + model values; skill frontmatter fields; new features passing genuine-value filter → Upgrade Proposals table (max 5, classify config or capability). Write full findings to $RUN_DIR/docs-freshness.md using the Write tool. End your full findings file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Return ONLY: {\"status\":\"done\",\"file\":\"$RUN_DIR/docs-freshness.md\",\"findings\":N,\"deprecated\":N,\"new_features\":N,\"confidence\":0.N,\"summary\":\"N findings, N deprecated, N new features\"}")
```

<!-- URLs fetched live by web-explorer at runtime; graceful degradation: if any 404, instruct navigation from code.claude.com homepage. -->

Severity: deprecated/invalid = **high**; deprecated frontmatter field = **medium**; new feature not used = **Upgrade Proposals** (not LOW).

After checks complete: collect `⚠` lines, write full details to `$RUN_DIR/system-checks.md`, include only summary table in context.

```bash
_RUN_DIR=$(cat "${TMPDIR:-/tmp}/audit-state/run-dir" 2>/dev/null || echo "")
_KEEP=$(cat "${TMPDIR:-/tmp}/audit-state/keep-items" 2>/dev/null || echo "")
_PRESERVE="run-dir=$_RUN_DIR, static-findings=${TMPDIR:-/tmp}/audit-state/static-findings.jsonl, finding-files=$_RUN_DIR/*.md"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: foundry:audit · phase: aggregate (after parallel curator+system-checks fan-out)"
    echo "- run-dir: $_RUN_DIR"
    echo "- preserve: $_PRESERVE"
    echo "- next: consolidate findings → aggregate.md + summary.jsonl → Step 7 report"
} > .claude/state/skill-contract.md
```

## Step 5: Aggregate and classify findings

**Delegate aggregation** to consolidator agent to avoid flooding main context. Spawn **foundry:curator** consolidator:

> "Read all finding files in `<RUN_DIR>/` (\*.md files from Steps 3–4, including `docs-freshness.md` if present) AND the deterministic Layer-1 results at `${TMPDIR:-/tmp}/audit-state/static-findings.jsonl` (Step 1b — one JSON object per check; each `\"status\":\"fail\"` object's `lines` array is a set of already-verified mechanical findings, severity per the check's known level: fence/mode-dispatch=high, tag/README-drift/bash-persistence/spawn-vars/shared-drift=medium, orphaned-bin/routing=medium). Apply the severity classification from `$AUDIT_TPL/../severity-table.md`. Antipatterns that indicate severity under-classification are also in that file. Group all findings by severity (critical, high, medium, low). Apply the one-finding-per-issue rule: when a single location has multiple distinct problems at different severities, emit one finding entry per problem. Write the aggregated severity table to `<RUN_DIR>/aggregate.md` using the Write tool. End your aggregate.md file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Also write `<RUN_DIR>/summary.jsonl` — one compact JSON object per line, one line per finding: `{"file":"<basename>","sev":"critical|high|medium|low","id":"H1","line":"<line number or null>","category":"<category>","one_line":"<finding description>"}`. This file is what the orchestrator will read; aggregate.md is for human review only. Return ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"<RUN_DIR>/aggregate.md\",\"findings\":N,\"severity\":{\"security\":N,\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N,\"summary\":\"N findings total: S security, C critical, H high, M medium, L low\"}`"

Main context receives only that one-liner. Orchestrator MUST NOT read `aggregate.md` in full — 200–600 lines, overflows context on large audits. Use `$RUN_DIR/summary.jsonl` for all dispatch decisions in Steps 7 and 8.

## Step 5b: Low-confidence remediation

Parse confidence scores from each file's `## Confidence` block in `<RUN_DIR>/<slug>.md` output files (use Glob + Read — batch envelopes carry aggregate confidence, not per-file scores; individual file reports are the authoritative source). For each slug where `Score` < **0.80**, run three parallel passes:

**Health monitoring** (CLAUDE.md §6): apply the honest protocol in `$_FS/agent-spawn-protocol.md` — passes A–C return on completion; read each pass's output file afterwards. For a background probe, a single `find $RUN_DIR -newer "$SENTINEL" \( -name "*-rerun.md" -o -name "docs-recheck-*.md" -o -name "codex-recheck-*.md" \) | wc -l` per turn (`health_sentinel.py` §8b) — no sleep loop. On empty/missing output: mark `timed_out`, surface with ⏱ in final report.

> **Find precedence note**: parens around `-name` alternatives are mandatory — without them, `-newer` binds only to the first `-name`, and the others match every file regardless of mtime.

**A — Double-reasoning pass** (curator re-run with gaps called out):

Spawn **foundry:curator** with the prior report and its `Gaps:` block:

> "Re-audit `<original-source-file>` targeting these specific gaps from the prior pass: `<Gaps block content>`. Address each gap explicitly — do not repeat prior findings verbatim; focus on what was uncertain. Write updated findings to `<RUN_DIR>/<slug>-rerun.md`. End your full findings file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Return ONLY: `{\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N,\"summary\":\"...\"}`"

**B — Docs consultation** (verify findings against current Claude Code schema):

Spawn **foundry:web-explorer**:

> "Fetch current Claude Code docs for `[agent|skill|hook]` schema — navigate from `https://code.claude.com/docs/en/` to the `[sub-agents|skills|hooks]` page. Verify that findings about frontmatter fields or documented behavior in `<RUN_DIR>/<slug>-rerun.md` are accurate against current docs. List any corrections. Write to `<RUN_DIR>/docs-recheck-<slug>.md`. End your full findings file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Return ONLY: `{\"status\":\"done\",\"file\":\"<path>\",\"corrections\":N,\"confidence\":0.N}`"

**C — Codex adversarial pass** (requires `codex` plugin):

```bash
claude plugin list 2>/dev/null | grep -q 'codex@openai-codex' && CODEX_AVAILABLE=true || CODEX_AVAILABLE=false  # timeout: 15000
```

If `CODEX_AVAILABLE=true`: spawn `Agent(subagent_type="codex:codex-rescue")`:

> "Adversarial review of low-confidence findings for `<original-source-file>`. Prior foundry:curator pass scored confidence=<N> — gaps: `<Gaps>`. Challenge each finding: real? severity correct? missed issues? Read source file + prior report `<RUN_DIR>/<slug>-rerun.md`. Write to `<RUN_DIR>/codex-recheck-<slug>.md`. End your full findings file with a `## Confidence` block per quality-gates.md format (Score, Gaps, Refinements). Return ONLY: `{\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}`"

If `CODEX_AVAILABLE=false`: log `[Step 5b] Codex unavailable — adversarial pass skipped; install codex plugin for full low-confidence remediation.` Include note in final report `## Confidence` section.

**After all three passes complete** for a slug: spawn **foundry:curator** mini-consolidator to merge `<slug>-rerun.md`, `docs-recheck-<slug>.md`, `codex-recheck-<slug>.md` → append `### Low-Confidence Remediation — <slug>` section to `aggregate.md` with reconciled findings (promoted corrections, confirmed findings, refuted findings). Update `summary.jsonl` with any net-new findings.

**Skip Step 5b entirely** when no Step 3 files scored below 0.80.

## Step 6: Cross-validate critical findings

```bash
_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
SKIP_CROSS_VAL=false
[ -f "$_SHARED/cross-validation-protocol.md" ] || { printf "⚠ WARNING: cross-validation-protocol.md not found at $_SHARED — skipping cross-validation\n"; SKIP_CROSS_VAL=true; }
```

If `$SKIP_CROSS_VAL` = false: Read and follow cross-validation protocol from `$_SHARED/cross-validation-protocol.md`.

**Skill-specific**: the verifier agent is always **foundry:curator**.

## Step 7: Report findings

```bash
_RUN_DIR=$(cat "${TMPDIR:-/tmp}/audit-state/run-dir" 2>/dev/null || echo "")
_KEEP=$(cat "${TMPDIR:-/tmp}/audit-state/keep-items" 2>/dev/null || echo "")
_PRESERVE="run-dir=$_RUN_DIR, aggregate=$_RUN_DIR/aggregate.md, summary=$_RUN_DIR/summary.jsonl"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: foundry:audit · phase: report (after aggregate complete)"
    echo "- run-dir: $_RUN_DIR"
    echo "- preserve: $_PRESERVE"
    echo "- next: emit report → follow-up gate → optional fix mode (Steps 8-10) → Step 11"
} > .claude/state/skill-contract.md
```

Before emitting, read current `$RUN_DIR/summary.jsonl` (may have been updated by Step 5b with net-new promoted findings) and recompute severity totals. Then emit report (omit Upgrade Proposals if none passed genuine-value filter):

```markdown
## Audit Report

### Findings by Severity
#### Security (N) | Critical (N) | High (N) | Medium (N) | Low (N)
| File | Line | Issue | Category |
|---|---|---|---|
| agents/foo.md | 42 | References `bar-agent` which does not exist on disk | broken cross-ref |

### Summary
- Total: N (S security, C critical, H high, M medium, L low)
- Fix via follow-up gate: (a) Fix auto-fixable (Recommended) · (b) Fix SECURITY + CRITICAL + HIGH · (c) fix ALL incl. systemic

### Upgrade Proposals (N — pick `/audit --upgrade` from gate to apply)
| # | Feature | Type | Rationale |
|---|---------|------|-----------|
```

After report → fire **Follow-up gate**. If user picks fix option (a–c), proceed inline to the fix mode (Steps 8–10, loaded from `modes/fix.md`). Otherwise skip to Step 11.

## Steps 8–10: Fix dispatch, codex cross-file check, re-audit (mode: fix)

Runs **only** when the user picked a fix option (a–c) from the Step 7 follow-up gate. Resolve the modes dir, then read and execute `fix.md` — it carries Step 8 (delegate fixes to subagents), Step 9 (codex cross-file check), and Step 10 (re-audit + convergence loop), then returns here to Step 11:

```bash
AUDIT_MODES=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_skill_subdir.py" audit modes $( [ "$LOCAL_MODE" = true ] && echo "--local" )) || { printf "! BREAKING: audit/modes not found — run /foundry:setup first\n"; exit 1; }  # timeout: 5000
```

> loads: modes/fix.md
Read `$AUDIT_MODES/fix.md` and execute Steps 8–10 inline (state on disk in `summary.jsonl`, `$RUN_DIR`, `$AUDIT_TPL`). On convergence (clean or 5-pass limit), continue to Step 11 below. If no fix option was picked, skip directly to Step 11.

## Step 11: Final report

<!-- loads: report-template.md -->
Read `$AUDIT_TPL/report-template.md` and emit the complete audit report following its template and instructions.

**Terminal output** — per quality-gates.md universal rule: read the `---` header block from the top of the report file (all fields from opening `---` up to and including closing `---`) and print verbatim as the FIRST content of the reply. Then print `→ <report path>`. Then executive summary. Omit the `╔═╗` Re:Anchor box (communication.md exempts quality-gates `---` report headers).

**Completion marker** — on successful completion, write `$RUN_DIR/result.jsonl` with one JSONL line summarising the run (severity totals, scope, pass count). On any abort/error path before completion, leave `result.jsonl` absent — the TTL cleanup hook (artifact-lifecycle.md) intentionally skips run directories without `result.jsonl`, preserving incomplete runs for post-mortem debugging. To force cleanup of a known-bad incomplete run, write `{"status":"incomplete","reason":"<one-line>"}` to `result.jsonl` so TTL can age it out.

```bash
rm -f .claude/state/skill-contract.md  # clear contract — skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

## Mode: upgrade

**Trigger**: `/audit --upgrade`

Read and execute `$AUDIT_TPL/../modes/upgrade.md`.

## Mode: adversarial (alias: --challenge)

**Trigger**: `/audit [<scope>...] --adversarial`

Read and execute `$AUDIT_TPL/../modes/adversarial.md`.

## Mode: efficiency

**Trigger**: `/audit [<scope>...] --efficiency`

Read and execute `$AUDIT_TPL/../modes/efficiency.md`.

## Combined-run output isolation

When `--adversarial` and `--efficiency` both run in the same invocation: each mode writes its finding files to its own subdirectory to prevent overwriting — `$RUN_DIR/adversarial/` for adversarial mode output, `$RUN_DIR/efficiency/` for efficiency mode output. Step 5 consolidator reads both subdirs. Follow-up gate fires once after both complete with merged finding counts.

## Follow-up gate

**Always fires** unless `--skip-gate` passed (programmatic callers). Call `AskUserQuestion` — do NOT write options as plain text first. Map options directly into tool call arguments.

When user picks fix option (a–c): run Steps 8–10 inline via `modes/fix.md` (state on disk in `summary.jsonl`); no recursive `/audit` call.

**HARD RULE — Fixed option labels**: Use exactly the labels below verbatim. Do NOT rewrite, paraphrase, or substitute finding-specific alternatives. Finding context must NOT influence option labels. This rule has been violated repeatedly in past runs; enforce strictly.

**Mandatory options (always present, never omit)**:
- (a) label: `Fix auto-fixable (Recommended)` — auto-fix critical, high, medium, and low findings (skip NON_AUTO_FIXABLE systemic issues)
- (c) label: `Fix ALL` — collect all NON_AUTO_FIXABLE decisions upfront (max 4 `AskUserQuestion` calls), then run one integrated fix pass covering auto-fixable + resolved systemic items + lows; most thorough option

**Conditional options (include when condition met)**:
- (b) label: `Fix SECURITY + CRITICAL + HIGH` — include only when security, critical, or high findings present; omit otherwise to stay within 4-option cap
- (d) label: `Skip` — always include; when `--efficiency` ran and `extract_count > 0` (HIGH or MEDIUM), replace with `` `Run /distill executables (N HIGH, M MEDIUM candidates)` `` instead

**Option slot budget** (`AskUserQuestion` hard cap = 4 options; "Other" always auto-appended as 5th free-text slot):
- Typical: (a) + (b) + (c) + (d) = 4 ✓
- No sec/crit/high findings: (a) + (c) + (d) = 3 ✓ — slot freed; do NOT fill with custom finding-specific option
- Efficiency override active: (a) + (b) + (c) + distill = 4 ✓ — (d) Skip replaced by distill label

- question: "What next?" (include counts, e.g. "2 critical, 4 high, 3 medium, 1 low. What next?")

After completing `--upgrade`, `--adversarial`, or `--efficiency`: also fire this gate. For (d) Skip: remove the mode just run from the "for other modes" list. When `--adversarial --efficiency` combined: fire gate once after both complete with merged finding counts; remove both from (d) hint. Efficiency distill override: selecting distill option invokes `/distill executables` → `foundry:sw-engineer` extraction then `/audit --efficiency` re-run to confirm savings.

</workflow>

<notes>

- **`!` Breaking findings**: when skill or agent completely non-functional (check #7, broken cross-refs, invalid hook events), prefix finding with `!` and state impact + fix in one place — don't bury in table row. Surfaces as **`! BREAKING`** in bash output and as prominent callout in final report. **`! BREAKING` findings require user acknowledgment before audit proceeds past that check**: call `AskUserQuestion` — state what is broken and impact; user must explicitly confirm awareness before continuing. One question per distinct breaking finding; group only when logically one atomic issue. Prose acknowledgment in response body does NOT count — `AskUserQuestion` mandatory.
- **settings.json is hands-off**: missing permissions always reported, never auto-edited — structural JSON edits risk breaking Claude Code config loading
- **Dead loops need human judgment**: cycle in follow-up chains might be intentional (e.g., refactor → review → fix → refactor) — flag and explain, don't auto-remove
- **Convergence loop replaces cycle cap**: fix loop runs until zero fixable findings or 5-pass hard limit — see `modes/fix.md` Step 10 for full protocol
- **Relationship to curator**: `foundry:curator` = single-file reactive audit; `/audit` = system-wide sweep running foundry:curator at scale + cross-file checks
- **Paths must be portable**: `.claude/` for project-relative, `~/` or `$HOME/` for home — never literal `/Users/<name>/` or `/home/<name>/` (anti-examples only); applies to ALL config files including `settings.json`
- **Bash error logging**: if bash block in Pre-flight or Step 4 fails unexpectedly, append JSONL line to `.claude/logs/audit-errors.jsonl` (`{"ts":"<ISO>","check":"<N>","error":"<message>"}`) for post-mortem — never swallow errors silently.
- **Parallel execution rule**: after Step 2, launch Steps 3 and 4 in same response — all foundry:curator spawns AND system-wide bash checks issued together. Do NOT run Step 3 first then Step 4. Aggregation (Step 5) waits for both. Docs-freshness web-explorer (within Step 4) launches in same parallel batch.
- **Token cost**: Step 3 (foundry:curator spawns) most expensive. For quick structural scan needing only cross-reference + inventory validation, Step 4 system-wide checks often sufficient. Run `/audit agents` or `/audit skills` to scope, or skip Step 3 for fast pass when per-file quality already trusted.
- **Routing calibration complement**: for testing whether skill trigger descriptions fire correctly (trigger accuracy, A/B testing), use `/foundry:calibrate routing`. `/audit` checks structural quality; `/foundry:calibrate routing` validates right skill selected by Claude Code dispatcher.
- Follow-up chains:
  - Audit clean → pick `/foundry:setup` from gate to propagate verified config to `~/.claude/`
  - Audit found structural issues → review flagged files manually before syncing; pick fix level from gate
  - Audit found many low items → pick "Fix all" from gate, or run `/develop:refactor` (requires `develop` plugin) for targeted cleanup
  - After fixing agent instructions (from audit gate) → `/foundry:calibrate <agent>` to verify fix improved recall and confidence calibration
  - Audit Check 20 found description overlap → `/foundry:calibrate routing` to verify behavioral routing impact; update descriptions for confused pairs based on routing report
  - Audit surfaced upgrade proposals → run `/audit --upgrade` separately to apply (not a gate option — use Other slot or run the command directly after gate)
  - `/audit --upgrade` reverted capability change → run `/foundry:calibrate <agent> --full` for deeper signal (N=10 vs N=3 used in upgrade mode)
  - Audit Check 22 found unregistered calibratable mode → update `calibrate/modes/skills.md` domain table and run `/foundry:calibrate skills` to verify new target works
  - Audit Check 22 found stale domain table entry → remove from `calibrate/modes/skills.md`
  - `/audit --efficiency` found model over-provisioning → apply P1+P2 changes from efficiency report → re-run `/audit --efficiency` to confirm savings estimate; run `/foundry:calibrate routing --fast` to verify no routing regression from model changes
  - `/audit --efficiency` found bin/ extraction candidates (HIGH or MEDIUM verdict) → select `Run /distill executables` from follow-up gate to perform extraction; then re-run `/audit --efficiency` to confirm `extract_count == 0`

</notes>
