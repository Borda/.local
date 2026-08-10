---
name: code-review
description: "Review local diffs/PRs with scope gates, specialists, and JSON artifact; fix via code-remediate."
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

PR evidence has two tiers. Core evidence is `gh pr view` metadata including contributor description/body, authoritative base-repository identity, refreshed target ancestry, an exact local PR head, and a diff derived with local `git diff <base>...<head>` after SHA verification. Supplemental evidence is GraphQL review-thread resolution state and derived diff statistics. The collector delegates remote GitHub state reads to `github_read.py`, which uses `gh` as an opaque local credential broker: it never invokes `gh auth`, reads token/keychain state, or writes CLI failure output to artifacts. That read-only boundary permits audited view commands, REST GET, and GraphQL query operations; public HTTPS fallback cannot establish private PR evidence. A classified core command failure is recorded in `command-failure.json` when diagnostics exist. For an open PR, use fork-aware `gh pr checkout <number>` unless the current HEAD already exactly equals PR metadata; historical collection fetches GitHub's `refs/pull/<number>/head`, verifies its exact SHA, and checks it out detached. Inspect source only in the local checkout recorded by `<run-directory>/local-checkout.json`; `diff.patch` must record `diff_source=verified-local-checkout` provenance there. Never reconstruct changed source from `curl`, `raw.githubusercontent.com`, or `head-files/` snapshots. If checkout or local-diff verification fails, fail instead of reviewing remote raw files. Do not retry with `--force` unless user explicitly confirms after receiving force reason and overwrite risk.

Classify diff; write `<run-directory>/scope.txt`:

- `TRIVIAL`: no public API/config/security/ML behavior touched, \<3 files, \<50 changed lines.
- `LOCAL`: one subsystem or 3-7 files; local context explains behavior.
- `BROAD`: 8+ files, cross-subsystem change, dependency/config change, or unclear ownership.
- `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

For `scope=pr`, merge-oriented code review is limited to an `OPEN` PR. `collect_pr.py` can also collect historical evidence for a merged or closed PR, including its diff, online discussions, refreshed current target state, and exact checked-out PR head; that raw collector evidence is useful for diagnosis but must not receive a merge recommendation or feed code-remediate. For an open review, core evidence includes `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, and locally derived `diff.patch`; online evidence includes comments, reviews, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json`. Selected remote must match the base repository from the PR URL. The freshly fetched target must equal or descend from the PR-recorded base, proven by `expected_base_is_ancestor=true`; target advancement is integration context, never a PR finding or merge blocker. Genuine divergence fails collection. The local checkout head must exactly match open-PR metadata. Historical `target-branch.json` may record divergence. `pr-routing.json` and `local-checkout.json` must include `force_policy` proving no automatic forced checkout. Treat unresolved online threads/comments as candidate findings until triaged valid, duplicate, stale, out-of-scope, or already fixed. If GraphQL review-thread collection fails or is incomplete, continue source review with empty normalized thread arrays, `review-threads-error.txt`, `review_threads_status=unavailable`, explicit partial-online-triage notes, and confidence gap `PR review-thread resolution status was unavailable; online review triage may be incomplete.` Never convert that supplemental integration gap into a PR finding or merge blocker by itself.

If `files.txt` and `untracked.txt` are empty with no explicit target, fail before gates. If `scope=pr` and `pr-error.txt` exists, fail with captured reason and do not begin T1/T2 source review.

**Terminal review-unavailable output gate:** A core T0 PR collection failure is a process failure, not a review result. State `PR Review Availability: unavailable`; `Source findings: not assessed`; and `Merge decision: not made`. Use plain diagnostic prose with exactly a process diagnostic, recovery action, and evidence path. Do not emit a Markdown table: neither `PR Evidence Collection Recovery` nor `Review Findings and Merge Blocks` applies before source assessment. Do not emit `needs-more-work`, `minor-changes`, `reject`, `not-aligned`, or any other merge recommendation. Retain current-attempt metadata, checkout state, or partial diff artifacts for diagnosis, but label them unassessed and never turn them into findings. Name the classified failure and `<run-directory>/pr-error.txt`, then stop. Still write a canonical `result.json` with `status=fail`, zero findings, `review_status=unavailable`, and `collection_failure={"code": "<pr-error.txt text>", "artifact": "pr-error.txt"}`; the review-specific validator rejects a review decision, source findings, specialist artifacts, any table, or assessed-review sections.

For retryable `github-network`, `github-rate-limit`, or `command-timeout`, explain that no review occurred and ask the user to retry the unchanged collector later; rate-limit diagnostics deliberately retain no server interval. If `checkout-state.json` exists, say the local checkout command may have changed the worktree, tell the user to inspect that local state before retrying, and never claim no checkout was produced. For `github-auth` or a permission failure, stop and explain that the local `gh` configuration/account access needs repair; tell the user to run `gh auth status` and, if needed, `gh auth login` privately outside the agent workflow, verify repository access, and never paste tokens, keychain data, or credential output into chat. For `missing-command:gh`, tell the user to install or repair `gh` locally before retrying. For `github-not-found`, ask for the canonical PR URL and repository identity. For definitive `unsafe-gh-command`, invalid protocol/JSON, missing required PR identity, or an unclassified deterministic collector error, stop at the unavailable result, explain the classified code and artifact, and suggest filing a Codex Rig bug with the plugin version, command label, failure code, and sanitized artifacts. Never retry a deterministic target, permission, safety-guard, or plugin-contract failure automatically.

**Structural context (optional)**: after the diff is collected, also probe codemap-py once for changed-symbol blast
radius: `python PLUGIN_ROOT/shared/codemap_adapter.py context --category review --out <run-directory>/codemap-context.json`.
Per `../../shared/codemap-contract.md`, absence/incompatibility is non-fatal — continue with T1/T2 as scoped by `scope.txt`
alone. Persist the diff-impact evidence once here; T2 specialist fan-out (step 04) includes
`<run-directory>/codemap-context.json` in each triggered context pack, never a fresh per-specialist query.

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
- `Review Findings and Merge Blocks` when `Recommendation` is `needs-more-work`, or for any assessed non-`accept-as-is` PR decision
- `No-Finding Residual Risks`
- `Confidence Gaps`
- `Confidence Calibration`
- `Online Review Triage` for `scope=pr`

### 07: Run shared quality gates

Inspect `python PLUGIN_ROOT/shared/run_gates.py --help`; run every project-relevant review gate with explicit command/skip reason.

### 08: Classify findings using `../../shared/severity-map.md`

### 09: Compute the structured review decision and update `Decision Summary`

Skip this step after a T0 PR collection failure: write the terminal availability/recovery output instead, with no recommendation or merge decision.

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

For every assessed non-`accept-as-is` PR decision and any `needs-more-work` decision in another scope, add a `## Review Findings and Merge Blocks` section immediately after `Decision Summary`. It is the canonical pre-merge handoff and must use this exact Markdown header and column order:

| Finding / area | Required change | Evidence | Status |
| --- | --- | --- | --- |
| Finding ID/title and owning area, or an operational blocker | Concrete action that closes the finding or decision condition | File, command, gate, review thread, or other observed evidence | Required, Minor change, Verify, Implemented; verify, Required verification, Reject, or Not aligned |

Include one non-empty row for every reported finding, unresolved blocker, failed or missing gate, and required verification. The first cell names the finding ID/title or clearly states the operational area. `Status` must make clear whether the row is required, minor, verification-only, rejected, or not aligned; `Implemented` alone is not an open action. Do not collapse distinct findings into a generic row. This table is mandatory evidence only after source assessment: an assessed non-`accept-as-is` PR artifact or any `needs-more-work` artifact fails validation when it is missing, malformed, empty, or contains a non-actionable status. The terminal review-unavailable output gate forbids tables and uses plain process diagnostic prose.

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

`CODE_REVIEW_METADATA.specialist_passes` mirrors every triggered `specialist-manifest.json` entry; `review_run_id`/`review_input_sha256` mirror top-level values. `CODE_REVIEW_METADATA.scope` matches normalized scope. For assessed reviews, `CODE_REVIEW_METADATA.review_decision` mirrors `Decision Summary` recommendation, summary, rationale; a terminal collection failure instead records `review_status=unavailable` with source findings not assessed and merge decision not made. Its `findings` object has exactly `critical`, `high`, `medium`, and `low`, each `0`; no normal findings/recommendations/follow-up fields or assessed review metadata are permitted. Every assessed non-`accept-as-is` PR and every `needs-more-work` result in another scope carries the validated canonical `Review Findings and Merge Blocks` table in `review-notes.md`; terminal unavailable collection carries plain process diagnostic prose and no table. An assessed review with unavailable thread-resolution evidence includes the canonical thread confidence gap and unresolved/deferred closure rationale. `CODE_REVIEW_METADATA.confidence_recovery` mirrors `Confidence Calibration` and includes `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, `remaining_limits`. `CODE_REVIEW_METADATA.confidence_gap_closures` has one closure per non-empty `confidence_gaps`, with `status=closed|unresolved|deferred` and matching evidence/rationale.

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
13. PR scope without PR body metadata, authoritative remote/target evidence, exact `local-checkout.json`, locally derived `diff.patch`, comments/reviews, normalized thread artifacts, and `online-review-summary.json` => fail.
14. PR scope ignores unresolved online reviews without triage, or claims complete thread triage when `review_threads_status=unavailable` => fail.
15. Missing structured review decision summary or invalid recommendation => fail.
16. PR scope uses `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for source inspection instead of local checkout => fail.
17. PR scope runs `git`/`gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
18. Missing `Confidence Calibration`, `metadata.confidence_recovery`, or `metadata.confidence_gap_closures` => fail.
19. Shared confidence policy violation from `../../shared/quality-gates.md` => fail.
20. Spawned specialist lacks validated parent/child rollout provenance, hashes, or exact output binding => fail.
21. More than two attempts or retry after non-transient outcome => fail.
22. An assessed non-`accept-as-is` PR or `needs-more-work` result is missing a complete actionable `Review Findings and Merge Blocks` table => fail.
23. A terminal core T0 PR collection failure emits any Markdown table or merge recommendation, omits its plain process diagnostic/recovery/evidence prose, or does not explicitly mark source findings `not assessed` and merge decision `not made` => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, local changed-file inspection, simplicity/readability/reproducibility inspection, project docstring-style detection, docstring/comment policy inspection for changed code, PR body/target/checkout/local-diff evidence when relevant, specialist manifest/notes, structured assessed decision summary or terminal unavailable process result, non-approval PR findings/action table for assessed reviews, plain process diagnostics for terminal core collection failure, explicit supplemental-thread degradation, confidence calibration/recovery, PR online-review triage, severity map, `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run/inspect available results when needed to validate finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, decision vocabulary, or output shape changes:

- benchmark patterns: `code-review`
- behavioral cases: false blocker, target-advance false blocker, supplemental-thread degradation, non-approval PR findings/action table missing a reported finding, missing `needs-more-work` table, T0 PR collection failure with a merge recommendation/table or without plain process diagnostic/source findings `not assessed`/merge decision `not made`, malformed finding-table row, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage, missing project docstring-style detection, missing code self-documentation, long code blocks, deep branching, docstrings masking poor structure, low-confidence recovery loop, objective confidence evidence
- PR routing cases: target-branch refresh required, fork-aware numbered local checkout, exact-head checkout reuse, verified local diff required, stale local PR branch, raw-file snapshot rejection

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Final chat starts compact `Review Decision Summary` for assessed reviews: recommendation, blockers, required next work, confidence/material limits, artifact path. For every assessed non-`accept-as-is` PR decision, and every `needs-more-work` decision in another scope, reproduce the canonical `Review Findings and Merge Blocks` table in the chat output; it is the decision handoff, not optional detail. A terminal core T0 PR collection failure instead starts `PR Review Availability: unavailable` and uses plain prose for classified process diagnostic, recovery, source findings `not assessed`, merge decision `not made`, confidence/material limits, evidence, and artifact path; never reproduce a table or recommendation. Keep full routing, recovery, closure evidence in artifact, not chat. Assessed recommendations must be `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`.

Minimum artifact payload template: `result-template.json`.
