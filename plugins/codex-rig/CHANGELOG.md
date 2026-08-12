# Changelog

## 0.7.4

- Accept canonical `Review Findings and Merge Blocks` sections by using regex control sequences as regex tokens instead of matching their backslash spellings literally.
- Derive mechanical review tier and evidence through one shipped routing helper shared by the code-review producer and validator, eliminating model-authored file/line arithmetic drift.
- Keep shell network access blocked by default while requiring scoped external-network approval for the complete command owning every intentional `gh` or `kaggle` call, GitHub collector fetch/HTTPS path, Codex Git marketplace add/upgrade, and paid live `codex exec` calibration.
- Keep missing Kaggle CLI installation and authentication user-owned: Codex Rig reports the prerequisite and never runs or authorizes an installer.
- Require the complete PR collector command to own approval for its nested GitHub CLI, HTTPS fallback, checkout, and Git fetch traffic instead of approving a standalone `gh` command.
- Retry one unapproved sandbox-shaped `github-network` collection failure through the runtime approval mechanism before reporting review or remediation evidence unavailable.

## 0.7.3

- Require abstractions to reduce reader-visible concepts, keep ordinary Python imports at module scope, and prefer concrete fixture state plus ordinary helpers over nested fixture factories or meaningless aliases.
- Calibrate nested fixture builders, redundant fixture aliases, unjustified local imports, and incomplete helper extractions that hide scenario inputs or leave sibling behavior duplicated.
- Keep Terra as the normal parent/session and require explicit user selection before either Sol-pinned architecture or security role runs; Sol passes are bounded read-only advisories that return evidence and final acceptance to Terra.

## 0.7.2

- Add `$code-remediate review` for current-session report-mode remediation: reuse the latest assessed `code-review` artifact without refreshing PR evidence or online comments, and fail closed when that artifact is unavailable.
- Add an evidence-backed PR `close` gate before detailed code review, with eight explicit reason codes, false-positive safeguards, blocking-default guidance, validator-enforced terminal artifacts, and remediation rejection for closed results.
- Require every proposed or created Codex commit to include complete `Changes`, `Impact`, `Verification`, and `Residual limits` sections so the commit itself preserves behavioral scope, concrete effects, executed evidence, and remaining uncertainty.
- Restore calibration coverage for the shipped escalation-ledger CLI by registering it in the shared helper self-test roster and restoring its executable package mode.

## 0.7.1

- Add a bounded public HTTPS PR metadata fallback through the allowlisted, read-only `github_read.py` boundary for `github-network`, `github-auth`, `github-rate-limit`, and `command-timeout` failures; raw GitHub CLI stderr remains unpersisted and terminal diagnostics may include a safe `failure_reason` enum.
- Distinguish GitHub GraphQL object-resolution failures from DNS errors, and recover an available system CA bundle when Python's default HTTPS trust store is empty.
- Require canonical PR URLs to match a configured GitHub remote and numeric targets to resolve to one distinct configured GitHub repository identity; ambiguous, unsafe, permission, not-found, and unclassified cases remain fail-closed.
- Normalize limited public PR metadata, verify the `refs/pull/<number>/head` detached checkout and local diff, and list unavailable evidence in `online-review-summary.json` while preserving private-PR and open-only merge/remediation constraints.
- Require review/remediation online triage and action evidence to list sorted fallback evidence IDs, add the exact public-fallback confidence gap, and cap final confidence at `0.89`.

## 0.7.0

- Add task-neutral adaptive Codemap routing to the shared structural-context adapter: localized edits can record a zero-query `skip`, one unresolved structural fact selects one compact query, and broad or unknown scope retains the legacy `standard` batch.
- Persist `query_kind` and `artifact_schema_version: 2` while retaining the provider protocol `codemap-py.integration.v1`; add truthful `skipped` status and explicit target normalization rules.
- Keep Codemap optional and persist each decision once so specialist passes consume one artifact without re-querying.

## 0.6.1

- Ground the `kaggle` workflow through the authenticated Kaggle CLI: probe availability and credentials separately from rules acceptance, then read the real file listing, leaderboard range, and sample submission instead of a login-walled competition page.
- Rank CLI evidence above the fetched page for file names, data schema, and submission format while the page stays authoritative for problem narrative and metric definition.
- Suggest user-owned CLI installation and token setup instead of failing when the CLI is absent or unauthorized, and record degraded grounding as a residual limit.
- Fail any run that downloads a full competition or dataset archive without first listing file sizes and asking.

## 0.6.0

- Detect two consecutive work cycles with no material progress and require a ledger rather than subjective model-stall judgments.
- Escalate after three evidence-backed attempts when they still leave one closure condition unmet, so incremental progress cannot conceal an unresolved task.
- Escalate once for higher-capability advice under existing model/authority boundaries, permit one bounded recovery action, then stop for a user decision when progress still does not occur.
- Keep advisory escalation distinct from repeated-obstacle handling: it never resets recurrence counts, bypasses root-cause evidence, transfers acceptance authority, or routes bounded support to Sol.
- Persist and validate the bounded escalation ledger before any post-trigger cycle; reject incomplete state, repeated retries, and unsuccessful recovery without a human handoff.
- Require an observed read-only sandbox and no state changes for advice-only routing; unverified or unavailable routes now hand off directly to the user.
- Calibrate advisory escalation, post-escalation user handoff, user-directed material progress, and advisor-route safety with scored fixture observations.

## 0.5.1

- Classify a refreshed target branch as `advanced` when the PR-recorded base remains its ancestor, then continue reviewing the exact verified PR head; only genuine target divergence remains a collection failure.
- Validate the same ancestry evidence in code-review and PR code-remediation artifacts so target advancement is operational context, never a PR finding or false merge blocker.
- Restore the intended PR evidence hierarchy: retain PR title/body and current-attempt diagnostics, use numbered fork-aware checkout or exact-HEAD reuse, and derive the authoritative review patch from the verified local checkout.
- Degrade unavailable GraphQL review-thread resolution status to explicit empty artifacts plus a confidence gap instead of aborting source review; keep core identity, target, checkout, and local-diff failures terminal.
- Report terminal collection failures as plain process diagnostic/recovery/evidence prose with source findings not assessed and no merge decision; forbid all Markdown tables so integration failures cannot look like PR issues.

## 0.5.0

- Add `shared/github_read.py` as the plugin-wide GitHub data boundary: authenticated `gh` is primary; only audited built-in view groups (`gist`, `issue`, `pr`, `project`, `release`, `repo`, `ruleset`, `run`, `workflow`) are permitted; REST API calls are GET-only; and GraphQL accepts queries but rejects mutations.
- Route PR collection through that shared boundary while retaining `gh pr diff` and local-only `gh pr checkout` for PR workflow completeness.
- Add a last-resort unauthenticated `urllib` GET fallback restricted to public `https://api.github.com/repos/...` resources; it never reads tokens/keychain state and private-only evidence still fails closed.
- Keep GitHub CLI diagnostics credential-opaque: never run `gh auth` or persist CLI stdout/stderr on failure; artifacts retain only command label, failure class, and exit code.
- Clear prior collector evidence and terminal failure markers before each retry so attempts never mix source evidence; keep rate-limit recovery user-timed because opaque artifacts intentionally retain no server interval.
- Report failed PR collection as `PR Review Availability: unavailable`, with no source finding or merge decision, rather than misclassifying an unperformed review as `needs-more-work`.
- Make the unavailable-result writer omit normal recommendations and follow-up fields, preserve conservative `checkout-state.json` evidence when a local checkout command fails, and validate that end-to-end artifact branch.
- Keep assessed merge-review and remediation strictly open-PR-only: an advanced or diverged base remains fail-closed for open PRs, while merged or closed PRs may be collected only as raw diagnostic evidence through GitHub's pull ref, exact SHA verification, and detached local checkout.
- Bound production `gh` command memory use with spooled output buffers, reject oversized responses before exposing them to callers, and keep calibration fixtures aligned with the stricter result and PR-identity contracts.
- Keep Codex Git marketplace add/upgrade as its explicit non-`gh` lifecycle exception because it refreshes the snapshot used to manage local Codex plugins.

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
