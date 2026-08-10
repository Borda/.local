# Changelog

## 0.4.8

- Require every `code-review` `needs-more-work` result to include a validated `Review Findings and Merge Blocks` table with the affected area, exact pre-merge change, evidence, and actionable status; reproduce that table in the final review summary.
- Require the same table when PR evidence collection fails before source review, while explicitly marking source findings as not assessed rather than inventing a code finding.
- Require the table for every non-`accept-as-is` PR decision, including minor changes, rejection, and not-aligned outcomes; each row names a finding or operational blocker.

## 0.4.7

- Make repository Codex sync install, verify, and remove Codemap alongside Codex Rig while keeping Codex Rig as the sole owner of the managed global instructions block.

## 0.4.6

- Require evidence-based model-difficulty routing: use Luna only for bounded support, Terra for behavior and executable verification, and Sol only for architecture or security; record concrete escalation or de-escalation evidence and never route on cost alone.

## 0.4.5

- Replace bare option strings with named `(str, Enum)` types: `SyncAction` in `sync_codex.py`, and `ResultStatus`, `ClosureStatus`, and `RecoveryStatus` in `write-result.py`. `argparse` now derives `choices=` from the enum instead of repeating the literals, so the CLI surface and the accepted values cannot drift apart. Accepted CLI values and emitted output are unchanged.

## 0.4.4

- Prefer maintained standard-library, native-platform, and already-installed package functionality over duplicating custom code; reject complexity justified only by hypothetical future states, risks, scale, reuse, or edge cases; preserve trust-boundary, data-loss, security, accessibility, and explicit-contract safeguards; record a deliberately bounded simplification's present ceiling and observable revisit trigger.
- Require descriptive user-facing commit handoffs with each hash and title, behavioral impact, affected surfaces, exact verification evidence, residual limits, and the rationale for multiple-commit boundaries.

## 0.4.3

- Keep compact `investigate` and `sync` routing descriptions aligned with the offline calibration contract.

## 0.4.2

- Name the review, test, and toolchain owners in the `oss-shepherd` role card and state that its handover drafts stay advisory text rather than applied changes.
- Record in `shared/native-skill-contract.md` that `agent-shims` is absent from the calibration skill roster, so required-section, `result-template.json`, and canonical result-artifact checks do not run against it.
- Assert manifest identity relationally in `test_installed_cache_scaffold.py` — both shipped manifests must agree and the release must appear in this file — instead of pinning a version literal that broke on every bump.

## 0.4.1

- Require root-cause investigation when the same or plausibly shared obstacle occurs a second time, even when its surface symptom changes.
- Stop after a third occurrence and ask the human with attempted actions, current hypotheses and evidence, and a concise description of the recurring obstacle.
- Enforce recurrence-policy references only at recurrence-owning workflows (`develop`, `code-remediate`, `investigate`, and `delegation-lead`) with calibrated behavioral cases.

## 0.4.0

- Add optional codemap-py structural-context integration: `shared/codemap_adapter.py` probes the public `codemap-py doctor --json`/`query` CLI once per decision point in `analyse`, `audit`, `code-review`, `code-remediate`, `develop`, `investigate`, `optimize`, `release`, and `research`, and persists the result to the run artifact instead of re-querying per specialist.
- Document the `codemap-py.integration.v1` protocol, named status vocabulary (`available`/`absent`/`stale`/`incompatible`/`degraded`), category-to-query map, and the five not-applicable skills (`manage`, `sync`, `agent-shims`, `calibrate`, `kaggle`) in `shared/codemap-contract.md`.
- Keep the integration symmetric and optional: Codex Rig never imports `codemap_py` or requires it installed; absence/incompatibility falls back to normal bounded file inspection.

## 0.3.0

- Add native Windows package verification, read-only shim diagnostics, SessionStart execution, and explicit CI acceptance.
- Replace Bash-only workflow execution with canonical Python diff, PR, gate, run-directory, and Codex sync entrypoints; remove redundant POSIX compatibility wrappers.
- Preserve exact POSIX mode enforcement and authenticated shim cleanup while treating modes and shim mutation as explicitly not applicable on Windows.
- Freeze the audited Windows skip surface and reject private Windows user-profile paths from published package bytes.
- Keep extensionless package identity files LF-stable and resolve validated Windows batch launchers during Codex sync.

## 0.2.4

- Accept protected current-user Codex agent directories without changing their permissions, while keeping lifecycle state private.
- Align executable validation with the package-wide 512 MiB bound and report exact failed invariants.
- Make SessionStart and `agent-shims` diagnostics explain the first cause, confirm zero writes, and provide safe next steps.

## 0.2.3

- Add intent-first target-merge conflict resolution to PR remediation, with explicit merge-commit authorization and fail-closed completion evidence.
- Add scoped `sync.sh clear` teardown for Claude and Codex plugins plus authenticated removal of the managed global-instructions block.
- Keep package identity, release documentation, and acceptance checks synchronized with the plugin version.

## 0.2.2

- Make Codex Rig the canonical source for workflows, role cards, lifecycle contracts, calibration, and public product documentation.
- Document exact blank-agent role injection, inline fallback, model-control limits, lifecycle behavior, and lessons learned from the original named-agent design.
- Replace repository-to-home `.codex` copying with public GitHub plugin installation.
- Follow the GitHub default branch by default while retaining an optional immutable release-tag pin.
- Ship generic Codex guidance as inert `assets/AGENTS.md`; repository sync installs or updates its backup-protected managed block by default whenever Codex scope is active, with `--no-codex-global-agents` opt-out. Direct plugin installation and Claude-only sync leave global and project instructions untouched.
- Require exact, explicit authorization before any amend, rebase, reset, squash, fixup, or equivalent history rewrite.

## 0.2.1

- Package 13 Codex-native workflow skills, one experimental shim manager, and 15 canonical specialist role cards.
- Support parallel blank-agent role-card injection with inline fallback when spawning is unavailable.
- Preserve transactional, exact-approval diagnosis and cleanup for prior thin user-agent shims on supported POSIX local filesystems; block new installation until runtime selection is verifiable.
- Add a trust-gated, read-only SessionStart shim-health diagnostic.
- Keep MCP and native plugin-bundled agent registration out of scope.

Known limit: standalone shim installation proves ownership and link integrity, not selection by the active collaboration interface. Runtimes without an explicit custom-agent selector use blank-agent role injection.

## 0.1.0

- Establish the Apache-2.0 Codex plugin package, deterministic inventory, portable workflows, and canonical role cards.
- Define the thin-shim safety contract, authenticated installed state, and reversible transaction foundation.
- Introduce role-card fallback routing while native custom-agent selection remained unverified.
