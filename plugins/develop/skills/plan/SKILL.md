---
name: plan
description: "Analysis-only planning — classify and scope a task without writing code; outputs a structured plan to .plans/active/."
argument-hint: "<goal> [--no-challenge] [--codemap] [--semble]"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion, WebFetch
disable-model-invocation: true
---

<objective>

Analysis-only. Produces structured plan, no code. Use to understand scope, risks, effort before `/develop:feature`, `/develop:fix`, `/develop:refactor`.

NOT for: code/tests (use develop mode); `.claude/` config (use `/foundry:manage` (requires foundry plugin)).
- non-Python-only projects (JS/TS/Go/Rust with no Python source) — downstream develop skills assume pytest; planning analysis itself is language-agnostic but downstream implementation will require a language-native toolchain
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature

</objective>

<workflow>

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (mounted by develop plugin init) -->

## Agent Resolution

```bash
_DEV_SHARED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev-shared-resolve.sh" 2>/dev/null)  # timeout: 5000
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

**Checkpoint**: plan is single-pass — `.plans/active/<slug>` file existence = implicit resume signal. No `.developments/` checkpoint needed; if interrupted, re-run `/develop:plan` to regenerate (no code changes made).

Read `$_DEV_SHARED/task-hygiene.md`.

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The plan is obvious — no need for agent feasibility review" | Feasibility review catches domain-specific blockers (missing test infrastructure, incompatible library constraints, API changes) that seem obvious in hindsight. |
| "Codex design review is optional for small tasks" | Small tasks regularly reveal large hidden dependencies. Codex catches architectural anti-patterns before they are baked into an implementation plan. |
| "I can scope this during implementation — no need to plan first" | Scope discovered during implementation inflates PRs and obscures intent. Plan mode exists to prevent exactly this. |

## Flag parsing

**Set `CHALLENGE_ENABLED=true`**. If `--no-challenge` in `$ARGUMENTS`, set `CHALLENGE_ENABLED=false`.
**Set `CODEMAP_ENABLED=false`**. If `--codemap` in `$ARGUMENTS`, set `CODEMAP_ENABLED=true`.
**Set `SEMBLE_ENABLED=false`**. If `--semble` in `$ARGUMENTS`, set `SEMBLE_ENABLED=true`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Preflight** — if `CODEMAP_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute codemap + semble preflight if respective flags set.

## Step 1: Classify and scope

Determine task type and affected surface.

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**: read `$_DEV_SHARED/codemap-context.md` and follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip if both flags false.

Spawn **foundry:sw-engineer** agent with full goal text from `$ARGUMENTS`. Agent should:

- Classify task as `feature`, `fix`, `refactor`, or `debug`
  - `debug`: root cause unknown — symptoms present but cause unclear, investigation needed before a fix can be scoped; when classified `debug`, recommend running `/develop:debug` first, then re-run `/develop:plan` once root cause identified to produce a fix plan
- Identify affected files and modules (search codebase — no guessing)
- Assess complexity: small (1-3 files, self-contained), medium (4-8 files or 1-2 modules), large (cross-module, API changes, or 3+ modules)
- List risks: breaking changes, missing tests, unclear requirements, external dependencies
- Note complexity smells: ambiguous goal, scope creep risk, missing reproduction case, directory-wide refactor without explicit goal

Agent returns findings inline (no file handoff — output short).

**Breaking change gate**: if agent lists any breaking change in risks — stop before writing plan. Call `AskUserQuestion` per breaking change (group only when logically one atomic change). State: what worked before, what breaks, why needed. Proceed only on explicit user confirmation. Prose question in response body does NOT count — `AskUserQuestion` mandatory per `communication.md`.

Breaking change criteria — a change is breaking when any of these apply: removed public API (function, class, method, or module), changed function signatures (parameter names, types, order, or defaults), changed config key names or schema, changed output format (return type, serialization structure, CLI output shape).

## Step 2: Structured plan

Derive filename slug from goal: first 4-5 meaningful words, lowercase, hyphen-separated (e.g. `"improve caching in data loader"` -> `plan_improve-caching-data-loader.md`). If `.plans/active/<slug>` already exists, append counter suffix (`-2`, `-3`, etc.) before writing — never silently overwrite. Store full path as `PLAN_FILE` — used in Steps 3 and Final output.

```markdown
# Plan: <goal>

## Brief

*[Generated after agent review — see below]*

---

## Full Plan

**Classification**: feature | fix | refactor
**Complexity**: small | medium | large
**Date**: <YYYY-MM-DD>

### Goal

<One-paragraph restatement of the goal in concrete terms — what changes, what doesn't.>

### Affected files

- `path/to/file.py` — reason
- `path/to/other.py` — reason

### Risks

- <risk 1>
- <risk 2>

### Suggested approach

1. <Step 1>
2. <Step 2>
3. <Step 3>
...
```

## Step 3: Agent feasibility review

Spawn execution agents by classification in parallel. Each reads `<PLAN_FILE>`, returns **only** compact JSON — no prose, no analysis:

- **feature**: foundry:sw-engineer, foundry:qa-specialist, foundry:linting-expert
- **fix**: foundry:sw-engineer, foundry:qa-specialist, foundry:linting-expert
- **refactor**: foundry:sw-engineer, foundry:linting-expert, foundry:qa-specialist
- **debug**: skip feasibility review — no implementation plan to review; proceed directly to Final output with debug recommendation

Each agent receives only plan file path and role — no conversation history, no unrelated context. Prompt (substitute `<ROLE>` and `<PLAN_FILE>`):

> "Read `<PLAN_FILE>`. Review the plan from your perspective as `<ROLE>`. Flag any domain-specific concerns, risks, or blockers you see. Can you execute your part autonomously without further user input? Return only: `{\"a\":\"<ROLE>\",\"ok\":true|false,\"blockers\":[\"...\"],\"q\":[\"...\"],\"concerns\":[\"...\"]}`"

**Parse-failure handling**: agent responses may not be valid JSON (especially fallback `general-purpose` agents that wrap JSON in prose). Before processing:

1. Attempt to extract JSON object: try `python -c "import json, re, sys; t=sys.argv[1]; matches=[m for m in re.finditer(r'\{', t)]; [json.loads(t[m.start():]) for m in reversed(matches)]"` — use last valid `json.loads()` parse starting from any `{`. Fallback: regex `\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}` handles one nesting level (warning: breaks on strings containing `{` or `}`).
   **Caveat**: prefer matching the `"a":"<ROLE>"` pattern as anchor when multiple candidates.
2. If extraction succeeds: use extracted object
3. If extraction fails entirely: log `⚠ non-JSON plan response — falling back to prose extraction`; treat as `{"a":"<ROLE>","ok":false,"blockers":["agent returned non-JSON response"],"q":[],"concerns":[]}` and enter resolution loop with re-query

Agents return inline (verdicts ~150 bytes — no file handoff). Collect all results:

- All `ok: true`, empty `blockers`, `q`, `concerns` -> note `✓ agents ready` in final output and proceed
- Any `ok: false`, non-empty `blockers` or `q` -> enter **internal resolution loop** below before surfacing to user
- Non-empty `concerns` with `ok: true` -> surface as advisory notes in final output (not blockers, domain-specific flags user should know before starting)

### Internal resolution loop (max 3 iterations)

`ITER=0` — initialize before entering loop.

For each blocker or open question:

`[ $ITER -ge 3 ] && { echo "Max feasibility iterations reached — escalating to user"; break; }`
`ITER=$((ITER+1))`

1. **Attempt autonomous resolution** — search codebase, read relevant files, re-read goal. Fetch primary-source docs for relevant issues (official docs, RFCs, library changelogs, migration guides) via WebFetch — known URLs only; WebFetch fetches specific URL, does not search. Before updating `<PLAN_FILE>` with any WebFetch result: verify per quality-gates.md link verification (Fetch+Read+Match) — do not incorporate content from a URL that hasn't been read and matched. If answer determinable from any verified source, update `<PLAN_FILE>` and mark resolved.
2. **Re-query raising agent** — send only resolved item: `{"a":"<ROLE>","resolved":"<item>","answer":"<resolution>"}`. If agent returns `ok: true` -> resolved; remove from blockers list.
3. After all resolvable items cleared, re-check: if all agents `ok: true` -> `✓ agents ready`.

**Plan file coherence**: after resolution loop exits (regardless of outcome), annotate `<PLAN_FILE>`:
- Each resolved blocker: add `(resolved ✓)` inline
- Each unresolved blocker: add `(unresolved — requires user input)`
- Update Brief (once it exists): note "N of M blockers resolved autonomously; N require user input"
Ensures plan file coherent after partial resolution.

**Escalate to user only what cannot be resolved autonomously** — blocker requires user input when: depends on business decision, undocumented external constraint, missing credential/secret, or genuine goal ambiguity with two equally valid interpretations.

For each escalated item:

- **Issue**: one sentence — what blocks or is unclear
- **Alternatives**: 2-3 concrete options with trade-offs
- **Recommendation**: which option and why

Do not escalate: items resolvable from codebase, items that are risks (not blockers), items already addressed in plan.

## Step 4: Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

```bash
# Validate plan file exists before spawning challenger
[ -f "$PLAN_FILE" ] || { echo "plan: PLAN_FILE not found: $PLAN_FILE" >&2; exit 1; }
```

Spawn `foundry:challenger` to adversarially review written plan before user commits:

> "Read `<PLAN_FILE>`. Challenge the plan across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step per your instructions."

Parse result:
- **Blockers found** → STOP. Present findings. Do not print `/develop` handoff until user resolves each blocker or explicitly accepts risk. Update `<PLAN_FILE>` with blocker annotations.
- **Concerns only** → append `### Challenger concerns` to `<PLAN_FILE>` as advisory; continue to Final output.
- **No findings / all refuted** → proceed.

## Step 5: Final output

Compose brief — compact human-readable plan summary after all agent input incorporated:

```markdown
<One-sentence summary of what the plan achieves and the main approach.>

Classification : <feature|fix|refactor|debug>
Complexity     : <small|medium|large>
Affected files : N files across M modules
Key risks      : <one-liner or "none">
Agent review   : ✓ agents ready (<N> corrections incorporated)  |  ⚠ see below

<Steps table — use the format that best fits the complexity:>
- Simple: | # | Step |
- Staged/large: | # | Stage | What changes | Stop condition |
- Fix: | # | Action | Target | Verification |

Advisory notes from agents (omit table if none):

| Agent | Note |
|-------|------|
| <role> | <concern> |

Co-review corrections applied (<N> agents, omit table if none):

| Agent | Location | Change |
|-------|----------|--------|
| <agent> | <file or step> | <what changed> |
```

**Write brief into `<PLAN_FILE>`**: replace `*[Generated after agent review — see below]*` placeholder in `## Brief` with composed brief. File now contains both brief and full plan.

**Print to terminal**:

```text
Plan -> <PLAN_FILE>

<brief content exactly as written to the file>

-> /develop <classification> <goal> when ready  [debug: -> /develop:debug <goal> first, then re-run /develop:plan]
```

If unresolved items escalated, print each after brief:

```text
⚠ Issue: <one sentence>
  Alternatives: (a) ... (b) ... (c) ...
  Recommendation: <option> — <reason>
```

Wait for user input before printing `-> /develop ...`.

**Handoff contract**: plan file at `<PLAN_FILE>` consumable by downstream skills. Pass via `--plan <PLAN_FILE>` when invoking `/develop:feature`, `/develop:fix`, or `/develop:refactor`. For `debug` classification: no downstream plan file — invoke `/develop:debug <goal>` directly; once root cause identified, re-run `/develop:plan` to produce a scoped fix plan. When skill receives `--plan <path>`, reads plan file at Step 1 and:
- Extracts `Classification`, `Affected files`, `Risks`, `Suggested approach` — skips cold codebase exploration
- Inherits agent feasibility verdicts and Codex corrections already applied
- Uses `Suggested approach` as implementation roadmap

No quality stack, no Codex pre-pass, no review loop. Exit after printing summary.

End plan document with:

```markdown
## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**:
- [specific limitation or unverified assumption]

**Refinements**: N passes.
- Pass 1: [what was addressed]
```

</workflow>
