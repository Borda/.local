<!-- file: audit-checks.md — consumers: oss skills/release/modes/audit.md (Phase B), oss skills/release SKILL.md (Write release draft phase pre-flight) -->

```bash
TARGET=$(echo "$ARGUMENTS" | awk '{print $2}')  # optional target version
# Accept $RANGE from caller if already set (branch-aware detection in skill's Shared setup)
# Fallback: simple git describe with stable-tag-only filter — consistent with skill's detection logic
if [ -z "$RANGE" ]; then
    LAST_TAG=$(git describe --tags --abbrev=0 --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null || git rev-list --max-parents=0 HEAD)
    RANGE="$LAST_TAG..HEAD"
fi
```

### Data gathering (Checks 1, 2, 3, 4, 5, 6 + gh-auth preflight)

Extracted to `bin/run_audit_checks.py` — emits sectioned output (`--- check: <name> ---` banners) covering: repository state (`git status`, unreleased commits), CI health (`gh run list`), open issues + PRs, files changed in range, version-declaration grep, release-blocking TODO/FIXME/HACK grep, pip-audit CVE scan. Internally invokes `bin/parse_audit_json.py` to summarise pip-audit JSON output. Caller captures into one buffer for parsing:

```bash
# loads: run_audit_checks.py, parse_audit_json.py
AUDIT_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/run_audit_checks.py" \
    --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)" \
    ${TARGET:+--tag "$TARGET"} \
    ${RANGE:+--range "$RANGE"})  # timeout: 60000
echo "$AUDIT_OUT"
```

The script exits `2` when `gh` is not authenticated — surface this as a `BLOCKED` verdict immediately and skip the interpretive steps below.

### Check 4 interpretation (after data is in `$AUDIT_OUT`)

Read `README.md`: install/usage match current API, version refs not stale, deprecated APIs have notes. `docs/` exists → read all changed public API sections.

Check `CHANGELOG.md`: `[Unreleased]` or `$TARGET` section covers `$RANGE` commits?

### Check 5 interpretation

All version declarations from the `version-consistency` section must match. `$TARGET` given → verify or flag needs bump.

### Output

Print readiness report:

```markdown
---
repo: [repo-name]
date: [YYYY-MM-DD]
version: [version or "next"]
range: [range]
commits: [N non-merge commits]
verdict: [READY | NEEDS_ATTENTION | BLOCKED]
---

## Release Readiness — [repo] [version or "next release"]
Date: [date] | Range: [last-tag]..HEAD ([N] commits)

| Check                 | Status | Detail |
|-----------------------|--------|--------|
| Working tree          | ✅ Clean / ⚠️ N files | [filenames if dirty] |
| CI (last 5 runs)      | ✅ Passing / ❌ N failing | [failing job names] |
| Blocking issues       | ✅ None / ❌ N open | [#N title] |
| Open PRs (main)       | ✅ None / ⚠️ N open | [PR titles] |
| README aligned        | ✅ / ⚠️ Review needed | [reason if flagged] |
| CHANGELOG entry       | ✅ Present / ❌ Missing | [section name or "add [Unreleased]"] |
| Version consistent    | ✅ / ⚠️ Mismatch | [files and values] |
| Dependency CVEs       | ✅ Clean / ⚠️ N vulns | [package names] |

### Verdict
**READY** — no blockers. Run `/release prepare <version>` to write artifacts.
— or —
**NEEDS_ATTENTION** — N items before release:
- ❌ [blocking item]
- ⚠️ [recommended item]

### Next steps
[e.g., "resolve open PRs → re-run `/release audit v1.3.0` to verify → `/release prepare v1.3.0`"]
```

**Terminal output** — after writing the report file, print the readiness check table (the `| Check | Status | Detail |` rows only, no YAML header, no verdict prose) directly to the terminal so it appears inline in the Claude response. This is mandatory even when audit runs as a sub-phase of `/release prepare` — do not treat the table as intermediate pipeline output or route it only to the report file; it must appear in the terminal response before prepare proceeds to Phase 2.
