---
name: review
description: Tiered codex-native multi-axis review loop. Use for local diff review or GitHub PR review, including in-session skill invocations like "$review #123" where a bare number means PR number, with mechanical scope gates, explicit specialist fan-out or labeled substitutes, measurable quality gates, and a JSON artifact.
---

# Review

Run a tiered review loop with strict output gates.

## Input Schema

```json
{
  "scope": "optional working-tree|path|commit|pr; infer pr for bare number, #number, or PR URL",
  "target": "optional path, commit ref, PR number, PR URL, or current branch PR",
  "done_when": "blocking issues are identified with gate decision"
}
```

## Scope And Routing

- `working-tree`: review unstaged/staged local changes.
- `path`: review a specific file or directory diff.
- `commit`: review a git diff revision spec, such as `COMMIT^!`, `BASE..HEAD`, or `BASE...HEAD`.
- `pr`: review an open pull request by collecting GitHub PR metadata/review evidence, fetching the target branch, updating a local checkout with `gh pr checkout`, and inspecting local files; `target` may be a PR number, URL, or omitted for the current branch.

Input shorthand:

- Canonical in-session invocation: `$review 123` or `$review #123` => `scope=pr`, `target=123`.
- Natural-language aliases: `review 123`, `review #123`, and `review PR 123` => `scope=pr`, `target=123`.
- `review <github-pr-url>` => `scope=pr`, `target=<github-pr-url>`.
- If the user supplies a bare number, treat it as a GitHub PR number for this skill. Do not ask for `scope=pr`.

The skill never writes to the remote service. PR scope may update the local checkout to the PR head before inspection; otherwise it is read-only except for `.reports/codex/review/<timestamp>/` artifacts. Do not pass `--force` to `git` or `gh`; if a forced checkout appears necessary to align the local branch with the PR head, stop, explain the overwrite risk, and ask the user before retrying. If the user asks to fix findings, switch to `resolve` after the review artifact exists.

## Workflow (Exact Commands)

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/review/$TS"
mkdir -p "$OUT_DIR"
```

### 02: T0 mechanical scope gate: resolve scope, collect diff, and classify review risk before any model-level judgment

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
    --out "$OUT_DIR" \
    --checkout
```

In PR scope, GitHub data is evidence only: `gh pr view`, `gh pr diff`, and review-thread queries provide metadata, patch, and comments. Source inspection must use the local checkout recorded in `"$OUT_DIR/local-checkout.json"` after target-branch refresh evidence is written. Do not reconstruct changed source files with `curl`, `raw.githubusercontent.com`, or `head-files/` snapshots. If local checkout fails or `local-checkout.json` does not prove `head_matches_pr=true`, fail the review instead of reviewing remote raw files. Do not retry with `--force` unless the user explicitly confirms after being told why force is needed and what it may overwrite.

Classify the diff and write the decision to `"$OUT_DIR/scope.txt"`:

- `TRIVIAL`: no public API/config/security/ML behavior touched, fewer than 3 files, fewer than 50 changed lines.
- `LOCAL`: one subsystem or 3-7 files, behavior is understandable from local context.
- `BROAD`: 8+ files, cross-subsystem changes, dependency/config changes, or unclear ownership.
- `HIGH_RISK`: public API, release, security, auth, credentials, deserialization, data pipeline, ML tensor math, CI/CD, or migration behavior.

If `scope=pr`, include `pr.json`, `pr-routing.json`, `target-branch.json`, `local-checkout.json`, comments, reviews, review threads, unresolved review threads, and `online-review-summary.json` in the review evidence. `pr-routing.json` and `local-checkout.json` must include `force_policy` proving no forced checkout was run automatically. Treat unresolved online review threads and comments as candidate findings until triaged as valid, duplicate, stale, out-of-scope, or already fixed.

If `files.txt` and `untracked.txt` are both empty and there is no explicit target, fail before running gates. If `scope=pr` and `pr-error.txt` exists, fail with the captured reason.

### 03: T1 primary diff review. Read the changed files end-to-end from the local working tree or checked-out PR branch and identify findings before considering any fix or gate outcome

Review across these axes in order:

- API and behavior regressions.
- Test coverage and edge-case gaps.
- Error handling and logging.
- Project coding principles: changed code follows `.codex/AGENTS.md` for simplicity, readability, reproducibility, short reusable units without low-value argument-remapping wrappers, guard clauses or early `return`/`yield`/`continue`, project docstring-style detection, concise purpose docstrings, and inline comments only for non-trivial implementation blocks.
- Security, data, ML, CI/CD, or release risks signaled by T0.
- Documentation or migration gaps caused by behavior/API changes.

### 04: T2 multi-axis specialist fan-out. For `LOCAL`, `BROAD`, and `HIGH_RISK` diffs, get specialist review before final severity classification

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
- `doc-scribe`: public docs, changelog, migration text, examples, public docstrings, or code self-documentation policy.
- `oss-shepherd`: SemVer, deprecation policy, release readiness, contributor-facing process.
- `squeezer`: performance, memory, throughput, profiling claims, training/inference bottlenecks.
- `scientist`: research-paper methods, benchmark claims, experiment design, metric validity.
- `web-explorer`: current external docs, changelogs, migration guides, or volatile ecosystem behavior.

Use native subagents when runtime policy permits, especially when the user explicitly asks for multi-agent or specialist review. Do not claim specialist fan-out occurred unless separate specialist output exists. If runtime policy, model support, or tool availability prevents spawning, perform a clearly labeled in-main substitute pass for each required role, write it to that role's specialist file, and mark `fanout_substituted=true` in the review notes and result metadata. Substituted passes lower confidence; they do not satisfy independence for critical findings.

`BROAD` and `HIGH_RISK` reviews require real independent `qa-specialist` and `challenger` outputs to return `status=pass`, especially for "no blocking findings" conclusions. If required independent outputs are unavailable, return `status=fail` or `status=timeout`, set `independence_satisfied=false`, and add `needs-independent-review` to follow-up. `LOCAL` reviews may pass with substituted required passes only when the substitutions are explicit, all triggered conditional axes are covered, and confidence is reduced.

### 05: Cross-check every blocking finding against surrounding context and existing project patterns before reporting it. Critical/blocking findings require an independent second pass when feasible; if unconfirmed, downgrade or mark the evidence gap explicitly

### 06: Write `$OUT_DIR/review-notes.md`

Required sections:

- `Decision Summary`
- `Scope`
- `Risk Tier`
- `Files Inspected`
- `Specialist Passes`
- `Specialist Manifest`
- `Findings`
- `No-Finding Residual Risks`
- `Confidence Gaps`
- `Confidence Calibration`
- `Online Review Triage` for `scope=pr`

### 07: Run shared quality gates

```bash
.codex/skills/_shared/run-gates.sh --out "$OUT_DIR"
```

### 08: Classify findings using `../_shared/severity-map.md`

### 09: Compute the structured review decision and update `Decision Summary`

Use exactly one recommendation:

- `accept-as-is`: no findings, required gates passed or were not applicable, and residual risks are explicitly low.
- `minor-changes`: only non-blocking low/medium findings or polish items remain.
- `needs-more-work`: high findings, missing tests, missing evidence, failed relevant gates, or unresolved review-risk gaps remain.
- `reject`: critical findings, unsafe behavior, security/data-loss risk, or a change that should not merge in its current form.
- `not-aligned`: the change does not address the requested issue, PR intent, migration contract, or project direction even if the diff is mechanically sound.

`Decision Summary` must include:

- `Recommendation`: one of the exact values above
- `Summary`: 1-3 sentences covering the review outcome
- `Rationale`: why this recommendation follows from findings, gates, and scope
- `Blocking findings`: critical/high items or `none`
- `Minor changes`: medium/low items or `none`
- `Required next work`: work needed before merge, or `none`
- `Confidence`: score plus key gaps

### 10: Run confidence calibration and recovery before any user-facing output

Before final chat output or `result.json`, write the `Confidence Calibration` section in `review-notes.md` and mirror it in `REVIEW_METADATA.confidence_recovery`.

Required confidence calibration content:

- `Initial Confidence`: starting score and concrete uncertainty sources.
- `Objective Evidence`: changed files inspected, PR/local artifacts used, tests/checks reviewed, specialist outputs, and pattern cross-checks.
- `Confidence Gaps`: missing checks, substituted specialists, unresolved PR evidence, unverified assumptions, or unavailable source context.
- `Recovery Actions`: internal loops already performed to increase confidence, such as reading more code, checking nearby patterns, running focused commands, adding specialist passes, narrowing claims, or downgrading unsupported findings.
- `Recomputed Confidence`: final score and why the evidence supports it.
- `Remaining Limits`: residual uncertainty and whether it is acceptable or blocking.

Shared confidence policy:

Apply the shared confidence band policy from `../_shared/quality-gates.md`. This skill records the required evidence in the `Confidence Calibration` section and mirrors it in `REVIEW_METADATA.confidence_recovery` before output.

Confidence must be honest and objectively verifiable. Do not raise confidence to pass the gate; improve evidence, reduce claim scope, or fail with the missing evidence named.

### 11: If no findings are present, state that explicitly and note residual risks from T0 classification and any substituted specialist passes

### 12: Write and validate the mandatory result artifact

```bash
.codex/skills/_shared/write-result.py \
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

`REVIEW_METADATA.specialist_passes` must mirror every entry from `specialist-manifest.json`. `REVIEW_METADATA.scope` must match the normalized input scope. `REVIEW_METADATA.review_decision` must mirror the `Decision Summary` recommendation, summary, and rationale. `REVIEW_METADATA.confidence_recovery` must mirror the `Confidence Calibration` section and include `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, and `remaining_limits`. `REVIEW_METADATA.confidence_gap_closures` must include one closure record per non-empty `confidence_gaps` entry, with `status=closed|unresolved|deferred` and matching evidence or rationale.

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
13. PR scope without `pr.json`, `pr-routing.json`, `target-branch.json`, `local-checkout.json`, `diff.patch`, `comments.json`, `reviews.json`, `review-threads.json`, `unresolved-review-threads.json`, and `online-review-summary.json` => fail.
14. PR scope that ignores unresolved online reviews without triage => fail.
15. Missing structured review decision summary or invalid recommendation value => fail.
16. PR scope using `curl`, `raw.githubusercontent.com`, or copied `head-files/` snapshots for source inspection instead of the local checkout => fail.
17. PR scope running `git` or `gh` with `--force` before explicit user confirmation and overwrite-risk explanation => fail.
18. Missing `Confidence Calibration` section, `metadata.confidence_recovery`, or `metadata.confidence_gap_closures` => fail.
19. Shared confidence policy violation from `../_shared/quality-gates.md` => fail.

## Quality Gates

Required checks:

- `review`: T0 files, risk tier, local changed-file inspection, simplicity/readability/reproducibility inspection, project docstring-style detection, docstring/comment policy inspection for changed code, PR target-branch refresh and checkout evidence when relevant, specialist manifest, specialist notes, structured decision summary, confidence calibration/recovery, online review triage for PR scope, severity map, and `git diff --check`.

Conditional checks:

- `lint`/`format`/`types`/`tests`: run or inspect available results when needed to validate a finding.
- `calibration`: run when reviewing native skill/agent/config behavior.

## Calibration Hooks

Update calibration when review routing, severity discipline, decision vocabulary, or output shape changes:

- benchmark patterns: `review`
- behavioral cases: false blocker, missing specialist pass, no-finding residual risk, substituted fan-out confidence, PR online review triage, missing project docstring-style detection, missing code self-documentation, long code blocks, deep branching, docstrings masking poor structure, low-confidence recovery loop, objective confidence evidence
- PR routing cases: target-branch refresh required, local checkout required, stale local PR branch, and raw-file snapshot rejection

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

The final chat output must start with a `Review Decision Summary` before detailed findings. Include recommendation, summary, blockers, minor changes, required next work, confidence, confidence band status, recovery actions, remaining limits, confidence gaps or degradation reasons, confidence-gap closures, and artifact path. The recommendation must be one of `accept-as-is`, `minor-changes`, `needs-more-work`, `reject`, or `not-aligned`.

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
    "confidence_gaps": [
      "why confidence is below 1.0 or residual limits still matter"
    ],
    "confidence_gap_closures": [
      {
        "gap": "why confidence is below 1.0 or residual limits still matter",
        "status": "closed|unresolved|deferred",
        "evidence": "evidence that closes the gap when status=closed",
        "rationale": "why the gap remains open when status=unresolved|deferred"
      }
    ],
    "scope": "working-tree|path|commit|pr",
    "risk_tier": "TRIVIAL|LOCAL|BROAD|HIGH_RISK",
    "review_decision": {
      "recommendation": "accept-as-is|minor-changes|needs-more-work|reject|not-aligned",
      "summary": "1-3 sentence review outcome",
      "rationale": "why the recommendation follows from findings, gates, and scope"
    },
    "confidence_recovery": {
      "initial_confidence": 0.0,
      "final_confidence": 0.0,
      "status": "shared-confidence-band-status",
      "evidence": [
        "objective evidence supporting final confidence"
      ],
      "recovery_actions": [
        "internal confidence-improvement loop performed before output"
      ],
      "remaining_limits": [
        "residual uncertainty"
      ]
    },
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
