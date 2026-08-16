---
name: release
description: "Assess SemVer release readiness with gates/artifacts; never tag, publish, upload, or force-push."
---

# Release

SemVer-aware release readiness/communication. Prepares release evidence/docs; never tag, publish, upload, or force-push.

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

Run `python PLUGIN_ROOT/shared/create_run.py --skill release` once. Retain its single printed path as
`<run-directory>` and substitute that literal path into every later artifact path and helper argument. Never store or
reuse the path through a shell variable; shell variables do not persist across tool calls.

### 02: Determine mode, range, and target version

- `notes`: draft release notes from git range.
- `prepare`: audit plus notes/changelog/migration-artifact checks.
- `audit`: readiness verdict only.
- `demo`: optional release-demo planning artifact; never required for non-feature releases.

Unknown mode/ambiguous range => fail before release docs.

### 03: Collect release evidence

Use the supplied `range`; when absent, run `git describe --tags --abbrev=0` as argv and form `<printed-tag>..HEAD`.
Retain that literal release range in workflow state, run `git log --oneline <release-range>` as argv, and write stdout
to `<run-directory>/commits.txt`. Record range or log collection failure instead of treating empty output as success.

When current GitHub release metadata is required, use `python PLUGIN_ROOT/shared/github_read.py --out <run-directory>/github-release.json -- gh release view <tag-or-url> --json <fields>`. It prefers `gh`; a public `api.github.com` fallback is allowed only for public REST resources and cannot supply private release evidence. Never invoke `gh` directly. Apply the networked CLI approval contract in `../../shared/native-skill-contract.md`: run this complete owning command with external network approval from its first attempt. Before requesting it, state: `Action and purpose`: collect current release metadata for the selected tag or URL; `External capability`: read-only GitHub network access, with public HTTPS fallback only when eligible; `Credential behavior`: `gh` is an opaque local credential broker and no credential output is retained; `Filesystem and worktree effects`: write `github-release.json` to the release run directory without changing the worktree; `Retry policy and safe denial outcome`: do not repeat an equivalent request in this turn, and record current release metadata as unavailable evidence. In a Codex exec call set `sandbox_permissions="require_escalated"` with a narrow read-only GitHub justification, and never enable persistent workspace network access or approve only the nested `gh` executable. Denial aborts the active tool call and may end the assistant turn. Do not issue an equivalent approval request in the current turn. Do not switch to a broader command. Ask the user to send a new message to resume.

Inspect `python PLUGIN_ROOT/shared/collect_diff.py --help`; collect `commit` scope for the retained release range into
`<run-directory>/range`. Collection failure is evidence gap, not empty release.

Write `<run-directory>/change-table.md`: change type, user impact, breaking status, docs need, verification evidence.

### 04: Verify release readiness

Required checks:

- SemVer classification matches observed API/user-visible changes.
- Breaking changes have migration guidance.
- Deprecations follow project policy and released before removal.
- CHANGELOG/release notes mention user-visible changes.
- Do not advertise reverted changes as live features.
- Call out security/dependency changes with source evidence.

**Structural context (optional)**: for a Python package release, also probe codemap-py once for undocumented public
surface and externally-uncalled modules: `python PLUGIN_ROOT/shared/codemap_adapter.py context --category audit --out
<run-directory>/codemap-context.json`. Per `../../shared/codemap-contract.md`, absence/incompatibility is non-fatal —
continue with the checks above, using the persisted evidence as an additional readiness signal.

Write `<run-directory>/release-readiness.md` with:

- `SemVer`
- `Migration`
- `Checks`
- `Blockers`

For `prepare`/`audit`, apply `../../shared/specialist-orchestration.md` for public API changes, CI/release automation, security/dependency changes, docs/migration work, or broad verification risk. Write `<run-directory>/specialist-release-plan.md` with narrow context packs for:

- `oss-shepherd`: SemVer, deprecation policy, maintainer readiness.
- `cicd-steward`: release workflow, publishing, CI status, artifact gates.
- `doc-scribe`: changelog, migration guide, README/examples.
- `qa-specialist`: verification matrix and test evidence.
- `security-auditor`: only when the user expressly requests Sol or selects that role for security/dependency-sensitive changes; it returns a bounded read-only evidence artifact to the Terra parent/session for release acceptance.
- `challenger`: release-blocker downgrade or no-blocker conclusion.

Single-agent for `notes` on narrow low-risk range unless SemVer/migration impact ambiguous.

### 05: Run required checks from `../../shared/quality-gates.md`

Inspect `python PLUGIN_ROOT/shared/run_gates.py --help`; run every project-required release gate with explicit commands/skip reasons.

### 06: Classify blockers and warnings

- `critical`: publish would ship known security/data-loss/API breakage without mitigation.
- `high`: SemVer, changelog, migration, or required-check gap blocks readiness.
- `medium`: incomplete docs, missing contributor notes, uncertain compatibility.
- `low`: wording, formatting, or optional artifact polish.

### 07: Decide gate result, write `result.candidate.json`, validate artifacts, and publish `.reports/codex/release/<timestamp>/result.json`

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write `RELEASE_METADATA`, validate as `release`, promote only validated candidate.

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

Release readiness requires all five shared gates + shared artifact validator unless project has no executable package; record any skipped executable check as gap.

## Calibration Hooks

On SemVer, deprecation, changelog, or release-blocker policy change, update calibration:

- behavioral cases: missing migration, wrong SemVer, unreleased API removal, artifact validator bypass, networked CLI owning-command approval
- benchmark patterns: `release`

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
