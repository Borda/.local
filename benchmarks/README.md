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

28 tasks in `tasks-bench.json`, five series (D-series expanded to 8 tasks):

| Series | Type                   | Tasks        | What the agent must find                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------ | ---------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S      | `symbol_extraction`    | S-01..S-05   | Source file line range for a named symbol                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| FN     | `fn_call_graph`        | FN-01..FN-05 | Unique caller count for a function (static call graph)                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| RV     | `review_assistance`    | RV-01..RV-05 | Doc-gap counts, rdep counts, coverage gaps for code review                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Q      | `code_quality`         | Q-01..Q-05   | Coupling, broken xrefs, combined doc+coverage health                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| D      | `develop_blast_radius` | D-01..D-08   | Caller recall >=70% before modifying a function; developer workflow framing; calibratable via `/foundry:calibrate`. **n=8** — report accuracy as fractions (e.g. 6/8). D-06..D-08 GT = fn-rdeps AST callers; grep cross-check confirmed no false positives (grep missed same-file callers so was not used as subtractive filter). Developer-narrative prompts nudge full enumeration; reasoning sentences are not scored. Codemap arm uses `scan-query` via Bash PATH (not Skill tool). |

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
    --tasks S-01 --arm plain --model haiku
```

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                          | Default       | Description                                                                                                       |
| ----------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------- |
| `--repo-path PATH`            | auto          | Path to repo clone (default: `repo.default_path` from `tasks-bench.json`)                                         |
| `--index-path PATH`           | auto          | Override index; checks `.cache/codemap/` then `.cache/scan/`                                                      |
| `--tasks S-01 FN-02 …`        | all           | Run specific task IDs                                                                                             |
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
  ✓+ S-01    codemap tok= 45230 got=      146 exp=      146
  ✓- S-01    plain   tok= 89410 got=     None exp=      146
```

`✓` = subprocess success · `✗` = failure · `+` = quality correct · `-` = quality wrong · `!` = incomplete (budget exhausted) · `c` = contaminated (plain arm accessed codemap) · `?` = not evaluated.

Summary table printed after all runs:

```
Token ratio (codemap/plain):
  median = 0.37  mean = 1.05
  plain accuracy = 62.5%  (5/8 scored)
  plain incomplete = 1 (budget exhausted — not scored: D-04)
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
python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir> --task S-01

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
| **S** Symbol    | S_S-01..S-05 S2            | `symbol` command returns correct start/end lines (ground truth: `tasks-bench.json`) |
| **H** Health    | H_Q-\* H1 H2               | `undocumented`/`uncovered` totals match `tasks-bench.json` ground truth             |
| **X** Xrefs     | X_Q-04 X1                  | `xrefs --broken` count + target set match `tasks-bench.json` ground truth           |

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

## Results

`results/` holds all past run outputs:

| Pattern                                 | Source                                |
| --------------------------------------- | ------------------------------------- |
| `agentic-YYYY-MM-DD[-N].json`           | Agentic benchmark JSON snapshot       |
| `agentic-YYYY-MM-DD[-N].md`             | Agentic benchmark markdown report     |
| `bench-<model>-<YYYYMMDD-HHMMSS>.jsonl` | Real-codebase benchmark JSONL results |
| `code-YYYY-MM-DD[-N].md`                | Query benchmark markdown report       |

### Latest: real-codebase benchmark — sonnet, 2026-06-19

`results/bench-sonnet-20260619-223507.jsonl` — 28 tasks × 2 arms, pytorch-lightning-master.

**Token efficiency** (codemap/plain ratio):

| Statistic | Value                                |
| --------- | ------------------------------------ |
| Median    | **0.17×** (83% reduction)            |
| Mean      | 0.28×                                |
| Min       | 0.06× (FN-03)                        |
| Max       | 1.41× (RV-04 — codemap over-queried) |

**Accuracy** (scored tasks only; excludes extraction_failed and incomplete):

| Arm     | Score     | Correct/Scored | extraction_failed | incomplete                 |
| ------- | --------- | -------------- | ----------------- | -------------------------- |
| plain   | **78.3%** | 18/23          | 4 (Q-01,02,03,05) | 1 (RV-03, error_max_turns) |
| codemap | **80.8%** | 21/26          | 2 (Q-01,Q-03)     | 0                          |

By series (excl. extraction_failed / incomplete):

| Series           | plain | codemap | Notes                                                         |
| ---------------- | ----- | ------- | ------------------------------------------------------------- |
| S (symbol)       | 5/5   | 5/5     | Both arms perfect                                             |
| FN (call graph)  | 5/5   | 4/5     | FN-02 codemap: 1 scan-query insufficient for 37-caller set    |
| D (blast radius) | 8/8   | 8/8     | Both arms perfect; primary benefit is token efficiency        |
| RV (review)      | 0/4   | 2/5     | RV-03 plain DNF at 2.2M; RV-04 both arms miss 1 of 5 issues   |
| Q (code quality) | 0/1   | 2/3     | Evaluator gaps reduce scoreable tasks; token efficiency valid |

codemap not-covered gaps (static AST only): `__import__`, dynamic dispatch, hook callbacks, `importlib.import_module`, lazy loading, string dispatch.

### Previous: agentic benchmark — 2026-04-29

`results/agentic-2026-04-29.md` — pytorch-lightning, 4 arms × 3 models × 8 tasks = 96 runs.
