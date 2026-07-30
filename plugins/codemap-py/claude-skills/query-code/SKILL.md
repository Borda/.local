---
name: query-code
description: |
  Query Codemap's Python structural index for dependencies, callers, paths,
  symbols, blast radius, test impact, mocks, fixtures, subprocesses, and
  coverage. Trigger for "what depends on", "who calls", "imports of",
  "dependency graph", or "blast radius". Skip for renames, simple text search,
  non-Python repositories, or rebuilding an index.
argument-hint: "<rdeps|deps|path|central|symbol|symbols|find-symbol|fn-rdeps|fn-deps|fn-blast|diff-impact> ..."
allowed-tools: Bash, Read, Write, Skill, AskUserQuestion
model: haiku
effort: low
---

<objective>
Answer structural Python questions with the unified `codemap-py query` CLI.
Use at most three Codemap calls and trust complete results.

NOT for: rebuilding the index (use `/codemap-py:scan-codebase`) or renaming
symbols (use `/codemap-py:rename-refs`).
</objective>

<workflow>

## Choose one query

Direction matters: "affected if X changes" means reverse dependencies.

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact rdeps "mypackage.auth"
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact fn-rdeps "mypackage.auth::validate_token"
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact symbol "MyClass.method" --with-imports
```

| Goal | Query subcommand |
| --- | --- |
| module importers / blast radius | `rdeps <module> [--exclude-tests]` |
| module imports | `deps <module>` |
| shortest import chain | `path <from> <to>` |
| central or highly coupled modules | `central --top N` · `coupled --top N` |
| symbol source or module symbols | `symbol <name> [--with-imports]` · `symbols <module>` |
| regex symbol search | `find-symbol <pattern>` |
| direct callers / callees | `fn-rdeps <module::symbol>` · `fn-deps <module::symbol>` |
| transitive caller closure | `fn-blast <module::symbol>` |
| changed-code blast radius | `diff-impact [--base REF]` |
| affected tests / mocks | `test-impact <target>` · `mock-rdeps <target>` |
| pytest fixtures | `fixture-rdeps <name>` · `fixture-graph <test-file>` |
| subprocess relationships | `subprocess-deps <module>` · `subprocess-rdeps <module>` |
| coverage / documentation gaps | `coverage <target>` · `coverage-gap [module]` · `undocumented [module]` |

Use `codemap-py query --help` only when needed. `--limit 0` is valid only for
`list`, `symbol`, and `find-symbol`; never attach it to `rdeps` or `fn-rdeps`,
whose default result sets are exhaustive.

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
- `query_complete: false`: name `completeness_reason`; search only gaps named
  by `degraded`, `not_covered`, `root_mismatch`, or `stale`.
- `compact: true` changes coverage metadata only; findings and counts remain
  complete.

Maximum: three Codemap calls including retries. A tool-routing failure does not
count when no CLI command ran. After three, report partial results and the
remaining caveat.

## Render

Use the JSON primary array: `imported_by` / `direct_imports`, `called_by` /
`calls`, `path`, `symbols`, `central` / `coupled`, `blast_radius`, or
`changed_modules` plus `test_impact`. Preserve qualified names exactly. Include
stale, degraded, root-mismatch, and `not_covered` caveats when present.

</workflow>
