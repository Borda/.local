# 🏠 Borda's AI-Rig

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg) [![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-orange)](https://claude.ai/code) [![Codex CLI](https://img.shields.io/badge/Codex_CLI-config-green)](https://github.com/openai/codex)

Specialist-agent infrastructure for Python/ML OSS — the scaffolding that lets you maintain at scale without becoming a full-time reviewer.

**14 specialist agents · 20+ slash-command workflows · 5 domain plugins** — opinionated [Claude Code](https://claude.ai/code) + [Codex CLI](https://github.com/openai/codex) configuration for Python/ML OSS maintainers, version-controlled and self-calibrating.

<details>
<summary><strong>Contents</strong></summary>

- [🚀 What This Setup Enables](#-what-this-setup-enables)
- [⚡ Quick Start](#-quick-start)
- [🔁 Daily OSS Workflow](#-daily-oss-workflow)
- [🎯 Why](#-why)
- [💡 Design Principles](#-design-principles)
- [🧩 Agents](#-agents)
- [🤖 Claude Code](#-claude-code)
- [🤖 Codex CLI](#-codex-cli)
- [🤝 Claude + Codex Integration](#-claude--codex-integration)
- [🛠 Recommended Add-ons](#-recommended-add-ons)
- [📦 What's Here](#-whats-here)
- [🔌 Plugin Management](#-plugin-management)

</details>

## 🚀 What This Setup Enables

Things not possible with vanilla Claude Code:

- **Parallel multi-specialist PR review with convergence callouts.** `/oss:review` fans six specialist agents — architecture, tests, perf, docs, lint, security — plus an independent Codex pre-pass, all running simultaneously. The consolidator flags every finding that two or more reviewers independently raised. You see both per-dimension analysis and the overlap, in one report.

- **Feature development that cannot skip the demo test.** `/develop:feature` requires a failing demo test to exist and pass review before a single line of production code is written. The gate is structural — the workflow does not proceed to implementation without it.

- **Metric-driven experiment loops that auto-rollback on regression.** `/research:run` proposes a change, applies it, measures the target metric, and automatically reverts if the metric regresses — then tries the next hypothesis. The loop runs unattended; you set the goal and the guard, and review the committed result.

- **Agent calibration benchmarks that measure overconfidence and fix it.** `/foundry:calibrate` generates synthetic problems, scores each agent's responses against ground truth, and computes the gap between stated confidence and actual recall. Agents that are systematically overconfident get concrete fix proposals — applied automatically with `--apply`.

### vs. vanilla Claude Code

| Capability             | Vanilla Claude Code                   | Borda's AI-Rig                                                                          |
| ---------------------- | ------------------------------------- | --------------------------------------------------------------------------------------- |
| Code review            | Generalist single pass                | 6 specialists in parallel + Codex pre-pass; convergence callouts                        |
| Context flooding       | Context fills up across long sessions | File-based handoff — agents write full output to disk, return compact envelopes         |
| Confidence calibration | No mechanism                          | `/foundry:calibrate` benchmarks recall vs stated confidence; auto-apply fixes           |
| Demo-test gate         | Skippable                             | Structural gate — `/develop:feature` cannot proceed without passing demo test           |
| ML experiment safety   | Manual rollback                       | `/research:run` auto-reverts regressions; goal + guard are explicit inputs              |
| Release discipline     | Manual                                | SemVer-aware `/oss:release` with deprecation tracking, migration guide, readiness audit |
| Token efficiency       | Default verbosity                     | RTK hook compresses Bash output 60–99%; caveman plugin cuts response tokens ~75%        |

## ⚡ Quick Start

```bash
# Install Claude Code
npm install -g @anthropic-ai/claude-code

# 1. Register from GitHub (no clone needed)
claude plugin marketplace add Borda/AI-Rig

# 2. Install plugins — pick what you need
claude plugin install foundry@borda-ai-rig   # base agents + audit, manage, calibrate, brainstorm, …
claude plugin install oss@borda-ai-rig       # OSS workflow: analyse, review, resolve, release
claude plugin install develop@borda-ai-rig   # development: feature, fix, refactor, plan, debug
claude plugin install research@borda-ai-rig  # ML research: topic, plan, judge, run, sweep
claude plugin install codemap@borda-ai-rig   # structural index: import graph, blast-radius scores
```

> [!NOTE]
>
> **Safe to install alongside any existing Claude Code setup.** Plugins live in a private cache (`~/.claude/plugins/cache/<plugin>/`) under their own namespace. Your existing `~/.claude/agents/`, `~/.claude/skills/`, and `settings.json` are never modified or overwritten — custom agents and skills you have created remain fully independent. See the [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference) for details.

**3. One-time settings merge** — run inside Claude Code:

```text
/foundry:setup
```

OSS, develop, and research skills always use their plugin prefix (`/oss:review`, `/develop:fix`, `/research:run`). Safe to re-run.

> [!IMPORTANT]
>
> **Codex CLI** — optional companion; requires a local clone (`.codex/` config is not a plugin):
>
> ```bash
> git clone https://github.com/Borda/AI-Rig Borda-AI-Rig
> npm install -g @openai/codex
> cp -r Borda-AI-Rig/.codex/ ~/.codex/   # Codex agents and profiles
> ```

→ See [Token Savings (RTK)](#-token-savings-rtk) for RTK install details.

## 🔁 Daily OSS Workflow

A typical maintainer morning — 15 new issues, 3 PRs waiting, a release due:

```text
# 1. Morning triage — what needs attention?
/oss:analyse health                # repo overview, duplicate issue clustering, stale PR detection

# 2. Review incoming PRs
/oss:review 55 --reply             # 7-agent review + welcoming contributor comment

# — or: full review first, then apply every finding in one automated pass
/oss:review 21                     # 7-agent review → saved findings report
/oss:resolve 21 report             # Codex reads the report and applies every comment

# 3. Fix the critical bug from overnight
/oss:analyse 42                    # understand the issue
/develop:fix 42                    # reproduce → regression test → minimal fix → quality stack

# 4. Ship the release
/oss:release prepare v2.1.0        # changelog, notes, migration guide, readiness audit
```

Each command chains agents in a defined topology — see [Common Workflow Sequences](#common-workflow-sequences) below for more patterns.

## 🎯 Why

**Without AI-Rig**: one generalist handles architecture, implementation, documentation, linting, testing, and performance with no boundary enforcement. A PR review misses the cache race condition because nobody ran the right checklist. The release gets wrong SemVer because nobody counted the breaking changes. ML experiments run without a judge gate and silently fail to improve anything. Corrections evaporate between sessions.

**With AI-Rig**: each part of the loop has a dedicated skill backed by a calibrated specialist agent. The agents know your conventions, enforce discipline at every gate, and feed corrections back into their own instructions. The feedback loop is closed.

Managing AI coding workflows for Python/ML OSS is complex — you need domain-aware agents, not generic chat. This config packages 14 specialist agents and 20+ slash-command skill workflows across five focused plugins, in a version-controlled, continuously benchmarked setup optimized for:

- Python/ML OSS libraries requiring SemVer discipline and deprecation cycles
- ML training and inference codebases needing GPU profiling and data pipeline validation
- Multi-contributor projects with CI/CD, pre-commit hooks, and automated releases

A typical maintainer morning — 15 issues, 3 PRs, a release due — handled in one session with four commands (see Daily OSS Workflow above).

## 💡 Design Principles

- **Agents are roles, skills are workflows** — agents carry domain expertise, skills orchestrate multi-step processes
- **No duplication** — agents reference each other instead of repeating content
- **Profile-first, measure-last** — performance skills always bracket changes with measurements
- **Link integrity** — never cite a URL without fetching it first (enforced in all research agents)
- **Python 3.10+ baseline** — all configs target py310 minimum (3.9 EOL was Oct 2025)
- **Modern toolchain** — uv, ruff, mypy, pytest, GitHub Actions with trusted publishing

## 🧩 Agents

<details>
<summary><strong>14 specialist agents (expand)</strong></summary>

Specialist roles with deep domain knowledge — requested by name, or auto-selected by Claude Code and Codex CLI.

| Agent                  | Claude [plugins] | Codex | Purpose                                                                                                                                                                               |
| ---------------------- | ---------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **doc-scribe**         | 🟠 foundry       | ✓     | Google/Napoleon docstrings, Sphinx/mkdocs, API references                                                                                                                             |
| **linting-expert**     | 🟠 foundry       | ✓     | ruff, mypy, pre-commit, type annotations                                                                                                                                              |
| **perf-optimizer**     | 🟠 foundry       | —     | Profile-first CPU/GPU/memory/I/O, torch.compile                                                                                                                                       |
| **qa-specialist**      | 🟠 foundry       | ✓     | pytest, hypothesis, mutation testing, ML test patterns                                                                                                                                |
| **curator**            | 🟠 foundry       | ✓     | Config quality review, duplication detection, cross-ref audit                                                                                                                         |
| **solution-architect** | 🟠 foundry       | ✓     | System design, ADRs, API surface, migration plans                                                                                                                                     |
| **sw-engineer**        | 🟠 foundry       | ✓     | Architecture, implementation, SOLID principles, type safety                                                                                                                           |
| **web-explorer**       | 🟠 foundry       | ✓     | API version comparison, migration guides, PyPI tracking                                                                                                                               |
| **challenger**         | 🟠 foundry       | —     | Adversarial plan/architecture/code review; default-on in all develop skills + oss:review (`--no-challenge` to skip)                                                                   |
| **creator**            | 🟠 foundry       | —     | Blog posts, Marp slide decks, social threads, talk abstracts — four-beat narrative arc (Problem→Journey→Insight→Action) calibrated to audience; reads `/foundry:create` outline files |
| **cicd-steward**       | 🟢 oss           | ✓     | GitHub Actions, test matrices, flaky test detection, caching                                                                                                                          |
| **shepherd**           | 🟢 oss           | ✓     | Issue triage, PR review, SemVer, releases, trusted publishing                                                                                                                         |
| **data-steward**       | 🟣 research      | ✓     | Dataset versioning, split validation, leakage detection                                                                                                                               |
| **scientist**          | 🟣 research      | —     | Paper analysis, hypothesis generation, experiment design                                                                                                                              |

</details>

## 🤖 Claude Code

Agents and skills for [Claude Code](https://claude.ai/code) (Anthropic's AI coding CLI).

### Skills

<details>
<summary><strong>20+ slash-command skills reference (expand)</strong></summary>

Skills are multi-agent workflows invoked via slash commands. Each skill composes several agents in a defined topology.

After running `/foundry:setup`, foundry skills are available without a prefix. OSS, develop, and research skills always use their plugin prefix.

| Skill                     | What It Does                                                                                                                                                                                                            |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🟠 `/foundry:brainstorm`  | `/brainstorm <idea>` — clarifying questions → approaches → spec → curator review → approval gate; `breakdown <spec>` — ordered task table with per-task skill tags                                                      |
| 🟠 `/foundry:manage`      | Create, update, delete agents/skills/rules; manage `settings.json` permissions; auto type-detection and cross-ref propagation                                                                                           |
| 🟠 `/foundry:investigate` | Systematic diagnosis for unknown failures — env, tools, hooks, CI divergence; ranks hypotheses and hands off to the right skill                                                                                         |
| 🟠 `/foundry:session`     | Parking lot for diverging ideas — auto-parks unanswered questions and deferred threads; `resume` shows pending, `archive` closes, `summary` digests the session                                                         |
| 🟠 `/foundry:audit`       | Config audit: broken refs, inventory drift, docs freshness; fix level chosen from always-fire follow-up gate; `--upgrade` applies docs-sourced improvements; `--adversarial` runs challenger + Codex review             |
| 🟠 `/foundry:calibrate`   | Synthetic benchmarks measuring recall vs confidence bias                                                                                                                                                                |
| 🟠 `/foundry:distill`     | Suggest new agents/skills, prune memory, consolidate lessons into rules; `external <source>` analyses an external plugin/skill/agent resource and produces a scored adoption proposal with install-as-is recommendation |
| 🟠 `/foundry:create`      | Interactive outline co-creation for developer advocacy content — format, audience, arc, voice → `.plans/content/<slug>-outline.md`; hand-off to `foundry:creator` for one-shot generation                               |
| 🔵 `/develop:plan`        | Scope analysis and implementation planning without code changes                                                                                                                                                         |
| 🔵 `/develop:feature`     | TDD-first feature implementation: codebase analysis, demo test, TDD loop, docs, review                                                                                                                                  |
| 🔵 `/develop:fix`         | Reproduce-first bug fixes: regression test, minimal fix, quality stack                                                                                                                                                  |
| 🔵 `/develop:debug`       | Systematic debugging for known test failures                                                                                                                                                                            |
| 🔵 `/develop:refactor`    | Test-first refactors with scope analysis                                                                                                                                                                                |
| 🔵 `/develop:review`      | Six-agent parallel review of local files or current git diff; no GitHub PR needed                                                                                                                                       |
| 🟢 `/oss:analyse`         | GitHub thread analysis; `health` = repo overview + duplicate issue clustering                                                                                                                                           |
| 🟢 `/oss:review`          | Tiered parallel review of GitHub PRs; `--reply` drafts welcoming contributor comments                                                                                                                                   |
| 🟢 `/oss:resolve`         | OSS fast-close: resolving conflicts + applying review comments via codex-plugin-cc; three source modes: `pr`, `report`, `pr + report`                                                                                   |
| 🟢 `/oss:release`         | SemVer-disciplined release pipeline: notes, changelog with deprecation tracking, migration guides, full prepare pipeline                                                                                                |
| 🟣 `/research:topic`      | SOTA literature research with codebase-mapped implementation plan                                                                                                                                                       |
| 🟣 `/research:plan`       | Config wizard: profile-first bottleneck discovery → `program.md`                                                                                                                                                        |
| 🟣 `/research:judge`      | Research-supervisor review of experimental methodology (APPROVED/NEEDS-REVISION/BLOCKED)                                                                                                                                |
| 🟣 `/research:run`        | Metric-driven iteration loop; `--resume` continues after crash; `--team` for parallel exploration; `--colab` for GPU workloads                                                                                          |
| 🟣 `/research:sweep`      | Non-interactive pipeline: auto-plan → judge gate → run                                                                                                                                                                  |

→ Full command reference, orchestration flows, rules (10 auto-loaded rule files), architecture internals, status line — see [`.claude/README.md` → Skills](.claude/README.md#-skills)

</details>

### Common Workflow Sequences

Skills chain naturally — the output of one becomes the input for the next.

<details>
<summary><strong>Bug report → fix → validate</strong></summary>

```text
/oss:analyse 42            # understand the issue, extract root cause hypotheses
/develop:fix 42            # reproduce with test, apply targeted fix
/oss:review                # validate the fix meets quality standards
```

</details>

<details>
<summary><strong>Code review → fix blocking issues</strong></summary>

```text
/oss:review 55                                           # 7 agent dimensions + Codex co-review
/develop:fix "race condition in cache invalidation"      # fix blocking issue from review
/oss:review 55                                           # re-review after fix
```

</details>

<details>
<summary><strong>Fuzzy idea → spec → breakdown → implement</strong></summary>

```text
/foundry:brainstorm "add caching layer to the data pipeline"
# clarifying questions → 2–3 approaches → spec saved to .plans/blueprint/ → curator review → approval

/foundry:brainstorm breakdown .plans/blueprint/2026-04-01-caching-layer.md
# reads spec → ordered task table with per-task skill/command tags:
#   | 1 | audit existing pipeline   | /foundry:audit             |
#   | 2 | implement caching layer   | /develop:feature           |
#   | 3 | run quality gates         | /develop:review            |

# then execute each row in the breakdown table using its tagged skill
```

</details>

<details>
<summary><strong>OSS contributor PR triage → review → reply</strong></summary>

Preferred flow for maintainers responding to external contributions:

```text
/oss:analyse 42 --reply      # assess PR readiness + draft contributor reply in one step

# or if you need the full deep review first:
/oss:review 42 --reply        # 7-agent + Codex co-review + draft overall comment + inline comments table
                              # output: .temp/output-reply-pr-42-dev-<date>.md

# post when ready:
gh pr comment 42 --body "$(cat .temp/output-reply-pr-42-dev-<date>.md)"
```

Both `--reply` flags produce a two-part shepherd output: an overall PR comment (prose, warm, decisive) and an inline comments table (file | line | 1–2 sentence fix). The `/oss:analyse` path is faster for routine triage; `/oss:review` gives deeper findings for complex PRs.

</details>

→ More sequences, full orchestration flows, and architecture internals: [`.claude/README.md`](.claude/README.md)

## 🤖 Codex CLI

Multi-agent configuration for [OpenAI Codex CLI](https://github.com/openai/codex). Default session model is `gpt-5.5`, with 14 specialist agents and a mirrored skill backbone (`review/develop/resolve/audit` + `calibrate/release/investigate/sync/manage/analyse/optimize/research`). Symptom-first failures route through `investigate` before implementation, and calibration emits measured recommendations for what to fix or improve next.

### Install

```bash
npm install -g @openai/codex          # install Codex CLI
cp -r Borda-AI-Rig/.codex/ ~/.codex/ # activate globally from the project source of truth
```

This repo's `.codex/` directory is the source of truth; `~/.codex/` is a downstream copy. After pulling updates, re-apply: `cp -r Borda-AI-Rig/.codex/ ~/.codex/` — or `rsync -av` to preserve local customizations.

### Usage

Mirrored skills are prompt-based — not slash commands:

```bash
codex                                                        # interactive — auto-selects agents
codex "use the qa-specialist to review src/api/auth.py"      # address agent by name
codex --profile deep-review "full security audit of src/api/" # activate a profile
```

```text
run investigate on this branch and find root cause of failing CI
run investigate before fixing this failing pytest; do not suggest a workaround unless it is explicitly temporary
run resolve for the current working tree and fix high-severity findings
```

→ Deep reference — agents, profiles, adversarial review, mirrored skills, RTK integration: [`.codex/README.md`](.codex/README.md)

## 🤝 Claude + Codex Integration

Claude and Codex complement each other — Claude handles long-horizon reasoning, orchestration, and judgment calls; Codex handles focused, mechanical in-repo coding tasks with direct shell access.

Every skill that reviews or validates code uses a three-tier pipeline:

- **Tier 0** (mechanical `git diff --stat` gate)
- **Tier 1** (codex:review pre-pass, ~60s, diff-focused)
- **Tier 2** (specialized Claude agents).

Cheaper tiers gate the expensive ones — this keeps full agent spawns reserved for diffs that actually need them. → Full architecture with skill-tier matrix: [`.claude/README.md` → Tiered review pipeline](.claude/README.md#tiered-review-pipeline)

**Why unbiased review matters / Real example**: Claude makes targeted changes with intentionality — it has a mental model of which files are "in scope". Codex has no such context: it reads the diff and the codebase independently. During one session, Claude applied a docstring-style mandate across 6 files and scored its own confidence at 0.88. The Codex pre-pass then found `skills/develop/modes/feature.md` still referencing the old style — a direct miss. The union of both passes is more complete than either alone.

### Two integration patterns make this pairing practical

1. **Offloading mechanical tasks from Claude to Codex**

   Claude identifies what needs to change and delegates execution to the plugin agent. Claude keeps its context clean and validates the output via `git diff HEAD`.

   Dispatched automatically by `/oss:review`, `/oss:resolve`, `/calibrate`, and `/research:run` via `codex-delegation.md`. The plugin agent has full working-tree access.

2. **Codex reviewing staged work**

   After Claude stages changes, `codex:review --wait` serves as a second pass — examining the diff, applying review comments, or resolving PR conflicts. The `/oss:resolve` skill automates this: it resolves conflicts semantically (Claude) then applies review comments (plugin agent).

   ```text
   /oss:resolve 42   # Claude resolves conflicts → plugin agent applies review comments
   /oss:resolve "rename the `fit` method to `train` throughout the module"
   ```

<details>
<summary><strong>Setup requirement</strong></summary>

Install the Codex plugin in Claude Code:

```text
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
```

Without the plugin: pre-pass review is skipped gracefully (skills check with `claude plugin list | grep 'codex@openai-codex'`); `/oss:resolve`'s review-comment step is skipped (conflict resolution works with Claude alone).

</details>

## 🛠 Recommended Add-ons

### Token Savings (RTK)

[RTK](https://github.com/rtk-ai/rtk) is an optional CLI proxy that compresses Bash output (git, pytest, build tools) before it reaches Claude — 60–99% token savings with no workflow changes. A `PreToolUse` hook (`plugins/foundry/hooks/rtk-rewrite.js`) transparently rewrites supported commands across all Claude skills; Codex runs get the same treatment via `.codex/hooks/rtk-enforce.js`. The hook is a no-op when RTK is not installed, so the config stays portable.

→ Install instructions: [rtk-ai/rtk](https://github.com/rtk-ai/rtk)

### Codex CLI plugin

[openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) connects the Codex CLI to Claude Code as a local plugin — enabling the cross-validation, mechanical delegation, and diff pre-pass described in [Claude + Codex Integration](#-claude--codex-integration).

→ Install: `/plugin marketplace add openai/codex-plugin-cc` → `/plugin install codex@openai-codex` → `/reload-plugins`

> [!NOTE]
>
> RTK only compresses **Bash tool output** — shell commands like `git`, `cargo`, `pytest`, etc. It does not affect Claude Code's native tools (Read, Grep, Glob, Edit, Write), which run inside Claude's own engine and are already token-efficient by design.

### cc-Lens

[cc-Lens](https://github.com/Arindam200/cc-lens) is a local analytics dashboard for Claude Code — token/cost trends, tool usage breakdowns, session replay. Reads `~/.claude/` directly, no cloud, no data leaves the machine.

→ Run: `npx cc-lens` — no install required

### Colab-MCP

[colab-mcp](https://github.com/googlecolab/colab-mcp) connects Google Colab as a remote GPU executor. Pre-configured in `.mcp.json` (disabled by default) — used by `/research:run --colab` to offload metric-improvement iterations to a cloud GPU without a local CUDA setup. Supports hardware selection: `--colab=H100`, `--colab=L4`, `--colab=T4`, `--colab=A100`.

→ Enable: add `"colab-mcp"` to `enabledMcpjsonServers` in `settings.local.json`

### Semble (semantic code search)

[semble](https://github.com/MinishLab/semble) runs a local MCP server that adds hybrid semantic + lexical search across any repo. When available, the `develop` and `oss` skills automatically expose `mcp__semble__search` to agents as a gap-fill tool — used when the codemap index is non-exhaustive. No cloud, no API key; runs fully local via `uvx`.

→ Install (global, all projects): `claude mcp add semble -s user -- uvx --from "semble[mcp]" semble`

→ Install (this project only): `claude mcp add semble -s project -- uvx --from "semble[mcp]" semble`

### Caveman

[caveman](https://github.com/JuliusBrussee/caveman) makes Claude respond in compressed "caveman speak" — cutting ~75% of output tokens while retaining full technical accuracy. Adjustable intensity levels (lite → full → ultra → 文言文) and a compression tool that also cuts ~46% of input tokens per session.

→ Install: `claude plugin marketplace add JuliusBrussee/caveman && claude plugin install caveman@caveman`

### Ponytail

[ponytail](https://github.com/DietrichGebert/ponytail) makes Claude apply YAGNI and stdlib-first discipline when writing code — checking stdlib, installed dependencies, and existing codebase before authoring anything new. Complements caveman: caveman cuts response verbosity, ponytail cuts code complexity. Intensity levels (lite → full → ultra) and a `/ponytail-review` scan that tags over-engineering by type (`stdlib` / `native` / `yagni` / `delete` / `shrink`) with a net LoC estimate.

> **Personal note**: popular plugin but limited observed improvement in practice. `/ponytail-audit` and `/ponytail-debt` produce noisy output with false positives. Recommended: set `PONYTAIL_DEFAULT_MODE=off` and activate per coding session with `/ponytail` — avoids injecting ~1300 tokens every session.

→ Install: `claude plugin marketplace add DietrichGebert/ponytail && claude plugin install ponytail@ponytail`

## 📦 What's Here

<details>
<summary><strong>Repository layout</strong></summary>

```text
AI-Rig/
├── plugins/
│   ├── foundry/            # Base plugin: agents, hooks, audit/manage/calibrate/brainstorm/…
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json # plugin manifest
│   │   ├── agents/         # 10 foundry agents (canonical source)
│   │   ├── skills/         # foundry skills (canonical source)
│   │   ├── rules/          # rule files (canonical source; symlinked from .claude/rules/)
│   │   ├── CLAUDE.md       # workflow rules (symlinked from .claude/CLAUDE.md)
│   │   ├── TEAM_PROTOCOL.md # AgentSpeak v2 protocol (symlinked from .claude/TEAM_PROTOCOL.md)
│   │   ├── permissions-guide.md # allow-entry reference (symlinked from .claude/permissions-guide.md)
│   │   └── hooks/
│   │       └── hooks.json  # task tracking, quality gates, preprocessing
│   ├── oss/                # OSS plugin: shepherd, cicd-steward + analyse/review/resolve/release (+ internal: gh-scraper, repo-warden)
│   ├── develop/            # Develop plugin: feature/fix/refactor/plan/debug
│   ├── research/           # Research plugin: scientist, data-steward + topic/plan/judge/run/sweep
│   └── codemap/            # codemap plugin: structural index, blast-radius scores, import graph
├── .claude/                # Claude Code source of truth
│   ├── README.md           # full reference: restore, skills, rules, hooks, architecture (real file)
│   ├── CLAUDE.md           # workflow rules and core principles (symlink → plugins/foundry/)
│   ├── TEAM_PROTOCOL.md    # AgentSpeak v2 inter-agent protocol (symlink → plugins/foundry/)
│   ├── permissions-guide.md # allow-entry reference (symlink → plugins/foundry/)
│   ├── settings.json       # deny list + project preferences (real file)
│   ├── agents/             # symlinks → plugins/foundry/agents/
│   ├── skills/             # symlinks → plugins/foundry/skills/
│   ├── rules/              # per-topic coding and config standards (symlinks → plugins/foundry/rules/)
│   └── hooks/              # symlinks → plugins/foundry/hooks/
├── .mcp.json               # MCP server definitions
├── .codex/                 # OpenAI Codex CLI source of truth
│   ├── README.md           # full reference: agents, profiles, Claude integration
│   ├── AGENTS.md           # global instructions and subagent spawn rules
│   ├── config.toml         # multi-agent config (gpt-5.5 baseline)
│   ├── agents/             # per-agent model and instruction overrides
│   ├── calibration/        # self-calibration harness + fixed task set
│   └── skills/             # codex-native workflow skills
├── .pre-commit-config.yaml
├── .gitignore
└── README.md
```

</details>

## 🔌 Plugin Management

### Upgrade

```bash
claude plugin install foundry@borda-ai-rig   # reinstalls from updated source
claude plugin install oss@borda-ai-rig
claude plugin install develop@borda-ai-rig
claude plugin install research@borda-ai-rig
claude plugin install codemap@borda-ai-rig
```

Re-run `/foundry:setup` only if permissions, `enabledPlugins`, or `advisorModel` changed. Re-run `/foundry:setup` if you previously used the link mode — symlinks point to the old plugin cache after an upgrade.

### Session-only (no install, for development)

```bash
git clone https://github.com/Borda/AI-Rig Borda-AI-Rig
claude --plugin-dir ./Borda-AI-Rig/plugins/foundry
```

### Uninstall

```bash
claude plugin uninstall foundry
claude plugin uninstall oss
claude plugin uninstall develop
claude plugin uninstall research
claude plugin uninstall codemap
```

Settings added by `/foundry:setup` remain in `~/.claude/settings.json`; remove manually if desired. If `/foundry:setup` was run, symlinks in `~/.claude/agents/` and `~/.claude/skills/` also persist and will be broken after uninstall — remove with `rm ~/.claude/agents/<name>.md` and `rm -rf ~/.claude/skills/<name>` for each.

______________________________________________________________________

<div align="center">

**Questions?** Open an [issue](https://github.com/Borda/AI-Rig/issues) or start a [discussion](https://github.com/Borda/AI-Rig/discussions).

Made with 💚 by the Borda et al.

</div>
