---
name: calibrate
description: Codex-native calibration loop. Use to detect leaks or major gaps across mirrored skills and agents with fixed checks plus behavioral recall, precision, and confidence-accuracy scoring.
---

# Calibrate

Run calibration for Codex workflow integrity and behavioral scoring.

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

- Require `source`, `run_id`, `observed_at`. `source=live-*` also needs route; campaign/pair IDs; pair/registered role; actual model/effort; recomputable prompt/task-contract SHA-256; task type/scope; input/cached/output tokens; latency; outcome; tool/check failures; normalized cost; pricing reference. Each complete campaign exactly matches case/role/type/scope signatures in `live-ab-tasks.json`; substituted task, fixture, gate, prompt input fails.

### 04: Inspect `.codex/calibration/run.py --help`, then run the required default or strict-live mode

### 05: Inspect `checks_failed`, `leaks_found`, and `behavioral`

### 06: Review behavioral metrics:

- `recall`: expected IDs recovered from known cases.
- `precision`: reported IDs matching expected IDs.
- `confidence_accuracy`: `1 - mean(abs(confidence - per-case F1))`.
- `mean_overconfidence`: mean positive confidence bias over per-case F1.
- `gate_metrics_raw`: unrounded pass/fail values.
- `by_source`: recall, precision, confidence calibration by source.
- `observation_freshness`: latest `observed_at`, missing timestamps, live/fixture counts.
- `live_route_acceptance`: matched baseline/candidate classification and isolated tool-use quality, normalized token-efficiency proxy, evidence sufficiency per configured route; not monetary pricing evidence.

### 07: Classify gaps as blocking or non-blocking

### 08: Emit measured recommendations for what should be fixed or improved next

- Failed checks/leaks first.
- Behavioral recommendations name metric gap/affected cases when available.
- Separate fixture-only caveats from live-quality claims.

### 09: Write skill artifacts to `.reports/codex/calibrate/<timestamp>/`; preserve runner evidence under `.reports/codex/calibration/<timestamp>/`

### 10: Write the validated skill-level artifact when this skill wraps the runner

Follow `../_shared/helper-cli-contract.md`/authoritative help. Gate intent: ruff lint/format calibration+skills, explicit no-typed-target reason, calibration tests, clean diff. Write `CALIBRATE_METADATA`, validate `calibrate`, promote only validated candidate.

## Native Contract Checks

Verify configured native surface, not only runner internals.

Skill checks:

- configured skill file exists; frontmatter has unindented `---`, `name:`, `description:`; required sections exist; artifact path `.reports/codex/<skill>/`; examples include `status`, `checks_run`, `checks_failed`, `findings`, `confidence`, `artifact_path`; no external runner-only metadata/cache.
- CLI checks find every local shebang Python/shell entry point in calibration, shared helpers, code-review, offline harness; each executable, fixed-help-roster registered, authoritative `--help`.
- every skill references `helper-cli-contract.md`, not complete local CLI invocations.
- compare `.codex/calibration/behavioral-cases.json` version to `HEAD`: dirty tree same or exactly one commit-relative version step; no repeated uncommitted bumps.

Agent checks:

- each configured agent exists/registered; active `model`/`review_model` supported current-runtime strings.
- default, review parent, runtime, research, curation, adversarial use `gpt-5.6-terra`; delegation/docs/CI-CD/web/OSS/static analysis use `gpt-5.6-luna`; only security/solution architecture use `gpt-5.6-sol`.
- Luna/high is explicit human override for bounded simpler roles; preserve strict quality/cost failure, reject undocumented expansion.
- every role defaults `high`; `xhigh`/`max` explicit task escalation. `model_reasoning_effort` follows agent-effort-policy: all `high`, `xhigh`/`max` task overrides.
- high-stakes roles use high-capability tier; bounded support may lower-cost tier. No deprecated model string in active config/TOML.
- role has clear `Scope`/boundary; counterpart mapping, evidence, boundaries, output format/contract present or waived; sensitive agents retain sandbox, especially read-only security audit; native agents require no external runtime tool/path variable.

## Usage Notes

- After meaningful agent/skill instruction change, confirm routing/output match stack.
- `leaks_found` primary drift; `checks_failed` mechanical gate.
- Behavioral metrics measure supplied observations only. `fixture-selftest` validates scoring; live Codex quality requires replacing/appending live-prompt observations.
- Missing route coverage is `insufficient-evidence`, never acceptance; `require_live_routes=true` exits nonzero.
- Compare thresholds with `gate_metrics_raw`, not rounded display.
- Paid paired campaigns: `.codex/calibration/run_live_ab.py`; plans by default, executes only `--confirm-paid-run=chatgpt-subscription`, verified local ChatGPT subscription login, no API key env, no `CI`/`GITHUB_ACTIONS`.
- Each live task names registered role; runner prepends exact project `AGENTS.md` plus role TOML developer instructions to both prompts. Tool pair can accept candidate passing executable gate when successfully invoked baseline fails; infrastructure timeout never candidate win.
- Sol critical-only unless paired quality exceeds Terra configured minimum; tie retains Terra.
- Do not claim currency savings from `normalized-token-v1`; need dated authoritative model-specific price.
- Fixture `version` is committed-history marker: compare `git show HEAD:<path>`; dirty tree stays committed or one-next version until commit.
- Missing registration/pattern mismatch: minimal config fix then rerun before widening.

## Fail-Fast Rules

1. Missing calibration files => fail.
2. Missing configured skill or agent file => fail.
3. Native skill/agent contract mismatch => fail unless result waives.
4. Runtime leakage in native skill or agent files => fail.
5. Behavioral gate below threshold => fail.
6. Result artifact missing => fail.
7. Behavioral case-set version >1 step from committed version => fail.
8. `require_live_routes=true` with incomplete route pairs => fail.
9. Live row without the strict paired execution schema => fail.

## Quality Gates

Required checks:

- `calibration`: `.codex/calibration/run.py`.
- `behavioral-version-policy`: compare case-set version to `HEAD`; avoid meaningless dirty-tree gaps.
- `review`: inspect failed patterns, leaks, behavioral gaps, stale fixtures before recommendations.

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
