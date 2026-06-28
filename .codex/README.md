# 🤖 Codex CLI — Deep Reference

Self-contained multi-agent configuration for OpenAI Codex CLI. This file covers agent spawn rules, model strategy, runtime profiles, execution architecture, skill usage, calibration, and home sync.

## What This Enables

Four things this Codex setup adds:

**Adversarial diff review.** Run `codex --profile deep-review "review the current diff with no prior assumptions"`. Codex reads the diff from the working tree, classifies risk, runs the review workflow, and writes a findings artifact.

**Workflow backbone.** The `review`, `develop`, `resolve`, `audit`, `calibrate`, `release`, `investigate`, `manage`, `analyse`, `optimize`, `research`, and `sync` skills enforce the same discipline: quality gates run, findings are classified by severity, and a structured artifact lands under `.reports/codex/<skill>/<timestamp>/`.

**RTK token compression.** Bash output — `git log`, `pytest`, `cargo build` — is compressed 60–99% before reaching the model. A typical `resolve` or `review` run costs 40–60% fewer tokens than without RTK, with no quality difference.

**Multi-agent profiles.** `deep-review` activates `xhigh` reasoning effort with live web search. `fast-edit` drops to medium effort for narrow mechanical changes. Profiles tune cost versus quality per task type without touching config.

<details>
<summary><strong>Contents</strong></summary>

- [🔄 Config Sync](#-config-sync)
- [🧩 Agents](#-agents)
  - [Reference table](#reference-table)
  - [Spawn rules](#spawn-rules)
- [🧠 Model Strategy & Profiles](#-model-strategy--profiles)
  - [Model Strategy](#model-strategy)
  - [Profiles](#profiles)
- [🧭 Skills In Codex](#-skills-in-codex)
  - [Built-in vs mirrored commands](#built-in-vs-mirrored-commands)
  - [Skill capabilities](#skill-capabilities)
  - [Usage examples](#usage-examples)
- [🪙 RTK Integration](#-rtk-integration)
- [🏗️ Architecture](#-architecture)
  - [Multi-agent execution model](#multi-agent-execution-model)
  - [Skills and gates](#skills-and-gates)
  - [AGENTS.md layering](#agentsmd-layering)
  - [MCP server](#mcp-server)

</details>

## 🔄 Config Sync

This repo (`.codex/`) is the source of truth. Home (`~/.codex/`) is a downstream copy. Before config edits, keep project-local backups under `.reports/codex/manage/<timestamp>/backup/` so the source-of-truth state is reversible without relying on home config:

```bash
cp -r .codex/ ~/.codex/ # activate globally (config_file paths are relative)
```

Run after editing any agent config, `config.toml`, hooks, or `AGENTS.md`.

<details>
<summary><strong>Install</strong></summary>

```bash
npm install -g @openai/codex # install Codex CLI
cp -r .codex/ ~/.codex/      # activate globally
```

</details>

## 🧩 Agents

### Reference table

Agents are tiered by task profile. Coding-heavy agents use `gpt-5.3-codex`, complex reasoning agents use `gpt-5.5`, and lighter non-coding agents use `gpt-5.4-mini`.

| Agent                  | Model         | Effort | Purpose                                                                 |
| ---------------------- | ------------- | ------ | ----------------------------------------------------------------------- |
| **sw-engineer**        | gpt-5.3-codex | xhigh  | SOLID implementation, doctest-driven dev, ML pipeline architecture      |
| **qa-specialist**      | gpt-5.3-codex | xhigh  | Edge-case matrix, The Borda Standard, adversarial test review           |
| **squeezer**           | gpt-5.3-codex | xhigh  | Profile-first optimization, GPU throughput, memory efficiency           |
| **doc-scribe**         | gpt-5.4-mini  | xhigh  | 6-point Google/Napoleon docstrings, README stewardship, CHANGELOG       |
| **security-auditor**   | gpt-5.3-codex | xhigh  | OWASP Python, ML supply chain, secrets, CI/CD hygiene *(read-only)*     |
| **data-steward**       | gpt-5.3-codex | xhigh  | Split leakage, DataLoader reproducibility, augmentation correctness     |
| **cicd-steward**       | gpt-5.3-codex | xhigh  | GitHub Actions, trusted PyPI publishing, pre-commit, flaky tests        |
| **linting-expert**     | gpt-5.3-codex | xhigh  | ruff, mypy, pre-commit config, rule progression, suppression discipline |
| **oss-shepherd**       | gpt-5.4-mini  | xhigh  | Issue triage, PR review, SemVer, pyDeprecate, release checklist         |
| **solution-architect** | gpt-5.5       | xhigh  | System design, ADRs, API compatibility, migration planning              |
| **web-explorer**       | gpt-5.4-mini  | xhigh  | External docs/release-note extraction and evidence gathering            |
| **curator**            | gpt-5.4-mini  | xhigh  | Config quality checks, drift/leak detection, workflow hygiene           |
| **challenger**         | gpt-5.5       | xhigh  | Adversarial plan, architecture, migration, and diff stress-testing      |
| **scientist**          | gpt-5.5       | xhigh  | Paper analysis, ML hypothesis design, ablations, experiment validation  |

### Spawn rules

Codex selects agents autonomously based on task type (defined in `AGENTS.md`). You can also address agents by name in your prompt.

Automatic spawn patterns (from `AGENTS.md`):

- Symptom-first failures route to `investigate` before implementation: failing tests, failing CI, flaky behavior, regressions, tool/environment errors, unexplained metric shifts, and workaround requests without verified cause
- `sw-engineer` handles core implementation; on completion Codex can fan out to `qa-specialist` + `doc-scribe`
- `security-auditor` is used when tasks touch auth, credentials, external APIs, model weights, or deserialization
- `data-steward` is used when tasks touch data pipelines, splits, augmentation, or DataLoaders
- `squeezer` is used for profiling, throughput, and memory optimization tasks
- `cicd-steward` is used for CI workflow and publishing tasks
- `challenger` is used for high-risk plans, architecture, and independent stress tests
- `scientist` is used for paper-driven ML work, experiment design, and ablation planning

When to address by name vs letting Codex decide:

- Use by name when you want a specific perspective that task-type detection might not trigger
- Let Codex decide for broad tasks; orchestration can fan out automatically

## 🧠 Model Strategy & Profiles

### Model Strategy

Session defaults:

- `model = "gpt-5.5"`
- `review_model = "gpt-5.4-mini"`
- `approval_policy = "on-request"`
- `sandbox_mode = "workspace-write"`

Agent model allocation:

- `gpt-5.3-codex`: code, tests, static analysis, CI/tooling, performance, data pipeline integrity, security code audit.
- `gpt-5.5`: architecture, adversarial challenge, and research-to-experiment reasoning.
- `gpt-5.4-mini`: documentation, web evidence gathering, OSS lifecycle, and config curation.

### Profiles

These runtime profiles belong in your user-level `~/.codex/config.toml`. Project-local `.codex/config.toml` files ignore `[profiles.*]`, so keep the definitions there if you want them to apply across sessions. Activate with `--profile <name>`:

```bash
codex --profile deep-review "full security audit of src/api/"
codex --profile fast-edit "fix the typo in the docstring"
```

| Profile       | What changes                                                          | When to use                                                  |
| ------------- | --------------------------------------------------------------------- | ------------------------------------------------------------ |
| `cautious`    | `approval_policy = "untrusted"`                                       | Unfamiliar codebases, production systems, destructive ops    |
| `fast-edit`   | `model = "gpt-5.3-codex"`, medium reasoning, low verbosity, 2 threads | Narrow mechanical code edits where speed > depth             |
| `fresh-docs`  | `web_search = "live"`, concise summaries                              | Questions about volatile docs, library versions, API changes |
| `deep-review` | `model = "gpt-5.5"`, `xhigh` reasoning, live web search               | Broad/high-risk changes needing maximum review depth         |

## 🧭 Skills In Codex

### Built-in vs mirrored commands

Codex built-in slash commands (for example `/fast`) work normally.

Mirrored workflow skills in `.codex/skills/*` are instruction assets, not custom slash commands. That means:

- `/investigate`, `/resolve`, `/review` are not recognized as Codex slash commands in this setup
- Use prompt-based invocation instead

### Skill capabilities

Each skill enforces a complete quality loop that prompt-style invocation does not: structured input schema, mandatory gates (lint, format, types, tests), severity classification, and a result artifact.

| Skill         | What it enables                                                                                                                             |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `review`      | Diff-scoped review with measurable gates: classifies findings by severity, writes a JSON artifact so results are comparable across runs     |
| `develop`     | TDD-first implementation: writes a failing test first, requires root-cause evidence for symptom-first failures, then reruns all gates       |
| `resolve`     | Findings closure: applies fixes in priority order (critical → high → medium), reruns gates, surfaces what remains                           |
| `audit`       | Config hygiene: detects broken refs, inventory drift, instruction overlap; produces a scored report with keep/sharpen/prune recommendations |
| `calibrate`   | Benchmarks recall vs confidence bias on a fixed task set and emits measured recommendations for the next fixes or improvements              |
| `release`     | SemVer-disciplined release: changelog entry, migration guide, and readiness check in one structured pass                                    |
| `investigate` | Root-cause diagnosis for unknown failures — env, tools, hooks, CI divergence — with ranked hypotheses and a handoff artifact                |
| `manage`      | Scaffolds agents, skills, and config with cross-ref propagation; prevents orphaned references                                               |
| `analyse`     | Deep inspection of a scope (module, issue thread, PR) — surfaces structural findings that diff-level review misses                          |
| `optimize`    | Profile-first optimization: measures before and after, rejects changes that don't improve the target metric                                 |
| `research`    | SOTA lookup anchored to the codebase — finds relevant techniques and maps them to concrete implementation entry points                      |
| `sync`        | Propagates config changes from `.codex/` to `~/.codex/` with a diff preview before overwriting                                              |

### Usage examples

Interactive prompt usage:

```text
run investigate on this branch and find root cause of failing CI
run investigate before fixing this failing pytest; do not suggest a workaround unless it is explicitly temporary
run resolve on the current working tree and fix high-severity findings
run review, then develop, then audit for issue #42
```

One-shot shell usage:

```bash
codex "run investigate for current failing pytest and write findings artifact"
codex "run resolve on this diff and apply required quality gates"
```

Agent targeting examples:

```text
use the qa-specialist to review tests/ for missing edge cases
use the solution-architect to produce a minimal migration plan for this API change
use the curator to review .codex drift and weak gates
```

## 🪙 RTK Integration

Codex hooks are enabled in `config.toml` with the canonical feature flag:

```toml
[features]
hooks = true
```

At ~60–99% Bash output compression, a typical `review` or `resolve` run costs 40–60% fewer tokens than without RTK — same quality gates, lower bill.

Configured hook files:

- `.codex/hooks.json`
- `.codex/hooks/rtk-enforce.js`

The hook launcher resolves the installed copy from `${CODEX_HOME:-$HOME/.codex}` so it still loads when Codex runs outside a Git repository.

Behavior:

- If `rtk` is not installed, hook is a no-op
- If command is already `rtk ...`, hook is a no-op
- For known RTK-eligible prefixes, agents should invoke `rtk <cmd>` directly
- The hook is fail-open for eligible commands to avoid turning missed RTK routing into visible tool failures
- For excluded risky patterns (for example `git push`, destructive git deletes), it passes through normal approvals unchanged

Note: current Codex `PreToolUse` parsing does not apply in-place command rewrites via `updatedInput`. RTK routing is therefore documented in `.codex/AGENTS.md` instead of enforced with deny-and-rerun.

## 🏗️ Architecture

### Multi-agent execution model

Configured in `config.toml`:

```toml
max_threads = 4
max_depth = 2
job_max_runtime_seconds = 3600
```

How Codex schedules agents:

1. The lead agent (or base session) classifies the task and decides which specialists to spawn
2. Agents spawn concurrently up to `max_threads`
3. Agents at depth 2 cannot spawn further (`max_depth = 2`)
4. Jobs exceeding `job_max_runtime_seconds` are stopped and surfaced to the orchestrator

### Skills and gates

Workflow backbone:

- Core loop: `review`, `develop`, `resolve`, `audit`
- Extended set: `calibrate`, `release`, `investigate`, `sync`, `manage`, `analyse`, `optimize`, `research`

Shared gate references:

- `.codex/skills/_shared/quality-gates.md`
- `.codex/skills/_shared/run-gates.sh`
- `.codex/skills/_shared/write-result.sh`
- `.codex/skills/_shared/severity-map.md`

Artifact contract:

- `.reports/codex/<skill>/<timestamp>/result.json`

Calibration runner:

```bash
.codex/calibration/run.sh
```

Each run writes `result.json`, `behavioral.json`, and `recommendations.md`. Recommendations are generated from failed gates, leaks, behavioral false positives/negatives, confidence calibration gaps, and live-observation coverage.

### AGENTS.md layering

Codex loads agent instructions in layers, with more specific layers overriding broader ones:

- Global baseline: `~/.codex/AGENTS.md` or project `.codex/AGENTS.md`
- Project-local override: repo root `AGENTS.md`

Project-local instructions take precedence for overlapping rules.

### MCP server

`config.toml` configures:

```toml
[mcp_servers.openaiDeveloperDocs]
url = "https://developers.openai.com/mcp"
```

Purpose: live OpenAI/Codex documentation lookups for freshness-critical guidance.

## Independent Diff Review

Run Codex as a cold reviewer when you want a separate pass over local changes.

```bash
codex --profile deep-review "review the current diff with no prior assumptions"
codex --profile deep-review "review the diff in src/mypackage/ and write a review artifact"
```

Codex reads `git diff`, applies the full `review` skill workflow, classifies findings by severity, and writes `.reports/codex/review/<timestamp>/result.json`. This is prompt-based invocation, not a registered slash command.
