# Codex Rig Roles

Each subdirectory under `roles/` holds one `ROLE.md` — a role card that packages a Codex specialist: its model tier, sandbox and approval posture, and the trigger/evidence/execution/handover/confidence contract that keeps it inside its lane. This README explains two things a maintainer needs before touching a role card: the three-tier model-routing schema that decides which model a role runs on, and the schema every `ROLE.md` must satisfy to pass the calibration harness.

## Contents

- [Three-tier model-routing schema](#three-tier-model-routing-schema)
- [Role roster](#role-roster)
- [Role-card contract](#role-card-contract)
- [Fallback modes](#fallback-modes)

## Three-tier model-routing schema

Every role runs on one of three `gpt-5.6-<tier>` models. All fifteen roles share the same `model_reasoning_effort: high`, `approval_policy: on-request`, and `fallback_modes: [shim, built-in-injected, inline]` — only `model` and `sandbox_mode` vary per role.

| Tier      | Model           | Purpose                                                                                                                                                                                    | Roles                                                                                             |
| --------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| **Sol**   | `gpt-5.6-sol`   | Deepest reasoning — architecture and security decisions that are expensive to get wrong and cheap to slow down.                                                                            | `solution-architect` (workspace-write), `security-auditor` (read-only)                            |
| **Terra** | `gpt-5.6-terra` | Core build-and-verify work, plus the roles that own a final parent-facing decision — implementation, executable acceptance, adversarial review, data integrity, research, and performance. | `sw-engineer`, `qa-specialist`, `challenger`, `curator`, `data-steward`, `scientist`, `squeezer`  |
| **Luna**  | `gpt-5.6-luna`  | Cost-aware coordination and execution — documentation, CI/CD, static analysis, web evidence, OSS triage, and delegation coordination itself.                                               | `doc-scribe`, `cicd-steward`, `delegation-lead`, `linting-expert`, `oss-shepherd`, `web-explorer` |

### Rationale

The tier assignment is not a preference guess — it is recorded, evidence-derived routing state in `runtime/calibration/accepted-route-evidence.json`. That file's `active_assignments` block lists the same three tier-to-role mappings above, and its `adjudication` block explains why:

- `delegation-lead` runs on Luna by explicit human override: the rationale is "a cost-aware delegation leader that uses Luna for coordination while routing implementation and executable acceptance to Terra and architecture/security to Sol; the strict Luna route failure remains preserved."
- `cicd-steward`, `doc-scribe`, `linting-expert`, `oss-shepherd`, and `web-explorer` run on Luna by a second override, for the same reason: documentation, CI/CD stewardship, web evidence, OSS triage, and static analysis stay on Luna, while architecture and security stay on Sol and general implementation plus final parent decisions stay on Terra.
- `adjudication.luna_strict_failure_preserved: true` means the strict-route calibration result — Luna failed the strict quality bar on its own (`luna-score.json` records `strict_status: "fail"`) — is kept on record rather than silently overwritten by the human override. The override changes the assignment; it does not erase the evidence that produced a different strict answer.
- The adjudication rule itself only accepts an evidence-derived candidate "with zero pair quality regressions and either mean F1 gain >= 0.01 or geometric-mean normalized cost ratio \<= 1.0" — the human overrides above are recorded as explicit exceptions to that rule, not replacements for it.

`sandbox_mode` is set per role, independent of tier: `read-only` for the five pure-analysis roles — `challenger`, `squeezer`, `security-auditor`, `oss-shepherd`, `web-explorer` — and `workspace-write` for the remaining ten, which are expected to produce or modify artifacts as part of their job.

### Task-difficulty selection

Role selection uses the canonical [model-difficulty policy](../shared/specialist-orchestration.md#delegation-lead-and-model-routing), not a model preference. Luna is limited to bounded support; Terra owns behavior and executable verification; Sol is reserved for architecture and security. The routing record must cite the current task boundary or observed lower-tier insufficiency to escalate, and an evidenced scope split to de-escalate; cost alone is insufficient.

## Role roster

| Role                 | Tier  | Sandbox mode    | Purpose                                                                                                 |
| -------------------- | ----- | --------------- | ------------------------------------------------------------------------------------------------------- |
| `solution-architect` | Sol   | workspace-write | System-design specialist for architecture, public API contracts, migrations, and module boundaries.     |
| `security-auditor`   | Sol   | read-only       | Security specialist for Python/web trust boundaries, ML supply chains, secrets, and CI/CD permissions.  |
| `sw-engineer`        | Terra | workspace-write | Implementation specialist for production code, bug fixes, refactors, and typed public API changes.      |
| `qa-specialist`      | Terra | workspace-write | Testing specialist for regression proof, risk-proportional edge coverage, and independent verification. |
| `challenger`         | Terra | read-only       | Adversarial reviewer for plans, architecture, migrations, releases, and non-trivial diffs.              |
| `curator`            | Terra | workspace-write | Configuration-quality specialist for instruction hygiene, routing clarity, duplication, and drift.      |
| `data-steward`       | Terra | workspace-write | ML data-pipeline integrity specialist for datasets, splits, labels, transforms, and leakage prevention. |
| `scientist`          | Terra | workspace-write | ML research specialist for paper analysis, hypotheses, ablations, and evaluation protocols.             |
| `squeezer`           | Terra | read-only       | Performance specialist for throughput, latency, memory, GPU utilization, and profiling evidence.        |
| `doc-scribe`         | Luna  | workspace-write | Documentation specialist for public API docs, docstrings, README content, and changelogs.               |
| `cicd-steward`       | Luna  | workspace-write | CI/CD reliability specialist for GitHub Actions, release automation, and flaky-CI diagnosis.            |
| `delegation-lead`    | Luna  | workspace-write | Cost-aware orchestration specialist for decomposing work and consolidating specialist evidence.         |
| `linting-expert`     | Luna  | workspace-write | Static-analysis specialist for Ruff, mypy, pre-commit, and suppression hygiene.                         |
| `oss-shepherd`       | Luna  | read-only       | Open-source lifecycle specialist for issue triage, semantic versioning, and release readiness.          |
| `web-explorer`       | Luna  | read-only       | External-evidence specialist for official documentation, release notes, and version verification.       |

## Role-card contract

Every `roles/<role_id>/ROLE.md` follows one fixed schema, and `runtime/calibration/run.py`'s `check_agents()` enforces it mechanically — a role card missing any required field or section fails calibration.

**Frontmatter (7 required fields):**

| Field                    | Constraint                                                                        |
| ------------------------ | --------------------------------------------------------------------------------- |
| `role_id`                | Must match the containing directory name.                                         |
| `name`                   | Must be `codex-rig-<role_id>`.                                                    |
| `model`                  | One of `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` — see the tier table above. |
| `model_reasoning_effort` | `high` for every role.                                                            |
| `approval_policy`        | `on-request` for every role.                                                      |
| `sandbox_mode`           | `read-only` or `workspace-write`.                                                 |
| `fallback_modes`         | `[shim, built-in-injected, inline]` for every role — see below.                   |

**Body (5 required `##` sections, in order):**

1. **Trigger and skip boundaries** — when the role fires, when it skips, and what it explicitly is not for. Keeps routing between roles unambiguous.
2. **Evidence ownership** — what the role must read or establish before acting, and what it must record (rejected alternatives, tradeoffs, verified-vs-assumed state) as it works.
3. **Execution constraints** — house style, conventions, and hard "do not" rules the role must respect, plus which other role owns adjacent work it must hand off instead of doing itself.
4. **Handover contract** — the exact ordered content the role must return to its parent or caller.
5. **Confidence contract** — the 0–1 confidence score the role must report, the ≥0.90 bar for a completion claim, and the instruction to name every material evidence gap rather than omit it.

A role card that satisfies this contract is portable: any consumer of the calibration harness can parse its frontmatter for routing and its five sections for behavior, without reading role-specific prose.

## Fallback modes

`fallback_modes: [shim, built-in-injected, inline]` is the same three-step injection fallback chain for every role, tried in order:

1. **`shim`** — a thin, authenticated Codex Rig role link (a generated `codex-rig-<role_id>.toml`) that verifies the installed package and role card before use. New shim *installation* is currently platform-blocked (Codex has no verifiable custom-agent selector yet); existing shims from prior development can still be diagnosed and removed — see `scripts/README.md`'s `manage_role_agents.py` entry.
2. **`built-in-injected`** — a runtime blank agent with the exact verified role-card bytes injected directly, used for parallel specialist work when no persistent shim is available.
3. **`inline`** — a serial inline role pass within the parent's own turn; the fallback of last resort when no independent agent route is available.

The chain order matters: a role only falls back to `inline` when both `shim` and `built-in-injected` are unavailable, so most work still gets the isolation and parallelism of a separate agent pass.
