---
name: calibrate
description: Codex-native calibration loop. Use to detect leaks or major gaps across mirrored skills and agents with fixed checks plus behavioral recall, precision, and confidence-accuracy scoring.
---

# Calibrate

Run a linear calibration loop for codex workflow integrity and behavioral scoring.

## Input Schema

```json
{
  "scope": "skills|agents|routing|all",
  "pace": "fast|full",
  "mode": "ab-test|apply",
  "require_live_routes": false,
  "skip_gate": false,
  "done_when": "recall and bias scores emitted; proposals written if mode=apply; gate skipped if skip_gate=true"
}
```

## Workflow

### 01: Load calibration task set from `.codex/calibration/tasks.json`

### 02: Load behavioral cases from `.codex/calibration/behavioral-cases.json`

### 03: Load behavioral observations from `.codex/calibration/behavioral-observations.jsonl`

- Require `source`, `run_id`, and `observed_at`. A `source=live-*` row must also include route, campaign and pair IDs, pair role, registered role, actual model/effort, recomputable prompt and task-contract SHA-256 values, task type/scope, input/cached/output tokens, latency, outcome, tool/check failures, normalized cost units, and pricing reference. Every complete campaign must exactly match the case/role/type/scope signatures in `live-ab-tasks.json`; substituted tasks, fixtures, gates, or prompt inputs fail.

### 04: Inspect `.codex/calibration/run.py --help`, then run the required default or strict-live mode

### 05: Inspect `checks_failed`, `leaks_found`, and `behavioral`

### 06: Review behavioral metrics:

- `recall`: expected finding IDs recovered from known cases.
- `precision`: reported finding IDs that match expected finding IDs.
- `confidence_accuracy`: `1 - mean(abs(confidence - per-case F1))`.
- `mean_overconfidence`: average positive confidence bias over per-case F1.
- `gate_metrics_raw`: unrounded overall values used for pass/fail thresholds.
- `by_source`: recall, precision, and confidence calibration grouped by observation source.
- `observation_freshness`: latest `observed_at`, missing timestamp count, and live-vs-fixture observation counts.
- `live_route_acceptance`: matched baseline/candidate quality across classification and isolated tool-use tasks, normalized token-efficiency proxy, and evidence sufficiency for every configured route. It is not monetary pricing evidence.

### 07: Classify gaps as blocking or non-blocking

### 08: Emit measured recommendations for what should be fixed or improved next

- Failed checks and leaks come first.
- Behavioral recommendations must name the metric gap and the affected cases when available.
- Fixture-only caveats must be separate from live-quality claims.

### 09: Write skill artifacts to `.reports/codex/calibrate/<timestamp>/`; preserve runner evidence under `.reports/codex/calibration/<timestamp>/`

### 10: Write the validated skill-level artifact when this skill wraps the runner

Follow `../_shared/helper-cli-contract.md` and authoritative help. Gate intent is ruff lint/format over calibration and skills, an explicit no-typed-target reason, calibration as tests, and a clean diff review. Write with `CALIBRATE_METADATA`, validate as skill `calibrate`, and promote only the validated candidate.

## Native Contract Checks

Calibration must verify the configured native surface, not only the runner internals.

Skill checks:

- each configured skill file exists
- skill frontmatter uses unindented `---` markers with `name:` and `description:`
- required contract sections are present
- artifact path uses `.reports/codex/<skill>/`
- output examples include `status`, `checks_run`, `checks_failed`, `findings`, `confidence`, and `artifact_path`
- native skill files do not depend on external runner-only metadata or cache paths
- CLI checks discover every local shebang Python/shell entry point across calibration, shared helpers, code-review, and the offline harness; each must be executable, registered in the fixed help roster, and return authoritative usage from `--help`
- every skill references `helper-cli-contract.md` instead of duplicating complete local CLI invocations
- behavioral case-set version checks compare `.codex/calibration/behavioral-cases.json` against `HEAD`; the working tree may keep the same version or advance by exactly one commit-relative version step, but must not repeatedly bump versions inside one uncommitted change set

Agent checks:

- each configured agent file exists and is registered
- active `model` and `review_model` pins use supported model strings for the current Codex runtime
- the project default, review parent, runtime, research, curation, and adversarial specialists use `gpt-5.6-terra`; delegation coordination, documentation, CI/CD stewardship, web, OSS, and static-analysis roles use `gpt-5.6-luna`; only security and solution architecture use `gpt-5.6-sol`
- Luna/high is an explicit human override for bounded simpler roles; calibration preserves its strict quality/cost failure and rejects any undocumented expansion
- every configured role defaults to `high`; `xhigh` and `max` require explicit task-level escalation
- `model_reasoning_effort` follows the agent-effort-policy: every configured role uses `high`; `xhigh` and `max` are explicit task-level overrides
- high-stakes specialist roles use the high-capability model tier, while bounded support roles may use the lower-cost support tier
- deprecated model strings are absent from active project config and agent TOML files
- role has a clear `Scope` or equivalent boundary
- counterpart mapping, evidence standard, boundaries, output format, and output contract are present or explicitly waived
- sensitive agents keep their sandbox constraints, especially read-only security audit
- no external runtime tool names or external path variables are required by native agents

## Usage Notes

- Use after any meaningful agent or skill instruction change to confirm routing and output shape still match the configured stack.
- Treat `leaks_found` as the primary drift signal and `checks_failed` as the mechanical gate signal.
- Treat behavioral metrics as measurement of supplied observations only. `fixture-selftest` observations validate the scoring contract; live Codex quality requires replacing or appending observations generated from live calibration prompts.
- Treat missing route coverage as `insufficient-evidence`, never route acceptance. When `require_live_routes=true`, insufficient evidence exits nonzero.
- Compare behavioral thresholds against `gate_metrics_raw`, not rounded display metrics.
- Use `.codex/calibration/run_live_ab.py` for paid paired campaigns. It plans calls by default and executes only with `--confirm-paid-run=chatgpt-subscription`, verified local ChatGPT subscription login, no API-key environment, and no `CI`/`GITHUB_ACTIONS` marker.
- Each live task names a registered role; the runner prepends the exact project `AGENTS.md` plus that role TOML's developer instructions to both paired prompts. Tool-use pairs may accept a candidate that passes the executable gate when a successfully invoked baseline fails that gate; infrastructure timeouts never count as a candidate win.
- Keep Sol critical-only unless its paired candidate quality exceeds Terra by the configured minimum; a tie retains Terra.
- Do not claim monetary savings from `normalized-token-v1`; use a dated authoritative model-specific price source before making a currency-cost claim.
- Treat calibration fixture `version` fields as committed-history markers. Before changing one, compare with `git show HEAD:<path>` and keep the dirty tree at either the last committed version or a single next version until the change is committed.
- If the run surfaces missing registration or pattern mismatches, prefer a minimal config fix and rerun before widening the change.

## Fail-Fast Rules

1. Missing calibration files => fail.
2. Missing configured skill or agent file => fail.
3. Native skill/agent contract mismatch => fail unless explicitly waived in the result.
4. Runtime leakage in native skill or agent files => fail.
5. Behavioral gate below threshold => fail.
6. Result artifact missing => fail.
7. Behavioral case-set version advances more than one step from the last committed version => fail.
8. `require_live_routes=true` with incomplete route pairs => fail.
9. Live row without the strict paired execution schema => fail.

## Quality Gates

Required checks:

- `calibration`: `.codex/calibration/run.py`.
- `behavioral-version-policy`: compare the behavioral case-set version against `HEAD` so dirty-tree iterations do not create meaningless version gaps.
- `review`: inspect failed patterns, leakage, behavioral gaps, and stale fixtures before recommending changes.

Conditional checks:

- `tests`: run focused tests when calibration code changes.
- `format`: validate JSON and shell syntax when calibration fixtures change.

## Calibration Hooks

When calibration expectations change, update together:

- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/calibration/behavioral-observations.jsonl`
- `.codex/calibration/run.py`
- `.codex/calibration/live-route-policy.json`
- `.codex/calibration/live-ab-tasks.json`
- `.codex/calibration/run_live_ab.py`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
