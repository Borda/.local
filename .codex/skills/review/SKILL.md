---
name: review
description: Tiered codex-native multi-axis review loop. Use for local diff review with mechanical scope gates, explicit specialist fan-out or labeled substitutes, measurable quality gates, and a JSON artifact.
---

# Review

Run a tiered review loop with strict output gates.

## Input Schema

```json
{
  "scope": "working-tree|path|commit|pr",
  "target": "optional path, commit ref, PR number, PR URL, or current branch PR",
  "done_when": "blocking issues are identified with gate decision"
}
```

## Scope And Routing

- `working-tree`: review unstaged/staged local changes.
- `path`: review a specific file or directory diff.
- `commit`: review a git diff revision spec, such as `COMMIT^!`, `BASE..HEAD`, or `BASE...HEAD`.
- `pr`: review an open pull request using `gh pr view` and `gh pr diff`; `target` may be a PR number, URL, or omitted for the current branch.

The skill is read-only except for `.reports/codex/review/<timestamp>/` artifacts. If the user asks to fix findings, switch to `resolve` after the review artifact exists.

## Workflow (Exact Commands)

01. Create run directory.

    ```bash
    TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
    OUT_DIR=".reports/codex/review/$TS"
    mkdir -p "$OUT_DIR"
    ```

02. T0 mechanical scope gate: resolve scope, collect diff, and classify review risk before any model-level judgment.

    For local scopes:

    ```bash
    .codex/skills/_shared/collect-diff.sh \
        --scope "$SCOPE" \
        --target "${TARGET:-}" \
        --out "$OUT_DIR"
    ```

    For PR scope:

    ```bash
    .codex/skills/_shared/collect-pr.sh \
        --target "${TARGET:-}" \
        --out "$OUT_DIR"
    ```

    Classify the diff and write the decision to `"$OUT_DIR/scope.txt"`:

    - `TRIVIAL`: no public API/config/security/ML behavior touched, fewer than 3 files, fewer than 50 changed lines.
    - `LOCAL`: one subsystem or 3-7 files, behavior is understandable from local context.
    - `BROAD`: 8+ files, cross-subsystem changes, dependency/config changes, or unclear ownership.
    - `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

    If `scope=pr`, include `pr.json`, `comments.json`, `reviews.json`, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json` in the review evidence. Treat unresolved online review threads and comments as candidate findings until triaged as valid, duplicate, stale, out-of-scope, or already fixed.

    If `files.txt` and `untracked.txt` are both empty and there is no explicit target, fail before running gates. If `scope=pr` and `pr-error.txt` exists, fail with the captured reason.

03. T1 primary diff review. Read the changed files end-to-end and identify findings before considering any fix or gate outcome.

    Review across these axes in order:

    - API and behavior regressions.
    - Test coverage and edge-case gaps.
    - Error handling and logging.
    - Security, data, ML, CI/CD, or release risks signaled by T0.
    - Documentation or migration gaps caused by behavior/API changes.

04. T2 multi-axis specialist fan-out. For `LOCAL`, `BROAD`, and `HIGH_RISK` diffs, get specialist review before final severity classification.

    Create `"$OUT_DIR/specialists"` and write one markdown file per spawned or substituted pass. Also write `"$OUT_DIR/specialist-manifest.json"` with a `passes` list containing every required and conditional role. Each entry must include role, axis, trigger rationale, mode (`spawned`, `substituted`, or `not_triggered`), output path for spawned/substituted passes, confidence, and blocking finding count. Do not continue to severity classification until required specialist outputs and the manifest exist.

    Required specialist passes:

    - `qa-specialist`: test adequacy, edge cases, regression coverage, tensor/data boundaries when relevant.
    - `challenger`: adversarial stress test for non-trivial findings, assumptions, migration/API risks, and "no findings" conclusions on `BROAD` or `HIGH_RISK` diffs.

    Conditional specialist passes:

    - `solution-architect`: public API, architecture, migration, or cross-subsystem coupling.
    - `security-auditor`: auth, credentials, deserialization, external data, dependency/supply-chain, or CI permissions.
    - `data-steward`: datasets, splits, augmentation, leakage, DataLoader reproducibility.
    - `cicd-steward`: GitHub Actions, release automation, publishing, flaky CI.
    - `linting-expert`: ruff, mypy, pre-commit configuration, suppression hygiene, or type/lint rollout.
    - `doc-scribe`: public docs, changelog, migration text, examples, or public docstrings.
    - `oss-shepherd`: SemVer, deprecation policy, release readiness, contributor-facing process.
    - `squeezer`: performance, memory, throughput, profiling claims, training/inference bottlenecks.
    - `scientist`: research-paper methods, benchmark claims, experiment design, metric validity.
    - `web-explorer`: current external docs, changelogs, migration guides, or volatile ecosystem behavior.

    Use native subagents when runtime policy permits, especially when the user explicitly asks for multi-agent or specialist review. Do not claim specialist fan-out occurred unless separate specialist output exists. If runtime policy, model support, or tool availability prevents spawning, perform a clearly labeled in-main substitute pass for each required role, write it to that role's specialist file, and mark `fanout_substituted=true` in the review notes and result metadata. Substituted passes lower confidence; they do not satisfy independence for critical findings.

    `BROAD` and `HIGH_RISK` reviews require real independent `qa-specialist` and `challenger` outputs to return `status=pass`, especially for "no blocking findings" conclusions. If required independent outputs are unavailable, return `status=fail` or `status=timeout`, set `independence_satisfied=false`, and add `needs-independent-review` to follow-up. `LOCAL` reviews may pass with substituted required passes only when the substitutions are explicit, all triggered conditional axes are covered, and confidence is reduced.

05. Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly.

06. Write `$OUT_DIR/review-notes.md`.

    Required sections:

    - `Scope`
    - `Risk Tier`
    - `Files Inspected`
    - `Specialist Passes`
    - `Specialist Manifest`
    - `Findings`
    - `No-Finding Residual Risks`
    - `Confidence Gaps`
    - `Online Review Triage` for `scope=pr`

07. Run shared quality gates.

    ```bash
    .codex/skills/_shared/run-gates.sh --out "$OUT_DIR"
    ```

08. Classify findings using `../_shared/severity-map.md`.

09. If no findings are present, state that explicitly and note residual risks from T0 classification and any substituted specialist passes.

10. Write and validate the mandatory result artifact.

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
    --follow-up "$FOLLOW_UP" \
    --metadata "$REVIEW_METADATA"
python3 .codex/skills/review/validate_artifacts.py \
    --out "$OUT_DIR" \
    --result "$OUT_DIR/result.candidate.json"
mv "$OUT_DIR/result.candidate.json" "$OUT_DIR/result.json"
```

`REVIEW_METADATA.specialist_passes` must mirror every entry from `specialist-manifest.json`. `REVIEW_METADATA.scope` must match the normalized input scope.

## Fail-fast Rules

01. Empty `files.txt` and `untracked.txt` with no explicit target => fail.
02. Shared gate or diff collection script missing => fail.
03. Result artifact missing => fail.
04. Review that skips changed-file inspection => fail.
05. Blocking finding without local evidence or pattern check => fail.
06. Missing T0 scope classification => fail.
07. `LOCAL`, `BROAD`, or `HIGH_RISK` review without `qa-specialist` and `challenger` output files or explicitly labeled in-main substitute files => fail.
08. Triggered conditional axis without a specialist output file, substitute file, or explicit non-trigger rationale => fail.
09. Missing `specialist-manifest.json` for `LOCAL`, `BROAD`, or `HIGH_RISK` reviews => fail.
10. `BROAD` or `HIGH_RISK` review that returns `status=pass` with substituted required specialists => fail.
11. Result artifact validator failure => fail.
12. Missing `review-notes.md` sections => fail.
13. PR scope without `pr.json`, `diff.patch`, `comments.json`, `reviews.json`, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json` => fail.
14. PR scope that ignores unresolved online reviews without triage => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, changed-file inspection, specialist manifest, specialist notes, online review triage for PR scope, severity map, and `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run or inspect available results when needed to validate a finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, or output shape changes:

- benchmark patterns: `review`
- behavioral cases: false blocker, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload shape:

```json
{
  "status": "pass|fail|timeout",
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
  "artifact_path": ".reports/codex/review/<timestamp>/result.json",
  "metadata": {
    "scope": "working-tree|path|commit|pr",
    "risk_tier": "TRIVIAL|LOCAL|BROAD|HIGH_RISK",
    "fanout_substituted": false,
    "independence_satisfied": true,
    "specialist_manifest": ".reports/codex/review/<timestamp>/specialist-manifest.json",
    "specialist_passes": [
      {
        "role": "qa-specialist",
        "axis": "tests",
        "trigger": "required for LOCAL/BROAD/HIGH_RISK reviews",
        "mode": "spawned|substituted",
        "output_path": ".reports/codex/review/<timestamp>/specialists/qa-specialist.md",
        "confidence": 0.0,
        "blocking_findings": 0
      },
      {
        "role": "solution-architect",
        "axis": "architecture",
        "trigger": "not triggered: no public API, migration, or cross-subsystem coupling",
        "mode": "not_triggered",
        "output_path": null,
        "confidence": 0.0,
        "blocking_findings": 0
      }
    ]
  },
  "follow_up": [
    "needs-independent-review when independence_satisfied=false"
  ]
}
```
