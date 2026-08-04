---
name: query-code
description: Query Codemap structural index.
---
NOT for: index rebuilds (`$codemap-py:scan-codebase`) or renames (`$codemap-py:rename-refs`).

Use verified `CODEMAP_BIN`; make one query first; keep it compact and task-shaped.

| Need | Query |
| --- | --- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| source / symbols | `symbol <name>` / `symbols <module>` |
| imports, tests, quality | `deps`/`fn-deps`, `test-impact`/`mock-rdeps`, `undocumented`/`uncovered` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

Modules that directly import a module: use `rdeps <module>`; filter/report test modules; reserve `test-impact <target>` for transitive affected-test selection.

`symbol <name>` accepts a bare function name (`authenticate`) or qualified class method (`MyClass.method`); `module::symbol` belongs to `fn-*` call-graph queries. Feature scaffolding: query the requested qualified extension method, e.g. `symbol MyClass.add_feature`, not a nearby `symbol MyClass` or `symbols <module>` listing unless requested.

```bash
"$CODEMAP_BIN" query --compact <subcommand> [arguments]
```

Benchmark Skill arm: read this exact Skill in its own call:
```bash
cat "$CODEMAP_SKILL_FILE"
```
Run the compact query separately; index/cache inspection cannot replace either call. Outside managed runs, use `bin/codemap-py` only when `CODEMAP_BIN` is absent; never guess a cache version.

`fn-blast` takes one qualified name, never `--depth`; `coupled` is not `central`. Correct one name/argument error; never invent flags or retry complete queries. Stop after `index.query_complete: true`; otherwise report named completeness gaps. Ordinary repository reads remain allowed only for a task-requested distinct independent AST/oracle view. Missing index: request `$codemap-py:scan-codebase`; `SCAN_NO_AUTOBUILD=1` forbids implicit builds.

Preserve qualified names; state completeness caveats. Use `"$CODEMAP_BIN" query --help` only when needed.
