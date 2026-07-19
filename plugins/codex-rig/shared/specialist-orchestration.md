# Specialist Orchestration Policy

Use specialists for quality/latency only when independent narrow-context axes exist. Do not fan out merely because agents exist.

## Goals

- Improve review, implementation, investigation, release through independent judgment.
- Reduce elapsed time with runtime-supported parallel disjoint evidence/verification.
- Give each specialist only needed files, diffs, logs, questions.
- Route bounded workstream to lowest-cost capable registered specialist.
- Parent owns final scope, conflicts, user conclusions.

## When To Orchestrate

Orchestrate when one holds:

- Crosses 2+ domains: code, tests, docs, CI, security, data, release, performance.
- Broad enough that independent ownership/verification reduces risk.
- High-risk conclusion needs adversarial/second pass.
- Parallel evidence reduces time without mostly duplicating context.

Stay single-agent when:

- Narrow/local, roughly 1–3 files.
- Specialist needs same full parent context.
- Context/wait/consolidation cost exceeds quality gain.
- State change needs serial safety more than speed.

## Delegation Lead And Model Routing

Use `delegation-lead` for 2+ separable workstreams when delegation beats context/consolidation cost. Config allows depth 2 nested specialists; leader returns one consolidated handover, never final ownership.

Choose lowest-cost capable registered role:

- Luna: delegation coordination, documentation, CI/CD stewardship, web evidence, OSS triage, and static analysis.
- Terra: implementation, tests, runtime behavior, data/ML, performance, research method, curation, adversarial challenge, and final executable verification.
- Sol: solution architecture and security only.

Never downgrade architecture, security, runtime/API, release-blocking judgment, executable acceptance; never escalate bounded support to Sol. Avoid delegation when all need same context or parent can finish before handoff packaging/validation.

## Context Packs

Before spawning/simulating pass, write/describe context pack:

- `Objective`: one-sentence subtask.
- `Relevant files`: only needed files, hunks, logs, docs.
- `Excluded context`: notable irrelevant withheld context.
- `Questions`: concrete required checks.
- `Output contract`: sections, confidence, evidence, unresolved gaps.
- `Stop rule`: stop rather than widen scope.

Do not default to full repo/PR thread/report. Specialist may request more; parent decides relevance.

Write human-readable context packs in Caveman Ultra. Preserve exact evidence, questions, output contract, stop rule, risks, and ownership. Use clear concise prose where Ultra would make security, irreversible, or ordered instructions ambiguous.

## Output Contract

Every real/substitute pass returns:

- role/axis
- inspected files/evidence
- findings with severity or `none`
- confidence score/band
- gaps/closure status
- recommended next action

Parent consolidates one decision, explicitly reconciles conflicts. Outputs are evidence, not votes.

## Handover Gate

Before accepting delegated work, lead then parent verify:

- ownership stayed assigned file/evidence axis
- requested output/objective evidence complete
- checks passed or each unavailable check has reason
- shared confidence contract and visible unresolved limits
- explicit scope widening/conflicts
- executable/behavior-changing acceptance returns parent or Terra/Sol owner

Reject/re-scope handovers lacking evidence, crossing ownership, hiding failures, transferring acceptance to support. Keep accepted changes unstaged. Use Caveman Ultra handover text: each fact once, no filler or repeated context; retain exact ownership, evidence, checks, failures, conflicts, limits, and next owner/action. Use clear concise prose where Ultra would make security, irreversible, or ordered instructions ambiguous. `.codex/handover/` patch only when materially useful and remains lossless.

## Substitution Rules

Use native subagents when policy allows and parallelism/independence helps. If unavailable, label in-main substitute. Substitution lowers independence/confidence, especially `BROAD`, `HIGH_RISK`, release, security, no-finding.

Claim "specialist fan-out" only with separate outputs/runtime provenance. Record only triggered axes as `spawned`/`substituted`; keep non-triggers in compact routing artifact.

## Retry And Checkpoint Policy

- Max 2 attempts/specialist.
- Retry only timeout, transport, rate limit; not deterministic finding, validation failure, completed output.
- Preserve completed output/narrow packs. Checkpoint records evidence, not completed response.
- Record selected completed attempt; retain failed transient attempt for audit.

## Recommended Specialist Axes

| Axis                 | Agent                | Use When                                                    |
| -------------------- | -------------------- | ----------------------------------------------------------- |
| implementation       | `sw-engineer`        | feature, fix, refactor, API implementation                  |
| tests and regression | `qa-specialist`      | acceptance checks, edge cases, failure/pass evidence        |
| architecture/API     | `solution-architect` | public API, migration, cross-subsystem coupling             |
| docs and migration   | `doc-scribe`         | public docs, examples, changelog, docstrings                |
| security             | `security-auditor`   | auth, secrets, permissions, deserialization, supply chain   |
| CI/tooling           | `cicd-steward`       | workflows, release automation, flaky CI                     |
| lint/types           | `linting-expert`     | ruff, mypy, pre-commit, suppression policy                  |
| data/ML pipeline     | `data-steward`       | datasets, leakage, reproducibility, tensor boundaries       |
| performance          | `squeezer`           | profiling, memory, throughput, GPU sync                     |
| release/OSS          | `oss-shepherd`       | SemVer, deprecations, maintainer readiness                  |
| research/method      | `scientist`          | papers, metrics, ablations, experiment design               |
| external docs        | `web-explorer`       | volatile API/docs/changelog evidence                        |
| config hygiene       | `curator`            | skill/agent drift, calibration, instruction overlap         |
| challenge            | `challenger`         | adversarial check for risky plans or no-finding conclusions |
