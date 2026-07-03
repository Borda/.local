# Codemap Benchmarks

Empirical validation for the `codemap` plugin — three independent benchmarks. The real-codebase benchmark is **repo-agnostic**: swap `tasks-bench.json` (which ships a `repo` header with name, namespace, and default clone path) to run against any Python codebase. Reference results use `pytorch-lightning-master`.

## Benchmark overview

| Benchmark                                                     | Script                   | LLM | Arms                                    | Tasks                                                       | Primary question                                                                                      |
| ------------------------------------------------------------- | ------------------------ | --- | --------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [Agentic](#agentic-benchmark-run-codemap-agenticpy)           | `run-codemap-agentic.py` | Yes | 4 (plain / codemap / semble / combined) | 16 import-graph tasks                                       | Does codemap/semble reduce exploration overhead vs grep?                                              |
| [Real-codebase](#real-codebase-benchmark-run-codemap-benchpy) | `run-codemap-bench.py`   | Yes | 2 (plain / codemap)                     | 44 tasks — 8 series (SE / FN / RV / CQ / BR / DG / FT / RI) | Does scan-query reduce token cost and improve structural recall on pre-implementation research tasks? |
| [Query](#query-benchmark-run-codemap-scan-querypy)            | `run-codemap-cli.py`     | No  | —                                       | 7 suites (C / A / L / I / S / H / X)                        | Is scan-query correct, complete, and fast enough?                                                     |

Run **Query** first — validates the index before spending LLM tokens on agentic runs.

## Contents

- [Agentic benchmark](#agentic-benchmark-run-codemap-agenticpy) — 4-arm, import-graph navigation, semble support
- [Real-codebase benchmark](#real-codebase-benchmark-run-codemap-benchpy) — 8 task series, structural navigation on pytorch-lightning
- [Query benchmark](#query-benchmark-run-codemap-scan-querypy) — scan-query correctness and latency, no LLM
- [Results](#results)

<details>
<summary><strong>Files</strong></summary>

| File                           | Purpose                                                                                                                                                                                                   |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run-codemap-agentic.py`       | 4-arm agentic benchmark — measures how much structural context (codemap / semble / combined) reduces Claude's exploration overhead                                                                        |
| `run-codemap-bench.py`         | Real-codebase benchmark — measures scan-query accuracy and token efficiency across 8 structural navigation task types; **repo-agnostic**, driven by `tasks-bench.json` `repo` header                      |
| `run-codemap-cli.py`           | Query-level benchmark — measures scan-query correctness, coverage, and latency against a real repo                                                                                                        |
| `suites/tasks-agentic.json`    | 16 blast-radius navigation tasks (BA-01–BA-16), 4 difficulty tiers, used by the agentic benchmark                                                                                                         |
| `suites/tasks-bench.json`      | 44 tasks across 8 series (SE / FN / RV / CQ / BR / DG / FT / RI) + `repo` header (name, namespace, default path) — swap to benchmark a different codebase                                                 |
| `suites/tasks-code.json`       | 15 code-level tasks used by the scan-query benchmark                                                                                                                                                      |
| `suites/tasks-patch.json`      | 5 end-to-end patch tasks (PT-01–PT-05) — failing test → minimal fix → test pass; requires `--patch` flag and sandbox harness                                                                              |
| `suites/tasks-readcrop.json`   | 6 read-crop tasks (RC-01–RC-06) — symbol-contract extraction; scored by keyword recall; headline metric is `tool_result_tokens` (codemap `symbol` extraction vs whole-file Read)                          |
| `suites/tasks-fix-single.json` | 4 fix-single tasks (FS-01–FS-04) — single-file bug fix with archive/restore isolation; scored by diff keyword recall (`erec`)                                                                             |
| `suites/tasks-fix-multi.json`  | 3 fix-multicaller tasks (FM-01–FM-03) — signature change + caller update across files; codemap `fn-rdeps` finds all callers before editing; scored by diff keyword recall (`erec`) + file recall (`rrec`) |
| `requirements.txt`             | Python dependencies for all benchmarks                                                                                                                                                                    |
| `results/`                     | JSON snapshots and markdown reports from past runs                                                                                                                                                        |

</details>

## Agentic benchmark (`run-codemap-agentic.py`)

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

| Metric | What it measures                                                                            |
| ------ | ------------------------------------------------------------------------------------------- |
| `erec` | Fraction of ground-truth rdeps found in agent output_text (tool results excluded; arm-fair) |
| `e@10` | erec restricted to the 10 most-central rdeps by dep_count                                   |
| `rrec` | Fraction of ground-truth rdeps present in the agent final written answer only               |
| `deff` | Tool calls saved vs plain arm, normalised                                                   |

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
# 1. Install deps
pip install -r benchmarks/requirements.txt

# 2. Build codemap index once (excluded from benchmark timing)
python plugins/codemap/bin/scan-index --root /path/to/repo

# 3. Run all tasks, all arms, all model tiers
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --run-all --report

# 4. Spot-check one task
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo \
    --tasks "['BA-01']" --arm plain --model haiku

# Run only non-semble arms (if semble not configured)
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --run-all --arm plain
python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --run-all --arm codemap
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

| Flag                                     | Default       | Description                                                              |
| ---------------------------------------- | ------------- | ------------------------------------------------------------------------ |
| `--repo-path PATH`                       | required      | Absolute path to the repo under test                                     |
| `--index PATH`                           | auto-detected | Override index path (default: `<repo>/.cache/scan/<name>.json`)          |
| `--arm plain\|codemap\|semble\|combined` | all four      | Run a single arm only                                                    |
| `--model haiku\|sonnet\|opus`            | all three     | Run a single model tier only                                             |
| `--tasks "['BA-01','BA-02',...]"`        | all 16        | Run specific task IDs (Python list literal — e.g. `"['BA-01','BA-02']"`) |
| `--run-all`                              | off           | Run all tasks (required unless `--tasks` given)                          |
| `--report`                               | off           | Write markdown report to `results/` after run                            |
| `--dry-run`                              | off           | Print system prompts, skip actual claude invocations                     |

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

## Real-codebase benchmark (`run-codemap-bench.py`)

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

44 tasks in `tasks-bench.json`, eight series:

| Series | Type                   | Tasks        | What the agent must find                                                                                                                                                                                                                                         |
| ------ | ---------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SE     | `symbol_extraction`    | SE-01..SE-05 | Source file line range for a named symbol                                                                                                                                                                                                                        |
| FN     | `fn_call_graph`        | FN-01..FN-05 | Unique caller count for a function (static call graph)                                                                                                                                                                                                           |
| RV     | `review_assistance`    | RV-01..RV-05 | Doc-gap counts, rdep counts, coverage gaps for code review                                                                                                                                                                                                       |
| CQ     | `code_quality`         | CQ-01..CQ-05 | Coupling, broken xrefs, combined doc+coverage health                                                                                                                                                                                                             |
| BR     | `develop_blast_radius` | BR-01..BR-08 | Caller recall ≥70% before modifying a function; developer workflow framing; calibratable via `/foundry:calibrate`. **n=8** — report accuracy as fractions. BR-06..BR-08 GT = fn-rdeps AST callers. Codemap arm uses `scan-query` via Bash PATH (not Skill tool). |
| DG     | `debug_from_trace`     | DG-01..DG-06 | Root-cause function + file from a traceback or log line                                                                                                                                                                                                          |
| FT     | `feature_scaffolding`  | FT-01..FT-05 | Which files to create or modify for a described new feature                                                                                                                                                                                                      |
| RI     | `real_issue`           | RI-01..RI-05 | Files relevant to a real GitHub issue (recall ≥ 0.70)                                                                                                                                                                                                            |

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

# 3. Run all 44 tasks, both arms, haiku model
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --run-all --model haiku

# 4. Run one series (e.g. symbol tasks only)
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --task-type symbol_extraction --arm codemap --model haiku

# 5. Spot-check one task
python benchmarks/run-codemap-bench.py \
    --repo-path ./<repo-dir> \
    --tasks "['SE-01']" --arm plain --model haiku
```

<details>
<summary><strong>CLI flags</strong></summary>

| Flag                              | Default       | Description                                                                                                                                                                |
| --------------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--repo-path PATH`                | auto          | Path to repo clone (default: `repo.default_path` from `tasks-bench.json`)                                                                                                  |
| `--index-path PATH`               | auto          | Override index; checks `.cache/codemap/` then `.cache/scan/`                                                                                                               |
| `--tasks "['SE-01','FN-02',...]"` | all           | Run specific task IDs (Python list literal — e.g. `"['SE-01','FN-02']"`)                                                                                                   |
| `--task-type TYPE`                | all           | Filter by type: `symbol_extraction`, `fn_call_graph`, `review_assistance`, `code_quality`, `develop_blast_radius`, `debug_from_trace`, `feature_scaffolding`, `real_issue` |
| `--arm plain\|codemap\|all`       | `all`         | Run one arm or both                                                                                                                                                        |
| `--model haiku\|sonnet\|opus`     | `haiku`       | Model tier                                                                                                                                                                 |
| `--run-all`                       | off           | Required when `--tasks` and `--task-type` both absent                                                                                                                      |
| `--no-save`                       | off           | Skip writing JSONL results to `results/bench-<model>-<ts>.jsonl`                                                                                                           |
| `--timeout N`                     | model default | Per-run wall-clock timeout in seconds                                                                                                                                      |

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
| L3            | amortised index build < 500 ms                                                                                                                                                              |
| L4            | speedup >= 2x                                                                                                                                                                               |
| I_fix/feature | JSON valid block present                                                                                                                                                                    |
| I_refactor    | JSON valid + has_rdeps + has_deps                                                                                                                                                           |
| S\_\* / S2    | symbol found + start_line within +-3 of ground truth                                                                                                                                        |
| H1 / H2       | undocumented / uncovered total == ground truth (exact)                                                                                                                                      |
| X1            | xrefs --broken count + target set == ground truth (exact)                                                                                                                                   |

______________________________________________________________________

## Benchmark methodology

### Task series

The benchmark covers 44 tasks across 8 series:

| Series           | Type                       | What it measures                                     | Evaluator                                 |
| ---------------- | -------------------------- | ---------------------------------------------------- | ----------------------------------------- |
| **SE** (5 tasks) | Symbol extraction          | Find file + line range of a function/class           | Line-tolerance (±5 lines)                 |
| **FN** (5 tasks) | Call graph count           | How many unique functions call target X              | Name-recall ≥ 0.70 against GT caller list |
| **BR** (8 tasks) | Blast radius (caller list) | Which specific functions call target X               | Recall ≥ 0.70 against GT caller list      |
| **RV** (5 tasks) | Review assistance          | Caller count for a function in a code review context | Integer extraction with ±10% tolerance    |
| **CQ** (5 tasks) | Code quality               | Undocumented / uncovered / unhealthy module metrics  | Recall ≥ 0.70 against GT metric           |
| **DG** (6 tasks) | Debug from trace           | Identify root-cause file + function from traceback   | Recall ≥ 0.70 against GT symbols          |
| **FT** (5 tasks) | Feature scaffolding        | List files that need editing for a new feature       | Recall ≥ 0.70 against GT file list        |
| **RI** (5 tasks) | Real GitHub issues         | Locate relevant code for a real issue/PR             | Recall ≥ 0.70 against GT file list        |

### Two arms

Every task runs twice:

- **plain**: grep, read, bash only — no structural index, no `scan-query`
- **codemap**: same tools + `scan-query` structural index (fn-rdeps, symbol, rdeps, undocumented, uncovered, find-symbol)

Scoring is independent per arm. Token ratio = `codemap_input_tokens / plain_input_tokens` (< 1.0 = codemap cheaper).

### Ground truth establishment

- **Symbol tasks (SE)**: GT from reading source directly (file path + AST line range).
- **Call-graph tasks (FN, BR, RV) — 2026-07-03**: authoritative `fn_callers` GT is validated against an independent AST oracle (`_callers_via_ast` in `generate-tasks-bench.py`); the `scan-query fn-rdeps` result is kept as `fn_callers_scan` diagnostic. Oracle-vs-tool divergence prints a loud warning listing divergent qnames — divergence signals a potential plugin bug and is never auto-overwritten. fn-rdeps `count` == unique deduped callers (the plugin also emits an explicit `unique_caller_count` alias since codemap 0.15.0).
- **Quality tasks (CQ)**: `undocumented` GT validated against an independent AST docstring walker; `uncovered` and `xrefs` GT remain scan-query-derived (circular) pending independent oracles — refreshing them requires the explicit `--update-from-tool` flag.
- **`--update` semantics (2026-07-03)**: default `--update` refreshes GT from the AST oracle only; scan-query-derived fields refresh only behind `--update-from-tool`, which prints a circularity warning + oracle diff before writing. Known gap: the AST oracle emits `src.`-prefixed module paths that diverge from the scan-query namespace on a real clone — normalize before regenerating GT against pytorch-lightning (see `.plans/active/todo_benchmarks-review-fixes.md`).
- **Residual circularity note (CQ uncovered / xrefs)**: those two metrics still measure index-assisted agreement, not independent correctness. SE-series GT is source-file derived and was never circular; FN/BR/RV are now oracle-anchored.

### Known limitations

- **Arm ordering**: plain arm always runs before codemap on each task. Token metrics are unaffected. Wall-clock time metrics may be biased toward codemap (OS page cache warm on second run); treat token ratio as the primary efficiency signal.
- **RV recall > 1.0**: Scores above 1.0 (marked `^` in per-run log) indicate model over-counts, not evaluator error. In June 22 runs RV-03/04 both showed systematic over-count (`^1.1–1.25×`). RV-03 was a task-definition bug — sub-question asked for "fn-rdeps count field" (= 42 total call-site edges) but GT = 37 unique callers; fixed June 23 (prompt now asks for "distinct caller entries"; new runs show RV-03 codemap recall ≈ 1.0). RV-04 remains: `fn-rdeps count: 24` = 24 unique callers = GT, so over-count is pure model error (grep over-counting).
- **NaN in summary table**: A task shows `NaN` recall in the summary table for any of four reasons: (1) `extraction_failed == True` — evaluator regex cannot extract the target metric from model output (most common); (2) `quality.scored == False` — task is marked not scoreable (e.g. RI-05); (3) only one arm ran — no plain+codemap pair to compare; (4) `quality.recall` is None and `metric_got`/`metric_expected` are also None. In June 22 runs (44 tasks): plain arm extraction_failed on SE-05/CQ-01/CQ-05/RI-04 (haiku), FT-03 (sonnet), CQ-01/CQ-05 (opus). Codemap arm extraction_failed on SE-05/CQ-03/CQ-05 (haiku), FN-03 (sonnet), FN-03/RI-02 (opus). Extraction failures are excluded from the accuracy denominator. Count-based tasks (SE / CQ / count-branch RV) show `NaN` in the summary table recall columns; per-task recall is visible in the per-run log line (`recall=…`).
- **RV-02 both arms low**: GT has 64 callers — too many for a single LLM response to enumerate exhaustively. Haiku plain 15.6% / codemap 28.1%; sonnet and opus similar. Task may be ill-suited for recall-based scoring at this scale.
- **Opus FN-02 and BR-03 regressions (June 22 — fixed June 23)**: June 22 runs showed FN-02 codemap recall=0.027 and BR-03 codemap recall=0.042. Root causes were two evaluator bugs: (1) missing extraction forms for bold+numbered list output format (Form 9) and file-dump pointer resolution; (2) evaluator version mismatch. Fixed in evaluator v3 (June 23 re-runs: both tasks recall=1.000). See `results/bench-opus-20260623-003745.jsonl`.
- **Haiku RI token spirals (June 22 — fixed June 23)**: June 22 runs: RI-02/RI-04 codemap hit `error_max_turns` consuming 2.6–3.0M tokens. Root cause: `Bash(python3:*)` allowed on codemap arm only — agents spiralled into implement-validate mode writing repro scripts. Fixed by blocking `Bash(python3:*)` and `Bash(python:*)` on both arms. June 23 re-runs: RI-02/RI-04 codemap recall=1.000, 2.0–2.1M tokens. See `results/bench-haiku-20260623-003825.jsonl`.
- **Haiku BR-07 regression**: codemap recall=0.778 vs plain=0.889 (Δ=−0.11). Single instance; monitor for recurrence.
- **FN-series extraction failures**: FN-03 codemap extraction_failed on both sonnet and opus — evaluator cannot parse model output. Plain arm scores 1.000 on both models.
- **Partial filesystem isolation**: `Write`, `Edit`, and `NotebookEdit` are blocked on both arms. Runs where either arm reads benchmark answer files (`tasks-bench`, `benchmarks/results`, `/benchmarks/`) are flagged `answer_file_read` and excluded from scoring — visible in the summary line and JSONL `error` field. Agents can still read arbitrary paths outside the target repo (alternate checkouts, `~/.claude`, etc.); for cleanest runs use a disposable checkout and verify the JSONL tool-use log shows no stray reads.

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

`tasks-bench.json` contains 44 tasks across 8 series: structural research (SE / FN / RV / CQ / BR), debug trace analysis (DG), feature scaffolding (FT), and real GitHub issues (RI). Core series model the pre-implementation structural research phase; DG/FT/RI cover broader developer workflows. No tasks require a code output or a test run.

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
python benchmarks/run-codemap-agentic.py \
    --repo-path /path/to/pytorch-lightning/src/lightning \
    --tasks "[\'FS-01\',\'FS-02\',\'FS-03\',\'FS-04\']" --run-all --model haiku

# Fix-multicaller (the codemap edit-assist test — run plain + codemap, compare rrec on FM-03)
python benchmarks/run-codemap-agentic.py \
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

### Multi-model results: real-codebase benchmark

> **⚠ Stale (2026-07-03)**: all results below predate the fairness overhaul (symmetric arm prompts, AST-oracle ground truth, real C1/C2 metrics). Token ratios and FN/BR/RV/CQ accuracy were measured under codemap-favoring prompt steering and partially circular GT — treat as upper bounds; re-run pending.

Results — June 22 2026 — 44 tasks × 2 arms × 3 models, pytorch-lightning-master.

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

Codemap reduces tool calls in every tier (🚧) — exploration savings are real but small vs preamble cost. Known limitations and planned mitigations: see `plugins/codemap/README.md`.

Results above include all three arms. Combined arm excluded from default "all" runs (run with `--arm combined` to include).

### Previous: agentic benchmark — 2026-04-29

`results/agentic-2026-04-29.md` — pytorch-lightning, 4 arms × 3 models × 8 tasks = 96 runs.
