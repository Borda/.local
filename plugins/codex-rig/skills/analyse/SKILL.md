---
name: analyse
description: Minimal codex-native analysis loop. Use for issue/PR/problem analysis before implementation with measurable gates.
---

# Analyse

Run evidence-first analysis: truth, risk, next action before implementation, review, release, sync.

## Input Schema

```json
{
  "question": "required analysis question",
  "scope": "required files, diff, issue text, report path, PR number, or repo area",
  "mode": "local|github|report|ecosystem",
  "done_when": "findings are source-backed, ranked, and have explicit confidence"
}
```

## Workflow

Codex provides this selected `SKILL.md` path. Resolve `PLUGIN_ROOT` as the directory two levels above the containing
skill directory, then use only helpers under `PLUGIN_ROOT/shared/` that are listed in `package-manifest.json`. Never
guess a cache version or fall back to a source checkout.

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/analyse/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Normalize the analysis mode

- `local`: code, local diff/reports, pasted text.
- `github`: live issue/PR/discussion metadata.
- `report`: `.reports/**` or `.reports/codex/**` artifact.
- `ecosystem`: downstream/API/dependency impact; current external claims need live web/`gh` evidence.

Unsupported/ambiguous mode => fail with usage note, unless pasted evidence supports `local`.

### 03: Capture scope and source inventory before drawing conclusions

Use `PLUGIN_ROOT/shared/collect-diff.sh --help`; collect `working-tree` into `$OUT_DIR/baseline`. Scan references
separately; record failed diff collection.

### 04: Gather evidence with a ledger. Write `$OUT_DIR/evidence.md` with one row per claim:

```markdown
| Claim | Source | Freshness | Confidence | Notes |
| --- | --- | --- | --- | --- |
```

Evidence rules:

- Code claims: file/line refs.
- External/current: primary sources or unavailable-live-verification caveat.
- Thread/report: distinguish facts/hypotheses.
- List duplicate/related findings; do not silently collapse.

### 05: Orchestrate specialist analysis when the question has independent axes

Use `../../shared/specialist-orchestration.md` for broad/multi-risk PR/issue, ecosystem, or independently challenged conclusions. Stay single-agent when narrow local fan-out duplicates context.

Write `"$OUT_DIR/orchestration.md"` when fan-out is used or intentionally skipped for a broad scope. Include:

- specialist axes considered
- context pack per triggered axis
- skipped axes with rationale
- consolidation plan

Routes: `solution-architect` architecture/API; `qa-specialist` testability; `security-auditor` risk; `web-explorer` current ecosystem; `scientist` method; `curator` config/workflow drift; `challenger` high-impact conclusions.

### 06: Analyze alternatives before recommending action

Required sections in `$OUT_DIR/analysis.md`:

- `Question`
- `Scope`
- `Verified Facts`
- `Hypotheses`
- `Rejected Alternatives`
- `Findings`
- `Recommendations`
- `Gaps`

### 07: Run the self-review check

```bash
git diff --check >"$OUT_DIR/review.txt" 2>&1 || true
```

### 08: Decide gate result

- `pass`: evidence-backed ranked findings, explicit gaps.
- `fail`: missing scope/blocking-claim evidence, stale external claim as fact, or no result artifact.

### 09: Run shared gates and write the validated result artifact

Follow `../../shared/helper-cli-contract.md` and helper `--help`. Analysis-only: mark lint/format/types/tests not applicable with reasons; review needs non-empty `analysis.md`, `self-review.md`, clean diff. Write `ANALYSE_METADATA`, validate `analyse`, promote only validated candidate.

Replace skip with command when analysis includes code changes/executable probes.

## Self-Critical Gate

Before final output, answer in `$OUT_DIR/self-review.md`:

1. Which claim would be most damaging if wrong?
2. What evidence directly supports it?
3. What plausible alternative did you rule out?
4. Which facts are unverified or stale?
5. What next check would most improve confidence?

Critical conclusion without self-review cannot pass.

## Fail-Fast Rules

1. Missing question or scope => fail.
2. Unsupported mode with insufficient pasted/local evidence => fail.
3. Current external claim lacks live primary-source evidence/stale-unverified caveat => fail.
4. Blocking conclusion without evidence ledger entry => fail.
5. Missing self-review for critical conclusions => fail.
6. Broad multi-axis analysis lacks orchestration evidence/skip rationale => fail.
7. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: evidence ledger, self-review, `git diff --check` when diff exists.

Optional checks:

- `lint`, `format`, `types`, `tests`: only with code changes/executable probes.

## Calibration Hooks

Update calibration when routing or evidence expectations change:

- benchmark patterns: `analyse`
- behavioral cases: unsupported claims, stale-source caveats, duplicate/related-item handling

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
