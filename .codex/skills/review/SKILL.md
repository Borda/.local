---
name: review
description: Tiered codex-native multi-axis review loop. Use for local diff review or GitHub PR review, including in-session skill invocations like "$review #123" where a bare number means PR number, with mechanical scope gates, explicit specialist fan-out or labeled substitutes, measurable quality gates, and a JSON artifact.
---

# Review

Run a tiered review loop with strict output gates.

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
- `path`: review a specific file or directory diff.
- `commit`: review a git diff revision spec, such as `COMMIT^!`, `BASE..HEAD`, or `BASE...HEAD`.
- `pr`: review an open pull request by collecting GitHub PR metadata/review evidence, fetching the target branch, updating a local checkout with `gh pr checkout`, and inspecting local files; `target` may be a PR number, URL, or omitted for the current branch.

Input shorthand:

- Canonical in-session invocation: `$review 123` or `$review #123` => `scope=pr`, `target=123`.
- Natural-language aliases: `review 123`, `review #123`, and `review PR 123` => `scope=pr`, `target=123`.
- `review <github-pr-url>` => `scope=pr`, `target=<github-pr-url>`.
- If the user supplies a bare number, treat it as a GitHub PR number for this skill. Do not ask for `scope=pr`.

The skill never writes to the remote service. PR scope may update the local checkout to the PR head before inspection; otherwise it is read-only except for `.reports/codex/review/<timestamp>/` artifacts. Do not pass `--force` to `git` or `gh`; if a forced checkout appears necessary to align the local branch with the PR head, stop, explain the overwrite risk, and ask the user before retrying. If the user asks to fix findings, switch to `resolve` after the review artifact exists.

## Workflow (Exact Commands)

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/review/$TS"
mkdir -p "$OUT_DIR"
```

### 02: T0 mechanical scope gate: resolve scope, collect diff, and classify review risk before any model-level judgment

For local scopes:

Inspect `collect-diff.sh --help`, then collect the normalized `SCOPE`, optional `TARGET`, and `OUT_DIR`.

For PR scope, inspect `collect-pr.sh --help`, then collect `TARGET` into `OUT_DIR` with checkout enabled.

In PR scope, GitHub data is evidence only: `gh pr view`, `gh pr diff`, and review-thread queries provide metadata, patch, and comments. Source inspection must use the local checkout recorded in `"$OUT_DIR/local-checkout.json"` after target-branch refresh evidence is written. Checkout must use the authoritative PR URL, not a bare number that can resolve against the wrong local fork. Do not reconstruct changed source files with `curl`, `raw.githubusercontent.com`, or `head-files/` snapshots. If local checkout fails or `local-checkout.json` does not prove `head_matches_pr=true`, fail the review instead of reviewing remote raw files. Do not retry with `--force` unless the user explicitly confirms after being told why force is needed and what it may overwrite.

Classify the diff and write the decision to `"$OUT_DIR/scope.txt"`:

- `TRIVIAL`: no public API/config/security/ML behavior touched, fewer than 3 files, fewer than 50 changed lines.
- `LOCAL`: one subsystem or 3-7 files, behavior is understandable from local context.
- `BROAD`: 8+ files, cross-subsystem changes, dependency/config changes, or unclear ownership.
- `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

If `scope=pr`, include `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, comments, reviews, review threads, unresolved review threads, and `online-review-summary.json` in the review evidence. The selected remote must match the base repository derived from the PR URL, and fetched base/head OIDs must exactly match PR metadata. `pr-routing.json` and `local-checkout.json` must include `force_policy` proving no forced checkout was run automatically. Treat unresolved online review threads and comments as candidate findings until triaged as valid, duplicate, stale, out-of-scope, or already fixed.

If `files.txt` and `untracked.txt` are both empty and there is no explicit target, fail before running gates. If `scope=pr` and `pr-error.txt` exists, fail with the captured reason.

### 03: T1 primary diff review. Read the changed files end-to-end from the local working tree or checked-out PR branch and identify findings before considering any fix or gate outcome

Review across these axes in order:

- API and behavior regressions.
- Test coverage and edge-case gaps.
- Error handling and logging.
- Project coding principles: changed code follows `.codex/AGENTS.md` for simplicity, readability, reproducibility, short reusable units without low-value argument-remapping wrappers, guard clauses or early `return`/`yield`/`continue`, project docstring-style detection, concise purpose docstrings, and inline comments only for non-trivial implementation blocks.
- Security, data, ML, CI/CD, or release risks signaled by T0.
- Documentation or migration gaps caused by behavior/API changes.

### 04: T2 risk-routed specialist fan-out. Route independent review from explicit behavior signals, not the file-count tier alone

Always write `"$OUT_DIR/review-routing.json"` with `schema_version=1`, the declared risk tier, validator-derived `mechanical_risk_tier` and `mechanical_risk_evidence`, every exact boolean signal below, non-empty `signal_evidence` for every true or false decision, a sorted `triggered_roles` list, and non-empty `trigger_reasons` for only those roles. The declared tier cannot be lower than mechanical file/line, binary-size, config/dependency, CI, migration, or security-path evidence. Mechanically detected test, docs, data/tensor, CI, and security paths force their matching signals true. Always write `"$OUT_DIR/specialist-manifest.json"`, including an empty `passes` list when no role triggers. Never add untriggered roles to the manifest.

Required routing signals:

- QA risk: `behavior_change`, `bug_fix`, `test_or_error_path`, `data_tensor_boundary`.
- Challenge risk: `high_candidate`, `unresolved_material_assumption`, `material_no_finding`, `explicit_adversarial`.
- Conditional axes: `axis_solution_architect`, `axis_security_auditor`, `axis_data_steward`, `axis_cicd_steward`, `axis_linting_expert`, `axis_doc_scribe`, `axis_oss_shepherd`, `axis_squeezer`, `axis_scientist`, `axis_web_explorer`.

Routing rules:

- `TRIVIAL`: no automatic QA or challenger pass; conditional axes may still trigger.
- `LOCAL`: trigger QA only for a QA-risk signal and challenger only for a challenge-risk signal. A file-count-only LOCAL diff triggers neither.
- `BROAD` and `HIGH_RISK`: always trigger real QA and challenger passes.
- Trigger a conditional role only when its matching `axis_<role>` signal is true.

Create `"$OUT_DIR/specialists"` and one markdown output per triggered spawned or substituted pass. Apply `../_shared/specialist-orchestration.md`. Before any pass, write a narrow `"$OUT_DIR/specialists/<role>-context.md"` with objective, axis, relevant evidence, excluded noise, concrete questions, output contract, and stop rule. Do not give every specialist the entire PR or repository. The parent owns final severity, duplicate merging, conflict resolution, and the decision.

For a spawned attempt, hash the completed context file before spawning and use task name `review_<role_with_underscores>_<first_12_context_sha256>_a<attempt>`. Record the resulting full agent path. This binds the runtime child identity to the role, context artifact, and attempt even when the current rollout schema leaves `agent_role` null. The runtime encrypts the actual inter-agent task payload, so do not claim cryptographic proof that its plaintext exactly equals the saved context; record that residual limit in confidence metadata.

Compute SHA-256 for `diff.patch` and each context pack. Require the spawned specialist to return this exact first line, with placeholders replaced:

```text
<!-- codex-review-provenance role=<role> run=<review_run_id> input=<review_input_sha256> context=<context_sha256> attempt=<n> -->
```

Routed specialist axes:

- `qa-specialist`: tests, edges, regressions, and tensor/data boundaries.
- `challenger`: adversarial assumptions, high findings, migration/API risks, and material no-finding conclusions.
- Conditional roles: `solution-architect`, `security-auditor`, `data-steward`, `cicd-steward`, `linting-expert`, `doc-scribe`, `oss-shepherd`, `squeezer`, `scientist`, and `web-explorer` cover their named domains.

Use native subagents when independence materially helps. If spawning is unavailable, write a labeled in-main substitute for every triggered role and set `fanout_substituted=true`. Substitution lowers confidence and does not satisfy independence for critical findings.

`specialist-manifest.json` uses schema version 2 and records `review_run_id`, `parent_thread_id=$CODEX_THREAD_ID`, `review_input_sha256`, and only triggered passes. Every spawned attempt records the parent spawn event ID, child thread ID/path, turn ID, actual model/effort, context/output paths and hashes, status, and transient error type when applicable. `selected_attempt` identifies the completed output. The validator checks the hash-derived child name, parent spawn, child linkage, actual model/effort, final child message, hashes, and the provenance header against Codex rollout logs.

Allow at most two attempts per role. Retry only `timeout`, `transport_error`, or `rate_limited`; never retry deterministic findings, validation failures, or completed work. Preserve completed outputs and context packs. A checkpoint is evidence only and cannot replace a completed output or provenance record.

`BROAD` and `HIGH_RISK` reviews require real independent QA and challenger outputs to pass. Record `independence_required=true` only when QA or challenger is risk-triggered, and `independence_satisfied=true` only when every triggered required role has validated spawned provenance. If either required output is unavailable, fail or time out with `independence_satisfied=false` and `needs-independent-review`. A risk-triggered `LOCAL` review may pass with explicit substitutes only when every triggered axis is covered and confidence is reduced.

### 05: Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly

### 06: Write `$OUT_DIR/review-notes.md`

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

Inspect `run-gates.sh --help`, then run every project-relevant review gate with explicit commands or skip reasons.

### 08: Classify findings using `../_shared/severity-map.md`

### 09: Compute the structured review decision and update `Decision Summary`

Use exactly one recommendation:

- `accept-as-is`: no findings, required gates passed or were not applicable, and residual risks are explicitly low.
- `minor-changes`: only non-blocking low/medium findings or polish items remain.
- `needs-more-work`: high findings, missing tests, missing evidence, failed relevant gates, or unresolved review-risk gaps remain.
- `reject`: critical findings, unsafe behavior, security/data-loss risk, or a change that should not merge in its current form.
- `not-aligned`: the change does not address the requested issue, PR intent, migration contract, or project direction even if the diff is mechanically sound.

`Decision Summary` must include:

- `Recommendation`: one of the exact values above
- `Summary`: 1-3 sentences covering the review outcome
- `Rationale`: why this recommendation follows from findings, gates, and scope
- `Blocking findings`: critical/high items or `none`
- `Minor changes`: medium/low items or `none`
- `Required next work`: work needed before merge, or `none`
- `Confidence`: score plus key gaps

### 10: Run confidence calibration and recovery before any user-facing output

Before final chat output or `result.json`, write the `Confidence Calibration` section in `review-notes.md` and mirror it in `REVIEW_METADATA.confidence_recovery`.

Required confidence calibration content:

- `Initial Confidence`: starting score and concrete uncertainty sources.
- `Objective Evidence`: changed files inspected, PR/local artifacts used, tests/checks reviewed, specialist outputs, and pattern cross-checks.
- `Confidence Gaps`: missing checks, substituted specialists, unresolved PR evidence, unverified assumptions, or unavailable source context.
- `Recovery Actions`: internal loops already performed to increase confidence, such as reading more code, checking nearby patterns, running focused commands, adding specialist passes, narrowing claims, or downgrading unsupported findings.
- `Recomputed Confidence`: final score and why the evidence supports it.
- `Remaining Limits`: residual uncertainty and whether it is acceptable or blocking.

Shared confidence policy:

Apply the shared confidence band policy from `../_shared/quality-gates.md`. This skill records the required evidence in the `Confidence Calibration` section and mirrors it in `REVIEW_METADATA.confidence_recovery` before output.

Confidence must be honest and objectively verifiable. Do not raise confidence to pass the gate; improve evidence, reduce claim scope, or fail with the missing evidence named.

### 11: If no findings are present, state that explicitly and note residual risks from T0 classification and any substituted specialist passes

### 12: Write and validate the mandatory result artifact

Follow `../_shared/helper-cli-contract.md` and authoritative help. Write with `REVIEW_METADATA` and `FOLLOW_UP`; run the review-specific validator before the shared validator for skill `review`, then promote only the candidate accepted by both.

`REVIEW_METADATA.specialist_passes` must mirror every triggered entry from `specialist-manifest.json`; `review_run_id` and `review_input_sha256` must mirror its top-level values. `REVIEW_METADATA.scope` must match the normalized input scope. `REVIEW_METADATA.review_decision` must mirror the `Decision Summary` recommendation, summary, and rationale. `REVIEW_METADATA.confidence_recovery` must mirror the `Confidence Calibration` section and include `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, and `remaining_limits`. `REVIEW_METADATA.confidence_gap_closures` must include one closure record per non-empty `confidence_gaps` entry, with `status=closed|unresolved|deferred` and matching evidence or rationale.

## Fail-fast Rules

01. Empty `files.txt` and `untracked.txt` with no explicit target => fail.
02. Shared gate or diff collection script missing => fail.
03. Result artifact missing => fail.
04. Review that skips changed-file inspection => fail.
05. Blocking finding without local evidence or pattern check => fail.
06. Missing T0 scope classification => fail.
07. Routing signals, triggered roles, manifest roles, and specialist files disagree => fail.
08. Triggered axis without a spawned or explicit substitute output => fail.
09. Missing review routing or schema-v2 specialist manifest => fail.
10. `BROAD` or `HIGH_RISK` review that returns `status=pass` with substituted required specialists => fail.
11. Result artifact validator failure => fail.
12. Missing `review-notes.md` sections => fail.
13. PR scope without `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, `diff.patch`, `comments.json`, `reviews.json`, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json` => fail.
14. PR scope that ignores unresolved online reviews without triage => fail.
15. Missing structured review decision summary or invalid recommendation value => fail.
16. PR scope using `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for source inspection instead of the local checkout => fail.
17. PR scope running `git` or `gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
18. Missing `Confidence Calibration` section, `metadata.confidence_recovery`, or `metadata.confidence_gap_closures` => fail.
19. Shared confidence policy violation from `../_shared/quality-gates.md` => fail.
20. Spawned specialist without validated parent/child rollout provenance, hashes, or exact output binding => fail.
21. More than two attempts or retry after a non-transient outcome => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, local changed-file inspection, simplicity/readability/reproducibility inspection, project docstring-style detection, docstring/comment policy inspection for changed code, PR target-branch refresh and checkout evidence when relevant, specialist manifest, specialist notes, structured decision summary, confidence calibration/recovery, online review triage for PR scope, severity map, and `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run or inspect available results when needed to validate a finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, decision vocabulary, or output shape changes:

- benchmark patterns: `review`
- behavioral cases: false blocker, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage, missing project docstring-style detection, missing code self-documentation, long code blocks, deep branching, docstrings masking poor structure, low-confidence recovery loop, objective confidence evidence
- PR routing cases: target-branch refresh required, local checkout required, stale local PR branch, and raw-file snapshot rejection

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

The final chat output must start with a compact `Review Decision Summary` before findings. Include recommendation, blockers, required next work, confidence with material limits, and artifact path. Keep full routing, recovery, and closure evidence in the artifact instead of duplicating it in chat. The recommendation must be one of `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`.

Minimum artifact payload template: `result-template.json`.
