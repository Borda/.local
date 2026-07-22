---
name: code-review
description: Tiered Codex-native multi-axis code review for local diffs or GitHub PRs, including `$code-review #123` (bare number = PR); uses mechanical scope gates, explicit specialist fan-out/substitutes, measurable gates, and a JSON artifact.
---

# Code Review

Run tiered review with strict output gates.

## Input Schema

```json
{
  "scope": "optional working-tree|path|commit|pr; infer pr for bare number, #number, or PR URL",
  "target": "optional path, commit ref, PR number, PR URL, or current branch PR",
  "done_when": "blocking issues are identified with gate decision"
}
```

## Scope And Routing

- `working-tree`: review unstaged/staged local changes.
- `path`: review one file/directory diff.
- `commit`: review a git diff revision spec, such as `COMMIT^!`, `BASE..HEAD`, or `BASE...HEAD`.
- `pr`: review an open pull request: collect GitHub PR metadata/review evidence, fetch target branch, update local checkout with `gh pr checkout`, inspect local files; `target` may be PR number, URL, or current-branch PR.

Input shorthand:

- Canonical in-session: `$code-review 123` or `$code-review #123` => `scope=pr`, `target=123`.
- Natural-language aliases: `code-review 123`, `code-review #123`, and `code-review PR 123` => `scope=pr`, `target=123`.
- `code-review <github-pr-url>` => `scope=pr`, `target=<github-pr-url>`.
- Bare number = GitHub PR number; do not ask for `scope=pr`.

Never write to remote. PR scope may update local checkout to PR head; otherwise read-only except `.reports/codex/code-review/<timestamp>/` artifacts. Never pass `--force` to `git` or `gh`; if forced checkout seems needed to align local branch and PR head, stop, explain overwrite risk, and ask before retrying. To fix findings, switch to `code-remediate` after creating review artifact.

## Workflow (Exact Commands)

### 01: Create run directory

Run `python PLUGIN_ROOT/shared/create_run.py --skill code-review` once. Retain its single printed path as
`<run-directory>` and substitute that literal path into every later artifact path and helper argument. Never store or
reuse the path through a shell variable; shell variables do not persist across tool calls.

### 02: T0 mechanical scope gate: resolve scope, collect diff, and classify review risk before any model-level judgment

For local scopes, inspect `python PLUGIN_ROOT/shared/collect_diff.py --help`; collect normalized `scope`, optional
`target`, and the literal `<run-directory>` path.

For PR scope, inspect `python PLUGIN_ROOT/shared/collect_pr.py --help`; collect the exact target into the literal
`<run-directory>` path with checkout enabled.

PR GitHub data is evidence only: `gh pr view`, `gh pr diff`, and review-thread queries provide metadata, patch, comments. Inspect source only in local checkout recorded by `<run-directory>/local-checkout.json` after target-branch refresh evidence. Checkout must use authoritative PR URL, never a bare number that may resolve to wrong local fork. Never reconstruct changed source from `curl`, `raw.githubusercontent.com`, or `head-files/` snapshots. If checkout fails or `local-checkout.json` does not prove `head_matches_pr=true`, fail instead of reviewing remote raw files. Do not retry with `--force` unless user explicitly confirms after receiving force reason and overwrite risk.

Classify diff; write `<run-directory>/scope.txt`:

- `TRIVIAL`: no public API/config/security/ML behavior touched, \<3 files, \<50 changed lines.
- `LOCAL`: one subsystem or 3-7 files; local context explains behavior.
- `BROAD`: 8+ files, cross-subsystem change, dependency/config change, or unclear ownership.
- `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

For `scope=pr`, review evidence includes `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, comments, reviews, review threads, unresolved review threads, and `online-review-summary.json`. Selected remote must match base repository from PR URL; fetched base/head OIDs must exactly match PR metadata. `pr-routing.json` and `local-checkout.json` must include `force_policy` proving no automatic forced checkout. Treat unresolved online threads/comments as candidate findings until triaged valid, duplicate, stale, out-of-scope, or already fixed.

If `files.txt` and `untracked.txt` are empty with no explicit target, fail before gates. If `scope=pr` and `pr-error.txt` exists, fail with captured reason.

### 03: T1 primary diff review. Read the changed files end-to-end from the local working tree or checked-out PR branch and identify findings before considering any fix or gate outcome

Review axes, in order:

- API and behavior regressions.
- Test coverage and edge-case gaps.
- Error handling and logging.
- Project coding principles: changed code follows the applicable `AGENTS.md` layers for simplicity, readability, reproducibility, short reusable units without low-value argument-remapping wrappers, guard clauses or early `return`/`yield`/`continue`, project docstring-style detection, concise purpose docstrings, and inline comments only for non-trivial implementation blocks.
- Security, data, ML, CI/CD, or release risks signaled by T0.
- Documentation or migration gaps caused by behavior/API changes.

### 04: T2 risk-routed specialist fan-out. Route independent review from explicit behavior signals, not the file-count tier alone

Always write `<run-directory>/review-routing.json`: `schema_version=1`; declared risk tier; validator-derived `mechanical_risk_tier`/`mechanical_risk_evidence`; every exact boolean signal below; non-empty `signal_evidence` for each true/false decision; sorted `triggered_roles`; non-empty `trigger_reasons` only for triggered roles. Declared tier cannot be below mechanical file/line, binary-size, config/dependency, CI, migration, or security-path evidence. Mechanically detected test, docs, data/tensor, CI, and security paths force matching signals true. Always write `<run-directory>/specialist-manifest.json`, with empty `passes` when no role triggers. Never add untriggered manifest roles.

Required routing signals:

- QA risk: `behavior_change`, `bug_fix`, `test_or_error_path`, `data_tensor_boundary`.
- Challenge risk: `high_candidate`, `unresolved_material_assumption`, `material_no_finding`, `explicit_adversarial`.
- Conditional axes: `axis_solution_architect`, `axis_security_auditor`, `axis_data_steward`, `axis_cicd_steward`, `axis_linting_expert`, `axis_doc_scribe`, `axis_oss_shepherd`, `axis_squeezer`, `axis_scientist`, `axis_web_explorer`.

Routing rules:

- `TRIVIAL`: no automatic QA/challenger pass; conditional axes may trigger.
- `LOCAL`: QA only for QA-risk; challenger only for challenge-risk. File-count-only LOCAL triggers neither.
- `BROAD` and `HIGH_RISK`: always real QA and challenger passes.
- Conditional role only when matching `axis_<role>` signal is true.

Create `<run-directory>/specialists` and one markdown output per triggered spawned/substituted pass. Apply `../../shared/specialist-orchestration.md`. Before each pass, write narrow `<run-directory>/specialists/<role>-context.md`: objective, axis, relevant evidence, excluded noise, concrete questions, output contract, stop rule. Never give every specialist whole PR/repository. Parent owns final severity, duplicate merge, conflict resolution, decision.

For spawned attempt, hash completed context before spawn; task name `review_<role_with_underscores>_<first_12_context_sha256>_a<attempt>`. Record full agent path. This binds runtime child identity to role, context artifact, and attempt even when rollout schema leaves `agent_role` null. Runtime encrypts actual inter-agent payload: do not claim cryptographic proof plaintext exactly equals saved context; record residual limit in confidence metadata.

Compute SHA-256 for `diff.patch` and every context pack. Require exact first specialist line (replace placeholders):

```text
<!-- codex-review-provenance role=<role> run=<review_run_id> input=<review_input_sha256> context=<context_sha256> attempt=<n> -->
```

Routed specialist axes:

- `qa-specialist`: tests, edges, regressions, tensor/data boundaries.
- `challenger`: adversarial assumptions, high findings, migration/API risks, material no-finding conclusions.
- Conditional roles: `solution-architect`, `security-auditor`, `data-steward`, `cicd-steward`, `linting-expert`, `doc-scribe`, `oss-shepherd`, `squeezer`, `scientist`, and `web-explorer` cover named domains.

Use runtime-provided subagents when independence materially helps and follow the portable route order in the shared
orchestration policy. A built-in/default child receives the exact canonical role card before its context pack. It may
count as independent only when it has a separate child identity/output and the artifact records the card hash, route,
actual model, and observed controls. If no safe subagent route exists, write a labeled in-main substitute for each
triggered role and set `fanout_substituted=true`. Substitution lowers confidence and never satisfies independence for
critical findings.

`specialist-manifest.json` uses schema version 2: `review_run_id`, `parent_thread_id=$CODEX_THREAD_ID`,
`review_input_sha256`, triggered passes only. Each spawn records role-card hash, route, attempted routes, fallback
reason, requested and observed controls, parent spawn event ID, child thread ID/path, turn ID, actual model/effort,
context/output paths/hashes, status, and transient error type when applicable. `selected_attempt` identifies completed
output. Validator checks hash-derived child name, parent spawn, child linkage, actual model/effort, final child message,
hashes, and provenance header against Codex rollout logs.

At most two attempts/role. Retry only `timeout`, `transport_error`, or `rate_limited`; never retry deterministic findings, validation failures, completed work. Preserve completed outputs/context. Checkpoint is evidence only, never completed output/provenance replacement.

`BROAD`/`HIGH_RISK` pass only with real independent QA/challenger outputs. Set `independence_required=true` only when QA/challenger risk-triggered; set `independence_satisfied=true` only when every triggered required role has validated spawned provenance. If either output unavailable, fail/timeout with `independence_satisfied=false` and `needs-independent-review`. Risk-triggered `LOCAL` may pass with explicit substitutes only if every triggered axis is covered and confidence is reduced.

### 05: Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly

### 06: Write `<run-directory>/review-notes.md`

Required sections:

- `Decision Summary`
- `Scope`
- `Risk Tier`
- `Files Inspected`
- `Specialist Passes`
- `Specialist Manifest`
- `Findings`
- `No-Finding Residual Risks`
- `Confidence Gaps`
- `Confidence Calibration`
- `Online Review Triage` for `scope=pr`

### 07: Run shared quality gates

Inspect `python PLUGIN_ROOT/shared/run_gates.py --help`; run every project-relevant review gate with explicit command/skip reason.

### 08: Classify findings using `../../shared/severity-map.md`

### 09: Compute the structured review decision and update `Decision Summary`

Use exactly one recommendation:

- `accept-as-is`: no findings; required gates passed/not applicable; residual risks explicitly low.
- `minor-changes`: only non-blocking low/medium findings or polish remain.
- `needs-more-work`: high findings, missing tests/evidence, failed relevant gates, or unresolved review-risk gaps.
- `reject`: critical findings, unsafe behavior, security/data-loss risk, or change should not merge as-is.
- `not-aligned`: change does not address requested issue, PR intent, migration contract, or project direction despite mechanical soundness.

`Decision Summary` must include:

- `Recommendation`: exact value above
- `Summary`: 1-3 sentences covering outcome
- `Rationale`: why recommendation follows from findings, gates, scope
- `Blocking findings`: critical/high items or `none`
- `Minor changes`: medium/low items or `none`
- `Required next work`: pre-merge work or `none`
- `Confidence`: score plus key gaps

### 10: Run confidence calibration and recovery before any user-facing output

Before final chat/`result.json`, write `Confidence Calibration` in `review-notes.md`; mirror in `CODE_REVIEW_METADATA.confidence_recovery`.

Required confidence calibration content:

- `Initial Confidence`: starting score and concrete uncertainty sources.
- `Objective Evidence`: inspected changed files; PR/local artifacts; tests/checks; specialist outputs; pattern cross-checks.
- `Confidence Gaps`: missing checks, substituted specialists, unresolved PR evidence, unverified assumptions, unavailable source context.
- `Recovery Actions`: loops to raise confidence: read more code, check nearby patterns, run focused commands, add specialists, narrow claims, downgrade unsupported findings.
- `Recomputed Confidence`: final score and supporting evidence.
- `Remaining Limits`: residual uncertainty; acceptable or blocking.

Shared confidence policy:

Apply shared confidence band policy from `../../shared/quality-gates.md`. Record required evidence in `Confidence Calibration`; mirror it in `CODE_REVIEW_METADATA.confidence_recovery` before output.

Confidence must be honest/objectively verifiable. Never raise it to pass a gate; improve evidence, narrow claims, or fail with named gap.

### 11: If no findings are present, state that explicitly and note residual risks from T0 classification and any substituted specialist passes

### 12: Write and validate the mandatory result artifact

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write with `CODE_REVIEW_METADATA` and `FOLLOW_UP`; run review-specific validator before shared validator for `code-review`; promote only candidate accepted by both.

`CODE_REVIEW_METADATA.specialist_passes` mirrors every triggered `specialist-manifest.json` entry; `review_run_id`/`review_input_sha256` mirror top-level values. `CODE_REVIEW_METADATA.scope` matches normalized scope. `CODE_REVIEW_METADATA.review_decision` mirrors `Decision Summary` recommendation, summary, rationale. `CODE_REVIEW_METADATA.confidence_recovery` mirrors `Confidence Calibration` and includes `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, `remaining_limits`. `CODE_REVIEW_METADATA.confidence_gap_closures` has one closure per non-empty `confidence_gaps`, with `status=closed|unresolved|deferred` and matching evidence/rationale.

## Fail-fast Rules

01. Empty `files.txt` and `untracked.txt` with no explicit target => fail.
02. Shared gate or diff collection script missing => fail.
03. Result artifact missing => fail.
04. Review that skips changed-file inspection => fail.
05. Blocking finding without local evidence or pattern check => fail.
06. Missing T0 scope classification => fail.
07. Routing signals, triggered roles, manifest roles, and specialist files disagree => fail.
08. Triggered axis without spawned/explicit substitute output => fail.
09. Missing review routing or schema-v2 specialist manifest => fail.
10. `BROAD` or `HIGH_RISK` review returning `status=pass` with substituted required specialists => fail.
11. Result artifact validator failure => fail.
12. Missing `review-notes.md` sections => fail.
13. PR scope without `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, `diff.patch`, `comments.json`, `reviews.json`, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json` => fail.
14. PR scope ignores unresolved online reviews without triage => fail.
15. Missing structured review decision summary or invalid recommendation => fail.
16. PR scope uses `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for source inspection instead of local checkout => fail.
17. PR scope runs `git`/`gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
18. Missing `Confidence Calibration`, `metadata.confidence_recovery`, or `metadata.confidence_gap_closures` => fail.
19. Shared confidence policy violation from `../../shared/quality-gates.md` => fail.
20. Spawned specialist lacks validated parent/child rollout provenance, hashes, or exact output binding => fail.
21. More than two attempts or retry after non-transient outcome => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, local changed-file inspection, simplicity/readability/reproducibility inspection, project docstring-style detection, docstring/comment policy inspection for changed code, PR target-branch refresh/checkout evidence when relevant, specialist manifest/notes, structured decision summary, confidence calibration/recovery, PR online-review triage, severity map, `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run/inspect available results when needed to validate finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, decision vocabulary, or output shape changes:

- benchmark patterns: `code-review`
- behavioral cases: false blocker, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage, missing project docstring-style detection, missing code self-documentation, long code blocks, deep branching, docstrings masking poor structure, low-confidence recovery loop, objective confidence evidence
- PR routing cases: target-branch refresh required, local checkout required, stale local PR branch, raw-file snapshot rejection

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Final chat starts compact `Review Decision Summary`: recommendation, blockers, required next work, confidence/material limits, artifact path. Keep full routing, recovery, closure evidence in artifact, not chat. Recommendation must be `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`.

Minimum artifact payload template: `result-template.json`.
