---
name: release
description: Minimal codex-native release loop. Use for SemVer-aware release readiness with measurable gates and artifact output.
---

# Release

Run a SemVer-aware release readiness and communication loop. This skill prepares release evidence and documentation; it does not tag, publish, upload, or force-push.

## Input Schema

```json
{
  "mode": "notes|prepare|audit|demo",
  "range": "optional git range, tag pair, or target version",
  "target_version": "optional SemVer version",
  "done_when": "release blockers, warnings, and required artifacts are explicit"
}
```

## Workflow

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/release/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Determine mode, range, and target version.

   - `notes`: draft release notes from a git range.
   - `prepare`: run audit plus notes/changelog/migration artifact checks.
   - `audit`: readiness verdict only.
   - `demo`: optional release-demo planning artifact; never required for non-feature releases.

   Unknown mode or ambiguous range => fail before writing release docs.

3. Collect release evidence.

   ```bash
   git log --oneline "${RANGE:-$(git describe --tags --abbrev=0 2>/dev/null)..HEAD}" >"$OUT_DIR/commits.txt" 2>/dev/null || true
   git diff --stat "${RANGE:-$(git describe --tags --abbrev=0 2>/dev/null)..HEAD}" >"$OUT_DIR/diffstat.txt" 2>/dev/null || true
   ```

   Write `$OUT_DIR/change-table.md` with change type, user impact, breaking status, docs need, and verification evidence.

4. Verify release readiness.

   Required checks:

   - SemVer classification matches observed API/user-visible changes.
   - Breaking changes have migration guidance.
   - Deprecations use project policy and were released before removal.
   - CHANGELOG or release notes mention user-visible changes.
   - Reverted changes are not advertised as live features.
   - Security/dependency changes are called out with source evidence.

5. Run required checks from `../_shared/quality-gates.md`.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

6. Classify blockers and warnings.

   - `critical`: publish would ship known security/data-loss/API breakage without mitigation.
   - `high`: SemVer, changelog, migration, or required-check gap blocks readiness.
   - `medium`: incomplete docs, missing contributor notes, uncertain compatibility.
   - `low`: wording, formatting, or optional artifact polish.

7. Decide gate result and write `.reports/codex/release/<timestamp>/result.json`.

## Fail-Fast Rules

1. Missing or invalid target range for notes/prepare/demo => fail.
2. Invalid SemVer target for prepare/audit => fail.
3. Breaking change without migration decision => fail.
4. Release blocker presented as warning => fail.
5. Publish/tag/upload action attempted by this skill => fail.
6. Result artifact missing => fail.

## Quality Gates

All five shared gates are required for release readiness unless the project has no executable package; any skipped executable check must be recorded as a gap.

## Calibration Hooks

Update calibration when SemVer, deprecation, changelog, or release-blocker policy changes:

- behavioral cases: missing migration, wrong SemVer, unreleased API removal
- benchmark patterns: `release`

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
  "artifact_path": ".reports/codex/release/<timestamp>/result.json"
}
```
