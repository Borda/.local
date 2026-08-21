# 🤖 Codex Rig — Native Codex Workflows and Specialist Roles

Codex Rig is the OpenAI Codex product in [Borda's AI-Rig](https://github.com/Borda/AI-Rig). It packages 13 reusable workflow skills, one lifecycle-manager skill, 15 canonical specialist role cards, shared quality gates, calibration, and an optional health hook as one Apache-2.0-licensed plugin.

Calibration measures instruction quality against synthetic cases. It is not evidence that any individual run is correct.

The package covers the capabilities Codex can currently install and verify. It contains no MCP server and no native bundled agent registrations. Parallel work uses a runtime blank agent with the exact role card injected when that route is available; an inline role pass is the serial fallback. Persistent named-agent routing remains platform-blocked until Codex exposes a verifiable custom-agent selector.

> Current release: `0.10.1`. Codex Rig is a peer product to foundry, oss, develop, research, and codemap-py—not a copy of the repository's `.codex/` configuration.

<details open>
<summary><strong>Navigation</strong></summary>

- [What Codex Rig adds](#-what-codex-rig-adds)
- [Requirements and installation](#-requirements)
- [Quick start](#-quick-start)
- [Skills and specialist roles](#-skills)
- [Quality, review, and calibration](#-quality-gates-and-artifacts)
- [Update, uninstall, and safety limits](#-update-or-reinstall)
- [Package layout and verification](#-package-layout)

</details>

> Value at a glance: install one independently verifiable plugin to get evidence-backed workflows, bounded specialist role cards, portable fallbacks, and auditable artifacts without pretending Codex has native persistent-agent selection.

> Current limits at a glance: named-agent shim installation remains platform-blocked; networked workflows require runtime approval; Codex CLI, Python 3.10+, and optional `gh`/Kaggle authentication are needed for their respective paths; shim mutation is unsupported on Windows and network/distributed filesystems.

## 🎯 What Codex Rig adds

- **A complete development loop:** investigate, change-analysis, implement, review, remediate, optimize, release, and audit with measurable gates.
- **Specialist depth without a permanent agent install:** exact packaged role cards can guide independent blank agents or inline passes.
- **Bounded context:** each specialist receives a narrow context pack instead of the whole parent thread.
- **Evidence-backed completion:** workflows write comparable artifacts under `.reports/codex/<skill>/<timestamp>/` and disclose failed gates and confidence limits.
- **Auditable commit handoffs:** every proposed or created commit records all meaningful changes, concrete impacts, executed verification, and residual limits in the commit body.
- **Cold PR review and remediation:** `$code-review #123` and `$code-remediate #123 +review` preserve current PR evidence and local merge context.
- **Scoped network access:** shell networking stays blocked by default; workflows request one runtime approval for the complete command owning each intentional GitHub, Kaggle, marketplace-refresh, or paid live-calibration operation.
- **Calibration:** fixed and behavioral checks measure recall, precision, confidence accuracy, routing leaks, stale assumptions, fixture misuse, unjustified local imports, and incomplete abstractions.
- **Safe legacy cleanup:** authenticated, exact-plan removal exists for thin shims created during pre-release development.
- **Optional codemap-py structural context:** the `implement`, `investigate`, and `optimize` workflows select a task-neutral route and probe the public codemap-py CLI once per run for only the required structural fact, or record a zero-query decision for a localized edit; they persist one artifact and fall back to bounded file inspection when Codemap is absent.

## ✅ Requirements

- Codex CLI with plugin support
- Python 3.10+
- GitHub CLI (`gh`) installed and authenticated for complete PR review, checkout, and private evidence; public metadata fallback remains limited
- Kaggle CLI installed and authenticated for grounded Kaggle workflows; when it is missing, Codex Rig only explains the user-owned setup and never installs it
- Public GitHub access for a Git marketplace install or refresh
- Windows, macOS, or Linux for workflows, package verification, sync, and read-only diagnostics
- A POSIX local filesystem only for authenticated legacy agent-shim cleanup

No official marketplace is assumed. Local, unpushed changes are not installable from GitHub.

Codex Rig never enables persistent workspace network access. In a network-sandboxed runtime, invoking a networked workflow authorizes the plugin to request a narrow runtime approval for the complete owning command; the user/runtime still grants or denies the prompt. Approving only `gh`, `kaggle`, or another nested executable is insufficient when a Python helper owns its subprocesses and HTTPS traffic.

Approval and denial behavior: the brief names the operation's purpose, capability and effects, target, owning command, and denial outcome. If approval is denied, the current tool call stops and the assistant turn may end; the external command is not run, and Codex Rig does not issue an equivalent reprompt or silently broaden the fallback. To continue, send a new message. Separate operations with materially different effects, such as a GitHub read and a local checkout or lifecycle mutation, remain separate approvals.

## 📦 Install from GitHub

```bash
codex plugin marketplace add Borda/AI-Rig
# Optional reproducible release pin:
# codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.4.0
codex plugin add codex-rig@borda-ai-rig
```

The primary command follows the GitHub repository's default branch. The commented form pins immutable release bytes.

Start a fresh Codex session. Codex discovers the plugin's `skills/` and default `hooks/hooks.json`; plugin hooks run only after their current definition is reviewed and trusted.

Verify the install in a fresh session:

```text
$codex-rig:agent-shims doctor
$codex-rig:audit
```

`doctor` verifies the active package, manifest, helpers, role cards, and legacy shim state without writing. The audit workflow checks the consuming repository and reports concrete gaps. Skill/all audits also emit prompt-efficiency evidence: matched instruction cost, loaded-reference cost, obligation preservation, behavioral/calibration guards, and adversarial review. `axis=value-per-token` accepts a candidate only with matched native/tokenizer evidence, no hard-guard regression, and the declared material cost reduction; length or byte count alone cannot establish quality.

## 🌍 Managed global instructions

<details open>
<summary><strong>Global-instruction behavior and sync commands</strong></summary>

`assets/AGENTS.md` is a versioned template, not an automatically installed plugin capability. Its policy requires the following:

- **Implementation:** Use the simplest solution for verified current behavior; prefer maintained standard-library/native/already-installed package functionality over duplicating custom code; reject machinery justified only by hypothetical future states, risks, scale, reuse, or edge cases; and preserve trust-boundary, data-loss, security, accessibility, and explicit-contract safeguards.
- **Abstractions and imports:** Abstractions must reduce reader-visible concepts, and Python imports stay at module scope unless a verified boundary requires locality.
- **Fixtures and simplification:** Fixtures provide concrete state unless fixture-managed lifecycle requires a callable; use ordinary helpers for configurable construction instead of nested fixture factories or aliases that add no meaning. A deliberately bounded simplification records its present ceiling and observable revisit trigger without creating a separate debt system.

The sync paths differ as follows:

| Operation                                        | Explicit behavior                                                                                                                                                       |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Direct marketplace/plugin installation           | Leaves `${CODEX_HOME:-$HOME/.codex}/AGENTS.md` unchanged and does not project repository `.codex/` settings.                                                            |
| Direct `plugins/codex-rig/scripts/sync_codex.py` | Installs or updates the managed Codex plugins and authenticated Codex Rig block only; it does not project repository model defaults or personal policy.                 |
| Root `bash sync.sh` with Codex scope             | Additionally projects the root `model` and `review_model` from `.codex/config.toml` and the authenticated personal-policy block from `.codex/global-session-policy.md`. |

The current repository policy keeps the parent session on Terra and permits Sol only for an explicitly requested advisory pass or explicitly selected Sol agent.

From an AI-Rig checkout:

```bash
bash sync.sh                                      # full Claude + Codex restore
bash sync.sh codex                                # Codex scope only
bash sync.sh codex --no-codex-global-agents       # leave AGENTS.md unchanged; project model defaults
bash sync.sh clear                                # teardown: uninstall plugins + strip block; keep model/policy
bash sync.sh clear codex                          # teardown Codex scope only
```

Native Codex-only restore and teardown need no Bash or `jq`:

```text
python plugins/codex-rig/scripts/sync_codex.py
python plugins/codex-rig/scripts/sync_codex.py --codex-ref codex-rig-v0.4.0
python plugins/codex-rig/scripts/sync_codex.py clear
```

`bash sync.sh claude` changes only Claude scope. Claude sync manages foundry, oss, develop, research, codemap-py, and `bridge`; it refreshes only the retained external caveman plugin. After the bridge installs successfully, sync removes any installed copy of the retired external Codex rescue plugin; a failed bridge install preserves it for recovery. The retired plugin and its marketplace are never installed or refreshed. Codex sync runs the installed Bridge static doctor after installation: it requires the `python` launcher used by MCP to report Python 3.10 or newer and checks the Claude CLI help contract without model inference, authentication changes, or provider cost. MCP inventory and workspace binding remain per fresh Codex project session. `--codex-ref REF` selects a Codex source revision; it does not change product scope. A configured local marketplace is retained and its snapshot is used directly; only configured Git marketplaces are refreshed.

The direct `sync_codex.py clear` action removes the managed Codex plugins and strips only the authenticated Codex Rig block from `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`; it leaves repository-projected model defaults and personal policy untouched. Root `bash sync.sh clear` reverses the selected Claude/Codex installation: it also uninstalls this marketplace's Claude plugins when Claude scope is active, strips the Codex Rig block, and leaves repository model defaults and personal-policy state in place. Both commands keep a timestamped backup and preserve user-owned content byte-for-byte, honor `claude`/`codex` scoping where applicable, and leave marketplace registrations plus external plugins in place. A tampered managed block makes the strip fail without writing, exactly like install.

Codex sync uses the template from the installed marketplace revision. A missing global file is created as one SHA-256-authenticated managed block. Existing user instructions are backed up and preserved byte-for-byte outside that block. An exact unmarked copy from an older sync is adopted without duplication. Later runs update only an unmodified managed block and otherwise fail without writing when markers are missing, duplicated, malformed, or manually changed.

Marketplace/plugin refresh can finish before a later global-instruction merge fails; resolve the reported target state and rerun sync. Avoid concurrent edits during restoration. The installer rechecks observed bytes immediately before atomic replacement, but portable filesystems provide no universal compare-and-swap operation.

Project `AGENTS.md` files remain project-owned and are never changed. Review merged instructions for semantic conflicts; byte preservation cannot resolve contradictory policies.

</details>

## ⚡ Quick start

Skills can be invoked explicitly with `$codex-rig:<skill>` or selected implicitly when the request matches their description.

```text
$codex-rig:investigate find the root cause of this Windows-only CI failure
$codex-rig:implement apply the verified fix and run relevant gates
$codex-rig:code-review review the current diff with no prior assumptions
$codex-rig:code-remediate close the high-severity findings
$codex-rig:release assess release readiness for the current package
```

For PR work:

```text
$codex-rig:code-review #123
$codex-rig:code-remediate #123 +review
```

To remediate the latest assessed review created in the current session without refreshing PR evidence or online comments:

```text
$codex-rig:code-remediate review
```

When the same invocations are passed from a shell, quote them so `$` is not expanded:

```bash
codex '$codex-rig:code-review #123'
codex '$codex-rig:code-remediate #123 +review'
codex '$codex-rig:code-remediate review'
```

## 🔧 Skills

> Skill frontmatter uses compact routing descriptions to conserve the Codex skills catalog; each `SKILL.md` body remains the complete workflow contract.

Codex Rig installs 14 skills: 13 workflows plus the legacy shim manager.

| Skill             | Purpose                                                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| `change-analysis` | Inspect an issue, PR, module, or problem before implementation; emit ranked findings and gates.                     |
| `audit`           | Detect configuration, workflow, routing, documentation, prompt-efficiency, and quality-gate drift.                  |
| `calibrate`       | Run fixed and behavioral checks across packaged skills and roles; score recall, precision, and confidence accuracy. |
| `code-remediate`  | Triage review findings, select valid work, assign owners/verifiers, apply fixes, and prove closure.                 |
| `code-review`     | Close a PR at an evidence-backed proposal gate or review its local diff across mandatory and risk-triggered axes.   |
| `implement`       | Run the linear plan-build-verify implementation loop with measurable acceptance gates.                              |
| `investigate`     | Debug code and narrow unknown failures to an evidence-backed root cause before implementation.                      |
| `kaggle`          | Create or extend grounded Jupytext Kaggle notebooks, grounding schema via the authenticated `kaggle` CLI.           |
| `manage`          | Safely create, update, or remove Codex skills, agent configuration, and related references.                         |
| `optimize`        | Measure first, change one bounded variable, remeasure, and reject regressions.                                      |
| `release`         | Assess SemVer, changelog, migration, packaging, and release readiness.                                              |
| `research`        | Collect current primary evidence and map findings to concrete implementation choices.                               |
| `sync`            | Inspect active plugin-cache drift or refresh the public-GitHub Codex Rig installation without cache edits.          |
| `agent-shims`     | Diagnose and remove authenticated thin shims from pre-release development; new installation stays blocked.          |

Every workflow defines an input contract, fail-fast rules, required gates, artifact shape, and confidence output. Every workflow and the legacy lifecycle helper use one compact outcome-coupled final-chat frame—Outcome, Results, Verification, Remaining, Recommendations / next steps, Confidence, Artifact—with a skill-specific results table when multiple decision units need distinct dispositions; next steps reference those rows instead of repeating them, and artifacts supplement rather than replace the readable result. The workflow instructions live in `skills/<name>/SKILL.md`; shared executable contracts live in `shared/`.

## 🔗 Optional codemap-py structural context

<details>
<summary><strong>Bounded Codemap integration and fallback vocabulary</strong></summary>

`implement`, `investigate`, and `optimize` select a route and probe the [codemap-py](https://github.com/Borda/AI-Rig/tree/main/plugins/codemap-py) plugin once at a bounded decision point via `shared/codemap_adapter.py`, then persist the result to the run artifact — specialists consume that artifact, never a fresh query. An exact localized edit with no unresolved structural fact uses `skip`; one unresolved fact uses the matching single route; broad or unknown scope uses the legacy `standard` batch; an explicit structural request overrides `skip`. The other workflows retain their existing category-specific standard behavior or recorded not-applicable status. The adapter reads only the public `codemap-py doctor --json`/`query` CLI surface, never codemap-py's cache internals, source paths, or a cross-plugin Python import.

The adapter reports one named status: `available`, `absent`, `stale`, `incompatible`, `degraded`, `stale+degraded`, or `skipped`. `skipped` means the workflow deliberately selected zero Codemap subprocesses; it is not structural evidence. `stale+degraded` is the vocabulary's only composed value and means both caveats hold at once, so neither masks the other. A standard batch run without `--target` omits the queries that require one instead of failing them, so a targetless probe reports the honest status of the queries it actually ran. Each query also records the index file that answered it, and any disagreement with the path the health probe resolved is listed under `index_path_divergence` as evidence — both paths retained, never reconciled, and never folded into the status. Absence and incompatibility are non-fatal — the workflow falls back to its normal bounded file inspection. `manage`, `sync`, `agent-shims`, `calibrate`, and `kaggle` stay not-applicable with a recorded behavioral reason (no Python call-graph subject); see `shared/codemap-contract.md` for the full protocol, adaptive route vocabulary, category-to-query map, per-skill route selection, and not-applicable rationale. Repository sync installs Codemap alongside Codex Rig, but Codex Rig retains zero runtime dependency on it: packaging, skill discovery, and startup still work when Codemap is absent or incompatible.

</details>

## 🤖 Specialist role cards

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

## 🔗 How portable role routing works

<details>
<summary><strong>Role-card injection, fallback, and provenance details</strong></summary>

The canonical policy is `shared/specialist-orchestration.md`.

1. The parent determines whether the work actually benefits from an independent specialist.
2. It reads and hashes `roles/<role-id>/ROLE.md`.
3. It builds a narrow context pack: objective, relevant evidence, exclusions, concrete questions, output contract, and stop rule.
4. It asks a runtime-provided blank/default subagent to follow the complete role card before the context pack.
5. If no safe subagent route exists, it performs an inline role pass and reports that independence is false.
6. The parent reconciles outputs, inspects executable evidence, and owns final acceptance.

Passing only a role name or path is not role injection. A task name records provenance only; it does not select a custom profile. Fallback is permitted for route absence or rejection before substantive work, never because a specialist disagreed or found a problem.

For every routed pass, Codex Rig records the role ID, card hash, attempted and selected routes, fallback reason, observable model/effort, requested and observed controls, independence, nesting depth, and material fidelity limits.

</details>

## 💰 Orchestration and cost control

<details>
<summary><strong>Tier ownership and escalation guardrails</strong></summary>

Use delegation only when two or more disjoint workstreams can proceed without duplicating the same context. Typical high-value splits are implementation versus tests, architecture versus migration docs, or CI diagnosis versus static analysis.

- Luna owns bounded coordination, documentation, CI/CD, web evidence, OSS, and linting support.
- Terra owns implementation, runtime behavior, tests, data/ML, performance, curation, challenge, and executable verification.
- Sol is reserved for solution architecture and security.

Select the smallest capable tier from current task evidence: escalate only for a mandatory boundary or observed lower-tier insufficiency, de-escalate only after an evidenced scope split leaves bounded support, and never change tiers on cost alone. The canonical policy is [`shared/specialist-orchestration.md`](https://github.com/Borda/AI-Rig/blob/main/plugins/codex-rig/shared/specialist-orchestration.md#delegation-lead-and-model-routing).

Two consecutive work cycles without material progress, or three evidence-backed attempts that leave the same closure condition unmet, trigger a persisted and validated `reasoning-progress.json` stall ledger and one advisory escalation: a supported higher reasoning effort first, then the next permitted tier. The advisor supplies a bounded recovery action and stop condition but makes no changes; its route is valid only when the observed sandbox is `read-only`. If no safe route exists or that one action still fails to close the condition, Codex Rig stops and asks the user with consolidated evidence, hypotheses, rejected alternatives, and a recommended next step. This guardrail is distinct from, and never resets, the repeated-obstacle policy.

The delegation lead returns one handover. Executable acceptance, runtime/API changes, release-blocking decisions, and security/architecture conclusions remain parent- or appropriate Terra/Sol-owned. Narrow work stays in the parent when handoff cost would exceed its value.

</details>

## 📊 Quality gates and artifacts

<details>
<summary><strong>Artifact shape and confidence thresholds</strong></summary>

Workflow artifacts commonly use this shape; exact files vary by workflow:

```text
.reports/codex/<skill>/<timestamp>/
├── result.json
├── gates.json
├── gates.txt
├── failed.txt
├── gates.checks.jsonl
└── skill-specific evidence
```

The exact files vary by workflow, but completion requires the requested output, explainable gate results, unresolved risks, and a validated `result.json`. Shared helpers provide diff collection, PR evidence collection, gate execution, artifact validation, severity mapping, and result writing.

Confidence is evidence-backed:

- `<= 0.80`: incomplete; continue recovery or report a blocker.
- `0.80 < confidence < 0.85`: very questionable; stronger evidence is required.
- `0.85 <= confidence < 0.90`: cautious-low; objective recovery evidence and remaining limits must be explicit.
- `>= 0.90`: fair, not automatic; material residual limits still belong in the result.

</details>

## 🗺️ PR review-to-remediation

<details>
<summary><strong>Evidence collection, review closure, and remediation boundaries</strong></summary>

- **Review intake:** `$codex-rig:code-review #123` collects contributor intent from the PR title/body, comments/reviews, target-branch evidence, an exact local PR head, and a locally derived diff before producing a structured review artifact. Assessed PR handoffs begin with a snapshot rebuilt from those run artifacts: PR number/link, author, GitHub check status, intent-based type, and the review suggestion.
- **Terminal closure:** After successful collection it may emit an evidence-backed terminal `close` decision before detailed review for one of `FALSE_GOAL`, `BREAKING_CONDUCT`, `WRONG_SCOPE`, `WRONG_PROVENANCE`, `DUPLICATE`, `UNADDRESSED_REVERT`, `SPAM`, or `ARCHITECTURE_VIOLATION`; ambiguous evidence always continues to detailed review, and the decision never closes, comments on, merges, or otherwise mutates GitHub.
- **Review routing:** It performs mandatory QA/challenge passes for broad or high-risk diffs and conditionally triggers architecture, security, CI, docs, data, performance, research, or web evidence when detailed review proceeds. Routing evidence and triggered-role reasons are always non-empty JSON string arrays, so validators can distinguish malformed output from an assessed review.
- **GitHub transport:** `shared/github_read.py` is the sole GitHub data transport: it prefers authenticated `gh` but never reads credentials; permits only audited built-in view groups (`gist`, `issue`, `pr`, `project`, `release`, `repo`, `ruleset`, `run`, `workflow`), REST GET, and GraphQL query operations; and retains no CLI failure output.
- **Approval boundary:** In a network-sandboxed runtime, the complete collector command—not a standalone `gh` preflight—must receive external-network approval because its nested CLI, HTTPS fallback, checkout, and Git fetches inherit the collector's execution context.
- **Retry and denial:** If an agent mistakenly launched that collector without approval and receives a sandbox-shaped `github-network` failure before any user prompt or denial, one unchanged collector retry through the approval mechanism is required before the failure becomes terminal. A user denial always stops the current turn and forbids that retry.- **Evidence tiers:** `collect_pr.py` separates core source evidence from supplemental online evidence: PR identity/body, base-repository identity, target ancestry, exact PR-head checkout, and local diff are mandatory; GraphQL review-thread resolution status and derived statistics may degrade with explicit artifacts and confidence gaps.
- **Checkout and ancestry:** Open fork PRs use `gh pr checkout <number>` unless the current HEAD already exactly matches PR metadata, then `git diff <base>...<head>` supplies the authoritative patch. Target advancement is integration context, not a PR finding or merge blocker; genuine divergence remains a collection failure.
- **Historical and assessed results:** Historical merged/closed PR evidence uses GitHub's pull ref, exact SHA verification, and detached local checkout, but merge decisions and code-remediate remain OPEN-only. Every assessed non-approval PR result includes the findings/action table only for actual findings or review gates.
- **Collection failure:** If core collection fails before source review, report `PR Review Availability: unavailable`, source findings `not assessed`, merge decision `not made`, and plain process diagnostic/recovery/evidence prose; never use a Markdown table, list the operational failure as a PR issue, or emit `needs-more-work`. Current-attempt evidence is retained for diagnosis but remains explicitly unassessed. Authentication recovery remains a user-owned, out-of-band `gh` operation.
- **Fallback eligibility:** Public PR metadata fallback is limited to `github-network`, `github-auth`, `github-rate-limit`, or `command-timeout` failures and requires a canonical URL matching a configured GitHub remote, or a numeric target bound to one distinct configured GitHub repository identity. Ambiguous or unsafe targets, permission, not-found, and unclassified failures fail closed. GitHub GraphQL object-resolution failures remain not-found errors instead of activating the network fallback.
- **Fallback evidence:** The HTTPS client uses Python's default CA store and recovers an available system CA bundle only when that store is empty. The fallback normalizes limited metadata, verifies a `refs/pull/<number>/head` detached checkout, derives the local diff, and records unavailable evidence in `online-review-summary.json`; it cannot establish private PR evidence.
- **Fallback gaps and diagnostics:** Review and remediation list the sorted IDs `github_provided_file_list`, `mergeability`, `review_decision`, `reviews`, and `top_level_comments` in their online triage/action evidence, add the exact gap `Public HTTPS PR metadata fallback omitted evidence: <sorted IDs>.`, and cap final confidence at `0.89`. Raw CLI stderr is never persisted; terminal diagnostics may include a safe `failure_reason` enum.
- **PR refresh:** `$codex-rig:code-remediate #123 +review` finds the newest matching assessed review artifact, refreshes the same core PR/body/checkout/local-diff evidence, records supplemental review-thread coverage gaps, evaluates merge-conflict risk, and presents a resolution table before editing.
- **Current-session reuse:** `$codex-rig:code-remediate review` instead reuses the latest assessed `code-review` result created in the current session in report mode; it does not refresh PR evidence or online comments, and fails if that artifact is unavailable or closed at the proposal gate. A newer close result blocks fallback to stale assessed findings because it contains no source-remediation contract.
- **Prompt ownership:** Selection and parallel-plan context appears in user-visible messages without repeating the interactive question or choices; each control exclusively owns its prompt, and a runtime without controls uses one plain-text prompt instead.
- **Work buckets:** Selected findings form non-overlapping specialist/domain work buckets of at most five items. Five or fewer items stay in one agent scope; larger work uses the fewest coherent buckets, and parallel fan-out occurs only after the user approves the exact displayed plan digest.
- **Plan revision:** A revise response regenerates the plan and requires a fresh `approve` or `parent-only` decision.
- **Validation:** The validator rejects missing/duplicate item coverage, hidden source records, invalid owners or context packs, path-alias or ancestor overlap, excessive bucket size, one-specialist-per-finding fan-out, and approval not bound to the current plan.
- **Recap:** The final recap is rendered from a validated per-item machine ledger and repeats every ingested item in a compact outcome table, including implemented, rejected, skipped/unselected, already-closed, and unresolved dispositions.
- **Duplicate provenance:** Exact duplicate items may share one row only when its `Sources` cell retains every contributing `report|online` source ID, location, complete body, and evidence path; source counts, representative comments, and artifact-only links cannot replace that visible provenance.
- **Remote boundary:** The workflow never pushes, comments, merges, or publishes remotely.
- **Detailed review routing:** The shipped `skills/code-review/review_routing.py` helper derives the mechanical tier and exact file/line evidence from collected diff artifacts before specialist selection; the terminal validator imports the same derivation, so reviewers never calculate or copy those fields manually.
- **Remediation intake:** Assessed non-approval results retain a validator-checked `Review Findings and Merge Blocks` table that becomes the remediation intake contract.

Historical `.reports/codex/review/` and `.reports/codex/resolve/` artifacts remain readable fallback inputs. `code-review` and `code-remediate` are the canonical names.

</details>

## 🎚️ Calibration

<details>
<summary><strong>Offline and live calibration boundaries</strong></summary>

The packaged runner supports the plugin layout directly:

```bash
python3 plugins/codex-rig/runtime/calibration/run.py --layout plugin --root .
```

It validates packaged skills, role cards, shared contracts, behavior fixtures, accepted routing evidence, confidence scoring, and known workflow leaks. The offline CI harness shadows network and LLM commands, uses an isolated home, and writes compact failure artifacts without contacting an LLM.

Paid live A/B calibration is separate, explicit, and never implied by the offline result.

</details>

## 🧾 Approval prompts and commit handoffs

For every intentional approval request, Codex keeps the detailed safety and effects pre-brief separate from the runtime prompt. The prompt reason is a short plain-English question about the outcome or material effect; it never duplicates command syntax, arguments, flags, paths, multiline content, or the full pre-brief. Reusable approval uses only a justified short categorical safe prefix, while one-time or high-risk commands omit the persistent prefix.

Codex-created commit handoffs identify every commit by hash and title, summarize behavior and affected surfaces, list exact verification evidence, disclose residual limits, and explain boundaries between multiple commits. As one application of the approval rule, multiline messages remain complete but stay out of the approval argv: Codex shows the exact message, stores it in a private temporary file outside the worktree, and requests one-time approval for `rtk git commit --cleanup=verbatim -F <file>` without a persistent prefix rule.

## 🩺 Optional SessionStart diagnostic

<details>
<summary><strong>Read-only hook behavior</strong></summary>

`hooks/hooks.json` defines a read-only diagnostic for `startup` and `resume`. Codex discovers this default plugin hook path after install. The hook runs the same shim doctor used by the manager; it does not install, update, or remove shims.

Review the hook command before trusting it. Declining hook trust leaves the diagnostic inactive and does not disable skills.

</details>

## ⬆️ Update or reinstall

Use the bundled `$codex-rig:sync` workflow for a dry-run state report and an approval-gated refresh, or run the supported CLI commands directly:

```bash
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
codex plugin add bridge@borda-ai-rig
```

Then start a fresh Codex session. Plugin reinstall does not update external user-agent files automatically. Use the manager's authenticated `remove` action to clean prior development shims; new installation remains platform-blocked.

Repository sync never restores the legacy `.codex/` tree. When Codex scope is active, root `sync.sh` installs or updates the public Codex plugins and authenticated Codex Rig block, then projects repository model defaults and personal policy as described above. `--no-codex-global-agents` leaves `${CODEX_HOME:-$HOME/.codex}/AGENTS.md` unchanged and skips personal-policy projection while still projecting `model` and `review_model`.

### Legacy project-to-home copies

<details>
<summary><strong>Legacy copy cleanup warning</strong></summary>

Older `sync.sh` versions copied AI-Rig files into `~/.codex/`. The copied files had no durable per-file ownership marker, so Codex Rig does not delete them automatically. Before manual cleanup, back up the home, distinguish AI-Rig copies from user-owned modifications, and remove only files whose ownership you can establish. An old home copy can otherwise expose duplicate unnamespaced skills or stale named-agent registrations beside the plugin.

</details>

## 🧪 Experimental agent shims

<details>
<summary><strong>Shim diagnostics and authenticated cleanup</strong></summary>

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

</details>

## ⬆️ Uninstall

<details>
<summary><strong>Plugin removal and recovery procedure</strong></summary>

Remove authenticated legacy shims while the plugin manager still exists:

1. Run `$codex-rig:agent-shims remove` and approve the exact plan when one exists.
2. If global instructions were installed, back up `$CODEX_HOME/AGENTS.md` and remove only the block between the `codex-rig:global-agents` markers when it is no longer wanted.
3. Run `codex plugin remove codex-rig@borda-ai-rig`.
4. Start a fresh Codex session.

Removing plugin first deliberately leaves thin shim files behind. Those shims break because role cards and the verifier live in the removed plugin cache. They are not auto-deleted.

Recovery: reinstall `codex-rig@borda-ai-rig`, start a fresh session, run `doctor`, then run approved `remove`. Compatible historical state can authenticate guarded cleanup. Verification failure remains blocked; no force cleanup is provided.

</details>

## 🧭 Lifecycle safety limits

<details open>
<summary><strong>Fail-closed mutation limits</strong></summary>

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

</details>

## 🎯 What changed from the idealized design

<details>
<summary><strong>Architecture evidence and remaining platform dependency</strong></summary>

The initial design assumed a plugin could bundle named agents with model, sandbox, approval, and nesting controls. Implementation evidence changed that architecture:

1. **Agents became role cards.** The behavioral instructions remain full-fidelity, versioned product assets, but they are no longer presented as directly installable native agents.
2. **Selection became injection.** Skills load the exact role card and inject it into a runtime blank agent. This preserves parallel specialist reasoning when available without inventing a selector that Codex does not expose.
3. **Inline execution became the mandatory fallback.** When a safe blank-agent route is unavailable, the parent applies the card serially and reports lost independence.
4. **Thin shims became cleanup-only.** The transaction engine can authenticate and remove development shims, but `install` fails closed until runtime selection is observable and testable.
5. **Project configuration left the product.** Models, MCP, and repository runtime defaults belong to user/project configuration. The plugin distributes reusable workflows, roles, hooks, helpers, evidence fixtures, and one inert global-instructions template. Repository sync installs it when Codex scope is active unless explicitly opted out; direct plugin installation alone leaves it inert.
6. **Install identity became immutable.** Released package bytes are tied to a SemVer version and manifest hashes; README or code changes require a new version rather than same-version cache drift.

This design delivers the maintainable part of the original goal today and records the remaining platform dependency honestly. If Codex later exposes custom-agent selection, named shims can be reconsidered behind fresh runtime probes without changing skill or role-card semantics.

</details>

## 🏗️ Package layout

<details open>
<summary><strong>Installed package topology</strong></summary>

```text
codex-rig/
├── .codex-plugin/plugin.json
├── assets/AGENTS.md        # inert global-instructions template
├── skills/                 # 13 workflows + agent-shims lifecycle manager
├── roles/                  # 15 canonical role cards
├── shared/                 # gates, helpers, orchestration, artifact contracts
├── runtime/calibration/    # fixed, behavioral, and live calibration assets
├── hooks/                  # optional read-only SessionStart diagnostic
├── scripts/                # package, role, and shim lifecycle executables
├── tests/                  # package and cross-platform acceptance tests
└── package-manifest.json   # exact packaged file and role-card hashes
```

The installed cache is immutable input. Workflows never edit their own plugin root or manually patch Codex plugin configuration.

</details>

## 🧪 Development and verification

<details open>
<summary><strong>Maintainer verification commands and acceptance gate</strong></summary>

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

### Hardening checks

The denial gate is deterministic and offline: it validates a local JSON Lines transcript, requires one exact `item/commandExecution/requestApproval` callback followed by `decline`, matching resolution and declined completion, rejects output or fallback execution, and requires a later local recovery item. Run its focused tests and inspect the supported probe interface with:

```bash
python3 -m pytest -q plugins/codex-rig/tests/test_app_server_denial_protocol.py
python3 plugins/codex-rig/tests/app_server_denial_probe.py --help
```

The installed-package-safe gate copies only manifest-declared payload into a disposable cache and runs the explicit package-safe test selection without checkout context (`sync.sh`, `.github`, and `.git`). Run it with:

```bash
python3 -m pytest -q plugins/codex-rig/tests/test_installed_package_gate.py
```

> **CI matrix:** The repository CI test matrix runs the complete plugin test suite on Linux, macOS, and Windows with Python 3.10, 3.11, 3.12, and 3.13. The synthetic denial gate and installed-package-safe gate are included in that offline matrix.
>
> **Manual-only boundary:** A live App Server candidate-binding probe is separately authorized and manual; it must not run in CI and does not establish equivalence with the desktop approval UI.
>
> **Live manifest:** Its `--live-matrix` form consumes one local three-entry manifest ordered `text-control`, `skill-control`, and `denial`; all entries must use the same Codex binary, model, plugin version, timeout, and independently recorded SHA-256 digest of `package-manifest.json`, with operator-prepared isolated non-overlapping Codex homes, workdirs, evidence roots, and output paths.
>
> **Isolation and launch:** The probe verifies the full manifest and every declared payload before launch, rejects any candidate or cross-row digest mismatch, and mechanically enforces path isolation; whether a Codex home had prior use remains an operator precondition and is not inferred from directory contents. It stops at the first failure, never accepts the collector command, and never installs or retries.
>
> **Failure artifact:** After each process cleanup attempt, the live probe atomically records either passing evidence or a bounded failing diagnostic containing only allowlisted event names/statuses, run-local identifier aliases, booleans, safe failure codes, sorted schema-owned error categories, the first specific category, whether any retry occurred, and the final retry state. The diagnostic omits commands, paths, prompts, model output, raw identifiers, error payloads, environment values, and credentials; a failing artifact explains the protocol shape but never counts as acceptance.
>
> **Interpretation limit:** A passing skill control proves only that the host completed a turn carrying the installed skill input, not semantic skill loading.

</details>

## 📄 License

Codex Rig is licensed under Apache-2.0. See `LICENSE` and `NOTICE`.
