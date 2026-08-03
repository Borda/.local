---
name: query-code
description: Query Codemap for dependencies, callers, symbols, blast radius, and static quality gaps.
---

# Query Code

NOT for: index rebuilds (`$codemap-py:scan-codebase`) or renames (`$codemap-py:rename-refs`).

Use verified `CODEMAP_BIN`. Make one query first: compact and task-shaped. “Affected if X changes” means reverse dependencies.

| Need | Query |
| --- | --- |
| module importers / blast radius | `rdeps <module>` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| imports / callees | `deps <module>` / `fn-deps <module::symbol>` |
| source / symbols | `symbol <name>` / `symbols <module>` |
| transitive affected tests / mocks | `test-impact <target>` / `mock-rdeps <target>` |
| documentation / static test gaps | `undocumented [module]` / `uncovered [module]` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

Test modules that directly import a module: use `rdeps <module>`; filter/report test modules. Reserve `test-impact <target>` for transitive affected-test selection.

```bash
"$CODEMAP_BIN" query --compact <subcommand> [arguments]
```

Benchmark Skill arm: read this exact Skill in its own call:

```bash
cat "$CODEMAP_SKILL_FILE"
```

Run the compact query separately. Index/cache inspection cannot replace either call. Outside managed runs, use installed `bin/codemap-py` only when `CODEMAP_BIN` is absent; never guess a cache version.

`fn-blast` takes one qualified name, never `--depth`; `coupled` is not `central`. Correct one started name/argument error; never invent flags or retry a complete query. Stop after `index.query_complete: true`; otherwise report named completeness gaps. Ordinary repository reads remain allowed only for a task-requested distinct independent AST/oracle view; label it separately. Missing index: stop and request `$codemap-py:scan-codebase`. `SCAN_NO_AUTOBUILD=1` forbids implicit, not explicit, builds.

Preserve qualified names and state any completeness caveat. Use `"$CODEMAP_BIN" query --help` only when the needed command is not listed above.
