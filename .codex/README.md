# 🤖 Codex CLI — Deep Reference

Self-contained multi-agent configuration for OpenAI Codex CLI. This file covers agent spawn rules, specialist orchestration, model strategy, execution architecture, skill usage, calibration, PR review-to-resolve flow, and optional home sync.

## What This Enables

Core capabilities this Codex setup adds:

**Adversarial, multi-axis diff review.** Run `codex "review the current diff with no prior assumptions"`. Codex reads the diff from the working tree, classifies risk, runs required QA and challenge passes for non-trivial changes, triggers conditional specialists, emits a structured recommendation, and writes a findings artifact.

**Specialist orchestration without context flooding.** The shared orchestration policy splits broad work into narrow context packs. Specialists receive only the files, hunks, logs, comments, and questions relevant to their axis; the parent agent consolidates conflicts and owns the final decision.

**Workflow backbone.** The `review`, `develop`, `resolve`, `audit`, `calibrate`, `release`, `investigate`, `manage`, `analyse`, `optimize`, `research`, and `sync` skills enforce the same discipline: quality gates run, findings are classified by severity, confidence gaps are recorded, and a structured artifact lands under `.reports/codex/<skill>/<timestamp>/`.

**PR review-to-resolve loop.** `$review #123` creates the review artifact. `$resolve #123 +review` finds the newest matching report, re-fetches current PR comments/reviews/threads, checks out the PR locally, fetches the target branch, records merge-conflict context, asks which findings to resolve, groups selected work, and assigns it to the right owner/verifier before editing.

**Confidence calibration and offline CI.** Skill and agent behavior is measured with fixed calibration fixtures plus live observations. The offline harness runs in CI without contacting Codex, OpenAI, GitHub, curl, or wget.

**RTK token compression.** Bash output from supported commands is reduced before reaching the model. Treat token-savings ranges as workload-specific until the same task passes the same quality gates with and without RTK.

<details>
<summary><strong>Contents</strong></summary>

- [🔄 Config Sync](#-config-sync)
- [🧩 Agents](#-agents)
  - [Reference table](#reference-table)
  - [Spawn rules](#spawn-rules)
  - [Specialist orchestration](#specialist-orchestration)
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

This repo (`.codex/`) is the source of truth. Home (`~/.codex/`) is a downstream runtime copy. Use the agent-led `sync` skill with `mode=check` first, then approve `mode=apply`, `source=project`, and the exact target allowlist. `.codex/sync-manifest.json` is the only portable surface; the agent backs up mutations, semantically merges managed TOML keys, and preserves home-only runtime state.

The `sync` skill compares only manifest targets, writes drift/action/post-check artifacts, and applies changes only after explicit home-write approval and backups. It has no dedicated Python runtime or vendored dependencies. Retired managed paths need separate approval. Ordinary review/develop/resolve usage does not require a sync.

<details>
<summary><strong>Install</strong></summary>

```bash
npm install -g @openai/codex # install Codex CLI
```

Then run the guarded `sync` workflow; raw `cp -r .codex/ ~/.codex/` nests the source directory when `~/.codex/` already exists.

</details>

## 🧩 Agents

### Reference table

Agents are tiered by task risk and explicit user routing preference. The daily default, review parent, implementation, verification, runtime, data, performance, research-method, curation, and adversarial-challenge roles use `gpt-5.6-terra`. Documentation, CI/CD stewardship, web-evidence, OSS, and static-analysis roles use `gpt-5.6-luna`. Only security and solution architecture use `gpt-5.6-sol`. Every role defaults to `high`.

| Agent                  | Model         | Effort | Purpose                                                                 |
| ---------------------- | ------------- | ------ | ----------------------------------------------------------------------- |
| **sw-engineer**        | gpt-5.6-terra | high   | SOLID implementation, doctest-driven dev, ML pipeline architecture      |
| **qa-specialist**      | gpt-5.6-terra | high   | Edge-case matrix, project standard, adversarial test review             |
| **squeezer**           | gpt-5.6-terra | high   | Profile-first optimization, GPU throughput, memory efficiency           |
| **doc-scribe**         | gpt-5.6-luna  | high   | 6-point Google/Napoleon docstrings, README stewardship, CHANGELOG       |
| **security-auditor**   | gpt-5.6-sol   | high   | OWASP Python, ML supply chain, secrets, CI/CD hygiene *(read-only)*     |
| **data-steward**       | gpt-5.6-terra | high   | Split leakage, DataLoader reproducibility, augmentation correctness     |
| **cicd-steward**       | gpt-5.6-luna  | high   | GitHub Actions permissions, trusted publishing, matrix/cache, flaky CI  |
| **linting-expert**     | gpt-5.6-luna  | high   | ruff, mypy, pre-commit config, rule progression, suppression discipline |
| **oss-shepherd**       | gpt-5.6-luna  | high   | Issue triage, PR review, SemVer, pyDeprecate, release checklist         |
| **solution-architect** | gpt-5.6-sol   | high   | System design, ADRs, API compatibility, migration planning              |
| **web-explorer**       | gpt-5.6-luna  | high   | External docs/release-note extraction and evidence gathering            |
| **curator**            | gpt-5.6-terra | high   | Config quality checks, drift/leak detection, workflow hygiene           |
| **challenger**         | gpt-5.6-terra | high   | 6-axis adversarial plan, architecture, migration, and diff review       |
| **scientist**          | gpt-5.6-terra | high   | Paper analysis, ML hypothesis design, ablations, experiment validation  |

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

### Specialist orchestration

The shared policy lives in `.codex/skills/_shared/specialist-orchestration.md`.

Orchestration is used when work crosses multiple domains, needs independent verification, or can be split into parallel evidence gathering without sending every specialist the same full context. It stays single-agent when the task is narrow, local, and the handoff would duplicate the parent context.

Every spawned or substituted specialist pass needs:

- a narrow context pack with objective, relevant files/logs/hunks, excluded context, concrete questions, output contract, and stop rule
- an output with role, axis, evidence inspected, findings, confidence, confidence gaps, and recommended next action
- parent-owned consolidation; specialist outputs are evidence, not votes

High-benefit orchestrated skills:

- `review`: QA and challenge are mandatory for broad/high-risk diffs and risk-triggered for local diffs; architecture, security, CI, docs, data, performance, research, and web specialists trigger conditionally.
- `develop`: public API, regression, CI/tooling, security, ML/data, docs, and broad changes get owner/verifier plans.
- `resolve`: selected findings are grouped into work clusters, assigned to primary owners and verifiers, then closed with evidence.
- `investigate`: broad symptoms split into hypothesis-specific specialist probes before root cause is claimed.

Conditional orchestration exists in `analyse`, `research`, `release`, `audit`, and `optimize`. `sync`, `manage`, and `calibrate` stay mostly linear because serial safety and deterministic scoring matter more than fan-out.

## 🧠 Model Strategy

Session defaults:

- `model = "gpt-5.6-terra"`
- `review_model = "gpt-5.6-terra"`
- `model_reasoning_effort = "high"`
- `approval_policy = "on-request"`
- `sandbox_mode = "workspace-write"`

Agent model allocation:

- `gpt-5.6-terra`: daily default and general specialist model; use for implementation, tests, curation, data integrity, performance, research-method reasoning, and adversarial challenge.
- `gpt-5.6-sol`: restricted quality-first model; use only for security and solution architecture.
- `gpt-5.6-luna`: user-selected model for documentation, CI/CD stewardship, web evidence, OSS triage, and static analysis at `high`; final acceptance remains with the parent or the relevant Terra/Sol owner.
- Effort defaults to `high` for every role. Use `xhigh` or `max` only as an explicit task-level escalation after `high` proves insufficient.
- Add Sol only for solution architecture or a concrete security signal; Challenger remains on Terra unless a future paired calibration shows a role-specific quality gain.
- Preserve existing reasoning effort during migration. Test one level lower only on representative tasks, and accept it only when task success and required evidence do not regress.
- Active model strings outside the configured GPT-5.6 allowlist are rejected by calibration.
- The current GPT-5.6 mapping combines paid paired evidence with an explicit human Luna override. The strict Luna route remains recorded as failed; do not describe the override as evidence-derived or expand it beyond bounded support without a new campaign. Durable score files and observations live under `.codex/calibration/evidence/2026-07-11/`.

## 🧭 Skills In Codex

### Built-in vs mirrored commands

Codex built-in slash commands (for example `/fast`) work normally.

Mirrored workflow skills in `.codex/skills/*` are instruction assets, not custom slash commands. That means:

- `/investigate`, `/resolve`, `/review` are not recognized as Codex slash commands in this setup
- Use prompt-based invocation instead

### Skill capabilities

Each skill enforces a complete quality loop that prompt-style invocation does not: structured input schema, mandatory gates (lint, format, types, tests), severity classification, and a result artifact.

| Skill         | What it enables                                                                                                                                                                        |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `review`      | Diff-scoped, multi-axis review with measurable gates: classifies findings by severity, emits a structured recommendation, and writes comparable JSON artifacts                         |
| `develop`     | TDD-first implementation with specialist owner/verifier planning for broad changes; requires root-cause evidence for symptom-first failures before implementation                      |
| `resolve`     | Findings closure with current PR evidence: asks scope, groups selected items, assigns specialist owners/verifiers, applies fixes in priority order, reruns gates, and surfaces remains |
| `audit`       | Config hygiene: detects broken refs, inventory drift, instruction overlap; produces a scored report with keep/sharpen/prune recommendations                                            |
| `calibrate`   | Benchmarks recall vs confidence bias on a fixed task set and emits measured recommendations for the next fixes or improvements                                                         |
| `release`     | SemVer-disciplined release: changelog entry, migration guide, and readiness check in one structured pass                                                                               |
| `investigate` | Root-cause diagnosis for unknown failures and code debugging — tracebacks, failing tests, env, tools, hooks, CI divergence — with ranked hypotheses and a handoff artifact             |
| `manage`      | Scaffolds agents, skills, and config with cross-ref propagation; prevents orphaned references                                                                                          |
| `analyse`     | Deep inspection of a scope (module, issue thread, PR) — surfaces structural findings that diff-level review misses                                                                     |
| `optimize`    | Profile-first optimization: measures before and after, rejects changes that don't improve the target metric                                                                            |
| `research`    | SOTA lookup anchored to the codebase — finds relevant techniques and maps them to concrete implementation entry points                                                                 |
| `sync`        | Optional agent-led project/home `.codex` drift report and approved manifest-scoped copy; not needed for ordinary skill usage                                                           |

### Usage examples

Interactive prompt usage:

```text
run investigate on this branch and find root cause of failing CI
run investigate before fixing this failing pytest; do not suggest a workaround unless it is explicitly temporary
run investigate this traceback before changing the code
run resolve on the current working tree and fix high-severity findings
run review, then develop, then audit for issue #42
$review #123
$resolve #123 +review
```

One-shot shell usage:

```bash
codex "run investigate for current failing pytest and write findings artifact"
codex "run resolve on this diff and apply required quality gates"
codex '$review #123'
codex '$resolve #123 +review'
```

`$review` and `$resolve` are in-session skill invocation shorthands. Quote them in shell prompts so the shell does not expand `$review` or `$resolve` as environment variables.

Agent targeting examples:

```text
use the qa-specialist to review tests/ for missing edge cases
use the solution-architect to produce a minimal migration plan for this API change
use the curator to review .codex drift and weak gates
```

## 🪙 RTK Integration

Codex hook support remains enabled in `config.toml` for future state-changing safeguards:

```toml
[features]
hooks = true
```

RTK reduces supported command output before it enters model context. Measure token savings on representative tasks and require identical quality-gate outcomes before treating the reduction as cost-neutral.

Behavior:

- For known RTK-eligible prefixes, agents should invoke `rtk <cmd>` directly
- `.codex/hooks.json` intentionally has no RTK `PreToolUse` hook because current Codex cannot rewrite the command in place; running a fail-open process on every shell command adds latency without enforcement
- Remote mutation is out of scope for Codex: `gh` may read PR/issue evidence and check out/update a PR locally, and `git` may run local operations plus read-only fetch needed to update a PR branch. Agents must not push, pull, clone, change upstream tracking or remote configuration, comment, merge, publish releases, dispatch workflows, or run write-mode remote APIs.
- `.codex/AGENTS.md` is the enforcement source for routing and forbidden remote mutations.

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
- `.codex/skills/_shared/helper-cli-contract.md`
- `.codex/skills/_shared/run-gates.sh`
- `.codex/skills/_shared/write-result.py`
- `.codex/skills/_shared/severity-map.md`
- `.codex/skills/_shared/specialist-orchestration.md`
- `.codex/skills/_shared/validate-artifacts.py`
- `.codex/skills/<skill>/result-template.json` for each skill-specific result payload example

Artifact contract:

- `.reports/codex/<skill>/<timestamp>/result.json`

Calibration runner: inspect `.codex/calibration/run.py --help`, then choose default or strict-live mode from its authoritative CLI contract.

Each run writes `result.json`, `behavioral.json`, and `recommendations.md`. Recommendations are generated from failed gates, leaks, behavioral false positives/negatives, confidence calibration gaps, and live-observation coverage.

Confidence policy:

- `<= 0.8`: not acceptable for a completed skill/agent conclusion; continue recovery or fail with the blocker.
- `0.8 < confidence < 0.85`: very questionable; serious recovery is required before output and pass is not allowed without stronger evidence.
- `0.85 <= confidence < 0.9`: cautious-low; may proceed only with objective evidence, recovery actions, and remaining limits recorded.
- `>= 0.9`: fair, not automatic; residual limits still need to be named.

Every output that reports confidence must include degradation reasons and confidence-gap closures or explicit unresolved/deferred records.

Offline CI harness: inspect `.github/codex-harness.sh --help` before invocation.

The GitHub Actions workflow `.github/workflows/ci-harness.yml` runs this wrapper for `.codex/**` changes. It does not invoke Codex or any LLM API: it clears common LLM API environment variables, runs with an isolated temporary `HOME`, and shadows `codex`, `openai`, `gh`, `curl`, and `wget` with blockers before executing `.codex/calibration/run.py`. The wrapper prints a compact result summary in the action log, appends it to `GITHUB_STEP_SUMMARY`, saves generated calibration artifacts under `.github/codex-harness-results/`, and uploads that folder as the `codex-harness-results` artifact only when the harness job fails.

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

`$resolve #123 +review` auto-selects the newest `.reports/codex/review/*/result.json` whose sibling `pr.json` matches PR `123`, then re-collects current PR comments/reviews, fetches the latest target branch, updates the local PR checkout, and writes a merge-conflict pre-stage before applying report or online-review findings. That pre-stage records the clean PR intent, latest target-branch context, conflict risk, and collision resolution strategy so conflicts are resolved semantically instead of from noisy conflict markers alone.

After that, resolve triages each item as `valid`, `resolved`, `duplicate`, `stale`, `out-of-scope`, `already-fixed`, `already-applied`, or `needs-clarification`, starts terminal output with a resolution table, and asks which selectable findings to resolve before editing unless the resolve scope was supplied up front. Review report `checks_failed`, `follow_up`, required next work, confidence gaps, and residual risks are report-origin resolution items; they are not marked `out-of-scope` just because closure needs an independent reviewer, full gates, CI, or an installed tool. PR comments or review items connected to the PR purpose, changed diff, adjacent verification, or unknown relation remain selectable or visible as required follow-up so the user can rule them into the PR. Any `out-of-scope` item needs a specific rationale and explicit user confirmation before it is removed from the selectable list. The selection prompt supports `all`, severity groups such as `critical,high`, or indexed items such as `1,3,5-7`; online PR items already marked resolved are omitted from the selectable list but kept in the audit table. `$resolve #123 +report` remains a compatibility alias.

Before editing selected findings, resolve writes `.reports/codex/resolve/<timestamp>/resolution-workplan.md`. The workplan groups selected items by shared root cause, closure type, affected files, verification command, or merge risk. Each group records selected indexes, severity range, grouping rationale, primary owner, verifier, context pack path, expected closure evidence, dependencies, and execution status. Parent-owned tiny items stay in `Ungrouped Items`; specialist-owned groups get narrow context packs under `$OUT_DIR/specialists/`. The shared validator fails selected-item runs that lack workplan groups, leave selected items unassigned, or omit owner/verifier/context/closure evidence.

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
