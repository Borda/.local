---
name: resolve
description: Minimal codex-native resolve loop. Use to apply review findings, rerun checks, and publish unresolved gaps with measurable gates, including in-session skill invocations like "$resolve #123 +review" that resolve a PR using the latest matching review artifact.
---

# Resolve

Run a linear resolve loop for findings closure.

## Input Schema

```json
{
  "findings_source": "optional path, explicit list, or +review/+report/report/latest to auto-select the newest matching review report",
  "mode": "optional report|pr|auto; infer pr for bare number, #number, or PR URL",
  "target": "optional shorthand target number, issue/PR URL, path, or current branch",
  "pr_target": "optional PR number, PR URL, or current branch PR when mode=pr",
  "resolve_scope": "optional all|critical|high|medium|low|comma-separated severities|comma-separated selection indexes; ask before editing when omitted",
  "target_scope": "required path/module",
  "done_when": "selected findings are fixed/resolved and unselected critical/high findings are explicitly deferred"
}
```

## Workflow (Exact Commands)

### 01: Create Run Directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/resolve/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Normalize Shorthand Input And Copy Findings Source

Shorthand rules:

- Canonical in-session invocation: `$resolve #123 +review` => `mode=pr`, `PR_TARGET=123`, and `FINDINGS_SOURCE=latest-matching-review-report`.
- Compatibility alias: `$resolve #123 +report` => `mode=pr`, `PR_TARGET=123`, and `FINDINGS_SOURCE=latest-matching-review-report`; `$resolve #123 +report compatibility alias` means the same report lookup behavior.
- Natural-language aliases: `resolve 123 report`, `resolve #123 report`, and `resolve PR 123 report` => `mode=pr`, `PR_TARGET=123`, and `FINDINGS_SOURCE=latest-matching-review-report`.
- `resolve <github-pr-url> report` => `mode=pr`, `PR_TARGET=<github-pr-url>`, and `FINDINGS_SOURCE=latest-matching-review-report`.
- If `+review`, `+report`, `report`, `latest`, `latest-report`, or `review-report` is supplied instead of a path, find the newest `.reports/codex/review/*/result.json` whose sibling `pr.json` has the same PR number or URL as `PR_TARGET`.
- If no matching review report exists, fail with a direct instruction to run `review <target>` first or provide an explicit report path.
- If multiple matching reports exist, use the newest timestamped directory and record the selected path in `$OUT_DIR/findings-input.txt`.

For `latest-matching-review-report`, inspect `find-review-report.py --help`, resolve `PR_TARGET` against `.reports/codex/review`, and assign the printed path to `FINDINGS_SOURCE`.

```bash
cp "$FINDINGS_SOURCE" "$OUT_DIR/findings-input.txt"
```

For `mode=pr`, inspect `collect-pr.sh --help`, then collect `PR_TARGET` into `$OUT_DIR/pr` with checkout enabled so online evidence, target/head refresh, and the local checkout are current.

The helper records `gh pr checkout` without `--force` in `$OUT_DIR/pr/local-checkout.json`.

Use the review report plus `$OUT_DIR/pr/comments.json`, `$OUT_DIR/pr/reviews.json`, `$OUT_DIR/pr/review-threads.json`, and `$OUT_DIR/pr/unresolved-review-threads.json` as the findings intake. A review report is a closure contract, not only a list of code findings: normalize report findings, failed `checks_failed`, `follow_up`, `review_decision.required_next_work`, confidence gaps, confidence recovery remaining limits, and no-finding residual risks into report-origin action items before editing. Use the local checkout recorded in `$OUT_DIR/pr/local-checkout.json` as the authoritative source for code triage and edits. `$OUT_DIR/pr/target-branch.json` must prove the base/target branch was fetched before conflict or review-item resolution, and `$OUT_DIR/pr/pr-head-fetch.json` records same-repo PR branch refresh or a cross-repository skip rationale. The checkout artifacts must include `force_policy`; if checkout fails or does not match the PR head, record `forced-checkout-not-attempted` and stop before any forced retry. If online PR collection, target refresh, or local checkout fails, record the failure and either continue with the supplied report only when the user accepts stale online-review coverage and no code edits are required, or fail. Do not inspect or edit PR code from `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots; this is a raw-file snapshot rejection rule.

### 03: Pre-Stage PR Merge/Conflict Context

For `mode=pr`, this phase is mandatory and must happen before `action-items.md`, `resolution-scope.md`, or any code changes for report/PR-review findings. The goal is to understand the clean PR implementation and the latest target-branch implementation before any merge conflict markers make the worktree noisy.

Required local context commands:

```bash
BASE_REMOTE_REF="$(
    sed -n 's/^[[:space:]]*"remote_ref"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$OUT_DIR/pr/target-branch.json" |
head -n 1
)"
MERGE_BASE="$(git merge-base HEAD "$BASE_REMOTE_REF")"
printf '%s\n' "$MERGE_BASE" >"$OUT_DIR/pr/merge-base.txt"
git diff --stat "$MERGE_BASE"..HEAD >"$OUT_DIR/pr/pr-intent.diffstat" 2>/dev/null || true
git diff --name-only "$MERGE_BASE"..HEAD >"$OUT_DIR/pr/pr-intent-files.txt" 2>/dev/null || true
git diff --stat "$MERGE_BASE".."$BASE_REMOTE_REF" >"$OUT_DIR/pr/target-since-merge-base.diffstat" 2>/dev/null || true
git merge-tree "$MERGE_BASE" HEAD "$BASE_REMOTE_REF" >"$OUT_DIR/pr/merge-tree.txt" 2>/dev/null || true
```

Write `$OUT_DIR/merge-prestage.md` with these sections:

- `## PR And Target Refresh`: PR number, PR head, target branch, fetched target hash, local checkout hash, and evidence paths.
- `## Clean PR Implementation Context`: what the PR is trying to change, changed files, important invariants, and tests/docs implied by the clean PR branch.
- `## Target Branch Context`: relevant target-branch implementation details from the fetched target branch, especially for files likely to collide.
- `## Conflict Risk`: mergeability status, `merge-tree` signal, files changed on both sides, and whether conflicts are present, likely, or absent.
- `## Resolution Strategy`: for each conflict or likely collision, how to reconcile the PR intent with the target-branch implementation before applying review/report findings.

If conflicts are present or likely, resolve collisions as a preliminary PR-integration task before applying selected review/report findings. Use the clean PR branch, the fetched target branch, `git show "$BASE_REMOTE_REF:path"`, and nearby tests as primary context. Use conflict markers only after the PR and target intent have been recorded in `merge-prestage.md`. Keep collision resolution limited to preserving the PR intent on top of the current target branch; do not fold review-comment fixes into conflict resolution unless the same line cannot be made coherent otherwise, and record that coupling in `$OUT_DIR/closure-log.md`.

If the checkout starts in a dirty, conflicted, or partially merged state, fail or ask for cleanup before editing. Do not reason directly from an existing conflicted worktree as the primary source of truth.

### 04: Normalize Findings Before Editing

Write `$OUT_DIR/action-items.md` with a `## Review Item Resolution Table` section first, before any prose. Include one row per ingested entry: every report finding, every normalized report-origin review obligation, each fetched online PR review comment, PR review, review thread, and unresolved review thread. If the user supplied or asked to use a report, include report items even when the same item is also present in fresh PR evidence. The table is the source for selectable findings and must include resolved evidence for any item marked `resolved`. Do not collapse the ledger to only changed, selected, unresolved, or high-impact rows.

For `mode=pr`, every report and PR-review item must be checked against PR intent and the changed diff before triage:

- `direct-diff`: the item references a changed file, changed hunk, or behavior directly modified by the PR
- `pr-intent`: the item connects to the PR purpose, acceptance criteria, review decision, or requested change even if it is outside a touched hunk
- `adjacent`: the item touches nearby code, tests, docs, config, or verification needed to safely merge the PR
- `unknown`: relation cannot be determined from current evidence
- `unrelated`: no connection to PR intent, changed files, adjacent verification, or merge readiness after inspecting local PR context

Write this relation in the action table and in each expanded item. Items with relation `direct-diff`, `pr-intent`, `adjacent`, or `unknown` are not `out-of-scope`. They must remain `valid` or `needs-clarification` and be selectable unless already closed by `resolved`, `already-fixed`, or `already-applied` evidence. If such an item cannot be closed in the current PR, record it as `unresolved`, `deferred`, or required follow-up; do not downgrade it to `out-of-scope`. The user can then select it, defer it, or explicitly rule it into this PR.

For a review report, also include report-origin review obligations even when they are not code edits:

- failed checks from `checks_failed`, such as missing independence, full gates, lint, type, test, or confidence gates
- `follow_up` entries, especially `needs-independent-review`
- `review_decision.required_next_work` and merge/readiness blockers
- confidence gaps, confidence recovery remaining limits, and no-finding residual risks that block acceptance

Report-origin review obligations are in scope by default when the user asks for `+review`, `+report`, `report`, or a review report path. Do not mark them `out-of-scope` merely because closure requires an independent reviewer, an installed tool, CI/full-gate execution, or an environment that may not be available locally. Mark them `valid` or `needs-clarification`, keep them selectable, and leave them `unresolved` or user-deferred until closure evidence exists. `out-of-scope` is reserved for items unrelated to the requested report/PR/target after citing evidence; it is not a valid way to silence failed review gates or report follow-up.

After the resolution table, write a `## Review Report Intake` section with counts for total report-origin items, report-origin review-gate/follow-up items, selectable review-gate/follow-up items, and report-origin items marked `out-of-scope`. The last count must be `0` unless the item is proven unrelated to the requested report/PR/target.

Required table columns:

- selection index: numeric for selectable items, `-` for non-selectable items
- input item: stable input row id, report id, PR comment id, review id, thread id, or source location
- item name: short human-readable name for the finding, review obligation, gate, comment, or thread
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
- resolved how: short answer explaining if/how it was resolved, or why it remains unresolved/deferred/not applicable
- closure evidence or unresolved rationale

After the table, write a `## Final Resolution Summary` section with:

- what was requested
- ingested entries total
- resolved or already-closed entries total
- implemented entries total
- unresolved entries total
- deferred/not-selected entries total
- not-applicable/stale/duplicate/rejected entries total
- one sentence stating whether all selected local actionable items are closed

Then write a `## Final Resolution Table Completeness` section with:

- ingested entries total
- final table rows total
- omitted entries total, which must be `0`
- selectable and non-selectable row totals
- triage status counts
- resolution status counts

`RESOLVE_METADATA.final_resolution_table` must contain the same counts. If the final table omits any ingested entry, fails to account for every row in the triage or resolution status counts, or uses a row without triage status and resolution status, fail before final output. `RESOLVE_METADATA.final_resolution_table.required_columns` must list `input item`, `item name`, `item type`, `triage status`, `resolution`, `owner/status`, `resolved how`, and `evidence`.

Closure evidence for report-origin review obligations must match the obligation type:

- independent review: path to the independent specialist/maintainer output and updated review metadata showing independence satisfied, or unresolved rationale if unavailable
- full gates: path to a clean full-gate or CI result, or unresolved rationale if the workspace/environment prevents it
- type/lint/test environment: command log from the installed environment, or unresolved rationale naming the missing executable/dependency
- confidence gap: additional evidence that closes the gap, or an explicit unresolved/deferred record

After the table, keep one expanded item per report finding and unresolved online review thread/comment:

- finding id or source location
- severity
- source and fetched evidence path
- PR/diff relation and evidence for that relation
- summary
- exact affected files
- expected closure evidence
- triage status: `valid|resolved|duplicate|stale|out-of-scope|already-fixed|already-applied|needs-clarification`
- resolution: `implemented|resolved|rejected|stale|not-applicable|duplicate|already-fixed|already-applied|needs-clarification|unresolved`
- owner/status: `todo|fixed|resolved|deferred|unresolved`
- unresolved rationale, when applicable

If a finding or online review thread/comment is ambiguous, inspect the referenced code in the local working tree or checked-out PR branch and either sharpen it into an action item or mark it `needs-clarification` before editing. If a fetched PR comment or review thread is marked resolved in current PR evidence, list it in the table with triage status and resolution `resolved`, cite the fetched evidence path, and state that the PR evidence marks it resolved. Do not create follow-up implementation work for it. If the requested change is already present in current local code, mark triage status and resolution `already-applied`, cite the code evidence, and do not create follow-up implementation work for it. Do not fix duplicate, stale, out-of-scope, already-fixed, already-applied, or resolved review comments; record the triage evidence instead.

### 05: Ask For Resolution Scope Before Editing

Build `$OUT_DIR/resolution-scope.md` with a `## Resolution Scope Selection` section before any code changes. The selectable list must include every non-closed finding that could require work and must omit all fetched online PR comments or review threads currently marked resolved. Keep resolved online PR items in `action-items.md` only as non-selectable audit rows with selection index `-`; this is the omit resolved online PR rule.

Selection list table columns:

- index
- severity: `critical|high|medium|low`
- item id or source location
- source
- summary
- expected closure evidence

Selectable items:

- include triage status `valid`
- include `needs-clarification` only when the next step is clarification or code inspection, not implementation
- include report-origin failed checks, follow-ups, required next work, confidence gaps, and residual risks unless already closed by cited evidence
- include PR/review items related to PR intent, changed diff, adjacent verification, or unknown relation unless already closed by cited evidence
- exclude triage or resolution `resolved`, `duplicate`, `stale`, `out-of-scope`, `already-fixed`, and `already-applied`
- exclude fetched online PR review comments/threads marked resolved in current PR evidence

Present the selectable list to the user and ask:

```text
Which findings should I resolve?
- all
- severity group: critical, high, medium, low, or comma-separated groups such as critical,high
- indexes: comma-separated indexes or ranges such as 1,3,5-7
```

If `resolve_scope` was supplied up front, treat that input as the user's selection, apply it without asking again, and still write `$OUT_DIR/resolution-scope.md`. If `resolve_scope` was omitted and selectable items exist, stop before editing and ask the user exactly which findings to resolve. Do not infer `all`, do not silently select only code-editable items, and do not proceed from a default selection. If the runtime cannot ask the user interactively, fail with `scope-selection-required` before editing. If no selectable items remain, write `none-selectable`, skip implementation, and proceed to gates/artifact output.

Record in `$OUT_DIR/resolution-scope.md` and `RESOLVE_METADATA.resolution_scope`:

- selection source: `explicit-input`, `user-prompt`, or `none-selectable`
- whether a prompt was presented
- whether the user's selection was confirmed before editing
- selected indexes and selected severity groups
- omitted resolved-online count
- deferred/unselected indexes
- any unselected critical/high findings

Validate selection before editing:

- `all` selects every selectable item
- severity groups select every selectable item with matching severity
- indexes select only rows in the selectable list
- invalid indexes or attempts to select omitted/resolved items => fail before editing
- selectable items with no explicit input or confirmed user prompt => fail before editing
- unselected critical/high findings must be recorded as deferred by user selection in `resolution-scope.md` and final output

Any item marked `out-of-scope` must be justified and confirmed by the user before it is removed from the selectable list. Record each such item in a `## Out Of Scope Confirmation` section with item id, source, rationale, evidence path, and the user's confirmation. If the user does not confirm, keep the item selectable as `valid` or `needs-clarification`.

For `mode=pr`, also write a `## PR Relevance Summary` section in `$OUT_DIR/action-items.md` and `$OUT_DIR/resolution-scope.md` with counts for connected open items, connected selectable items, connected required follow-ups, and connected items marked `out-of-scope`. Connected means relation `direct-diff`, `pr-intent`, `adjacent`, or `unknown`. `connected items marked out-of-scope` must be `0`. Required follow-up rows must remain visible in the final output so the user can rule them into the current PR if they choose.

### 06: Group Selected Findings And Assign Specialist Owners

Before editing, write `$OUT_DIR/resolution-workplan.md` with these sections:

- `## Selected Finding Groups`: one row per work cluster.
- `## Specialist Assignments`: primary owner, verifier, context pack path, expected output, and mode for each cluster.
- `## Execution Order`: dependency-aware order for clusters.
- `## Ungrouped Items`: selected items intentionally left parent-owned, with rationale.

Group selected items only when grouping reduces duplicate context or keeps one root cause together. Valid grouping keys:

- shared affected files, modules, tests, docs, or CI workflows
- same closure type: code, tests, docs, CI, security, typing, performance, review-gate, or merge/conflict
- same root cause or same expected fix
- same verification command or closure evidence
- same merge/conflict collision risk

Do not split one coherent fix across multiple specialists. Do not create one specialist pass per tiny finding when the parent can safely close it. Do not group unrelated findings merely because they share severity.

Each selected item must appear in exactly one group or in `## Ungrouped Items`. Each group row must include:

- cluster id
- selected indexes
- severity range
- grouping rationale
- primary owner: `parent|sw-engineer|qa-specialist|doc-scribe|cicd-steward|linting-expert|security-auditor|data-steward|scientist|squeezer|solution-architect|oss-shepherd`
- verifier: `parent|qa-specialist|security-auditor|linting-expert|cicd-steward|challenger|none`
- context pack path
- expected closure evidence
- dependencies or `none`
- execution status: `planned|in-progress|fixed|verified|deferred|unresolved`

Owner assignment rules:

- implementation/refactor/API fix: primary `sw-engineer`, verifier `qa-specialist`; add `solution-architect` in the verifier/context when public API or migration shape matters.
- test gap or regression proof: primary `qa-specialist`, verifier `parent`.
- docs/changelog/examples/docstrings: primary `doc-scribe`, verifier `parent` or `qa-specialist` for executable docs.
- CI/workflow/release gate: primary `cicd-steward`, verifier `parent`; add `security-auditor` when permissions or secrets are involved.
- lint/type/pre-commit/suppression: primary `linting-expert`, verifier `parent` or `qa-specialist` when runtime behavior could change.
- security/dependency/permission/data exposure: primary `security-auditor`, verifier `challenger` for high/critical or non-obvious closure.
- data/ML/research/performance: primary `data-steward`, `scientist`, or `squeezer` as appropriate, verifier `qa-specialist` for tensor/data boundary checks.
- review-gate/follow-up obligation: primary role matching the missing evidence, verifier `parent`; keep unresolved when the evidence requires unavailable CI, maintainer review, or a user-deferred external step.
- merge/conflict collision: primary `sw-engineer`, verifier `challenger` when critical/high or non-obvious; cite `$OUT_DIR/merge-prestage.md`.

Write one narrow context pack per non-parent cluster under `$OUT_DIR/specialists/<cluster-id>-context.md`. A context pack must include only the selected items in that cluster, relevant files/hunks/logs, closure question, stop rule, and expected evidence. Do not include unrelated selected items, full PR discussion, or full review reports by default.

Record the workplan in `RESOLVE_METADATA.resolution_workplan` with `groups_total`, `parent_owned_groups`, `specialist_owned_groups`, `verifier_groups`, `unassigned_selected_items`, and `workplan_path`.

### 07: Apply Fixes In Selected Scope

Apply fixes in priority order within the selected scope: `critical` -> `high` -> `medium` -> `low`.

In `mode=pr`, complete any merge/conflict collision work identified in `$OUT_DIR/merge-prestage.md` before applying selected report or online-review findings. Then fix one selected valid finding group at a time using `$OUT_DIR/resolution-workplan.md` as the execution ledger. Do not edit unselected findings. Do not edit a selected item outside its assigned group unless the workplan is updated first with the reason and affected closure evidence. After each group, record the changed files and evidence in `$OUT_DIR/closure-log.md`.

### 08: Challenge Closure Before Full Gates

For each selected fixed finding, answer:

- Does the original failure still reproduce?
- Could the finding pass review while remaining functionally wrong?
- Which regression check now protects it?
- What risk remains?

Missing closure evidence keeps the item unresolved.

Write `$OUT_DIR/closure-log.md` with a `Closure Evidence` section before any item is marked fixed.

Apply `../_shared/specialist-orchestration.md` when selected findings cross a specialist domain. `$OUT_DIR/resolution-workplan.md` is the source of truth for specialist closure ownership; write `"$OUT_DIR/specialist-closure-plan.md"` only when an additional post-fix verification pass is needed beyond the workplan's owner/verifier assignments. Keep context packs group-local: include the selected item group, changed files, closure evidence, and the exact verification question; omit unrelated review items and PR discussion.

Specialist closure triggers:

- `qa-specialist`: any bug fix, test gap, regression proof, or "already-applied" claim for behavior.
- `security-auditor`: auth, credentials, deserialization, dependency/supply-chain, permissions, or data exposure.
- `cicd-steward`: GitHub Actions, release automation, flaky CI, or gate-environment failures.
- `linting-expert`: ruff, mypy, pre-commit, type/lint config, or suppression changes.
- `doc-scribe`: public docs, changelog, examples, migration text, or public docstrings.
- `data-steward`, `scientist`, or `squeezer`: data/ML/research/performance findings.
- `challenger`: critical/high findings, conflict resolution, or closure that depends on a non-obvious assumption.

If a triggered specialist is unavailable, write a labeled in-main substitute file under `"$OUT_DIR/specialists"` and lower confidence when independence was material. Do not mark a selected high/critical item resolved solely from the parent agent's claim when the closure evidence depends on a triggered specialist domain.

### 09: Run Shared Quality Gates

Inspect `run-gates.sh --help`, then run every project-relevant closure gate with explicit commands or skip reasons.

### 10: Write Unresolved Findings

Write unresolved findings to `$OUT_DIR/unresolved.txt`.

When selected items remain unresolved, the file must distinguish what was actually fixed from what still needs a process, environment, CI, or external review action. Include these sections:

- `Unresolved Work Summary`: selected total, selected resolved, selected unresolved, local actionable unresolved, process/gate unresolved, environment blocked, external-owner blocked, and whether all local code/doc findings are closed.
- `Why Selected Items Remain Unresolved`: one row per unresolved selected item or reason group with selected indexes, severity, closure class, status, why it remains unresolved, attempted evidence, next owner, and next action.
- `Next Action`: the smallest concrete action that would close each unresolved reason group.

Use closure classes consistently: `local-code-or-doc`, `process-gate`, `independent-review`, `environment-blocked`, `external-ci`, `user-deferred`, `already-closed`, or `other`. If `resolve_scope=all`, never summarize the run as "resolved all" while any selected item remains unresolved. Say "all local actionable findings are closed" only when local code/doc findings are closed, then list the remaining selected gate/process obligations separately.

### 11: Write And Validate Result Artifact

Follow `../_shared/helper-cli-contract.md` and authoritative help. Write with `RESOLVE_METADATA`, validate as skill `resolve`, and promote only the validated candidate.

`RESOLVE_METADATA.mode` must be the normalized mode. `RESOLVE_METADATA.confidence_recovery` must include `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, and `remaining_limits`. `RESOLVE_METADATA.confidence_gap_closures` must include one closure record per non-empty `confidence_gaps` entry, with `status=closed|unresolved|deferred` and matching evidence or rationale. `RESOLVE_METADATA.resolution_scope` must summarize the requested scope, `selection_source`, whether a prompt was presented, `selection_confirmed_by_user` before editing, selected indexes, selected severity groups, deferred indexes, and omitted resolved-online count. `RESOLVE_METADATA.resolution_workplan` must summarize `groups_total`, `parent_owned_groups`, `specialist_owned_groups`, `verifier_groups`, `unassigned_selected_items`, and `workplan_path`. `RESOLVE_METADATA.review_report_intake` must summarize report-origin intake with `requested_report`, `report_items_total`, `review_gate_items_total`, `review_gate_items_selectable`, and `report_items_marked_out_of_scope`. `RESOLVE_METADATA.final_resolution_table` must summarize ingested entries, final table rows, omitted entries, selectable/non-selectable row totals, required columns, triage status counts, and resolution status counts. `RESOLVE_METADATA.out_of_scope_confirmation` must summarize `count`, `all_confirmed_by_user`, and one item per out-of-scope row with item id, source, rationale, evidence path, and confirmation status. `RESOLVE_METADATA.pr_relevance` must summarize `evaluated`, `connected_open_items_total`, `connected_selectable_items_total`, `connected_required_followup_total`, and `connected_items_marked_out_of_scope`. `RESOLVE_METADATA.unresolved_summary` must summarize selected item totals, unresolved closure-class counts, `all_local_actionable_items_closed`, and `unresolved_reason_groups` with reason, count, owner, next action, and evidence path. For `mode=pr`, include the selected PR target, `$OUT_DIR/pr/pr-routing.json`, `$OUT_DIR/pr/target-branch.json`, `$OUT_DIR/pr/local-checkout.json`, and `$OUT_DIR/merge-prestage.md`.

## Fail-fast Rules

01. Missing findings source => fail. 01a. `+review`, `+report`, or `report` shorthand without a matching review report for the target => fail with "run `$review <target>` first or provide a report path".
02. Shared gate script missing => fail.
03. Selected critical findings left unresolved => fail. Unselected critical/high findings are allowed only when explicitly recorded as deferred by user selection.
04. Finding marked fixed without closure evidence => fail.
05. Gate failure caused by the resolution patch => fail unless explicitly listed as unresolved.
06. PR mode without fresh online review collection or explicit stale-coverage caveat => fail. 06a. PR mode with code edits but without `pr/local-checkout.json` proving the local checkout matches the PR head => fail.
07. Online review thread/comment fixed without valid triage status => fail.
08. Duplicate/stale/out-of-scope/already-fixed review thread/comment edited instead of recorded => fail.
09. Result artifact validator failure => fail.
10. Result artifact missing => fail.
11. `$OUT_DIR/action-items.md` missing the complete review item resolution table => fail.
12. PR mode using `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for code inspection or edits => fail.
13. Missing `$OUT_DIR/resolution-scope.md` with `Resolution Scope Selection` before edits => fail.
14. Editing a finding not selected in `resolution-scope.md` => fail.
15. Selectable scope list includes a fetched online PR comment/thread marked resolved => fail.
16. PR mode missing `$OUT_DIR/pr/target-branch.json`, `$OUT_DIR/pr/merge-tree.txt`, or `$OUT_DIR/merge-prestage.md` before review/report finding edits => fail.
17. PR mode resolving merge conflicts from conflict markers without recorded clean PR and target-branch context => fail.
18. Applying report or online-review findings before PR merge/conflict prestage is complete => fail.
19. PR mode running `git` or `gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
20. Review report `checks_failed`, `follow_up`, required next work, confidence gaps, or residual risks omitted from `action-items.md` => fail.
21. Report-origin review obligation marked `out-of-scope` before user scope selection without cited evidence that it is unrelated to the requested report/PR/target => fail.
22. Selected review gate or follow-up item marked resolved without matching closure evidence => fail.
23. Selectable findings exist and `resolve_scope` was omitted, but no user prompt and confirmed user selection were recorded before editing => fail.
24. Any item marked `out-of-scope` without specific rationale and explicit user confirmation => fail.
25. PR item connected to PR intent, changed diff, adjacent verification, or unknown relation marked `out-of-scope` => fail.
26. Connected PR item omitted from selectable scope or required follow-up without closure evidence => fail.
27. Selected items exist but `$OUT_DIR/resolution-workplan.md` is missing before edits => fail.
28. Selected item missing from both `Selected Finding Groups` and `Ungrouped Items` => fail.
29. Specialist-owned group without a context pack path and owner/verifier assignment => fail.
30. Selected unresolved items exist but `$OUT_DIR/unresolved.txt` lacks `Unresolved Work Summary`, `Why Selected Items Remain Unresolved`, or `Next Action` => fail.
31. `resolve_scope=all` with unresolved selected items but final output says or implies all selected work is resolved => fail.
32. Any unresolved selected item missing closure class, attempted evidence, next owner, or next action => fail.
33. Selected local code/doc item remains unresolved without blocker evidence and status fail/timeout => fail.
34. Final resolution table row count does not match the total ingested entries => fail.
35. Final resolution table omits any ingested entry or records `omitted_entries_total` other than `0` => fail.
36. Final resolution table status counts do not account for every table row => fail.
37. Final resolution table missing `input item`, `item name`, `item type`, `triage status`, `resolution`, `owner/status`, `resolved how`, or `evidence` columns => fail.
38. Final chat missing the compact resolution summary, unresolved/deferred items, confidence with material limits, or artifact path => fail.

## Quality Gates

Required checks:

- `review`: action-item ledger with complete review item resolution table, table completeness counts, review report failed-gate/follow-up intake, PR/diff relevance classification, indexed resolution scope selection with prompt/confirmation evidence, resolution workplan with grouped selected items and specialist assignments, user-confirmed out-of-scope rationale, PR online review triage, target branch refresh, PR merge/conflict prestage, local checkout evidence when relevant, closure log, unresolved list with closure classes, next owners, attempted evidence, next actions, and `git diff --check`.
- `tests`: the smallest checks that prove closure for fixed findings.
- `artifact`: shared validator confirms closure artifacts, gate logs, and result JSON shape.

Conditional checks:

- `lint`/`format`/`types`: run project-configured checks for changed code/config.
- `calibration`: run when findings affect `.codex/skills`, `.codex/agents`, routing, or gate policy.

## Calibration Hooks

Update calibration when resolution policy or output shape changes:

- benchmark patterns: `resolve`
- behavioral cases: ambiguous findings, false closure, unresolved critical/high handling, missing user-selected resolution scope, missing resolution workplan for selected items, selected item omitted from all workplan groups, specialist-owned group missing context pack, unconfirmed out-of-scope triage, connected PR item marked out-of-scope, missing connected follow-up, review-to-resolve gate symmetry, unresolved selected-item closure summary, complete final resolution table, gate failure disclosure, artifact validator bypass, PR online review triage, PR target-branch refresh, PR merge/conflict prestage, PR local checkout before edits

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Apply the shared confidence band policy from `../_shared/quality-gates.md` for confidence score, confidence recovery, and confidence-gap closure output.

Keep the complete, unabridged resolution ledger in `$OUT_DIR/action-items.md`; it must cover every ingested item and retain the validated columns, counts, status vocabulary, closure evidence, scope selection, workplan, PR relevance, unresolved classes, and confidence recovery required above.

The final terminal/chat output is intentionally compact. Start with `Resolution Summary` and include requested scope, ingested/selected/implemented/unresolved/deferred totals, whether all selected local actionable items are closed, gate status, confidence with material limits, and the artifact path. List only unresolved or user-deferred items with next owner/action; do not duplicate rows already closed in the artifact. State "resolved all" only when `selected_items_unresolved=0`. For `mode=pr`, add one compact merge-prestage line with the evidence path and remaining collision risk. The artifact validator, not chat repetition, proves full-ledger completeness.

Minimum artifact payload template: `result-template.json`.
