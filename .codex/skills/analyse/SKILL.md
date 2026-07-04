---
name: analyse
description: Minimal codex-native analysis loop. Use for issue/PR/problem analysis before implementation with measurable gates.
---

# Analyse

Run a linear evidence-first analysis loop. Use this skill to answer "what is true, what is risky, and what should happen next" before implementation, review, release, or sync work.

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

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/analyse/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Normalize the analysis mode.

   - `local`: code, local diff, local reports, pasted text.
   - `github`: issue/PR/discussion metadata where live access is available.
   - `report`: existing `.reports/**` or `.reports/codex/**` artifact.
   - `ecosystem`: downstream/API/dependency impact. Live web or `gh` evidence is required for current external claims.

   Unsupported or ambiguous mode => fail with a usage note, unless the user supplied enough pasted evidence to continue in `local`.

3. Capture scope and source inventory before drawing conclusions.

   ```bash
   .codex/skills/_shared/collect-diff.sh --scope working-tree --out "$OUT_DIR/baseline" 2>/dev/null || true
   rg -n "$SCOPE_PATTERN" . >"$OUT_DIR/reference-scan.txt" 2>/dev/null || true
   ```

4. Gather evidence with a ledger. Write `$OUT_DIR/evidence.md` with one row per claim:

   ```markdown
   | Claim | Source | Freshness | Confidence | Notes |
   | --- | --- | --- | --- | --- |
   ```

   Evidence rules:

   - Code claims require file paths and line references.
   - External/current claims require primary sources or a caveat that live verification was unavailable.
   - Thread/report claims must separate verified facts from hypotheses.
   - Duplicate or related issues/findings are listed explicitly instead of collapsed silently.

5. Analyze alternatives before recommending action.

   Required sections in `$OUT_DIR/analysis.md`:

   - `Question`
   - `Scope`
   - `Verified Facts`
   - `Hypotheses`
   - `Rejected Alternatives`
   - `Findings`
   - `Recommendations`
   - `Gaps`

6. Run the self-review check.

   ```bash
   git diff --check >"$OUT_DIR/review.txt" 2>&1 || true
   ```

7. Decide gate result.

   - `pass`: findings are evidence-backed, ranked, and gaps are explicit.
   - `fail`: missing scope, missing evidence for a blocking claim, stale external claim presented as fact, or no result artifact.

8. Write mandatory result artifact to `.reports/codex/analyse/<timestamp>/result.json`.

## Self-Critical Gate

Before final output, answer in `$OUT_DIR/self-review.md`:

1. Which claim would be most damaging if wrong?
2. What evidence directly supports it?
3. What plausible alternative did you rule out?
4. Which facts are unverified or stale?
5. What next check would most improve confidence?

Critical conclusions without this self-review are non-passing.

## Fail-Fast Rules

1. Missing question or scope => fail.
2. Unsupported mode with insufficient pasted/local evidence => fail.
3. Current external claim without live primary-source evidence or stale/unverified caveat => fail.
4. Blocking conclusion without evidence ledger entry => fail.
5. Missing self-review for critical conclusions => fail.
6. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: evidence ledger, self-review, and `git diff --check` when a diff exists.

Optional checks:

- `lint`, `format`, `types`, `tests`: only when analysis includes code changes or executable probes.

## Calibration Hooks

Update calibration when routing or evidence expectations change:

- benchmark patterns: `analyse`
- behavioral cases: unsupported claims, stale-source caveats, duplicate/related-item handling

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "review"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "artifact_path": ".reports/codex/analyse/<timestamp>/result.json"
}
```
