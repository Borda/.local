---
name: review
description: Minimal codex-native review loop. Use for local diff review with measurable quality gates and a JSON artifact.
---

# Review

Run a linear review loop with strict output gates.

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

2. Resolve scope and collect diff.

   ```bash
   git status --short >"$OUT_DIR/status.txt"
   git diff --name-only >"$OUT_DIR/files.txt"
   ```

3. Read the changed files end-to-end and identify findings before considering any fix or gate outcome.

4. Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly.

5. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

6. Classify findings using `../_shared/severity-map.md`.

7. If no findings are present, state that explicitly and note any residual risks.

8. Write mandatory result artifact.

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
