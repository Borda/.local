# Codemap Benchmarks

Empirical validation for the `codemap` plugin — three independent benchmarks. The real-codebase benchmark is **repo-agnostic**: swap `tasks-bench.json` (which ships a `repo` header with name, namespace, and default clone path) to run against any Python codebase. Reference results use `pytorch-lightning-master`.

## Benchmark overview

| Benchmark                                                     | Script                      | LLM | Arms                                    | Tasks                                                 | Primary question                                                                   |
| ------------------------------------------------------------- | --------------------------- | --- | --------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [Agentic](#agentic-benchmark-run-codemap-agenticpy)           | `run-codemap-agentic.py`    | Yes | 4 (plain / codemap / semble / combined) | 16 import-graph tasks                                 | Does codemap/semble reduce exploration overhead vs grep?                           |
| [Real-codebase](#real-codebase-benchmark-run-codemap-benchpy) | `run-codemap-bench.py`      | Yes | 2 (plain / codemap)                     | 28 developer tasks — 5 series (S / FN / RV / OSS / D) | Does scan-query improve accuracy and token efficiency on real developer workflows? |
| [Query](#query-benchmark-run-codemap-scan-querypy)            | `run-codemap-scan-query.py` | No  | —                                       | 7 suites (C / A / L / I / S / H / X)                  | Is scan-query correct, complete, and fast enough?                                  |

Run **Query** first — validates the index before spending LLM tokens on agentic runs.

## Contents

- [Agentic benchmark](#agentic-benchmark-run-codemap-agenticpy) — 4-arm, import-graph navigation, semble support
- [Real-codebase benchmark](#real-codebase-benchmark-run-codemap-benchpy) — 5 task series, developer workflows on pytorch-lightning
- [Query benchmark](#query-benchmark-run-codemap-scan-querypy) — scan-query correctness and latency, no LLM
- [Results](#results)

<details>
<summary><strong>Files</strong></summary>

| File                        | Purpose                                                                                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `run-codemap-agentic.py`    | 4-arm agentic benchmark — measures how much structural context (codemap / semble / combined) reduces Claude's exploration overhead                                       |
| `run-codemap-bench.py`      | Real-codebase benchmark — measures scan-query accuracy and token efficiency across 5 developer task types; **repo-agnostic**, driven by `tasks-bench.json` `repo` header |
| `run-codemap-scan-query.py` | Query-level benchmark — measures scan-query correctness, coverage, and latency against a real repo                                                                       |
| `tasks-agentic.json`        | 16 import-graph navigation tasks (T01–T16), 4 types x 4 difficulty tiers, used by the agentic benchmark                                                                  |
| `tasks-bench.json`          | 28 developer tasks across 5 series (S / FN / RV / OSS / D) + `repo` header (name, namespace, default path) — swap to benchmark a different codebase                      |
| `tasks-code.json`           | 15 code-level tasks used by the scan-query benchmark                                                                                                                     |
| `requirements.txt`          | Python dependencies for all benchmarks                                                                                                                                   |
| `results/`                  | JSON snapshots and markdown reports from past runs                                                                                                                       |

</details>

## Agentic benchmark (`run-codemap-agentic.py`)

Runs the same 8 import-graph tasks under four arms:

| Arm        | Tools available                                                                           | Protocol                                              |
| ---------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `plain`    | Grep / Glob / Bash only                                                                   | Freeform exploration                                  |
| `codemap`  | + `/codemap:query` skill (structural AST index); semble blocked                           | Skill-first; no semble                                |
| `semble`   | + `mcp__semble__search` MCP tool (hybrid semantic + lexical search); Skill + Bash blocked | Semble-only; iterate until convergence                |
| `combined` | Both `/codemap:query` and `mcp__semble__search`; no restrictions                          | Sequential: codemap anchor → semble gap-fill → report |

**Combined arm protocol**: codemap runs first (deterministic anchor). If exhaustive, write report directly — count-anchoring enforces list completeness. If non-exhaustive, semble gap-fills with varied queries until two consecutive calls add zero new modules (convergence signal), then report. No interleaving between phases.

**Metrics**: tool call count, elapsed time, input tokens, exposure recall (erec), top-10 exposure recall (e@10), report recall (rrec), discovery efficiency (deff).

| Metric | What it measures                                                                  |
| ------ | --------------------------------------------------------------------------------- |
| `erec` | Fraction of ground-truth rdeps found anywhere in the agent output or tool results |
| `e@10` | erec restricted to the 10 most-central rdeps by dep_count                         |
| `rrec` | Fraction of ground-truth rdeps present in the agent final written answer only     |
| `deff` | Tool calls saved vs plain arm, normalised                                         |

<details>
<summary><strong>Tasks</strong></summary>

16 tasks: 4 types (fix / feature / refactor / review) x 4 difficulty tiers (simple / medium / hard / extreme). Difficulty maps to rdep count: simple 1-4 * medium 5-15 * hard 16-50 * extreme 50+.

| ID  | Type     | Difficulty | Primary module                                              | Scenario                                                                                |
| --- | -------- | ---------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| T01 | fix      | simple     | `lightning.pytorch.callbacks.timer`                         | Timer bug: `timedelta` compared as float, premature training stop                       |
| T02 | fix      | medium     | `lightning.pytorch.core.optimizer`                          | LR scheduler fires twice per batch when `optimizer_step` overridden                     |
| T03 | fix      | hard       | `lightning.pytorch.utilities.model_helpers`                 | `is_overridden` returns True for inherited methods — silent callback errors             |
| T04 | fix      | extreme    | `lightning.pytorch.utilities.exceptions`                    | Rename `MisconfigurationException` to `LightningConfigError` — assess full blast radius |
| T05 | feature  | simple     | `lightning.pytorch.callbacks.finetuning`                    | Add `freeze_until_epoch` — scope callers before coding                                  |
| T06 | feature  | medium     | `lightning.fabric.utilities.load`                           | Add `map_location` to checkpoint loaders — assess caller integration surface            |
| T07 | feature  | hard       | `lightning.fabric.utilities.rank_zero`                      | Add `group` parameter to rank-zero logging — find dual-importer consistency risk        |
| T08 | feature  | extreme    | `lightning.fabric.utilities.types`                          | Add `ReduceOp` protocol, deprecate `torch.distributed.ReduceOp`                         |
| T09 | refactor | simple     | `lightning.pytorch.callbacks.lr_finder`                     | Extract `_lr_find` helper into standalone function — classify callers                   |
| T10 | refactor | medium     | `lightning.fabric.plugins.environments.cluster_environment` | Rename `creates_processes_externally` — enumerate all call sites                        |
| T11 | refactor | hard       | `lightning.fabric.utilities.distributed`                    | Replace barrier wrappers with `DistributedBarrier` context manager                      |
| T12 | refactor | extreme    | `lightning.pytorch.callbacks`                               | Split `callbacks.__init__` into training/evaluation sub-modules                         |
| T13 | review   | simple     | `lightning.pytorch.strategies.deepspeed`                    | PR adds ZeRO-3 CPU offload — verify isolation                                           |
| T14 | review   | medium     | `lightning.fabric.plugins.precision.utils`                  | PR makes `_convert_fp_tensor` dtype arg keyword-only — quantify coupling                |
| T15 | review   | hard       | `lightning.pytorch.utilities`                               | PR removes 3 deprecated symbols — identify non-migrated callers                         |
| T16 | review   | extreme    | `lightning.pytorch.utilities.rank_zero`                     | PR replaces `rank_zero_warn` with deduplicating variant — full risk assessment          |

</details>

### Quick start

```bash
# 1. Install deps
pip install -r benchmarks/requirements.txt

# 2. Build codemap index once (excluded from benchmark timing)
python plugins/codemap/bin/scan-index --root /path/to/repo

# 3. Run all tasks, all arms, all model tiers
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --all --report

# 4. Spot-check one task
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo \
    --tasks T01 --arm plain --model haiku

# Run only non-semble arms (if semble not configured)
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --all --arm plain
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --all --arm codemap
```

<details>
<summary><strong>Enabling the semble arm (required for semble + combined)</strong></summary>

See [semble docs](https://github.com/MinishLab/semble) for full MCP server documentation. One-time setup:

```bash
claude mcp add semble -s user -- uvx --from "semble[mcp]" semble
```

`-s user` registers it globally (all projects). Use `-s project` to scope to this repo only.

**Verify** — the preflight check in `run-codemap-agentic.py` will raise a `RuntimeError` with instructions if semble is not found.

</details>

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                                     | Default       | Description                                                     |
| ---------------------------------------- | ------------- | --------------------------------------------------------------- |
| `--repo-path PATH`                       | required      | Absolute path to the repo under test                            |
| `--index PATH`                           | auto-detected | Override index path (default: `<repo>/.cache/scan/<name>.json`) |
| `--arm plain\|codemap\|semble\|combined` | all four      | Run a single arm only                                           |
| `--model haiku\|sonnet\|opus`            | all three     | Run a single model tier only                                    |
| `--tasks T01 T02 …`                      | all 16        | Run specific task IDs                                           |
| `--all`                                  | off           | Run all tasks (required unless `--tasks` given)                 |
| `--report`                               | off           | Write markdown report to `results/` after run                   |
| `--dry-run`                              | off           | Print system prompts, skip actual claude invocations            |

</details>

### Output

Each run prints one coloured line:

```
[NN/TT] T01 (fix) | haiku  | codemap  | elapsed= 45.2s | tokens= 120.3k | calls= 3 (grep=  0; glob= 0; bash=  0; skill= 1; semble= 0) | erec= 94% rrec= 88%  sc=100%
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

## Real-codebase benchmark (`run-codemap-bench.py`)

Measures whether `scan-query` structural access reduces token usage and improves recall on real developer tasks — symbol lookup, call-graph navigation, code review assistance, OSS health checks, and blast-radius assessment before modifying code.

**Benchmark philosophy**: this is a lens onto real developer workflow, not a number-manufacturing exercise. The D-series tasks model a concrete production safety gate: a developer must enumerate ≥70% of a function's callers before modifying it. Missing 30%+ callers in real code means blind refactoring — broken call sites, silent regressions. The 0.70 threshold exists because that is the practical boundary, not to produce a metric. Fixes to the evaluator (remove format noise, exclude budget-exhaustion from accuracy, guard arm isolation) make the benchmark more honest, not higher.

Two arms run the same tasks:

| Arm       | Tools available                      |
| --------- | ------------------------------------ |
| `plain`   | Grep / Bash / Glob / Read only       |
| `codemap` | + scan-query (via PATH) + Skill tool |

**Primary metric**: `token_ratio = codemap_input_tokens / plain_input_tokens` per task. Values below 1.0 mean codemap arm used fewer tokens.

**Secondary**: per-arm accuracy — fraction of *scored* tasks where the key metric matches ground truth within tolerance. Incomplete and contaminated runs are excluded from the denominator and reported separately.

### Task series

28 tasks in `tasks-bench.json`, five series (BR-series expanded to 8 tasks):

| Series | Type                   | Tasks        | What the agent must find                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------ | ---------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SE     | `symbol_extraction`    | SE-01..SE-05 | Source file line range for a named symbol                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| FN     | `fn_call_graph`        | FN-01..FN-05 | Unique caller count for a function (static call graph)                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| RV     | `review_assistance`    | RV-01..RV-05 | Doc-gap counts, rdep counts, coverage gaps for code review                                                                                                                                                                                                                                                                                                                                                                                                                                |
| CQ     | `code_quality`         | CQ-01..CQ-05 | Coupling, broken xrefs, combined doc+coverage health                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| BR     | `develop_blast_radius` | BR-01..BR-08 | Caller recall >=70% before modifying a function; developer workflow framing; calibratable via `/foundry:calibrate`. **n=8** — report accuracy as fractions (e.g. 6/8). BR-06..BR-08 GT = fn-rdeps AST callers; grep cross-check confirmed no false positives (grep missed same-file callers so was not used as subtractive filter). Developer-narrative prompts nudge full enumeration; reasoning sentences are not scored. Codemap arm uses `scan-query` via Bash PATH (not Skill tool). |

**SE — Symbol extraction.** Asks the agent to locate where a named symbol is defined and report its start line — the foundation of every "go-to-definition" and "find references" workflow in real development. Plain agents must grep the repo and read candidate files to confirm the match, which burns tokens and still fails when symbol names are ambiguous across modules or appear in strings. A codemap index stores each symbol's qualified name and source range directly, so a single `scan-query symbols` lookup returns the canonical location without reading any source file.

**FN — Function call graph.** Asks the agent to enumerate every unique function that calls a given target — the "who calls me?" question developers ask before refactoring an interface, adding a parameter, or deprecating a function. Plain agents rely on grep-based discovery, which counts raw string occurrences including imports and comments, and silently misses aliased imports and same-file callers. The codemap AST-derived call graph resolves qualified names structurally, producing an exact count unaffected by lexical ambiguity.

**RV — Review assistance.** Asks the agent to answer quantitative code-review questions — how many symbols lack docstrings, how many modules import a given module, how many public symbols have no test coverage — the metrics a reviewer needs to assess whether a change degrades coverage or widens blast radius. Plain agents must read entire module source files and cross-reference test files, a process that scales poorly and produces inconsistent counts due to varying output formats. The `scan-query` subcommands (`undocumented`, `rdeps`, `uncovered`) answer each question with a single structured JSON response containing an exact `count` and the full qualified-name list.

**CQ — Code quality.** Asks the agent to surface structural health metrics used at release gates — the most-coupled module, symbols with broken cross-references in docstrings, combined documentation and coverage deficits. Plain agents must invoke independent file reads for each metric and often miss cases requiring whole-graph reasoning such as transitive coupling. The codemap index exposes `coupled`, `xrefs-broken`, `undocumented`, and `uncovered` subcommands that query pre-built structural graphs and return ranked, quantified results in one call.

**BR — Develop blast radius.** Asks the agent to enumerate all direct callers of a function *before* making a change — the most operationally critical series, since missing callers of a function being refactored ships silent breakage. Plain agents miss aliased callers, same-file callers unreachable by grep, and callers whose import path differs from the module name, requiring dozens of file reads to validate each hit. The codemap `fn-rdeps` subcommand returns the AST-derived caller list directly, reaching high recall without reading a single source file. Recall ≥ 0.70 is a _partial coverage threshold_ — a passing score can still miss up to 30% of direct callers. Do not interpret pass as a production-safety guarantee; for safety-critical refactors, require near-exhaustive enumeration or explicitly bound missed-caller count.

### Quick start

```bash
# 1. Install deps
pip install -r benchmarks/requirements.txt

# 2. Build index once
python plugins/codemap/bin/scan-index --root ./<repo-dir>

# 3. Run all 28 tasks, both arms, haiku model
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --all --model haiku

# 4. Run one series (e.g. symbol tasks only)
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --task-type symbol_extraction --arm codemap --model haiku

# 5. Spot-check one task
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --tasks SE-01 --arm plain --model haiku
```

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                          | Default       | Description                                                                                                       |
| ----------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------- |
| `--repo-path PATH`            | auto          | Path to repo clone (default: `repo.default_path` from `tasks-bench.json`)                                         |
| `--index-path PATH`           | auto          | Override index; checks `.cache/codemap/` then `.cache/scan/`                                                      |
| `--tasks SE-01 FN-02 …`       | all           | Run specific task IDs                                                                                             |
| `--task-type TYPE`            | all           | Filter by type: `symbol_extraction`, `fn_call_graph`, `review_assistance`, `code_quality`, `develop_blast_radius` |
| `--arm plain\|codemap\|all`   | `all`         | Run one arm or both                                                                                               |
| `--model haiku\|sonnet\|opus` | `haiku`       | Model tier                                                                                                        |
| `--all`                       | off           | Required when `--tasks` and `--task-type` both absent                                                             |
| `--no-save`                   | off           | Skip writing JSONL results to `results/bench-<model>-<ts>.jsonl`                                                  |
| `--timeout N`                 | model default | Per-run wall-clock timeout in seconds                                                                             |

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

Results written to `results/bench-<model>-<YYYYMMDD-HHMMSS>.jsonl`.

### Ground truth

`tasks-bench.json` ships with pre-verified ground truth. To validate or refresh against a live index:

```bash
# Validate all tasks (exits 1 on any mismatch)
python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir>

# Validate single task
python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir> --task SE-01

# Refresh ground truth from live index (overwrites tasks-bench.json)
python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir> --update --verbose
```

______________________________________________________________________

## Query benchmark (`run-codemap-scan-query.py`)

Validates `scan-query` directly — no LLM involved. Requires a pre-built index.

Seven suites always run together:

| Suite           | Codes                      | What it measures                                                                    |
| --------------- | -------------------------- | ----------------------------------------------------------------------------------- |
| **C** Coverage  | C1 C2 C3                   | Fraction of known importers found by codemap vs cold grep                           |
| **A** Accuracy  | A1 A2 A3                   | Precision / recall / F1 on rdeps queries against grep ground truth                  |
| **L** Latency   | L1 L2 L3 L4                | Wall-clock time for `central`, `rdeps`, index build, vs cold grep baseline          |
| **I** Injection | I_fix I_feature I_refactor | Verifies that develop/oss skills inject `has_rdeps` + `has_deps` fields             |
| **S** Symbol    | S_SE-01..SE-05 S2          | `symbol` command returns correct start/end lines (ground truth: `tasks-bench.json`) |
| **H** Health    | H_CQ-\* H1 H2              | `undocumented`/`uncovered` totals match `tasks-bench.json` ground truth             |
| **X** Xrefs     | X_CQ-04 X1                 | `xrefs --broken` count + target set match `tasks-bench.json` ground truth           |

Suites S, H, X auto-skip (no error) when `tasks-bench.json` is absent.

### Quick start

```bash
# Run all suites against the target repo (auto-detects index)
python benchmarks/run-codemap-scan-query.py \
    --repo-path ./<repo-dir> \
    --report

# Explicit index path
python benchmarks/run-codemap-scan-query.py \
    --repo-path ./<repo-dir> \
    --index-path ./<repo-dir>/.cache/codemap/pytorch-lightning-master.json \
    --report

# Verify task modules exist in index before a full run
python benchmarks/run-codemap-scan-query.py \
    --repo-path ./<repo-dir> \
    --verify-tasks
```

Index resolution checks `.cache/codemap/<name>.json` first, then `.cache/scan/<name>.json`.

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                | Default | Description                                                  |
| ------------------- | ------- | ------------------------------------------------------------ |
| `--repo-path PATH`  | auto    | Path to repo clone                                           |
| `--index-path PATH` | auto    | Override index; checks `.cache/codemap/` then `.cache/scan/` |
| `--report`          | off     | Write markdown report to `results/code-YYYY-MM-DD[-N].md`    |
| `--json-only`       | off     | Print JSON only; suppress markdown                           |
| `--verify-tasks`    | off     | Verify task primary_modules exist in index before running    |

</details>

### Pass thresholds

| Code          | Threshold                                                 |
| ------------- | --------------------------------------------------------- |
| C1            | coverage gap >= 10%                                       |
| C2            | infeasible path fraction >= 50%                           |
| C3            | leverage ratio >= 2.0x                                    |
| A1            | precision >= 0.90, recall >= 0.85 (high-risk tasks)       |
| A2            | precision = 1.00 (low-risk tasks)                         |
| A3            | FP rate < 5%                                              |
| L1            | `central` median < 200 ms                                 |
| L2            | `rdeps` median < 100 ms                                   |
| L3            | amortised index build < 500 ms                            |
| L4            | speedup >= 2x                                             |
| I_fix/feature | JSON valid block present                                  |
| I_refactor    | JSON valid + has_rdeps + has_deps                         |
| S\_\* / S2    | symbol found + start_line within +-3 of ground truth      |
| H1 / H2       | undocumented / uncovered total == ground truth (exact)    |
| X1            | xrefs --broken count + target set == ground truth (exact) |

______________________________________________________________________

## Benchmark methodology

### Task series

The benchmark covers 28 tasks across 5 series:

| Series           | Type                       | What it measures                                     | Evaluator                                 |
| ---------------- | -------------------------- | ---------------------------------------------------- | ----------------------------------------- |
| **S** (5 tasks)  | Symbol extraction          | Find file + line range of a function/class           | Line-tolerance (±5 lines)                 |
| **FN** (5 tasks) | Call graph count           | How many unique functions call target X              | Name-recall ≥ 0.70 against GT caller list |
| **D** (8 tasks)  | Blast radius (caller list) | Which specific functions call target X               | Recall ≥ 0.70 against GT caller list      |
| **RV** (5 tasks) | Review assistance          | Caller count for a function in a code review context | Integer extraction with ±10% tolerance    |
| **Q** (5 tasks)  | Code quality               | Undocumented / uncovered / unhealthy module metrics  | Recall ≥ 0.70 against GT metric           |

### Two arms

Every task runs twice:

- **plain**: grep, read, bash only — no structural index, no `scan-query`
- **codemap**: same tools + `scan-query` structural index (fn-rdeps, symbol, rdeps, undocumented, uncovered, find-symbol)

Scoring is independent per arm. Token ratio = `codemap_input_tokens / plain_input_tokens` (< 1.0 = codemap cheaper).

### Ground truth establishment

- **Symbol tasks (S)**: GT from reading source directly (file path + AST line range).
- **Call-graph tasks (FN, D)**: GT from running `scan-query fn-rdeps "<module::function>" --exclude-tests` on the indexed repo, then deduplicating caller qnames (`set()` dedup — multiple call-sites to same function counted once). `unique_caller_count` = len after dedup.
- **Review-assist (RV)**: Same `fn-rdeps` output but framed as a code-review question.
- **Quality tasks (Q)**: GT from running `scan-query undocumented` / `scan-query uncovered` directly against the repo.
- **Circularity note (FN / D / RV / Q)**: GT for these series is derived from `scan-query` output. The codemap arm is instructed to trust `scan-query` as authoritative. Results for these series measure index-assisted agreement, not independent correctness against an external oracle. S-series GT is source-file derived and is not circular.

### Known limitations

- **RV recall > 1.0**: Scores above 1.0 (marked `^` in per-run log) indicate model over-counts, not evaluator error. RV-03/04 over-count systematically across all models on both arms — root cause: `fn-rdeps` count field = call-site edge count, not unique callers; a model that copies the tool count lands above GT while a model that counts distinct caller names lands on GT.
- **extraction_failed (NaN in summary table)**: Evaluator regex cannot extract the target metric from model output for some tasks. In June 21 runs: plain arm failed on S-04, Q-05 (haiku); RV-02, Q-02 (sonnet). Codemap arm failed on FN-03 (sonnet only). Extraction failures are excluded from the accuracy denominator. Count-based tasks (S / Q / count-branch RV) show `NaN` in the summary table's recall columns; per-task recall is visible in the per-run log line (`recall=…`).
- **RV-02 both arms low**: GT has 64 callers — too many for a single LLM response to enumerate exhaustively. Haiku plain 15.6% / codemap 28.1%; sonnet and opus similar. Task may be ill-suited for recall-based scoring at this scale.
- **Sonnet FN regression**: FN-02 codemap recall=0.081 (plain=1.000) and FN-03 codemap extraction_failed (plain=1.000) on June 21 sonnet run. Cause not yet diagnosed. Plain arm brute-forces these tasks successfully. Investigate before using codemap for sonnet on `fn_call_graph` tasks.
- **Partial filesystem isolation**: `Write`, `Edit`, and `NotebookEdit` are blocked on both arms. Runs where either arm reads benchmark answer files (`tasks-bench`, `benchmarks/results`, `/benchmarks/`) are flagged `answer_file_read` and excluded from scoring — visible in the summary line and JSONL `error` field. Agents can still read arbitrary paths outside the target repo (alternate checkouts, `~/.claude`, etc.); for cleanest runs use a disposable checkout and verify the JSONL tool-use log shows no stray reads.

## Results

`results/` holds all past run outputs:

| Pattern                                 | Source                                |
| --------------------------------------- | ------------------------------------- |
| `agentic-YYYY-MM-DD[-N].json`           | Agentic benchmark JSON snapshot       |
| `agentic-YYYY-MM-DD[-N].md`             | Agentic benchmark markdown report     |
| `bench-<model>-<YYYYMMDD-HHMMSS>.jsonl` | Real-codebase benchmark JSONL results |
| `code-YYYY-MM-DD[-N].md`                | Query benchmark markdown report       |

### Multi-model results: real-codebase benchmark

Results — June 21 2026 runs — 28 tasks × 2 arms × 3 models, pytorch-lightning-master. All three use the current `_evaluate_develop_br` evaluator for FN tasks (name-recall ≥ 0.70).

| Model      | Plain accuracy | Codemap accuracy | Accuracy lift | Safety-grade plain | Safety-grade codemap | Token ratio (median) | Token ratio range |
| ---------- | -------------- | ---------------- | ------------- | ------------------ | -------------------- | -------------------- | ----------------- |
| Haiku 4.5  | 70.8% (17/24)  | 82.1% (23/28)    | **+11 pp**    | 7/13               | **13/13**            | **0.21×**            | 0.04–1.82×        |
| Sonnet 4.6 | 80.8% (21/26)  | 81.5% (22/27)    | **+1 pp**     | 12/13              | 11/12                | **0.14×**            | 0.03–0.61×        |
| Opus 4.6   | 73.1% (19/26)  | 89.3% (25/28)    | **+16 pp**    | 10/13              | **13/13**            | **0.32×**            | 0.03–1.17×        |

Safety-grade = fraction of tasks with explicit recall (FN + D series) where recall ≥ 0.90. Token ratio = codemap / plain input tokens. Token savings are model-independent (median 0.14–0.32×). Accuracy lift is model-dependent.

#### Haiku 4.5 — `results/bench-haiku-20260621-214854.jsonl`

28 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                     |
| --------- | ------------------------- |
| Median    | **0.21×** (79% reduction) |
| Min       | 0.04× (FN-02)             |
| Max       | 1.82× (D-08)              |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete      |
| ------- | --------- | -------------- | ----------------- | --------------- |
| plain   | **70.8%** | 17/24          | 2 (S-04, Q-05)    | 2 (RV-03, Q-03) |
| codemap | **82.1%** | 23/28          | 0                 | 0               |

By series (excl. extraction_failed / incomplete):

| Series           | plain | codemap | Notes                                                           |
| ---------------- | ----- | ------- | --------------------------------------------------------------- |
| S (symbol)       | 4/4\* | 5/5     | \*S-04 ext-fail plain; codemap passes all 5                     |
| FN (call graph)  | 4/5   | 5/5     | FN-04 plain=0.000, FN-02 plain=0.108; codemap perfect on all 5  |
| D (blast radius) | 8/8   | 8/8     | Both arms perfect; codemap saves 53–96% tokens                  |
| RV (review)      | 1/3†  | 2/5     | †RV-03 plain incomplete; haiku RV-04 codemap regression (0.458) |
| Q (code quality) | 1/3†  | 4/5     | †Q-03 incomplete, Q-05 ext-fail; Q-02 fails both arms           |

**Safety-grade**: plain 7/13 → codemap 13/13 — haiku is the model most dependent on codemap for correctness. FN-04 plain=0.000 → codemap=1.000. Not-covered gaps: `__import__`, `importlib.import_module`, lazy-loading.

#### Sonnet 4.6 — `results/bench-sonnet-20260621-223352.jsonl`

28 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                     |
| --------- | ------------------------- |
| Median    | **0.14×** (86% reduction) |
| Min       | 0.03× (D-01)              |
| Max       | 0.61× (D-06)              |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | **80.8%** | 21/26          | 2 (RV-02, Q-02)   | 0          |
| codemap | **81.5%** | 22/27          | 1 (FN-03)         | 0          |

By series (excl. extraction_failed / incomplete):

| Series           | plain | codemap | Notes                                                                |
| ---------------- | ----- | ------- | -------------------------------------------------------------------- |
| S (symbol)       | 5/5   | 4/5     | S-05 codemap over-counts (recall=^1.380)                             |
| FN (call graph)  | 5/5   | 3/4†    | **⚠ Regression**: FN-02 plain=1.000 → codemap=0.081; †FN-03 ext-fail |
| D (blast radius) | 8/8   | 8/8     | Both arms perfect; codemap saves 39–97% tokens                       |
| RV (review)      | 2/4†  | 4/5     | †RV-02 ext-fail; count-based RV-03/04 struggle both arms             |
| Q (code quality) | 3/4†  | 3/5     | †Q-02 ext-fail; Q-02 codemap over-counts; Q-01/03/04/05 codemap pass |

**Safety-grade**: plain 12/13 → codemap 11/12 (slight regression). Token savings are the primary codemap benefit at this model tier. ⚠ FN-series regression on codemap arm: FN-02 recall=0.081, FN-03 extraction_failed — both tasks plain arm succeeds at 1.000.

#### Opus 4.6 — `results/bench-opus-20260621-212141.jsonl`

28 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                     |
| --------- | ------------------------- |
| Median    | **0.32×** (68% reduction) |
| Min       | 0.03× (D-01)              |
| Max       | 1.17× (D-07)              |

**Accuracy** (scored tasks only):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete |
| ------- | --------- | -------------- | ----------------- | ---------- |
| plain   | **73.1%** | 19/26          | 1 (Q-05)          | 1 (Q-04)   |
| codemap | **89.3%** | 25/28          | 0                 | 0          |

By series (excl. extraction_failed / incomplete):

| Series           | plain | codemap | Notes                                                                 |
| ---------------- | ----- | ------- | --------------------------------------------------------------------- |
| S (symbol)       | 5/5   | 5/5     | Both arms perfect; codemap saves 37–63% tokens                        |
| FN (call graph)  | 3/5   | 5/5     | FN-01 plain=0.808, FN-02 plain=0.108 — codemap perfect on all 5       |
| D (blast radius) | 8/8   | 8/8     | Both arms perfect; codemap saves 49–97% tokens                        |
| RV (review)      | 2/5   | 3/5     | RV-03/04 count-based over-count (both arms); RV-05 codemap lift       |
| Q (code quality) | 1/3†  | 5/5     | †Q-05 ext-fail, Q-04 plain incomplete; codemap scores all 5 correctly |

**Safety-grade**: plain 10/13 → codemap 13/13. Codemap drives +16 pp accuracy lift, primarily from FN-series (plain 3/5 → codemap 5/5). RV-03/04 count-based over-count persists on both arms.

### Previous: agentic benchmark — 2026-04-29

`results/agentic-2026-04-29.md` — pytorch-lightning, 4 arms × 3 models × 8 tasks = 96 runs.
