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

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/release/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Determine mode, range, and target version

- `notes`: draft release notes from a git range.
- `prepare`: run audit plus notes/changelog/migration artifact checks.
- `audit`: readiness verdict only.
- `demo`: optional release-demo planning artifact; never required for non-feature releases.

Unknown mode or ambiguous range => fail before writing release docs.

### 03: Collect release evidence

```bash
RELEASE_RANGE="${RANGE:-$(git describe --tags --abbrev=0 2>/dev/null)..HEAD}"
git log --oneline "$RELEASE_RANGE" >"$OUT_DIR/commits.txt" 2>/dev/null || true
```

Inspect `collect-diff.sh --help`, then collect `commit` scope for `RELEASE_RANGE` into `$OUT_DIR/range`; a collection failure is an evidence gap, not an empty release.

Write `$OUT_DIR/change-table.md` with change type, user impact, breaking status, docs need, and verification evidence.

### 04: Verify release readiness

Required checks:

- SemVer classification matches observed API/user-visible changes.
- Breaking changes have migration guidance.
- Deprecations use project policy and were released before removal.
- CHANGELOG or release notes mention user-visible changes.
- Reverted changes are not advertised as live features.
- Security/dependency changes are called out with source evidence.

Write `$OUT_DIR/release-readiness.md` with:

- `SemVer`
- `Migration`
- `Checks`
- `Blockers`

For `prepare` and `audit` modes, apply `../_shared/specialist-orchestration.md` when the release includes public API changes, CI/release automation, security/dependency changes, docs/migration work, or broad verification risk. Write `"$OUT_DIR/specialist-release-plan.md"` with narrow context packs for:

- `oss-shepherd`: SemVer, deprecation policy, maintainer readiness.
- `cicd-steward`: release workflow, publishing, CI status, artifact gates.
- `doc-scribe`: changelog, migration guide, README/examples.
- `qa-specialist`: verification matrix and test evidence.
- `security-auditor`: security/dependency-sensitive changes.
- `challenger`: release-blocker downgrade or no-blocker conclusion.

Stay single-agent for `notes` mode on a narrow, low-risk range unless SemVer or migration impact is ambiguous.

### 05: Run required checks from `../_shared/quality-gates.md`

Inspect `run-gates.sh --help`, then run every project-required release gate with explicit commands or skip reasons.

### 06: Classify blockers and warnings

- `critical`: publish would ship known security/data-loss/API breakage without mitigation.
- `high`: SemVer, changelog, migration, or required-check gap blocks readiness.
- `medium`: incomplete docs, missing contributor notes, uncertain compatibility.
- `low`: wording, formatting, or optional artifact polish.

### 07: Decide gate result, write `result.candidate.json`, validate artifacts, and publish `.reports/codex/release/<timestamp>/result.json`

Follow `../_shared/helper-cli-contract.md` and authoritative help. Write with `RELEASE_METADATA`, validate as skill `release`, and promote only the validated candidate.

## Fail-Fast Rules

1. Missing or invalid target range for notes/prepare/demo => fail.
2. Invalid SemVer target for prepare/audit => fail.
3. Breaking change without migration decision => fail.
4. Release blocker presented as warning => fail.
5. Publish/tag/upload action attempted by this skill => fail.
6. Missing `release-readiness.md` SemVer, Migration, Checks, or Blockers evidence => fail.
7. Result artifact validator failure => fail.
8. Result artifact missing => fail.

## Quality Gates

All five shared gates and the shared artifact validator are required for release readiness unless the project has no executable package; any skipped executable check must be recorded as a gap.

## Calibration Hooks

Update calibration when SemVer, deprecation, changelog, or release-blocker policy changes:

- behavioral cases: missing migration, wrong SemVer, unreleased API removal, artifact validator bypass
- benchmark patterns: `release`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
