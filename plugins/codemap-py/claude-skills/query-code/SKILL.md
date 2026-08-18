---
name: query-code
description: >-
  Query Codemap's Python structural index for dependencies, callers, paths, symbols, blast radius, test impact,
  mocks, fixtures, subprocesses, and static gaps. Trigger for "what depends on", "who calls", "imports of",
  "dependency graph", or "blast radius". Skip for renames, text search, non-Python repositories, or index rebuilds.
argument-hint: "<rdeps|deps|path|central|coupled|symbol|symbols|find-symbol|fn-rdeps|fn-deps|fn-blast|diff-impact|test-impact|mock-rdeps|fixture-rdeps|fixture-graph|subprocess-deps|subprocess-rdeps|coverage|coverage-gap|undocumented> ..."
allowed-tools: Bash(codemap-py query:*), Bash(*/bin/codemap-py* query:*), Read, Write
model: haiku
effort: low
---

<objective>
Answer structural Python questions with the unified `codemap-py query` CLI.

NOT for: rebuilding the index (use `/codemap-py:scan-codebase`), renaming symbols (use `/codemap-py:rename-refs`), or which tests cover or are affected by a change (use `/codemap-py:test-impact`).
</objective>

Test-impact split: a one-off structural fact ("which tests would this touch?") is the `test-impact <target>` subcommand in the table below; the full affected-test workflow (index ensure, JSON parse, `pytest` command, `not_covered` caveat) is `/codemap-py:test-impact`. The NOT-for line above defers the workflow, not the subcommand.

Skip Codemap when an exact file and symbol are supplied for a localized edit and no caller, dependency, blast-radius, test-impact, import, or source-slice fact remains unresolved. A lifecycle boundary—callback/hook, cancellation/exception, scheduling/cleanup, or state transfer—means source scope remains unresolved: inspect source plus the named test/oracle, then query `fn-rdeps` for caller or `fn-deps` for callee responsibility. An explicit structural query or tool requirement overrides this skip; otherwise choose the smallest complete query.

<workflow>

## Choose the smallest complete query set

Direction matters: "affected if X changes" means reverse dependencies. Run every query from the caller's current repository: its current working directory determines the project index. Do not `cd` into `$CLAUDE_PLUGIN_ROOT` or any plugin directory.

```bash
codemap-py query --compact <subcommand> [arguments]
```

The enabled plugin adds its version-matched `bin/` directory to the Bash tool's `PATH`. In an interactive installation where that command is unavailable, invoke the installed plugin's absolute `bin/codemap-py` launcher as one standalone command and accept the host's normal permission prompt; do not prepend `cd`, `export`, or another shell command.

| Goal | Query subcommand |
| --- | --- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| direct test-module importers | `rdeps <module>` then filter/report test modules |
| module imports | `deps <module>` |
| shortest import chain | `path <from> <to>` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| symbol source including module imports or module symbols | `symbol <name> --with-imports` · `symbols <module>` |
| regex symbol search | `find-symbol <pattern>` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| callers plus test-module importers | `fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>` |
| direct imports / callees | `fn-deps <module::symbol>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| broken Sphinx cross-references | `xrefs --broken <module>` |
| changed-code blast radius | `diff-impact [--base REF]` |
| transitive affected tests / mocks | `test-impact <target>` · `mock-rdeps <target>` |
| pytest fixtures | `fixture-rdeps <name>` · `fixture-graph <test-file>` |
| subprocess relationships | `subprocess-deps <module>` · `subprocess-rdeps <module>` |
| coverage / documentation gaps | `coverage <target>` · `coverage-gap [module]` · `undocumented [module]` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

For requests for test modules that directly import a module, use `rdeps <module>` and filter/report test modules; reserve `test-impact <target>` for transitive affected-test selection.

`symbol <name>` accepts a bare function name such as `authenticate` or a qualified class method such as `MyClass.method`; `module::symbol` belongs to `fn-*` call-graph queries. When chaining a `symbol` result into `fn-*`, compose its returned `module` and `qualified_name` exactly as `<module>::<qualified_name>`; for example, `mypackage.module::MyClass.method`. For feature scaffolding, query the requested qualified extension method (for example, `symbol MyClass.add_feature`), not a nearby `symbol MyClass` or `symbols <module>` listing unless the user requests that broader scope.

For method changes that may affect overrides, use `find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` to find same-name implementation/override candidates. Name matching is candidate discovery only, not proof of inheritance; inspect each source to verify ancestry and package boundaries before treating it as an override.

When a source request names imports, use `symbol <name> --with-imports`; `query_complete: true` confirms index coverage, not that optional fields were requested.

That table is a routing shortlist, not the parser's full surface — `codemap-py query --help` lists every supported subcommand. Read it rather than guessing a name when the need above is not covered.

## Index and completeness contract

Run the selected query set first; do not spend a call on an unconditional pre-scan or freshness probe. Run independently required queries as separate commands rather than `batch`. Use `test-impact` when the open question is test choice rather than a direct test-module import.

- Normal mode may perform the CLI's bounded incremental self-heal.
- With `SCAN_NO_AUTOBUILD=1`, do not run a freshness query, incremental
  refresh, or automatic full build. Query the existing index exactly as-is.
- A missing frozen index is a hard stop; report the structured error and ask
  for `/codemap-py:scan-codebase`.
- An explicit user-requested `codemap-py index` remains allowed because the
  environment flag blocks implicit writes only.

Interpret `index`:

- A complete, untruncated `query_complete: true` result settles the structural fact when it answers the request. Complete-query paths are caller-repo-relative, never Skill-relative; do not re-query/read/grep for that same graph fact.
- Ordinary repository reads remain allowed for a task-requested distinct independent AST/oracle view; source-body implementation/runtime reads are also allowed. Label either separately, never as rechecking a complete Codemap result.
- `query_complete: false`: name `completeness_reason`; use only a targeted fallback for gaps named by `degraded`, `not_covered`, `root_mismatch`, or `stale`.
- `compact: true` changes coverage metadata only; findings and counts remain
  complete.

Truncation is not incompleteness. Result truncation at 20 items is a real cap, not an exhaustive list, unless `--limit 0` is passed (`symbol` and `find-symbol` carry that default). `query_complete` scores graph coverage only — staleness, degraded files, untracked files, root mismatch, name collisions — and never reports the cap, so `query_complete: true` on a capped list is still 20-of-N and does not license "stop querying" for the missing items.

Read `index.confidence` before treating a list as whole: `"exact"` = every match returned, `"partial"` = capped or stale. When capped, `index.truncated: true` and `index.total_available: <N>` name the real total — re-run with `--limit 0` (or a `--top`/`--limit` above `total_available`) before reporting the list as complete. That re-run is a correction, not a new question, and is covered by the three-call budget below.

Maximum: three Codemap calls, including one correction to a started name or
argument error. `fn-blast` takes one qualified name, never `--depth`;
`coupled` is not `central`. Never invent flags or retry a completed structural
query. A tool-routing failure does not count when no CLI command ran. After
three, report partial results and the remaining caveat.

## Render

Use the JSON primary array: `imported_by` / `direct_imports`, `called_by` /
`calls`, `path`, `symbols`, `central` / `coupled`, `blast_radius`, or
`changed_modules` plus `test_impact`. Preserve qualified names exactly. Include
stale, degraded, root-mismatch, and `not_covered` caveats when present.

Output routing (the only use of `Write`): if the rendered result set is 5+ items, write it to `.temp/output-query-code-<branch>-<YYYY-MM-DD>.md`.

</workflow>
