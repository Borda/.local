<!-- oss:resolve final report template — read by Step 11 for output format reference -->
<!-- Placeholders: $PR_NUMBER, $PR_URL, $BRANCH, $REPO, $ACTION_ITEMS count, per-item status -->

## Resolve Report — PR #<number>

### Contribution
<2–3 sentence motivation summary from Step 3b>

### Conflicts
<conflict table from Step 7, or "No conflicts detected">

### Action Items

<!-- Use same action item schema as Step 3b (columns: item, type, status, commit, notes); statuses now final (✓ resolved / ⊘ skipped / ⊘ no action) -->

### Lint + QA
<linting-expert summary: N fixes applied | or "no violations"> / <foundry:qa-specialist summary: N blocking fixed, N warnings | or "clean">

### Push
✓ Pushed to <remote>/<HEAD_REF> — N new commits

**Next**:
- `gh pr merge <PR#> --merge` to merge now (preserves all commits)

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**: [e.g. conflict strategy ambiguity, action items skipped at guard, Codex partial completion]
**Refinements**: N passes. — omit if 0 passes
