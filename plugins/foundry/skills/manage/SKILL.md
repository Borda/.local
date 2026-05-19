---
name: manage
description: "Create, update, or delete agents, skills, rules, and hooks with full cross-reference propagation. Trivial edits (typos, small fixes ≤10 words) applied inline without agent; `.md` content-edits delegated to foundry:curator; code file edits (`.js`, `.py`, `.ts`) delegated to foundry:sw-engineer; large cross-ref fan-outs (> 3 files) also delegate. The parent orchestrates MEMORY.md, README, audit, calibration, and the final report. Also manages settings.json permissions atomically with permissions-guide.md. NOT for: validation/quality audit of existing agents/skills (use /foundry:audit); implementing code changes (use develop:feature or develop:fix — requires `develop` plugin)."
argument-hint: 'create <agent|skill|rule> <name> "desc" | update <name> [new-name|"change"|spec.md] | delete <name> | add perm <rule> "desc" "use-case" | remove perm <rule>'
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion, Skill
effort: high
---

> **Note:** `disable-model-invocation: true` — `/manage` user-invoked only, no `Skill()` chaining from orchestrators. When suggesting `/manage` as follow-up, invoking skill must present as user-run command, not auto step.

<objective>

Manage lifecycle of agents, skills, rules, hooks in `.claude/`. Handles creation with rich domain content, atomic renames with cross-ref propagation, content editing (trivial edits inline; `.md` files → foundry:curator; code files `*.js`/`*.py`/`*.ts` → foundry:sw-engineer; rule edits inline), clean deletion with broken-ref cleanup. Keeps MEMORY.md inventory in sync with disk.

</objective>

<inputs>

- **$ARGUMENTS**: required, one of:
  - `create agent <name> "description"` — create new agent with generated domain content
  - `create skill <name> "description"` — create new skill with workflow scaffold
  - `create rule <name> "description"` — create new rule file with frontmatter and sections
  - `update <name> <new-name>` — rename; type auto-detected from disk
  - `update <name> "change description"` — content-edit; trivial → inline, `.md` → foundry:curator, code → foundry:sw-engineer, rule → inline
  - `update <name> <spec-file.md>` — content-edit from spec file; trivial → inline, `.md` → foundry:curator, code → foundry:sw-engineer, rule → inline
  - `delete <name>` — delete; type auto-detected from disk (agents, skills, rules, hooks); asks user if ambiguous
  - `add perm <rule> "description" "use case"` — add permission to settings.json allow list and permissions-guide.md
  - `remove perm <rule>` — remove permission from settings.json allow list and permissions-guide.md

- Names must be **kebab-case** (lowercase, hyphens only)
- Descriptions must be quoted when containing spaces
- Permission rules use Claude Code format: `WebSearch`, `Bash(cmd:*)`, `WebFetch(domain:example.com)`
- `--skip-audit` — optional flag: skip Step 9 `/audit` validation (use inside `audit fix` loop to avoid recursion)

**Update/delete mode** — name looked up across agents, skills, rules automatically:

- One match on disk → proceed with that type
- Multiple matches → `AskUserQuestion`: (a) agent, (b) skill, (c) rule
- No match → report error and stop

**Update second-argument discrimination**:

- Two bare kebab-case args (second arg no spaces, no `.md` extension) → **rename mode**
- One name + quoted string → **content-edit mode** (trivial → inline; `.md`: foundry:curator; code `*.js`/`*.py`/`*.ts`: foundry:sw-engineer; rule: inline)
- One name + path ending in `.md` → **content-edit mode** (trivial → inline; `.md`: foundry:curator; code `*.js`/`*.py`/`*.ts`: foundry:sw-engineer; rule: inline)

**Examples:**

- `/foundry:manage create agent task-planner "Planning specialist for decomposing epics into actionable tasks"`
- `/foundry:manage update my-agent "add a section on error handling patterns"`
- `/foundry:manage update optimize docs/specs/YYYY-MM-DD-<spec-name>.md`
- `/foundry:manage delete old-agent-name`
- `/foundry:manage add perm "Bash(jq:*)" "Parse and filter JSON" "Extract fields from REST API responses"`

</inputs>

<constants>

- AGENTS_DIR: `.claude/agents`
- SKILLS_DIR: `.claude/skills`
- RULES_DIR: `.claude/rules`
- HOOKS_DIR: `.claude/hooks`
- USED_COLORS: blue, cyan, green, orange, pink, purple, yellow
- AVAILABLE_COLORS: indigo, lime, magenta, teal, violet

Maintain colors manually — add new agent colors here when creating agents; static list advisory only — live Grep in Step 3 authoritative for colors in use.

</constants>

<workflow>

**Task hygiene**: call `TaskList` first; close orphaned tasks. **Task tracking**: create tasks for each major phase; mark in_progress/completed throughout.

## Step 1: Parse and validate

Extract operation, type, name, optional arguments from `$ARGUMENTS`.

```bash
# Parse --skip-audit flag before other argument processing
SKIP_AUDIT=false
[[ "$ARGUMENTS" == *"--skip-audit"* ]] && SKIP_AUDIT=true
ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/\(^\|[[:space:]]\)--skip-audit\([[:space:]]\|$\)/ /g' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')
```

**Unsupported flag check** — after all supported flags extracted (`--skip-audit`), scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--skip-audit\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Validation rules:**

- Name must match `^[a-z][a-z0-9-]*$` (kebab-case)
- For `create`: name must NOT already exist on disk; description required
- For `update`/`delete`: name MUST already exist on disk
- For `update` rename: new-name must NOT already exist on disk
- For `add perm`: rule must NOT already exist in settings.json allow list; description and use case required
- For `remove perm`: rule MUST already exist in settings.json allow list

**Type auto-detection** (for `update` and `delete`): run all four Glob checks in parallel:

- Agent: pattern `agents/<name>.md`, path `.claude/`
- Skill: pattern `skills/<name>/SKILL.md`, path `.claude/`
- Rule: pattern `rules/<name>.md`, path `.claude/`
- Hook: pattern `hooks/<name>.js`, path `.claude/`

Results:

- One non-empty result → resolved type; proceed
- Multiple non-empty results → `AskUserQuestion`: "Multiple entities named `<name>` found. Which one? (a) agent (b) skill (c) rule (d) hook"
- All empty → report "No agent, skill, rule, or hook named `<name>` found" and stop

For `create`, check only relevant type's path.

**Delete confirmation gate** — when `$MODE` is `delete`, immediately after type resolution invoke `AskUserQuestion`: "Delete `<name>` (`<type>`)? This cannot be undone. (a) Confirm · (b) Abort". On Abort: stop. On Confirm: proceed to Step 4.

```bash
# Check permission existence (for add perm / remove perm)
jq -e --arg rule '<rule>' '.permissions.allow | index($rule) != null' .claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

**Update second-argument discrimination** — apply after type resolved. Set the shell variable `MODE` from the parsed operation; it is consumed by the delete confirmation gate above, the edit-complexity classifier below, and the per-mode workflow branches in Step 4. Recognised values: `create`, `rename`, `content-edit`, `delete`, `add-perm`, `remove-perm`.

| Argument shape | `MODE` |
| --- | --- |
| `create <type> <name> "..."` | `create` |
| `update <name> <new-name>` (two bare kebab-case args; second has no spaces, no `.md`) | `rename` (validate new-name does NOT already exist) |
| `update <name> "<change>"` (one name + quoted string) | `content-edit` (validate spec non-empty; set `DIRECTIVE` = the quoted string) |
| `update <name> <spec>.md` (one name + path ending in `.md`) | `content-edit` (validate spec file exists on disk; set `DIRECTIVE` = contents of the spec file via Read tool) |
| `delete <name>` | `delete` |
| `add perm <rule> "..." "..."` | `add-perm` |
| `remove perm <rule>` | `remove-perm` |

Assign `MODE` in shell before the edit-complexity classification below so the `[[ "$MODE" == "content-edit" ]]` guard fires correctly:

```bash
# Set MODE from the operation parsed above. Example for an update invocation:
# MODE="content-edit"   # or "rename" / "create" / "delete" / "add-perm" / "remove-perm"
```

If validation fails, report error and stop.

**Edit complexity classification** (content-edit mode only):

```bash
# DIRECTIVE is the change description string (second argument, stripped of quotes) or spec file contents
# Set from argument parsing above before this block
DIRECTIVE="${SECOND_ARGUMENT}"  # populated during discrimination step above
# Classify directive as trivial vs substantive
EDIT_TRIVIAL=false
if [[ "$MODE" == "content-edit" ]]; then
  WORD_COUNT=$(echo "$DIRECTIVE" | wc -w)
  if [[ "$WORD_COUNT" -le 10 ]]; then
    echo "$DIRECTIVE" | grep -qiE '(typo|spelling|rename .+ to .+|change .+ to .+|replace .+ with .+|fix (a |the )?(typo|bug|error)|add missing|remove (the |a )?[a-z]+|correct)' \
      && EDIT_TRIVIAL=true
  fi
fi
```

Trivial = directive ≤10 words AND matches simple-change pattern. Trivial edits: apply inline with Edit tool — no agent spawn.

**Step skip rules**:

- **Perm operations**: skip Steps 2, 3, 5, 6, 7, 8, 9 — go Step 1 → Step 4 → Step 10
- **Hook operations**: skip Steps 2, 3, 6 (no color inventory, no MEMORY.md roster entry, no README table row); in Steps 5 and 7 skip cross-ref propagation (hook filenames not referenced from agent/skill markdown) — go Step 1 → Step 4 → Step 9 → Step 10
- **Content-edit operations**: skip Step 2 (entity already exists); skip Step 3 color inventory (no create); in Steps 5–7 only update cross-refs and README if name or description changed. Step 6 count: only update if name added or removed — content-only edits do not change agent/skill count.
- **Trivial content-edits**: additionally skip Steps 6–7 (no roster/description change possible); proceed Step 1 → Step 4 → Step 8 → Step 10

## Step 2: Overlap review (create only)

Before creating, check if existing agents/skills already cover requested functionality:

1. Read descriptions of all existing agents (use `Read(file_path=..., limit=3)` on each `.md` in agents/) and skills (use `Read(file_path=..., limit=3)` on each `SKILL.md`)
2. Compare new description against each existing — look for domain overlap, similar workflows, redundant scope
3. Present findings:
   - **No overlap**: proceed to Step 3
   - **Partial overlap**: name overlapping agent/skill, explain coverage vs what new one adds, use `AskUserQuestion`: "Extend existing (Recommended)" / "Proceed" / "Abort"
   - **Strong overlap**: recommend against creation — suggest using or extending existing agent/skill

Skip for `update`, `delete`, perm operations.

## Step 3: Inventory current state

Snapshot current roster for later comparison. Steps 2 and 3 are independent reads — issue Glob calls for both in same response.

Use Glob (pattern `agents/*.md`, path `.claude/`) for agents and Glob (pattern `skills/*/`, path `.claude/`) for skills. Use Grep (pattern `^color:`, glob `agents/*.md`, path `.claude/`, output mode `content`) to collect colors in use.

Extract names inline from Glob results — strip `.claude/agents/` prefix and `.md` suffix for agents; strip `.claude/skills/` prefix and trailing `/` for skills; strip `.claude/rules/` prefix and `.md` suffix for rules. Sort alphabetically when building roster string.

## Step 4: Execute operation

### Mode: Create Agent

1. Fetch latest Claude Code agent frontmatter schema:

   - Spawn **foundry:web-explorer** to fetch `https://code.claude.com/docs/en/sub-agents` with instruction: "Write your full findings (schema fields, new fields, deprecated fields) to `/tmp/manage-schema-$(date +%s).md` using the Write tool. Return ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"/tmp/manage-schema-<ts>.md\",\"fields\":N,\"new\":N,\"deprecated\":N,\"confidence\":0.N,\"summary\":\"N fields, N new, N deprecated\"}`" <!-- URL unverified — verify at: https://code.claude.com/docs/en/sub-agents -->

   **Health monitoring** (CLAUDE.md §8): After spawning web-explorer agent:
   ```bash
   eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/health_sentinel.py" start manage-web-explorer 2>/dev/null)"  # timeout: 5000
   [ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
   # Sets LAUNCH_AT + SENTINEL; use $SENTINEL in 5-min find -newer poll on /tmp for manage-schema-*.md files.
   ```
   Every 5 min: `find /tmp -newer "$SENTINEL" -name "manage-schema-*.md" | wc -l` — new files = alive; zero for 15 min = stalled. On timeout: read partial output; surface with ⏱.

   - Read returned summary; extract: valid frontmatter fields (`name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `effort`, `initialPrompt`, `skills`, `mcpServers`, `hooks`, `memory`, `background`, `isolation`, `color`), current model shorthands, new fields
   - Note new fields worth including. Adjust template to reflect current schema. If new field broadly useful for agent's role (e.g. `maxTurns` for long-running agents), include with sensible default and inline comment.

2. Pick first unused color from AVAILABLE_COLORS pool (compare against Step 3 colors)

3. Choose model based on role complexity:

   - `opusplan` — plan-gated roles (solution-architect, oss:shepherd, foundry:curator)
   - `opus` — complex implementation roles (foundry:sw-engineer, foundry:qa-specialist, research:scientist, foundry:perf-optimizer)
   - `sonnet` — focused execution roles (research:data-steward, foundry:web-explorer, foundry:doc-scribe, foundry:creator, oss:cicd-steward)
   - `haiku` — high-frequency diagnostics ONLY (e.g. linting-expert); NOT for analysis/auditing roles that require substantive reasoning

4. Resolve template path (cascade primary → project-local → cache scan; only the cache scan runs if neither of the cheaper paths exists, since each candidate must satisfy `-d` before being assigned):

```bash
MANAGE_TPL=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_skill_subdir.py" manage templates) || { printf "! BREAKING: manage templates not found — run /foundry:init first\n"; exit 1; }  # timeout: 5000
```

5. Spawn **foundry:sw-engineer** subagent to scaffold and write the agent file. `foundry:curator` is the wrong delegate here — its NOT-for explicitly excludes creating or scaffolding agents/skills; curator only reviews and edits existing config. `foundry:sw-engineer` owns scaffolding (treat agent `.md` as a config artifact whose authoring is a software task — frontmatter schema, tool selection, structural completeness).

> Before passing schema file path to sw-engineer: verify file exists on disk using Read tool (limit=1). If schema file path from JSON envelope does not exist, proceed with default frontmatter fields (name, description, model, color) — note omission in Step 10 report.

```markdown
Read the agent scaffold template at `$MANAGE_TPL/agent-scaffold.md`.
Also read the schema file at the path returned in the step 1 JSON to incorporate any new frontmatter fields (skip if schema file not found — use default frontmatter fields: name, description, model, color).
Scaffold `.claude/agents/<name>.md` with:
- Frontmatter: name=<name>, description=<description>, model=<model>, color=<color>; add any broadly-useful new fields from the schema
- Body: rich domain-specific content for the role described by the description, following all content rules and tool selection guidelines in the scaffold template
Write the file using the Write tool.
Return ONLY: {"status":"done","file":".claude/agents/<name>.md","lines":N,"confidence":0.N}
```

**Health monitoring** (CLAUDE.md §8): After spawning foundry:sw-engineer agent:
```bash
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/health_sentinel.py" start manage-sw-engineer-agent 2>/dev/null)"  # timeout: 5000
[ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
```
Every 5 min: `find .claude/agents -newer "$SENTINEL" -name "<name>.md" | wc -l` — new files = alive; zero for 15 min = stalled. On timeout: read partial output; surface with ⏱.

### Mode: Create Skill

1. Fetch latest Claude Code skill frontmatter schema:

   - Spawn **foundry:web-explorer** to fetch `https://code.claude.com/docs/en/skills` with instruction: "Write your full findings (schema fields, new fields, deprecated fields) to `/tmp/manage-skill-schema-$(date +%s).md` using the Write tool. Return ONLY a compact JSON envelope on your final line — nothing else after it: `{\"status\":\"done\",\"file\":\"/tmp/manage-skill-schema-<ts>.md\",\"fields\":N,\"new\":N,\"deprecated\":N,\"confidence\":0.N,\"summary\":\"N fields, N new, N deprecated\"}`" <!-- URL unverified — verify at: https://code.claude.com/docs/en/skills -->

   **Health monitoring** (CLAUDE.md §8): After spawning web-explorer agent:
   ```bash
   eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/health_sentinel.py" start manage-web-explorer-skill 2>/dev/null)"  # timeout: 5000
   [ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
   ```
   Every 5 min: `find /tmp -newer "$SENTINEL" -name "manage-skill-schema-*.md" | wc -l` — new files = alive; zero for 15 min = stalled. On timeout: read partial output; surface with ⏱.

   - Read returned summary; extract: valid frontmatter fields (`name`, `description`, `argument-hint`,`disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `effort`, `shell`, `paths`, `context`, `agent`, `hooks`), new fields
   - Note new fields worth including. Adjust template to reflect current schema. Include `model` or `context: fork` only when skill's purpose clearly benefits.

2. **Re-resolve `MANAGE_TPL` at the start of each skill invocation**; do not assume it is set from a prior step. Most `/foundry:manage create skill ...` invocations enter Create Skill mode directly without going through Create Agent first, so the variable will be unset. Run the resolution block from Create Agent step 4 above (cascade primary → project-local → cache scan with the `-d` guards) before reading any template path.

3. Spawn **foundry:sw-engineer** subagent to create directory and scaffold the skill file (`foundry:curator` NOT-for excludes scaffolding new agents/skills — see Create Agent rationale above):

```markdown
Run: `mkdir -p .claude/skills/<name>` using the Bash tool.
Read the skill scaffold template at `$MANAGE_TPL/skill-scaffold.md`.
Also read the schema file at the path returned in the step 1 JSON to incorporate any new frontmatter fields.
Read `$_FOUNDRY_SHARED/bin-authoring-guide.md` — before writing any fenced code block in the new SKILL.md, apply the extraction gate. Write a bin/ script directly if verdict is MEDIUM or HIGH.
Scaffold `.claude/skills/<name>/SKILL.md` with:
- Frontmatter: name=<name>, description=<description>; add other fields per schema and scaffold guidance
- Body: rich workflow scaffold derived from the description, following all content rules in the scaffold template
Write using the Write tool.
Return ONLY: {"status":"done","file":".claude/skills/<name>/SKILL.md","lines":N,"confidence":0.N}
```

**Health monitoring** (CLAUDE.md §8): After spawning foundry:sw-engineer agent:
```bash
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/health_sentinel.py" start manage-sw-engineer-skill 2>/dev/null)"  # timeout: 5000
[ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
```
Every 5 min: `find .claude/skills -newer "$SENTINEL" -name "SKILL.md" | wc -l` — new files = alive; zero for 15 min = stalled. On timeout: read partial output; surface with ⏱.

### Mode: Update Agent (rename)

Atomic rename — write new file before deleting old:

1. Read `.claude/agents/<old-name>.md` using the Read tool.

2. Write new file to `.claude/agents/<new-name>.md` using the Write tool (copy content of old file with `name:` line updated to `<new-name>`).

3. Verify new file exists and is valid: `Read(file_path=".claude/agents/<new-name>.md", limit=5)`

```bash
# 4. Delete old file only after new file is confirmed — user invoked rename explicitly; new file verified above; no additional confirmation required
rm .claude/agents/<old-name>.md # timeout: 5000
```

### Mode: Update Skill (rename)

Atomic rename — create new directory before removing old:

1. Create new directory:

    ```bash
    mkdir -p .claude/skills/<new-name>  # timeout: 5000
    ```

2. Read old SKILL.md, update `name:` line in frontmatter, Write to new location.

   > After updating `name:` in frontmatter: also scan the new SKILL.md body for TRIGGER conditions, NOT-for lines, and example invocations that still reference the old skill name — update those inline with Edit tool before proceeding to Step 5.

3. Verify new file exists: `Read(file_path=".claude/skills/<new-name>/SKILL.md", limit=5)`

    ```bash
    # 4. Remove old directory only after new is confirmed — user invoked rename explicitly; new file verified above; no additional confirmation required
    rm -r .claude/skills/<old-name>  # timeout: 5000
    ```

### Mode: Delete Agent

```bash
# Confirmed by delete gate in Step 1 — safe to proceed
rm .claude/agents/<name>.md # timeout: 5000
```

### Mode: Delete Skill

```bash
# Confirmed by delete gate in Step 1 — safe to proceed
rm -r .claude/skills/<name>  # timeout: 5000
```

### Mode: Update Agent/Skill (content-edit)

Before executing type-specific content-edit mode, determine approach:

**File-type → agent routing:**

| File extension | Agent |
| --- | --- |
| `.md` (agents, skills, SKILL.md) | `foundry:curator` |
| `.js`, `.py`, `.ts`, `.sh` (code) | `foundry:sw-engineer` |
| Rule `.md` (under `rules/`) | inline Edit — no agent |

**If `EDIT_TRIVIAL=true`** (classified in Step 1):
1. Read file using Read tool
2. Apply directive directly using Edit tool — no agent spawn
3. Proceed to Step 8; skip Steps 5–7 unless name or description changed in edit

**If `EDIT_TRIVIAL=false`**: proceed to type-specific mode below for full agent-delegated edit.

### Mode: Content-Edit Agent

1. Determine change directive:
   - Quoted description → use as-is
   - Spec file path → Read spec file; use content as directive
2. Spawn **foundry:curator** subagent:

```markdown
Read `.claude/agents/<name>.md`.
Apply this change: <directive>
Rules:
- Preserve frontmatter fields (name, description, tools, model, color) unless the change explicitly targets them
- Preserve XML tags (<role>, <core_knowledge>, <workflow>, <notes>) — targeted edits only; do not rewrite unchanged sections
- If the change modifies the agent's purpose: update the description: frontmatter field
- If the change adds any fenced code block: read `$_FOUNDRY_SHARED/bin-authoring-guide.md` and apply the extraction gate — write a bin/ script instead if verdict is MEDIUM or HIGH
- After editing: verify XML tag balance, step numbering, cross-ref validity
Write all changes using the Edit tool.
Return ONLY: {"status":"done","file":".claude/agents/<name>.md","edits":N,"description_changed":true|false,"confidence":0.N}
```

Use `description_changed` from returned JSON to decide whether Steps 5–7 need cross-ref propagation.

### Mode: Content-Edit Skill

1. Determine change directive (same as Content-Edit Agent).
2. Spawn **foundry:curator** subagent:

```markdown
Read `.claude/skills/<name>/SKILL.md`.
Apply this change: <directive>
Rules:
- Preserve frontmatter fields (name, description, argument-hint, disable-model-invocation, allowed-tools)
- Preserve XML tags (<objective>, <inputs>, <workflow>, <notes>) — targeted edits only; do not rewrite unchanged sections
- If the change modifies the skill's purpose: update the description: frontmatter field
- If the change adds any fenced code block: read `$_FOUNDRY_SHARED/bin-authoring-guide.md` and apply the extraction gate — write a bin/ script instead if verdict is MEDIUM or HIGH
- After editing: verify XML tag balance, step numbering, workflow gate completeness
Write all changes using the Edit tool.
Return ONLY: {"status":"done","file":".claude/skills/<name>/SKILL.md","edits":N,"description_changed":true|false,"confidence":0.N}
```

Use `description_changed` from returned JSON to decide whether Steps 5–7 need cross-ref propagation.

### Mode: Content-Edit Rule

1. Read `.claude/rules/<name>.md` using the Read tool.
2. Determine change directive (same as Content-Edit Agent).
3. Apply changes directly using the Edit tool:
   - Preserve YAML frontmatter (description, paths) unless change explicitly targets them
   - Rule files are free-form markdown with `##` sections — no XML tags
   - Targeted edits — do not rewrite unchanged sections
   - Adding new section: match heading level and style of existing sections
   - If change modifies rule's scope: also update `description:` and `paths:` frontmatter fields
   - After editing: verify YAML frontmatter valid, no broken internal references

### Mode: Create Rule

No schema fetch needed — rule files simpler than agents/skills (only frontmatter + free-form markdown sections).

**Rule scope guidance**: empty `paths:` = global rule (applies everywhere); populated `paths:` = scoped (e.g., `paths: ["src/**/*.py"]` for Python-only rules). Default to global unless rule is clearly language/directory-specific.

Write `.claude/rules/<name>.md` with this structure:

```markdown
---
description: <one-line description from user>
paths:
  - '<glob pattern matching the rule's scope>'
---

## <First Section Title>

[Real domain-specific rules derived from the description — not generic boilerplate. 20-60 lines total.]
```

Content rules:

- Generate real domain content from description (e.g., for "torch-patterns": actual PyTorch patterns, not generic "write clean code")
- Use `##` sections for major topics, bullets for individual rules
- Include code examples only when they carry domain-specific patterns
- Match tone and density of existing rules files (terse, imperative, no padding)

### Mode: Update Rule (rename)

Atomic update — write new file before deleting old:

1. Read `.claude/rules/<old-name>.md` using the Read tool.
2. Rule files have no `name:` frontmatter field — filename IS identifier. Write new file at `.claude/rules/<new-name>.md` with identical content.
3. Verify new file exists.
4. Delete old file only after new file confirmed: `rm .claude/rules/<old-name>.md` <!-- timeout: 5000 -->

### Mode: Delete Rule

```bash
# Confirmed by delete gate in Step 1 — safe to proceed
rm .claude/rules/<name>.md # timeout: 5000
```

### Mode: Content-Edit Hook

Hook files are JavaScript — delegate to **foundry:sw-engineer** (not foundry:curator):

1. Determine change directive (same as Content-Edit Agent).
2. Spawn **foundry:sw-engineer** subagent:

```markdown
Read `.claude/hooks/<name>.js`.
Apply the hook authoring standards from the `\<hook_authoring>` section in your agent definition — file-header structure, exit code semantics, stdin pattern, and anti-patterns.
Apply this change: <directive>
Rules:
- Preserve the file header block (PURPOSE, HOW IT WORKS, EXIT CODES) unless the change explicitly modifies that logic
- Preserve CommonJS require() style; do not convert to ESM
- stdin must use event-based accumulation (process.stdin.on("data"/"end")); never readFileSync("/dev/stdin")
- All subprocess calls must use execFileSync or spawnSync (args array — no execSync with shell strings)
- All logic must be wrapped in try/catch; catch always exits 0
- After editing: verify exit codes match documented cases, no shell injection surface added
Write all changes using the Edit tool.
Return ONLY: {"status":"done","file":".claude/hooks/<name>.js","edits":N,"confidence":0.N}
```

### Mode: Delete Hook

```bash
rm .claude/hooks/<name>.js # timeout: 5000
```

After deleting the hook file, also remove its entry from `.claude/settings.json` so Claude Code does not invoke a missing script. Identify the hook's matcher pattern (the entry's `matcher` field, or `command` substring containing the deleted filename) and run jq to strip every block referencing it. Substitute `<name>` with the deleted hook's basename (no `.js` suffix):

```bash
# timeout: 5000
HOOK_NAME="<name>"        # e.g. "rtk-rewrite" — basename of deleted hook, no .js suffix
# Remove every PreToolUse / PostToolUse / SessionStart / etc. entry whose hooks[].command references this file
jq --arg hook "$HOOK_NAME" '
    .hooks //= {}
    | .hooks |= with_entries(
        .value |= map(
            .hooks |= map(select((.command // "") | test("/" + $hook + "\\.js"; "i") | not))
        )
        | .value |= map(select((.hooks // []) | length > 0))
    )
    | .hooks |= with_entries(select((.value // []) | length > 0))
' .claude/settings.json > /tmp/settings-tmp.json && mv /tmp/settings-tmp.json .claude/settings.json
```

Verify the entry is gone:

```bash
jq --arg hook "$HOOK_NAME" '[.. | objects | select(.command? // "" | test($hook + "\\.js"))] | length' .claude/settings.json  # timeout: 5000
# Expected output: 0
```

### Mode: Add Permission

Adds rule to both `settings.json` and `permissions-guide.md` atomically.

1. Determine guide category from rule prefix:

   - `WebSearch` → `## Web`
   - `WebFetch(domain:...)` → `## WebFetch — allowed domains`
   - `Bash(gh ...)` → `## GitHub CLI — read-only`
   - `Bash(git log:*)`, `Bash(git show:*)`, `Bash(git diff:*)`, `Bash(git rev-*:*)`, `Bash(git ls-*:*)`, `Bash(git -C:*)`, `Bash(git branch:*)`, `Bash(git tag:*)`, `Bash(git status:*)`, `Bash(git describe:*)`, `Bash(git shortlog:*)` → `## Git — read-only`
   - `Bash(git add:*)`, `Bash(git checkout:*)`, `Bash(git stash:*)`, `Bash(git restore:*)`, `Bash(git clean:*)`, `Bash(git apply:*)` → `## Git — local write`
   - `Bash(pytest:*)`, `Bash(python ...)`, `Bash(ruff:*)`, `Bash(mypy:*)`, `Bash(pip ...)` → `## Python toolchain`
   - `Bash(brew ...)`, `Bash(codex:*)` → `## macOS / ecosystem`
   - All other `Bash(...)` → `## Shell utilities`

2. Update `settings.json` — atomic jq edit via shared helper:

    ```bash
    # timeout: 15000
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/jq_write.py" .claude/settings.json '.permissions.allow += [$rule]' --arg rule "<rule>"
    ```

3. Also append to plugin's `permissions-allow.json` so `/foundry:init` syncs it to `~/.claude/settings.json` on reinstall:

    ```bash
    # timeout: 5000
    PERM_FILE="${CLAUDE_PLUGIN_ROOT}/.claude-plugin/permissions-allow.json"
    if [ -f "$PERM_FILE" ]; then
        python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/jq_write.py" "$PERM_FILE" '. += [$rule] | unique' --arg rule "<rule>"
    fi
    ```

4. Update `permissions-guide.md` — append new row to end of correct section (before its trailing `---` separator). New row format:

    ```markdown
    | `<rule>` | <description> | <use case> |
    ```

    Use Edit tool to insert row: find last table row in target section and insert after it.

5. Verify both files updated:

    ```bash
    # timeout: 5000
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/verify_perm.py" "<rule>" .claude/settings.json .claude/permissions-guide.md present
    # Exits 0 if both consistent; prints "settings: OK|MISSING" + "guide: OK|MISSING"
    ```

### Mode: Remove Permission

Removes rule from both `settings.json` and `permissions-guide.md` atomically.

1. Update `settings.json` — atomic jq edit via shared helper:

    ```bash
    # timeout: 15000
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/jq_write.py" .claude/settings.json 'del(.permissions.allow[] | select(. == $rule))' --arg rule "<rule>"
    ```

2. Update `permissions-guide.md` — use Edit tool to remove table row containing `` `<rule>` ``.

3. Verify both files clean:

    ```bash
    # timeout: 5000
    python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/verify_perm.py" "<rule>" .claude/settings.json .claude/permissions-guide.md absent
    # Exits 0 if both consistent; prints "settings: OK|STILL_PRESENT" + "guide: OK|STILL_PRESENT"
    ```

## Step 5: Propagate cross-references

Search all `.claude/` markdown files for changed name and update references:

Use Grep to find all references:

- Pattern `<name>`, glob `agents/*.md`, path `.claude/`, output mode `content`
- Pattern `<name>`, glob `skills/*/SKILL.md`, path `.claude/`, output mode `content`
- Pattern `<name>`, glob `rules/*.md`, path `.claude/`, output mode `content`
- Pattern `<name>`, file `.claude/CLAUDE.md`, output mode `content`
- Pattern `<name>`, file `README.md`, output mode `content`

**For update (rename):** Count files grep returns. **≤ 3 files**: apply inline with Edit tool. **> 3 files**: spawn **foundry:curator** subagent. For hook renames: also update hook entry in `.claude/settings.json` `hooks` array if hook filename referenced there by path.

```text
Apply these cross-reference updates (<old-name> → <new-name>):
<list each file path with the required substitution>
Use the Edit tool for each file (replace_all: true where appropriate).
Return ONLY: {"status":"done","files_updated":N}
```

**For delete:** Review each reference. Deleted name in:

- Cross-ref suggestion — remove or replace with closest alternative
- Inventory list — remove entry
- Workflow spawn directive — flag for manual review

**For create:** No cross-ref propagation needed.

**For content-edit:** Run propagation only if entity's `description:` frontmatter changed — propagate new description to any MEMORY.md or README summary lines that quote it. Skip if only internal content changed.

## Step 6: Update MEMORY.md roster (auto-memory)

MEMORY.md is Claude Code's auto-memory file — **not** stored under `.claude/`. Injected into conversation context at session start. Absolute path appears near top of system prompt (e.g. `~/.claude/projects/.../memory/MEMORY.md`). Use that absolute path with Edit tool.

Regenerate inventory lines from disk:

Use Glob (`agents/*.md`, path `.claude/`) for agents, Glob (`skills/*/`, path `.claude/`) for skills, Glob (`rules/*.md`, path `.claude/`) for rules. Extract names inline from returned paths (strip path prefix and `.md`/trailing-`/` suffix), join as comma-separated string.

Use Edit tool with **absolute auto-memory path** to update these roster lines in MEMORY.md:

- `- Agents: doc-scribe, foundry:sw-engineer, ...`
- `- Skills: review, research, ...`
- `- Rules (N): artifact-lifecycle, ...` (update count N when rules created or deleted)

**For content-edit:** Skip if only internal content changed; update only if description changed.

## Step 7: Update README.md

**`README.md` (project root):**

- **create agent**: add row to `### Agents` table — columns: `| **name** | Short tagline | Key capabilities |`
- **create skill**: add row to `### Skills` table — columns: `| **name** | \`/name\` | Description |\`
- **update (rename)**: find and replace old name in table row
- **delete**: remove row for deleted name

**`.claude/README.md` (config README) — Rules table only:**

- **create rule**: add row to Rules reference table — columns: `| rule-file | Applies to | What it governs |`
- **update rule (rename)**: replace old name in Rules table row
- **update rule (content-edit)**: update "What it governs" column if rule's description changed
- **delete rule**: remove row for deleted rule

Keep descriptions concise (one line), consistent in tone with surrounding rows. Do not add/remove table columns.

**For content-edit (agent/skill):** Update README if description OR model field changed. Model changes update the Model column only; description changes update the description column.

## Step 8: Verify integrity

Confirm no broken references remain:

Use Grep (pattern `[a-z]+:[a-z]+(-[a-z]+)*` to find cross-plugin references, or `See [a-z-]+ agent` for cross-references, glob `{agents/*.md,skills/*/SKILL.md}`, path `.claude/`, output mode `content`). Avoid broad kebab-case patterns — they match code examples and produce false positives.

Use Glob (`agents/*.md`, path `.claude/`) and Glob (`skills/*/`, path `.claude/`) for on-disk inventory; extract names inline. Use Grep to search for changed name and confirm:

- **Update (rename)**: zero hits for old name, appropriate hits for new name
- **Delete**: zero hits for deleted name (or flagged references noted)
- **Create**: new file exists with valid structure
- **Content-edit**: target file has valid structure (XML tag balance for agents/skills; YAML frontmatter for rules)

Add rules to on-disk inventory check: Glob (`rules/*.md`, path `.claude/`), extract names inline.

For **create** and **update (rename)**: verify tool efficiency — cross-check agent/skill's declared tools (`tools:` or `allowed-tools:`) against tool names in workflow body. Declared tool not referenced anywhere → flag as cleanup candidate in Step 10 report (report only — do not block operation).

## Step 9: Audit and calibrate

Invoke `Skill(skill="foundry:audit", args="--skip-gate")` to validate created/modified files without triggering interactive follow-up gate (requires `foundry` plugin). **Skip if invoked with `--skip-audit` or if current `manage` operation runs inside audit-initiated fix session** — outer audit covers it.

```bash
[[ "$SKIP_AUDIT" == "true" ]] && { echo "[--skip-audit] skipping Step 9 audit"; }
```

For targeted check of only affected file, spawn **foundry:curator** directly:

- For `create`: audit new file for structural completeness, cross-ref validity, content quality
- For `update`: audit renamed file, verify no stale references remain
- For `delete`: audit remaining files for broken references to deleted name

Include audit findings in final report. Do not proceed to sync if any `critical` findings remain.

**Calibration** — for agent/skill create or non-trivial content-edit, invoke `Skill(skill="foundry:calibrate", args="<name>")` after audit passes — mandatory, not optional (requires `foundry` plugin).

Then invoke `Skill(skill="foundry:calibrate", args="routing --fast")` to confirm overall routing accuracy unaffected (requires `foundry` plugin).

Skip calibration for: trivial edits, renames, deletes, rule operations, perm operations.

## Step 10: Summary report

- **Operation**: what was done (create/update/delete + type + name, or add/remove perm + rule)
- **Files Changed**: table of file paths and actions (created/renamed/deleted/cross-ref updated/appended/removed)
- **Cross-References**: count of files updated, broken refs cleaned (n/a for perm operations)
- **Current Roster**: agents (N) and skills (N) with comma-separated names (n/a for perm operations)
- **Audit Result**: audit findings (pass / issues found) (n/a for perm operations)
- **Calibration Result**: recall score and routing accuracy from Step 9 (n/a for trivial edits, renames, deletes, perms)
- **Follow-up**: perm ops → confirm both `settings.json` and `permissions-guide.md` updated; run `/foundry:init` to sync `~/.claude/`

End response with `## Confidence` block per CLAUDE.md output standards.

</workflow>

<notes>

- **Atomic updates**: write-before-delete prevents data loss on interruption; perm ops must update both `settings.json` and `permissions-guide.md`
- **settings.json format**: jq with atomic tmp-file pattern (`jq ... > .tmp && mv .tmp dest`) — avoids fragile sed/awk on JSON; indent=2 via `jq --indent 2` when formatting required
- **README.md tables**: agent/skill tables in project `README.md`; rules table in `.claude/README.md` — keep row format consistent with existing rows
- **No auto-edit for agent/skill/rule operations**: skill does not mutate settings.json for non-perm operations
- **Color pool**: AVAILABLE_COLORS lists unused colors; if exhausted, reuse with note
- Follow-up chains:
  - create or non-trivial update of agent/skill → `Skill(skill="foundry:audit", args="--skip-gate")` → `Skill(skill="foundry:calibrate", args="<name>")` (mandatory) → `Skill(skill="foundry:calibrate", args="routing --fast")`
  - trivial update or rename or delete → `Skill(skill="foundry:audit", args="--skip-gate")` → `Skill(skill="foundry:calibrate", args="routing --fast")` (if description changed)
  - add/remove perm → confirm both files updated; run `/foundry:init`

</notes>
