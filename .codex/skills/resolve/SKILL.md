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

Discovery command for `latest-matching-review-report`:

```bash
FINDINGS_SOURCE="$(
    .codex/skills/_shared/find-review-report.py \
        --target "${PR_TARGET:-}" \
        --reports-dir ".reports/codex/review"
)"
```

```bash
cp "$FINDINGS_SOURCE" "$OUT_DIR/findings-input.txt"
```

For `mode=pr`, also collect fresh online PR evidence, refresh the PR target branch, refresh the PR branch where possible, and update the local PR checkout:

```bash
.codex/skills/_shared/collect-pr.sh \
    --target "${PR_TARGET:-}" \
    --out "$OUT_DIR/pr" \
    --checkout
```

The helper records `gh pr checkout` without `--force` in `$OUT_DIR/pr/local-checkout.json`.

Use the review report plus `$OUT_DIR/pr/comments.json`, `$OUT_DIR/pr/reviews.json`, `$OUT_DIR/pr/review-threads.json`, and `$OUT_DIR/pr/unresolved-review-threads.json` as the findings intake. Use the local checkout recorded in `$OUT_DIR/pr/local-checkout.json` as the authoritative source for code triage and edits. `$OUT_DIR/pr/target-branch.json` must prove the base/target branch was fetched before conflict or review-item resolution, and `$OUT_DIR/pr/pr-head-fetch.json` records same-repo PR branch refresh or a cross-repository skip rationale. The checkout artifacts must include `force_policy`; if checkout fails or does not match the PR head, record `forced-checkout-not-attempted` and stop before any forced retry. If online PR collection, target refresh, or local checkout fails, record the failure and either continue with the supplied report only when the user accepts stale online-review coverage and no code edits are required, or fail. Do not inspect or edit PR code from `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots; this is a raw-file snapshot rejection rule.

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

Write `$OUT_DIR/action-items.md` with a `## Review Item Resolution Table` section first, before any prose. Include one row per report finding and each fetched online PR review comment, PR review, review thread, and unresolved review thread. If the user supplied or asked to use a report, include report items even when the same item is also present in fresh PR evidence. The table is the source for selectable findings and must include resolved evidence for any item marked `resolved`.

Required table columns:

- selection index: numeric for selectable items, `-` for non-selectable items
- item id or source location
- source: `report|pr-comment|pr-review|pr-thread|unresolved-pr-thread`
- fetched evidence path, or `report-only`
- severity
- summary
- triage status: `valid|resolved|duplicate|stale|out-of-scope|already-fixed|already-applied|needs-clarification`
- resolution: `implemented|resolved|rejected|stale|not-applicable|duplicate|already-fixed|already-applied|needs-clarification|unresolved`
- closure evidence or unresolved rationale

After the table, keep one expanded item per report finding and unresolved online review thread/comment:

- finding id or source location
- severity
- source and fetched evidence path
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
- exclude triage or resolution `resolved`, `duplicate`, `stale`, `out-of-scope`, `already-fixed`, and `already-applied`
- exclude fetched online PR review comments/threads marked resolved in current PR evidence

Present the selectable list to the user and ask:

```text
Which findings should I resolve?
- all
- severity group: critical, high, medium, low, or comma-separated groups such as critical,high
- indexes: comma-separated indexes or ranges such as 1,3,5-7
```

If `resolve_scope` was supplied up front, apply it without asking, but still write `$OUT_DIR/resolution-scope.md`. Record the selected indexes, selected severity groups, omitted resolved-online count, deferred/unselected indexes, and any unselected critical/high findings. If no selectable items remain, write `none-selectable`, skip implementation, and proceed to gates/artifact output.

Validate selection before editing:

- `all` selects every selectable item
- severity groups select every selectable item with matching severity
- indexes select only rows in the selectable list
- invalid indexes or attempts to select omitted/resolved items => fail before editing
- unselected critical/high findings must be recorded as deferred by user selection in `resolution-scope.md` and final output

### 06: Apply Fixes In Selected Scope

Apply fixes in priority order within the selected scope: `critical` -> `high` -> `medium` -> `low`.

In `mode=pr`, complete any merge/conflict collision work identified in `$OUT_DIR/merge-prestage.md` before applying selected report or online-review findings. Then fix one selected valid finding cluster at a time. Do not edit unselected findings. After each cluster, record the changed files and evidence in `$OUT_DIR/closure-log.md`.

### 07: Challenge Closure Before Full Gates

For each selected fixed finding, answer:

- Does the original failure still reproduce?
- Could the finding pass review while remaining functionally wrong?
- Which regression check now protects it?
- What risk remains?

Missing closure evidence keeps the item unresolved.

Write `$OUT_DIR/closure-log.md` with a `Closure Evidence` section before any item is marked fixed.

### 08: Run Shared Quality Gates

```bash
.codex/skills/_shared/run-gates.sh --out "$OUT_DIR"
```

### 09: Write Unresolved Findings

Write unresolved findings to `$OUT_DIR/unresolved.txt`.

### 10: Write And Validate Result Artifact

```bash
.codex/skills/_shared/write-result.sh \
    --out "$OUT_DIR/result.candidate.json" \
    --status "$STATUS" \
    --checks-run "lint,format,types,tests,review" \
    --checks-failed "$CHECKS_FAILED" \
    --critical "$CRITICAL" \
    --high "$HIGH" \
    --medium "$MEDIUM" \
    --low "$LOW" \
    --confidence "$CONFIDENCE" \
    --artifact-path "$OUT_DIR/result.json" \
    --metadata "$RESOLVE_METADATA"
python3 .codex/skills/_shared/validate-artifacts.py \
    --skill resolve \
    --out "$OUT_DIR" \
    --result "$OUT_DIR/result.candidate.json"
mv "$OUT_DIR/result.candidate.json" "$OUT_DIR/result.json"
```

`RESOLVE_METADATA.mode` must be the normalized mode. `RESOLVE_METADATA.resolution_scope` must summarize the requested scope, selected indexes, deferred indexes, and omitted resolved-online count. For `mode=pr`, include the selected PR target, `$OUT_DIR/pr/pr-routing.json`, `$OUT_DIR/pr/target-branch.json`, `$OUT_DIR/pr/local-checkout.json`, and `$OUT_DIR/merge-prestage.md`.

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
11. Final output or `$OUT_DIR/action-items.md` missing the review item resolution table => fail.
12. PR mode using `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for code inspection or edits => fail.
13. Missing `$OUT_DIR/resolution-scope.md` with `Resolution Scope Selection` before edits => fail.
14. Editing a finding not selected in `resolution-scope.md` => fail.
15. Selectable scope list includes a fetched online PR comment/thread marked resolved => fail.
16. PR mode missing `$OUT_DIR/pr/target-branch.json`, `$OUT_DIR/pr/merge-tree.txt`, or `$OUT_DIR/merge-prestage.md` before review/report finding edits => fail.
17. PR mode resolving merge conflicts from conflict markers without recorded clean PR and target-branch context => fail.
18. Applying report or online-review findings before PR merge/conflict prestage is complete => fail.
19. PR mode running `git` or `gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.

## Quality Gates

Required checks:

- `review`: action-item ledger with review item resolution table, indexed resolution scope selection, PR online review triage, target branch refresh, PR merge/conflict prestage, local checkout evidence when relevant, closure log, unresolved list, and `git diff --check`.
- `tests`: the smallest checks that prove closure for fixed findings.
- `artifact`: shared validator confirms closure artifacts, gate logs, and result JSON shape.

Conditional checks:

- `lint`/`format`/`types`: run project-configured checks for changed code/config.
- `calibration`: run when findings affect `.codex/skills`, `.codex/agents`, routing, or gate policy.

## Calibration Hooks

Update calibration when resolution policy or output shape changes:

- benchmark patterns: `resolve`
- behavioral cases: ambiguous findings, false closure, unresolved critical/high handling, user-selected resolution scope, gate failure disclosure, artifact validator bypass, PR online review triage, PR target-branch refresh, PR merge/conflict prestage, PR local checkout before edits

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

The final terminal/chat output must start with a Markdown table under `Review Item Resolution Table` before narrative summary. The table must include every report item requested by the user and every fetched PR review item considered during `mode=pr`, with source, summary, triage status, resolution, and evidence. Use the same resolution vocabulary as `$OUT_DIR/action-items.md`: `implemented`, `resolved`, `rejected`, `stale`, `not-applicable`, `duplicate`, `already-fixed`, `already-applied`, `needs-clarification`, or `unresolved`. Do not use `resolved` without explaining how it was resolved in the evidence column. For PR comments or threads resolved in fetched online evidence, mark triage status and resolution `resolved`, cite the fetched evidence, and do not list any further action. For review items already applied in current local code, mark triage status and resolution `already-applied` and do not list any further action. After the table, include a `Resolution Scope Selection` summary with selected indexes, selected severities or `all`, omitted resolved-online count, and deferred critical/high items. For `mode=pr`, also include a compact `Merge Prestage Summary` that cites `$OUT_DIR/merge-prestage.md`, target branch refresh evidence, and any conflict/collision work completed before applying review/report findings.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "lint",
    "format",
    "types",
    "tests",
    "review"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "artifact_path": ".reports/codex/resolve/<timestamp>/result.json",
  "metadata": {
    "mode": "report|pr",
    "resolution_scope": {
      "requested": "all|critical|high|medium|low|indexes",
      "selected_indexes": [],
      "deferred_indexes": [],
      "omitted_resolved_online_count": 0
    }
  }
}
```
