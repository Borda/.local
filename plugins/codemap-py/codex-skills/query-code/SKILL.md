---
name: query-code
description: |
  Query Codemap's Python structural index for dependencies, callers, paths,
  symbols, blast radius, test impact, mocks, fixtures, subprocesses, and
  coverage. Trigger for "what depends on", "who calls", "imports of",
  "dependency graph", or "blast radius". Skip for renames, simple text search,
  non-Python repositories, or rebuilding an index.
---

# Query Code

NOT for: rebuilding the index (use `$codemap-py:scan-codebase`) or renaming symbols (use `$codemap-py:rename-refs`).

Use the unified CLI. In benchmark and managed integrations, `CODEMAP_BIN` is the verified absolute launcher:

```bash
"$CODEMAP_BIN" query --compact rdeps "mypackage.auth"
"$CODEMAP_BIN" query --compact fn-rdeps "mypackage.auth::validate_token"
"$CODEMAP_BIN" query --compact symbol "MyClass.method" --with-imports
```

If `CODEMAP_BIN` is absent outside the benchmark, resolve this installed skill's plugin root once and use `<installed-root>/bin/codemap-py`. Do not guess a cache version or invoke `fn-rdeps`, `rdeps`, or another query command at the CLI root. Shell variables do not persist between tool calls.

## Managed context and query discipline

When a managed workflow supplies an existing `<run-directory>/codemap-context.json`, consume that persisted artifact first. If it already contains the evidence needed for the task, do not issue a second Codemap query. A managed benchmark/integration invocation is valid only after the packaged query skill has been used or an equivalent persisted query result has been supplied. When measuring the direct CLI path, issue at least one query.

For a packaged integration arm, select the latest reviewed `codemap-py` release at setup, record its exact version/hash and the installed `query-code` skill bytes, then keep that copy fixed for all measured cells. Do not float an update during a task or treat installation alone as evidence that the skill was used.

Every new managed query uses the compact public CLI form:

```bash
"$CODEMAP_BIN" query --compact <subcommand> <arguments>
```

In a benchmark Skill arm, the runner provides an immutable `CODEMAP_SKILL_FILE` bound to this exact installed Skill. Before the first query, activate/read it in its own tool call whose complete shell command is exactly:

```bash
cat "$CODEMAP_SKILL_FILE"
```

Do not replace that command with `sed`, a literal or locally bound path, an unquoted variable, or shell composition. Run the required compact query in a separate tool call whose complete shell command is exactly the public `$CODEMAP_BIN` form above. Additional repository reads, shell commands, conditionals, and diagnostics are allowed as separate tool calls; they do not replace the required Skill activation or successful Codemap query.

Use only the CLI's JSON output. Do not read index files, cache internals, raw logs, or runtime/session logs to recover structural evidence. When the returned `index.query_complete` is `true`, stop querying and answer from that result; do not re-query or verify it with grep, source reads, or another structural tool.

## Choose one query

Direction matters: "affected if X changes" means reverse dependencies.

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

Use `"$CODEMAP_BIN" query --help` only when the needed command is not listed. `--limit 0` is valid only for `list`, `symbol`, and `find-symbol`; never attach it to `rdeps` or `fn-rdeps`, whose default result sets are exhaustive.

## Index and completeness contract

Run the selected query first when no sufficient persisted context is available. Do not spend a call on an unconditional freshness probe.

- Normal mode may perform the CLI's bounded incremental self-heal.
- `SCAN_NO_AUTOBUILD=1` means use the existing index exactly as-is: do not run a freshness query, incremental refresh, or automatic full build.
- A missing frozen index is a hard stop; report the structured error and ask for `$codemap-py:scan-codebase`.
- An explicit user request to build may still use `codemap-py index`; `SCAN_NO_AUTOBUILD` blocks implicit writes, not deliberate indexing.

Read the returned `index` block:

- `query_complete: true`: answer immediately. Do not re-query or verify with grep/read.
- `query_complete: false`: name the `completeness_reason`; search only gaps identified by `degraded`, `not_covered`, `root_mismatch`, or `stale`.
- `compact: true` changes coverage metadata only. Primary findings and counts
  remain complete.

Maximum: three Codemap calls per task, including retries. A tool-routing error does not count if no CLI command ran. After three calls, report partial results and the remaining completeness caveat.

## Render

`codemap-py query` emits JSON. Use the command's primary array:

- `rdeps` / `deps`: `imported_by` / `direct_imports`
- `fn-rdeps` / `fn-deps`: `called_by` / `calls`
- `path`: `path`
- `symbol`: `symbols[].source`
- `central` / `coupled`: `central` / `coupled`
- `fn-blast`: `blast_radius`
- `diff-impact`: `changed_modules` and `test_impact`

Preserve qualified names exactly. Include stale, degraded, root-mismatch, and `not_covered` caveats when present.
