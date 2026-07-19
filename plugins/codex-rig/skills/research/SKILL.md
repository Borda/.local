---
name: research
description: Minimal codex-native research loop. Use for docs/papers/state-of-the-art scan with source-backed recommendations.
---

# Research

Source-backed research for documentation, API migration, paper, or state-of-the-art questions.

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

- Prefer primary docs, papers, specs, release notes, code.
- Use current live sources for volatile docs, dependencies, APIs.
- Mark stale/unavailable source explicitly.
- Do not cite secondary summaries for high-impact claims unless independently corroborated.

For `sota`, `paper`, `methodology`, `code-fidelity`, apply `../../shared/specialist-orchestration.md` when independent expertise improves correctness. Write `"$OUT_DIR/specialist-research-plan.md"` with context packs for:

- `web-explorer`: current docs, release notes, API and dependency changes.
- `scientist`: formulas, methodology, metrics, ablations, benchmark claims.
- `solution-architect`: implementation fit, API boundaries, migration shape.
- `squeezer`: performance or resource claims.
- `data-steward`: datasets, splits, leakage, reproducibility.
- `challenger`: unsupported recommendation or overconfident source synthesis.

Do not send full papers, repositories, or all search results to every specialist. Give each only source excerpts, code files, questions needed for its axis.

### 04: Map to codebase context when implementation is relevant

Inspect `collect-diff.sh --help`; collect `working-tree` scope into `$OUT_DIR/baseline`. Run topic scan separately; record unavailable paths/collection failures as evidence gaps.

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

### 08: Run shared gates and write the validated result artifact

Follow `../../shared/helper-cli-contract.md` and authoritative help. For research-only work, mark lint, format, types, tests inapplicable with concrete reasons; review requires non-empty `research.md`, `sources.md`, clean diff check. Write `RESEARCH_METADATA`, validate as `research`, promote only validated candidate.

Replace explicit skip with relevant command when research includes executable validation.

## Fail-Fast Rules

1. Missing question => fail.
2. No primary sources for high-impact/current claims => fail.
3. Recommendation not tied to constraints => fail.
4. Paper/code-fidelity claim without code or source reference => fail.
5. Result artifact missing => fail.

## Quality Gates

Required:

- `review`: source table, caveats, self-review, `git diff --check`.

Conditional:

- `tests`: when research includes an executable validation or code-fidelity probe.

## Calibration Hooks

On source-protocol/recommendation-policy change, update calibration:

- behavioral cases: stale docs, unsupported SOTA claim, paper-code mismatch
- benchmark patterns: `research`

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
