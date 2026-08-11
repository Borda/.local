# 🤖 Codex Rig — Native Codex Workflows and Specialist Roles

Codex Rig is the OpenAI Codex product in [Borda's AI-Rig](https://github.com/Borda/AI-Rig). It packages 13 reusable workflow skills, one lifecycle-manager skill, 15 canonical specialist role cards, shared quality gates, calibration, and an optional health hook as one Apache-2.0-licensed plugin.

The plugin is complete for the capabilities Codex can currently install and verify. It contains no MCP server and no native bundled agent registrations. Parallel work uses a runtime blank agent with the exact role card injected; an inline role pass is the serial fallback. Persistent named-agent routing remains platform-blocked until Codex exposes a verifiable custom-agent selector.

> Current release: `0.7.0`. Codex Rig is a peer product to foundry, oss, develop, research, and codemap-py—not a copy of the repository's `.codex/` configuration.

## What Codex Rig adds

- **A complete development loop:** investigate, analyse, implement, review, remediate, optimize, release, and audit with measurable gates.
- **Specialist depth without a permanent agent install:** exact packaged role cards can guide independent blank agents or inline passes.
- **Bounded context:** each specialist receives a narrow context pack instead of the whole parent thread.
- **Evidence-backed completion:** workflows write comparable artifacts under `.reports/codex/<skill>/<timestamp>/` and disclose failed gates and confidence limits.
- **Cold PR review and remediation:** `$code-review #123` and `$code-remediate #123 +review` preserve current PR evidence and local merge context.
- **Calibration:** fixed and behavioral checks measure recall, precision, confidence accuracy, routing leaks, and stale assumptions.
- **Safe legacy cleanup:** authenticated, exact-plan removal exists for thin shims created during pre-release development.
- **Optional codemap-py structural context:** the `develop`, `investigate`, and `optimize` workflows select a task-neutral route and probe the public codemap-py CLI once per run for only the required structural fact, or record a zero-query decision for a localized edit; they persist one artifact and fall back to bounded file inspection when Codemap is absent.

## Requirements

- Codex CLI with plugin support
- Python 3.10+
- GitHub CLI (`gh`) installed and authenticated for complete PR review, checkout, and private evidence; public metadata fallback remains limited
- Public GitHub access for install or marketplace refresh
- Windows, macOS, or Linux for workflows, package verification, sync, and read-only diagnostics
- A POSIX local filesystem only for authenticated legacy agent-shim cleanup

No official marketplace is assumed. Local, unpushed changes are not installable from GitHub.

## Install from GitHub

```bash
codex plugin marketplace add Borda/AI-Rig
# Optional reproducible release pin:
# codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.3.0
codex plugin add codex-rig@borda-ai-rig
```

The primary command follows the GitHub repository's default branch. The commented form pins immutable release bytes.

Start a fresh Codex session. Codex discovers the plugin's `skills/` and default `hooks/hooks.json`; plugin hooks run only after their current definition is reviewed and trusted.

Verify the install in a fresh session:

```text
$codex-rig:agent-shims doctor
$codex-rig:audit
```

`doctor` verifies the active package, manifest, helpers, role cards, and legacy shim state without writing. The audit workflow checks the consuming repository and reports concrete gaps.

## Managed global instructions

`assets/AGENTS.md` is a versioned template, not an automatically installed plugin capability. It requires the simplest solution for verified current behavior, prefers maintained standard-library/native/already-installed package functionality over duplicating custom code, rejects machinery justified only by hypothetical future states, risks, scale, reuse, or edge cases, and preserves trust-boundary, data-loss, security, accessibility, and explicit-contract safeguards. A deliberately bounded simplification records its present ceiling and observable revisit trigger without creating a separate debt system. Direct marketplace and plugin installation leaves `${CODEX_HOME:-$HOME/.codex}/AGENTS.md` unchanged. Repository sync installs or updates its managed block by default whenever Codex scope is active.

From an AI-Rig checkout:

```bash
bash sync.sh                                      # full Claude + Codex restore
bash sync.sh codex                                # Codex scope only
bash sync.sh codex --no-codex-global-agents       # skip global guidance
bash sync.sh clear                                # teardown: uninstall plugins + strip managed block
bash sync.sh clear codex                          # teardown Codex scope only
```

Native Codex-only restore and teardown need no Bash or `jq`:

```text
python plugins/codex-rig/scripts/sync_codex.py
python plugins/codex-rig/scripts/sync_codex.py --codex-ref codex-rig-v0.3.0
python plugins/codex-rig/scripts/sync_codex.py clear
```

`bash sync.sh claude` changes only Claude scope. `--codex-ref REF` selects a Codex source revision; it does not change product scope.

`bash sync.sh clear` reverses a sync instead of installing: it uninstalls this marketplace's Claude plugins plus the Codex Rig and Codemap plugins, then strips the managed block from `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`, keeping a timestamped backup and preserving user-owned content byte-for-byte. It honors `claude`/`codex` scoping and leaves marketplace registrations plus external plugins in place. A tampered managed block makes the strip fail without writing, exactly like install.

Codex sync uses the template from the installed marketplace revision. A missing global file is created as one SHA-256-authenticated managed block. Existing user instructions are backed up and preserved byte-for-byte outside that block. An exact unmarked copy from an older sync is adopted without duplication. Later runs update only an unmodified managed block and otherwise fail without writing when markers are missing, duplicated, malformed, or manually changed.

Marketplace/plugin refresh can finish before a later global-instruction merge fails; resolve the reported target state and rerun sync. Avoid concurrent edits during restoration. The installer rechecks observed bytes immediately before atomic replacement, but portable filesystems provide no universal compare-and-swap operation.

Project `AGENTS.md` files remain project-owned and are never changed. Review merged instructions for semantic conflicts; byte preservation cannot resolve contradictory policies.

## Quick start

Skills can be invoked explicitly with `$codex-rig:<skill>` or selected implicitly when the request matches their description.

```text
$codex-rig:investigate find the root cause of this Windows-only CI failure
$codex-rig:develop implement the verified fix and run relevant gates
$codex-rig:code-review review the current diff with no prior assumptions
$codex-rig:code-remediate close the high-severity findings
$codex-rig:release assess release readiness for 0.8.0
```

For PR work:

```text
$codex-rig:code-review #123
$codex-rig:code-remediate #123 +review
```

When the same invocations are passed from a shell, quote them so `$` is not expanded:

```bash
codex '$codex-rig:code-review #123'
codex '$codex-rig:code-remediate #123 +review'
```

## Skills

> Skill frontmatter uses compact routing descriptions to conserve the Codex skills catalog; each `SKILL.md` body remains the complete workflow contract.

Codex Rig installs 14 skills: 13 work workflows plus the legacy shim manager.

| Skill            | Purpose                                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| `analyse`        | Inspect an issue, PR, module, or problem before implementation; emit ranked findings and gates.                     |
| `audit`          | Detect configuration, workflow, routing, documentation, and quality-gate drift.                                     |
| `calibrate`      | Run fixed and behavioral checks across packaged skills and roles; score recall, precision, and confidence accuracy. |
| `code-remediate` | Triage review findings, select valid work, assign owners/verifiers, apply fixes, and prove closure.                 |
| `code-review`    | Review a local diff or GitHub PR across mandatory and risk-triggered specialist axes.                               |
| `develop`        | Run the linear plan-build-verify implementation loop with measurable acceptance gates.                              |
| `investigate`    | Debug code and narrow unknown failures to an evidence-backed root cause before implementation.                      |
| `kaggle`         | Create or extend grounded Jupytext Kaggle notebooks, grounding schema via the authenticated `kaggle` CLI.           |
| `manage`         | Safely create, update, or remove Codex skills, agent configuration, and related references.                         |
| `optimize`       | Measure first, change one bounded variable, remeasure, and reject regressions.                                      |
| `release`        | Assess SemVer, changelog, migration, packaging, and release readiness.                                              |
| `research`       | Collect current primary evidence and map findings to concrete implementation choices.                               |
| `sync`           | Inspect active plugin-cache drift or refresh the public-GitHub Codex Rig installation without cache edits.          |
| `agent-shims`    | Diagnose and remove authenticated thin shims from pre-release development; new installation stays blocked.          |

Every workflow defines an input contract, fail-fast rules, required gates, artifact shape, and confidence output. The workflow instructions live in `skills/<name>/SKILL.md`; shared executable contracts live in `shared/`.

## Optional codemap-py structural context

`develop`, `investigate`, and `optimize` select a route and probe the [codemap-py](https://github.com/Borda/AI-Rig/tree/main/plugins/codemap-py) plugin once at a bounded decision point via `shared/codemap_adapter.py`, then persist the result to the run artifact — specialists consume that artifact, never a fresh query. An exact localized edit with no unresolved structural fact uses `skip`; one unresolved fact uses the matching single route; broad or unknown scope uses the legacy `standard` batch; an explicit structural request overrides `skip`. The other workflows retain their existing category-specific standard behavior or recorded not-applicable status. The adapter reads only the public `codemap-py doctor --json`/`query` CLI surface, never codemap-py's cache internals, source paths, or a cross-plugin Python import.

The adapter reports one named status: `available`, `absent`, `stale`, `incompatible`, `degraded`, or `skipped`. `skipped` means the workflow deliberately selected zero Codemap subprocesses; it is not structural evidence. Absence and incompatibility are non-fatal — the workflow falls back to its normal bounded file inspection. `manage`, `sync`, `agent-shims`, `calibrate`, and `kaggle` stay not-applicable with a recorded behavioral reason (no Python call-graph subject); see `shared/codemap-contract.md` for the full protocol, adaptive route vocabulary, category-to-query map, and not-applicable rationale. Repository sync installs Codemap alongside Codex Rig, but Codex Rig retains zero runtime dependency on it: packaging, skill discovery, and startup still work when Codemap is absent or incompatible.

## Specialist role cards

Roles are canonical behavioral profiles, not claims that Codex selected a custom agent configuration. Each card includes trigger/skip boundaries, evidence ownership, execution constraints, handover fields, and confidence rules.

| Role                 | Requested model | Primary axis                                                                     |
| -------------------- | --------------- | -------------------------------------------------------------------------------- |
| `delegation-lead`    | Luna            | Cost-aware workstream routing and consolidated handover.                         |
| `sw-engineer`        | Terra           | Core implementation, APIs, types, and reproducible Python/ML code.               |
| `qa-specialist`      | Terra           | Regression proof, edge cases, test design, and executable acceptance.            |
| `squeezer`           | Terra           | Profile-first performance, throughput, memory, and synchronization analysis.     |
| `doc-scribe`         | Luna            | User documentation, docstrings, examples, changelogs, and migration guidance.    |
| `security-auditor`   | Sol             | Auth, permissions, secrets, deserialization, supply chain, and trust boundaries. |
| `data-steward`       | Terra           | Dataset integrity, leakage, splits, augmentation, and reproducibility.           |
| `cicd-steward`       | Luna            | CI/CD, matrices, caching, publishing, and flaky-run diagnosis.                   |
| `linting-expert`     | Luna            | Ruff, mypy, pre-commit, suppressions, and static-analysis policy.                |
| `oss-shepherd`       | Luna            | OSS triage, SemVer, deprecations, contributor workflow, and release readiness.   |
| `solution-architect` | Sol             | System design, public contracts, coupling, compatibility, and migrations.        |
| `web-explorer`       | Luna            | Current external documentation, changelogs, and migration evidence.              |
| `curator`            | Terra           | Configuration quality, duplication, drift, stale references, and weak gates.     |
| `challenger`         | Terra           | Adversarial stress tests for plans, risky changes, and no-finding conclusions.   |
| `scientist`          | Terra           | Papers, hypotheses, experimental methods, metrics, and ablations.                |

The model names are requested role settings. Blank-agent injection does not prove the actual model, reasoning effort, sandbox, approval policy, or nesting profile. Workflows must record requested and observed controls and stop when an unproved setting is mandatory for safety.

## How portable role routing works

The canonical policy is `shared/specialist-orchestration.md`.

1. The parent determines whether the work actually benefits from an independent specialist.
2. It reads and hashes `roles/<role-id>/ROLE.md`.
3. It builds a narrow context pack: objective, relevant evidence, exclusions, concrete questions, output contract, and stop rule.
4. It asks a runtime-provided blank/default subagent to follow the complete role card before the context pack.
5. If no safe subagent route exists, it performs an inline role pass and reports that independence is false.
6. The parent reconciles outputs, inspects executable evidence, and owns final acceptance.

Passing only a role name or path is not role injection. A task name records provenance only; it does not select a custom profile. Fallback is permitted for route absence or rejection before substantive work, never because a specialist disagreed or found a problem.

For every routed pass, Codex Rig records the role ID, card hash, attempted and selected routes, fallback reason, observable model/effort, requested and observed controls, independence, nesting depth, and material fidelity limits.

## Orchestration and cost control

Use delegation only when two or more disjoint workstreams can proceed without duplicating the same context. Typical high-value splits are implementation versus tests, architecture versus migration docs, or CI diagnosis versus static analysis.

- Luna owns bounded coordination, documentation, CI/CD, web evidence, OSS, and linting support.
- Terra owns implementation, runtime behavior, tests, data/ML, performance, curation, challenge, and executable verification.
- Sol is reserved for solution architecture and security.

Select the smallest capable tier from current task evidence: escalate only for a mandatory boundary or observed lower-tier insufficiency, de-escalate only after an evidenced scope split leaves bounded support, and never change tiers on cost alone. The canonical policy is [`shared/specialist-orchestration.md`](shared/specialist-orchestration.md#delegation-lead-and-model-routing).

Two consecutive work cycles without material progress, or three evidence-backed attempts that leave the same closure condition unmet, trigger a persisted and validated `reasoning-progress.json` stall ledger and one advisory escalation: a supported higher reasoning effort first, then the next permitted tier. The advisor supplies a bounded recovery action and stop condition but makes no changes; its route is valid only when the observed sandbox is `read-only`. If no safe route exists or that one action still fails to close the condition, Codex Rig stops and asks the user with consolidated evidence, hypotheses, rejected alternatives, and a recommended next step. This guardrail is distinct from, and never resets, the repeated-obstacle policy.

The delegation lead returns one handover. Executable acceptance, runtime/API changes, release-blocking decisions, and security/architecture conclusions remain parent- or appropriate Terra/Sol-owned. Narrow work stays in the parent when handoff cost would exceed its value.

## Quality gates and artifacts

Workflow artifacts use this shape:

```text
.reports/codex/<skill>/<timestamp>/
├── result.json
├── gates.json
├── gates.log
└── skill-specific evidence
```

The exact files vary by workflow, but completion requires the requested output, explainable gate results, unresolved risks, and a validated `result.json`. Shared helpers provide diff collection, PR evidence collection, gate execution, artifact validation, severity mapping, and result writing.

Confidence is evidence-backed:

- `<= 0.80`: incomplete; continue recovery or report a blocker.
- `0.80 < confidence < 0.85`: very questionable; stronger evidence is required.
- `0.85 <= confidence < 0.90`: cautious-low; objective recovery evidence and remaining limits must be explicit.
- `>= 0.90`: fair, not automatic; material residual limits still belong in the result.

## PR review-to-remediation

`$codex-rig:code-review #123` collects contributor intent from the PR title/body, comments/reviews, target-branch evidence, an exact local PR head, and a locally derived diff before producing a structured review artifact. It performs mandatory QA/challenge passes for broad or high-risk diffs and conditionally triggers architecture, security, CI, docs, data, performance, research, or web evidence. `shared/github_read.py` is the sole GitHub data transport: it prefers authenticated `gh` but never reads credentials; permits only audited built-in view groups (`gist`, `issue`, `pr`, `project`, `release`, `repo`, `ruleset`, `run`, `workflow`), REST GET, and GraphQL query operations; and retains no CLI failure output. `collect_pr.py` separates core source evidence from supplemental online evidence: PR identity/body, base-repository identity, target ancestry, exact PR-head checkout, and local diff are mandatory; GraphQL review-thread resolution status and derived statistics may degrade with explicit artifacts and confidence gaps. Open fork PRs use `gh pr checkout <number>` unless the current HEAD already exactly matches PR metadata, then `git diff <base>...<head>` supplies the authoritative patch. Target advancement is integration context, not a PR finding or merge blocker; genuine divergence remains a collection failure. Historical merged/closed PR evidence uses GitHub's pull ref, exact SHA verification, and detached local checkout, but merge decisions and code-remediate remain OPEN-only. Every assessed non-approval PR result includes the findings/action table only for actual findings or review gates. If core collection fails before source review, report `PR Review Availability: unavailable`, source findings `not assessed`, merge decision `not made`, and plain process diagnostic/recovery/evidence prose; never use a Markdown table, list the operational failure as a PR issue, or emit `needs-more-work`. Current-attempt evidence is retained for diagnosis but remains explicitly unassessed. Authentication recovery remains a user-owned, out-of-band `gh` operation.

`$codex-rig:code-remediate #123 +review` finds the newest matching review artifact, refreshes the same core PR/body/checkout/local-diff evidence, records supplemental review-thread coverage gaps, evaluates merge-conflict risk, and presents a resolution table before editing. Selected findings are grouped by root cause and assigned a primary owner, verifier, expected closure evidence, and context pack. The workflow never pushes, comments, merges, or publishes remotely.

Historical `.reports/codex/review/` and `.reports/codex/resolve/` artifacts remain readable fallback inputs. `code-review` and `code-remediate` are the canonical names.

## Calibration

The packaged runner supports the plugin layout directly:

```bash
python3 plugins/codex-rig/runtime/calibration/run.py --layout plugin --root .
```

It validates packaged skills, role cards, shared contracts, behavior fixtures, accepted routing evidence, confidence scoring, and known workflow leaks. The offline CI harness shadows network and LLM commands, uses an isolated home, and writes compact failure artifacts without contacting an LLM.

Paid live A/B calibration is separate, explicit, and never implied by the offline result.

## Commit handoffs

Codex-created commit handoffs identify every commit by hash and title, summarize behavior and affected surfaces, list exact verification evidence, disclose residual limits, and explain boundaries between multiple commits. The Git message remains concise; the user-facing handoff carries the fuller impact and evidence record.

## Optional SessionStart diagnostic

`hooks/hooks.json` defines a read-only diagnostic for `startup` and `resume`. Codex discovers this default plugin hook path after install. The hook runs the same shim doctor used by the manager; it does not install, update, or remove shims.

Review the hook command before trusting it. Declining hook trust leaves the diagnostic inactive and does not disable skills.

## Update or reinstall

Use the bundled `$codex-rig:sync` workflow for a dry-run state report and an approval-gated refresh, or run the supported CLI commands directly:

```bash
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
```

Then start a fresh Codex session. Plugin reinstall does not update external user-agent files automatically. Use the manager's authenticated `remove` action to clean prior development shims; new installation remains platform-blocked.

Repository sync never restores the legacy `.codex/` tree. When Codex scope is active, it installs the public GitHub plugin and manages only the authenticated global-instructions block by default. `--no-codex-global-agents` leaves that file unchanged.

### Legacy project-to-home copies

Older `sync.sh` versions copied AI-Rig files into `~/.codex/`. The copied files had no durable per-file ownership marker, so Codex Rig does not delete them automatically. Before manual cleanup, back up the home, distinguish AI-Rig copies from user-owned modifications, and remove only files whose ownership you can establish. An old home copy can otherwise expose duplicate unnamespaced skills or stale named-agent registrations beside the plugin.

## Experimental agent shims

The manager diagnoses prior development installations and safely removes authenticated standalone TOML files. New installation is platform-blocked because current collaboration tooling does not expose a verifiable custom-agent selector. Do not infer selection from a matching task name, child path, or file name.

Invoke exactly one action:

```text
$codex-rig:agent-shims doctor
$codex-rig:agent-shims status
$codex-rig:agent-shims install
$codex-rig:agent-shims remove
```

- `doctor`: read-only runtime, active-package, manifest, helper, role-card, and filesystem checks.
- `status`: read-only installed-roster, lifecycle-state, target, and recovery summary.
- `install`: report the platform block without creating or relinking files.
- `remove`: plan removal of intact, authenticated Codex Rig shims. No prefix-based cleanup.

`doctor` and `status` are read-only on Windows, macOS, and Linux. Windows verifies package hashes, active selection, executables, and an inventory of exact `codex-rig-*.toml` names; it does not authenticate, adopt, or mutate those files. POSIX additionally validates lifecycle state and permissions. A blocked result names the failed check and required invariant; it does not authorize a repair. The optional SessionStart hook shows the first bounded reason and confirms that no files changed. Do not apply recursive permission changes or delete/link-replace evidence from the diagnostic alone. Existing POSIX `$CODEX_HOME/agents` directories are accepted when they are real current-user directories without group/world write or special permission bits; lifecycle state and recovery directories remain private mode `0700`.

Prior lifecycle files use authenticated names such as `codex-rig-linting-expert.toml`. `remove` prints the exact target root, operations, and SHA-256 approval digest. Review the displayed plan. Type that exact digest only after explicit approval. Wrong or missing digest causes cancellation without authorized writes.

Interrupted recognized transactions use a separate recovery digest. Approved recovery rolls back partial mutation or finalizes durable committed state. Repeat the original action after recovery. Use `remove` to recover prior interrupted transactions; blocked `install` never enters recovery or mutation planning.

## Uninstall

Remove authenticated legacy shims while the plugin manager still exists:

1. Run `$codex-rig:agent-shims remove` and approve the exact plan when one exists.
2. If global instructions were installed, back up `$CODEX_HOME/AGENTS.md` and remove only the block between the `codex-rig:global-agents` markers when it is no longer wanted.
3. Run `codex plugin remove codex-rig@borda-ai-rig`.
4. Start a fresh Codex session.

Removing plugin first deliberately leaves thin shim files behind. Those shims break because role cards and the verifier live in the removed plugin cache. They are not auto-deleted.

Recovery: reinstall `codex-rig@borda-ai-rig`, start a fresh session, run `doctor`, then run approved `remove`. Compatible historical state can authenticate guarded cleanup. Verification failure remains blocked; no force cleanup is provided.

## Lifecycle safety limits

- Foreign or marker-only `codex-rig-*.toml` files are never adopted, overwritten, or removed.
- Modified managed shims, concurrent drift, unsafe links/nodes, ambiguous package selection, or changed runtime binaries block mutation.
- Executable hashing is bounded consistently at 512 MiB across the manager, generator, and verifier; larger files report the selected path, observed size, and limit.
- Missing, malformed, oversized, aliased, or identity-inconsistent lifecycle state blocks cleanup. Manual evidence recovery is required.
- Only one exact recognized interrupted transaction can be recovered. Unknown, conflicting, or multiple residue remains blocked.
- The manager owns only its authenticated roster and state under the current user's Codex home; it never cleans unrelated agents.
- Thin shims require an active compatible plugin cache. Offline cached use may work; update, reinstall, and active-package validation depend on Codex CLI state.
- Hook trust, plugin install, shim install, and shim removal are separate lifecycle decisions.
- Plugin removal does not edit `$CODEX_HOME/AGENTS.md`; a sync-installed managed block remains until explicitly removed.
- A successful shim transaction proves file ownership and link integrity, not runtime profile selection.
- Native Windows and network/distributed filesystems are unsupported for shim mutation. Windows workflows, package verification, sync, hooks, and read-only shim inventory remain supported.

## What changed from the idealized design

The initial design assumed a plugin could bundle named agents with model, sandbox, approval, and nesting controls. Implementation evidence changed that architecture:

1. **Agents became role cards.** The behavioral instructions remain full-fidelity, versioned product assets, but they are no longer presented as directly installable native agents.
2. **Selection became injection.** Skills load the exact role card and inject it into a runtime blank agent. This preserves parallel specialist reasoning when available without inventing a selector that Codex does not expose.
3. **Inline execution became the mandatory fallback.** When a safe blank-agent route is unavailable, the parent applies the card serially and reports lost independence.
4. **Thin shims became cleanup-only.** The transaction engine can authenticate and remove development shims, but `install` fails closed until runtime selection is observable and testable.
5. **Project configuration left the product.** Models, MCP, and repository runtime defaults belong to user/project configuration. The plugin distributes reusable workflows, roles, hooks, helpers, evidence fixtures, and one inert global-instructions template. Repository sync installs it when Codex scope is active unless explicitly opted out; direct plugin installation alone leaves it inert.
6. **Install identity became immutable.** Released package bytes are tied to a SemVer version and manifest hashes; README or code changes require a new version rather than same-version cache drift.

This design delivers the maintainable part of the original goal today and records the remaining platform dependency honestly. If Codex later exposes custom-agent selection, named shims can be reconsidered behind fresh runtime probes without changing skill or role-card semantics.

## Package layout

```text
codex-rig/
├── .codex-plugin/plugin.json
├── assets/AGENTS.md        # inert global-instructions template
├── skills/                 # 14 installable skills
├── roles/                  # 15 canonical role cards
├── shared/                 # gates, helpers, orchestration, artifact contracts
├── runtime/calibration/    # fixed, behavioral, and live calibration assets
├── hooks/                  # optional read-only SessionStart diagnostic
├── scripts/                # package, role, and shim lifecycle executables
├── tests/                  # package and cross-platform acceptance tests
└── package-manifest.json   # exact packaged file and role-card hashes
```

The installed cache is immutable input. Workflows never edit their own plugin root or manually patch Codex plugin configuration.

## Development and verification

From the repository root:

```bash
python3 plugins/codex-rig/scripts/build_package.py --update
python3 plugins/codex-rig/scripts/build_package.py --check
python3 plugins/codex-rig/scripts/validate_package.py
python3 -m pytest -q plugins/codex-rig
NO_MKDOCS_2_WARNING=1 python3 -m mkdocs build --strict
```

On Windows, use `python` in place of `python3`; `build_package.py --check`, package validation, calibration, and tests are native. Authoritative manifest regeneration (`--update`) remains POSIX-only because released mode bits are part of the package contract.

The package is accepted only when the generated manifest is current, every recorded file hash matches, plugin-only copied-tree tests pass, lifecycle safety tests pass, Windows collection and path behavior pass, the offline calibration harness passes, and public documentation builds without warnings.

## License

Codex Rig is licensed under Apache-2.0. See `LICENSE` and `NOTICE`.
