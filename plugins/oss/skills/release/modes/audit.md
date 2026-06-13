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

### Phase A.5: Deprecation-removal check

Verify all APIs scheduled for removal at `$TARGET` are actually absent from HEAD. Runs after gather, before readiness checks.

**Step 1** — find all scheduled removals from two sources (run in parallel):

```bash
# Source A: pyDeprecate remove_in= markers in source (includes deprecated_class, deprecated_instance)
git -C "$REPO_ROOT" grep -n 'remove_in=' HEAD -- '*.py' 2>/dev/null | grep -v '^\s*#'  # timeout: 5000

# Source B: CHANGELOG 🗑️ Deprecated entries — prior releases may name removal version in prose
CHANGELOG_FILE=$(find "$REPO_ROOT" -maxdepth 2 -name "CHANGELOG.md" 2>/dev/null | head -1)
[ -f "$CHANGELOG_FILE" ] && grep -n '🗑️\|Deprecated\|remove_in\|scheduled for removal\|will be removed' "$CHANGELOG_FILE" 2>/dev/null | head -60  # timeout: 3000
```

**Step 2** — for each `remove_in="V.W"` found, compare with `$TARGET`:

- Skip version comparison when `$TARGET` is empty or `"next"` — report as informational only
- OVERDUE = `remove_in ≤ $TARGET`:

```bash
# Pure stdlib version parse — no packaging dependency
python3 -c "
import sys, re
def parse_ver(v):
    v = v.strip('\"v ')
    parts = [int(x) for x in re.sub(r'[^0-9.]', '', v).split('.') if x]
    return tuple(parts) if parts else (0,)
rv, tv = parse_ver(sys.argv[1]), parse_ver(sys.argv[2])
print('OVERDUE' if rv <= tv else 'FUTURE')
" "<remove_in_value>" "${TARGET:-0}"  # timeout: 5000
```

**Step 3** — for each OVERDUE item, check if old symbol still present in HEAD. Read 3-line context around the `remove_in=` match to extract the deprecated function or class name (typically the decorated name 1–2 lines above), then:

```bash
# Definition-level check only — not mention-level; comments and docstrings can reference removed names
git -C "$REPO_ROOT" grep -n "^def <symbol>\|^class <symbol>\|    def <symbol>\|    class <symbol>" HEAD -- '*.py' 2>/dev/null  # timeout: 3000
```

**Outcomes per symbol**:
- Absent from HEAD → ✅ correctly removed
- Still present AND OVERDUE → ❌ **CRITICAL** — add to Phase B findings table as:
  `| Scheduled removal overdue | ❌ \`<symbol>\` still present (remove_in="V.W") | <file:line> | critical |`
- `$TARGET` not set → surface OVERDUE candidates as informational (`⚠️ remove_in="V.W" scheduled but target version unknown`)

### Phase B: Readiness checks

Read and execute all checks from `$SKILL_DIR/templates/audit-checks.md`. Checks cover: version consistency across manifests, docs/CHANGELOG alignment, open blocking issues, dependency CVE scan, unreleased commits since last tag.

After readiness table, if issues found, append **Findings summary** table:

| # | Issue | Location | Severity |
| --- | --- | --- | --- |
| 1 | <what is wrong> | <section or file> | critical/high/medium/low |

Every finding needs explicit location, severity, action — matches structured output format of `notes` and `changelog` modes.

### Output routing

Write the full report to `.reports/release/$BRANCH-$DATE.md` (create dir with `mkdir -p .reports/release` if needed) — **not** `.temp/`. This overrides the quality-gates default `.temp/output-...` path. Print the verdict line and executive summary to terminal per quality-gates rules.

### Verdict line (mandatory final output)

Print exactly one verdict line immediately before `## Confidence` block so callers (e.g. `prepare` Phase 1) can pattern-match without parsing prose:

- `verdict: READY` — no CRITICAL or HIGH findings
- `verdict: NEEDS_ATTENTION` — one or more HIGH findings, no CRITICAL
- `verdict: BLOCKED` — one or more CRITICAL findings (also written when readiness checks cannot complete)

End response with `## Confidence` block per CLAUDE.md output standards.
