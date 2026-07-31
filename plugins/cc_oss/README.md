# 🌱 oss — Claude Code Plugin

OSS workflow plugin for Python/ML open-source projects. Four agents (two user-facing, two internal pipeline), four slash-command skills: issue analysis, parallel code review, PR resolution, SemVer-disciplined releases.

> Works standalone — `foundry` not required. Without it, agent dispatches fall back to `general-purpose` with role descriptions (lower quality). Installing `foundry` unlocks specialized agents (`foundry:sw-engineer`, `foundry:qa-specialist`, etc.) — strongly recommended for production.

______________________________________________________________________

<details>

<summary><strong>📋 Contents</strong></summary>

- [What is oss?](#what-is-oss)
- [Why oss?](#why-oss)
- [Install](#install)
- [Quick start](#quick-start)
- [Skills reference](#skills-reference)
  - [/oss:analyse](#ossanalyse)
  - [/oss:review](#ossreview)
  - [/oss:resolve](#ossresolve)
  - [/oss:release](#ossrelease)
- [Agents reference](#agents-reference)
  - [oss:gh-scraper](#gh-scraper)
  - [oss:repo-warden](#repo-warden)
  - [oss:shepherd](#ossshepherd)
  - [oss:cicd-steward](#osscicd-steward)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing / feedback](#contributing--feedback)

</details>

______________________________________________________________________

## 🤔 What is oss?

`oss` = Claude Code plugin for Python/ML open-source maintainers. Four slash-command skills — analyse, review, resolve, release — plus two specialist agents owning contributor communication and CI health. Covers recurring expensive maintainer work: triaging GitHub threads, multi-perspective PR review, closing review feedback in one pass, cutting releases with correct SemVer and complete changelogs.

______________________________________________________________________

## 🎯 Why oss?

Maintaining OSS = three competing demands: review code carefully (catch regressions), respond to contributors fast (keep engaged), ship releases confidently (users upgrade). Each = context-switch tax.

`oss` removes tax:

**PR review in minutes, not hours.** `/oss:review` runs Codex pre-pass ~60 seconds. Trivial PRs close there. Substantive PRs → six specialist agents fan out parallel — architecture, tests, performance, docs, linting, security — return ranked consolidated report. Expert coverage without reading every line.

**Contributors get real response, fast.** `--reply` flag drafts welcoming comment in project voice, citing your conventions. 30 seconds review vs 10 minutes writing. Contributors feel heard, stay engaged.

**Review feedback applied completely.** `/oss:resolve` closes gap between "reviewer said X" and "X in code." Reads live PR comments, saved review report, or both. Deduplicates across sources, resolves conflicts semantically (not mechanical side-pick), implements in parallel per-specialist worktrees with `[resolve No.N]` tags for traceability.

**Releases go out correct.** `oss:shepherd` enforces SemVer before any tag. Writes changelog with deprecation tracking, generates migration guides for breaking changes, runs readiness audit. No accidental major bumps. No forgotten changelog entries.

**Triage fast, structured.** `/oss:analyse vitality` = repo vitality scorecard with duplicate issue clustering + stale PR detection every morning. Specific thread → structured summary, act immediately.

______________________________________________________________________

## 📦 Install

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install oss@borda-ai-rig
```

Full suite for best results:

```bash
claude plugin install foundry@borda-ai-rig   # base agents — strongly recommended
claude plugin install oss@borda-ai-rig
claude plugin install develop@borda-ai-rig
claude plugin install research@borda-ai-rig
```

**Optional integrations** (unlock extra capabilities inside `oss` skills):

| Plugin    | What it unlocks                                                                                                                                                                                      |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `foundry` | Specialized review agents (sw-engineer, qa-specialist, perf-optimizer, doc-scribe, solution-architect, linting-expert) instead of general-purpose fallbacks                                          |
| `codex`   | Action item implementation in `/oss:resolve` Step 8; Tier 1 pre-pass in `/oss:review`                                                                                                                |
| `codemap` | Reverse-dependency count (`rdep_count`) in `/oss:review` risk assessment; stale-symbol detection in `/oss:analyse` issue triage, Open-PR Overlap + Structural Constraints in `/oss:analyse vitality` |

All `oss` skills degrade gracefully when optional plugins absent — reduced capability, not broken commands.

> **Note:** Skills always invoked with `oss:` prefix: `/oss:analyse`, `/oss:review`, `/oss:resolve`, `/oss:release`.

<details>

<summary><strong>Upgrade</strong></summary>

```bash
claude plugin install oss@borda-ai-rig
```

</details>

<details>

<summary><strong>Uninstall</strong></summary>

```bash
claude plugin uninstall oss
```

</details>

______________________________________________________________________

## ⚡ Quick start

```text
# Morning: understand what needs attention
/oss:analyse vitality

# Review top PR and draft a contributor-facing response
/oss:review 55 --reply

# Apply all review feedback in one pass
/oss:resolve 55 report

# Cut a release
/oss:release prepare v2.1.0
```

______________________________________________________________________

## 🔧 Skills reference

### /analyse

Analyse GitHub threads + repo vitality. Accepts issue/PR number, keyword `vitality`, keyword `ecosystem`, or path to saved report file.

**Purpose:** Structured actionable summary of any GitHub thread, or broad view of open work. No need to read every comment yourself.

**Auto-invokes when:** user gives GitHub issue/PR number (`#N`) or `github.com` URL + asks analyze/summarize/triage; user asks "is this repo healthy" or vitality stats.

**Invocation:**

```text
/oss:analyse 123                # issue, PR, or discussion by number
/oss:analyse vitality           # repo vitality: 9-axis health scorecard, duplicate clustering, raw data JSONL
/oss:analyse vitality --quick   # fast daily scorecard: core scoring only, skips codex + adversarial passes
/oss:analyse ecosystem          # dependency health, upstream compatibility
/oss:analyse path/to/report.md  # re-analyse a saved report
```

**Flags:**

| Flag               | Effect                                                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--reply`          | Draft contributor-facing response after analysis (routed through `oss:shepherd` for voice consistency)                                                                                      |
| `--quick`          | Vitality only: fast daily scorecard — skips Codex independent review + adversarial rework loop, reduces to 4 spawns. Full (reviewed) mode = default; confidence capped lower in quick mode. |
| `--keep "<items>"` | Append quoted string to compaction contract's `preserve:` line — items survive auto-compact mid-run (advanced; long multi-agent sessions)                                                   |

**What it does:**

Thread number: fetches issue/PR, reads all comments, classifies thread type (bug report, feature request, question, duplicate, stale), produces structured summary: what asked, current state, action needed from you, and — with `--reply` — draft response. With codemap index present, symbols/modules named in issue thread existence-checked against index; identifiers that no longer resolve flag issue as referencing stale code (with likely rename target when codemap suggests one).

`vitality`: pulls open issues + PRs, scores repo across 9 axes (Axes 1–8 plus Axis 9 Trajectory), clusters duplicates, flags threads stale beyond project threshold, gives prioritised triage list with weighted Health Score %. All raw API data saved to JSONL file alongside report for manual inspection. With codemap index, report gains Open-PR Overlap note (pairwise changed-file overlap plus tightly-coupled-module conflict candidates) and Structural Constraints block (highest-blast-radius modules, collision/degraded/stale index signals). Every codemap signal optional — no index or plugin absent → analyse degrades to GitHub-only behavior, flags gap inline, never blocks.

**Sample vitality scorecard (terminal output):**

```text
# Repo Vitality — example/mylib
**Skill:** oss:analyse v0.7.0 · **Generated:** 2026-05-11T10-00-00Z

---

## Executive Summary

Project is in healthy condition (74%) with strong CI/CD and documentation.
Bus factor of 2 is the primary risk. Dependency update config absent.

**Health Score:** 74% 🟡 · 5 healthy · 3 warning · 1 critical · 0 unavailable (⚪)
**Top Risk:** Axis 3 bus factor = 2 — one departure stalls merges

---

| # | Axis                 | Score  | Status | Key Signal                           |
|---|----------------------|--------|--------|--------------------------------------|
| 1 | Responsiveness       | 10.0   | 🟢     | median issue 1.2d, PR 0.8d; 94% ≤7d |
| 2 | Maintenance activity | 10.0   | 🟢     | last commit 3d, 18 commits/30d       |
| 3 | Contributor health   |  5.0   | 🟡     | bus factor 2, retention 67%          |
| 4 | Issue & PR health    |  5.0   | 🟡     | stale 18%, close 0.71, review 62%    |
| 5 | CI/CD & code quality | 10.0   | 🟢     | 5/5 checks, CI pass 95%              |
| 6 | Documentation        |  7.8   | 🟢     | 7/9 checkpoints                      |
| 7 | Governance           |  8.3   | 🟢     | 5/6 files, active maint 3/3          |
| 8 | Security posture     |  5.0   | 🟡     | dep-config: no, alerts: 403          |
| 9 | Trajectory           |  5.0   | 🟡     | pool -10%, TTM 2d->3d, P90 45d, dep 12% |
|   | **Total Score**      | **74%** |       |                                      |
```

**Output locations:**

- Thread analysis: `.reports/analyse/thread/`
- Vitality report: `.reports/analyse/vitality/`
- Ecosystem report: `.reports/analyse/ecosystem/`

GitHub API responses cached in `.cache/gh/` by number and date (30-day TTL) — repeated calls on same thread fast.

______________________________________________________________________

### /review

Tiered parallel review of GitHub PR. Input always PR number.

**Purpose:** Expert-level review coverage — architecture, tests, performance, docs, linting, security — without reading every line. Produces ranked findings report. Optionally drafts welcoming contributor comment.

**Invocation:**

```text
/oss:review 55                # full tiered review — saves findings report
/oss:review 55 --reply        # review + draft contributor-facing comment
```

> Local files or current git diff without PR → use `/develop:review` from `develop` plugin.

**How the pipeline works:**

```text
Tier 0  git diff --stat
        Scope detection — exits only if no Python or doc files changed

Tier 1  Codex pre-pass (~60 seconds)
        Independent diff review; surfaces obvious issues first
        If blocking issue found → report immediately, skip Tier 2

Tier 2  Parallel specialist agents (requires foundry plugin)
        foundry:sw-engineer        — correctness, design, API contracts
        foundry:qa-specialist      — test coverage, edge cases, regression risk
        foundry:perf-optimizer     — hot paths, memory, algorithmic complexity
        foundry:doc-scribe         — docstrings, README accuracy, examples  [always]
        foundry:solution-architect — architecture fit, dependency impact
        foundry:linting-expert     — style, type annotations, ruff/mypy

        Agent skip rules (sw-engineer, challenger, Codex always run):
          CI/CD-only PR → oss:cicd-steward + sw-engineer + challenger + Codex
          docs-only PR  → doc-scribe + sw-engineer + challenger + Codex
          FIX           → skips perf-optimizer, solution-architect
          REFACTOR      → all agents (perf-optimizer verifies new structure isn't slower)
          FEATURE/MIXED → all agents
          CHORE         → sw-engineer + doc-scribe + linting-expert + challenger + Codex

        CI status: failing CI noted in report header — review always proceeds
        codemap integration: rdep_count > 20 flags as high-risk change

        Consolidation: foundry:sw-engineer merges all agent findings into ranked report

        --reply: oss:shepherd drafts contributor-facing comment from consolidated report (written to .temp/; user posts)
```

**Typical scenarios:**

| PR type                                               | Agents that run                                                                                        | Skipped                                                                       |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| CI/CD only (.github/workflows, azure-pipelines, etc.) | oss:cicd-steward, sw-engineer, challenger, Codex                                                       | qa-specialist, perf-optimizer, doc-scribe, linting-expert, solution-architect |
| Docs/README only (.md, .rst)                          | doc-scribe, sw-engineer, challenger, Codex                                                             | qa-specialist, perf-optimizer, linting-expert, solution-architect             |
| Bug fix (\<3 files, \<50 lines)                       | sw-engineer, qa-specialist, doc-scribe, linting-expert, challenger                                     | perf-optimizer, solution-architect                                            |
| Refactor (restructure, no new API)                    | sw-engineer, qa-specialist, perf-optimizer, doc-scribe, linting-expert, solution-architect, challenger | —                                                                             |
| Feature (new public API/module)                       | all agents                                                                                             | —                                                                             |
| Chore (deps, config, tooling)                         | sw-engineer, doc-scribe, linting-expert, challenger, Codex                                             | qa-specialist, perf-optimizer, solution-architect                             |
| Any PR with failing CI                                | same as above by type                                                                                  | — (CI noted in report header)                                                 |

Without `foundry`, Tier 2 falls back to general-purpose agents with role descriptions — functional, lower quality.

**Output locations:**

- Per-agent handover files (intermediate): `.temp/review/<timestamp>/`
- Consolidated report: `.reports/review/<timestamp>/review-report.md`
- Reply draft (with `--reply`): `.temp/output-reply-<PR#>-<date>.md`

**Flags:**

| Flag               | Effect                                                                                                                                                                                                                        |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--reply`          | After consolidation, `oss:shepherd` drafts welcoming two-part PR comment (positive framing first, then specific actionable asks)                                                                                              |
| `--worktree`       | Opt-in. Run the review in an isolated git worktree (base: HEAD) so no dimension agent can mutate main sources. Report is written to the **main tree**; you review + merge. PR-review mode only (not `--reply`/direct-report). |
| `--keep "<items>"` | Append quoted string to compaction contract's `preserve:` line — items survive auto-compact mid-run (advanced; long multi-agent sessions)                                                                                     |

______________________________________________________________________

### /resolve

Apply review findings to codebase. Reads live PR comments, saved review report, or both — deduplicates, resolves conflicts, implements fixes.

**Purpose:** Close gap between "reviewer said X" and "X in code." One command: open findings → committed fixes.

**Invocation:**

```text
/oss:resolve 55                # pr mode — apply fixes from live GitHub PR comments
/oss:resolve report            # report mode — apply fixes from the saved /oss:review report
/oss:resolve 55 report         # pr + report mode — both sources, deduplicated
/oss:resolve                   # review-handoff mode — picks up from the last /oss:review run
```

**Source modes:**

| Arguments        | Mode           | Source                            | When to use                                                 |
| ---------------- | -------------- | --------------------------------- | ----------------------------------------------------------- |
| `55` (PR number) | pr             | Live GitHub PR comments           | Apply feedback posted directly on GitHub                    |
| `report`         | report         | Saved `/oss:review` findings file | Apply findings from last review run                         |
| `55 report`      | pr + report    | Both, aggregated                  | Full close — deduplicates across both inputs                |
| _(none)_         | review-handoff | Review-handoff                    | Continues directly from last `/oss:review` run this session |

**How it works:**

Three phases:

1. **Intelligence gathering** — dedicated subagent fetches full PR thread (comments, reviews, inline code comments) — orchestrator context stays small; subagent classifies each finding, writes structured output to files; orchestrator reads compact classified table
2. **Conflict resolution** — merge conflicts: read intent from both sides; apply semantically correct resolution (never mechanical "take ours"/"take theirs")
3. **Action item implementation** — three-phase parallel dispatch: medium-effort items go to Codex individually first (fast, no batching needed); everything else splits into Phase 1 challenge (grouped by domain, all groups fire concurrently — read-only, safe to overlap), Phase 2 implementation (grouped by one of six specialists — `sw-engineer`, `qa-specialist`, `doc-scribe`, `linting-expert`, `perf-optimizer`, `solution-architect` — max 5 items/group, each group runs in its own isolated `git worktree` so concurrent specialists never race on the same working tree), Phase 3 merge-back (orchestrator cherry-picks every item's commit onto the PR branch, sequentially — whole worktree groups ordered most-central-first, so a foundational contract change lands before the commits that depend on it). Before Phase 2 dispatch, two grouping tiebreaks reduce Phase 3 conflicts at the root: a **file-ownership** tiebreak (rank: `linting-expert < doc-scribe < qa-specialist < perf-optimizer < sw-engineer < solution-architect`) reassigns every item touching a contested file to its single highest-ranked owner, so two specialists never edit the same file concurrently; then a soft **import-coupling** merge co-locates items in different files when one imports the other (caught via codemap forward `deps` — a module's own imports, so recall isn't truncated by the caller-list cap), so a rename and its callers land in one worktree instead of silently diverging. The codemap maps are built once, concurrently with the read-only challenge phase, so grouping adds ~0 wall-clock. Any conflict that still slips through Phase 3 routes through the same semantic conflict-resolution as Step 5. A branch mutex blocks a second concurrent resolve run from racing the same tree, and a HEAD fingerprint taken before Phase 2 flags any external write that lands mid-flight so cherry-picks never stack silently on a moved base. Per-item verdicts and `[resolve No.N]` attribution unchanged throughout; soft cap 10 items per dispatch (AskUserQuestion beyond, hard cap 20); soft codemap blast-radius check flags callers of changed modules before Phase 2 dispatch

Resolve after `/review` on same PR: blast-radius check reuses per-module codemap answers review already computed, no re-query — review's persisted pre-flight batch split into freshness-stamped per-module artifacts (index `git_sha` + `scanned_at`); each module served from cache when stamp matches current index. Rebuilt index invalidates cache, resolve re-queries. Reuse measured as `reuse_ratio` (fraction of persisted answers actually reused). No review artifact or codemap plugin absent → every module cache miss, scan queries live — no behaviour change.

**Severity → triage type mapping** (report mode):

| Review severity         | Section                                                        | Resolve `type`                                                           |
| ----------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| CRITICAL / `[blocking]` | any                                                            | `[req]`                                                                  |
| HIGH                    | any                                                            | `[req]`                                                                  |
| MEDIUM                  | Architecture, Performance, API Design (code-related)           | `[req]`                                                                  |
| MEDIUM                  | Test Coverage, Documentation, Static Analysis, Codex Co-Review | `[suggest]`                                                              |
| LOW                     | any                                                            | `[suggest]` — grouped by topic when count exceeds ceiling, never dropped |

`[req]` items apply by default on bulk-action; `[suggest]` items need explicit selection. Security findings inherit severity from `/oss:review` (hardcoded secrets → CRITICAL, dep CVEs → HIGH) — no separate security category. LOW findings cluster into composite rows by logical theme when total exceeds AskUserQuestion ceiling (12 items); each composite carries full member bullet list in `full_comment_text`.

**Guard rails:**

- More than 15 required items → pauses, asks confirm before continuing
- More than 20 conflicted files → aborts, reports; you review manually
- Git push requires explicit confirmation before executing
- Core invariant: uses `git merge`, never `git rebase` — preserves history

Every resolve cycle closes with parallel `foundry:linting-expert` + `foundry:qa-specialist` passes before final report.

**Flags:**

| Flag               | Effect                                                                                                                                                                                                                                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--worktree`       | Opt-in. Wrap the whole run in an isolated git worktree (base: HEAD) entered before `gh pr checkout`, so the checkout, per-specialist worktrees, and cherry-picks never touch your main tree/branch. Commits still push to the fork as usual; the local worktree is disposable. Composes with resolve's existing per-specialist isolation. |
| `--keep "<items>"` | Append quoted string to compaction contract's `preserve:` line — items survive auto-compact mid-run (advanced; long multi-agent sessions)                                                                                                                                                                                                 |

**Output location:** `.reports/resolve/<timestamp>/`

______________________________________________________________________

### /release

SemVer-disciplined release pipeline. Six modes: from generating notes to auditing readiness.

**Purpose:** Cut release correctly — right version bump, complete changelog, migration guides where needed, readiness verified before tag goes out.

**Invocation:**

```text
/oss:release notes v1.2->HEAD                       # release notes from range
/oss:release notes --changelog                      # notes + CHANGELOG.md entry
/oss:release notes --summary                        # notes + internal summary
/oss:release notes v1.2->v2.0 --migration           # notes + migration guide
/oss:release notes --changelog --summary --migration  # all four outputs
/oss:release prepare v2.1.0                         # full pipeline: audit → all artifacts
/oss:release audit                                  # readiness check before tagging
/oss:release demo                                   # story-telling notebook for the release
/oss:release demo v1.2->v2.0                        # demo scoped to explicit range
```

Range notation: `v1->v2` (e.g. `v1.2->v2.0`). Omit range → defaults to `last-tag..HEAD`. Pre-release tags (`rcN`, `devN`, `alphaN`, `betaN`) excluded from tag detection automatically.

**Modes and flags:**

| Mode / Flag   | What it produces                                                                                                                          |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `notes`       | Release notes (`DRAFT.md`); add flags for extra outputs                                                                                   |
| `--changelog` | CHANGELOG.md entry (no shepherd review)                                                                                                   |
| `--summary`   | Internal summary saved to `.temp/`                                                                                                        |
| `--migration` | Migration guide for breaking changes saved to `.temp/` (shepherd review)                                                                  |
| `prepare`     | Full pipeline: audit → all four artifacts + `demo.py` in `releases/<version>/`                                                            |
| `audit`       | Readiness checklist: tests green, changelog present, version bumped, no uncommitted changes, doc proportionality for newly added features |
| `demo`        | Story-telling jupytext notebook (`demo.py`) highlighting most significant contributions                                                   |

**What each mode does:**

| Primitive             | `notes`       | `prepare` | `audit` | `demo` |
| --------------------- | ------------- | --------- | ------- | ------ |
| Read git log + PRs    | full          | diff      | full    | full   |
| Classify changes      | ✓             | ✓         | -       | ✓      |
| Explore codebase      | full          | diff      | full    | diff   |
| Shepherd voice review | ✓             | ✓         | -       | -      |
| DRAFT.md              | write         | write     | -       | -      |
| CHANGELOG.md          | `--changelog` | write     | -       | -      |
| SUMMARY.md            | `--summary`   | write     | -       | -      |
| MIGRATION.md          | `--migration` | write¹    | -       | -      |
| demo.py               | -             | -         | -       | write² |
| Working tree          | -             | ✓         | ✓       | -      |
| CI status             | -             | ✓         | ✓       | -      |
| Open issues / PRs     | -             | ✓         | ✓       | -      |
| Docs alignment        | -             | diff      | full    | -      |
| Version consistency   | -             | ✓         | ✓       | -      |
| CVEs                  | -             | ✓         | ✓       | -      |

Flag mark = output produced only when flag passed. ¹ Full guide when breaking changes detected; single-line stub otherwise. ² Jupytext percent-format Python script with `# %%` code cells and `# %% [markdown]` narrative cells; self-contained with references to additional resources.

**SemVer enforcement:**

`oss:shepherd` validates proposed version bump against actual diff before anything written. Refuses to proceed if:

- `patch` bump proposed but diff contains breaking changes → should be `major`
- `minor` bump proposed but no new public API added → should be `patch`
- Version string not `MAJOR.MINOR.PATCH` format

**Breaking-change classification** (codemap-gated): after truth check, each diff-derived public symbol run through `fn-rdeps --exclude-tests`. Symbol with caller outside own top-level package → labelled **Breaking**, moved to ⚠ Breaking Changes with external call sites cited; symbol whose callers all inside own package stays under human label. Affected call-site list drafted into migration guide — downstream consumers see exactly what to change. Requires codemap v3 index — no index → phase skipped, human classification stands. Partial coverage (`query_complete:false`) surfaces evidence as possibly-incomplete, never drops it.

**CHANGELOG section ordering** (strict, enforced):

```text
Added → Breaking Changes → Changed → Deprecated → Removed → Fixed → 🔒 Security
```

**Deprecation tracking:** Uses `pyDeprecate` for deprecation lifecycle. Migration guides include before/after table with argument mapping for all renamed/removed parameters.

**Shepherd review** applies to release notes + migration guides. CHANGELOG entries + summaries written directly, no review.

**Output location:** `releases/<version>/` for `prepare` mode (including `demo.py` when version tag stable); `.temp/` for individual modes and demo on non-release branches.

______________________________________________________________________

## 🤖 Agents reference

### gh-scraper

**Role:** Raw GitHub data fetcher for `/oss:analyse vitality`. Fetches all GitHub API data (REST + GraphQL) across two parallel groups, writes raw JSONL consumed by oss:repo-warden axis scorers. Internal — spawned by oss:analyse vitality Step 1 only.

**Model:** Sonnet (focused data collection)

**What gh-scraper does:**

- Runs all GitHub API fetch calls parallel (Group 1), then Group 2 (README, CONTRIBUTING, workflow files, branch protection)
- Retries contributor stats (202 computing) up to 6× before writing partial record
- Writes `raw-data-{owner}-{repo}-{date}.jsonl` for reproducibility + scorer consumption

**What gh-scraper does NOT do:**

- Axis scoring → oss:repo-warden owns all axis scoring
- Report generation, terminal output, adversarial review → oss:analyse vitality Steps 4–7 own those
- Direct user invocation — always spawned by vitality skill

______________________________________________________________________

### repo-warden

**Role:** Axis scorer for `/oss:analyse vitality`. Reads pre-fetched raw JSONL from oss:gh-scraper, scores assigned group of vitality axes per vitality-scoring.md rubric; writes partial scores JSON for assembly. Spawned 3× parallel by oss:analyse vitality Step 2 — not for direct user invocation.

**Model:** Sonnet (focused computation)

**What repo-warden does:**

- Scores assigned axis group (A: Axes 1,2,5,6 / B: Axes 4,7,8 / C: Axes 3,9) from DATA_FILE
- Runs Axis 3 multi-pass confidence logic; applies fallback from commits_50 when contributor stats unavailable
- Writes `partial-{group}-{owner}-{repo}-{ts}.json` consumed by vitality Step 3 assembly

**What repo-warden does NOT do:**

- Raw data fetching → oss:gh-scraper owns all GitHub API calls
- Report generation, terminal output, adversarial review → oss:analyse vitality Steps 4–7 own those
- Direct user invocation — always spawned by vitality skill

______________________________________________________________________

### shepherd

**Role:** Public voice of project. Owns all external-facing communication — PR replies, issue responses, release notes, changelog entries, migration guides. Never writes implementation code.

**Model:** opusplan

**When to use shepherd directly:**

```bash
use shepherd to draft a response for issue #88, citing the contributing guide
use shepherd to review this changelog entry for tone before I post it
use shepherd to write a migration guide for the v3.0 breaking changes
```

**What shepherd does:**

- **Issue triage:** Classifies every issue into one of seven archetypes (bug confirmed, feature request, question/support, duplicate, stale, out of scope, breaking change), drafts response fitting each
- **Close-scenario replies:** Seven close archetypes from shepherd playbook — fixed in release, fixed on `develop`, superseded by architecture change, external/wrong repo, self-resolved/stale, keep open + relabel, superseded PR
- **PR review response:** Two-part format — leads with genuinely good, then specific actionable asks with line references; never adversarial
- **SemVer validation:** Reads actual diff, enforces correct bump type before any release proceeds
- **Release pipeline:** Writes release notes, changelog entries, migration guides in consistent project voice
- **Deprecation lifecycle:** Works with `pyDeprecate`; tracks deprecated APIs, writes migration guides, enforces deprecation → warning → removal timeline

**What shepherd does NOT do:**

- Inline docstrings or API reference docs → use `foundry:doc-scribe`
- CI pipeline configuration or GitHub Actions YAML structure for publish/release workflows → use `oss:cicd-steward`
- Implementation code of any kind

**Voice principles:**

- Leads with what's good
- Treats contributors as partners, never supplicants
- Cites specific conventions (contributing guide, coding style) when asking for changes
- Never adversarial, never dismissive of effort

______________________________________________________________________

### cicd-steward

**Role:** GitHub Actions health specialist. Owns CI configuration quality: workflow topology, runner strategy, caching, branch protections, flaky test detection.

**Model:** Sonnet (fast iteration on workflow YAML)

**When to use cicd-steward directly:**

```bash
use cicd-steward to reduce the build time in .github/workflows/ci.yml
use cicd-steward to diagnose the failing test matrix on PR #72
use cicd-steward to add SHA pinning to all actions in the workflow
```

**What cicd-steward does:**

- Diagnoses CI failures by failure type (linting, type errors, test failures, import errors, timeouts, OOM)
- Audits GitHub Actions workflow files for antipatterns (unpinned actions, missing concurrency groups, broken caching, wrong parallelism)
- Optimises build time toward targets: unit tests < 5 min, full CI < 15 min
- Enforces cache hit rate > 80% using `astral-sh/setup-uv` with `uv.lock`-keyed caching
- Detects + quarantines flaky tests (target: 0% flakiness)
- Configures test matrices, reusable workflows, nightly upstream CI, performance regression benchmarks

**SHA pinning enforcement** (cicd-steward flags these as primary findings):

| Severity  | Pattern              | Example                                                           |
| --------- | -------------------- | ----------------------------------------------------------------- |
| Critical  | Branch/named refs    | `uses: actions/checkout@main`                                     |
| High      | Mutable version tags | `uses: actions/checkout@v4`                                       |
| Compliant | Full 40-char SHA     | `uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` |

Short SHAs (fewer than 40 hex chars) treated as unpinned — can collide, not cryptographically safe.

**What cicd-steward does NOT do:**

- ruff/mypy rule selection or `.pre-commit-config.yaml` authoring → use `foundry:linting-expert` (IS for CI workflow steps that invoke pre-commit, e.g. `pre-commit/action@SHA`)
- PyPI release management, release notes, CHANGELOG entries, contributor communication → use `oss:shepherd`
- PyPI project registration, OIDC trusted publisher setup on pypi.org dashboard, GitHub environment configuration → use `oss:shepherd`

**Health targets:**

| Metric          | Target                                         |
| --------------- | ---------------------------------------------- |
| Main branch     | Green 100% of the time                         |
| Unit test suite | < 5 minutes                                    |
| Full CI         | < 15 minutes                                   |
| Cache hit rate  | > 80%                                          |
| Flaky tests     | 0% — any flaky test is quarantined immediately |

______________________________________________________________________

## ⚙️ Configuration

`oss` needs no required configuration — reads project structure automatically.

**GitHub authentication:** Skills use `gh` CLI. Run `gh auth login` once if not already.

**Optional plugin integrations** detected automatically at runtime. Install any optional plugin from [Install](#install) — skills use them next invocation, no config changes.

**Cache location:** `.cache/gh/` at project root. Cached responses: 30-day TTL. Force fresh fetch: delete relevant cache file or entire `.cache/gh/` directory.

**Artifact directories** created by `oss` skills:

| Directory             | Created by                    | Contents                                         |
| --------------------- | ----------------------------- | ------------------------------------------------ |
| `.reports/analyse/`   | `/oss:analyse`                | Thread, vitality, ecosystem reports              |
| `.temp/review/`       | `/oss:review`                 | Per-agent handover files (intermediate, per-run) |
| `.reports/resolve/`   | `/oss:resolve`                | Resolve run outputs                              |
| `.temp/`              | All skills                    | Long-form output files                           |
| `.cache/gh/`          | `/oss:analyse`, `/oss:review` | GitHub API response cache                        |
| `releases/<version>/` | `/oss:release prepare`        | Release artefacts                                |

All artifact directories gitignored (ephemeral, TTL-managed).

______________________________________________________________________

<a id="troubleshooting"></a>

<details>

<summary>

## 🔍 Troubleshooting

</summary>

## 🔍 Troubleshooting

**`/oss:review` skips Tier 2 agents**

Tier 2 runs only when Tier 1 (Codex pre-pass) finds no blocking issue alone. Tier 1 flags blocking → shows in report. Install `codex` plugin to enable pre-pass; without it, `/oss:review` goes directly to Tier 2.

**`/oss:review` uses general-purpose agents instead of specialist agents**

`foundry` plugin not installed or not detected. Install: `claude plugin install foundry@borda-ai-rig`. All skills degrade gracefully to general-purpose agents when `foundry` absent.

**`/oss:resolve` pauses mid-run asking for confirmation**

More than 15 required items found across sources. Intentional — resolve asks before applying large batch. Confirm to continue, or review item list, tell resolve which to skip.

**`/oss:resolve` aborts with "too many conflicted files"**

More than 20 files have semantic conflicts. Resolve aborts rather than guessing intent at scale. Review conflict list in output, resolve most complex manually, re-run resolve on remainder.

**`/oss:release` refuses to proceed with a proposed version bump**

`oss:shepherd` validated diff, found bump type incorrect. Output tells what bump type justified by actual changes. Adjust version argument, re-run.

**`/oss:analyse` returns stale data**

Cached GitHub API responses served from `.cache/gh/`. Delete cache file for specific thread number or clear `.cache/gh/` entirely for fresh fetch.

**Skills not found after install**

Run `claude plugin install oss@borda-ai-rig` again, then `/reload-plugins` in Claude Code.

______________________________________________________________________

</details>

<a id="contributing--feedback"></a>

## 🙏 Contributing / feedback

`oss` = part of Borda-AI-Rig plugin suite. Contribute or report issues:

- **Bugs and feature requests:** Open issue in Borda-AI-Rig repository
- **Plugin authoring rules:** See `plugins/CLAUDE.md` — file layout, naming conventions, cross-plugin references, README sync requirements, versioning policy
- **Voice and tone:** All contributor-facing text follows same principles as `oss:shepherd` — welcoming, specific, treats contributors as partners

Editing `oss` skills or agents → update this README before commit. Rule in `plugins/CLAUDE.md`: changed trigger, scope, NOT-for, or hook behaviour → update README description. Added/removed agent/skill → update table. Unsynced change = incomplete.
