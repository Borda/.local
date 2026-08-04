# Codemap Benchmarks

Empirical validation for the `codemap` plugin. Provider ownership is explicit in every LLM runner name: `claude` and `codex` identify provider-exclusive transport, while `cli`, `generate`, and `provider_parity_contracts` are provider-neutral. The structural benchmark is **repo-agnostic**: swap `tasks-bench.json` (which ships a `repo` header with name, namespace, and default clone path) to run against any Python codebase. Reference results use `pytorch-lightning` pinned at tag `2.6.5` (auto-cloned to `.sandbox/pytorch-lightning`).

## Provider-parity expansion

The committed [methodology manifest](manifests/provider-parity-methodology.json) freezes the canonical task objects, prompts, evaluators, target, and index shared by the Claude and Codex structural studies. The committed [Codex integration manifest](manifests/codex-integration.json) locks Codex to `gpt-5.6-luna` at high reasoning effort and defines the plain, direct-CLI, and installed-Skill treatments. Its [human companion](manifests/codex-integration.md) records the exact review and execution contract. Runtime logs and telemetry remain under ignored `results/` paths.

The completed historical 165-cell paid run remains immutable evidence under the approved 0.28.2 machine manifest SHA-256 `568caefa6cdd1e876e2f35a5e2476d5e661d9672894191c930017f14a29305e4`; its methodology SHA-256 was `3320c2d35e3189d43e3c2336603189083cc7ef8e76ac10dfb2f99ef47ee07afa`. The active prospective relock is separate: methodology SHA-256 `5f613da7ff7c431ff30be9e44a3d9444d1246766a8505e38fc2c6e2908a18112`, machine-manifest SHA-256 `3a69c31a82db95526d8b3e7ab3edf3c9b3a49dd917683413dc43154ddd6f42f8`, and human-manifest SHA-256 `be884757b2e738f3bfe9efba2cf75522b82220fe13fc36dd48d059ba3b7e5086`. It binds Codemap `0.28.3`, the shared evaluator v4, runner metadata v2, and the component-level locked-query telemetry contract. This contract is pending a fresh paid 165-cell rerun and must not supply headline results until that run completes. No historical result is rewritten or pooled with that prospective contract.

Two paid post-fix diagnostic attempts stopped before any model cell: the first on macOS `/var` alias handling during snapshot creation, the second because the intentional `DI-01` stage conflicted with global clean-worktree admission. Both are infrastructure diagnostics, not treatment evidence. The repaired `DiffImpactStageAdmission` records exact Git status, repository commit, and intended-file SHA-256, restores the target in `finally`, and fails closed on unapproved changes or index/commit drift. The subsequent diagnostic completed 54/54 cells across `DI-01`, `DI-05`, `DI-06`, `GR-01`, `GR-03`, and `GR-04`: mean quality was equal at `0.8945` for A/B/C; paired geometric ratios were B/A `0.4465` input, `0.2732` output, `0.3335` elapsed and C/A `0.2849` input, `0.2623` output, `0.2932` elapsed. All 36 B/C cells used Codemap transport, but only 11/36 matched the exact locked query shape. This exposed a measurement bug: exact query-shape mismatch had been incorrectly folded into treatment adherence. The prospective runner now preserves transport adherence and reports `locked_query_conformance` separately, with continuous `locked_query_fitness`, `locked_query_endpoint_fitness`, `locked_query_target_fitness`, and `locked_query_option_fitness`; exact mismatches remain diagnostic counts and do not alone exclude a cell from pooling. Direct and Skill guidance now route production direct callers through `fn-rdeps … --exclude-tests`, transitive callers through `fn-blast`, and production centrality through `central --top N --exclude-tests`.

The provider-neutral library lives in `provider_parity_contracts.py`; it locks task/prompt identity, arm semantics, evaluator dispatch, continuous fitness components, capability strata, headline exclusions, and effort-aware paired construction. It does not generate tasks, run benchmarks, invoke models, or implement provider transport.

The stopped partial artifacts `benchmarks/results/codex-integration-20260802T095824Z` and `benchmarks/results/codex-integration-20260803T191236Z` are audit-only and non-poolable; no treatment effect is inferred from either. The latter persisted 86/165 rows, first failed authentication at `execution_index=50`, and then recorded identical zero-token `401 Unauthorized` failures. Root fixes in the relock include zero-argument `coupled` canonical detection, CQ-03 ranking by internal import count with complete ordered five `name + dep_count` rows, and RV-02 acceptance of natural `N modules directly import/depend` forms.

Final no-model verification is green: the full benchmark suite passed (1,653 passed, 4 skipped), and generated `--check` validation passes. Ruff, targeted Python compilation, Bash syntax, diff, package build/validation, and source/package identity checks pass. Generic plugin-creator validation remains a non-blocking residual because it does not model the existing multi-runtime `codex-skills/` layout; no layout change is proposed.

The historical paid run used shared RV evaluator v6 and remains immutable/non-poolable. Its raw answers contain the correct RV-02 count `64 modules directly import` in all A/B/C rows; v6 failed to extract these natural forms. The relocked evaluator accepts optional `directly` and natural `[unique] [public] symbols [are] uncovered` phrasing; immutable tests preserve RV-05's real `2/5` symbol loss and aggregate score `0.7` with `correct=false`. It does not retroactively rescore historical telemetry.

Claude is the mature, repeatedly debugged reference adapter, but it is not an unquestionable oracle. Provider parity is bidirectional: every unexplained Claude/Codex divergence is investigated as a possible Codex defect, Claude defect, provider/backend limitation, or shared-methodology bug. Only transport, isolation, and provider-native event normalization may legitimately diverge.

**B2 Claude adapter migration.** Both Claude runners now route explicit canonical arms through the shared contracts:

- **`A_plain`** — Codemap is absent and inaccessible.
- **`B_auto`** — Codemap is available; the model may use it, and no-call is valid.
- **`C_required`** — Codemap is available and must be used at least once; no-call is recorded as a separate compliance failure while task scoring remains independent.

Canonical runs load the locked task/prompt/evaluator policy and fail closed unless the target commit/tree, clean worktree, and index bytes/metadata match the manifest; result records carry task, suite, evaluator, envelope, arm-contract, repository, and index provenance. Legacy labels (`plain`, `codemap`, `semble`, `combined`) retain their historical behavior and remain `legacy-unversioned`; they are not retroactively mapped to A/B/C. `--dry-run` prints the selected plan without invoking Claude or writing model results; the real-code runner's default `--arm all` plan is A/B/C and validates the locked inputs, while the agentic runner validates them when a canonical arm is selected.

**Codex structural adapter and active controls.** `run-codex-structural.py` executes structural A/B/C cells through noninteractive `codex exec --json --ephemeral`, retains raw native events, normalizes usage/tool/error/compliance fields, and reuses the exact Claude structural evaluator registry. A has no Codemap access. B receives only a locked direct CLI and must complete at least one compact query. C installs the locked Codemap and Codex Rig packages, reads the exact installed query Skill, and completes at least one compact query. Additional repository reads and shell commands are allowed in B/C but do not replace the required treatment evidence. The Claude and Codex adapters share task loading, prompt materialization, hashes, validators, ground truth, scoring, and pairing; provider-specific code is limited to transport, isolation, and native event normalization.

Each cell receives an isolated `CODEX_HOME`. Permission profiles deny the copied credential, host agent roots, network, and source-tree writes; treatment arms may write only to the index-local coordination directory. The runner records answer, quality, extraction, treatment adherence, Codemap use, locked-query component fitness, and transport failures per cell and continues after the admission smoke so these outcomes remain measurable. Terminal output uses `treatment:✓|✗` for the assigned transport contract and `codemap-used:✓|✗` for observed Codemap use: clean `A_plain` is `treatment:✓ codemap-used:✗`; a contaminated A row can be `treatment:✗ codemap-used:✓`; B/C require the assigned direct or Skill delivery plus a successful compact query. Exact locked-query agreement is independently recorded as `locked_query_conformance`; continuous Jaccard components are `locked_query_fitness`, `locked_query_endpoint_fitness`, `locked_query_target_fitness`, and `locked_query_option_fitness`, so a useful but non-exact query no longer masquerades as failure to receive the treatment.

Existing Claude and exploratory Codex results remain historical evidence and are never pooled with the current study. The confirmatory population has 45 independently scored tasks; ten static-reference or approximate/self-consistency tasks run as diagnostics. Target-dependent ground truth is valid only for PyTorch Lightning tag `2.6.5` at commit `be98784a1a03581b7051a355ae1084fd352d7cea`.

### Entrypoint ownership

| Ownership        | Entrypoint                      | Role                                                                     |
| ---------------- | ------------------------------- | ------------------------------------------------------------------------ |
| Claude only      | `run-claude-structural.py`      | Structural and real-code A/B/C plus legacy Claude arms                   |
| Claude only      | `run-claude-agentic.py`         | Agentic Claude/semble comparison plus canonical Claude arms              |
| Codex only       | `run-codex-structural.py`       | Canonical structural Codex A/B/C transport                               |
| Provider-neutral | `run-all.sh`                    | Safe dispatcher for smoke, Claude, or Codex batch workflows              |
| Provider-neutral | `run-codemap-cli.py`            | Deterministic scan/query correctness and performance; no model           |
| Provider-neutral | `provider_parity_contracts.py`  | Shared task, arm, scoring, provenance, and pairing library; not a runner |
| Provider-neutral | `generate-tasks-bench.py`       | Validates or refreshes shared structural oracle fields                   |
| Provider-neutral | `generate-tasks-real-issues.py` | Refreshes shared real-issue task evidence                                |

Archived manifests retain historical consumer labels from before this rename. Active execution uses only the concise names above; no compatibility launchers remain.

## Benchmark overview

| Benchmark                                                      | Provider         | Script                     | LLM | Arms                       | Tasks                                                                       | Primary question                                                                                      |
| -------------------------------------------------------------- | ---------------- | -------------------------- | --- | -------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [Agentic](#agentic-benchmark-run-claude-agenticpy)             | Claude           | `run-claude-agentic.py`    | Yes | Legacy 4; parity 3 (A/B/C) | 16 import-graph tasks                                                       | Does codemap/semble reduce exploration overhead vs grep?                                              |
| [Structural](#real-codebase-benchmark-run-claude-structuralpy) | Claude           | `run-claude-structural.py` | Yes | Legacy 2; parity 3 (A/B/C) | 60 tasks — 11 series (SE / FN / RV / CQ / BR / DG / FT / RI / DI / GR / MB) | Does scan-query reduce token cost and improve structural recall on pre-implementation research tasks? |
| Provider parity                                                | Codex            | `run-codex-structural.py`  | Yes | Parity 3 (A/B/C)           | Locked structural `tasks-bench.json` tasks                                  | Does Codemap provide an objective within-Codex advantage under the same shared contracts?             |
| [Query](#query-benchmark-run-codemap-clipy)                    | Provider-neutral | `run-codemap-cli.py`       | No  | —                          | Deterministic query/correctness suites                                      | Is scan-query correct, complete, and fast enough?                                                     |

Run **Query** first — validates the index before spending LLM tokens on agentic runs.

## Unified batch entrypoint

`run-all.sh` is the only batch orchestrator. It requires one mode; only `codex` accepts the optional `--dry-run` argument. Missing or unknown arguments do nothing:

```bash
bash benchmarks/run-all.sh smoke
bash benchmarks/run-all.sh claude
bash benchmarks/run-all.sh codex --dry-run
bash benchmarks/run-all.sh codex --tasks=DI,GR --dry-run
CODEX_PAID_APPROVAL="$(shasum -a 256 benchmarks/manifests/codex-integration.json | awk '{print $1}')" \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    CODEX_RUN_DIR="benchmarks/results/codex-integration-$(date -u +%Y%m%dT%H%M%SZ)" \
    CODEX_MAX_WALL_CLOCK_SECONDS=86400 \
    bash benchmarks/run-all.sh codex
```

Modes:

- `smoke` — validate the frozen active index, run the deterministic query check, and execute Claude and Codex dry-run/preflight paths. It invokes no model.
- `claude` — validate the frozen index and preflight, then run the existing paid Claude structural tiers and agentic batch.
- `codex --dry-run` — validate the frozen index, run the deterministic query check and FN-02 Codex smoke, then print the exact 165-coordinate plan. It needs no paid approval, authentication source, or result directory and invokes no model.
- `codex --tasks=DI,GR --dry-run` — resolve the requested families, validate the selected scope, exercise the selected no-model preflight, and print the exact 90-coordinate plan. Selected scopes are targeted and non-poolable; they need no paid approval or authentication source for dry-run.
- `codex` — validate the frozen index, run the fail-fast FN-02 A/B/C smoke and exact no-model plan, then execute the complete 55-task × one-repetition × three-arm study. Cell outcomes are recorded without fail-fast after admission. It fails before setup unless the exact active-manifest SHA-256, a private auth source, a new run directory, and the manifest-locked complete-run ceiling are supplied.
- `codex --tasks=DI,GR` — execute only the selected, non-poolable scope after the same smoke and admission gates. The resolved selection scope SHA-256 is printed and must authorize that scope; the full-run machine-manifest SHA-256 remains the approval for an unselected complete study.

#### Codex task selection

`--tasks=<selector[,selector...]>` is the systematic selector for targeted Codex work; the former asymmetric `--diagnostic` switch is removed from the active interface. Selectors accept exact task IDs or two-letter families, case-insensitively: `--tasks=DI,GR` selects all Diff Impact and Graph Reasoning tasks, while `--tasks=DI-01,GR-03` selects exactly two tasks. Mixed selections are allowed, duplicates are removed, and the locked manifest order is retained. Exact IDs resolve before family expansion, so a selector is deterministic and auditable.

Empty selectors, unknown IDs/families, selectors resolving to no executable task, excluded RI tasks, and invalid mixtures fail before target setup or paid admission. Every selected task runs three repetitions across A/B/C (three arms), with the retry-inclusive 600-second coordinate budget; the selected scope's complete-run ceiling is derived and printed (for `DI,GR`, 90 cells and 54,000 seconds). A selection is explicitly targeted and non-poolable. The resolver prints the selection scope SHA-256 for selected-run approval; the complete unselected study uses the full machine-manifest SHA-256.

For a human-launched run, setting `CODEX_PAID_APPROVAL` to the current machine-manifest SHA-256 in the same command is the paid authorization and stale-manifest safety lock; no separate chat authorization is required. The entrypoint prints a complete launch template whenever paid admission fails.

Credential handling is explicit, not discover-and-search. The security-approved paid-run contract opens only `CODEX_AUTH_SOURCE`, requires a user-owned nonsymlink regular file with mode `0600`, snapshots it into private run-scoped sequential auth state, and atomically propagates the current state into each disposable mode-`0700` Codex home. The source is immutable and drift-checked before each cell; a valid refresh from one cell seeds the next. Cleanup is verified for the run state and every home. Known authentication failures stop immediately; an unknown equivalent zero-token infrastructure failure stops after three matching occurrences, while semantic/model failures remain recorded and continue. Credential bytes, the source path, and standard auth/token/cookie fields are redacted from telemetry and run metadata. Do not run another Codex session concurrently: server-side refresh rotation can invalidate the benchmark state, and the source may require reauthentication after the run. Batch approval, auth-source, result-directory, and wall-clock variables are removed from measured Codex arm environments.

The target is pinned to PyTorch Lightning tag `2.6.5`; the hardcoded ground truth and active manifest reject every other tree. The managed `/private/tmp/codemap-provider-parity-pl-2.6.5` clone is reset to that tag before each mode. `REPO=/path/to/clone` may select an external clone, but the script never resets an override and canonical preflight still requires the locked clean commit and exact frozen-index SHA-256. A missing index is rebuilt and admitted only when normalization of declared environment-specific metadata reproduces the complete locked SHA-256. Every Codex result row records provider, model, effort, task, repetition, arm, telemetry, adherence, Codemap-use, provenance, timing, gross input tokens, cached input tokens, fresh input tokens, output tokens, and limits; `run-metadata.json` is updated after each durable cell. Native Codex input usage is cumulative within a turn, so cached input is a subset of gross input. Gross input is retained for reporting; when `cached_input_tokens <= gross_input_tokens`, fresh input is `gross - cached`; only an inconsistent `cached_input_tokens > gross_input_tokens` row is reported as `?` and token-ineligible.

### Codex result artifacts and ordering

The append-only `telemetry.jsonl` is the execution record. Rows retain `execution_index` and the actual randomized arm order so interrupted runs can be audited without rewriting history. The runner rejects existing raw/metadata artifacts for a new run; partial runs are audit-only and are never resumed, pooled, or re-scored as confirmatory evidence. Before setup, paid `run-all.sh` execution copies itself to a mode-`0500` private launcher under the new run directory and re-executes that snapshot. The runner archives the exact launcher bytes, validates the manifest-bound SHA-256 before and after every cell and at completion, and fails the run if those bytes drift. A successful run also emits `telemetry-canonical.jsonl`, an atomically written derived view sorted by locked task position, repetition, and fixed treatment order. Human labels are `A_plain`, `B_direct`, and `C_skill`; machine telemetry and manifest IDs remain `A_plain`, `B_direct_required`, and `C_skill_required`. Terminal summaries and later paired analysis use the canonical view; raw and canonical files are never pooled or silently substituted. `run-metadata.json` records the canonical artifact status and SHA-256 alongside the raw telemetry hash.

The human result line uses fixed columns and compact units (`k` = 1,000; `M` = 1,000,000). Each top-level smoke, Codex paid, or diagnostic paid section emits exactly one shared terminal legend; nested preflight/study sections do not repeat it. Legends use `A_plain`, `B_direct`, and `C_skill` for plain, direct CLI, and installed Skill. The console reports gross input only; cached and fresh remain raw telemetry fields (`fresh = gross - cached` when consistent). `quality` is continuous fitness in `[0, 1]`; `treatment:✓|✗` answers treatment adherence; `codemap-used:✓|✗` answers observed Codemap use. Codex CLI 0.146.0 exposes no supported per-cell provider prompt-cache reset/disable, so six-permutation counterbalancing mitigates order exposure without claiming cache elimination. Machine telemetry and manifest IDs remain `A_plain`, `B_direct_required`, and `C_skill_required`.

The installed-Skill treatment reads a compact 2,489-byte Skill (reduced from 6,058 bytes) and still performs one exact Skill read followed by one successful canonical query. The direct CLI remains intentionally bare, but top-level CLI help and query help expose valid subcommands and explicit count semantics. `undocumented` distinguishes declaration totals from unique symbols; `uncovered` identifies its static-query coverage semantics. These usability fixes are part of the shared product surface and are tested independently from the paid provider study.

The earlier remediation candidate had deterministic source-transfer proof: its 74-file Codemap package passed package-manifest validation with manifest SHA-256 `fa1a89d86fedc3bc94ce54167378a138065b4a81057ef47007d81bec4adef57f`, and a disposable Codex install/runtime probe passed for the six Codemap skills against schema 12. The active candidate and its exact source/cache Skill hash are recorded in the current integration-study status above. No authentication source was read.

<details>
<summary>Manual equivalent — paste-safe, no inline <code>#</code> comments (interactive zsh does not strip them and passes them as args)</summary>

```bash
cd ~/Workspace/Borda.local
REPO=.sandbox/pytorch-lightning
[ -d "$REPO/.git" ] || git clone --depth 1 --branch 2.6.5 https://github.com/Lightning-AI/pytorch-lightning.git "$REPO"
git -C "$REPO" reset --hard 2.6.5 && git -C "$REPO" clean -fd
CM=plugins/codemap-py/bin/codemap-py

"$CM" index --root "$REPO"
python benchmarks/run-codemap-cli.py --repo-path "$REPO" --report
python benchmarks/run-claude-structural.py --repo-path "$REPO" --run-all --model haiku
python benchmarks/run-claude-structural.py --repo-path "$REPO" --run-all --model sonnet
python benchmarks/run-claude-structural.py --repo-path "$REPO" --run-all --model opus
python benchmarks/run-claude-agentic.py "$REPO" --run-all --report
```

</details>

- **Order**: validate frozen index → query (gates the index, no LLM) → real-codebase → agentic. Per-benchmark options live in each section's **Quick start** below.
- **Scale**: real-codebase = 55 × 2 × 3 = 330 model runs; agentic = 16 × 4 × 3 = 192. ~500+ agent invocations — hours of wall time and real token cost. That is why the script smoke-checks first.
- **Model tiers** (`MODELS` map in each runner): `haiku` → `claude-haiku-4-5`, `sonnet` → `claude-sonnet-5`, `opus` → `claude-opus-5`.
- **Agentic arms**: the `semble` / `combined` arms need the semble MCP configured; without it, add `--arm codemap` to run the structural arm only.
- **Cheaper option**: swap the three bench lines for the tiered strategy (`--tiered`, see [Cost profiles](#cost-profiles)) — full suite on haiku, dev subset on sonnet, only cross-tier disagreements on opus.
- **Results** land in `benchmarks/results/` — `code-<date>.md`, `bench-<model>-<ts>.jsonl`, and agentic JSON (`.md` with `--report`).

## Contents

- [Agentic benchmark](#agentic-benchmark-run-claude-agenticpy) — Claude-only 4-arm import-graph navigation with semble support
- [Real-codebase benchmark](#real-codebase-benchmark-run-claude-structuralpy) — Claude-only structural navigation on pytorch-lightning
- [Query benchmark](#query-benchmark-run-codemap-clipy) — provider-neutral scan-query correctness and latency, no LLM
- [Results](#results)

<details>
<summary><strong>Files</strong></summary>

| File                                         | Ownership        | Purpose                                                                                                                                                           |
| -------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `manifests/provider-parity-methodology.json` | Provider-neutral | Committed shared task, evaluator, target, index, and analysis identities used to regenerate the Codex execution lock                                              |
| `manifests/codex-integration.json`           | Codex            | Machine-enforced plain/direct-CLI/Skill execution contract                                                                                                        |
| `manifests/codex-integration.md`             | Codex            | Human-readable manifest review and paid-run instructions                                                                                                          |
| `provider_parity_contracts.py`               | Provider-neutral | Canonical task identity, A/B/C semantics, evaluator dispatch, headline eligibility, and paired effects; not a runner or generator                                 |
| `run-claude-agentic.py`                      | Claude           | Agentic benchmark measuring how Codemap/semble structural context changes Claude exploration                                                                      |
| `run-claude-structural.py`                   | Claude           | Repo-agnostic structural benchmark driven by the `tasks-bench.json` repository header                                                                             |
| `run-all.sh`                                 | Provider-neutral | Sole batch dispatcher: no-model cross-provider smoke, paid Claude batches, or approval-gated complete Codex structural study                                      |
| `run-codemap-cli.py`                         | Provider-neutral | Query-level correctness, coverage, and latency against a real repository                                                                                          |
| `run-codex-structural.py`                    | Codex            | Codex structural provider-parity transport for canonical A/B/C cells with isolated plugin homes, native telemetry normalization, and shared structural evaluators |
| `generate-tasks-bench.py`                    | Provider-neutral | Validates or refreshes shared structural oracle fields; it does not author prompts                                                                                |
| `generate-tasks-real-issues.py`              | Provider-neutral | Refreshes shared real-issue evidence                                                                                                                              |
| `suites/tasks-agentic.json`                  | Provider-neutral | 16 blast-radius navigation tasks (BA-01–BA-16), 4 difficulty tiers, used by the agentic benchmark                                                                 |
| `suites/tasks-bench.json`                    | Provider-neutral | 60 tasks across 11 series plus the target repository header                                                                                                       |
| `suites/tasks-code.json`                     | Provider-neutral | 15 code-level tasks used by the scan-query benchmark                                                                                                              |
| `suites/tasks-patch.json`                    | Provider-neutral | 5 end-to-end patch tasks requiring patch application and tests                                                                                                    |
| `suites/tasks-readcrop.json`                 | Provider-neutral | 6 symbol-contract extraction tasks scored by keyword recall                                                                                                       |
| `suites/tasks-fix-single.json`               | Provider-neutral | 4 single-file fix tasks scored by diff keyword recall                                                                                                             |
| `suites/tasks-fix-multi.json`                | Provider-neutral | 3 multicaller fix tasks scored by diff keyword and file recall                                                                                                    |
| `results/`                                   | Provider-neutral | JSON snapshots and Markdown reports from past runs                                                                                                                |

</details>

## Agentic benchmark (`run-claude-agentic.py`)

Runs the same 16 import-graph tasks under four arms:

| Arm        | Tools available                                                                           |
| ---------- | ----------------------------------------------------------------------------------------- |
| `plain`    | Grep / Glob / Bash only                                                                   |
| `codemap`  | + `/codemap:query` skill (structural AST index); semble blocked                           |
| `semble`   | + `mcp__semble__search` MCP tool (hybrid semantic + lexical search); Skill + Bash blocked |
| `combined` | Both `/codemap:query` and `mcp__semble__search`; no restrictions                          |

**Prompt symmetry (2026-07-03)**: all four arms share one neutral base prompt — identical task framing, identical "Required answer format" block, and one shared efficiency sentence ("Answer in as few tool calls as possible; do not re-verify results you already have."). Arm supplements carry tool availability + invocation syntax only. Earlier versions steered arms asymmetrically (plain coached toward more grepping; codemap capped at 3 calls and forbidden to verify; semble/combined given prescriptive protocols) — that steering contaminated efficiency metrics, so results produced before this date are not comparable with new runs.

**Ground truth (2026-07-03)**: expected rdeps come from an independent AST scan of the repo (absolute, aliased, `from`-import, and relative forms resolved), not from the codemap index. The index-derived list is kept as a diagnostic; divergence is printed per task as `[gt-divergence] BA-XX: ast=N index=M ...` — a divergence now signals a potential plugin bug instead of being invisible.

**Metrics**: tool call count, elapsed time, input tokens, exposure recall (erec), top-10 exposure recall (e@10), report recall (rrec), discovery efficiency (deff).

| Metric | What it measures                                                                                                                                                                      |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `erec` | Fraction of ground-truth rdeps found in agent output_text (tool results excluded; arm-fair)                                                                                           |
| `e@10` | erec restricted to the 10 most-central rdeps, ranked by reverse-dependency count (in-degree — how many modules import each), matching the "imported by the most modules" task wording |
| `rrec` | Fraction of ground-truth rdeps present in the agent final written answer only                                                                                                         |
| `deff` | Tool calls saved vs plain arm, normalised                                                                                                                                             |

<details>
<summary><strong>Tasks</strong></summary>

16 tasks: 4 types (fix / feature / refactor / review) x 4 difficulty tiers (simple / medium / hard / extreme). Difficulty maps to rdep count: simple 1-4 * medium 5-15 * hard 16-50 * extreme 50+.

| ID    | Type     | Difficulty | Primary module                                              | Scenario                                                                                |
| ----- | -------- | ---------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| BA-01 | fix      | simple     | `lightning.pytorch.callbacks.timer`                         | Timer bug: `timedelta` compared as float, premature training stop                       |
| BA-02 | fix      | medium     | `lightning.pytorch.core.optimizer`                          | LR scheduler fires twice per batch when `optimizer_step` overridden                     |
| BA-03 | fix      | hard       | `lightning.pytorch.utilities.model_helpers`                 | `is_overridden` returns True for inherited methods — silent callback errors             |
| BA-04 | fix      | extreme    | `lightning.pytorch.utilities.exceptions`                    | Rename `MisconfigurationException` to `LightningConfigError` — assess full blast radius |
| BA-05 | feature  | simple     | `lightning.pytorch.callbacks.finetuning`                    | Add `freeze_until_epoch` — scope callers before coding                                  |
| BA-06 | feature  | medium     | `lightning.fabric.utilities.load`                           | Add `map_location` to checkpoint loaders — assess caller integration surface            |
| BA-07 | feature  | extreme    | `lightning.fabric.utilities.rank_zero`                      | Add `group` parameter to rank-zero logging — find dual-importer consistency risk        |
| BA-08 | feature  | extreme    | `lightning.fabric.utilities.types`                          | Add `ReduceOp` protocol, deprecate `torch.distributed.ReduceOp`                         |
| BA-09 | refactor | simple     | `lightning.pytorch.callbacks.lr_finder`                     | Extract `_lr_find` helper into standalone function — classify callers                   |
| BA-10 | refactor | medium     | `lightning.fabric.plugins.environments.cluster_environment` | Rename `creates_processes_externally` — enumerate all call sites                        |
| BA-11 | refactor | hard       | `lightning.fabric.utilities.distributed`                    | Replace barrier wrappers with `DistributedBarrier` context manager                      |
| BA-12 | refactor | hard       | `lightning.pytorch.callbacks`                               | Split `callbacks.__init__` into training/evaluation sub-modules                         |
| BA-13 | review   | simple     | `lightning.pytorch.strategies.deepspeed`                    | PR adds ZeRO-3 CPU offload — verify isolation                                           |
| BA-14 | review   | medium     | `lightning.fabric.plugins.precision.utils`                  | PR makes `_convert_fp_tensor` dtype arg keyword-only — quantify coupling                |
| BA-15 | review   | hard       | `lightning.pytorch.utilities`                               | PR removes 3 deprecated symbols — identify non-migrated callers                         |
| BA-16 | review   | extreme    | `lightning.pytorch.utilities.rank_zero`                     | PR replaces `rank_zero_warn` with deduplicating variant — full risk assessment          |

</details>

### Quick start

```bash
# 1. Install deps (source of truth: pyproject [dependency-groups] bench)
pip install --group pyproject.toml:bench   # or: uv sync --only-group bench

# 2. Build codemap index once (excluded from benchmark timing)
python plugins/codemap-py/bin/scan-index --root /path/to/repo

# 3. Run all tasks, all arms, all model tiers
python benchmarks/run-claude-agentic.py --repo-path /path/to/repo --run-all --report

# 4. Spot-check one task
python benchmarks/run-claude-agentic.py --repo-path /path/to/repo \
    --tasks "['BA-01']" --arm plain --model haiku

# Run only non-semble arms (if semble not configured)
python benchmarks/run-claude-agentic.py --repo-path /path/to/repo --run-all --arm plain
python benchmarks/run-claude-agentic.py --repo-path /path/to/repo --run-all --arm codemap
```

<details>
<summary><strong>Enabling the semble arm (required for semble + combined)</strong></summary>

See [semble docs](https://github.com/MinishLab/semble) for full MCP server documentation. One-time setup:

```bash
claude mcp add semble -s user -- uvx --from "semble[mcp]" semble
```

`-s user` registers it globally (all projects). Use `-s project` to scope to this repo only.

**Verify** — the preflight check in `run-claude-agentic.py` will raise a `RuntimeError` with instructions if semble is not found.

</details>

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                                                                  | Default       | Description                                                              |
| --------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------ |
| `--repo-path PATH`                                                    | required      | Absolute path to the repo under test                                     |
| `--index PATH`                                                        | auto-detected | Override index path (default: `<repo>/.cache/scan/<name>.json`)          |
| `--arm plain\|codemap\|semble\|combined\|A_plain\|B_auto\|C_required` | all four      | Run a single legacy or canonical arm only                                |
| `--model haiku\|sonnet\|opus`                                         | all three     | Run a single model tier only                                             |
| `--tasks "['BA-01','BA-02',...]"`                                     | all 16        | Run specific task IDs (Python list literal — e.g. `"['BA-01','BA-02']"`) |
| `--run-all`                                                           | off           | Run all tasks (required unless `--tasks` given)                          |
| `--report`                                                            | off           | Write markdown report to `results/` after run                            |
| `--dry-run`                                                           | off           | Print the selected plan without invoking Claude or writing model results |

</details>

### Output

Each run prints one coloured line:

```
[NN/TT] BA-01 (fix) | haiku  | codemap  | elapsed= 45.2s | tokens= 120.3k | calls= 3 (grep=  0; glob= 0; bash=  0; skill= 1; semble= 0) | erec= 94% rrec= 88%  sc=100%
```

Colour: yellow = plain · cyan = codemap · blue = semble · green = combined · red = failure.

JSON snapshot written to `results/agentic-YYYY-MM-DD[-N].json` after every run (partial results survive interruptions). Markdown report written to `results/agentic-YYYY-MM-DD[-N].md` with `--report`.

### Failure conditions

| Condition              | Meaning                                                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `timeout`              | claude subprocess exceeded 300 s                                                                                          |
| `non-zero exit`        | claude returned non-success subtype                                                                                       |
| `codemap no-call`      | codemap arm never called the Skill tool                                                                                   |
| `semble no-call`       | semble arm never called `mcp__semble__search` or `mcp__semble__find_related`                                              |
| `degenerate_grep_loop` | codemap arm made zero skill calls but ≥70% of calls were grep/bash-grep — index ignored, fell back to plain-arm behaviour |

______________________________________________________________________

## Real-codebase benchmark (`run-claude-structural.py`)

Measures whether `scan-query` structural access reduces token usage and improves recall on pre-implementation structural research — symbol lookup, call-graph navigation, code review metrics, code quality health checks, and blast-radius assessment before modifying code.

**Benchmark philosophy**: this benchmark measures the *pre-implementation structural research* phase — locating symbols, enumerating callers, assessing blast radius before any code is written. It is not an end-to-end developer workflow benchmark. Tasks have rigid output format constraints (`benchmark_shaped: true`) or qualitative-only ground truth (`scoreable: false`), which determines whether a run contributes to the accuracy denominator. The D-series tasks model a concrete production safety gate: a developer must enumerate ≥70% of a function’s callers before modifying it. Missing 30%+ callers in real code means blind refactoring — broken call sites, silent regressions. The 0.70 threshold exists because that is the practical boundary, not to produce a metric.

Two arms run the same tasks:

| Arm       | Tools available                      |
| --------- | ------------------------------------ |
| `plain`   | Grep / Bash / Glob / Read only       |
| `codemap` | + scan-query (via PATH) + Skill tool |

**Primary metric**: `token_ratio = codemap_input_tokens / plain_input_tokens` per task. Values below 1.0 mean codemap arm used fewer tokens.

**Secondary**: per-arm accuracy — fraction of *scored* tasks where the key metric matches ground truth within tolerance. Incomplete and contaminated runs are excluded from the denominator and reported separately.

### Task series

60 tasks in `tasks-bench.json`, eleven series:

| Series | Type                   | Tasks        | What the agent must find                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------ | ---------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SE     | `symbol_extraction`    | SE-01..SE-05 | Source file line range for a named symbol                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| FN     | `fn_call_graph`        | FN-01..FN-05 | Unique caller count for a function (static call graph)                                                                                                                                                                                                                                                                                                                                                                                                                          |
| RV     | `review_assistance`    | RV-01..RV-05 | Doc-gap counts, rdep counts, coverage gaps for code review                                                                                                                                                                                                                                                                                                                                                                                                                      |
| CQ     | `code_quality`         | CQ-01..CQ-05 | Coupling, broken xrefs, combined doc+coverage health                                                                                                                                                                                                                                                                                                                                                                                                                            |
| BR     | `develop_blast_radius` | BR-01..BR-09 | Caller recall ≥70% before modifying a function; developer workflow framing; calibratable via `/foundry:calibrate`. **n=9** — report accuracy as fractions. BR-06..BR-08 GT = fn-rdeps AST callers. BR-09 is a **high caller-fan-in** stratum member (`fanin_tier: "high"`, `profiles: ["fanin"]`) — `MisconfigurationException`, fan-in 102 (~2.8× the prior BR ceiling of 37); GT = qualified AST caller oracle. Codemap arm uses `scan-query` via Bash PATH (not Skill tool). |
| DG     | `debug_from_trace`     | DG-01..DG-06 | Root-cause function + file from a traceback or log line                                                                                                                                                                                                                                                                                                                                                                                                                         |
| FT     | `feature_scaffolding`  | FT-01..FT-05 | Which files to create or modify for a described new feature                                                                                                                                                                                                                                                                                                                                                                                                                     |
| RI     | `real_issue`           | RI-01..RI-05 | Files relevant to a real GitHub issue (recall ≥ 0.70)                                                                                                                                                                                                                                                                                                                                                                                                                           |
| DI     | `diff_impact`          | DI-01..DI-06 | Blast radius of a *staged* change: production callers (recall ≥ 0.70) + test modules to re-run (recall ≥ 0.70). Runner stages the change around both arms then reverts (refuses on a dirty tree). GT = pre-change AST caller oracle + test-import oracle.                                                                                                                                                                                                                       |
| GR     | `graph_*`              | GR-01..GR-04 | Graph queries: `central` top-N most-imported (set overlap ≥ 0.70), `path` A→B shortest import chain (unique-path pairs only), `fn-blast` depth-2 transitive callers (recall ≥ 0.70). GT = AST central / path / fn-blast oracles.                                                                                                                                                                                                                                                |
| MB     | `module_blast_radius`  | MB-01..MB-05 | Import fan-in: enumerate the modules that IMPORT a target module (its rdeps) — the module-level reverse of BR's per-function callers. Importer recall ≥ 0.70; module names matched by ≥2-component dotted form (never a bare leaf). Fan-in stratum (`profiles: ["fanin"]`) over import hubs. GT = AST importer oracle (`_module_importers_via_ast`), test modules excluded.                                                                                                     |

**SE — Symbol extraction.** Asks the agent to locate where a named symbol is defined and report its start line — the foundation of every "go-to-definition" and "find references" workflow in real development. Plain agents must grep the repo and read candidate files to confirm the match, which burns tokens and still fails when symbol names are ambiguous across modules or appear in strings. A codemap index stores each symbol's qualified name and source range directly, so a single `scan-query symbols` lookup returns the canonical location without reading any source file.

**FN — Function call graph.** Asks the agent to enumerate every unique function that calls a given target — the "who calls me?" question developers ask before refactoring an interface, adding a parameter, or deprecating a function. Plain agents rely on grep-based discovery, which counts raw string occurrences including imports and comments, and silently misses aliased imports and same-file callers. The codemap AST-derived call graph resolves qualified names structurally, producing an exact count unaffected by lexical ambiguity.

**RV — Review assistance.** Asks the agent to answer quantitative code-review questions — how many symbols lack docstrings, how many modules import a given module, how many public symbols have no test coverage — the metrics a reviewer needs to assess whether a change degrades coverage or widens blast radius. Plain agents must read entire module source files and cross-reference test files, a process that scales poorly and produces inconsistent counts due to varying output formats. The `scan-query` subcommands (`undocumented`, `rdeps`, `uncovered`) answer each question with a single structured JSON response containing an exact `count` and the full qualified-name list.

**CQ — Code quality.** Asks the agent to surface structural health metrics used at release gates — the most-coupled module, symbols with broken cross-references in docstrings, combined documentation and coverage deficits. Plain agents must invoke independent file reads for each metric and often miss cases requiring whole-graph reasoning such as transitive coupling. The codemap index exposes `coupled`, `xrefs-broken`, `undocumented`, and `uncovered` subcommands that query pre-built structural graphs and return ranked, quantified results in one call.

**BR — Develop blast radius.** Asks the agent to enumerate all direct callers of a function *before* making a change — the most operationally critical series, since missing callers of a function being refactored ships silent breakage. Plain agents miss aliased callers, same-file callers unreachable by grep, and callers whose import path differs from the module name, requiring dozens of file reads to validate each hit. The codemap `fn-rdeps` subcommand returns the AST-derived caller list directly, reaching high recall without reading a single source file. Recall ≥ 0.70 is a _partial coverage threshold_ — a passing score can still miss up to 30% of direct callers. Do not interpret pass as a production-safety guarantee; for safety-critical refactors, require near-exhaustive enumeration or explicitly bound missed-caller count.

**DI — Diff impact.** Stages a *scripted synthetic change* to a widely-called function (a new keyword-only parameter, a body edit) before the task, then asks the agent to assess the blast radius: which production callers are affected and which test modules must be re-run. The runner applies the change once, runs BOTH arms against the identically-staged tree, and reverts every touched path with `git checkout -- <path>` in a `finally` block — so neither arm sees a different tree and the change never outlives the task. The series refuses to run against a dirty target tree (a `DirtyTreeError`), because reverting a path the user had already modified would silently clobber their edits. Ground truth is the *pre-change* AST caller oracle (`_callers_via_ast`) unioned with the test modules importing the changed module (`_test_modules_importing_via_ast`) — both independent of scan-query. Correctness requires caller recall ≥ 0.70 AND test-file recall ≥ 0.70; the plain arm answers by grep/read over the same staged change. The codemap arm may use `diff-impact` (structural blast radius of the git change set) directly.

**GR — Graph navigation.** Three whole-graph queries a developer runs before a cross-cutting change: `central` (the top-N most-imported modules — where a breaking change hurts most; GT `_central_via_ast`, set overlap ≥ 0.70), `path` (a shortest import chain A→B — how two modules are coupled; GT `_import_path_via_ast`, scored on ordered-chain match, and pairs are chosen where `_shortest_path_is_unique` so the oracle path is the only valid answer), and `fn-blast` (the depth-2 transitive caller closure of a function — the indirect blast radius; GT `_fn_blast_via_ast`, recall ≥ 0.70). Plain agents must build the import graph by hand across dozens of reads; the codemap `central` / `path` / `fn-blast` subcommands answer each from the pre-built graph in one call.

**MB — Module blast radius.** Asks the agent to enumerate every module that IMPORTS a target module — its import fan-in (reverse dependencies). This is the module-level reverse of BR's per-function caller enumeration: before changing a widely-imported hub (an exceptions module, a shared types module), a developer needs the set of modules that would be affected. The five MB tasks target import hubs in `pytorch-lightning` (`utilities.exceptions`, `fabric.utilities.types`, `utilities.rank_zero`, `fabric.utilities.imports`, `trainer.states`), each imported by dozens of production modules. Plain agents must grep every `import`/`from` statement across the tree and dedupe by module, missing re-export aliases and relative imports; the codemap `rdeps` subcommand returns the AST-derived importer list directly. Ground truth is the AST importer oracle (`_module_importers_via_ast`, the reverse of `_central_via_ast`) with test modules excluded; correctness is importer recall ≥ 0.70, and a candidate module counts only via a ≥2-component dotted form (a bare leaf name never scores).

### Quick start

```bash
# 1. Install deps (source of truth: pyproject [dependency-groups] bench)
pip install --group pyproject.toml:bench   # or: uv sync --only-group bench

# 2. Build index once
python plugins/codemap-py/bin/scan-index --root ./<repo-dir>

# 3. Run all 60 tasks, both arms, haiku model
python benchmarks/run-claude-structural.py \
    --repo-path ./<repo-dir> \
    --run-all --model haiku

# 4. Run one series (e.g. symbol tasks only)
python benchmarks/run-claude-structural.py \
    --repo-path ./<repo-dir> \
    --task-type symbol_extraction --arm codemap --model haiku

# 5. Spot-check one task
python benchmarks/run-claude-structural.py \
    --repo-path ./<repo-dir> \
    --tasks "['SE-01']" --arm plain --model haiku
```

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                                                     | Default       | Description                                                                                                                                                                                              |
| -------------------------------------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--repo-path PATH`                                       | auto          | Path to repo clone (default: `repo.local_path` from `tasks-bench.json`)                                                                                                                                  |
| `--index-path PATH`                                      | auto          | Override index; checks `.cache/codemap/` then `.cache/scan/`                                                                                                                                             |
| `--tasks "['SE-01','FN-02',...]"`                        | all           | Run specific task IDs (Python list literal — e.g. `"['SE-01','FN-02']"`)                                                                                                                                 |
| `--task-type TYPE`                                       | all           | Filter by type: `symbol_extraction`, `fn_call_graph`, `review_assistance`, `code_quality`, `develop_blast_radius`, `debug_from_trace`, `feature_scaffolding`, `real_issue`                               |
| `--arm plain\|codemap\|A_plain\|B_auto\|C_required\|all` | `all`         | Run one legacy arm, one canonical A/B/C arm, or both legacy arms                                                                                                                                         |
| `--model haiku\|sonnet\|opus`                            | `haiku`       | Model tier                                                                                                                                                                                               |
| `--run-all`                                              | off           | Required when `--tasks` and `--task-type` both absent                                                                                                                                                    |
| `--no-save`                                              | off           | Skip writing JSONL results to `results/bench-<model>-<ts>.jsonl`                                                                                                                                         |
| `--timeout N`                                            | model default | Per-run wall-clock timeout in seconds                                                                                                                                                                    |
| `--resume`                                               | off           | Reuse a matching prior result (same `task_id`/`arm`/`model` + `repo_sha`/`index_sha`/`task_hash` provenance) from `results/bench-*.jsonl` instead of re-executing it; reused lines carry `resumed: true` |
| `--profile dev\|release`                                 | none          | Cost profile — `dev` = haiku-only stratified subset (fast regression signal), `release` = full matrix incl. RI. Absent → current behavior unchanged                                                      |
| `--tiered`                                               | off           | Tiered protocol (release companion): run one tier per `--model` (haiku full → sonnet dev-subset → opus disagreements). See **Cost profiles** below                                                       |
| `--dry-run`                                              | off           | Validate locked canonical inputs and print the planned A/B/C cells; never invoke Claude or write model results                                                                                           |

When `--resume` is set, provenance is fingerprinted per run: `repo_sha` = `git -C <repo> rev-parse HEAD` (or `"unknown"`), `index_sha` = sha256 of the index head-meta (`scan_version`, `scanned_at`, `git_sha`, `project`, `scan_root`), and `task_hash` = sha256 of the task's canonical JSON. These three fields are written on **every** result line (not only under `--resume`), so any prior run is resumable later. A resume match reuses the stored line verbatim and skips the `claude` subprocess entirely.

</details>

### Output

Per-run line printed during execution:

```
  ✓+ SE-01    codemap tok= 45230 got=      146 exp=      146
  ✓- SE-01    plain   tok= 89410 got=     None exp=      146
```

`✓` = subprocess success · `✗` = failure · `+` = quality correct · `-` = quality wrong · `!` = incomplete (budget exhausted) · `c` = contaminated (plain arm accessed codemap) · `?` = not evaluated.

Summary table printed after all runs:

```
Token ratio (codemap/plain):
  median = 0.37  mean = 1.05
  plain accuracy = 62.5%  (5/8 scored)
  plain incomplete = 1 (budget exhausted — not scored: BR-04)
  codemap accuracy = 87.5%  (7/8 scored)
```

**Interpreting results**: single-run accuracy is a point estimate with high per-task variance (≥5 of 8 tasks can flip between runs at n=1). The direction (codemap vs plain) is stable at n=1; per-task verdicts and magnitudes are not. Run ≥3 times and report mean ± stderr for reliable per-task comparison. Focus on `recall` and `token_ratio`, not the pass/fail threshold alone.

Results written to `results/bench-<model>-<YYYYMMDD-HHMMSS>.jsonl`. Each per-task JSONL record carries `scan_query_subcommands` (per-subcommand call counts, with batched inner `cmd`s attributed to their own counters) and `used_batch: bool` (whether the codemap arm invoked `scan-query batch` at least once — batch use is measured, never forced).

### Cost profiles

The full matrix (60 tasks × 2 arms × 3 model tiers) is expensive. Three cost levers trade coverage for spend; when none are passed the runner behaves exactly as before.

- **dev** (`--profile dev`) — haiku-only, a stratified ~12-task subset with ≥1 task per series (SE/FN/RV/CQ/BR/DG/FT + DI/GR, RI skipped; the MB fan-in stratum is likewise out of the dev subset). Purpose: a fast regression signal that a change did not break the runner or a series. Subset membership is declared per task in `tasks-bench.json` via a `"profiles": ["dev"]` tag, not hardcoded in the runner, so it can be re-stratified without a code change. The dev subset excludes the self-consistency tasks so its accuracy stays clean.

- **release** (`--profile release`) — the full matrix, including the RI (real_issue) series. RI is gated to release (or an explicit `--tasks`/`--task-type` selection) because those runs are ~2M-token outliers — the plain arm greps the whole tree — and would dominate the cost of a routine run.

- **tiered** (`--tiered`, a release companion) — spend opus budget only where it adjudicates. Run one tier per invocation, escalating:

  ```bash
  python benchmarks/run-claude-structural.py --repo-path ./<repo> --tiered --model haiku   # full suite on haiku
  python benchmarks/run-claude-structural.py --repo-path ./<repo> --tiered --model sonnet  # dev subset on sonnet
  python benchmarks/run-claude-structural.py --repo-path ./<repo> --tiered --model opus    # only haiku/sonnet disagreements
  ```

  Each invocation reads the earlier tiers' results from the same `results/` dir (matched on `repo_sha` + `index_sha` provenance). The opus tier runs **only** the tasks where the haiku and sonnet `quality.correct` verdicts disagree — the cases a stronger model is worth paying for. Three separate invocations were chosen over one orchestrated run because it fits the runner's per-model structure and lets each tier's cost be inspected and resumed independently (`--resume`).

**Prompt-cache note.** Within one arm, tasks already execute serially against a stable system prefix (the shared neutral wrapper plus the arm's fixed tool section — identical across all tasks of that arm). A stable, repeated system prefix is exactly what prompt caching prices down, so serial-per-arm execution already benefits from cache pricing without any extra flag; the cost profiles reduce the *number* of runs, not the per-run cache economics.

### Ground truth

`tasks-bench.json` ships with pre-verified ground truth. To validate or refresh against a live index:

```bash
# Validate all tasks (exits 1 on any mismatch)
python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir>

# Validate single task
python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir> --task SE-01

# Refresh AST-oracle-backed ground truth (fn/br/rv; overwrites tasks-bench.json)
python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir> --update --verbose

# Also refresh scan-query-derived fields (cq uncovered/xrefs) — circular; prints warning + oracle diff
python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir> --update --update-from-tool --verbose
```

______________________________________________________________________

## Query benchmark (`run-codemap-cli.py`)

Validates `scan-query` directly — no LLM involved. Requires a pre-built index.

Seven suites run together, split into two tracks. **Primary** suites (C / A / L / Q) decide the verdict. **Self-consistency** suites (S / H / X) validate scan-query against ground truth that is itself partly scan-query-derived — they check determinism, not independent correctness, and are reported separately (excluded from the verdict).

| Suite             | Codes                      | What it measures                                                                                                                                                              |
| ----------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C** Coverage    | C1 C2 C3                   | AST-verified importers codemap finds beyond boundary-anchored grep (real set comparison since 2026-07-03)                                                                     |
| **A** Accuracy    | A1 A2 A3                   | Precision (vs AST-verified importer oracle) + recall floor (vs boundary-anchored grep) on rdeps queries — codemap is not penalized for importers grep cannot see              |
| **L** Latency     | L1 L2 L3 L4                | Wall-clock time for `central`, `rdeps`, index build, vs cold grep baseline                                                                                                    |
| **Q** Query-shape | Q_fix Q_feature Q_refactor | scan-query returns well-formed JSON with the fields develop/oss skills expect (`has_rdeps`+`has_deps`) — shape validation only; does NOT exercise the SKILL.md injection path |
| **S** Symbol      | S_SE-01..SE-05 S2          | `symbol` command returns correct start/end lines (ground truth: `tasks-bench.json`)                                                                                           |
| **H** Health      | H_CQ-\* H1 H2              | `undocumented`/`uncovered` totals match `tasks-bench.json` ground truth                                                                                                       |
| **X** Xrefs       | X_CQ-04 X1                 | `xrefs --broken` count + target set match `tasks-bench.json` ground truth                                                                                                     |

Suites S, H, X auto-skip (no error) when `tasks-bench.json` is absent.

**Deterministic correctness suites (D / B / R / K / U).** In addition to the seven tracks above, `run-codemap-cli.py` runs five deterministic correctness suites, and — unlike S/H/X — they **join the primary verdict**. Each builds a self-contained fixture repo in a tmp dir whose ground truth is KNOWN by construction (an exact importer count, an exactly-corrupted index, a single broken sphinx xref), so a pass is genuine independent-oracle correctness rather than agreement with a scan-query-derived snapshot. They assert the user-visible CLI contract offline (independent of `--repo-path`), and skip cleanly when `scan-index` is absent.

| Suite                 | What it asserts (known-by-construction fixture)                                                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **D** diff-impact     | changed module/symbol detection, risk tiers (HIGH ≥5 importers / MODERATE / LOW), test-impact union, `--base` scoping                                                         |
| **B** batch           | N valid + 1 invalid → exit 0, per-item order, invalid item isolated (`ok:false`), byte-equivalence of a batched result vs its standalone form                                 |
| **R** src_roots       | monorepo multi-root naming + collision winner under a configured root, `src_roots` meta recorded                                                                              |
| **K** self-check      | corrupt index variants (missing key / bad version / wrong type / truncated JSON) → exit 3 + parseable JSON error, never a partial serve                                       |
| **U** uncovered/xrefs | fixture with KNOWN counts (2 undocumented public fns, 1 broken sphinx xref) → exact counts — the deterministic replacement for the LLM bench's circular scan-query-derived GT |

This is the division of labour between the two runners: **deterministic correctness now lives in `run-codemap-cli.py`** (suites D/B/R/K/U, joining its primary verdict), while the **LLM bench (`run-claude-structural.py`) measures workflow efficiency** — token ratio, tool-call economy, and recall on tasks whose ground truth is independent of the index. Because suite U pins the uncovered/xref counts deterministically, the corresponding LLM tasks (`CQ-02` uncovered, `CQ-04` xrefs, `CQ-05` combined-health uncovered part) are **demoted to self-consistency** in the LLM bench: they still run and score, but are excluded from the headline accuracy aggregates (scoring the codemap arm against index-derived truth would measure agreement with itself) and reported in a separate self-consistency row.

### Quick start

```bash
# Run all suites against the target repo (auto-detects index)
python benchmarks/run-codemap-cli.py \
    --repo-path ./<repo-dir> \
    --report

# Explicit index path
python benchmarks/run-codemap-cli.py \
    --repo-path ./<repo-dir> \
    --index-path ./<repo-dir>/.cache/codemap/pytorch-lightning-master.json \
    --report

# Verify task modules exist in index before a full run
python benchmarks/run-codemap-cli.py \
    --repo-path ./<repo-dir> \
    --verify-tasks
```

Index resolution checks `.cache/codemap/<name>.json` first, then `.cache/scan/<name>.json`.

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                | Default | Description                                                                      |
| ------------------- | ------- | -------------------------------------------------------------------------------- |
| `--repo-path PATH`  | auto    | Path to repo clone                                                               |
| `--index-path PATH` | auto    | Override index; checks `.cache/codemap/` then `.cache/scan/`                     |
| `--report`          | off     | Write markdown report to `results/code-YYYY-MM-DD[-N].md`                        |
| `--json-only`       | off     | Emit per-scenario JSONL + summary envelope only; suppress human logs + md report |
| `--verify-tasks`    | off     | Verify task primary_modules exist in index before running                        |

</details>

### Pass thresholds

| Code          | Threshold                                                                                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1            | coverage gap >= 10% — AST-verified importers codemap finds beyond boundary-anchored grep, as fraction of codemap importers (real set comparison since 2026-07-03; was a hardcoded constant) |
| C2            | infeasible path fraction >= 50% — fraction of A→B path queries where A is not a direct importer of B (one boundary grep cannot surface the path; real test since 2026-07-03)                |
| C3            | leverage ratio >= 2.0x                                                                                                                                                                      |
| A1            | precision >= 0.90, recall >= 0.85 (high-risk tasks)                                                                                                                                         |
| A2            | precision = 1.00 (low-risk tasks)                                                                                                                                                           |
| A3            | FP rate < 5%                                                                                                                                                                                |
| L1            | `central` median < 200 ms                                                                                                                                                                   |
| L2            | `rdeps` median < 100 ms                                                                                                                                                                     |
| L3            | amortised index build < 500 ms — build_ms / QUERIES_PER_SESSION (=10); expected to FAIL on large repos under this honest divisor, and the verdict owns that                                 |
| L4            | speedup >= 2x (warm-index vs cold grep; gate is warm-only, a build-inclusive variant is reported alongside for honesty)                                                                     |
| Q_fix/feature | JSON valid block present                                                                                                                                                                    |
| Q_refactor    | JSON valid + has_rdeps + has_deps                                                                                                                                                           |
| S\_\* / S2    | symbol found + start_line within +-3 of ground truth                                                                                                                                        |
| H1 / H2       | undocumented / uncovered total == ground truth (exact)                                                                                                                                      |
| X1            | xrefs --broken count + target set == ground truth (exact)                                                                                                                                   |

**Scoring honesty (2026-07-03)**: a scan-query error (crash / timeout / missing module) now fails its scenario instead of scoring a false precision=1.0. Accuracy precision is judged against an independent AST importer oracle, not raw grep. S/H/X are a self-consistency track and do not count toward the verdict; the primary verdict has genuine room to fail.

______________________________________________________________________

## Benchmark methodology

### Task series

The benchmark covers 60 tasks across 11 series:

| Series           | Type                        | What it measures                                     | Evaluator                                          |
| ---------------- | --------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| **SE** (5 tasks) | Symbol extraction           | Find file + line range of a function/class           | Line-tolerance (±5 lines)                          |
| **FN** (5 tasks) | Call graph count            | How many unique functions call target X              | Name-recall ≥ 0.70 against GT caller list          |
| **BR** (9 tasks) | Blast radius (caller list)  | Which specific functions call target X               | Recall ≥ 0.70 against GT caller list               |
| **RV** (5 tasks) | Review assistance           | Caller count for a function in a code review context | Integer extraction with ±10% tolerance             |
| **CQ** (5 tasks) | Code quality                | Undocumented / uncovered / unhealthy module metrics  | Recall ≥ 0.70 against GT metric                    |
| **DG** (6 tasks) | Debug from trace            | Identify root-cause file + function from traceback   | Recall ≥ 0.70 against GT symbols                   |
| **FT** (5 tasks) | Feature scaffolding         | List files that need editing for a new feature       | Recall ≥ 0.70 against GT file list                 |
| **RI** (5 tasks) | Real GitHub issues          | Locate relevant code for a real issue/PR             | Recall ≥ 0.70 against GT file list                 |
| **DI** (6 tasks) | Diff impact (staged change) | Callers + tests affected by a staged change          | Caller recall ≥ 0.70 AND test-file recall ≥ 0.70   |
| **GR** (4 tasks) | Graph navigation            | Central modules / import path / transitive callers   | Set overlap or recall ≥ 0.70 (path: ordered chain) |

### Two arms

Every task runs twice:

- **plain**: grep, read, bash only — no structural index, no `scan-query`
- **codemap**: same tools + `scan-query` structural index (fn-rdeps, symbol, rdeps, undocumented, uncovered, find-symbol)

Scoring is independent per arm. Token ratio = `codemap_input_tokens / plain_input_tokens` (< 1.0 = codemap cheaper).

### Ground truth establishment

- **Symbol tasks (SE)**: GT from reading source directly (file path + AST line range).
- **Call-graph tasks (FN, BR, RV) — 2026-07-03**: authoritative `fn_callers` GT is validated against an independent AST oracle (`_callers_via_ast` in `generate-tasks-bench.py`); the `scan-query fn-rdeps` result is kept as `fn_callers_scan` diagnostic. Oracle-vs-tool divergence prints a loud warning listing divergent qnames — divergence signals a potential plugin bug and is never auto-overwritten. fn-rdeps `count` == unique deduped callers (the plugin also emits an explicit `unique_caller_count` alias since codemap 0.15.0).
- **Diff-impact / graph tasks (DI, GR)**: ground truth is AST-oracle-only by construction — `_callers_via_ast` + `_test_modules_importing_via_ast` (DI), `_central_via_ast` / `_import_path_via_ast` / `_fn_blast_via_ast` (GR). scan-query is never consulted for their GT (it is the tool the codemap arm invokes). New tasks ship with `gt_pending: true` when the target repo is absent at authoring time; `generate-tasks-bench.py --update` computes and writes their GT deterministically against the target repo and clears the flag. The `path` series requires a *unique* shortest path (`_shortest_path_is_unique`) so the oracle answer is unambiguous.
- **Quality tasks (CQ)**: `CQ-01` undocumented GT uses an independent AST docstring oracle. `CQ-02` uncovered GT uses a documented simple-name AST approximation and is diagnostic. `CQ-03`–`CQ-05` remain self-consistency diagnostics and are excluded from headline correctness.
- **`--update` semantics (2026-07-29)**: default `--update` refreshes independent AST-oracle fields only; scan-query-derived diagnostic fields refresh only behind `--update-from-tool`, which prints a circularity warning and oracle diff before writing. Namespace normalization is applied before comparing or writing qualified names.
- **Residual oracle limits**: `RV-05` and `CQ-02` use an approximate uncovered oracle; RI uses offline/static issue evidence and `RI-05` is unscoreable. SE, FN/BR, RV-01–04, DG/FT, DI/GR, and MB use the independent or source-anchored classifications recorded in the locked provider-parity manifest.

### Known limitations

- **Arm ordering**: plain arm always runs before codemap on each task. Token metrics are unaffected. Wall-clock time metrics may be biased toward codemap (OS page cache warm on second run); treat token ratio as the primary efficiency signal.
- **Equal turn caps (2026-07-03)**: both arms get the same per-task max-turns budget (was plain×4 / codemap×2 per caller, which lowered the codemap/plain token ratio precisely on the highest-caller tasks). The token_ratio headline is now measured under symmetric caps.
- **Paired accuracy (2026-07-03)**: because extraction failures are excluded per-arm, per-arm accuracy is computed over different task subsets. The summary now also prints a paired accuracy — both arms scored over the tasks where BOTH extracted — with the paired-n stated; treat that as the comparable figure.
- **Hardware capture (2026-07-03)**: the query-benchmark report header and JSON envelope record platform / processor / cpu_count / python, since the latency thresholds (L1–L3) are hardware-calibrated and not comparable across machines without it.
- **RV recall > 1.0**: Scores above 1.0 (marked `^` in per-run log) indicate model over-counts, not evaluator error. In June 22 runs RV-03/04 both showed systematic over-count (`^1.1–1.25×`). RV-03 was a task-definition bug — sub-question asked for "fn-rdeps count field" (= 42 total call-site edges) but GT = 37 unique callers; fixed June 23 (prompt now asks for "distinct caller entries"; new runs show RV-03 codemap recall ≈ 1.0). RV-04 remains: `fn-rdeps count: 24` = 24 unique callers = GT, so over-count is pure model error (grep over-counting).
- **NaN in summary table**: A task shows `NaN` recall in the summary table for any of four reasons: (1) `extraction_failed == True` — evaluator regex cannot extract the target metric from model output (most common); (2) `quality.scored == False` — task is marked not scoreable (e.g. RI-05); (3) only one arm ran — no plain+codemap pair to compare; (4) `quality.recall` is None and `metric_got`/`metric_expected` are also None. In June 22 runs (44 tasks): plain arm extraction_failed on SE-05/CQ-01/CQ-05/RI-04 (haiku), FT-03 (sonnet), CQ-01/CQ-05 (opus). Codemap arm extraction_failed on SE-05/CQ-03/CQ-05 (haiku), FN-03 (sonnet), FN-03/RI-02 (opus). Extraction failures are excluded from the accuracy denominator. Count-based tasks (SE / CQ / count-branch RV) show `NaN` in the summary table recall columns; per-task recall is visible in the per-run log line (`recall=…`).
- **RV-02 scored by count (not recall)**: RV-02 asks *how many* modules import `rank_zero` (GT=64). Earlier framing scored it by enumerating all 64 callers — infeasible for one LLM response, so both arms scored low. It is now scored as a count within ±10% (`_int_close`, the same tolerance CQ count-checks use), keeping the task id `RV-02`. The blast-radius *enumeration* workflow it once approximated is now covered properly by the DI series (staged change, caller recall ≥0.70).
- **Opus FN-02 and BR-03 regressions (June 22 — fixed June 23)**: June 22 runs showed FN-02 codemap recall=0.027 and BR-03 codemap recall=0.042. Root causes were two evaluator bugs: (1) missing extraction forms for bold+numbered list output format (Form 9) and file-dump pointer resolution; (2) evaluator version mismatch. Fixed in evaluator v3 (June 23 re-runs: both tasks recall=1.000). See `results/bench-opus-20260623-003745.jsonl`.
- **Haiku RI token spirals (June 22 — fixed June 23)**: June 22 runs: RI-02/RI-04 codemap hit `error_max_turns` consuming 2.6–3.0M tokens. Root cause: `Bash(python3:*)` allowed on codemap arm only — agents spiralled into implement-validate mode writing repro scripts. Fixed by blocking `Bash(python3:*)` and `Bash(python:*)` on both arms. June 23 re-runs: RI-02/RI-04 codemap recall=1.000, 2.0–2.1M tokens. See `results/bench-haiku-20260623-003825.jsonl`.
- **Haiku BR-07 regression**: codemap recall=0.778 vs plain=0.889 (Δ=−0.11). Single instance; monitor for recurrence.
- **FN-series extraction failures**: FN-03 codemap extraction_failed on both sonnet and opus — evaluator cannot parse model output. Plain arm scores 1.000 on both models.
- **Partial filesystem isolation**: `Write`, `Edit`, and `NotebookEdit` are blocked on both arms. Runs where either arm reads benchmark answer files (`tasks-bench`, `benchmarks/results`, `/benchmarks/`) are flagged `answer_file_read` and excluded from scoring — visible in the summary line and JSONL `error` field. Agents can still read arbitrary paths outside the target repo (alternate checkouts, `~/.claude`, etc.); for cleanest runs use a disposable checkout and verify the JSONL tool-use log shows no stray reads.
- **Batch adoption is a signal, not forced**: the codemap arm may use `scan-query batch` (one process, one shared coverage block, a JSON array of `{cmd, args}`) but is never told to. Each run records `used_batch: bool` in the JSONL, and batched inner `cmd`s are attributed to their own subcommand counters (a batched `fn-rdeps` counts as `fn-rdeps`, not as an opaque `batch`) — so whether the model *chooses* batch is part of what is measured.
- **Guard-redundant-scan / avoidance chain not benchmarked here**: the codemap plugin's redundant-scan guard and the grep→scan-query avoidance chain are intentionally out of scope for this task-based benchmark — they are measured on real coding sessions by `/codemap:debrief-coding`'s avoidance join, not on synthetic tasks.

### Scope and out-of-scope

**What this benchmark measures:**

- Token reduction for structural queries (3–10× demonstrated across haiku/sonnet/opus)
- Structural recall on `fn_call_graph` and `develop_blast_radius` tasks
- Symbol lookup accuracy (exact line-range match)
- Code health metric retrieval (`undocumented`, `uncovered`, `xrefs-broken`)

**What this benchmark does NOT yet measure:**

- Test pass rate after fix — `fix_single` / `fix_multicaller` suites score by diff keyword recall and file recall, not compilation or test execution
- Semantic correctness beyond structural keyword matching
- Tasks sampled from real developer activity (issues, PRs, maintenance logs)
- Code quality judgment or review quality beyond structural metrics

`tasks-bench.json` contains 60 tasks across 11 series: structural research (SE / FN / RV / CQ / BR), debug trace analysis (DG), feature scaffolding (FT), real GitHub issues (RI), staged diff-impact (DI), graph queries (GR), and module import fan-in (MB). Core series model the pre-implementation structural research phase; DG/FT/RI cover broader developer workflows; DI/GR/MB add staged-change blast radius, whole-graph navigation, and module-level reverse-import blast radius. No tasks require a code output or a test run — the DI series stages a synthetic change but reverts it after both arms and never asks for a patch.

### Extensions

- **Tier E** (hard): End-to-end patch tasks (`tasks-patch.json`, PT-01–PT-05). Run with `--patch` flag; requires git worktree sandbox + pytest. Pre-fix commits and failing test paths embedded in task file.

### Fix-task benchmark families (agentic benchmark)

Two suite files extend agentic benchmark coverage from pure structural discovery into the **edit phase** of real developer work:

| Family            | Suite                   | Tasks       | Scoring                                             | Daily-work proxy                                                  |
| ----------------- | ----------------------- | ----------- | --------------------------------------------------- | ----------------------------------------------------------------- |
| `fix_single`      | `tasks-fix-single.json` | FS-01–FS-04 | Diff keyword recall (`erec`)                        | Single-file bug fix — validates archive/restore isolation         |
| `fix_multicaller` | `tasks-fix-multi.json`  | FM-01–FM-03 | Diff keyword recall (`erec`) + file recall (`rrec`) | Signature change + callers — codemap's edit-assist differentiator |

**Isolation**: both suites use `requires_reset: true` — per arm run, the benchmark copies the demo codebase to a temp dir, yields the copy to the agent, then captures `diff -ru` against the original. The original codebase is never mutated. No git required.

**FM-03 is the decisive cross-file test**: `Strategy.setup` in pytorch-lightning has 6 subclass overrides across `ddp.py`, `fsdp.py`, `deepspeed.py`, `model_parallel.py`, `single_xla.py`, and `xla.py`. The codemap arm uses `fn-rdeps` to enumerate all overrides before any edit; the plain arm must grep and read files. File recall (`rrec`) captures whether the right files were actually changed. This is the first benchmark family that directly measures whether codemap reduces missed callers in a real multi-file edit.

```bash
# Fix-single (validates archive/restore; single-file; no cross-file index benefit expected)
python benchmarks/run-claude-agentic.py \
    --repo-path /path/to/pytorch-lightning/src/lightning \
    --tasks "[\'FS-01\',\'FS-02\',\'FS-03\',\'FS-04\']" --run-all --model haiku

# Fix-multicaller (the codemap edit-assist test — run plain + codemap, compare rrec on FM-03)
python benchmarks/run-claude-agentic.py \
    --repo-path /path/to/pytorch-lightning/src/lightning \
    --tasks "[\'FM-01\',\'FM-02\',\'FM-03\']" --run-all --model haiku --report
```

**Scoring**: `score_fix()` extracts `+`-prefixed lines from `diff -ru` output, checks keyword hits (`erec`), and checks file recall against `expected_files` (`rrec`). Results flow through the same `QualityScore.erec` / `rrec` columns as the agentic benchmark — no new report rendering required.

## Results

`results/` holds all past run outputs:

| Pattern                                 | Source                                |
| --------------------------------------- | ------------------------------------- |
| `agentic-YYYY-MM-DD[-N].json`           | Agentic benchmark JSON snapshot       |
| `agentic-YYYY-MM-DD[-N].md`             | Agentic benchmark markdown report     |
| `bench-<model>-<YYYYMMDD-HHMMSS>.jsonl` | Real-codebase benchmark JSONL results |
| `code-YYYY-MM-DD[-N].md`                | Query benchmark markdown report       |

### Codex integration study (A/B/C)

The complete Codex run used the same 55 non-RI task objects, prompts, provider-neutral evaluators, target tree, and ground truth as the Claude structural benchmark. It ran one Claude-parity iteration over `A_plain`, `B_direct`, and `C_skill`: 165 cells, with 45 preregistered headline task blocks and 10 diagnostics reported separately.

| Field              | Locked value                                                                                                                                                                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Artifact           | `benchmarks/results/codex-integration-20260803T211755Z` (local, ignored run output)                                                                                                                                                                   |
| Target             | `pytorch-lightning` 2.6.5, commit `be98784a1a03581b7051a355ae1084fd352d7cea`                                                                                                                                                                          |
| Software           | codemap-py 0.28.2, codex-rig 0.4.1, Codex CLI 0.146.0                                                                                                                                                                                                 |
| Model              | `gpt-5.6-luna`, high effort                                                                                                                                                                                                                           |
| Design             | 55 tasks × 1 repetition × 3 treatments = 165 cells; 45 headline blocks + 10 diagnostics                                                                                                                                                               |
| Manifest           | `568caefa6cdd1e876e2f35a5e2476d5e661d9672894191c930017f14a29305e4`                                                                                                                                                                                    |
| Artifact checksums | Raw telemetry `44f0f734bda0f422605041d245442fdbe70115eb575bac976d005d276b381405`; canonical telemetry `0d5d06f730e8a39322781d27a9f82bf58b2e239c25d6bbf2b174a77e0f7e56f5`; metadata `b075e2c05313cfa4f3d186c829e2e5187f64de4092d0343c0362aed53e989831` |

All 165 coordinates completed. All 491 listed artifact checksums verify; planned, raw, and canonical coordinate sets match; every arm followed its treatment; contamination, compliance, extraction, incomplete, token-accounting, and infrastructure failures are zero. A made no Codemap call; B and C made successful compact Codemap calls in all 55 cells; C delivered the exact installed Skill in all 55 cells. The run is pooling-eligible only under its historical 0.28.2 manifest; it cannot satisfy the active prospective 0.28.3 contract.

Headline results use one task block as the paired unit (`n=45`). Ratios are paired geometric means. Intervals use 10,000 paired percentile bootstrap resamples under the manifest-derived deterministic seed; gross input is the locked primary token measure.

| Arm        | Correct | Mean quality | Mean gross input | Mean output | Mean elapsed |
| ---------- | ------: | -----------: | ---------------: | ----------: | -----------: |
| `A_plain`  |   34/45 |       0.8626 |           200.6k |       3,484 |       75.2 s |
| `B_direct` |   42/45 |       0.9673 |           103.6k |       2,094 |       47.9 s |
| `C_skill`  |   40/45 |       0.9525 |            74.0k |       1,420 |       33.2 s |

| Comparison |            Quality delta, 95% CI |  Gross-input ratio, 95% CI |       Output ratio, 95% CI |      Elapsed ratio, 95% CI |
| ---------- | -------------------------------: | -------------------------: | -------------------------: | -------------------------: |
| B/A        |     +0.1047 `[+0.0390, +0.1720]` |     0.735 `[0.580, 0.919]` |     0.775 `[0.596, 0.996]` |     0.800 `[0.644, 0.979]` |
| C/A        | **+0.0900 `[+0.0204, +0.1605]`** | **0.542 `[0.426, 0.681]`** | **0.520 `[0.408, 0.663]`** | **0.558 `[0.452, 0.685]`** |
| C/B        |     -0.0147 `[-0.0522, +0.0169]` | **0.738 `[0.644, 0.847]`** | **0.672 `[0.602, 0.753]`** | **0.698 `[0.636, 0.770]`** |

**Historical judgment.** Under the completed 0.28.2 study contract, C met its then-locked product acceptance policy versus A: gross-input CI upper `<1.00`, quality mean `>=0`, quality CI lower `>-0.02` and also `>0`, with no repeated task-family block below `-0.10`. The installed Skill produced higher structural-answer quality with lower gross input, output, and elapsed time than plain Codex in that run. B also improved over A. C was materially more efficient than B, but the locked C-B quality interval did not establish Skill quality superiority or strict non-inferiority. These findings remain immutable historical evidence; acceptance under the prospective 0.28.3 contract requires the pending fresh 165-cell run.

**Limits.** This is one `gpt-5.6-luna` run per task on one frozen repository. Task-block intervals measure variation across tasks, not rerun stochasticity. Provider cache could not be reset; index-build cost, cross-model/repository generalization, and end-to-end patch/test quality are outside scope.

**Diagnostics.** The 10 manifest-designated diagnostic tasks remain separate. Across all B/C execution cells, 44 successful queries did not exactly match the locked expected tuple; this is not a treatment or pooling failure, and 38/44 mismatch cells were binary-correct. The label currently mixes harmless exact-shape deviations with genuine routing gaps. Future reporting should call it exact locked-query conformance, split endpoint/target/option fitness, teach the Skill production `rdeps ... --exclude-tests` and feature-extension routing, and reconcile provider-neutral locks. The FT evaluator also rejects exact ground-truth entry points followed by the terminal period shown in its own prompt. A punctuation-tolerant post-hoc sensitivity changes mean quality A/B/C to `0.8848/0.9784/0.9859`; this supports robustness but does not replace the frozen score or telemetry.

#### Prospective codemap-py 0.28.3 execution

The fresh 0.28.3 run at `benchmarks/results/codex-integration-20260804T092013Z` completed all 165 cells under machine manifest `3a69c31a82db95526d8b3e7ab3edf3c9b3a49dd917683413dc43154ddd6f42f8`, and all 491 listed checksums verify. It does not replace the clean historical result or satisfy prospective acceptance: `RV-02/A_plain` failed extraction and `DG-02/B_direct` missed required treatment adherence, so run metadata correctly declares the canonical artifact pooling-ineligible for `extraction_failed` and `required_use_missing`. The four extraction failures across all 55 blocks are `RV-02/A_plain`, `RV-05/B_direct`, `CQ-03/A_plain`, and `CQ-04/C_skill`; only `RV-02` is headline-eligible.

Removing the two invalid headline triplets leaves a common descriptive cohort of 43 tasks. This is a sensitivity view, not confirmatory inference. Mean quality A/B/C is `0.8907/0.9850/0.9759`; binary correctness is `35/43`, `41/43`, and `41/43`; arithmetic mean gross input is `179.7k/135.2k/71.0k` tokens; arithmetic mean elapsed time is `81.9/60.5/37.9` seconds.

Gross-input ratios below are computed per task before aggregation. Geometric mean summarizes multiplicative efficiency; p10–p90 and observed min–max describe task heterogeneity, not confidence intervals or rerun variance.

| Comparison | Geometric mean |   Median |        p10–p90 | Observed min–max | Lower-token tasks | Tasks at least 1.5× comparison baseline |
| ---------- | -------------: | -------: | -------------: | ---------------: | ----------------: | --------------------------------------: |
| B/A        |       `0.729×` | `0.815×` | `0.259–1.801×` |   `0.107–2.667×` |     26/43 (60.5%) |                            8/43 (18.6%) |
| C/A        |       `0.493×` | `0.476×` | `0.252–1.194×` |   `0.053–1.317×` |     35/43 (81.4%) |                             0/43 (0.0%) |
| C/B        |       `0.676×` | `0.727×` | `0.365–1.260×` |   `0.108–1.912×` |     35/43 (81.4%) |                             2/43 (4.7%) |

The distribution matters: direct CLI has a substantial upper tail despite its aggregate saving, while the Skill never exceeds 1.5× plain input in the valid headline cohort. The worst B/A case is `BR-01` at `2.667×`; the worst C/A case is `DG-06` at `1.317×`. C can still cost more than B on individual tasks—the worst C/B case is `RV-03` at `1.912×`—so the result supports greater consistency, not a guarantee for every task. Raw telemetry SHA-256 is `def09bc4ee55957752da3e58a52fc309e1c58899e9b75f98a17f0db7b7ba55b8`; canonical telemetry is `575371ba0b4988356bfb16ee02e4222ab974fb0b9cad54235402c943621791ea`; metadata is `88d4ae24a109eba08d3b68acc49854a8cfe7b2819ebcdcde7cd5a82d6803e930`.

<details>

<summary>Historical selected and bounded Codex diagnostics</summary>

The earlier selected Codex runs used the same frozen methodology to locate and repair integration defects. They are descriptive and explicitly non-poolable; they are not mixed with the completed headline result.

| Field              | Locked value                                                                                                                                                                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Artifact           | `benchmarks/results/codex-integration-selected-20260803T091057Z` (local, ignored run output)                                                                                                                                                          |
| Target             | `pytorch-lightning` 2.6.5, commit `be98784a1a03581b7051a355ae1084fd352d7cea`                                                                                                                                                                          |
| Software           | Codemap-py `0.28.2`, codex-rig 0.4.1, Codex CLI 0.146.0.                                                                                                                                                                                              |
| Model              | `gpt-5.6-luna`, high effort                                                                                                                                                                                                                           |
| Design             | `DI-01`, `GR-01`, and `GR-03` × 3 repetitions × 3 treatments = 27 cells; explicitly selected and non-poolable                                                                                                                                         |
| Artifact checksums | Raw telemetry `aebf677437c6b65d04681ea1d67b52030710df44e91b9cad4f9097e8591bed69`; canonical telemetry `15ab38a5fbda643032ee21bdf833b9229fe2e47856caeeffa5e2673ca743e5d3`; metadata `d9d8032fa10795935ae53811729adf50eb5fa82d79ce723b7549249a465bc0c3` |
| Offline rescore    | `offline-rescore-v1-aebf677437c6b65d-cec6f4d18d3f5a6a.json`; SHA-256 `8458e5dc58957453fd3ba94507d27c8f2b1a8e9cdb4d6f2b5b205bd74b400e34`; derived SHA-256 `e9cca34f35da0672716bf12a6dd0fdd22e1d3158509856203d16cb93a2a1d987`                           |

Offline-derived selected diagnostics (continuous quality is the mean per-cell fitness; input and elapsed values are arithmetic means):

| Treatment  | Correctness by family                 | Quality by family                           | Gross input   | Elapsed       | Adherence |
| ---------- | ------------------------------------- | ------------------------------------------- | ------------- | ------------- | --------- |
| `A_plain`  | DI-01 `0/3`, GR-01 `3/3`, GR-03 `3/3` | DI-01 `0.367`, GR-01 `0.767`, GR-03 `1.000` | see telemetry | see telemetry | 9/9       |
| `B_direct` | DI-01 `0/3`, GR-01 `3/3`, GR-03 `3/3` | DI-01 `0.500`, GR-01 `0.700`, GR-03 `1.000` | see telemetry | see telemetry | 9/9       |
| `C_skill`  | DI-01 `0/3`, GR-01 `3/3`, GR-03 `3/3` | DI-01 `0.333`, GR-01 `0.700`, GR-03 `1.000` | see telemetry | see telemetry | 9/9       |

No pooled interval or treatment-effect estimate is reported for this selected scope: it is targeted, non-poolable diagnostic evidence with only three task families. Gross-input and elapsed comparisons remain available in the immutable telemetry for audit, but are not a headline result.

**Validity and interpretation.** All 27 selected cells completed and passed artifact integrity, but the run is explicitly non-poolable. The offline replay classifies all 27 cells as treatment-adherent and reports seven semantic query-shape misses: C `DI-01` (3), B `DI-01` (1), and B `GR-01` (3). `DI-01` binary correctness is 0/3 for each arm because the returned test-module identity did not match the locked oracle; `GR-01` is 3/3 for each arm and `GR-03` is 3/3 for each arm. These targeted results do not establish a causal Codemap advantage, confirmatory effect, or cross-provider raw-token comparison. The offline replay is diagnostic derived evidence only; the raw and canonical telemetry remain immutable and no active acceptance claim depends on the replay.

The selected run confirms the repaired parser and evaluator plumbing but also keeps the remaining query-shape mismatch visible. Root fixes now include unquoted `$CODEMAP_BIN` parsing, preserved Markdown message boundaries, provider-neutral DiffImpact caller-and-test precision/recall F1, scanner normalization to `tests_fabric...`, production-only `central --exclude-tests` in-degree, direct `fn-rdeps` versus explicit transitive `fn-blast` guidance, and fail-closed offline rescore.

The follow-up 18-cell validation at `benchmarks/results/codex-integration-selected-20260803T160316Z` completed all coordinates with zero treatment, contamination, extraction, completeness, or token-accounting failures; all 491 checksums verify. Raw/canonical/metadata SHA-256 values are `26535b20a9e2511df30a3277e0364128c4d96ff6254d2f031c07fa62e21a5705`, `c240dd4e366028149cb8530efd37295bcedd1fe4af3d911ae8bbd309a20e289e`, and `bd8cd8ed0eeac3ed79e874fd97486cc219c937300441ca57fb2edfe645235da6`.

| Task    | A quality | B quality | C quality | B/A input · elapsed | C/A input · elapsed |
| ------- | --------: | --------: | --------: | ------------------: | ------------------: |
| `DI-01` |   `0.500` |   `1.000` |   `0.501` | `1.603×` · `0.909×` | `1.008×` · `0.989×` |
| `GR-01` |   `0.733` |   `0.600` |   `1.000` | `0.282×` · `0.136×` | `0.197×` · `0.089×` |

These are paired geometric economy ratios and arithmetic mean quality over three repetitions. They are descriptive because the scope is targeted and non-poolable. C achieved quality parity on DI and improved GR while using much less input overall, but DI showed no stable input saving and B degraded on GR. Raw events establish deterministic causes: the GR prompt omitted the oracle's exclude-tests scope, while the Skill mapped DI's direct-import test request to transitive module `test-impact` and returned 247 tests. The semantic audit also checked only the caller half of DI. The shared task prompt now states production-only centrality; all DI tasks require exact caller and direct-importer queries; both runtime Skills reserve `test-impact` for transitive affected-test selection. A new bounded validation is required before the full study can be unlocked.

The corrected bounded gate at `benchmarks/results/codex-integration-selected-20260803T172707Z` completed 18/18 cells and verified all 491 checksums under the current manifest and selected-scope locks. Raw/canonical/metadata SHA-256 values are `1b20bb6756d9e301215b20cbc6bd90b01c6798667ee2be7a261be819604e8c77`, `2c810e840f2f9f03c6b8bd2a976f13c12df1a4cee3e46051b255add7dff106cf`, and `d6f4e0a71a52cb05d849a10d7635e3b4579f13c570694cf871e2574ccfd0c8b4`.

| Task    | A quality | B quality | C quality |   B/A input · output · elapsed |   C/A input · output · elapsed |
| ------- | --------: | --------: | --------: | -----------------------------: | -----------------------------: |
| `DI-01` |   `0.500` |   `1.000` |   `1.000` | `0.842×` · `0.704×` · `0.826×` | `0.627×` · `0.494×` · `0.555×` |
| `GR-01` |   `0.800` |   `1.000` |   `1.000` | `0.356×` · `0.113×` · `0.300×` | `0.251×` · `0.081×` · `0.169×` |

The run has zero treatment, contamination, extraction, completeness, token-accounting, or execution failures. Its three semantic-query misses are all DI-01/B_direct: the direct model omitted one or both exact locked query components but still used Codemap and returned every expected caller and test module. C_skill matched the exact caller-plus-direct-import route in every repetition. The methodology records exact query fitness independently from treatment delivery, so the misses remain discoverability diagnostics rather than exclusion failures. The bounded operational gate passes and permits the separately authorized complete 165-cell study; this targeted run remains non-poolable and cannot satisfy confirmatory product acceptance.

The Claude adapter remains the repeatedly debugged reference; only shared methodology corrections apply to both providers, and no Claude quality change is implied by this Codex recovery work.

The run is retained for audit and follow-up, not silently mixed with Claude results. Audit the local artifacts with `benchmarks/results/codex-integration-selected-20260803T091057Z/checksums.sha256`; the ignored result directory is intentionally not a published fixture. The offline rescore is immutable-derived evidence, not a rewrite of paid telemetry.

</details>

### Multi-model results: real-codebase benchmark

#### Latest — 2026-07-29 (39 tasks × 2 arms × 3 tiers)

Full summary + per-task reading: [`results/bench-summary-2026-07-29.md`](results/bench-summary-2026-07-29.md). **codemap v0.27.0** · models `claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5` · symmetric-prompt harness (post 2026-07-03 fairness overhaul). Single run (n=1); DI/GR series (10 tasks) skipped pending ground truth. Sources: `bench-{haiku,sonnet,opus}-20260729-*.jsonl`. Ratios reported as **median / mean** of the per-task codemap/plain distribution.

**Two value axes — read separately, never blended.** (1) **Reliability/quality**: safety-grade + structural recall — codemap **13/13 safety-grade every tier** vs plain 8/13 → 12/13 → 13/13; the primary proposition, holds up-tier. (2) **Economy (cost/tokens/time)**: read at *matched caller fan-in* — the win grows with fan-in (cost 0.35× haiku / 0.54× opus on high-fan-in tasks); raw median token ratio is a *secondary, caveated* number that → 1 as models get terser. Accuracy Δ is a saturation-sensitive tie-breaker, not a headline.

| Tier      | Plain accuracy | Codemap accuracy | Δ accuracy  | Safety-grade plain | Safety-grade codemap | Token× med / mean | Cost× med / mean |
| --------- | -------------- | ---------------- | ----------- | ------------------ | -------------------- | ----------------- | ---------------- |
| Haiku 4.5 | 66.7% (24/36)  | 91.7% (33/36)    | **+25 pp**  | 8/13               | 13/13                | **0.57 / 0.65**   | 0.81 / 0.73      |
| Sonnet 5  | 82.4% (28/34)  | 94.3% (33/35)    | **+12 pp**  | 12/13              | 13/13                | **0.82 / 0.93**   | 0.97 / 0.91      |
| Opus 5    | 88.6% (31/35)  | 80.6% (29/36)    | **−8 pp ⚠** | 13/13              | 13/13                | 0.83 / 0.96       | 0.95 / 0.91      |

Per-workflow codemap accuracy: query (n=28) 92.0 / 95.8 / 84.0%; debug (n=6) 100 / 100 / 100%; feature (n=5) 80 / 80 / **40% ⚠** (haiku / sonnet / opus).

> **⚠ The opus codemap figures are deflated by two harness bugs found in a post-run audit** — do not cite opus codemap −8 pp as a result. (1) The count-extraction regex (`run-claude-structural.py:1422`) grabs the first stray number in verbose codemap prose (RV-02/opus answered "65 modules", correct, but the regex read "0 symbols" → recall 0.000). (2) `codemap query methods used` (`:2975`) silently drops the method on non-pure-JSON tool output, so "index-lookup only" is a parse artifact — opus actually ran `rdeps` in ~17 runs. See the report's scoring banner + the bug list below. **RESOLVED (2026-07-29):** fixes landed; a 2-repeat opus re-run on the fixed scorer shows opus codemap = plain **100% / 100%** with codemap *better* on tail-recall (fewer missed callers, fewer turns) — the −8 pp was pure artifact, and the "codemap short-circuits opus" (anchoring) hypothesis is refuted 0/14. See the report's "Opus anchoring probe" section.

**Reading it**: codemap's lift is inversely proportional to model strength — biggest where native navigation is weakest (Haiku +25 pp, Sonnet +12 pp). The opus row shows codemap −8 pp **as measured**, but that is mostly the scoring artifact above (below-plain recalls on RV-02/CQ-03 are count-regex false-fails, not real misses); there is no per-model skill routing (both arms share one symmetric prompt), so the residual gap is model behavior, not a plugin defect. Token savings are real at Haiku, near break-even by Opus (fixed index-injection overhead); codemap is faster on wall-clock at every tier (median time× 0.81 / 0.95 / 0.92). The historical 2026-07-29 query report recorded **PARTIAL** (26/32); it is distinct from the current no-model diagnostic (14/18 primary and 10/14 self-consistency). The agentic run was **interrupted** and is not reportable this cycle.

**Why the gains look smaller than June 22 — comparability**: the drop in token savings (June 0.22–0.38× → July 0.57–0.83×) is **confounded** and cannot be attributed to the 5-series models alone. Three things changed at once between the two runs: (a) the **harness fairness overhaul** — June ran under codemap-favoring steering (codemap arm capped at 3 calls + forbidden to verify, plain arm coached toward more grepping), which by the README's own note made June ratios *upper bounds*; removing it raises the ratio toward 1.0 independent of model; (b) **model version** (Sonnet 4.6→5, Opus 4.6→5) — newer models navigate code better unaided, so the plain-arm denominator shrinks and the ratio rises even with codemap unchanged; (c) **codemap version** (pre-v0.13.2 → v0.27.0). To isolate the model-version effect you must hold the harness constant — run 4.6-era and 5-era models under the *current* fair harness. What *is* clean is the **within-July up-tier shrink** (0.57 → 0.82 → 0.83, one harness + one codemap version, only the tier varies): codemap injects a roughly fixed index blob while the plain arm's exploration cost falls as models strengthen → ratio → 1. So token savings are structurally largest where the plain baseline is most wasteful (weak models); on strong models the value proposition shifts from tokens to **structural recall / safety-grade** (8/13 → 13/13 at Haiku), which holds at every tier.

<details>
<summary><strong>Past experiments (pre-2026-07-03, stale)</strong> — June-22 real-codebase + older agentic runs, kept for history. Predate the fairness overhaul; not comparable with the latest above. Click to expand.</summary>

> **⚠ Stale (2026-07-03)**: all results below predate the fairness overhaul (symmetric arm prompts, AST-oracle ground truth, real C1/C2 metrics). Token ratios and FN/BR/RV/CQ accuracy were measured under codemap-favoring prompt steering and partially circular GT — treat as upper bounds; re-run pending.

Results — June 22 2026 — 44 tasks × 2 arms × 3 models, pytorch-lightning-master. **Models** `claude-haiku-4-5` / `claude-sonnet-4-6` / `claude-opus-4-6` · **codemap version not recorded in these result lines** (predates the v0.13.2 agentic run; ~mid-June 2026) · **codemap-favoring steering harness** (not comparable with the July run above — see comparability note).

| Model      | Plain accuracy | Codemap accuracy | Accuracy lift | Safety-grade plain | Safety-grade codemap | Token ratio (median) | Token ratio range |
| ---------- | -------------- | ---------------- | ------------- | ------------------ | -------------------- | -------------------- | ----------------- |
| Haiku 4.5  | 85.3% (29/34)  | 93.9% (31/33)    | **+9 pp**     | 5/13               | 12/13                | **0.38×**            | 0.04–68.2×        |
| Sonnet 4.6 | 83.8% (31/37)  | 91.9% (34/37)    | **+8 pp**     | 11/13              | 12/12                | **0.22×**            | 0.05–1.21×        |
| Opus 4.6   | 86.1% (31/36)  | 91.7% (33/36)    | **+6 pp**     | 13/13              | 12/12                | **0.31×**            | 0.05–1.46×        |

Safety-grade = fraction of FN + BR tasks with explicit recall where recall ≥ 0.90. Token ratio = codemap / plain input tokens. June 22 Haiku tok× max of 68.2× is RI-04 codemap `error_max_turns` (token spiral, fixed June 23). June 22 Opus codemap safety-grade 10/12: FN-02/BR-03 regressions fixed June 23 (both recall=1.000) — corrected post-fix safety-grade is **12/12**.

Per-workflow-type breakdown (codemap arm, tok× = median codemap/plain token ratio):

| Workflow type          | n tasks | Haiku tok× | Haiku cm_acc | Sonnet tok× | Sonnet cm_acc | Opus tok× | Opus cm_acc |
| ---------------------- | ------- | ---------- | ------------ | ----------- | ------------- | --------- | ----------- |
| query (SE/FN/RV/CQ/BR) | 28      | 0.28×      | 95.0%        | 0.14×       | 95.5%         | 0.23×     | 86.4%       |
| debug (DG)             | 6       | 0.33×      | 100%         | 0.31×       | 100%          | 0.39×     | 100%        |
| feature (FT)           | 5       | 0.55×      | 100%         | 0.71×       | 80%           | 0.58×     | 100%        |
| real_issue (RI)        | 5       | 3.36× ⚠    | 50%          | 0.85×       | 75%           | 0.41×     | 100%        |

#### Haiku 4.5 — `results/bench-haiku-20260622-223206.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                                                              |
| --------- | ------------------------------------------------------------------ |
| Median    | **0.38×** (62% reduction)                                          |
| Min       | 0.04× (FN-04)                                                      |
| Max       | 68.2× (RI-04, error_max_turns — arm-permission bug, fixed June 23) |

Note: max of 68.2× was RI-04 arm-permission bug (token spiral, fixed June 23) — not a normal operating point.

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed              | incomplete                       |
| ------- | --------- | -------------- | ------------------------------ | -------------------------------- |
| plain   | **85.3%** | 29/34          | 4 (SE-05, CQ-01, CQ-05, RI-04) | 2 (CQ-01, BR-04)                 |
| codemap | **93.9%** | 31/33          | 3 (SE-05, CQ-03, CQ-05)        | 2 (RI-02, RI-04) ⟵ fixed June 23 |

By series:

| Series       | plain | codemap | Notes                                                                                                                       |
| ------------ | ----- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| SE (5 tasks) | 4/4   | 4/4     | SE-05 ext-fail both arms                                                                                                    |
| FN (5 tasks) | 5/5   | 5/5     | Plain struggles (FN-01=0.769, FN-03=0.917); codemap perfect                                                                 |
| RV (5 tasks) | n/a   | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth    |
| CQ (5 tasks) | 1/3   | 2/3     | CQ-01 plain timeout; CQ-05 ext-fail both; CQ-03 codemap ext-fail                                                            |
| BR (8 tasks) | 8/8   | 7/8     | BR-07 codemap recall=0.778 < plain=0.889 ⚠                                                                                  |
| DG (6 tasks) | 6/6   | 6/6     | Both arms perfect; codemap saves 19–58% tokens                                                                              |
| FT (5 tasks) | 5/5   | 5/5     | Both arms perfect                                                                                                           |
| RI (5 tasks) | 4/5   | 1/3     | RI-01 codemap recall=0.667; RI-02/RI-04 codemap `error_max_turns` ⚠ (arm-permission bug — fixed June 23, both recall=1.000) |

**Safety-grade**: plain 5/13 → codemap 12/13 (June 22 run). BR-07 codemap recall=0.778 is the one miss. RI-02/RI-04 codemap `error_max_turns` were arm-permission bugs fixed June 23 (see `results/bench-haiku-20260623-003825.jsonl`, both recall=1.000).

#### Sonnet 4.6 — `results/bench-sonnet-20260622-235143.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                     |
| --------- | ------------------------- |
| Median    | **0.22×** (78% reduction) |
| Min       | 0.05× (BR-05)             |
| Max       | 1.21× (BR-03)             |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | **83.8%** | 31/37          | 1 (FT-03)         | 0          |
| codemap | **91.9%** | 34/37          | 1 (FN-03)         | 0          |

By series:

| Series       | plain | codemap | Notes                                                                                                                    |
| ------------ | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| SE (5 tasks) | 5/5   | 5/5     | Both arms perfect                                                                                                        |
| FN (5 tasks) | 4/5   | 3/4     | FN-02 plain=0.108 → codemap=1.000; FN-03 codemap ext-fail                                                                |
| RV (5 tasks) | n/a   | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth |
| CQ (5 tasks) | 3/5   | 4/5     | CQ-05 plain recall=^3.333 (over-count); codemap 4/5 correct                                                              |
| BR (8 tasks) | 8/8   | 8/8     | Both arms perfect; codemap saves 14–94% tokens                                                                           |
| DG (6 tasks) | 6/6   | 6/6     | Both arms perfect                                                                                                        |
| FT (5 tasks) | 4/4   | 4/5     | FT-03 plain ext-fail; FT-03 codemap recall=0.500 ⚠                                                                       |
| RI (5 tasks) | 4/5   | 4/5     | RI-01 both arms 0.667; RI-05 n/a both                                                                                    |

**Safety-grade**: plain 11/13 → codemap 12/12. Token savings primary codemap benefit at sonnet tier — query workflow median 0.14×.

#### Opus 4.6 — `results/bench-opus-20260622-230210.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                     |
| --------- | ------------------------- |
| Median    | **0.31×** (69% reduction) |
| Min       | 0.05× (BR-01)             |
| Max       | 1.46× (BR-02)             |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | **86.1%** | 31/36          | 2 (CQ-01, CQ-05)  | 0          |
| codemap | **91.7%** | 33/36          | 2 (FN-03, RI-02)  | 0          |

By series:

| Series       | plain | codemap | Notes                                                                                                                    |
| ------------ | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| SE (5 tasks) | 5/5   | 5/5     | Both arms perfect                                                                                                        |
| FN (5 tasks) | 4/5   | 2/4     | **🔴 FN-02**: codemap recall=0.027 vs plain=1.000 (Δ=−0.97); FN-03 codemap ext-fail                                      |
| RV (5 tasks) | n/a   | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth |
| CQ (5 tasks) | 2/3   | 4/5     | CQ-02 codemap recall=0.100 < plain=0.250; CQ-03/04/05 codemap perfect; CQ-03 plain=0.265 → codemap=1.000                 |
| BR (8 tasks) | 7/8   | 6/7     | **🔴 BR-03**: codemap recall=0.042 vs plain=1.000 (Δ=−0.96)                                                              |
| DG (6 tasks) | 6/6   | 6/6     | Both arms perfect                                                                                                        |
| FT (5 tasks) | 5/5   | 5/5     | Both arms perfect                                                                                                        |
| RI (5 tasks) | 4/5   | 3/4     | RI-01 codemap recall=1.000 vs plain=0.667 (+0.33); RI-02 codemap ext-fail                                                |

**Safety-grade**: plain 13/13 → codemap 10/12 (June 22 run). FN-02 and BR-03 regressions were evaluator bugs — fixed June 23 (see `results/bench-opus-20260623-003745.jsonl`, both recall=1.000).

### Agentic benchmark — plain vs codemap vs semble — 2026-06-27 (v0.13.2)

pytorch-lightning-master, 16 tasks × 3 models × 3 arms = 144 runs (143 completed; BA-16/opus/semble missing 1). erec = fraction of expected rdeps in agent output_text (tool results excluded, arm-fair).

> **🚧 Under reconstruction** — numbers from a benchmark run with skill failures (RC1 PID bug) and v0.13.1 cache. Clean numbers pending after v0.13.2 fix rollout.

**By model — quality + efficiency:**

| Model       | Plain erec | Codemap erec | Semble erec | Δ cm−plain | Plain tok | Codemap tok |
| ----------- | ---------- | ------------ | ----------- | ---------- | --------- | ----------- |
| Haiku 4.5   | 🚧         | 🚧           | 🚧          | 🚧         | 🚧        | 🚧          |
| Sonnet 4.6  | 🚧         | 🚧           | 🚧          | 🚧         | 🚧        | 🚧          |
| Opus 4.6    | 🚧         | 🚧           | 🚧          | 🚧         | 🚧        | 🚧          |
| **Overall** | 🚧         | 🚧           | 🚧          | 🚧         | 🚧        | 🚧          |

Tokens = avg input tokens per run.

**By difficulty — quality:**

| Difficulty | Tasks          | Plain erec | Codemap erec | Semble erec | Δ cm−plain |
| ---------- | -------------- | ---------- | ------------ | ----------- | ---------- |
| simple     | BA-01,05,09,13 | 🚧         | 🚧           | 🚧          | 🚧         |
| medium     | BA-02,06,10,14 | 🚧         | 🚧           | 🚧          | 🚧         |
| hard       | BA-03,11,12,15 | 🚧         | 🚧           | 🚧          | 🚧         |
| extreme    | BA-04,07,08,16 | 🚧         | 🚧           | 🚧          | 🚧         |

**Notable runs (v0.13.2)**: 🚧 pending clean re-run after bug fixes.

**Token component breakdown (143 runs, v0.13.2):**

| Component     | Plain mean | Codemap mean | Semble mean | Δ cm−plain |
| ------------- | ---------- | ------------ | ----------- | ---------- |
| input_tokens  | 🚧         | 🚧           | 🚧          | 🚧         |
| output_tokens | 🚧         | 🚧           | 🚧          | 🚧         |
| **total**     | 🚧         | 🚧           | 🚧          | 🚧         |

Token overhead 🚧 (pending clean re-run). Semble uses fewer input tokens than plain due to fewer tool calls.

**Tool call count (mean per run):**

| Tier    | Plain calls | Codemap calls | Delta |
| ------- | ----------- | ------------- | ----- |
| simple  | 🚧          | 🚧            | 🚧    |
| medium  | 🚧          | 🚧            | 🚧    |
| hard    | 🚧          | 🚧            | 🚧    |
| extreme | 🚧          | 🚧            | 🚧    |

Codemap reduces tool calls in every tier (🚧) — exploration savings are real but small vs preamble cost. Known limitations and planned mitigations: see `plugins/codemap-py/README.md`.

Results above include all three arms. Combined arm excluded from default "all" runs (run with `--arm combined` to include).

### Previous: agentic benchmark — 2026-04-29

`results/agentic-2026-04-29.md` — pytorch-lightning, 4 arms × 3 models × 8 tasks = 96 runs.

</details>
