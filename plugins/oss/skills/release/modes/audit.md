<!-- oss:release Mode: audit — executed via: Read $SKILL_DIR/modes/audit.md; execute -->
<!-- Variables available: $SKILL_DIR, $_OSS_SHARED, $LAST_TAG, $BRANCH, $DATE, $RANGE, $VERSION, $REPO_ROOT -->

**Trigger**: `/release audit [version]`

**Purpose**: Pre-release readiness check — surfaces outstanding work, alignment gaps, blockers before cutting release.

```bash
# LAST_TAG, REPO_ROOT, SKILL_DIR resolved in Shared setup block above
# In audit mode, $REST = optional version token (not a range) — RANGE always defaults to $LAST_TAG..HEAD
RANGE="${RANGE:-$LAST_TAG..HEAD}"
```

### Phase A: Gather and explore changes

Use **Delegation strategy** above — spawn gather subagent for `$RANGE`, run gather/explore/validate phases, write findings to `GATHER_FILE`. Read returned JSON envelope only. Audit agent (Phase B) reads `GATHER_FILE` directly — do not pull into main context.

### Phase B: Readiness checks

Read and execute all checks from `$SKILL_DIR/templates/audit-checks.md`. Checks cover: version consistency across manifests, docs/CHANGELOG alignment, open blocking issues, dependency CVE scan, unreleased commits since last tag.

After readiness table, if issues found, append **Findings summary** table:

| # | Issue | Location | Severity |
| --- | --- | --- | --- |
| 1 | <what is wrong> | <section or file> | critical/high/medium/low |

Every finding needs explicit location, severity, action — matches structured output format of `notes` and `changelog` modes.

### Verdict line (mandatory final output)

Print exactly one verdict line immediately before `## Confidence` block so callers (e.g. `prepare` Phase 1) can pattern-match without parsing prose:

- `verdict: READY` — no CRITICAL or HIGH findings
- `verdict: NEEDS_ATTENTION` — one or more HIGH findings, no CRITICAL
- `verdict: BLOCKED` — one or more CRITICAL findings (also written when readiness checks cannot complete)

End response with `## Confidence` block per CLAUDE.md output standards.
