---
name: review
description: Tiered codex-native review loop. Use for local diff review with mechanical scope gates, explicit specialist fan-out, measurable quality gates, and a JSON artifact.
---

# Review

Run a tiered review loop with strict output gates.

## Input Schema

```json
{
  "scope": "working-tree|path|commit",
  "target": "optional path or commit ref",
  "done_when": "blocking issues are identified with gate decision"
}
```

## Workflow (Exact Commands)

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/review/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. T0 mechanical scope gate: resolve scope, collect diff, and classify review risk before any model-level judgment.

   ```bash
   git status --short >"$OUT_DIR/status.txt"
   git diff --name-only >"$OUT_DIR/files.txt"
   git diff --stat >"$OUT_DIR/diffstat.txt"
   git diff --numstat >"$OUT_DIR/numstat.txt"
   ```

   Classify the diff and write the decision to `"$OUT_DIR/scope.txt"`:

   - `TRIVIAL`: no public API/config/security/ML behavior touched, fewer than 3 files, fewer than 50 changed lines.
   - `LOCAL`: one subsystem or 3-7 files, behavior is understandable from local context.
   - `BROAD`: 8+ files, cross-subsystem changes, dependency/config changes, or unclear ownership.
   - `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

   If there are no diff files and no explicit target, fail before running gates.

3. T1 primary diff review. Read the changed files end-to-end and identify findings before considering any fix or gate outcome.

   Review in this order:

   - API and behavior regressions.
   - Test coverage and edge-case gaps.
   - Error handling and logging.
   - Security, data, ML, CI/CD, or release risks signaled by T0.
   - Documentation or migration gaps caused by behavior/API changes.

4. T2 specialist fan-out. For `LOCAL`, `BROAD`, and `HIGH_RISK` diffs, get specialist review before final severity classification.

   Required specialist passes:

   - `qa-specialist`: test adequacy, edge cases, regression coverage, tensor/data boundaries when relevant.
   - `challenger`: adversarial stress test for non-trivial findings, assumptions, migration/API risks, and "no findings" conclusions on `BROAD` or `HIGH_RISK` diffs.

   Conditional specialist passes:

   - `solution-architect`: public API, architecture, migration, or cross-subsystem coupling.
   - `security-auditor`: auth, credentials, deserialization, external data, dependency/supply-chain, or CI permissions.
   - `data-steward`: datasets, splits, augmentation, leakage, DataLoader reproducibility.
   - `cicd-steward`: GitHub Actions, release automation, publishing, flaky CI.

   Do not claim specialist fan-out occurred unless separate specialist output exists. If runtime policy or tool availability prevents spawning, perform a clearly labeled in-main substitute pass for each required role and mark `fanout_substituted=true` in the review notes. Substituted passes lower confidence; they do not satisfy independence for critical findings.

5. Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly.

6. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

7. Classify findings using `../_shared/severity-map.md`.

8. If no findings are present, state that explicitly and note residual risks from T0 classification and any substituted specialist passes.

9. Write mandatory result artifact.

   ```bash
   .codex/skills/_shared/write-result.sh \
       --out "$OUT_DIR/result.json" \
       --status "$STATUS" \
       --checks-run "lint,format,types,tests,review" \
       --checks-failed "$CHECKS_FAILED" \
       --critical "$CRITICAL" \
       --high "$HIGH" \
       --medium "$MEDIUM" \
       --low "$LOW" \
       --confidence "$CONFIDENCE" \
       --artifact-path "$OUT_DIR/result.json"
   ```

## Fail-fast Rules

1. No diff files and no explicit target => fail.
2. Shared gate script missing => fail.
3. Result artifact missing => fail.
4. Review that skips changed-file inspection => fail.
5. Blocking finding without local evidence or pattern check => fail.
6. Missing T0 scope classification => fail.
7. `LOCAL`, `BROAD`, or `HIGH_RISK` review without `qa-specialist` and `challenger` output or explicitly labeled in-main substitutes => fail.

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
  "artifact_path": ".reports/codex/review/<timestamp>/result.json"
}
```
