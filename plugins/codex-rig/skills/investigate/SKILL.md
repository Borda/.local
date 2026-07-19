---
name: investigate
description: Minimal codex-native investigation loop. Use for unknown failures, code debugging, and root-cause narrowing with measurable gates.
---

# Investigate

Diagnosis-first loop for unclear failures: failing tests, tracebacks, regressions, surprising runtime behavior. Produce root-cause claim with evidence, falsification, rejected alternatives before any fix. Use `investigate` until root cause established; then hand off to `develop` or `code-remediate`.

## Input Schema

```json
{
  "symptom": "required failing command, traceback, runtime bug, CI failure, flaky behavior, or tool anomaly",
  "scope": "optional path/module/tool/CI run",
  "pace": "fast|full",
  "done_when": "one root cause is confirmed or the remaining uncertainty is explicit"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/investigate/$TS"
mkdir -p "$OUT_DIR"
```

In each later Bash block, replace `<run-directory-created-in-step-01>` with the exact path created in step 01.

### 02: Capture symptom and reproduction context

Write `$OUT_DIR/symptom.md` with:

- failing command or observed behavior
- expected behavior
- local vs CI vs external context
- first known bad time or commit, if known
- whether the failure is deterministic, flaky, or unknown

### 03: Gather signals before forming hypotheses

```bash
OUT_DIR="<run-directory-created-in-step-01>"
git log --oneline -10 >"$OUT_DIR/recent-commits.txt" 2>/dev/null || true
python --version >"$OUT_DIR/python-version.txt" 2>&1 || true
```

Inspect `collect-diff.sh --help`, collect `working-tree` scope into `$OUT_DIR/baseline`; record collection failure, never treat as empty diff.

Add needed tool logs, CI excerpts, tracebacks, config, changed source. Absence of evidence ≠ evidence of absence.

### 04: Rank hypotheses in `$OUT_DIR/hypotheses.md`

```markdown
| Rank | Hypothesis | Supporting evidence | Falsification check | Status |
| --- | --- | --- | --- | --- |
```

Include ≥3 plausible hypotheses unless failing command + code/log directly prove root cause.

### 05: Orchestrate specialist probes when hypotheses split by domain

Apply `../../shared/specialist-orchestration.md` for multi-domain symptoms or useful parallel evidence. Stay single-agent for narrow deterministic failure with one obvious hypothesis.

Write `"$OUT_DIR/specialist-probes.md"` before fan-out: role, hypothesis, context path, expected falsification signal, mode (`spawned`, `substituted`, `not_triggered`).

Recommended probe routing:

- `qa-specialist`: flaky tests, failing assertions, regression reproduction, missing edge-case evidence.
- `cicd-steward`: CI-only failure, matrix/cache/permission divergence, release workflow failures.
- `linting-expert`: ruff, mypy, pre-commit, tool version or suppression anomalies.
- `security-auditor`: auth, secret handling, deserialization, dependency, or permission-related failures.
- `data-steward`: data split, leakage, augmentation, DataLoader, or reproducibility anomalies.
- `squeezer`: performance regressions, memory/OOM, throughput drops, GPU sync suspicion.
- `scientist`: metric instability, paper/method mismatch, experiment validity.
- `web-explorer`: volatile dependency or external API behavior.
- `challenger`: root-cause claim that would be damaging if wrong.

Each context pack: symptom slice, relevant logs/touched files/environment facts, exact falsification question. Specialists may request context; parent decides widening, consolidates outcomes, owns final root-cause claim.

### 06: Probe the top hypotheses

Use targeted probes confirming, ruling out, or narrowing one hypothesis at a time.

Each probe must have a clear outcome:

- `confirmed`
- `ruled_out`
- `inconclusive`

Persist probe commands and outputs under `$OUT_DIR/probes/` or inline in `$OUT_DIR/probes.md`.

### 07: Run the anti-rationalization gate

A root-cause claim requires:

- supporting evidence from logs/code/commands
- one falsification check
- at least one rejected alternative
- explicit confidence

Low confidence: continue probing, no fix proposal.

Write `$OUT_DIR/root-cause.md` with:

- `Evidence`
- `Falsification`
- `Rejected Alternatives`
- `Confidence`

### 08: Run shared quality gates or targeted checks relevant to the failure

Inspect `run-gates.sh --help`, run full/targeted gates needed to falsify hypotheses.

### 09: Decide gate result, write `result.candidate.json`, validate artifacts, and publish `.reports/codex/investigate/<timestamp>/result.json`

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write with `INVESTIGATE_METADATA`, validate as skill `investigate`, and promote only the validated candidate.

## Fail-Fast Rules

1. Missing symptom => fail.
2. No evidence collected before hypotheses => fail.
3. Root cause stated without falsification check => fail.
4. Workaround presented as root cause => fail.
5. Missing `root-cause.md` evidence, falsification, rejected alternatives, confidence => fail.
6. Broad multi-domain symptom without `specialist-probes.md` or an explicit single-agent rationale => fail.
7. Result artifact validator failure => fail.
8. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: hypothesis table, probe outcomes, rejected alternatives, and `git diff --check`.
- `artifact`: shared validator confirms investigation artifacts, gate logs, and result JSON shape.

Conditional checks:

- `tests`: failing or confirming reproduction command when available.
- `lint`, `format`, `types`: only when code/config changes are made as part of a probe.

## Calibration Hooks

Update calibration when root-cause routing or workaround rejection changes:

- behavioral cases: symptom-first routing, rejected alternatives, low-confidence probe escalation, artifact validator bypass
- benchmark patterns: `investigate`

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
