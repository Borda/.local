# Skill Checks — 21, 22, 23, 24, 27, 28, 30, 31

## Check 21 — Skill frontmatter conflicts

`context:fork + disable-model-invocation:true` is broken combination.

```bash
RED='\033[1;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'
for f in .claude/skills/*/SKILL.md; do # timeout: 5000
    name=$(basename "$(dirname "$f")")
    if awk '/^---$/{c++} c<2' "$f" 2>/dev/null | grep -q 'context: fork' &&
    awk '/^---$/{c++} c<2' "$f" 2>/dev/null | grep -q 'disable-model-invocation: true'; then
        printf "${RED}! BREAKING${NC} skills/%s: context:fork + disable-model-invocation:true\n" "$name"
        printf "  ${RED}→${NC} forked skill has no model to coordinate agents or synthesize results\n"
        printf "  ${CYN}fix${NC}: remove disable-model-invocation:true (or remove context:fork if purely tool-only)\n"
    fi
done
```

## Check 22 — Calibration coverage gap

**Step 1 — Read calibrate domain table**: Read `.claude/skills/calibrate/modes/skills.md`, extract registered target list under `### Domain table`. Build registered-targets set.

**Step 2 — Scan all skill modes on disk**: Use Glob (`skills/*/SKILL.md`, path `.claude/`) and Glob (`skills/*/modes/*.md`, path `.claude/`) to enumerate every skill and mode file. Extract mode names from `argument-hint:` frontmatter and `## Mode:` / `### Mode:` headings.

**Step 3 — Validate registered targets exist on disk**: For each registered target, verify matching skill/mode file exists. Registered target with no matching file → **medium** (calibrate fails at runtime).

**Step 4 — Identify unregistered calibratable candidates** (model reasoning):

Mode is calibratable when ALL three signals present:

1. **Deterministic structured output**: findings list, completeness checklist, structured table, or machine-readable verdict
2. **Synthetic input feasible**: testable without external services
3. **Ground truth constructable**: known issues injectable and scorable

→ Unregistered mode matching all three: **low** (add to `calibrate/modes/skills.md` domain table)

**Step 5 — Read agents domain table**: Read `.claude/skills/calibrate/modes/agents.md`, extract all agent names from `### Domain table`. Build registered-agent-names set.

**Step 6 — Scan all agent files on disk**: Use Glob (`plugins/*/agents/*.md`, path project root) for plugin agent files; Glob (`agents/*.md`, path `.claude/`) for directly installed agents. Derive qualified name per file: `plugins/<plugin>/agents/<name>.md` → `<plugin>:<name>`; `.claude/agents/<name>.md` → `<name>`. Build full discovered-agent set.

**Step 7 — Validate registered agents exist on disk**: For each registered agent in domain table, verify it resolves to discovered file. Bare name (e.g. `sw-engineer`) matches `foundry:sw-engineer` when no `.claude/agents/sw-engineer.md` exists — apply model reasoning to resolve bare names against plugin-qualified discoveries. Registered agent with no matching file → **medium** (stale entry causes calibrate to fail at runtime; remove from domain table or correct prefix).

**Step 8 — Identify unregistered agents**: For each discovered agent not in domain table, apply same three-signal calibratability test from Step 4. → Unregistered calibratable agent: **low** (add to `calibrate/modes/agents.md` domain table with appropriate domain string).

## Check 23 — Bash command misuse / native tool substitution

```bash
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'
printf "=== Check 23: Bash misuse candidates ===\n"
grep -rn '\bcat \|`cat ' .claude/agents/ .claude/skills/ .claude/rules/ 2>/dev/null |
grep -v '^Binary' | grep -v '# ' &&
printf "  ${CYN}hint${NC}: replace cat with Read tool\n" || true
grep -rn '\bgrep \|\brg \b' .claude/agents/ .claude/skills/ .claude/rules/ 2>/dev/null |
grep -v '^Binary' | grep -v '# .*grep\|Grep tool\|Use Grep' &&
printf "  ${CYN}hint${NC}: replace grep/rg with Grep tool\n" || true
grep -rn '\bfind \b.*-name\|\bls \b.*\*' .claude/agents/ .claude/skills/ .claude/rules/ 2>/dev/null |
grep -v '^Binary' | grep -v '# .*Glob\|Use Glob\|Glob tool' &&
printf "  ${CYN}hint${NC}: replace find/ls with Glob tool\n" || true
grep -rn 'echo .* >\|tee ' .claude/agents/ .claude/skills/ .claude/rules/ 2>/dev/null |
grep -v '^Binary' | grep -v '# .*Write tool\|Use Write' &&
printf "  ${CYN}hint${NC}: replace echo-redirect/tee with Write tool\n" || true
grep -rn '\bsed \b\|\bawk \b' .claude/agents/ .claude/skills/ .claude/rules/ 2>/dev/null |
grep -v '^Binary' | grep -v '# .*Edit tool\|Use Edit\|awk.*{print\|awk.*BEGIN' &&
printf "  ${CYN}hint${NC}: replace sed/awk text-substitution with Edit tool\n" || true
printf "${GRN}✓${NC}: Check 23 scan complete\n"
```

After scan, apply model reasoning to each match — exclude cases where shell command genuinely necessary. Flag only where native tool is direct drop-in.

| Shell command | Preferred native tool | Severity |
| --- | --- | --- |
| `cat <file>` | Read tool | medium |
| `grep`/`rg` for content search | Grep tool | medium |
| `find`/`ls` for file listing | Glob tool | medium |
| `echo … >` / `tee` to write a file | Write tool | medium |
| `sed`/`awk` for text substitution | Edit tool | medium |

### Sub-check 23e — python3 inline policy (CLAUDE.md / MEMORY.md violation)

`python3` intentionally absent from allow list (MEMORY.md: "Allow List Policy — python* excluded by design"). Any `python3 -c` in skill body pauses for permission prompt mid-workflow; user deny = phase fails.

```bash
printf "=== Check 23e: python3 inline policy ===\n"
grep -rn 'python3 -c\b' plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null |
  grep -v '^Binary' | grep -v '^\s*#' &&
printf "  hint: python3 not in allow list by design — move logic to bin/*.py or use native tools (Read/Write/Edit/Bash with jq)\n" || true
printf "=== Check 23e: heredoc python policy ===\n"
grep -rn "python3 << '\|python3 <<\"" plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null |
  grep -v '^Binary' | grep -v '^\s*#' &&
printf "  hint: CLAUDE.md bans heredoc python; use bin/*.py instead\n" || true
printf "✓: Check 23e scan complete\n"  # timeout: 5000
```

Severity: **high** — permission prompt mid-workflow blocks automation; user deny = skill phase fails.

| Sub-check | Pattern | Severity |
| --- | --- | --- |
| 23e — python3 -c inline | `python3 -c` in skill body | high |
| 23e — python3 heredoc | `python3 << '` in skill body | high |

**Report only** — never auto-fix; some Bash invocations in example/illustration code blocks intentional.

## Check 24 — Skill sequence compatibility

Skill `<notes>` and `<workflow>` sections frequently document multi-skill chains (e.g., `→ /audit`, `suggested next: /brainstorm breakdown <file>`). Check verifies documented sequences internally consistent:

- **24a (target existence)**: every skill referenced in documented chain exists on disk — root skills under `.claude/skills/<name>/`, plugin skills under `plugins/<plugin>/skills/<skill>/`
- **24b (argument plausibility)**: when suggestion includes explicit argument (e.g., `→ /audit fix`), that argument must appear as substring in target skill's `argument-hint:` frontmatter (case-insensitive)

**Step 1 — Extract sequence references**:

Scan three sources for documented chains:

1. **Skill files**: Grep (pattern `→.*` + backtick + `/[a-z]|suggest.*` + backtick + `/[a-z]|run.*after.*` + backtick + `/[a-z]`, glob `skills/*/SKILL.md`, path `.claude/`, output mode `content`)
2. **Agent files**: same Grep on `agents/*.md` (path `.claude/`)
3. **README files**: Grep same pattern in `README.md` (project root), `plugins/*/README.md`, `.claude/README.md` — README sequence tables are canonical workflow chain documentation; must be consistent with what is installed

Filter out:

- Lines starting with `#` (comments)
- Lines containing `e.g.` or `for example` (illustrative, not directive)
- Lines whose surrounding context describes what skill does rather than "run next" directive

Collect all unique (source-file, skill-reference, trailing-argument) triples. README-sourced sequences held to same validity standard as skill-sourced ones: broken README sequence = **high** (user-facing workflow documentation).

**Step 2 — Resolve each reference (Check 24a)**:

| Reference form | Resolution |
| --- | --- |
| `/name` | Glob `.claude/skills/name/SKILL.md` — must exist |
| `/plugin:name` | Glob `plugins/plugin/skills/name/SKILL.md` — must exist; if no `plugins/` dir, note "installed plugin — cannot verify statically" and skip |

Missing target → **[high]**: `Sequence reference /<name> in <file> resolves to no installed skill`

**Step 3 — Argument plausibility (Check 24b)**:

For references with trailing argument token (e.g., `--adversarial` in `/audit --adversarial`, `breakdown` in `/brainstorm breakdown`):

1. Read target skill's frontmatter `argument-hint:` (Glob-resolved path, first 5 lines)
2. If argument token does NOT appear as case-insensitive substring of `argument-hint` → **[medium]**: `Sequence argument '<arg>' absent from /<name> argument-hint: '<hint>'`

**Step 4 — Cycle detection (Check 24c)**:

Build directed graph from (source-file, skill-reference) pairs collected in Step 1. Walk all paths from each node; flag back-edges (skill A → skill B → … → skill A).

→ Any cycle found: **[high] 24c**: `Cycle: <A> → <B> → … → <A>` — document full cycle path; do not auto-fix; resolution requires removing or redirecting one chain edge.

**Report only** — no auto-fix; sequence intent requires human judgment.

| Sub-check | Severity | Auto-fix |
| --- | --- | --- |
| 24a — target skill not on disk | high | no |
| 24b — argument absent from argument-hint | medium | no |
| 24c — directed cycle in follow-up chain | high | no |

## Check 27 — Cross-plugin shared-file reference integrity

Plugin SKILL.md files (non-foundry plugins) must not contain `Read` calls or inline references to `.claude/skills/_shared/<file>` unless that exact file ships inside `plugins/foundry/skills/_shared/`. Path only available at runtime via `foundry:init` symlink — any file absent from foundry's `_shared/` = broken reference when foundry installed, entirely unreachable when not installed.

**Special antipattern — foundry-dependency catch-22**: when referenced file's purpose is to describe fallback behaviour for users without foundry (e.g. `agent-resolution.md` listing `general-purpose` substitutes), reference is **critical** — file explaining how to work without foundry is only accessible via foundry.

**Step 1 — Collect cross-plugin shared-file references**:

```bash
# Find all Read/include refs to .claude/skills/_shared/ in plugin SKILL.md files  # timeout: 5000
grep -rn '\.claude/skills/_shared/' plugins/*/skills/ 2>/dev/null | grep -v 'foundry'
```

For each match: record `(plugin, skill-file, referenced-filename)`.

**Step 2 — Verify file exists in foundry's \_shared/**:

```bash
ls plugins/foundry/skills/_shared/ 2>/dev/null  # timeout: 5000
```

For each referenced filename from Step 1: check if it appears in foundry `_shared/` listing.

- Present → reference valid at runtime (when foundry installed) — **no finding**
- Absent → **[high] 27a**: `<plugin>/<skill>: references .claude/skills/_shared/<file> which is absent from foundry/_shared/ — broken at all times`

**Step 3 — Catch-22 upgrade**:

For each file flagged in Step 2 (absent from foundry `_shared/`): inspect referenced filename and surrounding context for signals it provides fallback/degraded-mode behaviour (keywords: `fallback`, `without foundry`, `agent-resolution`, `general-purpose`, `not installed`).

- Match → upgrade to **[critical] 27b**: `<plugin>/<skill>: fallback file <name> is only reachable via foundry — catch-22`
- No match → keep as **[high] 27a**

**Step 4 — Plugin-local \_shared/ unmounted files**:

```bash
ls plugins/*/skills/_shared/ 2>/dev/null  # timeout: 5000
```

Plugin-local `_shared/` directories (e.g. `plugins/develop/skills/_shared/`) have **no install-time mount point** — invisible to model at runtime. Any file there that SKILL.md references is unreachable.

```bash
# For each plugin-local _shared/ file, check if any SKILL.md in that plugin references it  # timeout: 5000
for f in plugins/*/skills/_shared/*; do
    plugin=$(echo "$f" | cut -d/ -f2)
    fname=$(basename "$f")
    grep -rl "$fname" "plugins/$plugin/skills/" 2>/dev/null | grep 'SKILL\.md'
done
```

- Referenced and in plugin-local `_shared/` → **[medium] 27c**: `<plugin>/<skill>: references <file> from plugin-local _shared/ which is not mounted at runtime — move to foundry/_shared/ or inline`
- Exists in plugin-local `_shared/` but not referenced → **[low]**: unreachable dead file; suggest removal

**Report only** — no auto-fix; resolution requires deciding whether to inline content or move file to `foundry/_shared/`.

| Sub-check | Severity | Auto-fix |
| --- | --- | --- |
| 27a — file absent from foundry's \_shared/ | high | no |
| 27b — catch-22 (fallback file needs foundry to reach) | critical | no |
| 27c — plugin-local \_shared/ file referenced but not mounted | medium | no |

## Check 28 — Cross-plugin agent dispatch fallback

Skills dispatching agents via `Agent(subagent_type="<plugin>:<name>", ...)` depend on that plugin being installed. When dispatched agent belongs to different plugin from skill's own plugin, and no fallback declared for absent-plugin case, skill fails at runtime.

**Exempt**: `general-purpose` (built-in, always available); `codex:*` agents (conditional dispatch tracked by Check 7).

**Step 1 — Map skills to owning plugin:**

```bash
# Map each plugin skill file to its owning plugin  # timeout: 5000
for f in plugins/*/skills/*/SKILL.md; do
    plugin=$(echo "$f" | cut -d/ -f2)
    skill=$(echo "$f" | cut -d/ -f4)
    echo "$plugin $skill $f"
done
```

**Step 2 — Collect cross-plugin dispatches per skill:**

```bash
# Find all subagent_type values across plugin skill files  # timeout: 5000
grep -rn 'subagent_type' plugins/*/skills/*/SKILL.md 2>/dev/null | grep -v '^Binary'
```

For each match: extract `(skill_file, dispatched_plugin, dispatched_agent)`. Dispatch is **cross-plugin** when `dispatched_plugin ≠ owning_plugin`. Build map: `skill_file → [cross-plugin agents]`.

Skip: any `general-purpose` dispatch and any `codex:*` dispatch.

**Step 3 — Verify fallback coverage:**

For each skill with one or more cross-plugin dispatches, read skill file and search for fallback declaration. Valid fallback is any of:

- Section heading matching `Agent Resolution`, `Fallback`, or `Plugin Check` (case-insensitive)
- Sentence containing cross-plugin agent name AND word from `{fallback, not installed, substitute, general-purpose, unavailable}` within 5 lines of each other
- Conditional dispatch block: `if not installed` or `plugin list.*grep.*<plugin>` followed by alternative

No fallback found → **[high] 28a**: `<plugin>/<skill>: dispatches <cross-plugin-agent> with no fallback for missing plugin`

**Step 4 — Completeness check:**

For each skill where fallback section exists: verify every cross-plugin agent dispatched by that skill is named within fallback block (bare name OR fully-qualified `plugin:name` form). Agent covered when name appears in fallback block.

Partially covered → **[medium] 28b**: `<plugin>/<skill>: fallback section present but does not cover <agent>`

**Report only** — fixing requires adding Agent Resolution section with fallback substitutes for each cross-plugin dependency; pattern in `develop:plan` (Agent Resolution table with `foundry agent | Fallback | Model | Role description prefix`) is reference implementation.

> **Related**: Check 25 (in `checks-shared.md`) covers bare-name dispatch (missing plugin prefix). Check 25 and Check 28 address different failure modes — run both.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| 28a — no fallback for cross-plugin dispatch | high | no |
| 28b — fallback present but agent not covered | medium | no |

### Sub-check 28c — Cross-plugin prose references without availability guard

Skills may reference other plugins' skills in `<notes>`, follow-up chains, and prose documentation without runtime dispatch (no `Agent(subagent_type=...)` call). These prose references shown to users as runnable next-steps; if referenced plugin absent, command fails silently.

**Step — Scan for unguarded prose cross-plugin references**:

```bash
printf "=== Check 28c: Cross-plugin prose refs ===\n"
for f in plugins/*/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  skill_plugin=$(echo "$f" | cut -d/ -f2)
  # Find refs to other plugins in prose (backtick-wrapped /plugin:skill or /plugin:skill in plain text)
  matches=$(grep -nE '`/[a-z]+:[a-z]|/oss:|/develop:|/research:|/codemap:|/foundry:' "$f" 2>/dev/null |
    grep -v "subagent_type\|#.*requires\|requires.*plugin\|plugin.*installed\|if.*plugin" |
    grep -v "$(echo "$skill_plugin" | sed 's/[^a-z]//g'):" || true)
  if [ -n "$matches" ]; then
    echo "$matches" | while IFS= read -r line; do
      printf "⚠ 28c: %s — cross-plugin ref without availability guard: %s\n" "$f" "$line"
      printf "  fix: add '(requires <plugin> plugin)' inline, or wrap in availability check\n"
    done
  fi
done
printf "✓: Check 28c scan complete\n"  # timeout: 5000
```

Severity: **medium** — user sees broken command in follow-up gate or documentation prose.
Fix: append `(requires \`<plugin>\` plugin)` immediately after cross-plugin skill reference, or restructure as conditional.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| 28a — no fallback for cross-plugin dispatch | high | no |
| 28b — fallback present but agent not covered | medium | no |
| 28c — prose cross-plugin ref without availability guard | medium | no |

## Check 30 — Plugin skill bash operational correctness

Four static-grep patterns catching silent failures in skill SKILL.md bash blocks. Run across both `.claude/skills/` and `plugins/*/skills/` — bugs appear in any skill.

### 30a — Pipe exit code capture (PIPESTATUS)

```bash
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'
printf "=== Check 30a: Pipe exit code capture ===\n"
# Find | tail or | head followed by $? assignment within 3 lines — tail/head always exit 0
grep -rn '| tail\b\|| head\b' plugins/*/skills/ .claude/skills/ 2>/dev/null |
  grep -v 'PIPESTATUS\|pipefail\|#.*tail\|#.*head' |
  grep -v '^Binary' &&
printf "  ${CYN}hint${NC}: use \${PIPESTATUS[0]} or set -o pipefail; \$? captures tail/head exit (always 0)\n" || true
printf "${GRN}✓${NC}: Check 30a scan complete\n"  # timeout: 5000
```

Severity: **critical** — gate commands appear to pass on genuine failure; `$?` after `cmd | tail -N` = tail's exit code (0), not cmd's.

Fix pattern: `cmd 2>&1 | tail -N; EXIT=${PIPESTATUS[0]}`

### 30b — SKIP variable guard missing

```bash
printf "=== Check 30b: SKIP variable guard ===\n"
# Find SKIP_X=1 detection lines; check whether subsequent runner commands have a guard
grep -rn 'SKIP_[A-Z_]*=1' plugins/*/skills/ .claude/skills/ 2>/dev/null |
  grep -v '^Binary' | grep -v '#' | while IFS= read -r match; do
    file=$(echo "$match" | cut -d: -f1)
    # Check if any guard exists in same file
    grep -q '\[ "\${SKIP_' "$file" 2>/dev/null ||
      printf "${YEL}⚠ SKIP guard missing${NC}: %s — SKIP variable set but no conditional guard found\n" "$file"
done
printf "${GRN}✓${NC}: Check 30b scan complete\n"  # timeout: 5000
```

Severity: **critical** — `SKIP_RUFF=1` set by tool detection, but `$RUNNER ruff check` runs unconditionally; detection is cosmetic.

Fix pattern: `[ "${SKIP_RUFF:-0}" -ne 1 ] && $RUNNER ruff check ...`

### 30c — Agent filename convention mismatch (model reasoning)

Cannot be caught by grep alone — requires reading spawn prompt and consolidator read pattern in same file.

Flag when skill file:
1. Spawns agents with prompt instructing them to write findings to file named with plugin-prefixed format (e.g. `foundry:sw-engineer.md`)
2. AND consolidator reads files using bare-name format (e.g. `sw-engineer.md`)

These never match → all agent findings silently dropped.

Severity: **high**

Fix: standardize to bare agent name in both spawn prompt and consolidator read pattern (e.g. `sw-engineer.md`).

### 30d — TEST_CMD used with pytest-specific flags without PYTEST_CMD split

```bash
printf "=== Check 30d: TEST_CMD/PYTEST_CMD split ===\n"
grep -rn '\$TEST_CMD.*--tb\b\|\$TEST_CMD.*--co\b\|\$TEST_CMD.*::\|\$TEST_CMD.*--cov\b\|\$TEST_CMD.*--doctest' \
  plugins/*/skills/ .claude/skills/ 2>/dev/null |
  grep -v 'PYTEST_CMD\|#' | grep -v '^Binary' &&
printf "  ${CYN}hint${NC}: derive PYTEST_CMD for pytest-specific flags; TEST_CMD=tox or make won't accept --tb/--co/::/--cov\n" || true
printf "${GRN}✓${NC}: Check 30d scan complete\n"  # timeout: 5000
```

Severity: **high** — skill fails silently on tox/make projects when pytest-specific flags appended to TEST_CMD.

Fix: after detecting TEST_CMD, derive `PYTEST_CMD` for targeted runs: `tox` → `PYTEST_CMD="uv run pytest"`; `make test` → `PYTEST_CMD="uv run pytest"`.

**Report only** — no auto-fix; resolution requires understanding each skill's runner detection block.

### 30e — Heredoc python in skill bodies

Heredoc python blocks (`python3 << 'EOF'`) banned by CLAUDE.md. Distinct from 23e (targets `python3 -c` one-liners); 30e catches multi-line heredoc forms that bypass one-liner size limit.

```bash
printf "=== Check 30e: Heredoc python ===\n"
grep -rn "python3 <<\|python3 << '" plugins/*/skills/ .claude/skills/ 2>/dev/null |
  grep -v '^Binary' | grep -v '^\s*#' &&
printf "  hint: CLAUDE.md bans python3 heredoc; use bin/*.py script instead\n" || true
printf "✓: Check 30e scan complete\n"  # timeout: 5000
```

Severity: **high** — heredoc triggers permission prompt; user deny = workflow block; violates CLAUDE.md §Pre-Authorized Operations.

| Sub-check | Pattern | Severity | Auto-fix |
| --- | --- | --- | --- |
| 30a — pipe exit code | `\ | tail` / `\ | head` without PIPESTATUS | critical | no |
| 30b — SKIP guard missing | `SKIP_X=1` with no `[ "${SKIP_X:-0}" ]` guard | critical | no |
| 30c — filename mismatch | spawn filename ≠ consolidator filename (model reasoning) | high | no |
| 30d — TEST_CMD+pytest flags | `$TEST_CMD --tb` / `--co` / `::` / `--cov` without PYTEST_CMD | high | no |
| 30e — heredoc python | `python3 <<` in skill body | high | no |

## Check 31 — Skill tool call vs allowed-tools consistency

For each SKILL.md, verify every **gating or dispatch tool** called in workflow body is declared in `allowed-tools:` frontmatter. Runtime enforces `allowed-tools` — undeclared tool calls blocked silently; entire workflow phase fails with no error message.

**High-risk tools** (absence breaks entire workflow phases, not just individual steps):

| Tool | Consequence if absent from `allowed-tools` |
| --- | --- |
| `Skill` | Follow-up gate never dispatches target skill; user's selection silently dropped |
| `AskUserQuestion` | Skill falls back to prose questions (violates communication.md; interactive gates broken) |
| `Agent` | Sub-agent spawns blocked; orchestration phase fails silently |

```bash
RED='\033[1;31m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'

found=0
for f in plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md; do  # timeout: 5000
    [ -f "$f" ] || continue
    skill_name=$(basename "$(dirname "$f")")
    allowed=$(awk '/^---$/{c++} c==1{print} c==2{exit}' "$f" 2>/dev/null | grep '^allowed-tools:' | sed 's/allowed-tools:[[:space:]]*//')
    [ -z "$allowed" ] && continue
    body=$(awk '/^---$/{c++} c>=2{print}' "$f" 2>/dev/null)
    for tool in Skill AskUserQuestion Agent; do
        if echo "$body" | grep -qE "\b${tool}\(" 2>/dev/null; then
            if ! echo "$allowed" | grep -qw "$tool"; then
                printf "${RED}! BREAKING${NC} skills/%s: body calls %s() but '%s' absent from allowed-tools\n" "$skill_name" "$tool" "$tool"
                printf "  ${CYN}fix${NC}: add '%s' to allowed-tools: in %s\n" "$tool" "$f"
                found=1
            fi
        fi
    done
done
[ "$found" -eq 0 ] && printf "${GRN}✓${NC}: Check 31 — all gating tool calls covered by allowed-tools\n"  # timeout: 5000
```

Severity: **critical** — blocked gating tool = entire workflow phase silently broken at runtime.

Auto-fix: append missing tool name to `allowed-tools:` frontmatter line.

| Sub-check | Condition | Severity | Auto-fix |
| --- | --- | --- | --- |
| 31 — tool-body mismatch | body calls `Skill()`, `AskUserQuestion()`, or `Agent()` but tool absent from `allowed-tools` | critical | yes — add to frontmatter |

### Sub-check 31b — Skill frontmatter completeness

Verify required frontmatter fields present in every SKILL.md. Missing fields cause undocumented default behavior or miscategorized routing.

```bash
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'
printf "=== Check 31b: Frontmatter completeness ===\n"
found=0
for f in plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md; do  # timeout: 5000
    [ -f "$f" ] || continue
    skill=$(basename "$(dirname "$f")")
    fm=$(awk '/^---$/{c++} c==1{print} c==2{exit}' "$f" 2>/dev/null)
    # effort: — required always; no documented default
    echo "$fm" | grep -q '^effort:' || {
        printf "${YEL}⚠${NC} 31b: %s — missing effort: field (required; no default)\n" "$skill"
        found=1
    }
    # when_to_use: — required when disable-model-invocation absent (routing signal)
    has_dmi=$(echo "$fm" | grep -c 'disable-model-invocation: true' || true)
    has_wtu=$(echo "$fm" | grep -c '^when_to_use:' || true)
    [ "$has_dmi" -eq 0 ] && [ "$has_wtu" -eq 0 ] && {
        printf "${YEL}⚠${NC} 31b: %s — missing when_to_use: (needed when auto-invocation allowed)\n" "$skill"
        found=1
    }
done
[ "$found" -eq 0 ] && printf "${GRN}✓${NC}: Check 31b — frontmatter complete across all skills\n"
```

Severity: **medium** for `effort:` (no default documented); **low** for `when_to_use:` (routing impact).

| Sub-check | Field | Condition | Severity | Auto-fix |
| --- | --- | --- | --- | --- |
| 31 — tool-body mismatch | `allowed-tools` | body calls Skill/AskUserQuestion/Agent, not in frontmatter | critical | yes |
| 31b — effort missing | `effort:` | always required | medium | yes |
| 31b — when_to_use missing | `when_to_use:` | no `disable-model-invocation: true` | low | no |

## Check C35 — Background agent health monitoring compliance (CLAUDE.md §8)

CLAUDE.md §8 requires every skill spawning background agents to implement: (1) launch sentinel creation, (2) 5-min file-activity poll, (3) 15-min hard cutoff. Absence = stalled agents silently drop findings.

**Step 1 — Find skills with background agent spawns**:

```bash
printf "=== Check C35: Background agent health monitoring ===\n"
BG_SKILLS=$(grep -rl 'run_in_background.*true\|run_in_background=true' plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null)
if [ -z "$BG_SKILLS" ]; then
    printf "✓: No background agent spawns found — C35 N/A\n"
fi  # timeout: 5000
```

**Step 2 — For each skill found, verify §8 protocol elements**:

```bash
for f in $BG_SKILLS; do  # timeout: 5000
    skill=$(basename "$(dirname "$f")")
    # Check for _shared/agent-spawn-protocol.md reference (preferred) OR inline §8 elements
    if grep -q 'agent-spawn-protocol' "$f" 2>/dev/null; then
        printf "✓ C35: %s — references agent-spawn-protocol.md\n" "$skill"
        continue
    fi
    # Fallback: check for inline §8 elements
    has_sentinel=$(grep -c 'LAUNCH_AT\|touch /tmp/' "$f" 2>/dev/null || echo 0)
    has_poll=$(grep -c 'find.*-newer.*-type f.*wc -l\|MONITOR_INTERVAL' "$f" 2>/dev/null || echo 0)
    has_cutoff=$(grep -c 'HARD_CUTOFF\|timed.out\|15 min\|900' "$f" 2>/dev/null || echo 0)
    [ "$has_sentinel" -eq 0 ] && printf "⚠ C35a: %s — no launch sentinel (CLAUDE.md §8 step 1)\n" "$skill"
    [ "$has_poll" -eq 0 ]    && printf "⚠ C35b: %s — no 5-min file-activity poll (§8 step 2)\n" "$skill"
    [ "$has_cutoff" -eq 0 ]  && printf "⚠ C35c: %s — no 15-min hard cutoff (§8 step 3)\n" "$skill"
done
```

Severity: **high** for C35a/b/c — stalled background agents drop findings with no user-visible signal.
Fix: reference `$_FOUNDRY_SHARED/agent-spawn-protocol.md` (preferred once file exists) or inline all three §8 elements in skill.

| Sub-check | Pattern | Severity | Auto-fix |
| --- | --- | --- | --- |
| C35a — no launch sentinel | no `touch /tmp/<sentinel>` after background spawn | high | no |
| C35b — no file-activity poll | no 5-min `find -newer` loop | high | no |
| C35c — no hard cutoff | no `HARD_CUTOFF` / 15-min signal | high | no |
