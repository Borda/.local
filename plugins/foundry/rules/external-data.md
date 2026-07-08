---
description: Pagination and completeness rules for external APIs and the gh CLI — never work on partial result sets
paths:
  - '**'
---

## External Data Completeness (stub)

**Never work on a partial result set.** Silent truncation (30 of 300) worse than error — wrong answer.

- `gh` default page = 30 — never OK for analysis: use `--limit` ≥10× expected, or `--paginate`; `gh api` always with `--paginate`; `--json`/`--jq` does NOT lift the 30-cap
- Check pagination signals before concluding: `Link` header, `next_cursor` / `nextPageToken`, `has_more`, `pageInfo.hasNextPage`, `total_count` vs items received
- Suspiciously round item count (10/25/30/50/100) → fetch page 2 to verify before proceeding
- Counting, ranking, or "all X" tasks → complete dataset mandatory first

> Full rule (per-API loop patterns: REST, GraphQL, Google-style tokens; examples) in `_full/external-data.md`. **Read before implementing any multi-page fetch loop**:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/external-data.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/foundry/rules/_full/external-data.md"  # timeout: 5000
> ```
