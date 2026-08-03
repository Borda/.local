---
name: query-code
description: Query Codemap's Python structural index for dependencies, callers, symbols, blast radius, and static quality gaps.
---

# Query Code

NOT for: rebuilding the index (use `$codemap-py:scan-codebase`) or renaming symbols (use `$codemap-py:rename-refs`).

Use verified `CODEMAP_BIN`. Make one query first: task-shaped and compact; do not spend calls on help, probes, or repeats. Direction: “affected if X changes” means reverse dependencies.

| Need | Query |
| --- | --- |
| module importers / blast radius | `rdeps <module>` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| imports / callees | `deps <module>` / `fn-deps <module::symbol>` |
| source / symbols | `symbol <name>` / `symbols <module>` |
| test impact / mocks | `test-impact <target>` / `mock-rdeps <target>` |
| documentation / static test gaps | `undocumented [module]` / `uncovered [module]` |

```bash
"$CODEMAP_BIN" query --compact <subcommand> [arguments]
```

Benchmark Skill arm: activate this exact Skill in its own tool call:

```bash
cat "$CODEMAP_SKILL_FILE"
```

Run the compact query separately, exactly as above. Do not replace either required call with index/cache inspection. Outside managed runs, use installed `bin/codemap-py` only if `CODEMAP_BIN` is absent; never guess a cache version.

Use documented syntax: `fn-blast` takes one qualified name, never `--depth`; `coupled` is not `central`. On a started name or argument error, correct it once; never invent flags or retry a completed query. Use CLI JSON. Stop after `index.query_complete: true`; otherwise report `completeness_reason` and inspect only named gaps (`degraded`, `not_covered`, `root_mismatch`, or `stale`). Ordinary repository reads remain allowed only for a task-requested distinct independent AST/oracle view; label it separately, never as rechecking complete Codemap evidence. A missing frozen index is a hard stop: report it and ask for `$codemap-py:scan-codebase`. `SCAN_NO_AUTOBUILD=1` forbids implicit refresh/build, not an explicit requested build.

Preserve qualified names and state any completeness caveat. Use `"$CODEMAP_BIN" query --help` only when the needed command is not listed above.
