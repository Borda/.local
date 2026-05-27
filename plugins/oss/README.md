# 🌱 oss — Claude Code Plugin

OSS workflow plugin for Python/ML open-source projects. Two specialist agents and four slash-command skills covering issue analysis, parallel code review, PR resolution, and SemVer-disciplined releases.

> Works standalone — `foundry` is not required. Without it, agent dispatches fall back to `general-purpose` with role descriptions (lower quality). Installing `foundry` unlocks specialized agents (`foundry:sw-engineer`, `foundry:qa-specialist`, etc.) and is strongly recommended for production use.

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

`oss` is a Claude Code plugin for maintainers of Python and ML open-source projects. It gives you four slash-command skills — analyse, review, resolve, release — and two specialist agents that own contributor communication and CI health. Together they cover the recurring, expensive parts of the maintainer loop: triaging GitHub threads, reviewing PRs with multiple expert perspectives, closing review feedback in one pass, and cutting releases with correct SemVer and complete changelogs.

______________________________________________________________________

## 🎯 Why oss?

Maintaining an open-source project means juggling three competing demands: reviewing code carefully enough to catch regressions, responding to contributors quickly enough that they stay engaged, and shipping releases confidently enough that users upgrade. Each of these is a context-switch tax.

`oss` removes that tax. Here is what it actually does for you:

**You review a PR in minutes, not hours.** `/oss:review` runs a Codex pre-pass in about 60 seconds. Trivial PRs close right there. For anything substantive, six specialist agents fan out in parallel — architecture, tests, performance, docs, linting, security — and hand you a ranked, consolidated report. You get expert-level coverage without reading every line yourself.

**Contributors get a real response, fast.** The `--reply` flag drafts a welcoming comment in your project's voice, citing your specific conventions. You spend 30 seconds reviewing it instead of 10 minutes writing from scratch. Contributors feel heard; they stay engaged.

**Review feedback gets applied completely.** `/oss:resolve` closes the gap between "reviewer said X" and "X is in the code." It reads live PR comments, a saved review report, or both, deduplicates across sources, resolves conflicts semantically (not by picking a side mechanically), and implements everything in batches with `[resolve #N]` tags so you can trace each fix.

**Releases go out correctly.** `oss:shepherd` enforces SemVer before any tag lands. It writes the changelog with deprecation tracking, generates migration guides for breaking changes, and runs a readiness audit. No accidental major bumps. No forgotten changelog entries.

**Triage is fast and structured.** `/oss:analyse vitality` gives you a repo vitality scorecard with duplicate issue clustering and stale PR detection every morning. Drilling into a specific thread gives you a structured summary you can act on immediately.

______________________________________________________________________

## 📦 Install

```bash
# Run from the directory that CONTAINS your Borda-AI-Rig clone
claude plugin marketplace add ./Borda-AI-Rig
claude plugin install oss@borda-ai-rig
```

Install the full suite for best results:

```bash
claude plugin install foundry@borda-ai-rig   # base agents — strongly recommended
claude plugin install oss@borda-ai-rig
claude plugin install develop@borda-ai-rig
claude plugin install research@borda-ai-rig
```

**Optional integrations** (unlock additional capabilities inside `oss` skills):

| Plugin    | What it unlocks                                                                                                                                             |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `foundry` | Specialized review agents (sw-engineer, qa-specialist, perf-optimizer, doc-scribe, solution-architect, linting-expert) instead of general-purpose fallbacks |
| `codex`   | Action item implementation in `/oss:resolve` Step 8; Tier 1 pre-pass in `/oss:review`                                                                       |
| `codemap` | Reverse-dependency count (`rdep_count`) in `/oss:review` risk assessment                                                                                    |

All `oss` skills degrade gracefully when optional plugins are absent — you get reduced capability, not broken commands.

> **Note:** Skills are always invoked with the `oss:` prefix: `/oss:analyse`, `/oss:review`, `/oss:resolve`, `/oss:release`.

<details>

<summary><strong>Upgrade</strong></summary>

```bash
cd Borda-AI-Rig && git pull
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

Analyse GitHub threads and repo vitality. Accepts an issue or PR number, the keyword `vitality`, the keyword `ecosystem`, or a path to a saved report file.

**Purpose:** Give you a structured, actionable summary of any GitHub thread or a broad view of your repo's open work. Saves you from reading every comment yourself.

**Auto-invokes when:** user provides a GitHub issue/PR number (`#N`) or `github.com` URL and asks to analyze, summarize, or triage it; user asks "is this repo healthy" or for vitality stats.

**Invocation:**

```text
/oss:analyse 123              # issue, PR, or discussion by number
/oss:analyse vitality         # repo vitality: 9-axis health scorecard, duplicate clustering, raw data JSONL
/oss:analyse ecosystem        # dependency health, upstream compatibility
/oss:analyse path/to/report.md  # re-analyse a saved report
```

**Flags:**

| Flag      | Effect                                                                                                   |
| --------- | -------------------------------------------------------------------------------------------------------- |
| `--reply` | Draft a contributor-facing response after analysis (routed through `oss:shepherd` for voice consistency) |

**What it does:**

For a thread number, `analyse` fetches the issue or PR, reads all comments, classifies the thread type (bug report, feature request, question, duplicate, stale), and produces a structured summary: what was asked, what the current state is, what action is needed from you, and — with `--reply` — a draft response.

For `vitality`, it pulls open issues and PRs, scores repo vitality across 9 axes (Axes 1–8 plus Axis 9 Trajectory), clusters duplicates, flags threads stale beyond your project's threshold, and gives you a prioritised triage list with a weighted Health Score %. All raw API data is saved to a JSONL file alongside the report for manual inspection.

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

GitHub API responses are cached in `.cache/gh/` by number and date (30-day TTL) — repeated calls on the same thread are fast.

______________________________________________________________________

### /review

Tiered parallel review of a GitHub PR. Input is always a PR number.

**Purpose:** Give you expert-level review coverage across architecture, tests, performance, docs, linting, and security — without reading every line yourself. Produces a ranked findings report. Optionally drafts a welcoming contributor comment.

**Invocation:**

```text
/oss:review 55                # full tiered review — saves findings report
/oss:review 55 --reply        # review + draft contributor-facing comment
```

> To review local files or the current git diff without a PR, use `/develop:review` from the `develop` plugin.

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

Without `foundry`, Tier 2 falls back to general-purpose agents with role descriptions — still functional, lower quality.

**Output locations:**

- Per-agent handover files (intermediate): `.temp/review/<timestamp>/`
- Consolidated report: `.reports/review/<timestamp>/review-report.md`
- Reply draft (with `--reply`): `.temp/output-reply-<PR#>-<date>.md`

**Flags:**

| Flag      | Effect                                                                                                                             |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `--reply` | After consolidation, `oss:shepherd` drafts a welcoming two-part PR comment (positive framing first, then specific actionable asks) |

______________________________________________________________________

### /resolve

Apply review findings to the codebase. Reads from live PR comments, a saved review report, or both — deduplicates, resolves conflicts, and implements fixes.

**Purpose:** Close the gap between "reviewer said X" and "X is in the code." One command takes you from open findings to committed fixes.

**Invocation:**

```text
/oss:resolve 55                # pr mode — apply fixes from live GitHub PR comments
/oss:resolve report            # report mode — apply fixes from the saved /oss:review report
/oss:resolve 55 report         # pr + report mode — both sources, deduplicated
/oss:resolve                   # review-handoff mode — picks up from the last /oss:review run
```

**Source modes:**

| Arguments        | Mode           | Source                            | When to use                                                        |
| ---------------- | -------------- | --------------------------------- | ------------------------------------------------------------------ |
| `55` (PR number) | pr             | Live GitHub PR comments           | Apply feedback posted directly on GitHub                           |
| `report`         | report         | Saved `/oss:review` findings file | Apply findings from your last review run                           |
| `55 report`      | pr + report    | Both, aggregated                  | Full close — deduplicates across both inputs                       |
| _(none)_         | review-handoff | Review-handoff                    | Continues directly from the last `/oss:review` run in this session |

**How it works:**

Resolve runs in three phases:

1. **Intelligence gathering** — a dedicated subagent fetches the full PR thread (comments, reviews, inline code comments) so the orchestrator context stays small; subagent classifies each finding and writes structured output to files; orchestrator reads the compact classified table
2. **Conflict resolution** — for merge conflicts, read intent from both sides; apply the semantically correct resolution (never mechanical "take ours" or "take theirs")
3. **Action item implementation** — each item dispatched to Codex (or appropriate foundry agent per change type and complexity); soft codemap blast-radius check runs after the loop to flag callers of changed modules

**Guard rails:**

- More than 15 required items → pauses and asks you to confirm before continuing
- More than 20 conflicted files → aborts and reports; you review manually
- Git push requires explicit confirmation via before executing
- Core invariant: uses `git merge`, never `git rebase` — preserves history

Every resolve cycle closes with parallel `foundry:linting-expert` + `foundry:qa-specialist` passes before the final report.

**Output location:** `.reports/resolve/<timestamp>/`

______________________________________________________________________

### /release

SemVer-disciplined release pipeline. Six modes covering every step from generating notes to auditing readiness.

**Purpose:** Cut a release correctly — right version bump, complete changelog, migration guides where needed, readiness verified before the tag goes out.

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

Range notation: `v1->v2` (e.g. `v1.2->v2.0`). Omit range → defaults to `last-tag..HEAD`. Pre-release tags (`rcN`, `devN`, `alphaN`, `betaN`) are excluded from tag detection automatically.

**Modes and flags:**

| Mode / Flag   | What it produces                                                                            |
| ------------- | ------------------------------------------------------------------------------------------- |
| `notes`       | Release notes (`PUBLIC-NOTES.md`); add flags for extra outputs                              |
| `--changelog` | CHANGELOG.md entry (no shepherd review)                                                     |
| `--summary`   | Internal summary saved to `.temp/`                                                          |
| `--migration` | Migration guide for breaking changes saved to `.temp/` (shepherd review)                    |
| `prepare`     | Full pipeline: audit → all four artifacts + `demo.py` in `releases/<version>/`              |
| `audit`       | Readiness checklist: tests green, changelog present, version bumped, no uncommitted changes |
| `demo`        | Story-telling jupytext notebook (`demo.py`) highlighting most significant contributions     |

**What each mode does:**

| Primitive             | `notes`       | `prepare` | `audit` | `demo` |
| --------------------- | ------------- | --------- | ------- | ------ |
| Read git log + PRs    | full          | diff      | full    | full   |
| Classify changes      | ✓             | ✓         | -       | ✓      |
| Explore codebase      | full          | diff      | full    | diff   |
| Shepherd voice review | ✓             | ✓         | -       | -      |
| PUBLIC-NOTES.md       | write         | write     | -       | -      |
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

Flag mark = output produced only when that flag is passed. ¹ Full guide when breaking changes detected; single-line stub otherwise. ² Jupytext percent-format Python script with `# %%` code cells and `# %% [markdown]` narrative cells; self-contained with references to additional resources.

**SemVer enforcement:**

`oss:shepherd` validates the proposed version bump against the actual diff before anything is written. It refuses to proceed if:

- A `patch` bump is proposed but the diff contains breaking changes → should be `major`
- A `minor` bump is proposed but no new public API was added → should be `patch`
- Version string does not follow `MAJOR.MINOR.PATCH` format

**CHANGELOG section ordering** (strict, enforced):

```text
Added → Breaking Changes → Changed → Deprecated → Removed → Fixed → 🔒 Security
```

**Deprecation tracking:** Uses `pyDeprecate` for the deprecation lifecycle. Migration guides include a before/after table with argument mapping for all renamed or removed parameters.

**Shepherd review** applies to release notes and migration guides. CHANGELOG entries and summaries are written directly without review.

**Output location:** `releases/<version>/` for `prepare` mode (including `demo.py` when version tag is stable); `.temp/` for individual modes and demo on non-release branches.

______________________________________________________________________

## 🤖 Agents reference

### gh-scraper

**Role:** Raw GitHub data fetcher for `/oss:analyse vitality`. Fetches all GitHub API data (REST + GraphQL) across two parallel groups, writes raw JSONL data file consumed by oss:repo-warden axis scorers. Internal — spawned by oss:analyse vitality Step 1 only.

**Model:** Sonnet (focused data collection)

**What gh-scraper does:**

- Runs all GitHub API fetch calls in parallel (Group 1) then Group 2 (README, CONTRIBUTING, workflow files, branch protection)
- Retries contributor stats (202 computing) up to 6× before writing partial record
- Writes `raw-data-{owner}-{repo}-{date}.jsonl` for reproducibility and scorer consumption

**What gh-scraper does NOT do:**

- Axis scoring of any kind → oss:repo-warden owns all axis scoring
- Report generation, terminal output, or adversarial review → oss:analyse vitality Steps 4–7 own those
- Direct user invocation — always spawned by the vitality skill

______________________________________________________________________

### repo-warden

**Role:** Axis scorer for `/oss:analyse vitality`. Reads pre-fetched raw JSONL from oss:gh-scraper and scores an assigned group of vitality axes per the vitality-scoring.md rubric; writes partial scores JSON for assembly. Spawned 3× in parallel by oss:analyse vitality Step 2 — not for direct user invocation.

**Model:** Sonnet (focused computation)

**What repo-warden does:**

- Scores assigned axis group (A: Axes 1,2,5,6 / B: Axes 4,7,8 / C: Axes 3,9) from DATA_FILE
- Runs the Axis 3 multi-pass confidence logic; applies fallback from commits_50 when contributor stats unavailable
- Writes `partial-{group}-{owner}-{repo}-{ts}.json` consumed by vitality Step 3 assembly

**What repo-warden does NOT do:**

- Raw data fetching → oss:gh-scraper owns all GitHub API calls
- Report generation, terminal output, or adversarial review → oss:analyse vitality Steps 4–7 own those
- Direct user invocation — always spawned by the vitality skill

______________________________________________________________________

### shepherd

**Role:** The public voice of your project. Shepherd owns all external-facing communication — PR replies, issue responses, release notes, changelog entries, and migration guides. It never writes implementation code.

**Model:** opusplan

**When to use shepherd directly:**

```bash
use shepherd to draft a response for issue #88, citing the contributing guide
use shepherd to review this changelog entry for tone before I post it
use shepherd to write a migration guide for the v3.0 breaking changes
```

**What shepherd does:**

- **Issue triage:** Classifies every issue into one of seven archetypes (bug confirmed, feature request, question/support, duplicate, stale, out of scope, breaking change) and drafts a response appropriate to each
- **Close-scenario replies:** Uses seven close archetypes from the shepherd playbook — fixed in a release, fixed on `develop`, superseded by architecture change, external/wrong repo, self-resolved/stale, keep open + relabel, and superseded PR
- **PR review response:** Two-part format — leads with what is genuinely good, then gives specific actionable asks with line references; never adversarial
- **SemVer validation:** Reads the actual diff and enforces correct bump type before any release proceeds
- **Release pipeline:** Writes release notes, changelog entries, and migration guides in consistent project voice
- **Deprecation lifecycle:** Works with `pyDeprecate`; tracks deprecated APIs, writes migration guides, enforces the deprecation → warning → removal timeline

**What shepherd does NOT do:**

- Inline docstrings or API reference docs → use `foundry:doc-scribe`
- CI pipeline configuration or GitHub Actions YAML structure for publish/release workflows → use `oss:cicd-steward`
- Implementation code of any kind

**Voice principles:**

- Leads with what is good
- Treats contributors as partners, never supplicants
- Cites specific conventions (contributing guide, coding style) when asking for changes
- Never adversarial, never dismissive of effort

______________________________________________________________________

### cicd-steward

**Role:** GitHub Actions health specialist. Owns CI configuration quality: workflow topology, runner strategy, caching, branch protections, and flaky test detection.

**Model:** Haiku (fast iteration on workflow YAML)

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
- Detects and quarantines flaky tests (target: 0% flakiness)
- Configures test matrices, reusable workflows, nightly upstream CI, and performance regression benchmarks

**SHA pinning enforcement** (cicd-steward flags these as primary findings):

| Severity  | Pattern              | Example                                                           |
| --------- | -------------------- | ----------------------------------------------------------------- |
| Critical  | Branch/named refs    | `uses: actions/checkout@main`                                     |
| High      | Mutable version tags | `uses: actions/checkout@v4`                                       |
| Compliant | Full 40-char SHA     | `uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` |

Short SHAs (fewer than 40 hex characters) are treated as unpinned — they can collide and are not cryptographically safe.

**What cicd-steward does NOT do:**

- ruff/mypy rule selection or `.pre-commit-config.yaml` authoring → use `foundry:linting-expert` (IS for CI workflow steps that invoke pre-commit, e.g. `pre-commit/action@SHA`)
- PyPI release management, release notes, CHANGELOG entries, or contributor communication → use `oss:shepherd`
- PyPI project registration, OIDC trusted publisher setup on pypi.org dashboard, or GitHub environment configuration → use `oss:shepherd`

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

`oss` has no required configuration — it reads your project structure automatically.

**GitHub authentication:** Skills use the `gh` CLI. Run `gh auth login` once if you have not already.

**Optional plugin integrations** are detected automatically at runtime. Install any of the optional plugins listed in [Install](#install) and the skills will use them on the next invocation — no config changes needed.

**Cache location:** `.cache/gh/` at project root. Cached responses have a 30-day TTL. To force a fresh fetch, delete the relevant cache file or the entire `.cache/gh/` directory.

**Artifact directories** created by `oss` skills:

| Directory             | Created by                    | Contents                                         |
| --------------------- | ----------------------------- | ------------------------------------------------ |
| `.reports/analyse/`   | `/oss:analyse`                | Thread, vitality, ecosystem reports              |
| `.temp/review/`       | `/oss:review`                 | Per-agent handover files (intermediate, per-run) |
| `.reports/resolve/`   | `/oss:resolve`                | Resolve run outputs                              |
| `.temp/`              | All skills                    | Long-form output files                           |
| `.cache/gh/`          | `/oss:analyse`, `/oss:review` | GitHub API response cache                        |
| `releases/<version>/` | `/oss:release prepare`        | Release artefacts                                |

All artifact directories are gitignored (ephemeral, TTL-managed).

______________________________________________________________________

<a id="troubleshooting"></a>

<details>

<summary>

## 🔍 Troubleshooting

</summary>

## 🔍 Troubleshooting

**`/oss:review` skips Tier 2 agents**

Tier 2 only runs when Tier 1 (Codex pre-pass) does not surface a blocking issue on its own. If Tier 1 flags something blocking, you will see it in the report. Install the `codex` plugin to enable the pre-pass; without it, `/oss:review` goes directly to Tier 2.

**`/oss:review` uses general-purpose agents instead of specialist agents**

`foundry` plugin is not installed or not detected. Install it with `claude plugin install foundry@borda-ai-rig`. All skills degrade gracefully to general-purpose agents when `foundry` is absent.

**`/oss:resolve` pauses mid-run asking for confirmation**

More than 15 required items were found across the sources. This is intentional — resolve asks before applying a large batch. Confirm to continue, or review the item list and tell resolve which items to skip.

**`/oss:resolve` aborts with "too many conflicted files"**

More than 20 files have semantic conflicts. Resolve aborts rather than guessing at intent at scale. Review the conflict list in the output, resolve the most complex ones manually, then re-run resolve on the remainder.

**`/oss:release` refuses to proceed with a proposed version bump**

`oss:shepherd` validated the diff and found the bump type is incorrect. The output will tell you what bump type is justified by the actual changes. Adjust your version argument and re-run.

**`/oss:analyse` returns stale data**

Cached GitHub API responses are served from `.cache/gh/`. Delete the cache file for the specific thread number or clear `.cache/gh/` entirely for a fresh fetch.

**Skills not found after install**

Run `claude plugin install oss@borda-ai-rig` again from the directory containing your Borda-AI-Rig clone, then `/reload-plugins` in Claude Code.

______________________________________________________________________

</details>

<a id="contributing--feedback"></a>

## 🙏 Contributing / feedback

`oss` is part of the Borda-AI-Rig plugin suite. To contribute or report issues:

- **Bugs and feature requests:** Open an issue in the Borda-AI-Rig repository
- **Plugin authoring rules:** See `plugins/CLAUDE.md` — covers file layout, naming conventions, cross-plugin references, README sync requirements, and versioning policy
- **Voice and tone:** All contributor-facing text follows the same principles as `oss:shepherd` — welcoming, specific, treats contributors as partners

When editing `oss` skills or agents, update this README before the commit. The rule in `plugins/CLAUDE.md` is: changed trigger, scope, NOT-for, or hook behaviour → update the README description. Added or removed agent/skill → update the table. Unsynced change = incomplete.
