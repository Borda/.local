---
Review — [target]
Verdict:     [🟢 Approve / 🟡 Minor Suggestions / 🟠 Request Changes / 🔴 Block] — [one sentence]
CI:          [local test suite: pass / fail / N/A]
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

### Architecture & Quality
- [sw-engineer findings]
- [blocking] marked explicit
- [nit] marked explicit

### Test Coverage Gaps
- [qa-specialist findings — top 5 missing tests]
- ML code: non-determinism or missing seed issues

### Performance Concerns
- [perf-optimizer findings — ranked by impact]
- Include: current behavior vs expected improvement

### Documentation Gaps
- [doc-scribe findings]
- Public API without docstrings listed explicit

### Static Analysis
- [linting-expert findings — ruff violations, mypy errors, annotation gaps]

### API Design (if applicable)
- [solution-architect findings — coupling, API surface, backward compat]
- Public API changes: [intentional / accidental leak]
- Deprecation path: [provided / missing]

### Codex Co-Review
(omit if Codex unavailable or no unique findings)
- [unique findings from codex.md not already in agent sections]
- Duplicate findings (same location as agent finding): omitted — see agent section

### Recommended Next Steps
1. [most important action]
2. [second most important]
3. [third]

### Review Confidence
| Agent | Score | Label | Gaps |
| --- | --- | --- | --- |
<!-- Replace with actual agent scores for this review -->

**Aggregate**: min 0.N / median 0.N
