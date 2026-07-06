# 🤖 Codex CLI — Deep Reference

Self-contained multi-agent configuration for OpenAI Codex CLI. This file covers agent spawn rules, model strategy, execution architecture, skill usage, calibration, and home sync.

## What This Enables

Three things this Codex setup adds:

**Adversarial diff review.** Run `codex "review the current diff with no prior assumptions"`. Codex reads the diff from the working tree, classifies risk, runs the review workflow, and writes a findings artifact.

**Workflow backbone.** The `review`, `develop`, `resolve`, `audit`, `calibrate`, `release`, `investigate`, `manage`, `analyse`, `optimize`, `research`, and `sync` skills enforce the same discipline: quality gates run, findings are classified by severity, and a structured artifact lands under `.reports/codex/<skill>/<timestamp>/`.

**RTK token compression.** Bash output — `git log`, `pytest`, `cargo build` — is compressed 60–99% before reaching the model. A typical `resolve` or `review` run costs 40–60% fewer tokens than without RTK, with no quality difference.

<details>
<summary><strong>Contents</strong></summary>

- [🔄 Config Sync](#-config-sync)
- [🧩 Agents](#-agents)
  - [Reference table](#reference-table)
  - [Spawn rules](#spawn-rules)
- [🧠 Model Strategy](#-model-strategy)
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

Agents are tiered by task risk. High-stakes reasoning, implementation, verification, security, CI, data, performance, architecture, adversarial, and research roles use `gpt-5.5`. Bounded support roles use `gpt-5.4-mini`. Deprecated Codex model strings are rejected by calibration.

| Agent                  | Model        | Effort | Purpose                                                                 |
| ---------------------- | ------------ | ------ | ----------------------------------------------------------------------- |
| **sw-engineer**        | gpt-5.5      | high   | SOLID implementation, doctest-driven dev, ML pipeline architecture      |
| **qa-specialist**      | gpt-5.5      | high   | Edge-case matrix, project standard, adversarial test review             |
| **squeezer**           | gpt-5.5      | high   | Profile-first optimization, GPU throughput, memory efficiency           |
| **doc-scribe**         | gpt-5.4-mini | medium | 6-point Google/Napoleon docstrings, README stewardship, CHANGELOG       |
| **security-auditor**   | gpt-5.5      | xhigh  | OWASP Python, ML supply chain, secrets, CI/CD hygiene *(read-only)*     |
| **data-steward**       | gpt-5.5      | high   | Split leakage, DataLoader reproducibility, augmentation correctness     |
| **cicd-steward**       | gpt-5.5      | high   | GitHub Actions permissions, trusted publishing, matrix/cache, flaky CI  |
| **linting-expert**     | gpt-5.4-mini | medium | ruff, mypy, pre-commit config, rule progression, suppression discipline |
| **oss-shepherd**       | gpt-5.4-mini | medium | Issue triage, PR review, SemVer, pyDeprecate, release checklist         |
| **solution-architect** | gpt-5.5      | xhigh  | System design, ADRs, API compatibility, migration planning              |
| **web-explorer**       | gpt-5.4-mini | medium | External docs/release-note extraction and evidence gathering            |
| **curator**            | gpt-5.4-mini | medium | Config quality checks, drift/leak detection, workflow hygiene           |
| **challenger**         | gpt-5.5      | xhigh  | 6-axis adversarial plan, architecture, migration, and diff review       |
| **scientist**          | gpt-5.5      | xhigh  | Paper analysis, ML hypothesis design, ablations, experiment validation  |

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

## 🧠 Model Strategy

Session defaults:

- `model = "gpt-5.5"`
- `review_model = "gpt-5.5"`
- `model_reasoning_effort = "high"`
- `approval_policy = "on-request"`
- `sandbox_mode = "workspace-write"`

Agent model allocation:

- `gpt-5.5`: default and review model; use for implementation, tests, security, CI/tooling, data integrity, performance, architecture, adversarial challenge, and research-to-experiment reasoning.
- `gpt-5.4-mini`: lower-cost support model; use for documentation, web evidence gathering, OSS lifecycle, config curation, and bounded static-analysis cleanup.
- Effort is role-scoped: `medium` for bounded support/static work, `high` for implementation/verification/runtime specialists, and `xhigh` for adversarial, architecture, security, and research reasoning.
- Escalate or pair a `gpt-5.4-mini` support role with a `gpt-5.5` owner when the decision becomes release-blocking, API-breaking, security-sensitive, architecture-heavy, or materially changes runtime behavior.
- Deprecated model strings such as `gpt-5.3-codex` are not allowed in active Codex config.

## 🧭 Skills In Codex

### Built-in vs mirrored commands

Codex built-in slash commands (for example `/fast`) work normally.

Mirrored workflow skills in `.codex/skills/*` are instruction assets, not custom slash commands. That means:

- `/investigate`, `/resolve`, `/review` are not recognized as Codex slash commands in this setup
- Use prompt-based invocation instead

### Skill capabilities

Each skill enforces a complete quality loop that prompt-style invocation does not: structured input schema, mandatory gates (lint, format, types, tests), severity classification, and a result artifact.

| Skill         | What it enables                                                                                                                                                                         |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `review`      | Diff-scoped review with measurable gates: classifies findings by severity, emits a structured decision recommendation, and writes a JSON artifact so results are comparable across runs |
| `develop`     | TDD-first implementation: writes a failing test first, requires root-cause evidence for symptom-first failures, then reruns all gates                                                   |
| `resolve`     | Findings closure: applies fixes in priority order (critical → high → medium), reruns gates, surfaces what remains                                                                       |
| `audit`       | Config hygiene: detects broken refs, inventory drift, instruction overlap; produces a scored report with keep/sharpen/prune recommendations                                             |
| `calibrate`   | Benchmarks recall vs confidence bias on a fixed task set and emits measured recommendations for the next fixes or improvements                                                          |
| `release`     | SemVer-disciplined release: changelog entry, migration guide, and readiness check in one structured pass                                                                                |
| `investigate` | Root-cause diagnosis for unknown failures and code debugging — tracebacks, failing tests, env, tools, hooks, CI divergence — with ranked hypotheses and a handoff artifact              |
| `manage`      | Scaffolds agents, skills, and config with cross-ref propagation; prevents orphaned references                                                                                           |
| `analyse`     | Deep inspection of a scope (module, issue thread, PR) — surfaces structural findings that diff-level review misses                                                                      |
| `optimize`    | Profile-first optimization: measures before and after, rejects changes that don't improve the target metric                                                                             |
| `research`    | SOTA lookup anchored to the codebase — finds relevant techniques and maps them to concrete implementation entry points                                                                  |
| `sync`        | Propagates config changes from `.codex/` to `~/.codex/` with a diff preview before overwriting                                                                                          |

### Usage examples

Interactive prompt usage:

```text
run investigate on this branch and find root cause of failing CI
run investigate before fixing this failing pytest; do not suggest a workaround unless it is explicitly temporary
run investigate this traceback before changing the code
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
- Remote mutation is out of scope for Codex: `gh` may read PR/issue evidence and check out/update a PR locally, and `git` may run local operations plus read-only fetch needed to update a PR branch. Agents must not push, pull, clone, change upstream tracking or remote configuration, comment, merge, publish releases, dispatch workflows, or run write-mode remote APIs.
- For excluded remote/online patterns (for example `git push`, upstream tracking changes, and write-mode `gh` commands), the hook is not the enforcement layer; `.codex/AGENTS.md` is the source of truth and agents must refuse those actions instead of requesting approval.

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
- `.codex/skills/_shared/write-result.py`
- `.codex/skills/_shared/severity-map.md`

Artifact contract:

- `.reports/codex/<skill>/<timestamp>/result.json`

Calibration runner:

```bash
.codex/calibration/run.py
```

Each run writes `result.json`, `behavioral.json`, and `recommendations.md`. Recommendations are generated from failed gates, leaks, behavioral false positives/negatives, confidence calibration gaps, and live-observation coverage.

Offline CI harness:

```bash
.github/codex-harness.sh
```

The GitHub Actions workflow `.github/workflows/ci-harness.yml` runs this wrapper for `.codex/**` changes. It does not invoke Codex or any LLM API: it clears common LLM API environment variables, runs with an isolated temporary `HOME`, and shadows `codex`, `openai`, `gh`, `curl`, and `wget` with blockers before executing `.codex/calibration/run.py`. The wrapper prints a compact result summary in the action log, appends it to `GITHUB_STEP_SUMMARY`, saves generated calibration artifacts under `.github/codex-harness-results/`, and uploads that folder as the `codex-harness-results` artifact.

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

Run Codex as a cold reviewer when you want a separate pass over local changes or an open PR.

```bash
codex "review the current diff with no prior assumptions"
codex "review the diff in src/mypackage/ and write a review artifact"
codex '$review #123'
```

Codex reads `git diff` or a locally checked-out PR branch with online review evidence, applies the full `review` skill workflow, classifies findings by severity, emits a decision recommendation (`accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`), and writes `.reports/codex/review/<timestamp>/result.json`. `$review #123` is the canonical in-session PR review invocation; when launching from a shell, wrap it in single quotes so `$review` is not expanded by the shell.

For PR review, Codex collects `gh pr view`, `gh pr diff`, PR comments, PR reviews, review threads, and unresolved review threads into the same report directory, fetches the PR target branch, then runs `gh pr checkout <number>` so code inspection uses the current local PR branch. It must not reconstruct changed files with raw GitHub URLs. Codex must not pass `--force` to any `git` or `gh` command automatically; if a forced checkout/update appears necessary, it stops and asks with the reason and overwrite risk. Resolve flow then starts from that report:

```bash
codex "resolve PR 123 using .reports/codex/review/<timestamp>/result.json; triage online review comments before editing"
codex '$resolve #123 +review'
```

`$resolve #123 +review` auto-selects the newest `.reports/codex/review/*/result.json` whose sibling `pr.json` matches PR `123`, then re-collects current PR comments/reviews, fetches the latest target branch, updates the local PR checkout, and writes a merge-conflict pre-stage before applying report or online-review findings. That pre-stage records the clean PR intent, latest target-branch context, conflict risk, and collision resolution strategy so conflicts are resolved semantically instead of from noisy conflict markers alone. After that, resolve triages each item as `valid`, `resolved`, `duplicate`, `stale`, `out-of-scope`, `already-fixed`, `already-applied`, or `needs-clarification`, starts terminal output with a resolution table, and asks which selectable findings to resolve before editing unless the resolve scope was supplied up front. Review report `checks_failed`, `follow_up`, required next work, confidence gaps, and residual risks are report-origin resolution items; they are not marked `out-of-scope` just because closure needs an independent reviewer, full gates, CI, or an installed tool. PR comments or review items connected to the PR purpose, changed diff, adjacent verification, or unknown relation remain selectable or visible as required follow-up so the user can rule them into the PR. Any `out-of-scope` item needs a specific rationale and explicit user confirmation before it is removed from the selectable list. The selection prompt supports `all`, severity groups such as `critical,high`, or indexed items such as `1,3,5-7`; online PR items already marked resolved are omitted from the selectable list but kept in the audit table. `$resolve #123 +report` remains a compatibility alias.

Path-free PR review-to-resolve flow:

Inside an active Codex session:

```text
$review #222222
$resolve #222222 +review
```

From a shell, pass the same in-session invocations as quoted prompts:

```bash
codex '$review #222222'
codex '$resolve #222222 +review'
```

The resolve command finds the newest matching review report automatically; you do not need to paste `.reports/codex/review/<timestamp>/result.json`. Use single quotes around `$review` and `$resolve` only in shell examples so the shell does not expand them as environment variables.
