# Specialist Orchestration Policy

Use specialist orchestration to improve quality or latency when the work can be split into independent axes with narrow context. Do not fan out merely because agents exist.

## Goals

- Increase review, implementation, investigation, and release quality through independent specialist judgment.
- Improve elapsed time by running disjoint evidence gathering or verification in parallel when runtime supports it.
- Reduce context pollution by giving each specialist only the files, diffs, logs, and questions needed for its axis.
- Keep the parent agent responsible for final scope, conflicts, and user-facing conclusions.

## When To Orchestrate

Orchestrate when at least one condition holds:

- The task crosses two or more domains, such as code plus tests, docs, CI, security, data, release, or performance.
- The task is broad enough that independent file ownership or independent verification reduces risk.
- A high-risk conclusion needs an adversarial or second-pass check.
- Parallel evidence gathering can reduce elapsed time without duplicating most of the same context.

Stay single-agent when:

- The task is narrow, local, and fits in roughly one to three files.
- A specialist would receive the same full context as the parent.
- The overhead of packaging context, waiting for results, and consolidating outputs exceeds the likely quality gain.
- The requested action is state-changing and serial safety matters more than speed.

## Context Packs

Before spawning or simulating a specialist pass, write or describe a context pack with:

- `Objective`: one sentence naming the subtask.
- `Relevant files`: only the files, hunks, logs, or docs needed for that subtask.
- `Excluded context`: notable surrounding context intentionally withheld because it is irrelevant.
- `Questions`: concrete checks the specialist must answer.
- `Output contract`: required sections, confidence, evidence, and unresolved gaps.
- `Stop rule`: when the specialist should stop instead of widening scope.

Do not give every specialist the full repository, full PR thread, or full report by default. A specialist may request more context; the parent decides whether the request is relevant.

## Output Contract

Every specialist pass, whether a real subagent or an in-main substitute, must return:

- role and axis
- files or evidence inspected
- findings with severity or `none`
- confidence score and confidence band
- confidence gaps and closure status
- recommended next action

The parent must consolidate specialist outputs into one decision and reconcile conflicts explicitly. Specialist outputs are evidence, not votes.

## Substitution Rules

Use native subagents when runtime policy permits and parallelism or independence materially helps. If subagents are unavailable, write a labeled in-main substitute pass. Substitution lowers independence and may lower confidence, especially for `BROAD`, `HIGH_RISK`, release, security, or no-finding conclusions.

Do not claim "specialist fan-out" happened unless separate specialist outputs exist. Use `spawned`, `substituted`, or `not_triggered` status for every planned specialist axis.

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
