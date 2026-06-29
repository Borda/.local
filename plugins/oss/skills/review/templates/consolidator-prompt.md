<!-- file: consolidator-prompt.md — consumers: plugins/oss/skills/review/SKILL.md -->

**Task:** Read all finding files in `$RUN_DIR/` (agent files: `foundry--sw-engineer.md`, `foundry--qa-specialist.md`, `foundry--perf-optimizer.md`, `foundry--doc-scribe.md`, `foundry--linting-expert.md`, `foundry--solution-architect.md`, `foundry--challenger.md` if present, and `foundry--codex.md` if present — skip missing). Read `<REVIEW_SKILL_DIR>/checklist.md` using Read tool and apply consolidation rules (signal-to-noise filter, annotation completeness, section caps). Read `<_OSS_SHARED>/review-section-taxonomy.md` for canonical section header strings and agent-to-section ownership. Include only findings that passed Step 4 cross-validation (verdict=CONFIRMED or un-cross-validated medium/low). For `foundry--challenger.md`: map severity keys Blockers → critical/high, Concerns → medium, Nitpicks → low when aggregating counts.

**Filtering rules:**
- Precision gate: only include findings with concrete, actionable location (function, line range, or variable name).
- Finding density: modules under 100 lines → aim ≤10 total findings.
- Ranking: within each section, order by impact (blocking > critical > high > medium > low).
- Codex deduplication: include `foundry--codex.md` unique findings under `### Codex Co-Review`; same file:line raised by both agent and Codex → keep agent version, mark 'also flagged by Codex'.

**Issue alignment (when `issue-*.md` files exist in `$RUN_DIR`):** Include `### Issue Root Cause Alignment` section placed immediately after `### [blocking] Critical`. Per linked issue: state root cause hypothesis, whether PR addresses it (yes / partially / no), whether PR description diverges from issue's stated problem, whether reproduction scenario tested. Any `root cause misalignment` or `scope divergence` finding is at least HIGH severity.
**PR description drift**: Before flagging `scope divergence`, cross-check PR thread and review comments to determine what was actually agreed upon; description diverges from *thread consensus* is the signal worth flagging.

**File head — MANDATORY format:** the file MUST begin with a `---`-delimited YAML metadata block exactly as in `<REVIEW_SKILL_DIR>/templates/review-report.md` — opening `---` on line 1, then the 13 fields in order (`Title:`, `PR:`, `Date:`, `PR Type:`, `Scope:`, `Focus:`, `Agents:`, `CI:`, `Outcome:`, `Summary:`, `Confidence:`, `Next steps:`, `Path:`), then closing `---`, then the report body. Do NOT encode the head as HTML comments (`<!-- ... -->`) or any other form — the orchestrator reads the `---` block verbatim as the reply header; no `---` head = broken terminal output. `Title:` `oss-review — [PR #N title]` · `PR:` `#<PR_NUMBER>` (omit field entirely when `<PR_NUMBER>` is empty — direct-path mode has no PR) · `Confidence:` aggregate score — key gaps · `Path:` `→ <REPORT_DIR>/review-report.md`.

**Header fields** (orchestrator must expand all shell vars to literal values before spawning):
- `PR:` `#<PR_NUMBER>` — omit field entirely when `<PR_NUMBER>` is empty (direct-path mode) · `Date:` `<DATE>` · `PR Type:` classify from diff INTENT (not title/file-count): `fix` / `feat` / `refactor` / `perf` / `docs` / `ci` / `chore` / `test` / `mixed` · `Scope:` key changed files from `<CHANGED_FILES>` (skip test files if >3 source; cap ~5) · `Focus:` `<SCOPE>` — one-line description from diff + PR body · `Agents:` short names of agents with output files in `$RUN_DIR/` · `CI:` `failing — [<CI_FAILING_CHECKS>]` or `passing (N/N)` or `pending` · `Outcome:` `APPROVE` / `NEEDS_WORK` / `REQUEST_CHANGES` · `Summary:` 1–2 sentences · `Next steps:` blockers first, max 5

**Severity tiers:** Every finding must carry an explicit inline severity label: `[cosmetic]`, `[low]`, `[medium]`, `[high]`, or `[critical]`. Cosmetic findings go in the dedicated `### Cosmetic / Style` section — never interleaved with behavioural findings.

**Confidence parsing:** Parse each agent's `confidence` from JSON envelope. Assign `codex` fixed confidence 0.75 (moderate — static analysis, no runtime context).

**Write to:** `<REPORT_DIR>/review-report.md` using Write tool.

**Source Files footnote**: after the `## Confidence` block, append `## Source Files` section. Use `Glob(pattern="*.md", path="$RUN_DIR")` to list every handover file present — lets reviewers locate raw subagent outputs without knowing the run timestamp. `$RUN_DIR` is the consolidator's self-resolved run-dir (from the run-dir preamble: `cat "${TMPDIR:-/tmp}/oss-review-run-dir"`) — not orchestrator-substituted.

**Return ONLY** one-liner summary: `verdict=<APPROVE|REQUEST_CHANGES|NEEDS_WORK> | findings=N | critical=N | high=N | file=<REPORT_DIR>/review-report.md`
