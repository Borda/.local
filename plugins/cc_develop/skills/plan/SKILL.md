---
name: plan
description: "Analysis-only planning — classify and scope a task without writing code; outputs a structured plan to .plans/active/. TRIGGER when: user wants to understand scope and risks before implementation; phrases: \"plan this\", \"scope out X\", \"what would it take to Y\", \"analyse before we start\". SKIP when: user already knows what to build and wants code immediately (use `/develop:feature` or `/develop:fix` directly); `.claude/` config planning (use `/foundry:manage`)."
argument-hint: "<goal> [--no-challenge] [--codemap] [--no-codemap] [--semble] [--max-depth <N>]"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion, WebFetch
disable-model-invocation: true
---

<objective>

Analysis-only. Produces structured plan, no code. Use to understand scope, risks, effort before `/develop:feature`, `/develop:fix`, `/develop:refactor`.

NOT for: code/tests (use develop mode); `.claude/` config (use `/foundry:manage` (requires foundry plugin)).
- non-Python-only projects (JS/TS/Go/Rust with no Python source) — downstream develop skills assume pytest; planning analysis language-agnostic but downstream implementation needs language-native toolchain
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature

</objective>

<workflow>

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (resolved via dev_shared_resolve.py and explicitly Read in workflow) -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
cat "$_DEV_SHARED/agent-resolution.md"
```

Contains: foundry check + fallback table. If foundry not installed: substitute each `foundry:X` with `general-purpose` per table. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:challenger`.

**Checkpoint**: plan single-pass — `.plans/active/<slug>` file existence = implicit resume signal. No `.developments/` checkpoint needed; if interrupted, re-run `/develop:plan` to regenerate (no code changes made).

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/task-hygiene.md"
```

## Flag parsing

Parse flags into shell variables (not prose) so downstream blocks see correct values. Persist to **per-invocation namespaced** temp dir for cross-block access (bash state lost between Bash() calls). Namespace by PID to prevent collision when two `/develop:plan` invocations run concurrently:

```bash
# timeout: 5000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS="${TMPDIR:-/tmp}/dev-plan-$$-${CSID}"
mkdir -p "$PLAN_NS"
echo "$PLAN_NS" > "${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID}"  # downstream blocks read back namespace
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_parse_args.py" --skill plan --write-files "$ARGUMENTS"
# values written to ${TMPDIR:-/tmp}/dev-plan-<flag>-${CSID} (legacy paths: see SKILL_SPECS["plan"])
cp "${TMPDIR:-/tmp}/dev-challenge-enabled-${CSID}"  "$PLAN_NS/challenge-enabled" 2>/dev/null || echo "true"  > "$PLAN_NS/challenge-enabled"
cp "${TMPDIR:-/tmp}/dev-codemap-raw-${CSID}"        "$PLAN_NS/codemap-raw"       2>/dev/null || echo "auto"  > "$PLAN_NS/codemap-raw"
cp "${TMPDIR:-/tmp}/dev-semble-enabled-${CSID}"     "$PLAN_NS/semble-enabled"    2>/dev/null || echo "false" > "$PLAN_NS/semble-enabled"
cp "${TMPDIR:-/tmp}/dev-plan-max-depth-${CSID}"     "$PLAN_NS/max-depth"         2>/dev/null || echo "3"     > "$PLAN_NS/max-depth"
```

Downstream blocks recover namespace then read back, e.g. `PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null); CODEMAP_ENABLED=$(cat "$PLAN_NS/codemap-enabled" 2>/dev/null || echo false)`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--semble\`, \`--max-depth\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Codemap auto-detection** — normalize `CODEMAP_RAW` to `true`/`false`; strict mode hard-fails when codemap unavailable:

```bash
# timeout: 5000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
[ -n "$PLAN_NS" ] || { echo "! PLAN_NS empty — dev-plan-ns-current not found; re-run /develop:plan"; exit 1; }
CODEMAP_RAW=$(cat "$PLAN_NS/codemap-raw" 2>/dev/null || echo auto)
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/codemap-resolve" "$CODEMAP_RAW")
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    if [ "$CODEMAP_RAW" = "strict" ]; then
        echo "! BLOCKED — codemap unavailable but --codemap (strict) passed; run /codemap:scan-codebase or install codemap plugin"
        exit 1
    fi
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED" > "$PLAN_NS/codemap-enabled"
```

> loads: codemap-gates.md

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-gates.md"
```
Follow Gate A and Gate B.

**Preflight** — if `SEMBLE_ENABLED=true`:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/preflight-helpers.md"
```
Execute semble preflight. Codemap validation handled by auto-detect block above.

## Step 1: Classify and scope

Determine task type and affected surface.

**Codemap target derivation** — when goal names explicit target as `module.path` or `module.path::function`, pre-set `TARGET_MODULE`/`TARGET_FN` so `codemap-context.md` runs caller-impact queries (`rdeps`, `fn-rdeps`) instead of only `central` baseline. Goal with no explicit target → both empty → only `central` runs (correct: affected surface unknown until agent searches):

```bash
# timeout: 5000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
if [[ "$ARGUMENTS" == *"::"* ]]; then
    _QNAME=$(printf '%s\n' "$ARGUMENTS" | grep -oE '[A-Za-z_][A-Za-z0-9_.]*::[A-Za-z_][A-Za-z0-9_]*' | head -1)
    TARGET_MODULE="${_QNAME%%::*}"
    TARGET_FN="${_QNAME##*::}"               # bare fn — codemap-context.md builds module::fn
elif [[ "$ARGUMENTS" =~ ([A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+) ]]; then
    TARGET_MODULE="${BASH_REMATCH[1]}"       # dotted module target
    TARGET_FN=""
else
    TARGET_MODULE=""
    TARGET_FN=""
fi
export TARGET_MODULE TARGET_FN
echo "$TARGET_MODULE" > "$PLAN_NS/target-module"   # persist — bash state lost between Bash() calls
echo "$TARGET_FN"     > "$PLAN_NS/target-fn"
```

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-context.md"
```
Follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip if both flags false.

**Effort sizing (codemap)** — when `CODEMAP_ENABLED=true`, derive blast-radius tier table from reverse dependencies so complexity estimate structural, not guessed. Degrade silently when codemap absent — plan works unchanged, sizing falls back to agent's file-count heuristic. Run Extended scan (`--source=diff` when partial diff exists, e.g. re-planning after abandoned work; otherwise per-target `rdeps` when `TARGET_MODULE` known):

```bash
# timeout: 15000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
CODEMAP_ENABLED=$(cat "$PLAN_NS/codemap-enabled" 2>/dev/null || echo false)
TARGET_MODULE=$(cat "$PLAN_NS/target-module" 2>/dev/null || echo "")
if [ "$CODEMAP_ENABLED" = "true" ] && command -v scan-query >/dev/null 2>&1; then
    if [ -n "$(git diff HEAD --name-only 2>/dev/null | grep '\.py$')" ]; then
        python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/codemap_scan.py" --source=diff > "$PLAN_NS/sizing-rdeps" 2>/dev/null || true
    elif [ -n "$TARGET_MODULE" ]; then
        scan-query --timeout 5 rdeps "$TARGET_MODULE" --top 10 --exclude-tests > "$PLAN_NS/sizing-rdeps" 2>/dev/null || true
        scan-query --timeout 5 coupled --top 10 >> "$PLAN_NS/sizing-rdeps" 2>/dev/null || true
    fi
fi
```

> Interpret `$PLAN_NS/sizing-rdeps` (skip when empty — codemap absent or no target): each `rdeps` block's caller count sets per-module blast tier; `coupled` output lists co-change pairs. Tiers match develop's convention:
> - `>= 5` rdeps → **HIGH** blast radius — cross-module reach; nudges complexity toward `large` and adds a Risks entry
> - `1–4` rdeps → **MODERATE** — note affected importers in plan
> - `0` rdeps → **LOW** — self-contained; proceed
>
> Fold highest tier across affected modules into complexity assessment below (HIGH tier or ≥3 affected modules → `large`), and pass tier table + coupled pairs to sw-engineer spawn as `## Structural blast radius` block so scope estimate accounts for downstream callers rather than file count alone.

Spawn **foundry:sw-engineer** agent with full goal text from `$ARGUMENTS`. Agent should:

- Classify task as `feature`, `fix`, `refactor`, or `debug`
  - `debug`: root cause unknown — symptoms present but cause unclear, investigation needed before fix scoped; when classified `debug`, recommend running `/develop:debug` first, then re-run `/develop:plan` once root cause identified to produce fix plan
  - **WARNING**: debug classification triggers `/develop:debug` which can re-invoke `/develop:plan` — caller tracks dispatch depth to prevent infinite loop via shared checkpoint file (not a CLI flag — `/develop:debug` does not accept `--max-depth`). Max depth = `$MAX_DEPTH` (default 3, CLAUDE.md safety break). Before invoking `/develop:debug`, execute depth-checkpoint bash block below:

```bash
# anti-loop guard  # timeout: 3000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
MAX_DEPTH=$(cat "$PLAN_NS/max-depth" 2>/dev/null || echo 3)
DEPTH_FILE="${TMPDIR:-/tmp}/dev-plan-depth-checkpoint-${CSID}"
CURRENT_DEPTH=$(cat "$DEPTH_FILE" 2>/dev/null || echo "$MAX_DEPTH")
if [ "$CURRENT_DEPTH" -le 0 ]; then
    echo "! depth limit ($MAX_DEPTH) reached — stopping plan→debug→plan loop"
    # don't invoke /develop:debug — proceed to AskUserQuestion below
else
    NEXT_DEPTH=$(( CURRENT_DEPTH - 1 ))
    echo "$NEXT_DEPTH" > "$DEPTH_FILE"
    echo "→ invoking /develop:debug (depth remaining: $NEXT_DEPTH)"
fi
```

At depth 0: stop, report current plan state, invoke `AskUserQuestion` — (a) Accept plan as-is · (b) Re-scope with reduced depth requirement.
- Identify affected files and modules (search codebase — no guessing)
- Assess complexity: small (1-3 files, self-contained), medium (4-8 files or 1-2 modules), large (cross-module, API changes, or 3+ modules). When effort-sizing block produced tier table, let structural reach override file count: any **HIGH** blast module (≥5 rdeps) or ≥3 affected modules → `large`, regardless of raw file count.
- Return **two separate** structured fields (not merged into flat risks list):
  - `breaking_changes`: list of changes affecting **public API only** — see criteria below; empty list when none
  - `risks`: non-breaking concerns (missing tests, unclear requirements, external dependencies, internal coupling); when effort-sizing tier table flags HIGH/MODERATE modules or coupled pairs, add each as concrete risk (e.g. "changing `<mod>` reaches N downstream callers", "`<a>`/`<b>` co-change coupling")
- Note complexity smells: ambiguous goal, scope creep risk, missing reproduction case, directory-wide refactor without explicit goal

Agent returns findings inline (no file handoff — output short).

**Breaking change gate**: gate triggers only when `breaking_changes` non-empty — items in `risks` do NOT trigger this gate. Stop before writing plan. Call `AskUserQuestion` per breaking change (group only when logically one atomic change). State: what worked before, what breaks, why needed. Options: (a) **Accept breaking change** — proceed with plan as-is · (b) **Revise to non-breaking** — return to Step 1 with constraint to avoid this breaking change · (c) **Abort** — stop immediately. Proceed only on explicit user selection of (a). Prose question in response body does NOT count — `AskUserQuestion` mandatory per `communication.md`. If user selects (b) or (c): stop immediately — do not proceed to Step 2 or subsequent steps.

Breaking change criteria — change is breaking when it affects **public API** (exported from `__init__.py`, documented in README, or stable interface used by external consumers) and any of these apply: removed public API (function, class, method, or module), changed function signatures (parameter names, types, order, or defaults), changed config key names or schema, changed output format (return type, serialization structure, CLI output shape). Internal/private signature changes (functions prefixed `_`, classes not exported) do NOT count as breaking — list under `risks` instead.

## Step 2: Structured plan

Derive filename slug from goal: first 4-5 meaningful words, lowercase, hyphen-separated (e.g. `"improve caching in data loader"` -> `plan_improve-caching-data-loader.md`). If `.plans/active/<slug>` already exists, append counter suffix (`-2`, `-3`, etc.) before writing — never silently overwrite. Store full path as `PLAN_FILE` — used in Steps 3 and Final output.

```bash
# persist — bash state lost between Bash() calls  # timeout: 3000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
echo "$PLAN_FILE" > "$PLAN_NS/plan-file"
```

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

<One-paragraph restatement of goal in concrete terms — what changes, what doesn't.>

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

- **feature**: foundry:sw-engineer, foundry:qa-specialist
- **fix**: foundry:sw-engineer, foundry:qa-specialist
- **refactor**: foundry:sw-engineer, foundry:qa-specialist
- **debug**: skip feasibility review — no implementation plan to review; proceed directly to Final output with debug recommendation

> `foundry:linting-expert` intentionally excluded — its role post-implementation static analysis (ruff/mypy), not pre-plan architectural feasibility. Including it produces noise (trivial `ok: true`) or false blockers on linting-config concerns. Surface lint-specific notes (e.g. "target module has no type annotations — mypy will flag everything") in Final output advisory notes section instead.

Each agent receives only plan file path and role — no conversation history, no unrelated context. Prompt (substitute `<ROLE>` and `<PLAN_FILE>`):

> "Read `<PLAN_FILE>`. Review plan from your perspective as `<ROLE>`. Flag domain-specific concerns, risks, or blockers you see. Can you execute your part autonomously without further user input? Return only: `{\"a\":\"<ROLE>\",\"ok\":true|false,\"blockers\":[\"...\"],\"q\":[\"...\"],\"concerns\":[\"...\"]}`"

**Parse-failure handling**: agent responses may not be valid JSON (especially fallback `general-purpose` agents that wrap JSON in prose). Before processing:

1. Attempt to extract JSON object: prefer `echo "$RESPONSE" | jq -c '.' 2>/dev/null` for parseable input. For mixed prose+JSON: use `echo "$RESPONSE" | grep -oE '\{[^{}]*(\{[^{}]*\}[^{}]*)?\}' | tail -1 | jq -c '.' 2>/dev/null` — extracts last balanced JSON object (one nesting level; breaks on strings containing `{` or `}`). If `jq` not available or both jq attempts fail, fallback: `echo "$RESPONSE" | python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/extract_json_field.py" .` — recovers outermost balanced JSON object from arbitrary prose+JSON text; pass specific field name (e.g. `ok`, `a`) instead of `.` to extract just that field.
   **Caveat**: prefer matching `"a":"<ROLE>"` pattern as anchor when multiple candidates.
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

1. **Attempt autonomous resolution** — search codebase, read relevant files, re-read goal. Fetch primary-source docs for relevant issues (official docs, RFCs, library changelogs, migration guides) via WebFetch — known URLs only; WebFetch fetches specific URL, does not search.
   - **Unknown-URL path**: if URL needed to resolve blocker unknown (e.g. "what does library X's new API look like?"), do NOT guess or invent URL. Mark blocker `requires-user-input` and skip WebFetch — escalate to user with note that documentation lookup required.
   - **Known URL — mandatory verification gate**: after each WebFetch call, before incorporating content into `<PLAN_FILE>`, perform three-step verification per quality-gates.md link verification: (a) Fetch returned non-error (HTTP 200), (b) Read returned content, (c) Match content against specific blocker — confirm topic alignment. If any step fails: mark URL non-resolving, do not write content to `<PLAN_FILE>`, escalate to user. Each URL requires its own Fetch+Read+Match pass — no exemption for same-domain or "similar" URLs.
   - If answer determinable from verified source, update `<PLAN_FILE>` and mark resolved.
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

**Two states** (plan has no diff yet, so no small-diff auto-skip and no `--challenge` flag — unlike fix/feature/refactor/debug): by **default** challenger always reviews plan design; `--no-challenge` (`CHALLENGE_ENABLED=false`) **skips gate entirely**.

```bash
# re-hydrate PLAN_FILE — bash state lost between Bash() calls  # timeout: 3000
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_NS=$(cat ${TMPDIR:-/tmp}/dev-plan-ns-current-${CSID} 2>/dev/null)
PLAN_FILE=$(cat "$PLAN_NS/plan-file" 2>/dev/null)
[ -f "$PLAN_FILE" ] || { echo "plan: PLAN_FILE not found: $PLAN_FILE" >&2; exit 1; }
```

Spawn `foundry:challenger` to adversarially review written plan before user commits:

> "Read `<PLAN_FILE>`. Challenge plan across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step per your instructions."

Parse result:
- **Blockers found** → STOP. Present findings. Do not print `/develop` handoff until user resolves each blocker or explicitly accepts risk. Update `<PLAN_FILE>` with blocker annotations.
- **Concerns only** → append `### Challenger concerns` to `<PLAN_FILE>` as advisory; continue to Final output.
- **No findings / all refuted** → proceed.

## Step 5: Final output

Compose brief — compact human-readable plan summary after all agent input incorporated:

```markdown
<One-sentence summary of what plan achieves and main approach.>

Classification : <feature|fix|refactor|debug>
Complexity     : <small|medium|large>
Affected files : N files across M modules
Key risks      : <one-liner or "none">
Agent review   : ✓ agents ready (<N> corrections incorporated)  |  ⚠ see below

<Steps table — use format that best fits complexity:>
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

Invoke `AskUserQuestion` tool before printing `-> /develop ...`. Options: (a) Proceed — print handoff line and continue · (b) Revise plan — return to Step 2 with user edits. Do not print handoff line until user selects option (a).

**Handoff contract**: plan file at `<PLAN_FILE>` consumable by downstream skills. Pass via `--plan <PLAN_FILE>` when invoking `/develop:feature`, `/develop:fix`, or `/develop:refactor`. For `debug` classification: no downstream plan file — invoke `/develop:debug <goal>` directly; once root cause identified, re-run `/develop:plan` to produce scoped fix plan. When skill receives `--plan <path>`, reads plan file at Step 1 and:
- Extracts `Classification`, `Affected files`, `Risks`, `Suggested approach` — skips cold codebase exploration
- Inherits agent feasibility verdicts and Codex corrections already applied
- Uses `Suggested approach` as implementation roadmap

No quality stack, no Codex pre-pass, no review loop. Exit after printing summary.

End plan document with:

```markdown
## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [specific limitation or unverified assumption]

**Refinements**: N passes.
- Pass 1: [what was addressed]
```

</workflow>

<notes>

<!-- Reference only — execution-dead at runtime; included for agent behavioral context -->

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The plan is obvious — no need for agent feasibility review" | Feasibility review catches domain-specific blockers (missing test infrastructure, incompatible library constraints, API changes) that seem obvious in hindsight. |
| "Codex design review is optional for small tasks" | Small tasks regularly reveal large hidden dependencies. Codex catches architectural anti-patterns before baked into implementation plan. |
| "I can scope this during implementation — no need to plan first" | Scope discovered during implementation inflates PRs and obscures intent. Plan mode exists to prevent exactly this. |

</notes>
