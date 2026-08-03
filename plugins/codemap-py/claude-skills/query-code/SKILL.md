---
name: query-code
description: >-
  Query Codemap's Python structural index for dependencies, callers, paths, symbols, blast radius, test impact,
  mocks, fixtures, subprocesses, and static gaps. Trigger for "what depends on", "who calls", "imports of",
  "dependency graph", or "blast radius". Skip for renames, text search, non-Python repositories, or index rebuilds.
argument-hint: "<rdeps|deps|path|central|symbol|symbols|find-symbol|fn-rdeps|fn-deps|fn-blast|diff-impact> ..."
allowed-tools: Bash, Read, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>
Answer structural Python questions with the unified `codemap-py query` CLI.

NOT for: rebuilding the index (use `/codemap-py:scan-codebase`) or renaming
symbols (use `/codemap-py:rename-refs`).
</objective>

<workflow>

## Choose one query

Direction matters: "affected if X changes" means reverse dependencies.

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact <subcommand> [arguments]
```

| Goal | Query subcommand |
| --- | --- |
| module importers / blast radius | `rdeps <module> [--exclude-tests]` |
| direct test-module importers | `rdeps <module>` then filter/report test modules |
| module imports | `deps <module>` |
| shortest import chain | `path <from> <to>` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| symbol source or module symbols | `symbol <name> [--with-imports]` · `symbols <module>` |
| regex symbol search | `find-symbol <pattern>` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| direct imports / callees | `fn-deps <module::symbol>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| changed-code blast radius | `diff-impact [--base REF]` |
| transitive affected tests / mocks | `test-impact <target>` · `mock-rdeps <target>` |
| pytest fixtures | `fixture-rdeps <name>` · `fixture-graph <test-file>` |
| subprocess relationships | `subprocess-deps <module>` · `subprocess-rdeps <module>` |
| coverage / documentation gaps | `coverage <target>` · `coverage-gap [module]` · `undocumented [module]` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

For requests for test modules that directly import a module, use `rdeps <module>` and filter/report test modules; reserve `test-impact <target>` for transitive affected-test selection.

Use `codemap-py query --help` only when needed.

## Index and completeness contract

Run the selected query first; do not spend a call on an unconditional freshness
probe.

- Normal mode may perform the CLI's bounded incremental self-heal.
- With `SCAN_NO_AUTOBUILD=1`, do not run a freshness query, incremental
  refresh, or automatic full build. Query the existing index exactly as-is.
- A missing frozen index is a hard stop; report the structured error and ask
  for `/codemap-py:scan-codebase`.
- An explicit user-requested `codemap-py index` remains allowed because the
  environment flag blocks implicit writes only.

Interpret `index`:

- `query_complete: true`: answer immediately; no re-query or grep/read
  verification.
- Ordinary repository reads remain allowed only for a task-requested distinct independent AST/oracle view; label it separately, never as rechecking a complete Codemap result.
- `query_complete: false`: name `completeness_reason`; search only gaps named
  by `degraded`, `not_covered`, `root_mismatch`, or `stale`.
- `compact: true` changes coverage metadata only; findings and counts remain
  complete.

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

</workflow>
