# Specialist Orchestration Policy

Use specialists for quality/latency only when independent narrow-context axes exist. Do not fan out merely because agents exist.

## Goals

- Improve review, implementation, investigation, release through independent judgment.
- Reduce elapsed time with runtime-supported parallel disjoint evidence/verification.
- Give each specialist only needed files, diffs, logs, questions.
- Route each bounded workstream to the lowest-cost capable canonical role.
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

## Bounded Dispatch Wave

Each parent work item gets one approved dispatch wave after routes/immutable packs. Parent overlaps only unowned work; joins all handoffs before acceptance. A second wave is forbidden: handle discoveries parent-serially or stop and re-plan with the user. Never add fan-out, overlap ownership, bypass approval, or start dependencies; unsafe/unavailable parallelism records equal-gate serial fallback.

## Delegation Lead And Model Routing

Use `delegation-lead` for 2+ separable workstreams when delegation beats context/consolidation cost. Request nested specialists only when the active runtime proves the required depth; otherwise keep delegation at the parent. The lead returns one consolidated handover, never final ownership.

Classify each workstream from current task evidence before selecting a role; a task label, file count, or a cheaper available model is not evidence of capability:

- Bounded support with no behavior, API, runtime, release-blocking, architecture, or security authority: Luna.
- Implementation, runtime behavior, tests, data/ML, performance, research method, curation, adversarial challenge, or executable verification: Terra.
- Architecture or security judgment: Sol only after the user expressly requests Sol or selects `solution-architect` or `security-auditor`; otherwise the Terra parent/session retains the work.

Choose the smallest tier satisfying that classification while preserving each role card's trigger and NOT-for boundary. Escalate only for a specific mandatory boundary or observed lower-tier insufficiency; record the boundary or failed/insufficient evidence. De-escalate only after an evidenced scope split leaves bounded support with no retained Terra/Sol authority; record that reduced scope. Cost alone never escalates or de-escalates a tier.

Current canonical assignments:

- Luna: delegation coordination, documentation, CI/CD stewardship, web evidence, OSS triage, and static analysis.
- Terra: implementation, tests, runtime behavior, data/ML, performance, research method, curation, adversarial challenge, and final executable verification.
- Sol: explicitly requested architecture or security advice only. The pass is read-only and bounded: it returns evidence and an artifact, then the Terra parent/session continues and accepts any behavior-changing or executable result.

Never downgrade architecture, security, runtime/API, release-blocking judgment, executable acceptance; never auto-escalate a matching architecture/security workstream to Sol or escalate bounded support to Sol. Sol selection requires the user's explicit request or agent selection, not task labels or risk classification. Record that request/selection, the bounded advisory question, and any escalation/de-escalation evidence in the routing decision. Avoid delegation when all need same context or parent can finish before handoff packaging/validation.

### Reasoning-Progress Escalation

The [reasoning-progress escalation policy](native-skill-contract.md#reasoning-progress-escalation) is authoritative for detecting a stalled workstream and its required ledger. Two consecutive work cycles without material progress or three evidence-backed attempts without closing the same condition are observed lower-tier insufficiency, not permission to bypass role boundaries.

For the single advisory pass, first request one supported higher reasoning-effort level for the same permitted model; only then use the next permitted tier. Luna may consult Terra. Sol remains limited to architecture or security and still requires the user's explicit request or agent selection; no advisory pass transfers executable acceptance or state-changing authority. A route is advisory-eligible only when the actual observed sandbox is `read-only`; a requested or claimed sandbox is insufficient. If no permitted read-only route is observable or available, route directly to the human handoff. Record the trigger ledger, closure condition, requested and observed model/effort, observed sandbox, route result, advisory recommendation, and its stop condition. The parent may authorize one bounded recovery action; a result without material progress or an unchanged unmet closure condition then requires the human handoff, not another advisor or retry.

## Context Packs

Before spawning/simulating pass, write/describe context pack:

- `Objective`: one-sentence subtask.
- `Relevant files`: only needed files, hunks, logs, docs.
- `Excluded context`: notable irrelevant withheld context.
- `Questions`: concrete required checks.
- `Output contract`: sections, confidence, evidence, unresolved gaps.
- `Stop rule`: stop rather than widen scope.

Do not default to full repo/PR thread/report. Specialist may request more; parent decides relevance.

## Portable Role Routing

Resolve the requested role card at `../roles/<role-id>/ROLE.md` relative to this policy. Treat those exact bytes as the behavioral authority. Plugin-only installs do not create custom-agent files.

Before routing, classify each requested model, sandbox, approval, and nesting setting as `mandatory` or `preferred` from the task's actual risk. Use this route order:

1. A runtime-provided blank/default subagent with the complete exact role-card bytes injected before the narrow context pack.
2. An inline pass in the parent context with the exact role card applied and independence reported as false.
3. `unavailable` when the runtime cannot provide any safe route or cannot prove a mandatory profile setting.

Fallback only for route absence or rejection before substantive role work. Never retry another route because the specialist disagreed, returned a finding, or failed an acceptance gate. Built-in injection may retain parallel independence but cannot claim the role card's model, sandbox, approval, or nesting profile unless the runtime independently proves each setting. Preferred settings that are unproved are recorded as requested-only and lower fidelity; mandatory settings that are unproved stop at `unavailable`. Inline fallback is serial and non-independent.

For injection, the parent reads and hashes the canonical card, then places its full text before the narrow task context. Passing only a role ID or path, or asking the child to search for the card, is not injection. A sanitized `task_name` is provenance only; it neither selects a custom profile nor proves agent activation.

Persistent named shims are platform-blocked for routing until Codex exposes a verifiable custom-agent selector and a fresh-session probe proves the child consumed the selected TOML. Their lifecycle manager remains available for diagnosis and authenticated cleanup of prior development installations.

Recurrence, root-cause, and reasoning-progress handling are authoritative in [`native-skill-contract.md`](native-skill-contract.md#recurrence-and-root-cause-policy); this orchestration policy does not duplicate or override them.

For every routed pass record: `role_id`, role-card SHA-256, route, attempted routes, fallback reason, actual model and reasoning effort when observable, requested and observed sandbox/approval controls, independence, nesting depth, and material fidelity limits. Also record the observed `agent_role` when available; a null value cannot support a custom profile claim.

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

An explicit Sol advisor is never an implementation or acceptance owner: preserve its evidence artifact, return to the Terra parent/session, and require that parent to decide the next action and final acceptance.

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

Use runtime-provided subagents when policy allows and parallelism or independence helps, following the portable route order above. If no safe subagent route exists, label an in-main substitute. Substitution lowers independence and confidence, especially for broad, high-risk, release, security, or no-finding conclusions.

Claim "specialist fan-out" only with separate outputs/runtime provenance. Record only triggered axes as `spawned`/`substituted`; keep non-triggers in compact routing artifact.

## Retry And Checkpoint Policy

- Max 2 attempts/specialist.
- Retry only timeout, transport, rate limit; not deterministic finding, validation failure, completed output.
- Preserve completed output/narrow packs. Checkpoint records evidence, not completed response.
- Record selected completed attempt; retain failed transient attempt for audit.

## Recommended Specialist Axes

| Axis | Agent | Use When |
| -- | -- | -- |
| implementation | `sw-engineer` | feature, fix, refactor, API implementation |
| tests and regression | `qa-specialist` | acceptance checks, edge cases, failure/pass evidence |
| architecture/API | `solution-architect` | user expressly requests Sol or selects the role for public API, migration, or cross-subsystem coupling |
| docs and migration | `doc-scribe` | public docs, examples, changelog, docstrings |
| security | `security-auditor` | user expressly requests Sol or selects the role for auth, secrets, permissions, deserialization, or supply chain |
| CI/tooling | `cicd-steward` | workflows, release automation, flaky CI |
| lint/types | `linting-expert` | ruff, mypy, pre-commit, suppression policy |
| data/ML pipeline | `data-steward` | datasets, leakage, reproducibility, tensor boundaries |
| performance | `squeezer` | profiling, memory, throughput, GPU sync |
| release/OSS | `oss-shepherd` | SemVer, deprecations, maintainer readiness |
| research/method | `scientist` | papers, metrics, ablations, experiment design |
| external docs | `web-explorer` | volatile API/docs/changelog evidence |
| config hygiene | `curator` | skill/agent drift, calibration, instruction overlap |
| challenge | `challenger` | adversarial check for risky plans or no-finding conclusions |
