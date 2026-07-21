<!-- file: audit-checks.md — consumers: oss skills/release/modes/audit.md (Phase B), oss skills/release SKILL.md (Write release draft phase pre-flight) -->

```bash
TARGET=$(echo "$ARGUMENTS" | awk '{print $2}')  # optional target version
# accept caller RANGE if set (branch-aware detection in Shared setup)
# fallback: git describe with stable-tag-only filter — consistent with skill detection
if [ -z "$RANGE" ]; then
    LAST_TAG=$(git describe --tags --abbrev=0 --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null || git rev-list --max-parents=0 HEAD)
    RANGE="$LAST_TAG..HEAD"
fi
```

### Data gathering (Checks 1, 2, 3, 4a, 4b, 5, 6 + gh-auth preflight)

Extracted to `bin/run_audit_checks.py` — emits sectioned output (`--- check: <name> ---` banners) covering: repository state (`git status`, unreleased commits), CI health (`gh run list`), open issues + PRs, files changed in range, version-declaration grep, release-blocking TODO/FIXME/HACK grep, pip-audit CVE scan. Internally invokes `bin/parse_audit_json.py` to summarise pip-audit JSON output. Caller captures into one buffer for parsing:

```bash
# loads: run_audit_checks.py, parse_audit_json.py
AUDIT_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/run_audit_checks.py" \
    --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)" \
    ${TARGET:+--tag "$TARGET"} \
    ${RANGE:+--range "$RANGE"})  # timeout: 60000
echo "$AUDIT_OUT"
```

The script exits `2` when `gh` is not authenticated — surface this as a `BLOCKED` verdict immediately and skip the interpretive steps below.

### Check 4a interpretation (after data is in `$AUDIT_OUT`)

Read `README.md`: install/usage match current API, version refs not stale, deprecated APIs have notes. `docs/` exists → read all changed public API sections.

Check `CHANGELOG.md`: `[Unreleased]` or `$TARGET` section covers `$RANGE` commits?

### Check 4b: Doc weight ratio (🚀 Added features)

For each 🚀 Added entry in CHANGELOG `$TARGET` or `[Unreleased]` identifying significant new entity (new public skill, new command, new agent, new submodule, new mode): compute **doc weight** for that feature and 2–3 comparable existing features of same nature (same task type, mode category, conceptual peer) in relevant README or docs file.

Doc weight = `header_score + coverage_score + example_score`:
- `header_score`: H2 = 3, H3 = 2, H4/deeper = 1, no heading = 0
- `coverage_score`: `min(non_blank_lines_in_section / 5, 5)` — non-blank lines from feature heading to next same-or-higher heading
- `example_score`: fenced code blocks in section, capped at 3

Weight ratio = `new_feature_weight / mean(comparable_weights)`. Flag as **HIGH** (UNDERTREATED) when ratio < 0.5. Report: `- [UNDERTREATED] <feature>: weight N vs peers M1/M2 (ratio R)`. Add to findings table with `severity: high`.

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
| Scheduled removals    | ✅ All removed / ❌ N still present | [symbol names with `remove_in` version] |
| Doc proportionality   | ✅ / ⚠️ N features undertreated | [feature names — no dedicated section / no example / thin coverage] |

### Verdict
**READY** — no blockers. Run `/release prepare <version>` to write artifacts.
— or —
**NEEDS_ATTENTION** — N items before release:
- ❌ [blocking item]
- ⚠️ [recommended item]

### Next steps
[e.g., "resolve open PRs → re-run `/release audit v1.3.0` to verify → `/release prepare v1.3.0`"]
```

**Terminal output** — after writing report file, print readiness check table (`| Check | Status | Detail |` rows only, no YAML header, no verdict prose) directly to terminal so it appears inline in Claude response. Mandatory even when audit runs as sub-phase of `/release prepare` — don't treat table as intermediate pipeline output or route it only to report file; must appear in terminal response before prepare proceeds to Phase 2.
