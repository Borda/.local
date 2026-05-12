---
Review — [target]
Verdict:     [🟢 Approve / 🟡 Minor Suggestions / 🟠 Request Changes / 🔴 Block] — [one sentence]
CI:          [passing / failing / pending]
Risk:        [n]/5 [low / medium / high]
Blockers:    [N] must-fix | [N] suggestions
Recommendation:
  1. [most important action]
  2. [second action if needed]
Summary:     [2–3 sentence overview of key findings]
Critical:    [blocking items one per line, or "none"]
Confidence:  [aggregate score] — [key gaps]
---

## Code Review: [target]

### [blocking] Critical (must fix before merge)
- [bugs, security issues, data corruption risks]
- Severity: CRITICAL / HIGH

### Issue Root Cause Alignment
(omit if no linked issues)
- Issue #N: [title] — [root cause hypothesis from analysis]
- Root cause addressed: [yes / partially / no — explanation]
- PR/issue scope alignment: [aligned / diverged — what differs]
- Reproduction tested: [yes / no — what's missing]

### Architecture & Quality
- [sw-engineer findings]
- [blocking] issues marked explicitly
- [nit] suggestions marked explicitly

### Test Coverage Gaps
- [qa-specialist findings — top 5 missing tests]
- ML code: non-determinism or missing seed issues

### Performance Concerns
- [perf-optimizer findings — ranked by impact]
- Include: current behavior vs expected improvement

### Documentation Gaps
- [doc-scribe findings]
- Public API without docstrings listed explicitly

### Static Analysis
- [linting-expert findings — ruff violations, mypy errors, annotation gaps]

### API Design (if applicable)
- [solution-architect findings — coupling, API surface, backward compat]
- Public API changes: [intentional / accidental leak]
- Deprecation path: [provided / missing]

### OSS Checks
- New deps: [list, license status]
- API stability: [public API removed without deprecation?]
- CHANGELOG: [updated / not updated]
- Secrets scan: [clean / found: file:line]

### Codex Co-Review
(omit if Codex unavailable or no unique findings)
- [unique findings from codex.md not in agent sections above]
- Duplicate findings (same location as agent finding): omitted — see agent section

### Recommended Next Steps
1. [most important action]
2. [second most important]
3. [third]

### Review Confidence
| Agent | Score | Label | Gaps |
| --- | --- | --- | --- |

**Aggregate**: min 0.65 / median 0.N
[⚠ LOW CONFIDENCE: qa-specialist could not verify test execution — treat coverage findings as indicative, not conclusive]
