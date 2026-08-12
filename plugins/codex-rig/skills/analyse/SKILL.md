---
name: analyse
description: "Analyze issue/PR/problem before implementation; produce source-backed findings and measurable gates."
---

# Analyse

Run evidence-first analysis: truth, risk, next action before implementation, review, release, sync.

## Input Schema

```json
{
  "question": "required analysis question",
  "scope": "required files, diff, issue text, report path, PR number, or repo area",
  "mode": "local|github|report|ecosystem",
  "done_when": "findings are source-backed, ranked, and have explicit confidence"
}
```

## Workflow

Codex provides this selected `SKILL.md` path. Resolve `PLUGIN_ROOT` as the directory two levels above the containing
skill directory, then use only helpers under `PLUGIN_ROOT/shared/` that are listed in `package-manifest.json`. Never
guess a cache version or fall back to a source checkout.

### 01: Create run directory

Run `python PLUGIN_ROOT/shared/create_run.py --skill analyse` once. Retain its single printed path as
`<run-directory>` and substitute that literal path into every later artifact path and helper argument. Never store or
reuse the path through a shell variable; shell variables do not persist across tool calls.

### 02: Normalize the analysis mode

- `local`: code, local diff/reports, pasted text.
- `github`: live issue/release/repository metadata through `github_read.py`; use only its audited built-in view groups (`gist`, `issue`, `pr`, `project`, `release`, `repo`, `ruleset`, `run`, `workflow`) or an explicit read-only GraphQL query for Discussions. PR collection uses `collect_pr.py` only. Prefer `gh`; use the public HTTPS fallback only as a final public REST fallback.
- `report`: `.reports/**` or `.reports/codex/**` artifact.
- `ecosystem`: downstream/API/dependency impact; current external claims need live web evidence. Do not invoke `gh` outside `github_read.py`.

Unsupported/ambiguous mode => fail with usage note, unless pasted evidence supports `local`.

### 03: Capture scope and source inventory before drawing conclusions

Use `python PLUGIN_ROOT/shared/collect_diff.py --help`; collect `working-tree` into `<run-directory>/baseline`. Scan references
separately; record failed diff collection.

**Structural context (optional)**: for `local`/`ecosystem` scope naming a Python module or symbol, probe codemap-py once:
`python PLUGIN_ROOT/shared/codemap_adapter.py context --category analysis [--target <qname>] --out <run-directory>/codemap-context.json`.
Per `../../shared/codemap-contract.md`, absence/incompatibility is non-fatal — continue with the evidence above. Persist
the result once here; step 05 specialist fan-out consumes `<run-directory>/codemap-context.json`, never a fresh query.

### 04: Gather evidence with a ledger. Write `<run-directory>/evidence.md` with one row per claim:

```markdown
| Claim | Source | Freshness | Confidence | Notes |
| --- | --- | --- | --- | --- |
```

Evidence rules:

- Code claims: file/line refs.
- External/current: primary sources or unavailable-live-verification caveat.
- Thread/report: distinguish facts/hypotheses.
- List duplicate/related findings; do not silently collapse.

### 05: Orchestrate specialist analysis when the question has independent axes

Use `../../shared/specialist-orchestration.md` for broad/multi-risk PR/issue, ecosystem, or independently challenged conclusions. Stay single-agent when narrow local fan-out duplicates context.

Write `<run-directory>/orchestration.md` when fan-out is used or intentionally skipped for a broad scope. Include:

- specialist axes considered
- context pack per triggered axis
- skipped axes with rationale
- consolidation plan

Routes: `qa-specialist` testability; `web-explorer` current ecosystem; `scientist` method; `curator` config/workflow drift; `challenger` high-impact conclusions. Use the Sol-pinned `solution-architect` for architecture/API or `security-auditor` for risk only when the user expressly requests Sol or selects that role; each is a bounded read-only advisory artifact returned to the Terra parent/session for next action and acceptance.

### 06: Analyze alternatives before recommending action

Required sections in `<run-directory>/analysis.md`:

- `Question`
- `Scope`
- `Verified Facts`
- `Hypotheses`
- `Rejected Alternatives`
- `Findings`
- `Recommendations`
- `Gaps`

### 07: Run the self-review check

Run `git diff --check` as an argv command. Write its combined output to `<run-directory>/review.txt` and retain its
exit status as review evidence; do not erase a nonzero result.

### 08: Decide gate result

- `pass`: evidence-backed ranked findings, explicit gaps.
- `fail`: missing scope/blocking-claim evidence, stale external claim as fact, or no result artifact.

### 09: Run shared gates and write the validated result artifact

Follow `../../shared/helper-cli-contract.md` and helper `--help`. Analysis-only: mark lint/format/types/tests not applicable with reasons; review needs non-empty `analysis.md`, `self-review.md`, clean diff. Write `ANALYSE_METADATA`, validate `analyse`, promote only validated candidate.

Replace skip with command when analysis includes code changes/executable probes.

## Self-Critical Gate

Before final output, answer in `<run-directory>/self-review.md`:

1. Which claim would be most damaging if wrong?
2. What evidence directly supports it?
3. What plausible alternative did you rule out?
4. Which facts are unverified or stale?
5. What next check would most improve confidence?

Critical conclusion without self-review cannot pass.

## Fail-Fast Rules

1. Missing question or scope => fail.
2. Unsupported mode with insufficient pasted/local evidence => fail.
3. Current external claim lacks live primary-source evidence/stale-unverified caveat => fail.
4. Blocking conclusion without evidence ledger entry => fail.
5. Missing self-review for critical conclusions => fail.
6. Broad multi-axis analysis lacks orchestration evidence/skip rationale => fail.
7. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: evidence ledger, self-review, `git diff --check` when diff exists.

Optional checks:

- `lint`, `format`, `types`, `tests`: only with code changes/executable probes.

## Calibration Hooks

Update calibration when routing or evidence expectations change:

- benchmark patterns: `analyse`
- behavioral cases: unsupported claims, stale-source caveats, duplicate/related-item handling

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
