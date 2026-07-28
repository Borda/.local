# 🛠️ develop — Claude Code Plugin

Six slash-command skills — `plan`, `feature`, `fix`, `refactor`, `debug`, `review` — one principle: prove problem exist before writing solution. Every code-changing skill force you prove understanding before touching production code.

> Works standalone — `foundry` not required. Without it, agent dispatches fall back to `general-purpose` with role descriptions (lower quality). Installing `foundry` unlocks specialized agents (`foundry:sw-engineer`, `foundry:qa-specialist`, etc.) — strongly recommended.

______________________________________________________________________

<details>

<summary><strong>📋 Contents</strong></summary>

- [What is develop?](#what-is-develop)
- [Why develop?](#why-develop)
- [Install](#install)
- [Quick start](#quick-start)
- [Skills reference](#skills-reference)
  - [`/develop:plan`](#developplan)
  - [`/develop:feature`](#developfeature)
  - [`/develop:fix`](#developfix)
  - [`/develop:refactor`](#developrefactor)
  - [`/develop:debug`](#developdebug)
  - [`/develop:review`](#developreview)
- [Workflow overview](#workflow-overview)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing / feedback](#contributing--feedback)

</details>

______________________________________________________________________

## 🤔 What is develop?

`develop` = development workflow plugin for Claude Code. Enforces validate-first discipline across full implementation lifecycle: scoping, features, bug fixes, refactoring, debugging, local code review — structured reproducible workflows, not freeform requests.

For developers who want AI that follows engineering discipline, not one that guesses and charges ahead. Every skill has explicit gates blocking forward motion on shaky ground.

**Not for**: dependency upgrades (pydantic v1→v2, numpy 1→2), codebase onboarding/exploration, data migration scripts, CI-only failures without local repro (use `--ci-run` in debug), cross-cutting refactors >15 files (split into phases).

______________________________________________________________________

## 🎯 Why develop?

Without it, AI-assisted development tends to:

- Implement before API contract pinned — discover wrong design after implementation
- Fix bugs by guessing root cause — patches pass tests, don't fix actual problem
- Refactor without safety net — break behavior silently
- Apply multi-file changes blind to affected downstream callers

With `develop`, each workflow enforces discipline rigorous engineer applies manually:

- **feature**: failing demo test first — cannot write test = feature underspecified
- **fix**: reproduce bug with failing regression test first — cannot reproduce = cannot verify fix
- **refactor**: audit test coverage, lock characterization tests before moving one line
- **debug**: gather all evidence, state one confirmed hypothesis before any fix
- **plan**: scope complexity, identify blast radius, agent feasibility review before committing
- **review**: six specialist agents — architecture, tests, performance, docs, lint, API design — against local diff. No GitHub PR needed

______________________________________________________________________

## 📦 Install

**Prerequisites**: Claude Code installed. Verify: `claude --version`

**Install develop**

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install develop@borda-ai-rig
```

<details>

<summary><strong>Install the full suite (recommended)</strong></summary>

```bash
claude plugin install foundry@borda-ai-rig   # specialized agents — strongly recommended
claude plugin install oss@borda-ai-rig        # progressive review loop integration
claude plugin install develop@borda-ai-rig
claude plugin install research@borda-ai-rig
```

</details>

`foundry` gives `develop` access to `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:doc-scribe`, others. Without it, all dispatches fall back to `general-purpose` with role-description prompts — functional, lower quality.

<details>

<summary><strong>Verify installation</strong></summary>

```bash
claude plugin list | grep -F 'develop@borda-ai-rig'
```

Expect enabled entry like `develop@borda-ai-rig` in output.

</details>

______________________________________________________________________

## ⚡ Quick start

Fastest value: scope next task before starting.

```text
/develop:plan "extract data loading into a dedicated DataLoader class"
```

`plan` reads codebase, classifies task, identifies affected files, estimates complexity, runs parallel feasibility review with specialist agents, writes structured plan to `.plans/active/`. Then tells exactly which skill to run next:

```text
Plan -> .plans/active/plan_extract-data-loading-dataloader.md

Classification : refactor
Complexity     : medium
Affected files : 4 files across 2 modules
Key risks      : Public API changes in dataset.py — 3 callers
Agent review   : ✓ agents ready (1 correction incorporated)

-> /develop:refactor "extract data loading into a dedicated DataLoader class" when ready
```

______________________________________________________________________

## 🔧 Skills reference

All skills invoked with `develop:` prefix.

______________________________________________________________________

### `/develop:plan`

**Purpose**: Scope task before committing. Produces structured plan: classification, complexity estimate, affected files, risks, suggested approach. No code written.

**When to use**: before non-trivial feature/fix/refactor; blast radius or complexity unclear; want agent-validated feasibility first.

**Invocation**:

```text
/develop:plan "<goal>"
```

**Flags**:

| Flag               | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `--no-challenge`   | Skip challenger adversarial gate                     |
| `--codemap`        | Strict codemap — fail if index missing               |
| `--no-codemap`     | Disable codemap even if available                    |
| `--accept-no-plan` | Skip inline plan generation (for nested invocations) |

**What happens**:

1. Spawns `foundry:sw-engineer` to classify task (feature / fix / refactor), map affected files, estimate complexity (small / medium / large), list risks. With codemap: effort sizing structural, not file-count-based — reverse-dependency counts per affected module set blast tier (≥5 rdeps HIGH, 1–4 MODERATE, 0 LOW), co-change coupled pairs surface as risks. HIGH module or 3+ affected modules push complexity to `large`
2. Writes structured plan to `.plans/active/<slug>.md`
3. Spawns parallel feasibility agents matching classification — flag blockers, open questions, concerns
4. Resolves blockers autonomously (codebase search, WebFetch for docs); escalates only what genuinely needs your input
5. Annotates plan with resolved/unresolved status, writes Brief summary

**Output to terminal**:

```markdown
Plan -> .plans/active/plan_<slug>.md

Classification : feature | fix | refactor
Complexity     : small | medium | large
Affected files : N files across M modules
Key risks      : <one-liner>
Agent review   : ✓ agents ready (N corrections incorporated)

-> /develop:feature|fix|refactor "<goal>" when ready
```

**Passing plan to downstream skills**: every code-changing skill accepts `--plan <path>`. Skill reads classification, affected files, risks, suggested approach from plan — skips cold codebase exploration, inherits validated feasibility verdicts.

```text
/develop:plan "add streaming response support"
/develop:feature "add streaming response support" --plan .plans/active/plan_add-streaming-response-support.md
```

**What plan does NOT do**: write code or tests. Analysis-only.

______________________________________________________________________

### `/develop:feature`

**Purpose**: TDD-first feature development. Crystallises API as failing demo test, drives implementation to pass, closes quality gaps via review loop + docs update.

**When to use**: adding new behavior.

**Not for**: bug fixes — use `/develop:fix`.

**Invocation**:

```text
/develop:feature "<goal>"
/develop:feature "<goal>" --plan <path>                     # skip cold analysis, use existing plan
/develop:feature 123 --repo owner/upstream-repo         # implement issue from upstream repo (fork workflow)
/develop:feature "<goal>" --team                            # parallel agents for complex/cross-module features
```

**Flags**:

| Flag                  | Description                                                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--repo <owner/repo>` | Route issue fetch to upstream repo. Use when working in fork and issue on original repo (e.g. `--repo owner/my-project`).                                                                  |
| `--plan <path>`       | Read classification, scope, approach from existing plan file                                                                                                                               |
| `--team`              | Spawn parallel `foundry:sw-engineer` + `foundry:qa-specialist` + `foundry:doc-scribe` teammates. Use when feature spans 3+ modules, changes public API, or touches auth/payment/data scope |
| `--no-codemap`        | Disable codemap even if available                                                                                                                                                          |
| `--codemap`           | Strict codemap — fail if index missing                                                                                                                                                     |
| `--accept-no-plan`    | Skip inline plan generation for medium/large scope (trust own scoping)                                                                                                                     |
| `--no-challenge`      | Skip challenger adversarial gate                                                                                                                                                           |
| `--challenge`         | Force challenger gate even on small change auto-skip would otherwise skip                                                                                                                  |
| `--keep "<items>"`    | Append items to compaction contract preserve field — keeps key context if auto-compaction fires mid-skill                                                                                  |

**Workflow**:

1. **Scope analysis** (`foundry:sw-engineer`): existing patterns, reuse opportunities, affected files, compatibility concerns. GitHub issue number given → fetches full issue + comments (upstream if `--repo`).
2. **Source verification** (conditional): feature calls external library API → detects installed version from `pyproject.toml`, fetches official docs via WebFetch, cites relevant passage in code comments.
3. **Demo use-case**: crystallises API contract as inline doctest (simple functions) or example script (complex features with setup). Demo must fail against current code before proceeding. Gate enforced via exit code — not output text.
4. **TDD implementation loop** (`foundry:sw-engineer`): tests pass one at a time, full suite after each change to catch regressions.
5. **Review and close gaps**: 5-axis quality scan (correctness, readability, architecture, security, performance) → fix loop, max 3 cycles.
6. **Documentation** (`foundry:doc-scribe`): Google-style docstrings, CHANGELOG entry, README updates if public API changed.
7. **Quality stack**: lint/format (ruff) → type check (mypy) → full test suite → blast-radius check (codemap-py) → Codex pre-pass → progressive review loop.

**Realistic example**:

```text
/develop:plan "add CSV export to the results API"
/develop:feature "add CSV export to the results API" --plan .plans/active/plan_add-csv-export-results-api.md
```

**Team mode coordination**: Lead broadcasts Step 1 analysis. `foundry:qa-specialist` challenges API design before implementation. `foundry:sw-engineer` implements while `foundry:qa-specialist` writes TDD tests parallel. `foundry:doc-scribe` prepares docs structure concurrently.

______________________________________________________________________

### `/develop:fix`

**Purpose**: Reproduce-first bug resolution. Captures bug in failing regression test before any fix.

**When to use**: fixing known bug with traceback, failing test, or GitHub issue.

**Not for**: CI-only failures — use `/develop:debug --ci-run <run-id>` first; production incidents without CI run or traceback — use `/foundry:investigate`; `.claude/` config issues — use `/foundry:audit`.

**Invocation**:

```text
/develop:fix "<symptom description>"
/develop:fix 88                                     # GitHub issue number — fetches full issue + comments
/develop:fix 88 --repo owner/upstream-repo          # issue on upstream repo (fork workflow)
/develop:fix "<symptom>" --plan <path>              # use existing plan
/develop:fix "<symptom>" --diagnosis <path>         # skip root cause analysis; use debug output
/develop:fix "<symptom>" --team                     # parallel root-cause investigation
```

**Flags**:

| Flag                  | Description                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `--repo <owner/repo>` | Route issue fetch to upstream repo. Use when working in fork and issue on original repo (e.g. `--repo owner/my-project`). |
| `--plan <path>`       | Read scope and approach from existing plan file                                                                           |
| `--diagnosis <path>`  | Read confirmed root cause from `/develop:debug` output file; skips Step 1 analysis entirely                               |
| `--team`              | Spawn 2-3 `foundry:sw-engineer` teammates, each investigating distinct root-cause hypothesis independently                |
| `--no-challenge`      | Skip challenger adversarial gate entirely                                                                                 |
| `--challenge`         | Force challenger gate even on small change auto-skip would otherwise skip                                                 |
| `--keep "<items>"`    | Append items to compaction contract preserve field — keeps key context if auto-compaction fires mid-skill                 |

**Workflow**:

1. **Understand the problem** (`foundry:sw-engineer`): reads full traceback, searches failing code path, traces call graph, identifies root cause, state mutation, blast radius. Argument = positive integer → fetches GitHub issue (upstream if `--repo`).
2. **Reproduce the bug** (`foundry:qa-specialist`): writes regression test failing on unfixed code. Gate: test must exit non-zero before proceeding.
3. **Apply the fix** (`foundry:sw-engineer`): minimal change — only what makes regression test pass.
4. **Review and close gaps**: 5-axis quality scan → fix loop, max 3 cycles. Adjacent bugs documented as observations, handled in separate session — never fixed same pass.
5. **Quality stack**: ruff → mypy → full test suite → blast-radius check → Codex pre-pass → progressive review loop.

**Realistic example**:

```text
/develop:fix "KeyError in transform pipeline when input has null values"
/develop:fix 124   # fix GitHub issue #124
```

**Using debug output**:

```text
/develop:debug "intermittent timeout on /api/predict under load"
# After debug session writes .plans/active/debug_intermittent-timeout.md:
/develop:fix "intermittent timeout on /api/predict under load" --diagnosis .plans/active/debug_intermittent-timeout.md
```

**Scope gate**: root cause spans 3+ modules → asked narrow scope or proceed — prevents large unfocused fixes.

______________________________________________________________________

### `/develop:refactor`

**Purpose**: Test-first refactoring. Audits test coverage, adds characterization tests for gaps, restructures code with safety net catching any behavior change.

**When to use**: restructuring existing code — extracting classes, simplifying logic, cleaning API, removing dead code — without changing observed behavior.

**Not for**: bug fixes — use `/develop:fix`; new features — use `/develop:feature`.

**Invocation**:

```text
/develop:refactor "<target file or directory> <goal>"
/develop:refactor "<goal>" --plan <path>
/develop:refactor "<goal>" --repo owner/upstream-repo   # context from upstream issue (fork workflow)
/develop:refactor "<goal>" --team                       # parallel: foundry:sw-engineer refactors + foundry:qa-specialist writes tests simultaneously
```

**Flags**:

| Flag                  | Description                                                                                                                                                        |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--repo <owner/repo>` | Route issue fetch to upstream repo. Use when refactor context tied to upstream issue in fork. Parsed for consistency; refactor has no issue-fetch step by default. |
| `--plan <path>`       | Read scope and approach from existing plan file                                                                                                                    |
| `--team`              | Spawn `foundry:sw-engineer` (refactoring) + `foundry:qa-specialist` (characterization tests) parallel. Use when target is directory or spans multiple modules      |
| `--no-codemap`        | Disable codemap even if available                                                                                                                                  |
| `--codemap`           | Strict codemap — fail if index missing                                                                                                                             |
| `--accept-no-plan`    | Skip inline plan generation for medium/large scope                                                                                                                 |
| `--no-challenge`      | Skip challenger adversarial gate                                                                                                                                   |
| `--challenge`         | Force challenger gate even on small change auto-skip would otherwise skip                                                                                          |
| `--keep "<items>"`    | Append items to compaction contract preserve field — keeps key context if auto-compaction fires mid-skill                                                          |

**Workflow**:

1. **Scope and understand** (`foundry:sw-engineer`): reads target code, maps public API surface, identifies complexity hotspots + coupling. Codemap for blast-radius when available. Scope gate: target spans 3+ modules, 5+ files, or any public-API rename → asks narrow or proceed.
2. **Audit test coverage**: classifies each public function covered / partially covered / uncovered. No `pytest-cov` installed → falls back to "all uncovered" conservatively.
3. **Add characterization tests** (`foundry:qa-specialist`): every uncovered/partial public API gets tests asserting *current* behavior (not desired). Gate: all characterization tests must pass on unmodified code before proceeding.
4. **Refactor with safety net**: one focused change per cycle, tests after each. Safety break: max 5 change-test cycles per inner session; max 10 total across all outer review cycles.
5. **Review and close gaps**: behavior preservation, goal achievement, no new smells, no unintended API surface changes. Max 3 outer review cycles.
6. **Quality stack**: ruff → mypy → full test suite → blast-radius check → Codex pre-pass → progressive review loop.

**Refactoring categories skill handles**:

- Logic simplification: replace complex conditionals, flatten nesting, extract helpers
- API cleanup: rename for clarity, consolidate parameters, add type annotations
- Structural: extract classes/modules, reduce coupling, apply design patterns
- Performance: replace loops with vectorized ops, reduce allocations, batch I/O
- Dead code removal: unused imports, unreachable branches, unexported public methods

**Realistic example**:

```text
/develop:plan "extract data loading into a dedicated DataLoader class"
/develop:refactor "extract data loading into a dedicated DataLoader class" --plan .plans/active/plan_extract-data-loading-dataloader.md
```

**Checkpoint and resume**: creates `.developments/<timestamp>/checkpoint.md` after each step. Session interrupted → re-run offers resume from last completed step.

______________________________________________________________________

### `/develop:debug`

**Purpose**: Investigation-first debugging. Gathers all signals, traces failure path, forms single confirmed root-cause hypothesis, writes diagnosis file, hands off to `/develop:fix`.

**When to use**: symptom without confirmed root cause; bug mysterious enough to warrant structured investigation before fixing.

**Not for**: production incidents without CI run ID or traceback — use `/foundry:investigate`; `.claude/` config issues — use `/foundry:audit`. CI-only failures ARE supported — pass `--ci-run <run-id or URL>`.

**Invocation**:

```text
/develop:debug "<symptom description>"
/develop:debug 88                                   # GitHub issue number
/develop:debug 88 --repo owner/upstream-repo        # issue on upstream repo (fork workflow)
/develop:debug "<symptom>" --team                   # parallel hypothesis investigation
```

**Flags**:

| Flag                   | Description                                                                                                                                                                                                                                     |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--repo <owner/repo>`  | Route issue fetch to upstream repo. Use when working in fork and issue on original repo (e.g. `--repo owner/my-project`).                                                                                                                       |
| `--team`               | Spawn 2-3 `foundry:sw-engineer` teammates, each investigating distinct root-cause hypothesis independently. Use when root cause unclear after initial analysis, or failure spans 3+ modules                                                     |
| `--ci-run <id-or-url>` | Fetch CI failure logs via `gh run view <id> --log-failed` instead of running pytest locally. Accepts bare run ID or any GitHub Actions URL (`/actions/runs/<id>` or `/actions/runs/<id>/jobs/<job>`). Use for CI-only failures, no local repro. |
| `--codemap`            | Strict codemap — fail if index missing (auto-enabled when installed)                                                                                                                                                                            |
| `--no-codemap`         | Disable codemap even if available                                                                                                                                                                                                               |
| `--no-challenge`       | Skip challenger adversarial gate entirely                                                                                                                                                                                                       |
| `--challenge`          | Force challenger gate even on small change auto-skip would otherwise skip                                                                                                                                                                       |
| `--keep "<items>"`     | Append items to compaction contract preserve field — keeps key context if auto-compaction fires mid-skill                                                                                                                                       |

**Workflow**:

1. **Understand the symptom** (`foundry:sw-engineer`): reads full tracebacks, recent git changes near failing code, traces call path entry point → failure site. GitHub issue number → fetches full issue + comments (upstream if `--repo`).
2. **Pattern analysis**: finds 2-3 similar working code paths, compares exhaustively against broken path — input, environment, call order, conditional branches, None/empty guards.
3. **Hypothesis and gate**: states root cause explicitly with supporting + contradicting evidence and confidence (high / medium / low). Presents hypothesis, waits for confirmation before proceeding. Low confidence → targeted probe (minimal script, added assertion) for missing signal. Codemap enabled → one-time `test-impact` query on confirmed suspect module/function.
4. **Hand off to fix**: writes diagnosis file to `.plans/active/debug_<slug>.md`, emits `-> /develop:fix --diagnosis <path>`. Fix's Step 1 pre-answered by diagnosis. Test-impact result (with index timestamp) written under `## Test Impact (codemap-py)` section — `/develop:fix` reuses it (test-impact runs once across debug→fix flow), re-queries only if index moved or result stale.

**Debug is investigation-only** — no code changes. Fix happens in separate auditable session with own regression test gate.

**Realistic example**:

```text
/develop:debug "intermittent timeout on /api/predict under load"
# -> /develop:fix --diagnosis .plans/active/debug_intermittent-timeout-api-predict.md
```

**Team mode**: teammates independently investigate competing hypotheses, lead facilitates cross-challenge, synthesises consensus before handing off to fix.

______________________________________________________________________

### `/develop:review`

**Purpose**: Comprehensive local code review via six specialist agents parallel — architecture, tests, performance, docs, static analysis, API design. Works against local files or current git diff. No GitHub PR required.

**When to use**: reviewing own changes before committing; structured feedback on local files; closing quality gaps before PR.

**Not for**: GitHub PR review — use `/oss:review <PR#>`; implementation work — use `/develop:feature` or `/develop:fix`.

**Scope**: Python source only. Non-Python files (YAML, Dockerfile, JSON, shell scripts) flagged in report header as "not reviewed" but presence noted — dependency/config changes can silently break reviewed Python code.

**Invocation**:

```text
/develop:review                          # review current git diff (staged + unstaged vs HEAD)
/develop:review src/mypackage/module.py  # review a specific file
/develop:review src/mypackage/           # review all Python files in a directory
```

**Flags**:

| Flag               | Description                                                                                               |
| ------------------ | --------------------------------------------------------------------------------------------------------- |
| `--no-challenge`   | Skip challenger adversarial gate                                                                          |
| `--challenge`      | Force challenger gate even on small change auto-skip would otherwise skip                                 |
| `--codemap`        | Strict codemap — fail if index missing                                                                    |
| `--no-codemap`     | Disable codemap even if available                                                                         |
| `--semble`         | Enable semble semantic search context                                                                     |
| `--keep "<items>"` | Append items to compaction contract preserve field — keeps key context if auto-compaction fires mid-skill |

**Workflow**:

1. **Identify scope**: collects Python files from path or `git diff HEAD`. Classifies diff FIX / REFACTOR / FEATURE / CHORE / MIXED — skips optional agents for smaller diffs (FIX skips `foundry:perf-optimizer` + `foundry:solution-architect`; CHORE skips `foundry:qa-specialist`, `foundry:perf-optimizer`, `foundry:solution-architect`). Small diff (single file, \<50 lines, no new public API) also auto-skips `foundry:challenger` gate unless `--challenge` passed.
2. **Codex co-review** (if `codex` plugin installed): adversarial diff review seeds pre-flagged issues list for specialist agents.
3. **Six parallel agents** (file-based handoff — each writes handover files to `.temp/review/<timestamp>/`):
   - `foundry:sw-engineer`: architecture, SOLID, type safety, error handling, Python anti-patterns, security for touched auth/input/data paths
   - `foundry:qa-specialist`: test coverage gaps, missing edge cases, ML non-determinism, seed pinning, boundary conditions
   - `foundry:perf-optimizer`: algorithmic complexity, loops that should be NumPy/torch ops, unnecessary I/O, ML DataLoader config (skipped for FIX diffs)
   - `foundry:doc-scribe`: public APIs without docstrings, Google-style section gaps, CHANGELOG entries, deprecated stdlib usage
   - `foundry:linting-expert`: ruff violations, mypy errors, type annotation gaps on public API, suppressed violations
   - `foundry:solution-architect`: API design quality, coupling, backward compatibility (only for public API boundary changes; skipped for REFACTOR and FIX)
4. **Cross-validate** critical + blocking findings using same agent type that raised each finding.
5. **Consolidate** (`foundry:sw-engineer`): reads all findings, deduplicates, ranks by impact, writes full report to `.reports/review/<timestamp>/review-report.md`. Signal-to-noise gate: small modules not padded with low-severity findings.
6. **Codex delegation** (optional): mechanical tasks — docstrings, missing tests for concrete scenarios, consistent renames — delegated to Codex when precise brief writable.

**Report structure**:

```text
Critical (must fix)
Architecture & Quality
Test Coverage Gaps
Performance Concerns
Documentation Gaps
Static Analysis
API Design
Codex Co-Review
Recommended Next Steps
Review Confidence (per-agent scores)
```

**Realistic example**:

```text
git add src/mypackage/trainer.py tests/test_trainer.py
/develop:review src/mypackage/trainer.py
```

**Follow-up from review findings**:

- Blocking bugs or regressions → `/develop:fix`
- Structural or quality issues → `/develop:refactor`
- Security findings → `/develop:fix`; run `pip-audit` if dependency files changed
- Mechanical issues (docstrings, missing tests) → `/codex:codex-rescue <task>` if Codex available
- GitHub PR review for contributor → `/oss:review <PR#>` instead

______________________________________________________________________

## 🗺️ Workflow overview

Skills chain naturally. Typical session:

### New feature

```text
# 1. Scope — understand what you're building before building it
/develop:plan "add rate limiting to the API gateway"

# 2. Implement — TDD contract pins the API, then implementation follows tests
/develop:feature "add rate limiting to the API gateway" --plan .plans/active/plan_add-rate-limiting-api-gateway.md

# 3. Review before committing (optional — quality stack already ran, but useful for a final check)
/develop:review src/gateway/
```

### Bug fix

```text
# Option A: symptom is clear enough — go straight to fix
/develop:fix "RateLimiter raises AttributeError when Redis connection fails"

# Option B: mysterious failure — investigate first
/develop:debug "API gateway returns 200 on every request under high load"
# Debug writes: .plans/active/debug_api-gateway-200-high-load.md
/develop:fix "API gateway returns 200 on every request under high load" --diagnosis .plans/active/debug_api-gateway-200-high-load.md
```

### Safe refactor

```text
/develop:plan "extract request parsing into a dedicated middleware layer"
/develop:refactor "extract request parsing into a dedicated middleware layer" --plan .plans/active/plan_extract-request-parsing-middleware.md
```

### Review before a PR

```text
/develop:review    # reviews the full current diff (staged + unstaged vs HEAD)
```

### Fork workflow (upstream issue)

Forked repo, want to fix/implement issue reported on original upstream. Pass `--repo <owner/repo>` to route issue fetch to upstream instead of fork:

```text
# Debug an upstream issue in your fork
/develop:debug 88 --repo owner/my-project

# Fix it — skip debug if root cause is clear
/develop:fix 88 --repo owner/my-project

# Implement a feature request from upstream
/develop:feature 123 --repo owner/my-project
```

`--repo` accepted by `fix`, `feature`, `debug`, `refactor`. Affects only `gh issue view` call fetching issue body + comments — rest of workflow operates on local fork as normal.

### Complex or high-stakes work

Add `--team` to any code-changing skill. Spawns parallel specialist agents exploring implementation space independently. Significantly higher token cost — reserve for multi-module changes, public API additions, auth/payment/data scope.

```text
/develop:feature "add streaming response support" --team
/develop:fix "memory leak in batch inference" --team
```

______________________________________________________________________

## ⚙️ Configuration

### Dependencies by capability

| Dependency       | Required    | Unlocks                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `foundry` plugin | recommended | `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:doc-scribe`, others; quality stack shared file. Without foundry, all agents fall back to `general-purpose` with role-description prompts.                                                                                                                                                                            |
| `oss` plugin     | optional    | `oss:review` checklist used by `develop:review` Agent 1. `oss:*` skills never auto-invoked from develop flows — progressive review loop escalates to `/develop:review` on concern signal only; run `/oss:review` explicitly once PR exists.                                                                                                                                                             |
| `codex` plugin   | optional    | Codex pre-pass in quality stack; Codex adversarial co-review in `develop:review`; mechanical delegation in Step 6. Gracefully skipped if absent.                                                                                                                                                                                                                                                        |
| `codemap-py`     | optional    | `codemap-py query` for blast-radius, import graph, call-graph context. **Auto-enabled** in all skills when installed and index found; existing index incremental-refreshed (SHA-diff) automatically before use; silently skipped if absent (no full build mid-task — run `/codemap-py:scan-codebase` once). Install: `claude plugin install codemap-py@borda-ai-rig`, then `/codemap-py:scan-codebase`. |
| `gh` CLI         | optional    | Used in `fix`, `debug`, `feature` when argument is GitHub issue number (`gh issue view`). Pass `--repo <owner/repo>` to route issue fetch to upstream repo (fork workflow).                                                                                                                                                                                                                             |

### Codemap-py behavior

Codemap-py auto-enabled in all skills when plugin installed and index exists. No flag needed for default experience.

| State                              | Behavior                                   |
| ---------------------------------- | ------------------------------------------ |
| Installed + index found + no flag  | Auto-enabled                               |
| Installed + no index + no flag     | AskUser: build index now? (Gate A)         |
| Installed + stale index + no flag  | AskUser: rebuild now? (Gate B)             |
| Not installed + no flag            | Silent skip                                |
| Not installed + `--codemap`        | AskUser: install codemap-py? (strict mode) |
| Installed + no index + `--codemap` | Fail with: build index first               |
| Any state + `--no-codemap`         | Always disabled                            |

`--codemap` = **strict assertion** — useful in CI or to guarantee structural context always applied. `--no-codemap` skips codemap for specific run (e.g. non-Python submodule).

### Python tooling

Quality stack auto-detects project tooling at skill start via shared runner-detection file. No configuration needed — finds `uv`, `ruff`, `mypy`, `pytest` if on path. Tool absent → stack step skipped with note in final report.

### Artifact directories

Skills write to these dirs at project root (all gitignored):

| Directory                      | Contents                                                               |
| ------------------------------ | ---------------------------------------------------------------------- |
| `.plans/active/`               | Plan files from `/develop:plan`, diagnosis files from `/develop:debug` |
| `.developments/<timestamp>/`   | Checkpoint files for resumable feature/fix/refactor sessions           |
| `.temp/review/<timestamp>/`    | Per-agent handover files (intermediate) from `/develop:review`         |
| `.reports/review/<timestamp>/` | Consolidated final report from `/develop:review`                       |

Completed runs cleaned after 30 days. Interrupted runs (no `result.jsonl`) kept for debugging.

______________________________________________________________________

<details>

<summary>

## 🔍 Troubleshooting

</summary>

## 🔍 Troubleshooting

### "foundry plugin not installed — quality stack skipped"

Quality stack reads shared file from `foundry` plugin. Not installed → lint/type/test/blast-radius steps skipped entirely, final report notes it.

```bash
claude plugin install foundry@borda-ai-rig
```

### Demo gate passes (exit 0) when it should fail

`/develop:feature` Step 2 confirms demo fails before implementation. Gate exits 0 → feature may already exist, or test tests wrong thing. Skill stops, asks revisit Step 1. Do not force past gate — means feature exists already or demo not testing intended contract.

### Regression test gate passes when it should fail

Same pattern in `/develop:fix` Step 2. Regression test passes on unfixed code → test not capturing bug. Revisit Step 1 — symptom description not pointing at actual failure site, or test exercises different code path.

### Characterization test fails on unmodified code

`/develop:refactor` Step 3: characterization tests must pass before refactoring begins. Characterization test fails → test wrong — must assert *current* behavior, not desired. Fix test to match what code actually does now.

### Session interrupted mid-skill

`feature`, `fix`, `refactor` write checkpoint file to `.developments/<timestamp>/checkpoint.md` after each major step. Re-running same skill command offers resume from last completed step.

### codemap-py query warnings appearing in output

`codemap-py` optional. `codemap-py` not on PATH → all codemap-py steps silently skipped. Plugin installed but index missing/stale → default (auto) mode prompts build/rebuild (Gate A/B); `--no-codemap` skips silently. Skill works fully without it. To enable codemap-py context, install the `codemap-py` plugin, run `/codemap-py:scan-codebase`.

______________________________________________________________________

</details>

## 🙏 Contributing / feedback

Plugin part of `borda-ai-rig` suite. Canonical source in `plugins/cc_develop/` within repository.

Report bug or suggest improvement: open issue in repository. Include skill name, invocation used, actual vs expected behavior.

**To update the plugin**:

```bash
claude plugin install develop@borda-ai-rig
```

**To uninstall**:

```bash
claude plugin uninstall develop
```

**Plugin structure**:

```text
plugins/cc_develop/
├── .claude-plugin/
│   └── plugin.json          -- manifest (name, version, author)
└── skills/
    ├── plan/
    │   └── SKILL.md
    ├── feature/
    │   └── SKILL.md
    ├── fix/
    │   └── SKILL.md
    ├── refactor/
    │   └── SKILL.md
    ├── debug/
    │   └── SKILL.md
    └── review/
        └── SKILL.md
```

Modify any skill → update this README before finishing — unsynced change = incomplete change.
