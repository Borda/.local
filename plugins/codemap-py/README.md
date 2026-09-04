# 🗂️ codemap-py — structural answers for Python codebases

codemap-py builds a local, static index of a Python project so maintainers can answer "what imports this?", "what calls this function?", "which tests are likely affected?", and "where is the highest coupling?" before changing code. It is useful when a task has unresolved structural scope; a fully localized edit with no such question should skip it.

The package ships the same six skills for Claude Code and Codex: scan the project, query the index, find affected tests, rename references, inspect integration, and debrief Claude telemetry. The runtime adapters share the capability contract but keep their host-specific invocation and path rules.

<details>
<summary><strong>Contents</strong></summary>

- [Quick start](#-quick-start)
- [What it solves](#-what-it-solves)
- [Adaptive use](#-adaptive-use)
- [Prerequisites and supported runtimes](#-prerequisites-and-supported-runtimes)
- [Build and query the index](#-build-and-query-the-index)
- [Honest limits](#-honest-limits)
- [Benchmark evidence](#-benchmark-evidence)
- [Six skills](#-six-skills)
- [Integration with other plugins](#-integration-with-other-plugins)
- [Configuration](#-configuration)
- [Compatibility and exit codes](#-compatibility-and-exit-codes)
- [Upgrade, uninstall, and migration](#-upgrade-uninstall-and-migration)
- [Maintainer documentation](#-maintainer-documentation)
- [Contributing and feedback](#-contributing-and-feedback)

</details>

## ⚡ Quick start

Install the plugin in the runtime you use:

```bash
# Claude Code
claude plugin marketplace add Borda/AI-Rig
claude plugin install codemap-py@borda-ai-rig

# OpenAI Codex
codex plugin marketplace add Borda/AI-Rig
codex plugin add codemap-py@borda-ai-rig
```

Start a fresh runtime session after installation. Build an index, then ask the first useful structural question:

```text
# Claude Code
/codemap-py:scan-codebase
/codemap-py:query-code rdeps mypackage.auth

# Codex
$codemap-py:scan-codebase
$codemap-py:query-code rdeps mypackage.auth
```

The direct CLI is also available to a project checkout or to Claude's installed `bin/` PATH. Its first query has the same shape:

```bash
codemap-py index
codemap-py query --compact rdeps mypackage.auth
```

From a source checkout, call the Python entrypoint instead:

```bash
python plugins/codemap-py/scripts/codemap_py_entry.py index
python plugins/codemap-py/scripts/codemap_py_entry.py query --compact rdeps mypackage.auth
python plugins/codemap-py/scripts/codemap_py_entry.py doctor --json
```

**Windows uses this Python entrypoint directly** — `bin/codemap-py` is a `#!/bin/sh` launcher and does not execute there; `bin/codemap-py.cmd` is the installed-package equivalent. macOS and Linux may use either form.

Codex does not add the plugin's `bin/` directory to PATH; use the `$codemap-py:*` skills or resolve the installed plugin root as their runtime instructions describe.

## 🎯 What it solves

Without a structural index, a refactor often starts with repeated file searches to discover importers, callers, and tests. That exploration can miss a reverse dependency or spend time reading files that do not answer the question. codemap-py makes those relationships queryable from one local JSON index and gives each result coverage and freshness metadata.

The index is not a replacement for reading source or running tests. It is a narrow, fast source of structural evidence that helps choose the next inspection or verification step.

## 🔗 Adaptive use

Use the smallest route that answers the unresolved question:

| Question                                                    | Route                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------------ |
| Exact file and symbol are known; no structural fact remains | Skip codemap-py and edit or inspect directly                 |
| Which modules import a module?                              | `rdeps <module>`                                             |
| Which modules does it import?                               | `deps <module>`                                              |
| Which production functions directly call a function?        | `fn-rdeps <module::symbol> --exclude-tests`                  |
| Which functions transitively depend on it?                  | `fn-blast <module::symbol>`                                  |
| Which modules have the highest reverse-dependency count?    | `central --top N --exclude-tests`                            |
| What source slice and imports define a symbol?              | `symbol <name> --with-imports`                               |
| Which tests are structurally affected?                      | `/codemap-py:test-impact` or `$codemap-py:test-impact`       |
| Is the integration wiring and runtime evidence healthy?     | `/codemap-py:integration audit` or `$codemap-py:integration` |

For an explicit request for structural context, query even when an edit looks small. A lifecycle boundary such as a callback, hook, cancellation path, cleanup path, or state transfer also needs source and the named test or oracle; a complete structural result does not prove runtime behavior.

`rdeps` and `deps` answer opposite directions. Query names and paths are relative to the project being queried, not the installed plugin. After a custom-root scan, retain the emitted index path and query with `--index <emitted-index-path> --root <same-root>`: `--root` controls path resolution only and does not select the index.

`fn-rdeps` reports incoming call edges; it does not discover inheritance or same-name override relationships. Use `find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` to gather same-name override candidates, then verify ancestry and package boundaries in source.

## ✅ Prerequisites and supported runtimes

- Claude Code or Codex, depending on the runtime you are installing into.
- CPython `>=3.11,<3.15` for the shipped dispatcher and launchers. The CLI checks this before importing the package and exits `127` when no eligible interpreter is available. Set `CODEMAP_PYTHON` to an eligible interpreter when PATH discovery is not enough.
- Git is recommended for branch-aware freshness checks and incremental rebuilds. Outside Git, content hashes provide a fallback.
- The core scanner and query engine use the Python standard library. `coverage>=7.4` is optional and is needed only for `scan-index --with-coverage` and the `coverage`/`coverage-gap` queries.

The scanner is intended for Python projects. It parses `.py` and `.pyi` files with `ast.parse`; a `.py` implementation takes precedence over a sibling `.pyi`, while a stub without an implementation contributes declarations and imports but no call edges. It also records selected Sphinx references from `.rst` files, `docs/**/*.md`, and supported root configuration files for cross-reference and freshness checks. It does not index TypeScript, Go, Rust, or other non-Python source as Python modules.

## 🗂️ Build and query the index

The canonical CLI is:

```text
codemap-py index [--root PATH] [--incremental] [--with-coverage PATH] [--timeout N]
codemap-py query [global flags] <subcommand> ...
codemap-py doctor [--json]
codemap-py integrate {audit,plan,apply,sync,demo} ...
```

`--incremental` requires an existing v3-or-newer index. `--with-coverage` reads a `.coverage` SQLite file when the optional dependency is available. Query help is authoritative for the complete subcommand and flag list; the current groups include module imports (`deps`, `rdeps`, `central`, `coupled`, `path`), symbol lookup (`symbol`, `symbols`, `find-symbol`), call graphs (`fn-deps`, `fn-rdeps`, `fn-central`, `fn-blast`), test/mock/fixture/subprocess relationships, documentation and coverage checks, dead-code checks, `diff-impact`, and `batch`.

Most query results include an `index` block. Read it before treating a list as final:

- `stale` reports that the index may no longer describe the working tree.
- `query_complete` describes graph coverage for the queried direction; it does not mean a display list was not truncated.
- `confidence`, `truncated`, and `total_available` describe result completeness. The default display limit is bounded for several list commands; use `--limit 0` where that command supports it when the full set matters.
- `not_covered` names static-analysis blind spots and should remain in the final reasoning.

Queries check freshness and may perform a bounded incremental self-heal unless `SCAN_NO_AUTOBUILD=1` disables query-time writes. An explicit scan is the predictable choice after a clone, a large change, a branch switch, or when a query reports stale/degraded coverage.

## 🧭 Honest limits

The graph is static AST evidence. It can miss dynamic dispatch, hook and callback registration, string-based dispatch, `getattr` lookups, `importlib.import_module`, `__import__`, and lazy-loading patterns. Import and call results therefore do not establish runtime behavior, external consumers, test pass status, or inheritance correctness. `rename-refs` calls out dynamic references, cross-repository callers, ABC/Protocol overrides, and caller lists above its edit cap as manual review items.

Files that fail to parse are marked degraded rather than silently treated as complete. Untracked files, root mismatches, collisions, stale hashes, and list caps can all reduce confidence. Review the returned coverage metadata and inspect the relevant source and tests before making a behavior or deletion decision.

Possible future work includes broader dynamic-behavior evidence, deeper cross-language support, and richer freshness diagnostics. Those are opportunities rather than promises; the current contract remains static Python analysis with explicit coverage metadata.

Claude's optional Python hooks provide ambient index status, session-sharded telemetry, skill-start records, and a narrow redundant-import-grep guard. Codex ships hooks for session seeding, ambient preamble/guard behavior, and runtime-scoped tool records, while its host does not provide a Codemap skill-start hook. Both runtimes' hooks fail open and are not required for indexing or querying; the difference is an evidence boundary, not a query-engine capability difference.

Performance and token use vary with repository size, model, index freshness, query choice, and whether an agent continues exploring after a result. Historical benchmark runs are exploratory and repository/model-specific; they do not establish universal savings or quality guarantees. See the [benchmark record](https://github.com/Borda/AI-Rig/blob/main/benchmarks/README.md) for methods and caveats.

## 📈 Benchmark evidence

The benchmark record gives Codemap a measurable, bounded value proposition: on structural questions with unresolved dependency or caller scope, a required Codemap Skill reduced context and elapsed time while improving the aggregate semantic answer score against a no-Codemap baseline. The same record retains unfavorable cells and explains when adaptive routing should skip Codemap.

<a id="codex-structural-2026-08-07"></a>

### Structural navigation snapshot — 2026-08-07

The run used 165 arm/task cells and reports a 43-task independently scored headline cohort after complete triplets with invalid evidence were excluded from that comparison. Host context was macOS 26.5.2 arm64 with 16 CPUs and Python 3.12.13; runtime context was Codex CLI 0.146.1, codemap-py 0.28.7, codex-rig 0.4.6, and `gpt-5.6-luna` at high effort. `A_plain` is the no-Codemap baseline, `B_direct` is required direct CLI access, and `C_skill` is the required installed Skill.

| Arm        | Mean semantic quality | Mean gross input | Mean output | Mean elapsed |
| ---------- | --------------------: | ---------------: | ----------: | -----------: |
| `A_plain`  |                0.9060 |           199.3k |       3,820 |       86.4 s |
| `B_direct` |                0.9682 |           103.9k |       1,962 |       49.4 s |
| `C_skill`  |                0.9875 |           124.5k |       1,629 |       43.4 s |

Quality is the evaluator's continuous semantic answer score in `[0, 1]` (higher is better); input/output are gross model tokens and elapsed is wall-clock time (lower is better). Relative to `A_plain`, the paired `C_skill` ratios were `0.6246×` gross input, `0.4264×` output, and `0.5028×` elapsed, with a descriptive mean-quality delta of `+0.0815`. These are paired aggregates, not a promise for every task: the benchmark reports observed per-task increases as well as savings.

The full run is descriptive and non-poolable because it retained unsuccessful, contaminated, incomplete, and extraction-failed cells; it is one model, one frozen repository revision, one repetition, and a prebuilt index. Fixed arm order and provider cache can bias elapsed time, and index-build cost, cross-repository/model generalization, runtime behavior, and test-pass quality were outside scope. Treat the figures as evidence for task-fit structural retrieval, not proof of universal savings or runtime correctness. Future runs should repeat across repositories and models and add build-inclusive and executable patch/test outcomes before any broader claim. See the [canonical structural result and limitations](https://github.com/Borda/AI-Rig/blob/main/benchmarks/README.md#combined-codemap-py-0287-structural-execution--2026-08-07).

<a id="codex-agentic-2026-08-07"></a>

<details>
<summary><strong>Agentic navigation snapshot — 2026-08-07</strong></summary>

The same host/runtime/model family completed 48 cells across 16 shared import-graph tasks and three arms. Here, quality is the mean semantic answer-component score; input/output/time use the same lower-is-better definitions as above. `C_strict` required one successful compact Codemap query; `B_auto` made Codemap optional.

| Arm        | Mean semantic quality | Mean input | Mean output | Mean elapsed |
| ---------- | --------------------: | ---------: | ----------: | -----------: |
| `A_plain`  |                0.8931 |     426.2k |        7.8k |      171.3 s |
| `B_auto`   |                0.9015 |     223.8k |        4.5k |      107.4 s |
| `C_strict` |                0.9900 |     103.5k |        2.4k |       60.4 s |

Relative to `A_plain`, `C_strict` used paired geometric-mean ratios of `0.337×` input, `0.306×` output, and `0.359×` elapsed, with a mean-quality delta of `+0.0969`. This study is also exploratory and non-poolable: one repetition, one repository revision, optional adoption in the middle arm, diagnostic answer recoveries, fixed arm order, and provider-cache exposure. See the [canonical agentic result and measurement caveats](https://github.com/Borda/AI-Rig/blob/main/benchmarks/README.md#completed-combined-run-codex-agentic-study--2026-08-07).

</details>

<details>
<summary><strong>Extended operational reference</strong></summary>

### 🔗 Integration protocol

The integration engine is source-owned and authenticated. Its modes have distinct evidence and mutation boundaries:

- `audit` is the bounded read-only route. It reports observed provider and consumer versions, managed blocks, index identity, runtime-scoped logs, usage, findings, bounded provider content identity, same-version content drift, and an explicit `session_catalog: unobservable` state when the native listing has no session provenance.
- `plan` writes an inspectable candidate and SHA-256.
- `apply` changes only an approved managed block in checked-in consumer source.
- `sync` installs only an approved local candidate or immutable release through the native runtime CLI.
- `demo` records disposable evidence.

These routes never edit installed caches directly, write global Codex instructions, publish a release, or push Git. Audit cannot claim live fresh-session activation; after a runtime sync, follow the host's fresh-session guidance.

Consumer integrations should treat Codemap as optional structural context. For the two currency states, choose one explicit route:

- Missing index: build it in the foreground, continue without it, or stop and ask for a later scan.
- Stale index: refresh, continue with the stale-data caveat, or skip retrieval.
- Unavailable launcher: use the host's normal source exploration rather than silently claiming that no callers or tests exist.

### 🧭 Skill boundaries and shared truth claims

Both runtime rosters expose the same six capabilities; only invocation syntax and host tool bindings differ. The shared contract is [`shared/capability-contract.md`](https://github.com/Borda/AI-Rig/blob/main/plugins/codemap-py/shared/capability-contract.md), and it is the authority for exit codes, completeness metadata, and static-analysis caveats.

| Skill            | Use it for                                                                                               | It does not do                                                                             |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `scan-codebase`  | Build or refresh the whole Python index, optionally from a consistent `--root`.                          | Answer a query or validate runtime behavior.                                               |
| `query-code`     | Read dependencies, callers, symbols, paths, quality flags, tests, or diff impact from an existing index. | Rename symbols, rebuild explicitly requested indexes, or replace source/test verification. |
| `test-impact`    | Identify structurally affected tests and emit a pytest command; it does not execute that command.        | Prove tests pass or resolve dynamic dispatch invisible to the static graph.                |
| `rename-refs`    | Apply or preview one Python symbol/module rename with a confirmation and re-scan verification pass.      | Guarantee dynamic, cross-repository, or inheritance references are covered.                |
| `integration`    | Audit, plan, apply, sync, or demo the supported consumer wiring with authenticated managed blocks.       | Mutate remote services, global instructions, or an installed cache directly.               |
| `debrief-coding` | Summarize local cross-runtime Codemap telemetry, timing, completeness, and repeated-search avoidance.    | Build/query the index or validate installation health.                                     |

Direction and scope rules:

- `rdeps` and `deps` point in opposite directions.
- For direct production callers, use `fn-rdeps <module::symbol> --exclude-tests`; use `fn-blast` only for an explicitly transitive request.
- For direct test-module importers, use `rdeps` and filter test modules; reserve `test-impact` for transitive affected-test selection.
- A method-name match is only an override candidate; verify ancestry and package boundaries in source.

### 🗂️ Index lifecycle and completeness

Index location and refresh rules:

- Default index: `.cache/codemap/<project>.json`.
- `CODEMAP_INDEX_DIR` changes only the parent directory and keeps the project basename as the filename.
- After a custom-root scan, query with `--index <emitted-index-path> --root <same-root>`; `--root` is path resolution only and does not select the index. With an explicit root, the guard admits only that exact default or `CODEMAP_INDEX_DIR`-override emitted path outside the caller project; arbitrary sibling files remain rejected.
- Prompt freshness runs its indexed dirty-path check from the Git root, so a nested session detects root-level `.py`, `.pyi`, `.rst`, and nested documentation Markdown changes before starting its bounded refresh.
- Normal queries may perform a bounded incremental self-heal; `SCAN_NO_AUTOBUILD=1` makes a missing index a hard refusal and prevents implicit writes.

Every query exposes an `index` block. Follow this sequence:

1. Query first; do not spend a call on an unconditional pre-scan or freshness probe.
2. Read `query_complete` as direction-scoped graph coverage, not as a promise that a bounded display list is untruncated.
3. Inspect `confidence`, `truncated`, and `total_available`; use `--limit 0` where supported when the complete list matters.
4. After a complete, untruncated result, do not re-query, read, or grep for the same structural fact. Source-body reads remain valid for distinct implementation or runtime details.
5. For an incomplete or degraded result, use only a targeted fallback for the named gap (`stale`, `degraded`, `not_covered`, or similar); use `test-impact` when the open question is test choice.

`stale`, degraded modules, untracked files, root mismatches, and collisions lower confidence and require source/test review.

### 🔍 Troubleshooting checklist

Use this order when a route is inconclusive:

1. Dispatcher `127`: inspect `CODEMAP_PYTHON` and the eligible CPython range before debugging imports.
2. Missing or stale index: run `codemap-py index --root PATH`, then repeat the query from the same project root.
3. Capped list: inspect its completeness metadata and rerun with a supported larger limit.
4. Hooks, callbacks, dynamic imports, string dispatch, lazy loading, or inheritance: read the source and named test/oracle regardless of a complete static result.
5. Integration drift: run `codemap-py integrate audit --json`, inspect observed findings, and create a fresh stage-specific plan before applying or syncing anything.

<details>
<summary><strong>Complete integration mode reference</strong></summary>

The integration skill is a thin, source-owned adapter over `codemap-py integrate`. It has a closed consumer set: Claude consumers `foundry`, `oss`, `develop`, and `research`, and Codex consumer `codex-rig`. It does not discover arbitrary plugins or invoke another runtime's model.

| Mode    | Supported arguments                                                                                         | Writes or mutates                                                                          |
| ------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `audit` | \[`--runtime {claude,codex,both}`\] \[`--json`\] \[`--since YYYY-MM-DD`\]                                   | Nothing; reports observed provider/consumer/index/log evidence, findings, and remediation. |
| `plan`  | \[`--runtime ...`\] \[`--consumers <csv>`\] \[`--source {local-candidate,release}`\] \[`--out <artifact>`\] | A reviewable plan artifact containing targets, hashes, argv, and rollback identities.      |
| `apply` | `--plan <artifact> --approve <sha256>`                                                                      | Approved managed blocks in checked-in consumer source only.                                |
| `sync`  | `--source {local-candidate,release} --plan <artifact> --approve <sha256> [--runtime ...]`                   | Approved local runtime plugin state through the native runtime CLI.                        |
| `demo`  | \[`--runtime {claude,codex,both}`\]                                                                         | Disposable evidence under `.reports/integrate/`; no durable wiring.                        |

`audit` has this contract:

- Defaults to `both`; supports `--runtime claude|codex|both`, JSON schema 2 (`codemap-py.integration.v2`), and `--since YYYY-MM-DD`.
- Reports `pass`, `warn`, or `fail`; exits `0`, `1`, or `2` for completed status/syntax semantics.
- Records stable findings such as `runtime_log_isolation_bypassed`, `runtime_identity_missing`, `runtime_logs_not_observed`, `managed_block_invalid`, `split_index_roots`, `index_stale_or_unknown`, and `index_degraded`.
- Remediation values are advisory (`plan_apply`, `plan_sync`, `provider_release_required`, `scan_codebase`, `observe_next_session`, `none`) and are never executable artifacts.
- `--runtime claude` scopes to the four Claude consumers; `--runtime codex` scopes to `codex-rig`.
- `--approve` is valid only with `apply` or `sync`, a saved plan, and the exact SHA-256 printed for that plan.

Mutation boundaries:

- `plan` is non-mutating.
- `apply` refuses path escapes, symlinks, installed-cache roots, dirty overlap, foreign markers, and body hashes that were not generated by the engine.
- `sync` uses either a deterministic local candidate or an immutable release identity and reports a journal for partial failure.
- Both mutation modes leave Git commits and pushes to the maintainer.

```text
/codemap-py:integration audit --runtime both --json
/codemap-py:integration plan --consumers foundry,oss --out .reports/integrate/plan.json
/codemap-py:integration apply --plan .reports/integrate/plan.json --approve <printed-sha256>
/codemap-py:integration sync --source release --plan .reports/integrate/plan.json --approve <printed-sha256> --runtime codex
/codemap-py:integration demo --runtime both
```

</details>

<details>
<summary><strong>Scan-codebase flags, performance, and exclusions</strong></summary>

The scan skill dispatches `codemap-py index`; it does not answer a query. Its verified CLI surface is:

| Flag                   | Contract                                                                                                   |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- |
| `--root PATH`          | Scan the selected project root instead of the Git root or current directory.                               |
| `--incremental`        | Re-parse changed files against an existing v3-or-newer index; without one, fall back to a full scan.       |
| `--with-coverage PATH` | Attach per-symbol line coverage from a `.coverage` SQLite file when `coverage>=7.4` is installed.          |
| `--timeout N`          | Set a hard Unix `SIGALRM` timeout in seconds; `0` means no limit and Windows does not provide this signal. |

Scan behavior and routing:

- The full scan walks Python files with `ast.parse`, records imports, symbols, calls, hashes, source-root metadata, and degraded-file reasons, then writes one JSON index.
- Incremental mode compares stored Git blob hashes or non-Git content hashes.
- Build duration varies with repository size and filesystem; the scanner reports indexed and degraded counts, so the README does not promise fixed timings.
- Run a full scan after clone or a large structural change, and use incremental mode after smaller changes or when a currency gate requests it.

```text
/codemap-py:scan-codebase
/codemap-py:scan-codebase --incremental
/codemap-py:scan-codebase --root services/api
codemap-py index --with-coverage .coverage
```

Built-in pruning excludes `.git`, virtual environments, build/dist/cache trees, `node_modules`, scratch/report directories, and dot-directories. Add project-specific exclusions in either form:

```toml
[tool.codemap]
exclude = ["vendor-copy", "generated/*.py"]
src_roots = ["packages/core/src", "services/api/src"]
```

```text
# .codemapignore: one directory name or fnmatch path per line
vendor-copy
generated/*.py
```

Exclusion semantics:

- A bare name prunes matching directories anywhere; a path or glob matches a project-relative file path.
- Exclusions are recorded in `excluded_roots` and do not trigger incremental rebuilds.
- `src_roots` is ordered: the first matching root determines module naming and collision priority.
- The index records effective roots and any deterministic module-name collisions so a result is not mistaken for a complete graph.

</details>

<details>
<summary><strong>Query-code subcommands and completeness contract</strong></summary>

The query CLI reads an existing index and emits JSON. The complete subcommand surface is grouped below; feature-gated commands report that an older index must be rebuilt rather than silently returning an incomplete answer.

Additional query contracts:

- The module group also includes `import-types <module>`.
- `deps` accepts `--stdlib`, `--third-party`, or `--internal`; `rdeps`, `central`, and `coupled` accept `--entity TYPE` for indexed project, test, docs, or example entities. `rdeps --limit N` previews static `imported_by` only; `dynamic_imported_by` and `config_refs` remain exhaustive. Default `rdeps` and `rdeps --limit 0` return every static importer.
- The path query returns exit 0 with a null path and reason `no-import-path` when known modules are disconnected; unknown-module and filesystem failures remain errors.
- Symbol responses expose `stale` and `stale_reason` when recorded line ranges no longer match source.
- Function results carry call-edge resolution (`import`, `local`, `self`, `star`, or `unresolved`), while `fn-rdeps` reports distinct caller count rather than raw call-site multiplicity.

| Group                          | Commands and purpose                                                                                                                                                                            |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Modules                        | `deps <module>`, `rdeps <module> [--limit N]`, `path <from> <to>`, `central [--top N]`, `coupled [--top N]`, `list [--limit N]`, `packages`                                                     |
| Symbols                        | `symbol <name> [--limit N] [--exclude-tests] [--with-imports]`, `symbols <module>`, `find-symbol <regex> [--limit N] [--exclude-tests]`                                                         |
| Calls                          | `fn-deps <module::symbol>`, `fn-rdeps <module::symbol> [--exclude-tests]`, `fn-central [--top N] [--exclude-tests]`, `fn-blast <module::symbol>`                                                |
| Tests and edges                | `test-impact <module[::symbol]> [--no-mocks]`, `mock-rdeps <module[::symbol]>`, `fixture-rdeps <fixture>`, `fixture-graph <test-file>`, `subprocess-deps <module>`, `subprocess-rdeps <module>` |
| Coverage and docs              | `coverage <module[::symbol]>`, `coverage-gap [module] [--all] [--threshold P]`, `uncovered [module] [--all] [--sort loc, name, or module] [--top N]`, `undocumented [module] [--all]`           |
| Cross-references and dead code | `xrefs <symbol-or-module> [--broken]`, `dead-symbols [--min-loc N]`, `dead-modules`                                                                                                             |
| Composite                      | `diff-impact [--base REF] [--diff-file PATH]`, `batch [JSON-PATH or stdin]`                                                                                                                     |

Every query accepts these global flags before or after the subcommand:

- `--index PATH` selects the index file.
- `--root PATH` resolves paths only; it does not retarget or rebuild an index, and a mismatch forces `query_complete=false`.
- `--timeout N` sets the query timeout.
- `--no-heal` answers from the existing index without bounded query-time refresh.
- `--verbose-coverage` keeps the full coverage block on every query.
- `--compact` reduces repeated coverage metadata.

Choose direction deliberately:

- `rdeps` means importers; `deps` means imports.
- `fn-rdeps` means direct callers; `fn-blast` means transitive callers.
- `central` ranks reverse imports; `coupled` ranks internal import count.
- Use `symbol --with-imports` for a source slice plus its module imports, `find-symbol` for a regex, and `path` for the shortest import chain.
- `find-symbol` name matches are override candidates, not inheritance proof.

Batch and diff behavior:

- Batch input is a JSON array of objects such as `[{"cmd":"rdeps","args":["mypackage.auth"]}]` read from a file or stdin.
- Items execute in one process and share one coverage block; nested `batch` and `diff-impact` items are rejected.
- `diff-impact` derives changed modules, per-module reverse dependencies/coupling, function callers, and a union of affected tests from a Git ref or unified diff.

Coverage metadata is intentionally dieted after the first query in a process. Keep these distinctions when interpreting results:

- Use `--verbose-coverage` when each result must carry the full block.
- `query_complete` is direction-scoped graph coverage, not a guarantee that a list is untruncated.
- Read `confidence`, `truncated`, and `total_available`.
- `symbol`, `find-symbol`, and list-like commands default to bounded output and accept `--limit 0` where documented.
- A complete graph with a capped display is still only a displayed slice; a truncated `rdeps` preview never settles exhaustive callers.

```text
codemap-py query --compact rdeps mypackage.auth --exclude-tests
codemap-py query fn-rdeps mypackage.auth::validate --exclude-tests
codemap-py query symbol validate --with-imports --limit 0
codemap-py query find-symbol '^Auth.*Handler$' --exclude-tests --limit 0
codemap-py query batch - < requests.json
```

</details>

<details>
<summary><strong>Test impact and rename-refs contracts</strong></summary>

The `test-impact` skill has a deliberately narrow contract:

- Accepts exactly one target, either a bare module or `module::symbol`, plus `--no-mocks`.
- Identifies structurally affected test files, preserves the index completeness and `not_covered` caveats, and emits a pytest command for the maintainer to review and run.
- Does not execute tests, find every caller, or prove runtime behavior.
- For more than one target, use separate invocations; the skill warns rather than silently combining them.

```text
/codemap-py:test-impact mypackage.auth::validate --no-mocks
$codemap-py:test-impact mypackage.auth
```

`rename-refs` has two explicit subcommands:

```text
/codemap-py:rename-refs symbol <old-qname> <new-qname> [--dry-run] [--deprecate[=<decorator>]] [--since <version>] [--removed-in <version>] [--remove-if-no-callers]
/codemap-py:rename-refs module <old-module> <new-module> [--dry-run]
```

Rename behavior and safety gates:

- The symbol route updates a one-to-one Python definition and statically visible references; the module route renames a file/module and import lines.
- `--dry-run` previews without editing.
- `--deprecate` is symbol-only and defaults to the project deprecation decorator; `--since` and `--removed-in` add the version window.
- `--remove-if-no-callers` is a hard safety gate: it is honored only when the caller graph is complete, zero callers are found, and the user confirms removal.
- The workflow refuses ambiguous or one-to-many matches, stale or degraded coverage, path escapes, dynamic references, cross-repository callers, and caller sets above its edit cap; inspect source and tests for those cases.
- A successful edit is followed by an explicit rescan and verification step.

```text
/codemap-py:rename-refs symbol mypackage.auth::validate mypackage.auth::verify --dry-run
/codemap-py:rename-refs symbol mypackage.auth::validate mypackage.auth::verify --deprecate --since 2.1 --removed-in 3.0
/codemap-py:rename-refs module mypackage.old_utils mypackage.utils
```

</details>

<details>
<summary><strong>Debrief-coding telemetry and anonymization</strong></summary>

`debrief-coding` reads local JSONL telemetry and writes a diagnostic report; it does not build or query the index. Its collection and report contract is:

- Flags: `--since YYYY-MM-DD`, `--session ID`, `--anonymize`, and `--output PATH` (default `.reports/codemap/debrief-<date>.md`).
- Claude records CLI, skill, and tool layers under `.cache/codemap/logs/`; Codex hooks record runtime-scoped CLI and tool shards but have no skill-start hook, so skill telemetry and some cross-layer joins can be unavailable.
- Flat legacy records remain unattributed.
- Reports include overall, per-runtime, and unattributed usage summaries, refresh provenance, timing, completeness, and repeated-search avoidance.
- `token_measurement` is unavailable because host hooks provide no token usage. Debrief does not measure token savings or verify live fresh-session activation.
- Set `CODEMAP_LOGGING=false` to disable logging. Logs rotate at the implementation-defined size limit.

The report summarizes command, skill, and search/read activity, timing, result counts, completeness reasons, per-runtime usage, and repeated-search avoidance. `join_avoidance.py` performs the offline join with a bounded time window; an avoidance event means a search/read names a module that a complete Codemap query already answered, not that the agent's runtime answer is incorrect.

Anonymization behavior:

- `--anonymize` pseudonymizes qualified names with a project-local salt at `.cache/codemap/logs/.salt`, scrubs qualified names inside error and stderr text, hashes `not_covered` values, and writes export JSONL separately.
- Never share the salt with an anonymized export.
- Anonymization protects names in the supported log fields; it is not a guarantee that arbitrary free text contains no identifying information.

```text
/codemap-py:debrief-coding
/codemap-py:debrief-coding --since 2026-08-01 --session <session-id>
/codemap-py:debrief-coding --anonymize --output .reports/codemap/debrief-shareable.md
```

</details>

<details>
<summary><strong>Scanner, query, and index architecture</strong></summary>

Scanner and query architecture:

- The scanner is dependency-free Python: it walks the selected root, parses `.py` and `.pyi` files with the standard-library AST, resolves imports and selected call edges, computes module/function graph counts, captures supported documentation references, and writes an atomic versioned JSON index.
- A `.py` implementation takes precedence over a sibling stub; an unpaired stub contributes declarations/imports but no implementation call edges.
- Parse or encoding failures are retained as degraded module records instead of being silently dropped.
- Incremental refreshes still track changed documentation for freshness and documentation references, but only `.py` and `.pyi` entries become module records, so documentation changes no longer contaminate module degradation counts and a subsequent refresh self-heals the index.

The query engine loads the same JSON under a read lease, performs bounded freshness checks or self-heal, dispatches one subcommand, and returns a primary result plus an `index` coverage block. The block includes method, confidence, query completeness, truncation, totals, degraded count, stale/root-mismatch state, and `not_covered` blind spots. The index is a cache, not a daemon or runtime tracer; no static result proves dynamic dispatch, external consumers, inheritance, test pass status, or behavior.

The default index contains modules, relative paths, symbols and line ranges, direct imports, calls and resolution tags, test/entity classification, source-root metadata, exclusions, collisions, scan version, and Git blob or non-Git content hashes. The JSON format is version-gated: call-graph, fixture, subprocess, documentation, dead-code, and coverage queries refuse unsupported index versions with an upgrade/rebuild instruction.

</details>

<details>
<summary><strong>Index locations, non-Git roots, and currency</strong></summary>

Index location and currency:

- By default the index is `.cache/codemap/<project>.json`, where `<project>` is the selected root basename.
- `CODEMAP_INDEX_DIR` changes the base to `<override>/<project>.json`; use separate override directories when two projects share a basename.
- `--index PATH` selects a specific query file, while `--root PATH` only controls path resolution.
- `SCAN_NO_AUTOBUILD=1` disables implicit query refresh and makes missing indexes a structured manual-build error.
- Git repositories use stored Git blob hashes and the repository revision for fast currency checks. Non-Git projects use content hashes, so incremental scans and stale detection still work without `git`.
- A custom root is recorded as `scan_root`; subsequent scans and queries must use that same tree or explicitly select the matching index. Multiple configured `src_roots` are ordered and recorded to make module naming reproducible.
- The integration and consumer currency gates distinguish a missing index from stale data: Gate A offers build, continue without Codemap, or abort; Gate B offers refresh, continue with an explicit stale caveat, or abort.
- There is no post-commit hook requirement. Explicit scan remains available for CI and benchmarks where build cost should be controlled.

```bash
CODEMAP_INDEX_DIR=<absolute-cache-dir> codemap-py index --root <project-root>
SCAN_NO_AUTOBUILD=1 codemap-py query --index <matching-index> rdeps mypackage.auth
```

</details>

<details>
<summary><strong>Named troubleshooting cases</strong></summary>

| Symptom                                 | Evidence-led response                                                                                                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `127` from a launcher                   | Check `CODEMAP_PYTHON`, PATH, and the supported CPython range before inspecting imports.                                                                               |
| `index not found` or empty results      | Confirm the selected root has Python files, check `CODEMAP_INDEX_DIR`, then run an explicit scan.                                                                      |
| stale or `root_mismatch`                | Re-scan the exact root and query from that root or pass the matching `--index`; do not report the graph as complete.                                                   |
| `query_complete=false`                  | Read `completeness_reason`, `degraded`, `untracked`, `collision`, and `not_covered`; investigate only the named gap.                                                   |
| capped result                           | Inspect `truncated` and `total_available`, then rerun with a supported larger `--limit` or `--limit 0`.                                                                |
| `upgrade required`                      | Rebuild the index with the current scanner; feature-gated graph data cannot be inferred from an older file.                                                            |
| degraded modules                        | Inspect the recorded path/reason; generated or syntax-invalid files remain outside reliable graph coverage.                                                            |
| `scan-query` not found                  | Use the skill, resolve the installed launcher path, or add the package `bin/` directory to PATH; Codex does not inject it automatically.                               |
| integration missing/outdated            | Run `integration audit`, inspect observed evidence and the source-owned managed block, then create a fresh stage-specific plan rather than editing an installed cache. |
| dynamic hook/callback/override behavior | Treat static results as candidates; inspect implementation and named tests/oracles because AST edges cannot prove runtime behavior.                                    |

</details>

</details>

## 🔧 Six skills

Both runtimes expose these names:

| Skill            | Purpose                                                                                              |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| `scan-codebase`  | Build or refresh the Python structural index. Explicit invocation; it does not answer a query.       |
| `query-code`     | Select and render a structural query without rebuilding or editing source.                           |
| `test-impact`    | Identify affected test files and emit a pytest command; it does not run tests.                       |
| `rename-refs`    | Rename a Python symbol or module using static caller/import evidence, with confirmation and caveats. |
| `integration`    | Audit, plan, apply, sync, or demo the supported consumer wiring and runtime evidence.                |
| `debrief-coding` | Analyze local cross-runtime Codemap telemetry, optionally producing an anonymized report.            |

Claude uses `/codemap-py:<skill>`. Codex uses `$codemap-py:<skill>`. Both skill rosters use concise, instruction-first prose while retaining command syntax, routing, stop rules, safety gates, and runtime notes for installed-root resolution, PATH behavior, and each host's confirmation mechanism. Claude executable fences remain byte-identical so compression cannot change shell behavior.

## 🔗 Integration with other plugins

The integration engine has an explicit closed consumer set:

- Claude consumers: `foundry`, `oss`, `develop`, and `research`.
- Codex consumer: `codex-rig`.

`/codemap-py:integration audit` or `$codemap-py:integration` reports observed installed versions, roots, protocol compatibility, managed blocks, runtime-scoped telemetry, and wiring state without guessing at unavailable runtime facts.

Mode boundaries:

- `plan` writes an inspectable artifact.
- `apply` updates only approved managed blocks in checked-in consumer source.
- `sync` installs only the approved local candidate or immutable release through the native runtime CLI.
- Both mutation modes require the plan SHA-256 and never push Git, publish a release, edit installed caches directly, or write Codex global instructions.
- `demo` records disposable evidence.

## ⚙️ Configuration

The default index path is `.cache/codemap/<project>.json`, where `<project>` is the project-root basename. Set `CODEMAP_INDEX_DIR` to an absolute override directory to use `<override>/<project>.json`; separate colliding project names with separate override directories. `SCAN_NO_AUTOBUILD=1` keeps query and test-impact routes from creating or refreshing an index implicitly.

Use `--root PATH` when the Python tree is a subproject or monorepo component. The scan names the index from that root's basename, and later queries must use the same root or an explicit matching index. `--root` on query controls file-path resolution; it does not retarget an index built for a different tree, and a mismatch is reported rather than silently accepted.

## 🔢 Compatibility and exit codes

`scan-index` and `scan-query` remain compatibility aliases for the canonical `codemap-py index` and `codemap-py query` launchers. New skill and documentation examples use the canonical dispatcher. The `.cache/codemap/` layout and `CODEMAP_*` variables remain compatible with the renamed product.

```text
! BREAKING — the Claude skill namespace changed from `/codemap:*` to `/codemap-py:*`. Every saved prompt, alias, or automation invoking a `/codemap:scan-codebase`-style trigger stops resolving.
Fix: update each call site to `/codemap-py:<skill>`. `scan-index`/`scan-query`, `.cache/codemap/`, and every `CODEMAP_*` variable are unaffected and keep working unchanged.
```

```text
! BREAKING — the `path` query changed its no-path result shape. A legitimate "no import path exists" answer now returns `{"path": null, "reason": "no-import-path"}` at exit 0; the former `{"error": "No import path found."}` key is gone. Any consumer branching on that `error` key silently misreads a valid empty result as a failure.
Fix: test `path === null` or read `reason`. Genuine failures (unknown module) still use the non-zero `error` contract, so the two cases are now distinguishable.
```

|  Exit | Meaning                                                                              |
| ----: | ------------------------------------------------------------------------------------ |
|   `0` | Successful request, including a valid empty result.                                  |
|   `1` | Runtime, index, filesystem, or integration failure.                                  |
|   `2` | Invalid command syntax, option, or approval.                                         |
|   `3` | Requested module or symbol is not indexed where the command distinguishes that case. |
| `127` | No eligible CPython interpreter was found by the dispatcher.                         |

## ⬆️ Upgrade, uninstall, and migration

Upgrade through the runtime's normal plugin manager and start a fresh session:

```bash
claude plugin install codemap-py@borda-ai-rig
codex plugin add codemap-py@borda-ai-rig
```

The second command applies to Codex; run only the command for the runtime you use. Consumer wiring is source-owned and managed through the integration contract; an upgrade does not inject files into an installed cache.

The direct successor to the old `codemap` plugin is `codemap-py`. Do not run both identities in one session — the legacy plugin does not implement the shared-index read/write gate and is rejected as a concurrent producer. Before switching, note the installed `codemap` version so a rollback has a known target. Then close old sessions, uninstall or disable the old plugin, install `codemap-py`, start a fresh session, and run the runtime's integration audit. The project cache is retained and revalidated; no migration step deletes it.

### Rolling back

1. Uninstall or disable `codemap-py` and close its sessions.
2. Reinstall the old `codemap` release from the immutable rollback source — commit `08e06b7a`, legacy `codemap` `0.24.1`.
3. Start a fresh session.
4. Verify the old `/codemap:*` commands resolve again against the retained `.cache/codemap/` project cache.

Rollback never deletes or rewrites the project cache; it is only ever read and revalidated.

### Uninstall

```bash
claude plugin uninstall codemap-py
codex plugin remove codemap-py@borda-ai-rig
```

Run only the command for the runtime you installed into.

## 📚 Maintainer documentation

- [`bin/README.md`](https://github.com/Borda/AI-Rig/blob/main/plugins/codemap-py/bin/README.md) documents shipped launchers, helpers, and compatibility shims.
- [`scripts/README.md`](https://github.com/Borda/AI-Rig/blob/main/plugins/codemap-py/scripts/README.md) documents deterministic package builds, validation, and install probes.
- [The rendered Codemap-py page](https://borda.github.io/AI-Rig/codemap-py/) projects this README into the documentation site.
- [`CHANGELOG.md`](https://github.com/Borda/AI-Rig/blob/main/plugins/codemap-py/CHANGELOG.md) records versioned runtime and documentation changes.

## 🙏 Contributing and feedback

Open an issue in [Borda/AI-Rig](https://github.com/Borda/AI-Rig) with the codemap-py version, CPython version, command, project layout, and the complete error or coverage block. Keep benchmark task IDs and repository-specific fixtures in benchmark evidence, not in shipped plugin docs. Changes to skills, hooks, manifests, or runtime contracts require synchronized README updates and the plugin checks described in the repository authoring guidance.

<a id="claude-agentic-2026-08-04"></a> <a id="codex-structural-2026-08-03"></a> <a id="three-model-comparison"></a>

> Historical benchmark anchors are retained for links from the benchmark record. Current values, methods, and limitations belong in [`benchmarks/README.md`](https://github.com/Borda/AI-Rig/blob/main/benchmarks/README.md); this plugin README intentionally does not duplicate run-specific tables.
