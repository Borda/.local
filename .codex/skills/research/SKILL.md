---
name: research
description: Minimal codex-native research loop. Use for docs/papers/state-of-the-art scan with source-backed recommendations.
---

# Research

Run a source-backed research loop for documentation, API migration, paper, or state-of-the-art questions.

## Input Schema

```json
{
  "question": "required research question",
  "mode": "docs|sota|paper|methodology|code-fidelity",
  "constraints": [
    "optional codebase, compute, version, or implementation constraints"
  ],
  "done_when": "recommendations are source-backed with caveats and confidence"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/research/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Define research question, mode, and constraints

Modes:

- `docs`: current API/docs/migration answer.
- `sota`: method comparison and implementation recommendation.
- `paper`: single-paper analysis.
- `methodology`: experiment design, metric, guard, and ablation review.
- `code-fidelity`: compare paper/spec claims against implementation.

### 03: Gather sources

Write `$OUT_DIR/sources.md`:

```markdown
| Source | Type | Date/version | Why reliable | Used for |
| --- | --- | --- | --- | --- |
```

Source rules:

- Prefer primary docs, papers, specifications, release notes, or code.
- Use current live sources for volatile docs, dependencies, and APIs.
- Mark any stale or unavailable source explicitly.
- Do not cite secondary summaries for high-impact claims unless independently corroborated.

### 04: Map to codebase context when implementation is relevant

```bash
.codex/skills/_shared/collect-diff.sh --scope working-tree --out "$OUT_DIR/baseline" 2>/dev/null || true
rg -n "$TOPIC_PATTERN" src tests docs >"$OUT_DIR/codebase-scan.txt" 2>/dev/null || true
```

### 05: Produce `$OUT_DIR/research.md` with:

- `Question`
- `Constraints`
- `Source Table`
- `Findings`
- `Comparison` for SOTA/method choices
- `Implementation Fit`
- `Risks And Unknowns`
- `Recommendation`
- `Next Checks`

### 06: For paper/code-fidelity mode, include dimensions:

- `F`: formula/math match
- `H`: hyperparameter parity
- `E`: evaluation protocol
- `N`: notation and naming consistency
- `C`: citation/derivation chain

### 07: Run review gate

```bash
git diff --check >"$OUT_DIR/review.txt" 2>&1 || true
```

### 08: Decide gate result and write `.reports/codex/research/<timestamp>/result.json`

## Fail-Fast Rules

1. Missing question => fail.
2. No primary sources for high-impact/current claims => fail.
3. Recommendation not tied to constraints => fail.
4. Paper/code-fidelity claim without code or source reference => fail.
5. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: source table, caveats, self-review, and `git diff --check`.

Conditional checks:

- `tests`: when research includes an executable validation or code-fidelity probe.

## Calibration Hooks

Update calibration when source protocol or recommendation policy changes:

- behavioral cases: stale docs, unsupported SOTA claim, paper-code mismatch
- benchmark patterns: `research`

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
  "artifact_path": ".reports/codex/research/<timestamp>/result.json"
}
```
