---
name: code-review
description: Close PRs at an evidence gate or review local diffs/PRs with specialists and JSON artifacts.
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

Run `create_run.py --skill code-review` per `../../shared/helper-cli-contract.md`.

### 02: T0 mechanical scope gate

For local scopes, inspect `python PLUGIN_ROOT/shared/collect_diff.py --help`; collect normalized `scope`, optional `target`, and the literal `<run-directory>` path.

For PR scope, inspect `python PLUGIN_ROOT/shared/collect_pr.py --help`; collect the exact target into the literal `<run-directory>` path with checkout enabled.

In runtimes with network sandboxing, execute the complete collector command with approved external network access from its first attempt under `../../shared/native-skill-contract.md`. Before requesting it, state:

- `Action and purpose`: collect current PR evidence.
- `External capability`: read-only GitHub access plus the documented local checkout.
- `Credential behavior`: `gh` is an opaque local credential broker.
- `Filesystem and worktree effects`: write collection artifacts and may update the local checkout.
- `Retry policy and safe denial outcome`: one classified recovery only, otherwise the review is unavailable.
- For Codex exec, set `sandbox_permissions="require_escalated"` on the collector with a narrow read-only GitHub justification; never request a broad `python` approval prefix. Apply the other shared runtime and denial boundaries. A direct approval for `gh pr view` does not cover `gh` spawned by the collector: the outer collector command owns its nested GitHub CLI, HTTPS fallback, checkout, and Git fetch traffic. The PR request authorizes asking, never bypassing runtime approval.
- If an agent-caused unapproved attempt returns `github-network` before any user approval request or denial, rerun that same complete collector command once through the runtime's external-network approval mechanism before producing a terminal unavailable result. This recovery exists only for that pre-denial sandbox mistake; after the user denies approval, the current turn stops and the retry is forbidden. Only after that approved collector attempt fails, external-network approval is unavailable, or the user denies it may the terminal collection-failure gate apply; never repeat more than one approved recovery attempt.

PR evidence has two tiers.

- Core evidence: `gh pr view` metadata including contributor description/body, authoritative base-repository identity, refreshed target ancestry, an exact local PR head, and a diff derived with local `git diff <base>...<head>` after SHA verification.
- Supplemental evidence: GraphQL review-thread resolution state and derived diff statistics.

Collector and source boundary:

- The collector delegates remote GitHub state reads to `github_read.py`, which uses `gh` as an opaque local credential broker: it never invokes `gh auth`, reads token/keychain state, or writes CLI failure output to artifacts.
- That read-only boundary permits audited view commands, REST GET, and GraphQL query operations; public HTTPS fallback cannot establish private PR evidence.
- A classified core command failure is recorded in `command-failure.json` when diagnostics exist.

Checkout and source requirements:

- For an open PR, use fork-aware `gh pr checkout <number>` unless the current HEAD already exactly equals PR metadata; historical collection fetches GitHub's `refs/pull/<number>/head`, verifies its exact SHA, and checks it out detached.
- Inspect source only in the local checkout recorded by `<run-directory>/local-checkout.json`; `diff.patch` must record `diff_source=verified-local-checkout` provenance there.
- Never reconstruct changed source from `curl`, `raw.githubusercontent.com`, or `head-files/` snapshots.
- If checkout or local-diff verification fails, fail instead of reviewing remote raw files.
- Do not retry with `--force` unless user explicitly confirms after receiving force reason and overwrite risk.

When `gh pr view` metadata fails, public unauthenticated HTTPS fallback is eligible only when all of these hold:

- The failure is `github-network`, `github-auth`, `github-rate-limit`, or `command-timeout`.
- The checkout target is trusted: a canonical PR URL must match a configured GitHub remote; a numeric target requires exactly one distinct configured GitHub repository identity.

Ambiguous or unsafe targets, permission failures, not-found failures, and unclassified failures remain fail-closed.

Fallback behavior:

- The fallback normalizes limited PR metadata, then uses the verified `refs/pull/<number>/head` ref for a detached checkout and derives the local diff; it never establishes private PR evidence.
- `online-review-summary.json` must list unavailable fallback evidence as sorted IDs.
- Raw GitHub CLI stderr is never persisted; terminal diagnostics may include a safe `failure_reason` enum alongside non-secret classification metadata.

Classify diff; write `<run-directory>/scope.txt`:

- `TRIVIAL`: no public API/config/security/ML behavior touched, \<3 files, \<50 changed lines.
- `LOCAL`: one subsystem or 3-7 files; local context explains behavior.
- `BROAD`: 8+ files, cross-subsystem change, dependency/config change, or unclear ownership.
- `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

For `scope=pr`, merge-oriented code review is limited to an `OPEN` PR. `collect_pr.py` can also collect historical evidence for a merged or closed PR, including its diff, online discussions, refreshed current target state, and exact checked-out PR head; that raw collector evidence is useful for diagnosis but must not receive a merge recommendation or feed code-remediate. For an open review, core evidence includes `pr.json`, `pr-routing.json`, `remote-selection.json`, `target-branch.json`, `local-checkout.json`, and locally derived `diff.patch`; online evidence includes comments, reviews, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json`. Selected remote must match the base repository from the PR URL. The freshly fetched target must equal or descend from the PR-recorded base, proven by `expected_base_is_ancestor=true`; target advancement is integration context, never a PR finding or merge blocker. Genuine divergence fails collection. The local checkout head must exactly match open-PR metadata. Historical `target-branch.json` may record divergence. `pr-routing.json` and `local-checkout.json` must include `force_policy` proving no automatic forced checkout. Treat unresolved online threads/comments as candidate findings until triaged valid, duplicate, stale, out-of-scope, or already fixed. If GraphQL review-thread collection fails or is incomplete, continue source review with empty normalized thread arrays, `review-threads-error.txt`, `review_threads_status=unavailable`, explicit partial-online-triage notes, and confidence gap `PR review-thread resolution status was unavailable; online review triage may be incomplete.` Never convert that supplemental integration gap into a PR finding or merge blocker by itself.

If `files.txt` and `untracked.txt` are empty with no explicit target, fail before gates. If `scope=pr` and `pr-error.txt` exists, fail with captured reason and do not begin T1/T2 source review.

**Terminal review-unavailable output gate:** A core T0 PR collection failure is a process failure, not a review result.

- State `PR Review Availability: unavailable`; `Source findings: not assessed`; and `Merge decision: not made`.
- Use plain diagnostic prose with exactly a process diagnostic, recovery action, and evidence path.
- Do not emit a Markdown table: neither `PR Evidence Collection Recovery` nor `Review Findings and Merge Blocks` applies before source assessment.
- Do not emit `needs-more-work`, `minor-changes`, `reject`, `not-aligned`, or any other merge recommendation.
- Retain current-attempt metadata, checkout state, or partial diff artifacts for diagnosis, but label them unassessed and never turn them into findings.
- Name the classified failure and `<run-directory>/pr-error.txt`, then stop.
- Still write a canonical `result.json` with `status=fail`, zero findings, `review_status=unavailable`, and `collection_failure={"code": "<pr-error.txt text>", "artifact": "pr-error.txt"}`; the review-specific validator rejects a review decision, source findings, specialist artifacts, any table, or assessed-review sections.

For retryable `github-network`, `github-rate-limit`, or `command-timeout`, explain that no review occurred and ask the user to retry the unchanged collector later; rate-limit diagnostics deliberately retain no server interval.

- If `checkout-state.json` exists, say the local checkout command may have changed the worktree, tell the user to inspect that local state before retrying, and never claim no checkout was produced.
- For `github-auth` or a permission failure, stop and explain that the local `gh` configuration/account access needs repair; tell the user to run `gh auth status` and, if needed, `gh auth login` privately outside the agent workflow, verify repository access, and never paste tokens, keychain data, or credential output into chat.
- For `missing-command:gh`, tell the user to install or repair `gh` locally before retrying.
- For `github-not-found`, ask for the canonical PR URL and repository identity.
- For definitive `unsafe-gh-command`, invalid protocol/JSON, missing required PR identity, or an unclassified deterministic collector error, stop at the unavailable result, explain the classified code and artifact, and suggest filing a Codex Rig bug with the plugin version, command label, failure code, and sanitized artifacts.
- Never retry a deterministic target, permission, safety-guard, or plugin-contract failure automatically.

**Terminal close gate (PR only):** After successful T0 collection for an `OPEN` PR and before structural context or T1/T2, screen the PR goal, description, minimal verified diff evidence, authoritative project policy/history, and linked upstream evidence for one conclusive proposal-level close reason. This is a disposition decision, not a source review. If evidence is inconclusive, continue to T1/T2; never close from suspicion, reviewer preference, contributor identity, AI authorship/style, or a merely related change.

Use exactly one close code:

| Code | Conclusive evidence | Insufficient alone |
| -- | -- | -- |
| `FALSE_GOAL` | The stated goal contradicts a citable invariant, specification, domain fact, or verified current behavior. | Implementation disagreement, stale wording, or an unverified claim. |
| `BREAKING_CONDUCT` | Direct evidence that the contribution is intentionally malicious or adversarial by design, such as a backdoor, exfiltration, or supply-chain attack. | An accidental security bug, poor code, suspicion, or inferred intent. |
| `WRONG_SCOPE` | A documented roadmap, maintainer decision, ADR, or contribution boundary directly excludes the proposed goal. | Size, mixed files, or an undocumented preference. |
| `WRONG_PROVENANCE` | A documented license or rights requirement and objective evidence of an incompatible or unresolvable provenance conflict. | Fork ownership, code similarity, unknown provenance, or a missing CLA/DCO signature that the project permits the contributor to fix. |
| `DUPLICATE` | A verified merged change or resolved upstream issue already supplies the same still-applicable outcome. | A similar title, overlapping files, related open work, or the same issue area. |
| `UNADDRESSED_REVERT` | The PR semantically reintroduces a reverted change and does not address the documented reason for that revert. | File overlap, patch similarity, or a revert title alone. |
| `SPAM` | Objective irrelevant, promotional, repeated-submission, or non-substantive evidence shows no bona fide project change. | A small change, missing tests, low quality, or AI-generated content by itself. |
| `ARCHITECTURE_VIOLATION` | The proposal directly contradicts a documented current architectural principle. | Style preference, abstraction concern, or reasoning that requires detailed source review. |

A close decision requires `confidence >= 0.90`, two distinct evidence sources, a recorded counterevidence/falsification check, and binding to the verified current PR head. Public-HTTPS fallback evidence cannot close because its confidence cap is `0.89`. For `WRONG_PROVENANCE`, a missing required CLA/DCO signature remains a normal blocking item unless documented project policy makes the conflict terminal. For `BREAKING_CONDUCT`, an accidental security defect remains a normal blocking finding; only evidenced by-design harm reaches this gate.

On close, skip structural context, T1, T2, specialist routing, detailed findings, severity classification, and the normal recommendation step. Write `review-notes.md` with `Review Decision: close`, source findings `not assessed`, detailed review `skipped`, the exact close reason, summary, rationale, evidence, counterevidence checked, and `GitHub mutation: not performed.` Emit `status=pass` for the successfully completed workflow, zero findings, `review_status=closed`, and `close_decision={"schema_version": 1, "code": "<CODE>", "advisory_only": true, "head_sha": "<verified PR head>", "summary": "<summary>", "rationale": "<rationale>", "evidence": [{"claim": "<observed fact>", "source": "<artifact, repository path, or authoritative URL>"}], "counterevidence_checked": ["<falsification check>"]}`. Include at least two distinct evidence entries. Omit `review_decision`, recommendations, follow-up, review routing, specialist artifacts, and every Markdown table. Run the shared gates with detailed-review checks marked not applicable and the `review` gate validating the close artifact, then run both artifact validators. This result only advises the user to close; never close, comment on, merge, or otherwise mutate GitHub.

**Structural context (optional)**: after the diff is collected, also probe codemap-py once for changed-symbol blast radius: `python PLUGIN_ROOT/shared/codemap_adapter.py context --category review --out <run-directory>/codemap-context.json`. Per `../../shared/codemap-contract.md`, absence/incompatibility is non-fatal — continue with T1/T2 as scoped by `scope.txt` alone. Persist the diff-impact evidence once here; T2 specialist fan-out (step 04) includes `<run-directory>/codemap-context.json` in each triggered context pack, never a fresh per-specialist query.

### 03: T1 primary diff review

Review axes, in order:

- API and behavior regressions.
- Test coverage and edge-case gaps.
- Error handling and logging.
- Project coding principles: changed code follows the applicable `AGENTS.md` layers for simplicity, readability, reproducibility, short reusable units without low-value argument-remapping wrappers, guard clauses or early `return`/`yield`/`continue`, project docstring-style detection, concise purpose docstrings, and inline comments only for non-trivial implementation blocks.
- Security, data, ML, CI/CD, or release risks signaled by T0.
- Documentation or migration gaps caused by behavior/API changes.

Blocking defaults guide merge judgment; they are not automatic labels:

| Category | Default | Nuance |
| -- | -- | -- |
| CI red or failing check | blocking | Only a major or required-check failure. Note a single flaky-looking rerun blip without automatically blocking. |
| Missing test coverage for new or changed logic | blocking | Require coverage proportional to the changed contract and regression risk. |
| Accidental security bug | blocking | Evidenced by-design harm is terminal `BREAKING_CONDUCT` at the close gate. |
| Breaking API change without deprecation or migration path | blocking | Require the project-compatible transition before merge. |
| Missing docs for new or changed public behavior | blocking | Missing CHANGELOG entry alone is not blocking and may be completed through the release workflow. |
| Performance regression | contextual | Block an unexplained regression against recent releases; do not block when a correctness fix necessarily removes invalid prior speed. |
| Merge conflicts | not blocking | Conflict resolution belongs to `code-remediate`; review does not gate on the conflict alone. |
| Incomplete implementation | blocking | Includes TODOs in changed paths, missing expected error handling, or an unfinished public contract. |
| Missing CLA/DCO signature | blocking only when the project requires it | Verify a CLA/DCO bot check or explicit contribution policy first; without such a requirement it is not applicable. |

### 04: T2 risk-routed specialist fan-out

Always:

- Write `<run-directory>/review-routing.json` with `schema_version=1`; declared risk tier; every exact boolean signal below; `signal_evidence` as an object containing every signal with a non-empty JSON `list[str]` value for each true/false decision; sorted `triggered_roles`; and `trigger_reasons` as an object containing only triggered roles with a non-empty JSON `list[str]` value.
- For example, write `"signal_evidence": {"bug_fix": ["PR body and changed test identify the corrected behavior."]}` and `"trigger_reasons": {"qa-specialist": ["Bug-fix and test-path evidence require QA."]}`. Bare strings are invalid.
- Then run `python PLUGIN_ROOT/skills/code-review/review_routing.py --out <run-directory>` so the shipped deterministic producer replaces `mechanical_risk_tier` and `mechanical_risk_evidence` from `files.txt`, `untracked.txt`, and `numstat.txt`; never calculate or copy those fields manually.
- Keep the declared tier at or above mechanical file/line, binary-size, config/dependency, CI, migration, or security-path evidence.
- Set matching signals true for mechanically detected test, docs, data/tensor, CI, and security paths.
- Write `<run-directory>/specialist-manifest.json`, with empty `passes` when no role triggers. Never add untriggered manifest roles.

Required routing signals:

- QA risk: `behavior_change`, `bug_fix`, `test_or_error_path`, `data_tensor_boundary`.
- Challenge risk: `high_candidate`, `unresolved_material_assumption`, `material_no_finding`, `explicit_adversarial`.
- Conditional axes: `axis_solution_architect`, `axis_security_auditor`, `axis_data_steward`, `axis_cicd_steward`, `axis_linting_expert`, `axis_doc_scribe`, `axis_oss_shepherd`, `axis_squeezer`, `axis_scientist`, `axis_web_explorer`.

Routing rules:

- `TRIVIAL`: no automatic QA/challenger pass; conditional axes may trigger.
- `LOCAL`: QA only for QA-risk; challenger only for challenge-risk. File-count-only LOCAL triggers neither.
- `BROAD` and `HIGH_RISK`: always real QA and challenger passes.
- Conditional role only when matching `axis_<role>` signal is true.

For every triggered pass:

- Create `<run-directory>/specialists` and one markdown output per triggered spawned/substituted pass.
- Apply `../../shared/specialist-orchestration.md`.
- Before the pass, write narrow `<run-directory>/specialists/<role>-context.md`: objective, axis, relevant evidence, excluded noise, concrete questions, output contract, stop rule.
- Never give every specialist whole PR/repository.

Parent owns final severity, duplicate merge, conflict resolution, and decision.

For a spawned attempt:

- Hash completed context before spawn; task name `review_<role_with_underscores>_<first_12_context_sha256>_a<attempt>`.
- Record full agent path. This binds runtime child identity to role, context artifact, and attempt even when rollout schema leaves `agent_role` null.
- Runtime encrypts actual inter-agent payload: do not claim cryptographic proof plaintext exactly equals saved context; record residual limit in confidence metadata.

Compute SHA-256 for `diff.patch` and every context pack. Require exact first specialist line (replace placeholders):

```text
<!-- codex-review-provenance role=<role> run=<review_run_id> input=<review_input_sha256> context=<context_sha256> attempt=<n> -->
```

Routed specialist axes:

- `qa-specialist`: tests, edges, regressions, tensor/data boundaries.
- `challenger`: adversarial assumptions, high findings, migration/API risks, material no-finding conclusions.
- Conditional roles: `data-steward`, `cicd-steward`, `linting-expert`, `doc-scribe`, `oss-shepherd`, `squeezer`, `scientist`, and `web-explorer` cover named domains. `solution-architect` and `security-auditor` are Sol-pinned and never triggered by a matching domain alone: use either only when the user expressly requests Sol or selects that role, then return its bounded read-only evidence artifact to the Terra parent/session for review acceptance.

Use runtime-provided subagents when independence materially helps and follow the portable route order in the shared orchestration policy.

- A built-in/default child receives the exact canonical role card before its context pack.
- It may count as independent only when it has a separate child identity/output and the artifact records the card hash, route, actual model, and observed controls.
- If no safe subagent route exists, write a labeled in-main substitute for each triggered role and set `fanout_substituted=true`.
- Substitution lowers confidence and never satisfies independence for critical findings.

`specialist-manifest.json` uses schema version 2 and contains `review_run_id`, `parent_thread_id=$CODEX_THREAD_ID`, `review_input_sha256`, and triggered passes only.

- Each spawn records role-card hash, route, attempted routes, fallback reason, requested and observed controls, parent spawn event ID, child thread ID/path, turn ID, actual model/effort, context/output paths/hashes, status, and transient error type when applicable.
- `selected_attempt` identifies completed output.
- Validator checks hash-derived child name, parent spawn, child linkage, actual model/effort, final child message, hashes, and provenance header against Codex rollout logs.

Attempt policy:

- At most two attempts/role.
- Retry only `timeout`, `transport_error`, or `rate_limited`; never retry deterministic findings, validation failures, completed work.
- Preserve completed outputs/context.
- Checkpoint is evidence only, never completed output/provenance replacement.

Independence gate:

- `BROAD`/`HIGH_RISK` pass only with real independent QA/challenger outputs.
- Set `independence_required=true` only when QA/challenger risk-triggered; set `independence_satisfied=true` only when every triggered required role has validated spawned provenance.
- If either output is unavailable, fail/timeout with `independence_satisfied=false` and `needs-independent-review`.
- Risk-triggered `LOCAL` may pass with explicit substitutes only if every triggered axis is covered and confidence is reduced.

### 05: Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly

### 06: Write `<run-directory>/review-notes.md`

Required sections:

- `Decision Summary`
- `PR Snapshot` for every assessed `scope=pr` review
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

When `online-review-summary.json` reports `pr_metadata_transport=public-https-fallback`, `Online Review Triage` must list the sorted `unavailable_evidence` IDs `github_provided_file_list`, `mergeability`, `review_decision`, `reviews`, and `top_level_comments`, and add the exact confidence gap `Public HTTPS PR metadata fallback omitted evidence: <sorted IDs>.` Substitute that sorted list into `<sorted IDs>`. The final review confidence is capped at `0.89`; preserve the gap and its closure state in the confidence metadata.

### 07: Run shared quality gates

Inspect `python PLUGIN_ROOT/shared/run_gates.py --help`; run every project-relevant review gate with explicit command/skip reason.

### 08: Classify findings using `../../shared/severity-map.md`

### 09: Compute the structured review decision and update `Decision Summary`

Skip this step after a T0 PR collection failure: write the terminal availability/recovery output instead, with no recommendation or merge decision.

Use exactly one recommendation:

- `accept-as-is`: no findings; required gates passed/not applicable; residual risks explicitly low.
- `minor-changes`: only non-blocking low/medium findings or polish remain.
- `needs-more-work`: high findings, missing tests/evidence, failed relevant gates, or unresolved review-risk gaps.
- `reject`: critical findings, unsafe behavior, security/data-loss risk, or another terminal defect discovered during a completed detailed review.
- `not-aligned`: change does not address requested issue, PR intent, migration contract, or project direction despite mechanical soundness.

`Decision Summary` must include:

- `Recommendation`: exact value above
- `Summary`: 1-3 sentences covering outcome
- `Rationale`: why recommendation follows from findings, gates, scope
- `Blocking findings`: critical/high items or `none`
- `Minor changes`: medium/low items or `none`
- `Required next work`: pre-merge work or `none`
- `Confidence`: score plus key gaps

For an assessed `scope=pr` review, immediately before user-facing output, rebuild `PR Snapshot` from the current run's `pr.json`, `pr-routing.json`, and `gates.json`; never reuse a PR number, author, CI state, or recommendation from the invocation or earlier chat. This is a refreshed presentation of the exact evidence reviewed, not a new network fetch after review.

`PR Snapshot` must use this compact Markdown table in `review-notes.md` and reproduce it before findings in the final chat:

| Field | Value |
| -- | -- |
| PR | `[#<number> — <title>](<url>)` |
| Author | `@<pr.json author.login>` |
| CI | `passing`, `failing — <check names>`, `pending — <check names>`, or `unavailable` |
| Type | `fix`, `feat`, `refactor`, `perf`, `docs`, `ci`, `chore`, `test`, or `mixed` |
| Suggestion | `approve`, `minor changes`, `needs work`, `reject`, or `not aligned` |

Read PR CI from `pr.json.statusCheckRollup`: a failing completed check makes CI `failing`; otherwise an incomplete check makes it `pending`; otherwise completed successful/neutral/skipped checks make it `passing`. An absent or empty rollup is `unavailable`, never `passing`; name the known non-passing checks. Classify `Type` from verified change intent and diff, not title or file count. Map `Suggestion` directly from `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, and `not-aligned`, respectively. The snapshot applies only after successful source assessment: terminal unavailable and close outputs retain their existing no-table contracts.

For every assessed non-`accept-as-is` PR decision and any `needs-more-work` decision in another scope, add a `## Review Findings and Merge Blocks` section immediately after `Decision Summary`. It is the canonical pre-merge handoff and must use this exact Markdown header and column order:

| Finding / area | Required change | Evidence | Status |
| -- | -- | -- | -- |
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

### 11: Declare no findings and residual risk

### 12: Write and validate the mandatory result artifact

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write with `CODE_REVIEW_METADATA` and `FOLLOW_UP`; run review-specific validator before shared validator for `code-review`; promote only candidate accepted by both.

`CODE_REVIEW_METADATA.specialist_passes` mirrors every triggered `specialist-manifest.json` entry; `review_run_id`/`review_input_sha256` mirror top-level values. `CODE_REVIEW_METADATA.scope` matches normalized scope. For assessed reviews, `CODE_REVIEW_METADATA.review_decision` mirrors `Decision Summary` recommendation, summary, rationale. A terminal collection failure records `review_status=unavailable` with source findings not assessed and merge decision not made. A terminal close records `review_status=closed` plus the validated `close_decision`, with source findings not assessed and detailed review skipped. Both terminal shapes use exactly zero `critical`, `high`, `medium`, and `low` findings and omit normal recommendations/follow-up and assessed-review metadata. Every assessed non-`accept-as-is` PR and every `needs-more-work` result in another scope carries the validated canonical `Review Findings and Merge Blocks` table in `review-notes.md`; terminal unavailable and closed results use their canonical plain prose and no table. An assessed review with unavailable thread-resolution evidence includes the canonical thread confidence gap and unresolved/deferred closure rationale. `CODE_REVIEW_METADATA.confidence_recovery` mirrors `Confidence Calibration` and includes `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, `remaining_limits`. `CODE_REVIEW_METADATA.confidence_gap_closures` has one closure per non-empty `confidence_gaps`, with `status=closed|unresolved|deferred` and matching evidence/rationale.

## Fail-fast Rules

01. Empty `files.txt` and `untracked.txt` with no explicit target => fail.
02. Shared gate or diff collection script missing => fail.
03. Result artifact missing => fail.
04. Assessed review that skips changed-file inspection => fail; a terminal close instead requires minimal verified diff evidence at T0.
05. Blocking finding without local evidence or pattern check => fail.
06. Missing T0 scope classification => fail.
07. Detailed-review routing signals, triggered roles, manifest roles, and specialist files disagree => fail.
08. Detailed review triggers an axis without spawned/explicit substitute output => fail.
09. Detailed review is missing review routing or its schema-v2 specialist manifest => fail.
10. `BROAD` or `HIGH_RISK` review returning `status=pass` with substituted required specialists => fail.
11. Result artifact validator failure => fail.
12. An assessed review is missing required `review-notes.md` sections, or a terminal result violates its exact prose shape => fail.
13. PR scope without PR body metadata, authoritative remote/target evidence, exact `local-checkout.json`, locally derived `diff.patch`, comments/reviews, normalized thread artifacts, and `online-review-summary.json` => fail.
14. PR scope ignores unresolved online reviews without triage, or claims complete thread triage when `review_threads_status=unavailable` => fail.
15. An assessed review has a missing structured review decision summary or invalid recommendation => fail.
16. PR scope uses `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for source inspection instead of local checkout => fail.
17. PR scope runs `git`/`gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
18. Missing `Confidence Calibration`, `metadata.confidence_recovery`, or `metadata.confidence_gap_closures` => fail.
19. Shared confidence policy violation from `../../shared/quality-gates.md` => fail.
20. Spawned specialist lacks validated parent/child rollout provenance, hashes, or exact output binding => fail.
21. More than two attempts or retry after non-transient outcome => fail.
22. An assessed non-`accept-as-is` PR or `needs-more-work` result is missing a complete actionable `Review Findings and Merge Blocks` table => fail.
23. A terminal core T0 PR collection failure emits any Markdown table or merge recommendation, omits its plain process diagnostic/recovery/evidence prose, or does not explicitly mark source findings `not assessed` and merge decision `not made` => fail.
24. A terminal close lacks one valid close code, two distinct evidence sources, a counterevidence check, verified-head binding, `confidence >= 0.90`, or advisory-only/no-mutation state => fail.
25. A terminal close emits findings, a normal recommendation/follow-up, any Markdown table, review routing, specialist artifacts, or detailed-review claims => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, either validated terminal close evidence or local changed-file inspection, simplicity/readability/reproducibility inspection, project docstring-style detection, docstring/comment policy inspection for changed code, PR body/target/checkout/local-diff evidence when relevant, specialist manifest/notes when detailed review proceeds, structured assessed decision summary or terminal unavailable/closed result, non-approval PR findings/action table for assessed reviews, plain terminal diagnostics, explicit supplemental-thread degradation, confidence calibration/recovery, PR online-review triage when assessed, severity map when assessed, `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run/inspect available results when needed to validate finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, decision vocabulary, or output shape changes:

- benchmark patterns: `code-review`
- behavioral cases: false blocker, target-advance false blocker, supplemental-thread degradation, sandboxed collector network approval, each terminal close code plus its false-positive fall-through, close-versus-reject separation, closed-report remediation rejection, non-approval PR findings/action table missing a reported finding, missing `needs-more-work` table, T0 PR collection failure with a merge recommendation/table or without plain process diagnostic/source findings `not assessed`/merge decision `not made`, malformed finding-table row, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage, missing project docstring-style detection, missing code self-documentation, long code blocks, deep branching, docstrings masking poor structure, low-confidence recovery loop, objective confidence evidence
- PR routing cases: target-branch refresh required, fork-aware numbered local checkout, exact-head checkout reuse, verified local diff required, stale local PR branch, raw-file snapshot rejection

## Output Contract

Before writing the result candidate, follow `../../shared/final-handoff-contract.md`: use branch `assessed`, `unavailable`, or `closed` exactly as the review result requires; render and bind `final-handoff.json`, `final.md`, and `final-handoff.validation.json`; after both validators and promotion pass, emit `final.md` verbatim. Terminal `unavailable` and `closed` branches forbid tables; an explicitly requested exact caller format uses `caller-contract`.

Use `../../shared/quality-gates.md`.

Final chat follows the shared ordered frame with these review-specific branches.

For an assessed review:

- `Outcome` starts with compact `Review Decision Summary`: recommendation, blockers, and required next work.
- `Results` reproduces the fresh `PR Snapshot` immediately after the summary and before any findings for every assessed PR. It also reproduces the canonical `Review Findings and Merge Blocks` table for every assessed non-`accept-as-is` PR and every `needs-more-work` decision in another scope; this table is mandatory decision handoff.
- Apply the shared `Verification`, `Remaining`, `Next steps`, `Confidence`, and supplemental `Artifact` rules; name reviewed evidence, checks, unresolved blocks, owners, and material limits.

For a terminal core T0 PR collection failure:

- Start `PR Review Availability: unavailable`.
- Use plain prose for classified process diagnostic, `Next steps` recovery, source findings `not assessed`, merge decision `not made`, confidence/material limits, evidence, and artifact path.
- Do not use a table or normal recommendation.

For a terminal close:

- Start `Review Decision: close` and name the close code.
- State source findings were not assessed, detailed review was skipped, decisive evidence, counterevidence checked, and `GitHub mutation: not performed`.
- Provide confidence/material limits and artifact path without a table or normal recommendation.
- Omit a separate `Next steps` recommendation because the close code is terminal.

Keep full routing, recovery, and closure evidence in the artifact. Assessed recommendations remain `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`.

Minimum artifact payload template: `result-template.json`.
