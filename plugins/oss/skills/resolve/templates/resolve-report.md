<!-- oss:resolve final report template — read by Step 11 for output format reference -->
<!-- Placeholders: $PR_NUMBER, $PR_URL, $BRANCH, $REPO, $ACTION_ITEMS count, per-item status -->

## Resolve Report — PR #<number>

### Contribution
<2–3 sentence motivation summary from Step 3b>

### Conflicts
<conflict table from Step 7, or "No conflicts detected">

### Action Items

<!-- One row per SELECTED item. Columns: # | Type | Change | Status | Resolution | Commit -->
<!-- Status: ✓ implemented / ⊘ skipped / ✗ rejected by challenge -->
<!-- Resolution: implemented / self-resolved / skipped / challenge-rejected -->
<!-- Change: code / test / docs / config / ci / style / refactor -->
<!-- Commit: short SHA or "—" when COMMIT_MODE=stage -->

| # | Type | Change | Status | Resolution | Commit |
| --- | --- | --- | --- | --- | --- |
| 1 | [gh][req] | code | ✓ | implemented | `abc1234` |

### Lint + QA
<linting-expert summary: N fixes applied | or "no violations"> / <foundry:qa-specialist summary: N blocking fixed, N warnings | or "clean">

### Push
✓ Pushed to <remote>/<HEAD_REF> — N new commits

**Next**:
- `gh pr merge <PR#> --merge` to merge now (preserves all commits)

## Confidence

<!-- format per quality-gates.md: Score 0.N, Gaps bullets, Refinements N passes (omit if 0) -->

**Score**: 0.N — **Gaps**: — **Refinements**: N passes.
