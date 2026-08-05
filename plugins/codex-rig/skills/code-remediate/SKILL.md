---
name: code-remediate
description: 'Codex-native code-remediation loop: triage/apply code-review findings, rerun checks, publish unresolved gaps with measurable gates; `$code-remediate #123 +review` remediates a PR from latest matching code-review artifact.'
---

# Code Remediate

See the [fixed recurrence and root-cause policy](../../shared/native-skill-contract.md#recurrence-and-root-cause-policy) for repeated-obstacle handling; it governs symptom patching, escalation, and reset evidence.

Run linear code remediation to close findings.

## Input Schema

```json
{
  "findings_source": "optional path, explicit list, or +review/+report/report/latest to auto-select the newest matching review report",
  "mode": "optional report|pr|auto; infer pr for bare number, #number, or PR URL",
  "target": "optional shorthand target number, issue/PR URL, path, or current branch",
  "pr_target": "optional PR number, PR URL, or current branch PR when mode=pr",
  "remediation_scope": "optional all|critical|high|medium|low|comma-separated severities|comma-separated selection indexes; ask before editing when omitted",
  "target_scope": "required path/module",
  "done_when": "selected findings are fixed/resolved and unselected critical/high findings are explicitly deferred"
}
```

## Workflow (Exact Commands)

### 01: Create Run Directory

Run `python PLUGIN_ROOT/shared/create_run.py --skill code-remediate` once. Retain its single printed path as
`<run-directory>` and substitute that literal path into every later artifact path and helper argument. Never store or
reuse the path through a shell variable; shell variables do not persist across tool calls.

### 02: Normalize Shorthand Input And Copy Findings Source

Shorthand rules:

- Canonical in-session: `$code-remediate #123 +review` => `mode=pr`, `PR_TARGET=123`, `FINDINGS_SOURCE=latest-matching-review-report`.
- Compatibility alias: `$code-remediate #123 +report` => `mode=pr`, `PR_TARGET=123`, `FINDINGS_SOURCE=latest-matching-review-report`; `$code-remediate #123 +report compatibility alias` has same report lookup.
- Natural-language aliases: `remediate 123 report`, `remediate #123 report`, and `remediate PR 123 report` => `mode=pr`, `PR_TARGET=123`, `FINDINGS_SOURCE=latest-matching-review-report`.
- `remediate <github-pr-url> report` => `mode=pr`, `PR_TARGET=<github-pr-url>`, `FINDINGS_SOURCE=latest-matching-review-report`.
- If `+review`, `+report`, `report`, `latest`, `latest-report`, or `review-report` replaces a path, find newest `.reports/codex/code-review/*/result.json` whose sibling `pr.json` has same PR number/URL as `PR_TARGET`.
- No matching code-review report => fail with direct instruction to run `$code-review <target>` first or supply report path.
- Multiple matches => use newest timestamped directory; record selected path in `<run-directory>/findings-input.txt`.

For `latest-matching-review-report`, inspect `python PLUGIN_ROOT/shared/find-review-report.py --help`, resolve `PR_TARGET` against `.reports/codex/code-review`, assign printed path to `FINDINGS_SOURCE`.

Copy the exact bytes from the retained findings-source path to `<run-directory>/findings-input.txt` with the
filesystem tool. Do not depend on a shell variable retaining that source path.

For `mode=pr`, inspect `python PLUGIN_ROOT/shared/collect_pr.py --help`; collect `PR_TARGET` into `<run-directory>/pr` with checkout enabled for current online evidence, target/head refresh, local checkout.

Helper records `gh pr checkout` without `--force` in `<run-directory>/pr/local-checkout.json`.

Findings intake: review report plus `<run-directory>/pr/comments.json`, `<run-directory>/pr/reviews.json`, `<run-directory>/pr/review-threads.json`, `<run-directory>/pr/unresolved-review-threads.json`. Review report is closure contract, not only code findings: before editing normalize report findings, failed `checks_failed`, `follow_up`, `review_decision.required_next_work`, confidence gaps, confidence-recovery remaining limits, and no-finding residual risks into report-origin action items. Use local checkout in `<run-directory>/pr/local-checkout.json` as authoritative source for code triage/edits. `<run-directory>/pr/target-branch.json` must prove base/target fetch before conflict/review-item resolution; `<run-directory>/pr/pr-head-fetch.json` records same-repo PR refresh or cross-repository skip rationale. Checkout artifacts include `force_policy`; if checkout fails or does not match PR head, record `forced-checkout-not-attempted` and stop before forced retry. If online collection, target refresh, or checkout fails, record failure; continue with supplied report only when user accepts stale online-review coverage and no code edits are required, else fail. Never inspect/edit PR code from `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots; raw-file snapshot rejection: snapshots are rejected.

### 03: Understand PR Intent, Then Resolve Merge Conflicts

For `mode=pr`, required before `action-items.md`, `resolution-scope.md`, or report/PR-review code changes. Establish clean PR and latest target implementation before conflict markers make worktree noisy.

Read `remote_ref` from `<run-directory>/pr/target-branch.json` with a JSON parser and retain the exact printed value as
`<base-remote-ref>`. Run `git merge-base HEAD <base-remote-ref>` as argv, retain its single printed value as
`<merge-base>`, and write that value to `<run-directory>/pr/merge-base.txt`. Run these argv commands separately and
write stdout to the named artifacts:

- `git diff --stat <merge-base>..HEAD` → `<run-directory>/pr/pr-intent.diffstat`
- `git diff --name-only <merge-base>..HEAD` → `<run-directory>/pr/pr-intent-files.txt`
- `git diff --stat <merge-base>..<base-remote-ref>` → `<run-directory>/pr/target-since-merge-base.diffstat`
- `git merge-tree <merge-base> HEAD <base-remote-ref>` → `<run-directory>/pr/merge-tree.txt`

Record each command's exit status; unavailable evidence is a gap, never an implied clean result.

Write `<run-directory>/merge-prestage.md` sections before attempting a merge:

- `## PR And Target Refresh`: PR number/head, target branch, fetched target hash, local checkout hash, evidence paths.
- `## Clean PR Implementation Context`: intended change, changed files, key invariants, clean-PR-implied tests/docs.
- `## Target Branch Context`: relevant fetched-target details, especially likely collision files.
- `## Conflict Risk`: mergeability, `merge-tree` signal, both-side changed files, conflicts present/likely/absent.
- `## Resolution Strategy`: reconcile PR intent and target implementation for each conflict/likely collision before review/report findings.
- `## Merge Execution`: conflict decision, authorization state, merge command/status, resolved paths, verification, and evidence path.

Write `<run-directory>/pr/merge-resolution.json` with `schema_version`, `conflicts_detected`, `status`, `authorization`, `base_remote_ref`, `target_oid`, `pre_merge_head`, `post_merge_head`, `merge_commit`, `resolved_paths`, `unmerged_paths`, and `evidence`. Use `status=not-needed` and `authorization=not-required` when fresh evidence proves no conflict. Do not merge the target merely to refresh a conflict-free PR.

If conflicts are present or likely, resolve them as PR integration before normalizing or addressing any report/online-review item:

1. Use the already-recorded clean PR purpose, invariants, target changes, and per-file resolution strategy as primary context. Inspect `git show <base-remote-ref>:<path>` and nearby tests where needed; conflict markers are secondary evidence only.
2. A generic remediation request does not authorize a local merge commit. Show the target ref/OID, intended merge, collision files, resolution strategy, and overwrite/commit effect. Ask for explicit authorization to create the local target-merge commit. Record `authorization=explicit-input|user-confirmed`; if authorization is absent or the runtime cannot ask, stop with `target-merge-authorization-required` before review-item work.
3. After authorization, run `git merge --no-commit --no-ff <base-remote-ref>` with the retained literal ref. Never rebase, force checkout, or rewrite history as a substitute.
4. Resolve only merge collisions, preserving the recorded PR intent atop the fetched target implementation. Do not combine review-comment fixes unless the same lines cannot otherwise form a coherent merge; record unavoidable coupling in `<run-directory>/closure-log.md`.
5. Verify `git diff --name-only --diff-filter=U` is empty, run the smallest collision-relevant tests, then create the authorized merge commit using `../../shared/commit-response-template.md` and the required `Co-authored-by: Codex <codex@openai.com>` trailer. Record the pre/post HEAD, merge commit, resolved paths, tests, and empty unmerged-path list in `merge-resolution.json` and `## Merge Execution`.

Do not create `action-items.md`, `resolution-scope.md`, or edit for a report/online-review finding until `merge-resolution.json` is `not-needed` or `completed`, the worktree has no unmerged paths, and no merge is in progress. If merge resolution or its verification fails, stop; do not hide the conflict behind finding remediation.

If checkout starts dirty, conflicted, or partially merged, fail or ask cleanup before editing. Never use an existing conflicted worktree as primary truth.

### 04: Normalize Findings Before Editing

**Structural context (optional)**: when `target_scope` names a Python module, also probe codemap-py once for
changed-symbol/caller impact: `python PLUGIN_ROOT/shared/codemap_adapter.py context --category review [--target
<qname>] --out <run-directory>/codemap-context.json`. Per `../../shared/codemap-contract.md`,
absence/incompatibility is non-fatal — continue normalizing findings from `findings-input.txt` alone. Persist the
result once here; specialist owners assigned in step 06 receive `<run-directory>/codemap-context.json` in their
context pack, never a fresh query.

Write `<run-directory>/action-items.md` starting with `## Review Item Resolution Table`, before prose. One row per ingested entry: all report findings, normalized report-origin review obligations, fetched online PR comments, PR reviews, review threads, unresolved review threads. If user supplied/requested report, include report items even if fresh PR evidence repeats them. Table is selectable-findings source; every `resolved` row needs resolution evidence. Never reduce ledger to changed/selected/unresolved/high-impact rows.

For `mode=pr`, check every report/PR-review item against PR intent and changed diff before triage:

- `direct-diff`: references PR-changed file/hunk/behavior.
- `pr-intent`: connects to PR purpose, acceptance criteria, review decision, requested change, even outside touched hunk.
- `adjacent`: touches nearby code/tests/docs/config/verification needed for safe merge.
- `unknown`: current evidence cannot determine relation.
- `unrelated`: no connection to PR intent, changed files, adjacent verification, or merge readiness after local PR-context inspection.

Write relation in action table and every expanded item. `direct-diff`, `pr-intent`, `adjacent`, `unknown` are never `out-of-scope`; keep `valid`/`needs-clarification` and selectable unless `resolved`, `already-fixed`, or `already-applied` evidence closes them. If current PR cannot close one, record `unresolved`, `deferred`, or required follow-up; never downgrade to `out-of-scope`. User can select, defer, or explicitly rule it into PR.

For review report, include non-code report-origin review obligations:

- failed `checks_failed`, including missing independence, full gates, lint, type, test, confidence gates
- `follow_up`, especially `needs-independent-review`
- `review_decision.required_next_work` and merge/readiness blockers
- confidence gaps, confidence-recovery remaining limits, no-finding residual risks blocking acceptance

Report-origin obligations default in scope for `+review`, `+report`, `report`, or review-report path. Never mark `out-of-scope` merely because closure needs independent reviewer, installed tool, CI/full-gate run, or unavailable local environment. Mark `valid`/`needs-clarification`, keep selectable, leave `unresolved`/user-deferred until closure evidence. `out-of-scope` only for item proven unrelated to requested report/PR/target after citing evidence; never use it to silence failed gates/follow-up.

After resolution table, add `## Review Report Intake`: total report-origin items, report-origin review-gate/follow-up items, selectable review-gate/follow-up items, report-origin `out-of-scope` count. Last count must be `0` unless item proven unrelated to requested report/PR/target.

Required table columns:

- selection index: numeric selectable; `-` non-selectable
- input item: stable input row id, report id, PR comment id, review id, thread id, source location
- item name: short human-readable finding/review obligation/gate/comment/thread name
- item type: `code|test|docs|review-gate|confidence-gap|pr-comment|pr-review|pr-thread|unresolved-pr-thread|ci|typing|lint|security|performance|process|other`
- item id or source location
- source: `report|pr-comment|pr-review|pr-thread|unresolved-pr-thread`
- fetched evidence path, or `report-only`
- PR/diff relation: `direct-diff|pr-intent|adjacent|unknown|unrelated`
- severity
- summary
- triage status: `valid|resolved|duplicate|stale|out-of-scope|already-fixed|already-applied|needs-clarification`
- resolution: `implemented|resolved|rejected|stale|not-applicable|duplicate|already-fixed|already-applied|needs-clarification|unresolved`
- owner/status: `todo|fixed|resolved|deferred|unresolved|not-selected|not-actionable`
- resolved how: how/why resolved/unresolved/deferred/not applicable
- closure evidence or unresolved rationale

After table add `## Final Resolution Summary`:

- what was requested
- ingested entries total
- resolved or already-closed entries total
- implemented entries total
- unresolved entries total
- deferred/not-selected entries total
- not-applicable/stale/duplicate/rejected entries total
- one sentence: all selected local actionable items closed or not

Then add `## Final Resolution Table Completeness`:

- ingested entries total
- final table rows total
- omitted entries total: must be `0`
- selectable/non-selectable row totals
- triage status counts
- resolution status counts

`CODE_REMEDIATE_METADATA.final_resolution_table` has same counts. Fail before output if final table omits an ingested entry, fails to account for every row in triage/resolution counts, or any row lacks triage/resolution status. `CODE_REMEDIATE_METADATA.final_resolution_table.required_columns` lists `input item`, `item name`, `item type`, `triage status`, `resolution`, `owner/status`, `resolved how`, `evidence`.

Closure evidence for report-origin obligation must match type:

- independent review: independent specialist/maintainer output path plus updated metadata proving independence, or unavailable rationale
- full gates: clean full-gate/CI result path, or workspace/environment-prevented rationale
- type/lint/test environment: installed-environment command log, or missing executable/dependency rationale
- confidence gap: closing evidence, or explicit unresolved/deferred record

After table, keep expanded item for each report finding and unresolved online review thread/comment:

- finding id or source location
- severity
- source and fetched evidence path
- PR/diff relation and evidence
- summary
- exact affected files
- expected closure evidence
- triage status: `valid|resolved|duplicate|stale|out-of-scope|already-fixed|already-applied|needs-clarification`
- resolution: `implemented|resolved|rejected|stale|not-applicable|duplicate|already-fixed|already-applied|needs-clarification|unresolved`
- owner/status: `todo|fixed|resolved|deferred|unresolved`
- unresolved rationale, when applicable

For ambiguous finding/thread/comment, inspect referenced local/checked-out code; sharpen to action item or `needs-clarification` before edits. If fetched PR evidence marks comment/thread resolved, table it as triage/resolution `resolved`, cite fetched evidence, state current PR marks it resolved; do not create implementation follow-up. If requested change already exists locally, mark triage/resolution `already-applied`, cite code evidence, no follow-up. Never fix duplicate, stale, out-of-scope, already-fixed, already-applied, or resolved comments; record triage evidence.

### 05: Ask For Resolution Scope Before Editing

Before code changes, build `<run-directory>/resolution-scope.md` with `## Resolution Scope Selection`. Selectable list includes every non-closed work-requiring finding; omits fetched online PR comments/threads currently resolved. Omit resolved online PR items from selection; keep them in `action-items.md` only as non-selectable audit rows, selection index `-`; omit-resolved-online rule.

Selection list table columns:

- index
- severity: `critical|high|medium|low`
- item id or source location
- source
- summary
- expected closure evidence

Selectable items:

- include triage `valid`
- include `needs-clarification` only when next step is clarification/code inspection, not implementation
- include report-origin failed checks, follow-ups, required next work, confidence gaps, residual risks unless cited evidence closes them
- include PR/review items related to PR intent, changed diff, adjacent verification, unknown relation unless cited evidence closes them
- exclude triage/resolution `resolved`, `duplicate`, `stale`, `out-of-scope`, `already-fixed`, `already-applied`
- exclude fetched online PR comments/threads marked resolved in current PR evidence

### Terminal Scope Context Contract

Before accepting an explicit scope or prompting for one, complete the pre-edit `<run-directory>/resolution-scope.md` document. It must contain, in this order:

1. `## Resolution Scope Selection`.
2. The selection source, exact prompt text or explicit-input note, selection-confirmation state, selected indexes/severity groups, omitted resolved-online count, deferred/unselected indexes, and unselected critical/high findings.
3. The complete six-column selection table above, with every selectable item. Do not abbreviate summaries, source locations, or expected closure evidence.

For an omitted `remediation_scope`, record the pending state before prompting: `selection source: user-prompt`, the exact prompt below, `user selection confirmed before editing: false`, and no selected indexes or severity groups. Retain resolved online items only as the documented omitted count; do not add them to the table.

Read the complete `<run-directory>/resolution-scope.md` through the filesystem tool and render it unabridged before
any scope prompt or edits. Immediately append `Full report: <run-directory>/action-items.md`; do not use shell output
or a persisted path variable to assemble this context.

The `Full report` path must appear immediately after the unabridged scope context and target `<run-directory>/action-items.md`, the complete normalized resolution report. The link supplements the scope context; do not replace the context with a `Selectable items:` summary, shortened numbered list, artifact link, or ellipsis. The terminal table must let the user choose from the full item id/source, severity, summary, and closure evidence without opening another file.

Immediately after the terminal command returns and before opening the scope-selection control, emit a user-visible assistant message that reproduces the exact unabridged `resolution-scope.md` content followed immediately by `Full report: <action-items.md path>`. Do this even when a terminal tool has already returned the same text. A collapsed tool result, `Read resolution-scope.md` summary, status message, artifact link without the ledger, or an announcement that the ledger is rendering does not count as user-visible scope context. The scope-selection control must not appear until that full message has been sent.

After the unabridged terminal rendering, ask:

```text
Which findings should I remediate?
- all
- severity group: critical, high, medium, low, or comma-separated groups such as critical,high
- indexes: comma-separated indexes or ranges such as 1,3,5-7
```

If `remediation_scope` supplied, it is user selection: apply without re-asking; still write and print the complete `<run-directory>/resolution-scope.md` before edits. If omitted and selectable items exist, stop before edits and ask exactly which findings to resolve. Never infer `all`, silently select only code-editable items, or use default selection. If runtime cannot ask, fail `scope-selection-required` before edit. If none selectable, write and print `none-selectable`, skip implementation, continue gates/artifact.

Record in `<run-directory>/resolution-scope.md` and `CODE_REMEDIATE_METADATA.resolution_scope`:

- selection source: `explicit-input`, `user-prompt`, or `none-selectable`
- prompt presented
- user selection confirmed before editing
- selected indexes/severity groups
- omitted resolved-online count
- deferred/unselected indexes
- unselected critical/high findings

Validate before edit:

- `all` selects every selectable item
- severity group selects every selectable matching severity
- indexes select only selectable rows
- invalid index or attempt to select omitted/resolved item => fail before editing
- selectable items without explicit input or confirmed user prompt => fail before editing
- unselected critical/high recorded as deferred by user selection in `resolution-scope.md` and final output

Each `out-of-scope` item needs user justification/confirmation before removal from selectable list. Record every item in `## Out Of Scope Confirmation`: item id, source, rationale, evidence path, user confirmation. Without confirmation, retain selectable as `valid`/`needs-clarification`.

For `mode=pr`, add `## PR Relevance Summary` to `<run-directory>/action-items.md` and `<run-directory>/resolution-scope.md`: connected open items, connected selectable items, connected required follow-ups, connected `out-of-scope` items. Connected is `direct-diff`, `pr-intent`, `adjacent`, or `unknown`. `connected items marked out-of-scope` must be `0`. Required-follow-up rows remain final-output-visible so user can rule them into current PR.

### 06: Group Selected Findings And Assign Specialist Owners

Before edit write `<run-directory>/resolution-workplan.md` sections:

- `## Selected Finding Groups`: one row/work cluster.
- `## Specialist Assignments`: owner, verifier, context-pack path, expected output, mode/cluster.
- `## Execution Order`: dependency-aware cluster order.
- `## Ungrouped Items`: intentionally parent-owned selected items and rationale.

Group only when it reduces duplicated context or preserves one root cause. Valid keys:

- shared affected files/modules/tests/docs/CI workflows
- same closure type: code, tests, docs, CI, security, typing, performance, review-gate, merge/conflict
- same root cause/expected fix
- same verification command/closure evidence
- same merge/conflict collision risk

Never split coherent fix across specialists; never make one pass per tiny parent-safe finding; never group unrelated findings for shared severity.

Each selected item is in exactly one group or `## Ungrouped Items`. Every group row:

- cluster id
- selected indexes
- severity range
- grouping rationale
- primary owner: `parent|sw-engineer|qa-specialist|doc-scribe|cicd-steward|linting-expert|security-auditor|data-steward|scientist|squeezer|oss-shepherd`
- verifier: `parent|qa-specialist|security-auditor|linting-expert|cicd-steward|challenger|solution-architect|none`
- context pack path
- expected closure evidence
- dependencies or `none`
- execution status: `planned|in-progress|fixed|verified|deferred|unresolved`

Owner assignment rules:

- implementation/refactor/API: `sw-engineer` primary, `qa-specialist` verifier; public API/migration shape adds `solution-architect` to verifier/context (verifier-only, never primary).
- test gap/regression proof: `qa-specialist` primary, `parent` verifier.
- docs/changelog/examples/docstrings: `doc-scribe` primary, `parent` or `qa-specialist` verifier for executable docs.
- CI/workflow/release gate: `cicd-steward` primary, `parent` verifier; permission/secret work adds `security-auditor`.
- SemVer/compatibility classification, deprecation-cycle correctness, or release-readiness/blocker impact: `oss-shepherd` primary, `parent` verifier; changelog/migration prose stays `doc-scribe`, release automation stays `cicd-steward`.
- lint/type/pre-commit/suppression: `linting-expert` primary, `parent` or `qa-specialist` verifier when runtime could change.
- security/dependency/permission/data exposure: `security-auditor` primary, `challenger` verifier for high/critical/non-obvious closure.
- data/ML/research/performance: `data-steward`, `scientist`, or `squeezer` primary; `qa-specialist` verifies tensor/data boundaries.
- review-gate/follow-up: primary role matching missing evidence, `parent` verifier; unresolved when evidence needs unavailable CI, maintainer review, user-deferred external step.
- merge/conflict collision: `sw-engineer` primary; `challenger` verifies critical/high/non-obvious; cite `<run-directory>/merge-prestage.md`.

For each non-parent cluster write narrow `<run-directory>/specialists/<cluster-id>-context.md`: selected cluster only, relevant files/hunks/logs, closure question, stop rule, expected evidence. Omit unrelated findings, full PR discussion, full review report by default.

Record `CODE_REMEDIATE_METADATA.resolution_workplan`: `groups_total`, `parent_owned_groups`, `specialist_owned_groups`, `verifier_groups`, `unassigned_selected_items`, `workplan_path`.

### 07: Apply Fixes In Selected Scope

Fix selected scope in priority: `critical` -> `high` -> `medium` -> `low`.

In `mode=pr`, complete target-merge conflict resolution and its authorized merge commit before selected report/online-review findings. Then fix one selected valid group at a time; `<run-directory>/resolution-workplan.md` is execution ledger. Never edit unselected findings or selected item outside assigned group unless update workplan first with reason/affected closure evidence. After each group, record changed files/evidence in `<run-directory>/closure-log.md`.

### 08: Challenge Closure Before Full Gates

For every selected fixed finding answer:

- Does original failure still reproduce?
- Could it pass review but remain functionally wrong?
- Which regression check protects it now?
- What risk remains?

Missing closure evidence keeps item unresolved.

Write `<run-directory>/closure-log.md` `Closure Evidence` before marking any item fixed.

Apply `../../shared/specialist-orchestration.md` when selected findings cross specialist domain. `<run-directory>/resolution-workplan.md` is source of truth for closure ownership; write `<run-directory>/specialist-closure-plan.md` only for post-fix verification beyond workplan owner/verifier. Context packs stay group-local: selected group, changed files, closure evidence, exact verification question; omit unrelated review items/PR discussion.

Specialist closure triggers:

- `qa-specialist`: bug fix, test gap, regression proof, or behavior `already-applied` claim.
- `security-auditor`: auth, credentials, deserialization, dependency/supply-chain, permissions, data exposure.
- `cicd-steward`: GitHub Actions, release automation, flaky CI, gate-environment failures.
- `linting-expert`: ruff, mypy, pre-commit, type/lint config, suppression changes.
- `doc-scribe`: public docs, changelog, examples, migration text, public docstrings.
- `data-steward`, `scientist`, or `squeezer`: data/ML/research/performance findings.
- `challenger`: critical/high, conflict resolution, or closure based on non-obvious assumption.

If triggered specialist unavailable, write labeled in-main substitute in `<run-directory>/specialists`; lower confidence when independence mattered. Never mark selected high/critical resolved only from parent claim when closure evidence depends on triggered specialist domain.

### 09: Run Shared Quality Gates

Inspect `python PLUGIN_ROOT/shared/run_gates.py --help`; run every project-relevant closure gate with explicit command/skip reason.

### 10: Write Unresolved Findings

Write unresolved findings to `<run-directory>/unresolved.txt`.

When selected items remain unresolved, distinguish fixed work from still-needed process/environment/CI/external-review action. Include:

- `Unresolved Work Summary`: selected total/resolved/unresolved; local actionable unresolved; process/gate unresolved; environment blocked; external-owner blocked; whether all local code/doc findings closed.
- `Why Selected Items Remain Unresolved`: one row/unresolved selected item or reason group: selected indexes, severity, closure class, status, reason, attempted evidence, next owner/action.
- `Next Action`: smallest concrete action closing each unresolved reason group.

Use closure classes: `local-code-or-doc`, `process-gate`, `independent-review`, `environment-blocked`, `external-ci`, `user-deferred`, `already-closed`, `other`. With `remediation_scope=all`, never say "resolved all" while selected item unresolved. Say "all local actionable findings are closed" only when local code/doc closed; separately list remaining selected gate/process obligations.

### 11: Write And Validate Result Artifact

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write `CODE_REMEDIATE_METADATA`, validate `code-remediate`, promote only validated candidate.

`CODE_REMEDIATE_METADATA.mode` is normalized mode. `CODE_REMEDIATE_METADATA.confidence_recovery` includes `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, `remaining_limits`. `CODE_REMEDIATE_METADATA.confidence_gap_closures` has one closure per non-empty `confidence_gaps`, with `status=closed|unresolved|deferred` plus evidence/rationale. `CODE_REMEDIATE_METADATA.resolution_scope` summarizes requested `remediation_scope`, `selection_source`, prompt presented, `selection_confirmed_by_user` pre-edit, selected indexes/severity groups, deferred indexes, omitted resolved-online count. `CODE_REMEDIATE_METADATA.resolution_workplan` summarizes `groups_total`, `parent_owned_groups`, `specialist_owned_groups`, `verifier_groups`, `unassigned_selected_items`, `workplan_path`. `CODE_REMEDIATE_METADATA.review_report_intake` summarizes `requested_report`, `report_items_total`, `review_gate_items_total`, `review_gate_items_selectable`, `report_items_marked_out_of_scope`. `CODE_REMEDIATE_METADATA.final_resolution_table` summarizes ingested entries, final rows, omitted entries, selectable/non-selectable rows, required columns, triage/resolution status counts. `CODE_REMEDIATE_METADATA.out_of_scope_confirmation` summarizes `count`, `all_confirmed_by_user`, every out-of-scope item id/source/rationale/evidence path/confirmation. `CODE_REMEDIATE_METADATA.pr_relevance` summarizes `evaluated`, `connected_open_items_total`, `connected_selectable_items_total`, `connected_required_followup_total`, `connected_items_marked_out_of_scope`. `CODE_REMEDIATE_METADATA.unresolved_summary` summarizes selected totals, unresolved closure-class counts, `all_local_actionable_items_closed`, `unresolved_reason_groups` with reason/count/owner/next action/evidence path. `CODE_REMEDIATE_METADATA.merge_resolution` summarizes the merge artifact path, conflict decision, status, and authorization. For `mode=pr`, include selected PR target, `<run-directory>/pr/pr-routing.json`, `<run-directory>/pr/target-branch.json`, `<run-directory>/pr/local-checkout.json`, `<run-directory>/pr/merge-resolution.json`, `<run-directory>/merge-prestage.md`.

### 12: Commit Attribution When Explicitly Requested

Leave accepted remediation changes unstaged by default. If the user explicitly requests a local commit after gates pass, load `../../shared/commit-response-template.md` and use its exact message shape. Every proposed or created remediation commit must end with:

```text
Co-authored-by: Codex <codex@openai.com>
```

Do not commit for a remediation summary alone or without the user's explicit authorization.
Creating a new remediation commit never authorizes rewriting an existing commit. Amend, rebase, reset, squash,
fixup, and equivalent history edits require an explicit request for that exact operation.

## Fail-fast Rules

01. Missing findings source => fail. 01a. `+review`, `+report`, or `report` shorthand without matching target code-review report => fail: "run `$code-review <target>` first or provide a report path".
02. Shared gate script missing => fail.
03. Selected critical unresolved => fail. Unselected critical/high allowed only when user selection explicitly records deferred.
04. Finding marked fixed without closure evidence => fail.
05. Gate fails because of resolution patch => fail unless explicitly unresolved.
06. PR mode without fresh online review or explicit stale-coverage caveat => fail. 06a. PR code edits without `pr/local-checkout.json` proving local checkout matches PR head => fail.
07. Online thread/comment fixed without valid triage status => fail.
08. Duplicate/stale/out-of-scope/already-fixed review thread/comment edited, not recorded => fail.
09. Result artifact validator failure => fail.
10. Result artifact missing => fail.
11. `<run-directory>/action-items.md` lacks complete review item resolution table => fail.
12. PR mode uses `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for code inspection/edits => fail.
13. `<run-directory>/resolution-scope.md` lacks `Resolution Scope Selection` before edits => fail.
14. Edit finding not selected in `resolution-scope.md` => fail.
15. Selectable list includes fetched online PR resolved comment/thread => fail.
16. PR mode lacks `<run-directory>/pr/target-branch.json`, `<run-directory>/pr/merge-tree.txt`, or `<run-directory>/merge-prestage.md` before review/report finding edits => fail.
17. PR merge conflicts resolved from markers without recorded clean PR/target context => fail.
18. Apply report/online-review findings before PR merge/conflict prestage complete => fail.
19. PR mode runs `git`/`gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
20. Review report `checks_failed`, `follow_up`, required next work, confidence gaps, residual risks omitted from `action-items.md` => fail.
21. Report-origin obligation marked `out-of-scope` before user selection without cited unrelatedness evidence => fail.
22. Selected review gate/follow-up marked resolved without matching closure evidence => fail.
23. Selectable findings and omitted `remediation_scope`, but no recorded user prompt/confirmed selection before edit => fail.
24. Any `out-of-scope` item lacks specific rationale and explicit user confirmation => fail.
25. PR item connected to PR intent, changed diff, adjacent verification, or unknown relation marked `out-of-scope` => fail.
26. Connected PR item omitted from selectable scope/required follow-up without closure evidence => fail.
27. Selected items but missing `<run-directory>/resolution-workplan.md` before edits => fail.
28. Selected item absent from both `Selected Finding Groups` and `Ungrouped Items` => fail.
29. Specialist-owned group lacks context-pack path or owner/verifier assignment => fail.
30. Selected unresolved items but `<run-directory>/unresolved.txt` lacks `Unresolved Work Summary`, `Why Selected Items Remain Unresolved`, or `Next Action` => fail.
31. `remediation_scope=all` with selected unresolved, but final output says/implies all selected work resolved => fail.
32. Unresolved selected item lacks closure class, attempted evidence, next owner, or next action => fail.
33. Selected local code/doc unresolved without blocker evidence and status fail/timeout => fail.
34. Final table row count differs from total ingested entries => fail.
35. Final table omits ingested entry or `omitted_entries_total` is not `0` => fail.
36. Final table status counts do not cover every row => fail.
37. Final table lacks `input item`, `item name`, `item type`, `triage status`, `resolution`, `owner/status`, `resolved how`, or `evidence` => fail.
38. Final chat lacks compact resolution summary, unresolved/deferred items, confidence/material limits, or artifact path => fail.
39. A pre-edit scope interaction substitutes a compact `Selectable items:` list for the unabridged terminal `resolution-scope.md` context => fail: `scope-context-not-rendered`.
40. The unabridged scope context is not immediately followed by a `Full report` link/path to `<run-directory>/action-items.md` => fail: `scope-report-link-missing`.
41. A scope-selection control opens without an immediately preceding user-visible assistant message containing the unabridged scope context and `Full report` path; collapsed tool output does not count => fail: `scope-context-not-visible`.
42. An explicitly requested remediation commit omits `Co-authored-by: Codex <codex@openai.com>` or the shared commit-response template => fail: `codex-coauthor-trailer-missing`.
43. Existing history would be rewritten without an explicit request for that exact operation => fail: `history-rewrite-not-explicitly-authorized`.
44. Target conflicts are present/likely but `merge-resolution.json` is absent or not `completed` before report/online-review work => fail: `target-merge-not-completed`.
45. Target merge starts or commits without explicit authorization for that local merge commit => fail: `target-merge-authorization-required`.
46. Report/online-review finding work starts while unmerged paths or an in-progress merge remain => fail: `merge-conflicts-unresolved-before-review-remediation`.

## Quality Gates

Required checks:

- `review`: complete action-item resolution table/row counts; review report failed-gate/follow-up intake; PR/diff relevance; indexed scope selection with prompt/confirmation; grouped workplan/specialist assignment; user-confirmed out-of-scope rationale; PR online-review triage; target refresh; intent-first merge/conflict resolution; merge authorization/completion evidence; relevant local checkout evidence; closure log; unresolved list with closure classes/next owner/attempted evidence/next action; `git diff --check`.
- `tests`: smallest checks proving fixed-finding closure.
- `artifact`: shared validator confirms closure artifacts, gate logs, result JSON shape.

Conditional checks:

- `lint`/`format`/`types`: run configured checks for changed code/config.
- `calibration`: run the owning calibration when findings affect skills, role/agent routing, or gate policy; Codex Rig source uses `runtime/calibration/run.py --layout plugin`.

## Calibration Hooks

Update calibration when resolution policy/output shape changes:

- benchmark patterns: `code-remediate`
- behavioral cases: ambiguous findings, false closure, unresolved critical/high handling, missing user-selected resolution scope, missing resolution workplan for selected items, selected item omitted from all workplan groups, specialist-owned group missing context pack, unconfirmed out-of-scope triage, connected PR item marked out-of-scope, missing connected follow-up, code-review-to-remediation gate symmetry, unresolved selected-item closure summary, complete final resolution table, gate failure disclosure, artifact validator bypass, PR online review triage, PR target-branch refresh, PR intent-first merge/conflict completion, PR local checkout before edits

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Apply shared confidence band policy from `../../shared/quality-gates.md` for score, recovery, confidence-gap closure output.

Keep complete, unabridged resolution ledger in `<run-directory>/action-items.md`: every ingested item, validated columns/counts/status vocabulary/resolved evidence/scope selection/workplan/PR relevance/unresolved classes/confidence recovery above.

The pre-edit scope context is deliberately unabridged: print the full `<run-directory>/resolution-scope.md` to the terminal and emit the same content plus the `Full report` path in a user-visible assistant message before the selection control, as required in the Terminal Scope Context Contract. After scope confirmation, final terminal/chat output is compact. Start `Remediation Summary`: requested scope; ingested/selected/implemented/unresolved/deferred totals; whether all selected local actionable items closed; gate status; confidence/material limits; artifact path. List only unresolved/user-deferred items with next owner/action; never duplicate closed artifact rows. Say "resolved all" only if `selected_items_unresolved=0`. For `mode=pr`, add compact merge-prestage line with evidence path/remaining collision risk. Artifact validator—not chat repetition—proves full-ledger completeness.

Minimum artifact payload template: `result-template.json`.
