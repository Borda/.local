---
name: resolve
description: Minimal codex-native resolve loop. Use to apply review findings, rerun checks, and publish unresolved gaps with measurable gates.
---

# Resolve

Run a linear resolve loop for findings closure.

## Input Schema

```json
{
  "findings_source": "required path or explicit list",
  "mode": "report|pr",
  "pr_target": "optional PR number, PR URL, or current branch PR when mode=pr",
  "target_scope": "required path/module",
  "done_when": "critical/high findings are either fixed or explicitly unresolved"
}
```

## Workflow (Exact Commands)

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/resolve/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Validate and copy findings source.

   ```bash
   cp "$FINDINGS_SOURCE" "$OUT_DIR/findings-input.txt"
   ```

   For `mode=pr`, also collect fresh online PR evidence:

   ```bash
   .codex/skills/_shared/collect-pr.sh \
       --target "${PR_TARGET:-}" \
       --out "$OUT_DIR/pr"
   ```

   Use the review report plus `$OUT_DIR/pr/comments.json`, `$OUT_DIR/pr/reviews.json`, `$OUT_DIR/pr/review-threads.json`, and `$OUT_DIR/pr/unresolved-review-threads.json` as the findings intake. If online PR collection fails, record the failure and either continue with the supplied report only when the user accepts stale online-review coverage, or fail.

3. Normalize findings before editing.

   Write `$OUT_DIR/action-items.md` with one item per report finding and unresolved online review thread/comment:

   - finding id or source location
   - severity
   - exact affected files
   - expected closure evidence
   - triage status: `valid|duplicate|stale|out-of-scope|already-fixed|needs-clarification`
   - owner/status: `todo|fixed|unresolved`
   - unresolved rationale, when applicable

   If a finding or online review thread/comment is ambiguous, inspect the referenced code and either sharpen it into an action item or mark it `needs-clarification` before editing. Do not fix duplicate, stale, out-of-scope, or already-fixed review comments; record the triage evidence instead.

4. Apply fixes in priority order: `critical` -> `high` -> `medium`.

   Fix one valid finding cluster at a time. After each cluster, record the changed files and evidence in `$OUT_DIR/closure-log.md`.

5. Challenge the closure before running full gates.

   For each fixed finding, answer:

   - Does the original failure still reproduce?
   - Could the finding pass review while remaining functionally wrong?
   - Which regression check now protects it?
   - What risk remains?

   Missing closure evidence keeps the item unresolved.

   Write `$OUT_DIR/closure-log.md` with a `Closure Evidence` section before any item is marked fixed.

6. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh --out "$OUT_DIR"
   ```

7. Write unresolved findings to `$OUT_DIR/unresolved.txt`.

8. Write and validate the mandatory result artifact.

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
       --artifact-path "$OUT_DIR/result.json"
   python3 .codex/skills/_shared/validate-artifacts.py \
       --skill resolve \
       --out "$OUT_DIR" \
       --result "$OUT_DIR/result.candidate.json"
   mv "$OUT_DIR/result.candidate.json" "$OUT_DIR/result.json"
   ```

## Fail-fast Rules

01. Missing findings source => fail.
02. Shared gate script missing => fail.
03. Critical unresolved findings => fail.
04. Finding marked fixed without closure evidence => fail.
05. Gate failure caused by the resolution patch => fail unless explicitly listed as unresolved.
06. PR mode without fresh online review collection or explicit stale-coverage caveat => fail.
07. Online review thread/comment fixed without valid triage status => fail.
08. Duplicate/stale/out-of-scope/already-fixed review thread/comment edited instead of recorded => fail.
09. Result artifact validator failure => fail.
10. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: action-item ledger, PR online review triage when relevant, closure log, unresolved list, and `git diff --check`.
- `tests`: the smallest checks that prove closure for fixed findings.
- `artifact`: shared validator confirms closure artifacts, gate logs, and result JSON shape.

Conditional checks:

- `lint`/`format`/`types`: run project-configured checks for changed code/config.
- `calibration`: run when findings affect `.codex/skills`, `.codex/agents`, routing, or gate policy.

## Calibration Hooks

Update calibration when resolution policy or output shape changes:

- benchmark patterns: `resolve`
- behavioral cases: ambiguous findings, false closure, unresolved critical/high handling, gate failure disclosure, artifact validator bypass, PR online review triage

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

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
  "artifact_path": ".reports/codex/resolve/<timestamp>/result.json"
}
```
