# Codemap Benchmarks

Empirical validation for the `codemap` plugin. Provider ownership is explicit in every LLM runner name: `claude` and `codex` identify provider-exclusive transport, while `cli`, `generate`, and `provider_parity_contracts` are provider-neutral. The structural benchmark is **repo-agnostic**: swap `tasks-bench.json` (which ships a `repo` header with name, namespace, and default clone path) to run against any Python codebase. Reference results use `pytorch-lightning` pinned at tag `2.6.5` (auto-cloned to `.sandbox/pytorch-lightning`).

## Provider-parity expansion

### Current cross-provider acceptance status

| Workload   | Codex                 | Claude                | Current judgment                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------- | --------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ReadCrop   | Complete              | Complete              | Both full suites preserve source-answer quality; the strict installed integration lowers aggregate input and command use, with disclosed per-task variance.                                                                                                                                                                                                                                                                                                                        |
| Fix-Single | Complete              | Complete              | Both full suites preserve executable quality. Efficiency is heterogeneous, so production guidance skips Codemap for a fully localized edit with no unresolved structural fact.                                                                                                                                                                                                                                                                                                     |
| Fix-Multi  | Complete (bounded W3) | Complete (bounded W3) | Revised FM-01/FM-03 scopes are checksum-valid on Codex Luna and Claude Haiku/Sonnet. P1 closes as a harness and heterogeneous-evidence milestone: FM-02 and the semantically accepted FM-03 A/C pairs support bounded conclusions, while incomplete FM-01 A/C and model-specific failures remain reported and no universal multi-file efficiency claim is admitted.                                                                                                                |
| Patch      | Complete (bounded W4) | Complete (bounded W4) | Current checksum-valid Claude `claude-patch-post-lifecycle-9e7bbb02bc3a` and Codex `codex-patch-post-lifecycle-4119d30180f3/patch` scopes both complete 15/15 cells with strict-query delivery, patch transport, containment, oracle, regression, and cleanup evidence. Valid A/C quality ties remain provider/model-stratified: Claude has two lower-context/time C pairs plus strict-only successes; Codex has three lower-context/time C pairs plus two strict oracle failures. |

These are separate, nonpoolable strata. `A_plain` versus `C_strict` is decision-grade; `B_auto` is an optional-use canary. The complete task suites and unfavorable cells remain in the reported artifacts rather than being filtered to favor Codemap. Exact artifacts, scorer replays, limitations, and the P1 closure decision are documented below and in the active provider-parity expansion plan.

The final Fix-Multi gate is complete as a bounded W3 stratum. FM-02 remains accepted from the existing evidence. The checksum-valid `benchmarks/results/claude-fix-multi-f16f4b86418d` artifact remains immutable diagnostic provenance: FM-01 omitted the explicit `should_stop` dry-run field and the original FM-03 required an invalid `Strategy.setup`/`super()` contract. The canonical FM-03 task now uses cooperative `Strategy.setup_environment` propagation. Final paid artifacts are `benchmarks/results/claude-fix-multi-f2719755cb23` (Haiku), `benchmarks/results/claude-fix-multi-243a7e2174ea` (Sonnet), and `benchmarks/results/codex-unified-91752e388e4e/fix-multi` (Luna); all transport, patch, path, lifecycle, and integrity checks pass. Artifact glyphs and stored quality labels are immutable. A prospective scorer replay classifies all Haiku FM-01 A/B/C rows as failures under the final reason/verbose gate, Sonnet FM-01 A/B as passes and C as a verbose-gated failure, Haiku/Sonnet FM-03 A/B/C as semantic passes (including harmless method-docstring changes), and all Codex FM-01/FM-03 cells as passes. Valid A/C efficiency comparisons therefore exclude incomplete pairs. This closes P1.3/P1 as a harness and heterogeneous-evidence milestone, not as a universal multi-file efficiency claim.

```bash
# Regenerate and inspect the fresh Claude scope before any paid run.
# First run `bash benchmarks/run-all.sh claude --dry-run`, then export the
# target and index paths it prints for the current machine.
REPO_PATH="${REPO_PATH:?set to the target clone printed by run-all.sh}"
INDEX_PATH="${INDEX_PATH:?set to the locked index printed by run-all.sh}"

python3 benchmarks/run-claude-agentic.py \
    --study fix-multi \
    --repo-path "$REPO_PATH" \
    --index "$INDEX_PATH" \
    --model haiku \
    --tasks FM-01,FM-03 \
    --dry-run
```

The corresponding Codex dry run used the same revised `FM-01,FM-03` selector. The paid executions and their immutable output directories are recorded in the W3 acceptance section below; if locked sources change in a future rerun, discard the old approval and repeat the dry run. Never reuse the rejected `f16f4b86418d` directory or its approval.

The tracked methodology policy seed, benchmark suites, and manifest builders are the canonical inputs. `run-all.sh` regenerates the ignored [methodology manifest](manifests/provider-parity-methodology.json), [Codex integration manifest](manifests/codex-integration.json), its [human companion](manifests/codex-integration.md), and the agentic machine/human manifests before live admission; tests do the same before collection. A paid launcher then freezes those exact generated bytes and their hashes in its run-owned source snapshot, so later workspace edits cannot change an admitted run. Runtime logs and telemetry remain under ignored `results/` paths.

The superseded historical 55-task/165-cell structural run remains immutable provenance under the approved 0.28.2 machine manifest SHA-256 `568caefa6cdd1e876e2f35a5e2476d5e661d9672894191c930017f14a29305e4`; it is not current P1 acceptance evidence. Its methodology SHA-256 was `3320c2d35e3189d43e3c2336603189083cc7ef8e76ac10dfb2f99ef47ee07afa`. The later 0.28.3 prospective lock is retained as superseded provenance rather than active evidence: methodology SHA-256 `5f613da7ff7c431ff30be9e44a3d9444d1246766a8505e38fc2c6e2908a18112`, machine-manifest SHA-256 `3a69c31a82db95526d8b3e7ab3edf3c9b3a49dd917683413dc43154ddd6f42f8`, and human-manifest SHA-256 `be884757b2e738f3bfe9efba2cf75522b82220fe13fc36dd48d059ba3b7e5086`. Current completed agentic and structural evidence is reported below; no historical result is rewritten or pooled with a later contract.

Two paid post-fix diagnostic attempts stopped before any model cell: the first on macOS `/var` alias handling during snapshot creation, the second because the intentional `DI-01` stage conflicted with global clean-worktree admission. Both are infrastructure diagnostics, not treatment evidence. The repaired `DiffImpactStageAdmission` records exact Git status, repository commit, and intended-file SHA-256, restores the target in `finally`, and fails closed on unapproved changes or index/commit drift. The subsequent diagnostic completed 54/54 cells across `DI-01`, `DI-05`, `DI-06`, `GR-01`, `GR-03`, and `GR-04`: mean quality was equal at `0.8945` for A/B/C; paired geometric ratios were B/A `0.4465` input, `0.2732` output, `0.3335` elapsed and C/A `0.2849` input, `0.2623` output, `0.2932` elapsed. All 36 B/C cells used Codemap transport, but only 11/36 matched the exact locked query shape. This exposed a measurement bug: exact query-shape mismatch had been incorrectly folded into treatment adherence. The prospective runner now preserves transport adherence and reports `locked_query_conformance` separately, with continuous `locked_query_fitness`, `locked_query_endpoint_fitness`, `locked_query_target_fitness`, and `locked_query_option_fitness`; exact mismatches remain diagnostic counts and do not alone exclude a cell from pooling. Direct and Skill guidance now route production direct callers through `fn-rdeps … --exclude-tests`, transitive callers through `fn-blast`, and production centrality through `central --top N --exclude-tests`.

The provider-neutral library lives in `_bench_common/provider_parity_contracts.py`; it locks task/prompt identity, arm semantics, evaluator dispatch, continuous fitness components, capability strata, headline exclusions, and effort-aware paired construction. It does not generate tasks, run benchmarks, invoke models, or implement provider transport.

The agentic benchmark uses the same provider-neutral contract. `_bench_common/agentic_contracts.py`, `suites/tasks-agentic.json`, `run-claude-agentic.py`, and `run-codex-agentic.py` share the 16 committed BA-01–BA-16 task objects, materialized prompts, answer envelopes, ground-truth oracle, continuous scorer, and paired metrics. The canonical arms are `A_plain`, `B_auto`, and `C_strict`; provider adapters own only transport, isolation, and native event normalization. The default repeat count is one: Claude's default batch is 16 tasks × 3 arms × 3 model tiers = 144 cells, while Codex's default paid batch is 16 tasks × 3 arms = 48 cells. Either provider's run with more than one repetition is explicitly non-poolable and requires its exact derived scope SHA-256; Codex selected-task scopes use the same admission rule.

The interrupted `benchmarks/results/codex-agentic-20260804T212004Z` run persisted 31/48 cells and is invalid, non-poolable diagnostic evidence. Its shared prompt named answer labels without declaring the value shapes enforced by the scorer, so models often returned semantically reasonable rich structures that silently scored zero; BA-04 also permitted an estimated affected count while the oracle required exact equality. The stopped `benchmarks/results/codex-agentic-20260805T122121Z` run persisted 14/48 successful transports across BA-01–BA-05 before plugin-version admission failed while preparing the next cell. That run is also invalid and non-poolable: each C cell re-resolved plugins from mutable marketplace state, and the old response path discarded valid bare JSON plus raw EREC/RREC/DEFF evidence when the strict labelled envelope was absent. Its displayed zero scores therefore do not establish a Codex or Codemap quality failure.

The repaired `codex-agentic-protocol-evidence-separation-2026-08-05` revision applies to both providers. It gives the same typed field instructions and synthetic JSON example, validates shapes before scoring, represents high-centrality modules as `module → rdep count`, defines BA-03 prefix buckets, defines BA-04's exact deduplicated second-wave set, and distinguishes BA-05 public initializers from internal examples. A strict labelled answer is pooling-eligible; one complete bare JSON object may be scored only as a diagnostic, while malformed or ambiguous responses remain semantically unscored. Raw EREC/RREC and unbounded DEFF are computed independently from response formatting. Codex snapshots the exact run-owned Codemap and Codex Rig source trees once, installs directly from those immutable paths, validates their bytes before later cells, and records expected/observed identities in private `runtime-isolation.jsonl`. The repaired revision completed its first full 48-cell Codex run on 2026-08-05; its bounded exploratory results are reported in [Codex agentic parity study](#codex-agentic-parity-study).

The stopped partial artifacts `benchmarks/results/codex-integration-20260802T095824Z` and `benchmarks/results/codex-integration-20260803T191236Z` are audit-only and non-poolable; no treatment effect is inferred from either. The latter persisted 86/165 rows, first failed authentication at `execution_index=50`, and then recorded identical zero-token `401 Unauthorized` failures. Root fixes in the relock include zero-argument `coupled` canonical detection, CQ-03 ranking by internal import count with complete ordered five `name + dep_count` rows, and RV-02 acceptance of natural `N modules directly import/depend` forms.

The completed run is frozen at `results/codex-agentic-20260805T170347Z` under methodology SHA-256 `e1717b806ebad49111aac8b8b7703d0cdf241440d3ef0140f7e96cc3eff7804e`, agentic machine/human manifest SHA-256 values `9ee83804df5fa43b7a4d64ae9ea316005fffff1d974429cae452f0c90ad54185` / `52216b8e513538367ae1ce21c9e384a8ce440e96016ad308d147e280a447567a`, and default scope SHA-256 `a7dbcd13a33460db2f577c960f69f640d73000c217281ff3940a5c5c44f2457a`. All 48 coordinates persisted with treatment adherence, stable token accounting, and no contamination or infrastructure failure. The checksum ledger verifies every listed entry but omits the permitted empty `runtime-isolation.jsonl` sidecar, so the artifact supports an exploratory performance summary but not a claim of complete checksum coverage or independent runtime-identity attestation.

After the run, the terminal legends were clarified with metric directionality without changing task, prompt, oracle, scorer, transport, or treatment behavior. The prospective generated locks are methodology `597a7928a6e096d453e277d923a4eecc1bff7ca01ecb3e018a3ce10019518946`, structural machine/human `62d27a3a155e8c105f373bbc66c42e7d885c81ae4fb213aaf1f754e47ec20f34` / `1cff24fa6f415534d056edf0f3a0adcf5b891816d7a30a9ca68cdb0db3ecba3c`, agentic machine/human `7a4ce9bcbba1b729a2af766e9b0f3160eff5a2940ee8cec7aa3c5677b39e19f4` / `f96c5d1898a37d047b230448a73c8b02e4c64d39eca8328cdd3fd825f8c737cc`, and default agentic scope `2f1f17c8ba968bf7cc51225da584434ee7a6480886b72a298c82fdbef603a94f`. The archived paid runner differs from the prospective runner only in those legend strings, so this presentation-only relock does not require another paid run and does not rewrite the frozen result hashes.

The historical paid run used shared RV evaluator v6 and remains immutable/non-poolable. Its raw answers contain the correct RV-02 count `64 modules directly import` in all A/B/C rows; v6 failed to extract these natural forms. The relocked evaluator accepts optional `directly` and natural `[unique] [public] symbols [are] uncovered` phrasing; immutable tests preserve RV-05's real `2/5` symbol loss and aggregate score `0.7` with `correct=false`. It does not retroactively rescore historical telemetry.

Claude is the mature, repeatedly debugged reference adapter, but it is not an unquestionable oracle. Provider parity is bidirectional: every unexplained Claude/Codex divergence is investigated as a possible Codex defect, Claude defect, provider/backend limitation, or shared-methodology bug. Only transport, isolation, and provider-native event normalization may legitimately diverge.

**B2 Claude adapter migration.** Both Claude runners now route explicit canonical arms through the shared contracts:

- **`A_plain`** — Codemap is absent and inaccessible.
- **`B_auto`** — Codemap is available; the model may use it, and no-call is valid.
- **`C_strict`** — Codemap is available and must be used at least once; no-call is recorded as a separate compliance failure while task scoring remains independent.

Canonical runs load the locked task/prompt/evaluator policy and fail closed unless the target commit/tree, clean worktree, and index bytes/metadata match the manifest; result records carry task, suite, evaluator, envelope, arm-contract, repository, and index provenance. Legacy labels (`plain`, `codemap`, `semble`, `combined`) retain their historical behavior and remain `legacy-unversioned`; they are not retroactively mapped to A/B/C. `--dry-run` prints the selected plan without invoking Claude or writing model results; the real-code runner's default `--arm all` plan is A/B/C and validates the locked inputs, while the agentic runner validates them when a canonical arm is selected.

**Codex structural adapter and active controls.** `run-codex-structural.py` is one task-driven Codex CLI. With no `--tasks`, it plans or runs all 73 supported tasks (55 structural, 6 ReadCrop, 4 Fix-Single, 3 Fix-Multi, and 5 Patch), producing 219 A/B/C cells. `--tasks` accepts family tokens, exact IDs, or a mixed list; task IDs route to the appropriate stage-specific scorer. ReadCrop, Fix-Single, Fix-Multi, and Patch remain separate, nonpoolable result stages even though they share the transport and launcher. All stages normalize gross/cached/fresh input, output/reasoning output, command count, tool elapsed time, Codemap usage, error, and compliance fields. ReadCrop has a source-extraction oracle; executable stages give the agent one benchmark-owned writable checkout, capture its canonical Git diff outside the agent sandbox, then apply that diff in a second clean worktree for the ordinary apply, exact changed-path, independent behavior-oracle, and cleanup gates. Patch additionally stages each task's frozen historical target-test fixture and task-local index before the agent runs; paid admission still requires a fresh scope lock. Git metadata and project dependencies are intentionally unavailable inside the agent sandbox, and the equal-arm prompt directs the agent to use bounded syntax/static validation instead of wasting turns on inaccessible Git or project pytest. The checkout receives a derived frozen index whose only content change is `scan_root`; source and derived hashes plus a hash excluding that root are recorded, and index mutation makes the cell ineligible. `git apply --recount` and the behavior result after recovery are diagnostic-only fields for malformed hunk headers. A has no Codemap access. B receives only a locked direct CLI and may use it when useful; B is an optional-use canary, so a no-query B cell is compliant. C installs the locked Codemap and Codex Rig packages, binds the installed query Skill immutably, and must complete the task-specific canonical compact query. An explicit Skill-file read remains diagnostic-only. Prompts state Codemap's static-graph boundary: it is for compact symbol/dependency/importer/caller facts, not runtime validation, tests, or edits. Additional repository reads and shell commands are allowed in B/C but do not replace C's required treatment evidence. A_plain-versus-C_strict is the decision-grade contrast; a B regression means users should prefer the installed integration and does not undermine the strict-arm result. The Claude and Codex adapters share task loading, prompt materialization, hashes, validators, ground truth, scoring, and pairing; provider-specific code is limited to transport, isolation, and native event normalization. All canonical stage rows use the shared Rich renderer on terminals and plain redirected output, preserving compact `k`/`M` token and `m`/`s` time units without changing telemetry.

Each cell receives an isolated `CODEX_HOME`. Permission profiles deny the copied credential, host agent roots, network, and source-tree writes; treatment arms may write only to the index-local coordination directory. The runner records answer, quality, extraction, treatment adherence, Codemap use, locked-query component fitness, and transport failures per cell and continues after the admission smoke so these outcomes remain measurable. Terminal output uses `treatment:✓|✗` for the assigned transport contract and `codemap-used:✓|✗` for observed Codemap use: clean `A_plain` is `treatment:✓ codemap-used:✗`; a contaminated A row can be `treatment:✗ codemap-used:✓`; B requires the assigned direct-CLI availability and isolation but may make zero queries, while C requires the assigned Skill delivery plus its successful compact query. Exact locked-query agreement is independently recorded as `locked_query_conformance`; continuous Jaccard components are `locked_query_fitness`, `locked_query_endpoint_fitness`, `locked_query_target_fitness`, and `locked_query_option_fitness`, so a useful but non-exact query no longer masquerades as failure to receive the treatment.

Existing Claude and exploratory Codex results remain historical evidence and are never pooled with the current study. The confirmatory population has 45 independently scored tasks; ten static-reference or approximate/self-consistency tasks run as diagnostics. Target-dependent ground truth is valid only for PyTorch Lightning tag `2.6.5` at commit `be98784a1a03581b7051a355ae1084fd352d7cea`.

### Entrypoint ownership

| Ownership        | Entrypoint                                   | Role                                                                                                          |
| ---------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Claude only      | `run-claude-structural.py`                   | Structural and real-code A/B/C plus legacy Claude arms                                                        |
| Claude only      | `run-claude-agentic.py`                      | Agentic Claude/semble comparison plus canonical Claude arms                                                   |
| Codex only       | `run-codex-structural.py`                    | One task-driven 73-task CLI: structural A/B/C plus separate ReadCrop, Fix-Single, Fix-Multi, and Patch stages |
| Codex only       | `run-codex-agentic.py`                       | Approval-gated 16-task agentic A/B/C execution and artifact persistence                                       |
| Provider-neutral | `run-all.sh`                                 | Safe dispatcher for smoke, Claude, or Codex batch workflows                                                   |
| Provider-neutral | `run-codemap-cli.py`                         | Deterministic scan/query correctness and performance; no model                                                |
| Provider-neutral | `_bench_common/provider_parity_contracts.py` | Shared task, arm, scoring, provenance, and pairing library; not a runner                                      |
| Provider-neutral | `generate-tasks-bench.py`                    | Validates or refreshes shared structural oracle fields                                                        |
| Provider-neutral | `generate-tasks-real-issues.py`              | Refreshes shared real-issue task evidence                                                                     |

Archived manifests retain historical consumer labels from before this rename. Active execution uses only the concise names above; no compatibility launchers remain.

## Benchmark overview

| Benchmark                                                      | Provider         | Script                     | LLM | Arms                                   | Tasks                                                                                                      | Primary question                                                                                      |
| -------------------------------------------------------------- | ---------------- | -------------------------- | --- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [Agentic](#agentic-benchmark-shared-claudecodex-contract)      | Claude           | `run-claude-agentic.py`    | Yes | Canonical 3 (A/B/C); legacy 4 explicit | 16 import-graph tasks                                                                                      | Does Codemap change agentic exploration recall, efficiency, or adoption under the shared contract?    |
| [Structural](#real-codebase-benchmark-run-claude-structuralpy) | Claude           | `run-claude-structural.py` | Yes | Legacy 2; parity 3 (A/B/C)             | 60 tasks — 11 series (SE / FN / RV / CQ / BR / DG / FT / RI / DI / GR / MB)                                | Does scan-query reduce token cost and improve structural recall on pre-implementation research tasks? |
| Provider parity                                                | Codex            | `run-codex-structural.py`  | Yes | Parity 3 (A/B/C)                       | 73 task IDs: 55 structural + 6 ReadCrop + 4 Fix-Single + 3 Fix-Multi + 5 Patch; stages reported separately | Does Codemap provide an objective within-Codex advantage under the same shared contracts?             |
| Codex agentic parity                                           | Codex            | `run-codex-agentic.py`     | Yes | Canonical 3 (A/B/C)                    | 16 tasks × one repetition                                                                                  | Does Codemap change agentic exploration recall, efficiency, or adoption under the shared contract?    |
| [Query](#query-benchmark-run-codemap-clipy)                    | Provider-neutral | `run-codemap-cli.py`       | No  | —                                      | Deterministic query/correctness suites                                                                     | Is scan-query correct, complete, and fast enough?                                                     |

Run **Query** first — validates the index before spending LLM tokens on agentic runs.

### Codex agentic parity study

The current Codex agentic adapter uses all 16 committed BA tasks across `A_plain`, `B_auto`, and `C_strict`, with one repetition by default. It consumes the shared prompt materializer, response assessor, AST oracle, semantic component scorer, and raw EREC/RREC/DEFF evidence scorer used by Claude. DEFF is an unbounded exposure-hit count per command, not a normalized quality score. Validate the exact 48-cell plan without credentials or a model:

```bash
bash benchmarks/run-all.sh codex --agentic --dry-run
```

The deterministic review lock is `benchmarks/manifests/codex-agentic.json`; regenerate or verify it with `python3 benchmarks/build-codex-agentic-manifest.py [--check]`. The dedicated human companion records the current manifest SHA, task order, treatment contract, exact approval variable, and retry-inclusive per-cell timeout in seconds. No-model dry runs require no credentials and no paid approval. A paid run requires the exact active machine-manifest SHA and private auth source; the launcher creates a fresh timestamped run directory automatically, with an optional `CODEX_RUN_DIR` override for a new path. Final run checksums attest the result artifacts, invocation launcher, and `source.sha256`; verify the archived source bytes separately with `(cd "$RUN_DIR/.launcher/source" && shasum -a 256 -c ../source.sha256)`. Codex CLI version is recorded as observed provenance only and is not a pinned or admission requirement. Each cell has only the retry-inclusive per-cell timeout; no total-run ceiling or wall-clock environment/CLI control applies. A non-default repetition or selected scope must additionally present the resolver's scope SHA-256.

For approval UX, the matching no-model dry run prints a lowercase 16-character SHA-256 scope prefix for copyable `--paid-approval` (or its equivalent approval variable). The complete 64-character scope SHA-256 remains recorded in run metadata and provenance, and the CLI accepts that full value as well. Never mix a prefix or full scope from another dry run with the selected command; regenerate approval after any locked-source change.

#### Completed combined-run Codex agentic study — 2026-08-07

The frozen `results/codex-combined-20260807T130711Z/agentic` run completed all 16 tasks once across the three arms with `gpt-5.6-luna` at high effort, codemap-py 0.28.7, codex-rig 0.4.6, and observed Codex CLI 0.146.1. All 48 cells completed and followed their treatment contract; A used Codemap in 0/16 cells, optional B in 10/16, and strict C in 16/16. The manifest declares the study exploratory and nonpoolable, and seven answers were diagnostic bare-JSON recoveries, so the values below are paired descriptive evidence rather than causal or release-acceptance estimates.

<!-- result-sync: duplicated/summarized in ../plugins/codemap-py/README.md#codex-agentic-2026-08-07; update both files or record an explicit divergence note. -->

| Arm        | Mean semantic score | Perfect score | Mean EREC/RREC | Strict answers | Codemap used | Mean input | Mean output | Mean elapsed |
| ---------- | ------------------: | ------------: | -------------: | -------------: | -----------: | ---------: | ----------: | -----------: |
| `A_plain`  |              0.8931 |          7/16 |     **1.0000** |      **16/16** |         0/16 |     426.2k |        7.8k |       171.3s |
| `B_auto`   |              0.9015 |          8/16 |     **1.0000** |          12/16 |        10/16 |     223.8k |        4.5k |       107.4s |
| `C_strict` |          **0.9900** |     **13/16** |     **1.0000** |          13/16 |        16/16 | **103.5k** |    **2.4k** |    **60.4s** |

Bold = best comparable arm value per column (higher is better for semantic score, perfect score, EREC/RREC, and strict answers; lower is better for input, output, and elapsed time). `Codemap used` is a treatment diagnostic, not a performance metric, so it is not bolded.

Relative to `A_plain`, `C_strict` used paired geometric-mean `0.337×` input, `0.306×` output, and `0.359×` elapsed time, with lower input on 15/16 tasks. Its mean semantic-score delta was `+0.0969` with 8 wins, 7 ties, and one loss. Relative to `B_auto`, C used paired geometric-mean `0.466×` input, `0.513×` output, and `0.548×` elapsed time, with lower input on 15/16 tasks; its mean score was `+0.0885` higher with 7 wins, 8 ties, and one loss. The latest result strengthens the descriptive B6 quality-and-efficiency finding, but one repetition, one repository/model, optional B adoption in only 10/16 cells, and seven diagnostic answers prohibit a general causal or pooling claim. All 329 listed checksums verify; raw and canonical telemetry SHA-256 are both `efa48c3477d5ace8824cd0d9ae3fbee8c9603bbe8e79f64175be07ca96f00b3e`, metadata is `9fd0d512f4b666f14b840e14f27ba9e18ce6957d2213f40f90224b8f545fa436`, manifest is `739485475e38209613c94f3008ff394c31548325d322981fa6be9788285eff62`, and scope is `049670fbdbb6a02fba1e03ff3ad0c62a2d886f275afde2c3b7add6afb4bdd358`.

The stopped directory `results/codex-agentic-20260804T205639Z` is infrastructure-only evidence with zero model cells. The launcher previously opened its console capture inside the new result directory before the runner's strict launcher-only admission check, so the runner rejected the launcher's own file. Console capture now uses a private temporary file outside the result directory, while the strict admission invariant remains unchanged. Any supported-entrypoint failure preserves the reported artifact and prints the exact dry-run command plus a fresh timestamped paid command; reuse of an existing result directory remains forbidden.

The stopped directory `results/codex-agentic-20260805T122121Z` contains 14 successful transport rows but is infrastructure/scoring diagnostic evidence only. Runtime identity drift stopped admission before the fifteenth cell, and the superseded response path conflated strict-envelope failure with absent semantic and raw-text evidence. The prospective runner freezes plugin source bytes before the first cell, preserves identity evidence even when initial C admission fails, and records semantic validity, diagnostic recovery, pooling eligibility, EREC, RREC, and DEFF as separate fields.

The stopped directory `results/codex-agentic-20260805T144950Z` contains one successful A row and is infrastructure-only evidence. The snapshot archive preserved the B launcher bytes but stripped its executable mode from `0755` to `0600`, so B admission failed before a model call. The repaired archive writes executable inputs as private `0700`, writes other inputs as `0600`, records each mode in the snapshot ledger, and fails closed on later byte or mode drift.

The completed frozen run `results/codex-agentic-20260804T172617Z` is historical immutable evidence: it persisted 9/9 BA-01 cells under archived machine manifest `f8490d39e2dbade395600423e4096cee94d7f87d1ada4cbe0a876fa74052fa8c`. Direct-importer exposure and final-report recall were `1.0` in every arm and repetition. Relative to `A_plain`, `B_auto` reduced mean input tokens by 39.6%, output tokens by 58.4%, and elapsed time by 52.5%; the then-named `C_required` arm reduced them by 66.3%, 71.9%, and 69.6%, respectively. These bounded exploratory means from one task and three repetitions are not the current default, are not pooled with the 16-task study, and do not define provider-wide performance.

## Unified batch entrypoint

`run-all.sh` is the only batch orchestrator. It requires one provider mode; both providers accept the mutually exclusive `--struct` and `--agentic` workload selectors plus `--dry-run`. `--repetitions=N` is agentic-only. Omitting a workload selector runs structural then agentic for both providers. A combined paid Codex invocation validates both approvals before any model call, freezes one outer source, and preserves isolated `structural/` and `agentic/` child artifacts. Missing or unknown arguments do nothing:

```bash
bash benchmarks/run-all.sh smoke
bash benchmarks/run-all.sh claude
bash benchmarks/run-all.sh claude --struct --dry-run
bash benchmarks/run-all.sh claude --agentic --dry-run
bash benchmarks/run-all.sh codex --struct --dry-run
bash benchmarks/run-all.sh codex --struct --tasks=DI,GR --dry-run
bash benchmarks/run-all.sh codex --agentic --dry-run
CODEX_PAID_APPROVAL="$(shasum -a 256 benchmarks/manifests/codex-integration.json | awk '{print $1}')" \
    CODEX_AGENTIC_PAID_APPROVAL="$(shasum -a 256 benchmarks/manifests/codex-agentic.json | awk '{print $1}')" \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    bash benchmarks/run-all.sh codex
CODEX_PAID_APPROVAL="$(shasum -a 256 benchmarks/manifests/codex-integration.json | awk '{print $1}')" \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    bash benchmarks/run-all.sh codex --struct
```

Modes:

- `smoke` — validate the frozen active index, run the deterministic query check, and execute Claude and Codex dry-run/preflight paths. It invokes no model.
- `claude` — validate the shared methodology lock and frozen index, then run the same locked 55 structural tasks as Codex across every canonical coordinate (`A_plain`, `B_auto`, `C_strict`) for each Claude model tier before the agentic batch. The shared revision-bound policy counterbalances arm order per task. Runner infrastructure failures stop the batch; individual cell outcomes remain recorded by their runner.
- `claude --struct [--dry-run]` — run or plan only the shared 55-task canonical Claude structural matrix with the same deterministic per-task arm-order policy; the agentic preflight and batch are excluded. Direct `run-claude-structural.py` calls retain their legacy arm and 60-task defaults unless `--provider-parity` is explicit.
- `claude --agentic --dry-run` — validate the shared 16-task methodology, resolve the exact one-repeat 144-cell scope across three Claude model tiers, and print the complete no-model plan. `--repetitions=N` derives and passes a distinct scope SHA-256; the same flag without `--agentic` is rejected.
- `claude --agentic` — run only the shared 16-task canonical A/B/C Claude study. The default is one repetition; a higher explicit repetition is admitted only with the launcher's exact derived scope SHA-256.
- `codex [--dry-run]` — plan or execute the complete unified 73-task/219-cell structural study followed by the complete agentic study. Paid mode requires the aggregate manifest-bound approval and one private auth source before either suite starts. `CODEX_RUN_DIR`, when supplied without a selector, is the new combined parent whose child runs are `structural/` and `agentic/`; the sequence stops on the first suite failure and preserves completed artifacts.
- `codex --struct --dry-run` — validate the frozen index, run the deterministic query check and FN-02 Codex smoke, then print the exact 219-coordinate unified plan. It needs no paid approval, authentication source, or result directory and invokes no model.
- `codex --struct --tasks=DI,GR --dry-run` — resolve the requested structural families, validate the selected scope, exercise the selected no-model preflight, and print the exact 90-coordinate plan. Selected scopes are targeted and non-poolable; they need no paid approval or authentication source for dry-run.
- `codex --struct` — validate the frozen index, run the fail-fast FN-02 A/B/C smoke and exact no-model plan, then execute all 73 tasks × one repetition × three arms. Structural, ReadCrop, Fix-Single, Fix-Multi, and Patch outcomes use native scorers and separate child artifacts; cell outcomes are recorded without fail-fast after admission. Paid execution requires the aggregate scope approval and private auth source; the launcher creates a fresh run directory, with an optional `CODEX_RUN_DIR` override for a new path. Each cell uses the retry-inclusive per-cell timeout in seconds; no total-run ceiling is configured.
- `codex --struct --tasks=DI,GR` — execute only the selected, non-poolable task scope after the same smoke and admission gates. Family, exact-ID, and mixed selectors are accepted; the resolved aggregate scope SHA-256 is printed and must authorize that scope.
- `codex --agentic --dry-run` — validate the shared 16-task agentic lock, target, index, and A/B/C capability probes, then print exactly 48 planned cells without credentials or a model.
- `codex --agentic` — execute BA-01–BA-16 across A/B/C for one repetition with the exact active-manifest approval and private auth source documented in `manifests/codex-agentic.md`. Runtime/admission integrity failures stop and preserve partial artifacts; ordinary model/task/treatment outcomes remain measurable and do not fail fast. The launcher creates a fresh run directory, with an optional `CODEX_RUN_DIR` override for a new path. Each cell uses the retry-inclusive per-cell timeout in seconds; no total-run ceiling is configured. Add `--repetitions=N` only with the resolver's matching scope SHA-256.

Claude preparation validates the shared methodology lock without requiring the Codex integration manifest; Codex and `smoke` retain the full methodology-plus-Codex-manifest cross-check. The Codex smoke preflight now uses the unified `--tasks FN-02` selector and no longer passes removed legacy flags. Paid/model validation remains pending human authorization, a fresh aggregate scope, credentials, and a new output directory.

#### Codex structural runner

`run-codex-structural.py` is task-driven: stage and execution mode are inferred from task selection and dry-run state. Omit `--tasks` to plan or run all 73 supported tasks (55 structural + 6 ReadCrop + 4 Fix-Single + 3 Fix-Multi + 5 Patch), for 219 A/B/C cells at the default one repetition. Use family tokens for a stage or exact IDs for a targeted scope; mixed selectors are allowed, duplicates are removed, and locked manifest order is retained:

```bash
# All supported tasks: 73 tasks × 3 arms = 219 cells
python3 benchmarks/run-codex-structural.py --repo-path /path/to/pytorch-lightning --model gpt-5.6-luna --dry-run

# Selected families: ReadCrop + Fix-Single + Fix-Multi + Patch
python3 benchmarks/run-codex-structural.py --repo-path /path/to/pytorch-lightning --model gpt-5.6-luna --tasks RC,FS,FM,PT --dry-run

# Selected exact IDs, mixed across stage families
python3 benchmarks/run-codex-structural.py --repo-path /path/to/pytorch-lightning --model gpt-5.6-luna --tasks RC-01,FS-03,FM-02 --dry-run
```

Run the no-model `--dry-run` first; omit it only for the approved execution command. ReadCrop, Fix-Single, Fix-Multi, and Patch retain stage-specific scorers and separate, nonpoolable result artifacts. Empty selectors, unknown IDs/families, and invalid mixtures fail before target setup or model admission. `CODEX_PAID_APPROVAL` remains the manifest-bound authorization and stale-manifest lock; no separate boolean paid flag is needed. The dry-run prints a lowercase 16-character SHA-256 prefix accepted by `--paid-approval`; the full 64-character scope remains recorded for provenance and is accepted too.

Credential handling is explicit, not discover-and-search. The security-approved paid-run contract opens only `CODEX_AUTH_SOURCE`, requires a user-owned nonsymlink regular file with mode `0600`, snapshots it into private run-scoped sequential auth state, and atomically propagates the current state into each disposable mode-`0700` Codex home. The source is immutable and drift-checked before each cell; a valid refresh from one cell seeds the next. Cleanup is verified for the run state and every home. Known authentication failures stop immediately; an unknown equivalent zero-token infrastructure failure stops after three matching occurrences, while semantic/model failures remain recorded and continue. Credential bytes, the source path, and standard auth/token/cookie fields are redacted from telemetry and run metadata. Do not run another Codex session concurrently: server-side refresh rotation can invalidate the benchmark state, and the source may require reauthentication after the run. Approval, auth-source, and run-directory controls are removed from measured Codex arm environments.

At paid launch, the runner freezes a run-scoped source bundle containing the benchmark runner, manifests, suites, and plugin sources; later workspace edits cannot affect that run. Only the sample repository and its frozen index remain external inputs. The target is pinned to PyTorch Lightning tag `2.6.5`; the hardcoded ground truth and active manifest reject every other tree. The managed temporary clone is reset to that tag before each mode. `REPO=/path/to/clone` may select an external clone, but the script never resets an override and canonical preflight still requires the locked clean commit and exact frozen-index SHA-256. A missing index is rebuilt and admitted only when normalization of declared environment-specific metadata reproduces the complete locked SHA-256. Every Codex result row records provider, model, effort, task, repetition, arm, telemetry, adherence, Codemap-use, provenance, timing, gross input tokens, cached input tokens, fresh input tokens, output tokens, and limits; `run-metadata.json` is updated after each durable cell. Native Codex input usage is cumulative within a turn, so cached input is a subset of gross input. Gross input is retained for reporting; when `cached_input_tokens <= gross_input_tokens`, fresh input is `gross - cached`; only an inconsistent `cached_input_tokens > gross_input_tokens` row is reported as `?` and token-ineligible.

### Codex result artifacts and ordering

The append-only `telemetry.jsonl` is the execution record. Rows retain `execution_index` and the actual randomized arm order so interrupted runs can be audited without rewriting history. The runner rejects existing raw/metadata artifacts for a new run; partial runs are audit-only and are never resumed, pooled, or re-scored as confirmatory evidence. Before setup, paid `run-all.sh` execution copies itself to a mode-`0500` private launcher under the new run directory and re-executes that snapshot. The runner archives the exact launcher bytes, validates the manifest-bound SHA-256 before and after every cell and at completion, and fails the run if those bytes drift. A successful run also emits `telemetry-canonical.jsonl`, an atomically written derived view sorted by locked task position, repetition, and fixed treatment order. Human labels are `A_plain`, `B_direct`, and `C_skill`; machine telemetry and manifest IDs remain `A_plain`, `B_direct_required`, and `C_skill_required`. Terminal summaries and later paired analysis use the canonical view; raw and canonical files are never pooled or silently substituted. `run-metadata.json` records the canonical artifact status and SHA-256 alongside the raw telemetry hash.

The human result line uses fixed columns and compact units (`k` = 1,000; `M` = 1,000,000). Each top-level smoke, Codex paid, or diagnostic paid section emits exactly one shared terminal legend; nested preflight/study sections do not repeat it. Legends use `A_plain`, `B_direct`, and `C_skill` for plain, direct CLI, and installed Skill. The console reports gross input only; cached and fresh remain raw telemetry fields (`fresh = gross - cached` when consistent). `quality` is continuous fitness in `[0, 1]`; `treatment:✓|✗` answers treatment adherence; `codemap-used:✓|✗` answers observed Codemap use. The observed Codex CLI exposes no supported per-cell provider prompt-cache reset/disable, so six-permutation counterbalancing mitigates order exposure without claiming cache elimination. Machine telemetry and manifest IDs remain `A_plain`, `B_direct_required`, and `C_skill_required`.

The installed-Skill treatment binds a compact Skill and requires one successful canonical query; an explicit full-Skill file read is optional audit telemetry, not productive-use ceremony. The direct CLI remains intentionally bare, but top-level CLI help and query help expose valid subcommands and explicit count semantics. `undocumented` distinguishes declaration totals from unique symbols; `uncovered` identifies its static-query coverage semantics. These usability fixes are part of the shared product surface and are tested independently from the paid provider study.

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
- **Scale**: real-codebase = 55 × 2 × 3 = 330 model runs; Claude agentic default = 16 × 3 × 3 = 144; Codex agentic default = 16 × 3 = 48. These are separate provider studies with shared task, prompt, oracle, and scorer contracts.
- **Model tiers** (`MODELS` map in each runner): `haiku` → `claude-haiku-4-5`, `sonnet` → `claude-sonnet-5`, `opus` → `claude-opus-5`.
- **Agentic arms**: canonical runs use `A_plain`, `B_auto`, and `C_strict`. Legacy Claude `semble` / `combined` arms remain explicit historical compatibility paths and need the semble MCP configured.
- **Cheaper option**: swap the three bench lines for the tiered strategy (`--tiered`, see [Cost profiles](#cost-profiles)) — full suite on haiku, dev subset on sonnet, only cross-tier disagreements on opus.
- **Results** land in `benchmarks/results/` — `code-<date>.md`, `bench-<model>-<ts>.jsonl`, and agentic JSON (`.md` with `--report`).

## Contents

- [Agentic benchmark](#agentic-benchmark-shared-claudecodex-contract) — shared 16-task A/B/C import-graph navigation for Claude and Codex
- [Real-codebase benchmark](#real-codebase-benchmark-run-claude-structuralpy) — Claude-only structural navigation on pytorch-lightning
- [Query benchmark](#query-benchmark-run-codemap-clipy) — provider-neutral scan-query correctness and latency, no LLM
- [Results](#results)

<details>
<summary><strong>Files</strong></summary>

| File                                            | Ownership        | Purpose                                                                                                                                                           |
| ----------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `policy/provider-parity-methodology.json`       | Provider-neutral | Tracked canonical methodology policy seed consumed by the deterministic builders                                                                                  |
| `manifests/provider-parity-methodology.json`    | Provider-neutral | Ignored, on-demand generated shared task, evaluator, target, index, and analysis identities; frozen into each admitted run                                        |
| `manifests/codex-integration.json`              | Codex            | Ignored, on-demand generated machine-enforced plain/direct-CLI/Skill execution contract                                                                           |
| `manifests/codex-integration.md`                | Codex            | Ignored, on-demand generated human-readable manifest review and paid-run instructions                                                                             |
| `manifests/codex-agentic.json`                  | Codex            | Ignored, on-demand generated machine-readable 16-task agentic A/B/C execution lock, exact-SHA admission, runtime limits, and artifact contract                    |
| `manifests/codex-agentic.md`                    | Codex            | Ignored, on-demand generated human-readable 16-task agentic scope, treatment, scorer, approval, and launch review                                                 |
| `build-provider-parity-methodology-manifest.py` | Provider-neutral | Deterministically regenerates or verifies the shared methodology manifest                                                                                         |
| `build-codex-integration-manifest.py`           | Codex            | Deterministically regenerates or verifies the structural machine and human manifests                                                                              |
| `build-codex-agentic-manifest.py`               | Codex            | Deterministically regenerates or verifies the shared 16-task agentic machine and human manifests                                                                  |
| `_bench_common/agentic_contracts.py`            | Provider-neutral | Shared agentic arms, prompt materialization, answer contracts, oracle, parsing, scoring, and paired metrics                                                       |
| `_bench_common/provider_parity_contracts.py`    | Provider-neutral | Canonical task identity, A/B/C semantics, evaluator dispatch, headline eligibility, and paired effects; not a runner or generator                                 |
| `run-claude-agentic.py`                         | Claude           | Agentic benchmark measuring how Codemap/semble structural context changes Claude exploration                                                                      |
| `run-claude-structural.py`                      | Claude           | Repo-agnostic structural benchmark driven by the `tasks-bench.json` repository header                                                                             |
| `run-all.sh`                                    | Provider-neutral | Sole batch dispatcher: no-model cross-provider smoke, paid Claude batches, or approval-gated Codex structural and agentic studies                                 |
| `run-codemap-cli.py`                            | Provider-neutral | Query-level correctness, coverage, and latency against a real repository                                                                                          |
| `run-codex-structural.py`                       | Codex            | Codex structural provider-parity transport for canonical A/B/C cells with isolated plugin homes, native telemetry normalization, and shared structural evaluators |
| `run-codex-agentic.py`                          | Codex            | 16-task Codex agentic runner with shared Claude-parity scoring, treatment isolation, paid admission, telemetry, and partial-artifact preservation                 |
| `generate-tasks-bench.py`                       | Provider-neutral | Validates or refreshes shared structural oracle fields; it does not author prompts                                                                                |
| `generate-tasks-real-issues.py`                 | Provider-neutral | Refreshes shared real-issue evidence                                                                                                                              |
| `suites/tasks-agentic.json`                     | Provider-neutral | Shared 16 blast-radius navigation tasks (BA-01–BA-16), answer contracts, and difficulty tiers used by both agentic adapters                                       |
| `suites/tasks-bench.json`                       | Provider-neutral | 60 tasks across 11 series plus the target repository header                                                                                                       |
| `suites/tasks-code.json`                        | Provider-neutral | 15 code-level tasks used by the scan-query benchmark                                                                                                              |
| `suites/tasks-patch.json`                       | Provider-neutral | 5 end-to-end patch tasks requiring patch application and tests                                                                                                    |
| `suites/tasks-readcrop.json`                    | Provider-neutral | 6 symbol-contract extraction tasks scored by keyword recall                                                                                                       |
| `suites/tasks-fix-single.json`                  | Provider-neutral | 4 single-file fix tasks scored by diff keyword recall                                                                                                             |
| `suites/tasks-fix-multi.json`                   | Provider-neutral | 3 multicaller fix tasks scored by clean patch application, exact changed-path boundaries, and complete-caller AST behavior oracles                                |
| `results/`                                      | Provider-neutral | JSON snapshots and Markdown reports from past runs                                                                                                                |

</details>

## Agentic benchmark (shared Claude/Codex contract)

Runs the same committed 16 import-graph tasks under the canonical three arms. Claude runs all three model tiers by default; Codex runs one repetition by default and requires exact scope approval for any expanded repetition count.

| Arm        | Codex treatment                                                       | Claude treatment                                                      |
| ---------- | --------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `A_plain`  | Codemap absent and inaccessible                                       | Codemap absent and inaccessible                                       |
| `B_auto`   | Direct Codemap CLI available; use is optional                         | Codemap available; use is optional                                    |
| `C_strict` | Codemap Skill available; at least one successful compact query needed | Codemap Skill available; at least one successful compact query needed |

The shared answer envelope is materialized from each task's committed `answer_contract`. The shared parser and oracle score exact fields plus continuous component fitness; `EREC`, `RREC`, and `DEFF` remain diagnostic metrics. Missing or malformed required fields score zero for that component without changing transport/admission status.

### Legacy Claude-only arms

Historical Claude compatibility runs can still be selected explicitly under these four arms; they are not part of the current provider-parity default and are not pooled with canonical A/B/C results:

| Arm        | Tools available                                                                           |
| ---------- | ----------------------------------------------------------------------------------------- |
| `plain`    | Grep / Glob / Bash only                                                                   |
| `codemap`  | + `/codemap:query` skill (structural AST index); semble blocked                           |
| `semble`   | + `mcp__semble__search` MCP tool (hybrid semantic + lexical search); Skill + Bash blocked |
| `combined` | Both `/codemap:query` and `mcp__semble__search`; no restrictions                          |

**Legacy prompt symmetry (2026-07-03)**: the four historical arms share one neutral base prompt — identical task framing, identical "Required answer format" block, and one shared efficiency sentence ("Answer in as few tool calls as possible; do not re-verify results you already have."). Arm supplements carry tool availability + invocation syntax only. Earlier versions steered arms asymmetrically (plain coached toward more grepping; codemap capped at 3 calls and forbidden to verify; semble/combined given prescriptive protocols) — that steering contaminated efficiency metrics, so results produced before this date are not comparable with new runs. Canonical A/B/C runs use the provider-neutral materialized prompt and answer contract described above.

**Ground truth (2026-07-03)**: expected rdeps come from an independent AST scan of the repo (absolute, aliased, `from`-import, and relative forms resolved), not from the codemap index. The index-derived list is kept as a diagnostic; divergence is printed per task as `[gt-divergence] BA-XX: ast=N index=M ...` — a divergence now signals a potential plugin bug instead of being invisible.

**Metrics**: tool call count, elapsed time, input tokens, exposure recall (erec), top-10 exposure recall (e@10), report recall (rrec), discovery efficiency (deff).

| Metric | What it measures                                                                                                                                                                      |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `erec` | Fraction of ground-truth rdeps found in agent output_text (tool results excluded; arm-fair)                                                                                           |
| `e@10` | erec restricted to the 10 most-central rdeps, ranked by reverse-dependency count (in-degree — how many modules import each), matching the "imported by the most modules" task wording |
| `rrec` | Fraction of ground-truth rdeps present in the agent final written answer only                                                                                                         |
| `deff` | Ground-truth reverse dependencies exposed per tool call: `erec_tp / max(tool_calls, 1)`                                                                                               |

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

# 3. Run the shared 16-task canonical A/B/C suite across all Claude model tiers
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

| Flag                                                                | Default         | Description                                                              |
| ------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------ |
| `--repo-path PATH`                                                  | required        | Absolute path to the repo under test                                     |
| `--index PATH`                                                      | auto-detected   | Override index path (default: `<repo>/.cache/scan/<name>.json`)          |
| `--arm plain\|codemap\|semble\|combined\|A_plain\|B_auto\|C_strict` | canonical A/B/C | Run a single legacy or canonical arm only                                |
| `--model haiku\|sonnet\|opus`                                       | all three       | Run a single model tier only                                             |
| `--tasks "['BA-01','BA-02',...]"`                                   | all 16          | Run specific task IDs (Python list literal — e.g. `"['BA-01','BA-02']"`) |
| `--run-all`                                                         | off             | Run all tasks (required unless `--tasks` given)                          |
| `--report`                                                          | off             | Write markdown report to `results/` after run                            |
| `--repeat N`                                                        | `1`             | Repeat each selected cell; values above one require `--scope-sha256`     |
| `--scope-sha256 SHA`                                                | none            | Admit the exact derived nondefault canonical scope                       |
| `--resolve-scope`                                                   | off             | Print the selected canonical scope and SHA-256 without running a model   |
| `--dry-run`                                                         | off             | Print the selected plan without invoking Claude or writing model results |

</details>

### Output

Each run prints one coloured line; canonical labels are `A_plain`, `B_auto`, and `C_strict`:

```
[NN/TT] BA-01 (fix) | haiku  | C_strict | elapsed= 45.2s | tokens= 120.3k | calls= 3 (grep=  0; glob= 0; bash=  0; skill= 1; semble= 0) | erec= 94% rrec= 88%  sc=100%
```

Colour: canonical `A_plain` = yellow · `B_auto` = cyan · `C_strict` = magenta; legacy `semble`/`combined` colors remain for explicitly selected compatibility runs; red = failure.

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

**CQ — Code quality.** Asks the agent to surface structural health metrics used at release gates — the most-coupled module, symbols with broken cross-references in docstrings, combined documentation and coverage deficits. Plain agents must invoke independent file reads for each metric and often miss cases requiring whole-graph reasoning such as transitive coupling. The codemap index exposes `coupled`, `xrefs --broken`, `undocumented`, and `uncovered` queries that inspect pre-built structural graphs and return ranked, quantified results.

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

| Flag                                                   | Default       | Description                                                                                                                                                                                              |
| ------------------------------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--repo-path PATH`                                     | auto          | Path to repo clone (default: `repo.local_path` from `tasks-bench.json`)                                                                                                                                  |
| `--index-path PATH`                                    | auto          | Override index; checks `.cache/codemap/` then `.cache/scan/`                                                                                                                                             |
| `--tasks "['SE-01','FN-02',...]"`                      | all           | Run specific task IDs (Python list literal — e.g. `"['SE-01','FN-02']"`)                                                                                                                                 |
| `--task-type TYPE`                                     | all           | Filter by type: `symbol_extraction`, `fn_call_graph`, `review_assistance`, `code_quality`, `develop_blast_radius`, `debug_from_trace`, `feature_scaffolding`, `real_issue`                               |
| `--arm plain\|codemap\|A_plain\|B_auto\|C_strict\|all` | `all`         | Run one legacy arm, one canonical A/B/C arm, or both legacy arms                                                                                                                                         |
| `--model haiku\|sonnet\|opus`                          | `haiku`       | Model tier                                                                                                                                                                                               |
| `--run-all`                                            | off           | Required when `--tasks` and `--task-type` both absent                                                                                                                                                    |
| `--no-save`                                            | off           | Skip writing JSONL results to `results/bench-<model>-<ts>.jsonl`                                                                                                                                         |
| `--timeout N`                                          | model default | Per-run wall-clock timeout in seconds                                                                                                                                                                    |
| `--resume`                                             | off           | Reuse a matching prior result (same `task_id`/`arm`/`model` + `repo_sha`/`index_sha`/`task_hash` provenance) from `results/bench-*.jsonl` instead of re-executing it; reused lines carry `resumed: true` |
| `--profile dev\|release`                               | none          | Cost profile — `dev` = haiku-only stratified subset (fast regression signal), `release` = full matrix incl. RI. Absent → current behavior unchanged                                                      |
| `--tiered`                                             | off           | Tiered protocol (release companion): run one tier per `--model` (haiku full → sonnet dev-subset → opus disagreements). See **Cost profiles** below                                                       |
| `--dry-run`                                            | off           | Validate locked canonical inputs and print the planned A/B/C cells; never invoke Claude or write model results                                                                                           |

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

- Native target-project test pass rate after fixes; canonical Claude and Codex executable stages use benchmark-owned behavior oracles because project dependencies are intentionally absent from the agent sandbox
- Semantic correctness beyond structural keyword matching
- Tasks sampled from real developer activity (issues, PRs, maintenance logs)
- Code quality judgment or review quality beyond structural metrics

`tasks-bench.json` contains 60 tasks across 11 series: structural research (SE / FN / RV / CQ / BR), debug trace analysis (DG), feature scaffolding (FT), real GitHub issues (RI), staged diff-impact (DI), graph queries (GR), and module import fan-in (MB). Core series model the pre-implementation structural research phase; DG/FT/RI cover broader developer workflows; DI/GR/MB add staged-change blast radius, whole-graph navigation, and module-level reverse-import blast radius. No tasks require a code output or a test run — the DI series stages a synthetic change but reverts it after both arms and never asks for a patch.

### Extensions

- **Tier E** (hard): End-to-end patch tasks (`tasks-patch.json`, PT-01–PT-05). Five historical revisions carry committed pre-fix coordinates, hidden reference patches, staged target-test fixtures, regression commands, and task-local index locks. Select them with the unified Codex `--tasks=PT` family selector or Claude `--study patch`; both five-task/15-cell no-model preflights and all five reference-patch lifecycles pass against the prepared frozen indexes. The current checksum-valid full scopes are `benchmarks/results/claude-patch-post-lifecycle-9e7bbb02bc3a` and `benchmarks/results/codex-patch-post-lifecycle-4119d30180f3/patch`. Both preserve every valid and invalid candidate outcome, prove strict-query delivery, patch transport, containment, clean rollback, targeted-oracle execution, regression safety, and cleanup, and are never pooled across providers/models. Earlier paid artifacts remain immutable diagnostic provenance only.

Patch scope admission fingerprints the absolute pytest launcher selected by the operator environment, its Python interpreter, pytest module/version, and installed pytest entry-point set. Every dry-run first admits each arm's Codex/Codemap integration against the clean historical worktree, then stages the frozen target-test fixture and executes its real regression=0/target=1 baseline predicate before printing a paid approval; paid execution follows the same order before model transport. This preserves the integration's clean-context invariant without weakening the patch fixture, and failures report the task, command, exit code, and bounded output. Target-project dependencies and pytest plugins intentionally come from that prospectively recorded runtime, while `PYTHONPATH` gives the disposable historical worktree source precedence. The emitted paid command carries the admitted launcher through `CODEMAP_BENCH_PATCH_PYTEST`, so an activated shell cannot silently switch the paid run to another pytest runtime.

Patch progress rows always render the semantic score to three decimals. The leading `✓` or `✗` reports pooling eligibility, while `patch` and `oracle` expose the executable gates; a visible score on an ineligible row never places that row in paired efficiency or quality aggregates.

The current Claude Patch scope has two valid A/C pairs (PT-01/02): equal 2/2 quality with strict C/A `0.852×/0.731×/0.716×/0.667×/0.712×` gross input, fresh input, output, commands, and elapsed time; strict C alone also passes PT-03 and PT-05, while PT-04 fails in every Claude arm. The current Codex Patch scope has three valid A/C pairs (PT-01/02/03): equal 3/3 quality with strict C/A `0.772×/0.872×/0.900×/0.950×/0.912×` gross input, fresh input, output, commands, and elapsed time. Codex PT-04/C and PT-05/C remain independent-oracle failures despite exact successful strict queries. The comparable strata are one repetition, one frozen Lightning family, and different provider/model transports; these results support quality parity and adaptive retrieval, not a universal Patch efficiency claim.

W5 broader generalization is explicitly deferred with zero paid cells. The program maintainer/parent owns reopening it for cross-repository external validity only after committed hash-locked issue/PR snapshots, deterministic generation and ordering, exact source/merge/pre-fix/test evidence, independently scored runtime/oracle contracts, and prospective limits on tasks, repositories, providers, models, repetitions, timeout, paid-cell count, and cost/time. Current terminal evidence therefore remains limited to Lightning exact revisions and named provider/model strata; no universal or cross-repository claim is made.

### Fix-task benchmark families (agentic benchmark)

Four suite files extend the benchmark from pure structural discovery into read-crop selection, executable edits, and patch application:

| Family            | Suite                   | Tasks       | Canonical P1 scoring                                         | Daily-work proxy                                                  |
| ----------------- | ----------------------- | ----------- | ------------------------------------------------------------ | ----------------------------------------------------------------- |
| `readcrop`        | `tasks-readcrop.json`   | RC-01–RC-06 | Source extraction oracle + context/token telemetry           | Read only the smallest sufficient source slice                    |
| `fix_single`      | `tasks-fix-single.json` | FS-01–FS-04 | Clean patch apply + exact path + independent behavior oracle | Single-file bug fix with independent executable validation        |
| `fix_multicaller` | `tasks-fix-multi.json`  | FM-01–FM-03 | Clean patch apply + exact paths + complete-caller AST oracle | Signature change + callers — codemap's edit-assist differentiator |

**Isolation**: the canonical Claude and Codex P1 paths create a benchmark-owned disposable worktree, expose only its checkout to the agent, capture the canonical Git diff outside the agent session, apply it to a second clean scoring worktree, run the independent oracle, and verify both cleanups. The original codebase is never mutated. The historical Claude `--study agentic` lane retains its earlier copy-and-`diff -ru` diagnostic scorer and is never pooled with canonical P1 evidence.

Claude `C_strict` requires two linked observations: the installed `/codemap-py:query-code` Skill must launch and its exact underlying `codemap-py query` or legacy `scan-query` command must complete successfully against the frozen checkout. Loading the Skill or merely attempting a denied command is not query evidence. The benchmark prepends the scope-locked repository plugin fixture to PATH and hashes the invoked `bin/codemap-py`; it never discovers a mutable user-cache version. Any attempt to rebuild the frozen index contaminates the cell. Absolute paths outside the disposable checkout are recorded as attempted diagnostics, but only a successful external access can leak bytes and exclude the cell from pooling. Canonical A/B/C cells disallow nested Agent/Task sessions because parent telemetry cannot account for child usage.

The selected artifact `results/claude-readcrop-aff1ece479cf` is checksum-valid diagnostic evidence but is rejected from admission. Its RC-01 query was permission-denied, while RC-02 changed into the plugin repository, retried a stale index, searched the user's home directory, and read another environment's installed Lightning source. Both answers scored correctly, but neither C cell satisfies the repaired strict treatment and the reported RC-02 token outlier is not valid efficiency evidence.

The follow-up artifact `results/claude-readcrop-cd23af087f68` is also checksum-valid diagnostic evidence and is rejected. Every C query was denied before execution: RC-01/C made 17 commands with 10 permission denials and RC-02/C made 18 commands with 8 permission denials, yielding zero successful Codemap calls despite `codemap=✓` in the historical renderer. The C input totals (`431.3k` and `356.9k`) are exactly the provider's uncached plus cache-creation plus cache-read accounting and reflect retry/cache churn, not Codemap result size. A/B failures in that artifact were also overstated when denied external path guesses were treated as successful contamination. The repaired parser reports Codemap use only after a successful query, separates attempted from successful external paths, and renders each interactive result row in one arm color with Rich semantic highlighting disabled.

The checksum-valid selected artifact `results/claude-readcrop-a27396a66a4e` validates the repaired permission route. Both C cells launch the installed Skill, execute the exact frozen query, remain checkout-isolated, and match A's quality. Across RC-01 and RC-02, C reduces aggregate gross input by 58.4%, fresh input by 55.8%, output by 43.5%, commands by 73.3%, and elapsed time by 39.9% relative to A. RC-01/B's displayed failure is a scorer-only false positive: the parser treated the slash in the relative `*/lightning/pytorch/core/*` shell glob as an absolute path even though the subsequent source read stayed in the disposable checkout. Current-parser replay admits the B cell; the immutable artifact is not rewritten. This selected two-task result validates treatment delivery but does not replace the full six-task Claude ReadCrop run.

The checksum-valid full artifact `results/claude-readcrop-8c605ce4f83e` completes 18/18 correct, compliant, uncontaminated, pooling-eligible cells with exact strict queries 6/6. At equal A/C quality, C reduces aggregate gross input by 25.74%, fresh input by 24.62%, output by 13.78%, commands by 39.39%, and elapsed time by 11.74%. Four tasks show clear C reductions; RC-01 is near gross-input parity, while RC-04/C costs 2.377× A input because Haiku misanchors the complete query's repository-relative `src/...` path under the installed Skill directory, retries two queries, and reads the full file. The first RC-04 query is exact, complete, and only 1,998 bytes, so this is not Codemap engine or payload cost. The production query contract now states that returned relative paths use the caller repository root and that a complete result must not trigger re-query or read/grep verification. B is canary-only; in this run it uses Codemap in five of six cells and reduces aggregate gross input by 31.81% versus A.

Only `query-code` uses command-specific Claude `allowed-tools`, and it declares both the PATH and installed absolute `codemap-py query` forms. The other Codemap Claude Skills intentionally declare generic `Bash`, which already covers their documented shell commands; command-specific duplicates are neither required for permission nor desirable for maintenance. Skill-declared permissions and the benchmark runner's outer headless `--allowedTools` policy remain separate enforcement layers.

**FM-03 is the revised cross-file test**: cooperative `Strategy.setup_environment` propagation spans `strategy.py`, `ddp.py`, `fsdp.py`, `deepspeed.py`, `model_parallel.py`, and `xla.py`; `single_xla.py` is intentionally excluded because it does not participate in this override contract. The prior `Strategy.setup` contract was invalid: these overrides are full replacements, so adding `super().setup` would repeat stateful setup. The strict Codemap arm uses an unlimited same-name symbol query to discover candidates, then verifies inheritance and the production package boundary from source; `fn-rdeps` is not an inheritance query. The plain arm must discover the same surface with ordinary repository tools. Exact changed-path validation captures whether the right files were actually changed. This remains the first benchmark family that directly measures whether Codemap reduces missed override candidates in a real multi-file edit, but only the revised task is admissible.

```bash
# Claude ReadCrop no-model admission; output includes the exact fresh paid command
python3 benchmarks/run-claude-agentic.py \
    --study readcrop \
    --repo-path /path/to/pytorch-lightning \
    --index /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \
    --model haiku \
    --tasks RC-01,RC-02 \
    --dry-run

# Claude Fix-Single no-model admission; output includes the exact fresh paid command
python3 benchmarks/run-claude-agentic.py \
    --study fix-single \
    --repo-path /path/to/pytorch-lightning \
    --index /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \
    --model haiku \
    --tasks FS-01,FS-02,FS-03,FS-04 \
    --dry-run

# Claude Fix-Multi no-model admission; omitted --tasks selects the full FM suite
python3 benchmarks/run-claude-agentic.py \
    --study fix-multi \
    --repo-path /path/to/pytorch-lightning \
    --index /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \
    --model haiku \
    --dry-run
```

**Scoring**: canonical Claude and Codex executable stages share the provider-neutral contracts and isolated patch executor. The baseline must fail its task-specific independent oracle; the patch must apply with ordinary `git apply --check`, touch exactly the allowed source paths in any order, pass that oracle, preserve the frozen source and index, and leave no worktree behind. Fix-Multi requires every caller or override declared by its contract. Task prompts preserve discovery as measured work rather than disclosing caller names or counts, and C receives a task-fit query: `fn-rdeps` for direct callers and unlimited `find-symbol` candidates plus source verification for overrides. Provider transport, native usage, and raw events remain provider-local; Claude reports unavailable native `tool_result_tokens` as `null` and the field is excluded rather than estimated. ReadCrop, Fix-Single, Fix-Multi, and Patch are separate strata and are never pooled with structural or historical agentic rows. The dry run is the only source of the paid scope hash: it emits a lowercase 16-character SHA-256 prefix accepted by `--paid-approval`; the complete 64-character scope remains recorded in provenance and is accepted too. Copy the exact command, use a fresh output directory, and do not use any separate paid-mode flag.

```bash
# Codex Fix-Single tasks: inspect the plan, then omit --dry-run for approved execution
python3 benchmarks/run-codex-structural.py --repo-path /path/to/pytorch-lightning --model gpt-5.6-luna --tasks FS-01,FS-02 --dry-run

# Codex Fix-Multi task: the same task-driven runner routes by FM-* ID
python3 benchmarks/run-codex-structural.py --repo-path /path/to/pytorch-lightning --model gpt-5.6-luna --tasks FM-01 --dry-run
```

Omitting `--tasks` runs all 73 locked tasks (219 A/B/C cells); use an explicit family, exact-ID, or mixed selector for a targeted nonpoolable scope. ReadCrop, Fix-Single, Fix-Multi, and Patch results retain separate stage artifacts and scorers.

## Results

`results/` holds all past run outputs:

| Pattern                                 | Source                                |
| --------------------------------------- | ------------------------------------- |
| `agentic-YYYY-MM-DD[-N].json`           | Agentic benchmark JSON snapshot       |
| `agentic-YYYY-MM-DD[-N].md`             | Agentic benchmark markdown report     |
| `bench-<model>-<YYYYMMDD-HHMMSS>.jsonl` | Real-codebase benchmark JSONL results |
| `code-YYYY-MM-DD[-N].md`                | Query benchmark markdown report       |

### Agentic blast-radius run — 2026-08-04 (⚠ unfinished)

`code-2026-08-04.json` / `code-2026-08-04.md` — killed by user at 62/144 cells (BA-01..BA-07 of 16 tasks; BA-08..BA-16 never ran). Single repetition (n=1), target `pytorch-lightning` 2.6.5. Numbers below describe what ran, not a confirmatory result.

<!-- result-sync: duplicated/summarized in ../plugins/codemap-py/README.md#claude-agentic-2026-08-04; update both files or record an explicit divergence note. -->

| Model  | Arm        |   n |     in tok |  out tok |    cost $ | elapsed s |     erec |     rrec |      aqs |  correct |
| ------ | ---------- | --: | ---------: | -------: | --------: | --------: | -------: | -------: | -------: | -------: |
| haiku  | A_plain    |   7 |     674.6k |     9.8k |     0.171 |     136.0 |     0.70 |     0.69 |     0.27 | **0.00** |
| haiku  | B_auto     |   7 | **281.3k** | **3.6k** | **0.091** |  **48.0** | **0.86** | **0.86** | **0.35** | **0.00** |
| haiku  | C_required |   7 |     362.1k |     4.2k |     0.097 |      57.2 |     0.85 |     0.85 |     0.30 | **0.00** |
| sonnet | A_plain    |   7 |     722.4k |    17.8k |     0.636 |     179.3 |     0.97 |     0.97 |     0.51 |     0.00 |
| sonnet | B_auto     |   7 | **251.6k** | **4.3k** | **0.310** |  **57.3** | **1.00** | **1.00** | **0.58** | **0.14** |
| sonnet | C_required |   7 |     370.0k |     4.9k |     0.311 |      60.1 |     0.97 |     0.97 |     0.57 | **0.14** |
| opus   | A_plain    |   7 |     238.3k |     9.2k |     0.497 |     116.8 |     0.57 |     0.57 |     0.32 |     0.00 |
| opus   | B_auto     |   7 |     299.6k |     6.2k |     0.529 |      88.0 | **1.00** | **1.00** | **0.61** |     0.00 |
| opus   | C_required |   6 | **173.6k** | **2.9k** | **0.344** |  **54.9** |     0.83 |     0.83 |     0.49 | **0.17** |

Bold = best value per model per column (lower is better for tok/cost/elapsed s, higher for erec/rrec/aqs/correct); ties bolded on both rows. `erec`/`rrec` = exposure/report recall of expected reverse-dependencies; `aqs` = mean `answer_quality_score`; `correct` = exact-match `answer_correct` fraction. Opus `C_required` n=6 — one cell excluded (`answer_error`).

**No single arm wins everywhere.** `B_auto` sweeps every metric on haiku and sonnet — cheapest and best recall, meaning the skill genuinely substitutes for manual exploration on those two models. Opus splits: `C_required` wins cost/tokens/elapsed/correct, `B_auto` wins recall/quality — opus under `B_auto` pays extra to explore on top of the skill without recovering any recall `C_required` didn't already have, making `C_required` the stronger opus arm on this partial data. Opus `A_plain` erec (0.57) is partly a markdown-fence parse artifact (fixed this session, not yet applied to this snapshot — see `rescore-claude-agentic.py`) but not entirely: 2 of 3 failing cells have genuinely malformed answer shapes even after unfencing. Full breakdown, per-cell `answer_error` list, and caveats: `code-2026-08-04.md`.

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

<!-- result-sync: summarized in ../plugins/codemap-py/README.md#codex-structural-2026-08-03; update both files or record an explicit divergence note. -->

| Arm        |   Correct | Mean quality | Mean gross input | Mean output | Mean elapsed |
| ---------- | --------: | -----------: | ---------------: | ----------: | -----------: |
| `A_plain`  |     34/45 |       0.8626 |           200.6k |       3,484 |       75.2 s |
| `B_direct` | **42/45** |   **0.9673** |           103.6k |       2,094 |       47.9 s |
| `C_skill`  |     40/45 |       0.9525 |        **74.0k** |   **1,420** |   **33.2 s** |

Bold = best comparable arm value per column (higher is better for correct and quality; lower is better for input, output, and elapsed time).

<!-- result-sync: summarized in ../plugins/codemap-py/README.md#codex-structural-2026-08-03; update both files or record an explicit divergence note. These pairwise rows use different baselines and are not cross-row comparable; retain values unbolded. -->

| Comparison |        Quality delta, 95% CI | Gross-input ratio, 95% CI |   Output ratio, 95% CI |  Elapsed ratio, 95% CI |
| ---------- | ---------------------------: | ------------------------: | ---------------------: | ---------------------: |
| B/A        | +0.1047 `[+0.0390, +0.1720]` |    0.735 `[0.580, 0.919]` | 0.775 `[0.596, 0.996]` | 0.800 `[0.644, 0.979]` |
| C/A        | +0.0900 `[+0.0204, +0.1605]` |    0.542 `[0.426, 0.681]` | 0.520 `[0.408, 0.663]` | 0.558 `[0.452, 0.685]` |
| C/B        | -0.0147 `[-0.0522, +0.0169]` |    0.738 `[0.644, 0.847]` | 0.672 `[0.602, 0.753]` | 0.698 `[0.636, 0.770]` |

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

#### Unified Structural checkpoint — 2026-08-11

The `benchmarks/results/codex-unified-88c93a32f471/structural` child completed all 165 Structural cells with checksum-valid telemetry, 165/165 successful transports, 165/165 scoreable answers, full treatment adherence, A Codemap use 0/55, and B/C Codemap use 55/55. The parent then stopped before the first ReadCrop model call because benchmark runner and manifest bytes changed while the three-hour Structural stage was active; the recomputed ReadCrop child scope no longer matched the admitted aggregate scope. This is a correct immutable-coordinate rejection, not a model, Codemap, task-selection, or progress-counter failure. The completed Structural child is preserved as descriptive evidence; the failed parent cannot be resumed or represented as a complete 68-task artifact, and the 13 remaining `RC,FS,FM` tasks require a fresh approval and result directory.

| Arm       | Clean headline pairs | Evaluator-correct | Mean quality | Mean gross / fresh input | Mean output | Mean elapsed |
| --------- | -------------------: | ----------------: | -----------: | -----------------------: | ----------: | -----------: |
| `A_plain` |                   45 |             37/45 |       0.9046 |           203.9k / 31.1k |       3,787 |       89.4 s |
| `C_skill` |                   45 |             42/45 |   **0.9770** |       **111.1k / 18.7k** |   **1,697** |   **43.8 s** |

Across the 45 decision-grade A/C pairs, C increased mean quality by 0.0724, reduced mean gross input 45.5%, fresh input 39.7%, output 55.2%, elapsed time 51.1%, and command calls 64.5%; the preregistered paired geometric-mean gross-input ratio was `0.560×`. C won/tied/lost quality on 12/31/2 tasks. On the common 44 clean B/C pairs, C improved mean quality by 0.0104 and reduced gross input 0.7%, fresh input 5.2%, output 13.8%, and elapsed time 19.6%, supporting the installed Skill over optional direct availability. Benefits concentrated in diff-impact, graph-reasoning, and review tasks. Feature scaffolding regressed from A quality 1.000 to C 0.900 and used 16.7% more gross input plus 38.7% more time; debug-from-trace retained perfect quality but used 41.8% more gross input, 140.9% more output, and 57.8% more time. Exact locked-query conformance was C 33/45 and B 19/45 on headline tasks, with C misses concentrated in DG and FT; treatment adherence remained 100% because exact query shape is a separate diagnostic.

The artifact remains descriptive rather than formally pooling-eligible because headline `RV-02/B_direct` and diagnostic `CQ-03/A_plain` failed answer extraction. The clean A/C headline comparison does not exclude any task, but this is still one model, repository revision, and repetition with heavy-tailed token usage. This partial current checkpoint is intentionally not synchronized into the plugin README; plugin-facing result claims remain frozen until a complete terminal artifact is accepted.

#### Current ReadCrop and executable-fix checkpoints — 2026-08-11

The checksum-valid children `benchmarks/results/codex-unified-6837a40300e9/readcrop` and `benchmarks/results/codex-unified-6837a40300e9/fix-single` completed 18/18 and 12/12 cells, respectively. That parent stopped before Fix-Multi because the installed Codex Rig package changed after aggregate admission. The separately approved `benchmarks/results/codex-unified-a860ca237d82/fix-multi` child then completed 9/9 cells with all 505 checksum entries valid. These are current stage-local descriptive checkpoints, not one resumable or terminal 68-task artifact.

| Stage                              |         A/C quality | C/A gross input | C/A fresh input | C/A output | C/A commands | C/A elapsed | Decision                                                                                                                                                   |
| ---------------------------------- | ------------------: | --------------: | --------------: | ---------: | -----------: | ----------: | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ReadCrop                           |       `6/6` / `6/6` |        `0.562×` |        `0.917×` |   `0.691×` |     `0.583×` |    `0.703×` | C selects substantially less context at equal source-answer quality.                                                                                       |
| Fix-Single                         |       `4/4` / `4/4` |        `1.101×` |        `1.575×` |   `1.428×` |     `1.158×` |    `1.240×` | Forced retrieval adds cost without a quality gain when the exact file and symbol are already supplied.                                                     |
| Fix-Multi (superseded FM-01/FM-03) |                 `—` |             `—` |             `—` |        `—` |          `—` |         `—` | Retained as diagnostic provenance only; FM-02 remains accepted and the revised W3 evidence is reported in the current acceptance section.                  |
| Fix-Multi (revised W3)             | `varied` / `varied` |        `varied` |        `varied` |   `varied` |     `varied` |    `varied` | P1.3 accepted as a bounded harness/heterogeneous-evidence milestone; valid A/C pairs are reported above and incomplete pairs are excluded from efficiency. |

The superseded Fix-Multi totals are deliberately not interpreted: the old FM-03 task required `super().setup` in full-replacement strategy overrides and therefore measured an invalid contract. The accepted FM-02 evidence and revised W3 results are multi-file quality/control evidence, not a suite-wide efficiency claim. Production guidance remains adaptive: skip Codemap when a localized edit has no unresolved structural fact; query the smallest relevant caller, dependency, importer, source-slice, test-impact, or override-candidate surface when scope is uncertain. `C_strict` remains a forced-use treatment and therefore intentionally measures the localized-edit overhead rather than simulating that production skip decision.

`B_auto` remains a canary rather than the decision-grade comparison. In ReadCrop it used Codemap on all six tasks but cost `1.736×` A gross input and missed RC-03; in Fix-Single it made no Codemap calls and reproduced plain-like quality/cost. The revised Fix-Multi B rows are retained for treatment/adoption context and are not used to claim adaptive benefit. This pattern supports installed adaptive guidance over mere optional CLI availability; P1 closes without forcing a favorable B outcome.

#### Current Claude Fix-Multi diagnostic — 2026-08-12

`benchmarks/results/claude-fix-multi-f16f4b86418d` is checksum-valid but rejected for P1 acceptance. FM-01 A/B/C all applied patches but scored `quality=0.000` because the implementations omitted the required explicit `should_stop` value in the dry-run log; this is a genuine task failure, not an oracle-only false negative. FM-02 A/B/C all passed the patch and independent oracle at `quality=1.000`, so that task's evidence remains accepted. FM-03 A and C applied exact-path patches but failed the independent oracle, while B timed out after producing an incomplete result; the task itself was invalid because `Strategy.setup` overrides are full replacements and a required `super().setup` call would duplicate stateful setup. The artifact is therefore nonpoolable for FM-01/FM-03 and does not establish a Claude provider or Codemap-engine regression.

The revised canonical FM-03 task targets cooperative `Strategy.setup_environment` propagation across six production files, with behavior fingerprints that preserve existing setup semantics. The selected A/B/C reruns on both providers are now complete under fresh scope locks; the old Codex and Claude FM-03 artifacts remain immutable historical diagnostics and are not pooled with the revised task.

#### Current Fix-Multi W3 acceptance — 2026-08-12

The revised six-cell scopes completed with valid immutable artifacts: Claude Haiku `benchmarks/results/claude-fix-multi-f2719755cb23`, Claude Sonnet `benchmarks/results/claude-fix-multi-243a7e2174ea`, and Codex Luna `benchmarks/results/codex-unified-91752e388e4e/fix-multi`. Stored row glyphs and quality values remain exactly as emitted. Independent prospective replay corrects only the semantic interpretation of harmless method-docstring changes and the FM-01 decision-log verbosity gate; it does not rewrite telemetry or manufacture favorable rows.

| Provider/model | Task  | Valid A/C semantic result                                 | C/A gross input | C/A output | C/A commands | C/A elapsed | Admission judgment                                       |
| -------------- | ----- | --------------------------------------------------------- | --------------: | ---------: | -----------: | ----------: | -------------------------------------------------------- |
| Claude Haiku   | FM-01 | A/B/C fail (`reason`/verbose-gated)                       |               — |          — |            — |           — | Exclude efficiency; retain all three failures.           |
| Claude Haiku   | FM-03 | A/C pass; B's docstring-only change is semantically valid |        `0.228×` |   `0.682×` |     `0.396×` |    `0.534×` | Bounded Codemap efficiency win on this valid pair.       |
| Claude Sonnet  | FM-01 | A/B pass prospectively; C fails verbose gate              |               — |          — |            — |           — | Exclude efficiency because the A/C pair is incomplete.   |
| Claude Sonnet  | FM-03 | A/C pass; B's docstring-only change is semantically valid |       `~0.616×` |  `~0.394×` |    `~0.679×` |   `~0.529×` | Bounded Codemap efficiency win on this valid pair.       |
| Codex Luna     | FM-01 | A/B/C pass                                                |        `1.189×` |   `1.377×` |     `1.000×` |    `1.283×` | Correctness parity with an efficiency loss for forced C. |
| Codex Luna     | FM-03 | A/B/C pass                                                |        `1.021×` |   `0.870×` |     `1.429×` |    `0.889×` | Correctness parity with mixed efficiency.                |

The scientific admission rule is to retain valid failures rather than rerun until a favorable outcome appears. `A_plain` versus `C_strict` remains the decision-grade comparison and `B_auto` remains a canary; incomplete A/C pairs are excluded from efficiency ratios but remain visible in the artifact record. The combined evidence supports adaptive production guidance—use Codemap when the edit has unresolved structural scope, and skip it for a fully localized edit—not a claim that Codemap universally improves multi-file edits. The runner now derives the leading progress glyph from pooling eligibility and persists the exact scored Claude diff plus SHA-256 in future executable artifacts; historical artifacts remain immutable and do not require a paid rerun for P1 closure.

#### Current Claude Fix-Single full checkpoint — 2026-08-11

The checksum-valid `benchmarks/results/claude-fix-single-5647f59aeeba` artifact executes the complete four-task Fix-Single suite rather than a favorable selected subset: FS-01 through FS-04 × A/B/C = 12/12 persisted cells. All cells use distinct provider sessions, pass the independent executable oracle and exact changed-path boundary, clean up their disposable checkout, remain uncontaminated and accounting-consistent, and score quality `1.000`. Every C cell launches the installed Skill and completes its frozen exact query. The paid approval `f8bc2b2746115092a8178bdf67167899e68c6cef9705b17ee36524739919da9e` binds the model, source/index, all four task/prompt/oracle hashes, all three arms, runner, treatment artifacts, and 12-cell scope; the snapshotted task suite matches the repository suite SHA-256 `2316927ea63da21f45752e33e3dc884aae0913faff2bf1d5fc5730abd39c446a`, whose task definitions predate this run.

| Scope                     |   A/C quality | C/A gross input | C/A fresh input | C/A output | C/A commands | C/A elapsed |
| ------------------------- | ------------: | --------------: | --------------: | ---------: | -----------: | ----------: |
| Four-task totals          | `4/4` / `4/4` |        `0.898×` |        `0.770×` |   `0.947×` |     `0.708×` |    `0.622×` |
| Equal-task geometric mean | `4/4` / `4/4` |        `0.859×` |        `0.761×` |   `0.931×` |     `0.690×` |    `0.671×` |

| Task  | A/C quality | C/A gross input | C/A output | C/A commands | C/A elapsed | Interpretation                                                                |
| ----- | ----------: | --------------: | ---------: | -----------: | ----------: | ----------------------------------------------------------------------------- |
| FS-01 |   `1.0/1.0` |        `0.687×` |   `0.837×` |     `0.600×` |    `0.275×` | Strict navigation avoids repeated path discovery at equal executable quality. |
| FS-02 |   `1.0/1.0` |        `0.755×` |   `0.830×` |     `0.636×` |    `0.797×` | Strict navigation wins modestly on every measured efficiency dimension.       |
| FS-03 |   `1.0/1.0` |        `0.998×` |   `1.007×` |     `0.692×` |    `0.945×` | Token parity: fewer commands do not materially change token consumption.      |
| FS-04 |   `1.0/1.0` |        `1.051×` |   `1.073×` |     `0.857×` |    `0.981×` | Honest loss: forced Codemap adds 5.1% gross input and 7.3% output.            |

This checkpoint's primary success is executable-quality parity; lower token use is secondary and heterogeneous. It is not evidence of universal Codemap savings: FS-04's regression is retained, the prior Claude full diagnostic records C/A `1.077×` gross input and `1.559×` elapsed when one C cell missed its required query, and the current Codex Fix-Single checkpoint records C/A `1.101×` gross input and `1.240×` elapsed. `B_auto` also made no Codemap call in this Claude run and cost `1.043×` A gross input, preserving an unfavorable canary instead of filtering it out. These disclosed counterexamples, the complete pre-existing task scope, immutable input snapshots, and checksums support non-selective reporting; they cannot prove absence of deliberate fabrication by themselves. Remaining limits are one repetition, fixed A→B→C order, provider prefix-cache state, one repository/model, and four localized synthetic tasks spanning only two source files. Production guidance therefore remains adaptive: require Codemap where a structural fact is unresolved, but accept plain-tool parity or skip retrieval when the exact edit location already makes discovery trivial.

#### Combined codemap-py 0.28.7 structural execution — 2026-08-07

The frozen `benchmarks/results/codex-combined-20260807T130711Z/structural` execution persisted all 165 cells under machine manifest `0ae79d69d1cabf6b020afa419bffa196b690191ee7a2c1dd2307ae08a8adb7ee`, `gpt-5.6-luna` at high effort, observed Codex CLI 0.146.1, codemap-py 0.28.7, codex-rig 0.4.6, Lightning 2.6.5 commit `be98784`, and schema-13 index `3c5840893e9c939baa61a6c5ce95994ff69ffe4a67d225aeb412c73deb61e0c1`. All 329 listed checksums and the recursive frozen-source checksum ledger verify. The run is descriptive and nonpoolable: 164/165 cells succeeded, `DI-03/C_skill` was contaminated and incomplete, `RV-04/C_skill` exposed an answer-extraction gap, `SE-04/C_skill` omitted the requested source, and diagnostic `CQ-03/A_plain` also failed extraction. The comparable table therefore uses the common 43-task headline cohort after excluding the complete `DI-03` and `RV-04` triplets; it does not hide the full-run failures stated above.

<!-- result-sync: duplicated/summarized in ../plugins/codemap-py/README.md#codex-structural-2026-08-07; update both files or record an explicit divergence note. -->

| Arm        | Mean quality | Mean gross input | Mean output | Mean elapsed | Required-use compliant | Exact locked query |
| ---------- | -----------: | ---------------: | ----------: | -----------: | ---------------------: | -----------------: |
| `A_plain`  |       0.9060 |           199.3k |       3,820 |       86.4 s |                    N/A |                N/A |
| `B_direct` |       0.9682 |       **103.9k** |       1,962 |       49.4 s |              **43/43** |              14/43 |
| `C_skill`  |   **0.9875** |           124.5k |   **1,629** |   **43.4 s** |              **43/43** |          **41/43** |

Bold = best comparable arm value per column (higher is better for quality and conformance; lower is better for token and elapsed measures). Required use and exact-query conformance are fidelity diagnostics, not quality metrics.

| Comparison | Descriptive mean-quality delta | Total gross-input ratio | Per-task input saving: median `[p10, p90]`, observed range | Output ratio | Elapsed ratio |
| ---------- | -----------------------------: | ----------------------: | ---------------------------------------------------------: | -----------: | ------------: |
| B/A        |                        +0.0622 |                 0.5215× |                34.8% `[-44.2%, 74.0%]`, `[-446.8%, 90.1%]` |      0.5136× |       0.5717× |
| C/A        |                        +0.0815 |                 0.6246× |                 35.2% `[-47.6%, 81.1%]`, `[-97.4%, 96.2%]` |      0.4264× |       0.5028× |

The ranges prevent an aggregate-saving claim from hiding task-level explosions: B used up to 446.8% more input than plain and C up to 97.4% more, while their best tasks saved 90.1% and 96.2%. B used less input on 34/43 common tasks and C on 29/43; each exceeded 1.5× plain input on four tasks. `BR-08/C_skill` is the clearest C outlier at almost twice plain input despite equal quality. Exact locked-query conformance improved to 43/45 across all C headline tasks, including the failed exact-query `DI-03` cell, while B reached only 14/45. Raw telemetry SHA-256 is `142672b860ff1d270b3e1b5e04c66cb25cc6d7741b58df9158d866acabb2bcd6`; canonical telemetry is `fecfdfbc54262215633465a70664d6d866abe08d38536a0e98561e3dc1f2e25c`; metadata is `8381a326add000bf801f4c6c481c600330e8203bb4860c9edb9f9508424083c0`.

**Post-run diagnosis.** The repaired C route contract now follows the exact locked headline query on 43/45 tasks and restores `CQ-04`, `CQ-05`, the scoreable DI tasks, and `FT-05`. The remaining structural blockers are narrower. `DI-03/C_skill` ran the exact two compact queries and produced the expected answer, but postflight detected an unexpected worktree change; telemetry records only the generic contamination error rather than the observed path/status, so the isolation defect cannot yet be localized. `RV-04/C_skill` returned the correct count in a natural phrase unsupported by the count extractor, while `SE-04/C_skill` genuinely failed to include the requested source. `FT-01/B_direct` scored `0.500`, B exact-query fidelity remains 14/45, and the `BR-08/C_skill` token explosion shows that strict routing is not a per-task efficiency guarantee. These are P0 benchmark observability/evaluator and focused route-calibration gaps; they do not justify rewriting the immutable artifact or claiming a query-engine defect.

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

| Treatment  | Correctness by family                             | Quality by family                                   | Gross input   | Elapsed       | Adherence |
| ---------- | ------------------------------------------------- | --------------------------------------------------- | ------------- | ------------- | --------- |
| `A_plain`  | DI-01 **`0/3`**, GR-01 **`3/3`**, GR-03 **`3/3`** | DI-01 `0.367`, GR-01 **`0.767`**, GR-03 **`1.000`** | see telemetry | see telemetry | **9/9**   |
| `B_direct` | DI-01 **`0/3`**, GR-01 **`3/3`**, GR-03 **`3/3`** | DI-01 **`0.500`**, GR-01 `0.700`, GR-03 **`1.000`** | see telemetry | see telemetry | **9/9**   |
| `C_skill`  | DI-01 **`0/3`**, GR-01 **`3/3`**, GR-03 **`3/3`** | DI-01 `0.333`, GR-01 `0.700`, GR-03 **`1.000`**     | see telemetry | see telemetry | **9/9**   |

No pooled interval or treatment-effect estimate is reported for this selected scope: it is targeted, non-poolable diagnostic evidence with only three task families. Gross-input and elapsed comparisons remain available in the immutable telemetry for audit, but are not a headline result.

**Validity and interpretation.** All 27 selected cells completed and passed artifact integrity, but the run is explicitly non-poolable. The offline replay classifies all 27 cells as treatment-adherent and reports seven semantic query-shape misses: C `DI-01` (3), B `DI-01` (1), and B `GR-01` (3). `DI-01` binary correctness is 0/3 for each arm because the returned test-module identity did not match the locked oracle; `GR-01` is 3/3 for each arm and `GR-03` is 3/3 for each arm. These targeted results do not establish a causal Codemap advantage, confirmatory effect, or cross-provider raw-token comparison. The offline replay is diagnostic derived evidence only; the raw and canonical telemetry remain immutable and no active acceptance claim depends on the replay.

The selected run confirms the repaired parser and evaluator plumbing but also keeps the remaining query-shape mismatch visible. Root fixes now include unquoted `$CODEMAP_BIN` parsing, preserved Markdown message boundaries, provider-neutral DiffImpact caller-and-test precision/recall F1, scanner normalization to `tests_fabric...`, production-only `central --exclude-tests` in-degree, direct `fn-rdeps` versus explicit transitive `fn-blast` guidance, and fail-closed offline rescore.

The follow-up 18-cell validation at `benchmarks/results/codex-integration-selected-20260803T160316Z` completed all coordinates with zero treatment, contamination, extraction, completeness, or token-accounting failures; all 491 checksums verify. Raw/canonical/metadata SHA-256 values are `26535b20a9e2511df30a3277e0364128c4d96ff6254d2f031c07fa62e21a5705`, `c240dd4e366028149cb8530efd37295bcedd1fe4af3d911ae8bbd309a20e289e`, and `bd8cd8ed0eeac3ed79e874fd97486cc219c937300441ca57fb2edfe645235da6`.

| Task    | A quality | B quality | C quality | B/A input · elapsed | C/A input · elapsed |
| ------- | --------: | --------: | --------: | ------------------: | ------------------: |
| `DI-01` |   `0.500` | **1.000** |   `0.501` | `1.603×` · `0.909×` | `1.008×` · `0.989×` |
| `GR-01` |   `0.733` |   `0.600` | **1.000** | `0.282×` · `0.136×` | `0.197×` · `0.089×` |

These are paired geometric economy ratios and arithmetic mean quality over three repetitions. They are descriptive because the scope is targeted and non-poolable. C achieved quality parity on DI and improved GR while using much less input overall, but DI showed no stable input saving and B degraded on GR. Raw events establish deterministic causes: the GR prompt omitted the oracle's exclude-tests scope, while the Skill mapped DI's direct-import test request to transitive module `test-impact` and returned 247 tests. The semantic audit also checked only the caller half of DI. The shared task prompt now states production-only centrality; all DI tasks require exact caller and direct-importer queries; both runtime Skills reserve `test-impact` for transitive affected-test selection. A new bounded validation is required before the full study can be unlocked.

The corrected bounded gate at `benchmarks/results/codex-integration-selected-20260803T172707Z` completed 18/18 cells and verified all 491 checksums under the current manifest and selected-scope locks. Raw/canonical/metadata SHA-256 values are `1b20bb6756d9e301215b20cbc6bd90b01c6798667ee2be7a261be819604e8c77`, `2c810e840f2f9f03c6b8bd2a976f13c12df1a4cee3e46051b255add7dff106cf`, and `d6f4e0a71a52cb05d849a10d7635e3b4579f13c570694cf871e2574ccfd0c8b4`.

| Task    | A quality | B quality | C quality |   B/A input · output · elapsed |   C/A input · output · elapsed |
| ------- | --------: | --------: | --------: | -----------------------------: | -----------------------------: |
| `DI-01` |   `0.500` | **1.000** | **1.000** | `0.842×` · `0.704×` · `0.826×` | `0.627×` · `0.494×` · `0.555×` |
| `GR-01` |   `0.800` | **1.000** | **1.000** | `0.356×` · `0.113×` · `0.300×` | `0.251×` · `0.081×` · `0.169×` |

The run has zero treatment, contamination, extraction, completeness, token-accounting, or execution failures. Its three semantic-query misses are all DI-01/B_direct: the direct model omitted one or both exact locked query components but still used Codemap and returned every expected caller and test module. C_skill matched the exact caller-plus-direct-import route in every repetition. The methodology records exact query fitness independently from treatment delivery, so the misses remain discoverability diagnostics rather than exclusion failures. The bounded operational gate passes and permits the separately authorized complete 165-cell study; this targeted run remains non-poolable and cannot satisfy confirmatory product acceptance.

The Claude adapter remains the repeatedly debugged reference; only shared methodology corrections apply to both providers, and no Claude quality change is implied by this Codex recovery work.

The run is retained for audit and follow-up, not silently mixed with Claude results. Audit the local artifacts with `benchmarks/results/codex-integration-selected-20260803T091057Z/checksums.sha256`; the ignored result directory is intentionally not a published fixture. The offline rescore is immutable-derived evidence, not a rewrite of paid telemetry.

</details>

### Multi-model results: real-codebase benchmark

#### Latest — 2026-07-29 (39 tasks × 2 arms × 3 tiers)

Full summary + per-task reading: [`results/bench-summary-2026-07-29.md`](results/bench-summary-2026-07-29.md). **codemap v0.27.0** · models `claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5` · symmetric-prompt harness (post 2026-07-03 fairness overhaul). Single run (n=1); DI/GR series (10 tasks) skipped pending ground truth. Sources: `bench-{haiku,sonnet,opus}-20260729-*.jsonl`. Ratios reported as **median / mean** of the per-task codemap/plain distribution.

**Two value axes — read separately, never blended.** (1) **Reliability/quality**: safety-grade + structural recall — codemap **13/13 safety-grade every tier** vs plain 8/13 → 12/13 → 13/13; the primary proposition, holds up-tier. (2) **Economy (cost/tokens/time)**: read at *matched caller fan-in* — the win grows with fan-in (cost 0.35× haiku / 0.54× opus on high-fan-in tasks); raw median token ratio is a *secondary, caveated* number that → 1 as models get terser. Accuracy Δ is a saturation-sensitive tie-breaker, not a headline.

<!-- result-sync: this is the canonical July 29 table; ../plugins/codemap-py/README.md#three-model-comparison contains the distinct June 22 legacy run, so do not synchronize their values. -->

| Tier      | Plain accuracy    | Codemap accuracy  | Δ accuracy | Safety-grade plain | Safety-grade codemap | Token× med / mean | Cost× med / mean |
| --------- | ----------------- | ----------------- | ---------- | ------------------ | -------------------- | ----------------- | ---------------- |
| Haiku 4.5 | 66.7% (24/36)     | **91.7% (33/36)** | **+25 pp** | 8/13               | **13/13**            | **0.57 / 0.65**   | **0.81 / 0.73**  |
| Sonnet 5  | 82.4% (28/34)     | **94.3% (33/35)** | **+12 pp** | 12/13              | **13/13**            | **0.82 / 0.93**   | **0.97 / 0.91**  |
| Opus 5    | **88.6% (31/35)** | 80.6% (29/36)     | −8 pp ⚠    | **13/13**          | **13/13**            | **0.83 / 0.96**   | **0.95 / 0.91**  |

Bold = better arm within each model and metric (higher accuracy/safety is better; token and cost ratios below `1.0` favor Codemap). Positive accuracy deltas are bolded; the audited Opus regression remains unbolded and caveated below.

Per-workflow codemap accuracy: query (n=28) 92.0 / 95.8 / 84.0%; debug (n=6) 100 / 100 / 100%; feature (n=5) 80 / 80 / **40% ⚠** (haiku / sonnet / opus).

> **⚠ The opus codemap figures are deflated by two harness bugs found in a post-run audit** — do not cite opus codemap −8 pp as a result. (1) The count-extraction regex (`run-claude-structural.py:1422`) grabs the first stray number in verbose codemap prose (RV-02/opus answered "65 modules", correct, but the regex read "0 symbols" → recall 0.000). (2) `codemap query methods used` (`:2975`) silently drops the method on non-pure-JSON tool output, so "index-lookup only" is a parse artifact — opus actually ran `rdeps` in ~17 runs. See the report's scoring banner + the bug list below. **RESOLVED (2026-07-29):** fixes landed; a 2-repeat opus re-run on the fixed scorer shows opus codemap = plain **100% / 100%** with codemap *better* on tail-recall (fewer missed callers, fewer turns) — the −8 pp was pure artifact, and the "codemap short-circuits opus" (anchoring) hypothesis is refuted 0/14. See the report's "Opus anchoring probe" section.

**Reading it**: codemap's lift is inversely proportional to model strength — biggest where native navigation is weakest (Haiku +25 pp, Sonnet +12 pp). The opus row shows codemap −8 pp **as measured**, but that is mostly the scoring artifact above (below-plain recalls on RV-02/CQ-03 are count-regex false-fails, not real misses); there is no per-model skill routing (both arms share one symmetric prompt), so the residual gap is model behavior, not a plugin defect. Token savings are real at Haiku, near break-even by Opus (fixed index-injection overhead); codemap is faster on wall-clock at every tier (median time× 0.81 / 0.95 / 0.92). The historical 2026-07-29 query report recorded **PARTIAL** (26/32); it is distinct from the current no-model diagnostic (14/18 primary and 10/14 self-consistency). The agentic run was **interrupted** and is not reportable this cycle.

**Why the gains look smaller than June 22 — comparability**: the drop in token savings (June 0.22–0.38× → July 0.57–0.83×) is **confounded** and cannot be attributed to the 5-series models alone. Three things changed at once between the two runs: (a) the **harness fairness overhaul** — June ran under codemap-favoring steering (codemap arm capped at 3 calls + forbidden to verify, plain arm coached toward more grepping), which by the README's own note made June ratios *upper bounds*; removing it raises the ratio toward 1.0 independent of model; (b) **model version** (Sonnet 4.6→5, Opus 4.6→5) — newer models navigate code better unaided, so the plain-arm denominator shrinks and the ratio rises even with codemap unchanged; (c) **codemap version** (pre-v0.13.2 → v0.27.0). To isolate the model-version effect you must hold the harness constant — run 4.6-era and 5-era models under the *current* fair harness. What *is* clean is the **within-July up-tier shrink** (0.57 → 0.82 → 0.83, one harness + one codemap version, only the tier varies): codemap injects a roughly fixed index blob while the plain arm's exploration cost falls as models strengthen → ratio → 1. So token savings are structurally largest where the plain baseline is most wasteful (weak models); on strong models the value proposition shifts from tokens to **structural recall / safety-grade** (8/13 → 13/13 at Haiku), which holds at every tier.

<details>
<summary><strong>Past experiments (pre-2026-07-03, stale)</strong> — June-22 real-codebase + older agentic runs, kept for history. Predate the fairness overhaul; not comparable with the latest above. Click to expand.</summary>

> **⚠ Stale (2026-07-03)**: all results below predate the fairness overhaul (symmetric arm prompts, AST-oracle ground truth, real C1/C2 metrics). Token ratios and FN/BR/RV/CQ accuracy were measured under codemap-favoring prompt steering and partially circular GT — treat as upper bounds; re-run pending.

Results — June 22 2026 — 44 tasks × 2 arms × 3 models, pytorch-lightning-master. **Models** `claude-haiku-4-5` / `claude-sonnet-4-6` / `claude-opus-4-6` · **codemap version not recorded in these result lines** (predates the v0.13.2 agentic run; ~mid-June 2026) · **codemap-favoring steering harness** (not comparable with the July run above — see comparability note).

<!-- result-sync: duplicated/summarized in ../plugins/codemap-py/README.md#three-model-comparison; update both files or record an explicit divergence note. All result tables in this historical block are canonical sources for downstream summaries. -->

| Model      | Plain accuracy    | Codemap accuracy  | Accuracy lift | Safety-grade plain | Safety-grade codemap | Token ratio (median) | Token ratio range |
| ---------- | ----------------- | ----------------- | ------------- | ------------------ | -------------------- | -------------------- | ----------------- |
| Haiku 4.5  | 85.3% (29/34)     | **93.9% (31/33)** | **+9 pp**     | 5/13               | **12/13**            | **0.38×**            | 0.04–68.2×        |
| Sonnet 4.6 | 83.8% (31/37)     | **91.9% (34/37)** | **+8 pp**     | 11/13              | **12/12**            | **0.22×**            | 0.05–1.21×        |
| Opus 4.6   | **86.1% (31/36)** | 91.7% (33/36)     | **+6 pp**     | **13/13**          | 12/12                | **0.31×**            | 0.05–1.46×        |

Bold = better arm within each model and metric (higher accuracy/safety is better; a token ratio below `1.0` favors Codemap). Positive lift is bolded; the range is descriptive and unbolded.

Safety-grade = fraction of FN + BR tasks with explicit recall where recall ≥ 0.90. Token ratio = codemap / plain input tokens. June 22 Haiku tok× max of 68.2× is RI-04 codemap `error_max_turns` (token spiral, fixed June 23). June 22 Opus codemap safety-grade 10/12: FN-02/BR-03 regressions fixed June 23 (both recall=1.000) — corrected post-fix safety-grade is **12/12**.

Per-workflow-type breakdown (codemap arm, tok× = median codemap/plain token ratio):

| Workflow type          | n tasks | Haiku tok× | Haiku cm_acc | Sonnet tok× | Sonnet cm_acc | Opus tok× | Opus cm_acc |
| ---------------------- | ------- | ---------- | ------------ | ----------- | ------------- | --------- | ----------- |
| query (SE/FN/RV/CQ/BR) | 28      | **0.28×**  | 95.0%        | **0.14×**   | 95.5%         | **0.23×** | 86.4%       |
| debug (DG)             | 6       | **0.33×**  | 100%         | **0.31×**   | 100%          | **0.39×** | 100%        |
| feature (FT)           | 5       | **0.55×**  | 100%         | **0.71×**   | 80%           | **0.58×** | 100%        |
| real_issue (RI)        | 5       | 3.36× ⚠    | 50%          | **0.85×**   | 75%           | **0.41×** | 100%        |

Bold token ratios below `1.0` indicate lower Codemap input than the same-model plain arm. Codemap-only accuracy columns have no displayed plain comparator and remain unbolded.

#### Haiku 4.5 — `results/bench-haiku-20260622-223206.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                                                              |
| --------- | ------------------------------------------------------------------ |
| Median    | 0.38× (62% reduction)                                              |
| Min       | 0.04× (FN-04)                                                      |
| Max       | 68.2× (RI-04, error_max_turns — arm-permission bug, fixed June 23) |

Note: max of 68.2× was RI-04 arm-permission bug (token spiral, fixed June 23) — not a normal operating point.

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed              | incomplete                       |
| ------- | --------- | -------------- | ------------------------------ | -------------------------------- |
| plain   | 85.3%     | 29/34          | 4 (SE-05, CQ-01, CQ-05, RI-04) | 2 (CQ-01, BR-04)                 |
| codemap | **93.9%** | **31/33**      | 3 (SE-05, CQ-03, CQ-05)        | 2 (RI-02, RI-04) ⟵ fixed June 23 |

By series:

| Series       | plain   | codemap | Notes                                                                                                                       |
| ------------ | ------- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| SE (5 tasks) | **4/4** | **4/4** | SE-05 ext-fail both arms                                                                                                    |
| FN (5 tasks) | **5/5** | **5/5** | Plain struggles (FN-01=0.769, FN-03=0.917); codemap perfect                                                                 |
| RV (5 tasks) | n/a     | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth    |
| CQ (5 tasks) | 1/3     | **2/3** | CQ-01 plain timeout; CQ-05 ext-fail both; CQ-03 codemap ext-fail                                                            |
| BR (8 tasks) | **8/8** | 7/8     | BR-07 codemap recall=0.778 < plain=0.889 ⚠                                                                                  |
| DG (6 tasks) | **6/6** | **6/6** | Both arms perfect; codemap saves 19–58% tokens                                                                              |
| FT (5 tasks) | **5/5** | **5/5** | Both arms perfect                                                                                                           |
| RI (5 tasks) | **4/5** | 1/3     | RI-01 codemap recall=0.667; RI-02/RI-04 codemap `error_max_turns` ⚠ (arm-permission bug — fixed June 23, both recall=1.000) |

**Safety-grade**: plain 5/13 → codemap 12/13 (June 22 run). BR-07 codemap recall=0.778 is the one miss. RI-02/RI-04 codemap `error_max_turns` were arm-permission bugs fixed June 23 (see `results/bench-haiku-20260623-003825.jsonl`, both recall=1.000).

#### Sonnet 4.6 — `results/bench-sonnet-20260622-235143.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                 |
| --------- | --------------------- |
| Median    | 0.22× (78% reduction) |
| Min       | 0.05× (BR-05)         |
| Max       | 1.21× (BR-03)         |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | 83.8%     | 31/37          | 1 (FT-03)         | 0          |
| codemap | **91.9%** | **34/37**      | 1 (FN-03)         | 0          |

By series:

| Series       | plain   | codemap | Notes                                                                                                                    |
| ------------ | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| SE (5 tasks) | **5/5** | **5/5** | Both arms perfect                                                                                                        |
| FN (5 tasks) | **4/5** | 3/4     | FN-02 plain=0.108 → codemap=1.000; FN-03 codemap ext-fail                                                                |
| RV (5 tasks) | n/a     | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth |
| CQ (5 tasks) | 3/5     | **4/5** | CQ-05 plain recall=^3.333 (over-count); codemap 4/5 correct                                                              |
| BR (8 tasks) | **8/8** | **8/8** | Both arms perfect; codemap saves 14–94% tokens                                                                           |
| DG (6 tasks) | **6/6** | **6/6** | Both arms perfect                                                                                                        |
| FT (5 tasks) | 4/4     | **4/5** | FT-03 plain ext-fail; FT-03 codemap recall=0.500 ⚠                                                                       |
| RI (5 tasks) | **4/5** | **4/5** | RI-01 both arms 0.667; RI-05 n/a both                                                                                    |

**Safety-grade**: plain 11/13 → codemap 12/12. Token savings primary codemap benefit at sonnet tier — query workflow median 0.14×.

#### Opus 4.6 — `results/bench-opus-20260622-230210.jsonl`

44 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                 |
| --------- | --------------------- |
| Median    | 0.31× (69% reduction) |
| Min       | 0.05× (BR-01)         |
| Max       | 1.46× (BR-02)         |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | 86.1%     | 31/36          | 2 (CQ-01, CQ-05)  | 0          |
| codemap | **91.7%** | **33/36**      | 2 (FN-03, RI-02)  | 0          |

By series:

| Series       | plain   | codemap | Notes                                                                                                                    |
| ------------ | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| SE (5 tasks) | **5/5** | **5/5** | Both arms perfect                                                                                                        |
| FN (5 tasks) | **4/5** | 2/4     | 🔴 FN-02: codemap recall=0.027 vs plain=1.000 (Δ=−0.97); FN-03 codemap ext-fail                                          |
| RV (5 tasks) | n/a     | n/a     | Scored in current runs (RV-01/05: symbol recall ≥0.70; RV-02/03/04: count ±10%); pre-June-23 runs had no RV ground truth |
| CQ (5 tasks) | 2/3     | **4/5** | CQ-02 codemap recall=0.100 < plain=0.250; CQ-03/04/05 codemap perfect; CQ-03 plain=0.265 → codemap=1.000                 |
| BR (8 tasks) | **7/8** | 6/7     | 🔴 BR-03: codemap recall=0.042 vs plain=1.000 (Δ=−0.96)                                                                  |
| DG (6 tasks) | **6/6** | **6/6** | Both arms perfect                                                                                                        |
| FT (5 tasks) | **5/5** | **5/5** | Both arms perfect                                                                                                        |
| RI (5 tasks) | **4/5** | 3/4     | RI-01 codemap recall=1.000 vs plain=0.667 (+0.33); RI-02 codemap ext-fail                                                |

**Safety-grade**: plain 13/13 → codemap 10/12 (June 22 run). FN-02 and BR-03 regressions were evaluator bugs — fixed June 23 (see `results/bench-opus-20260623-003745.jsonl`, both recall=1.000).

<details>
<summary><strong>Historical agentic benchmark — plain vs codemap vs semble — 2026-06-27 (obsolete)</strong></summary>

> **Outdated (2026-06-27).** This obsolete section reports Claude Haiku 4.5, Sonnet 4.6, and Opus 4.6. The exact Codemap execution version is unresolved: the section label says v0.13.2, while the run note records a v0.13.1 cache; the Semble package/MCP version was not recorded. Do not compare or pool these values with current results.

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

</details>
