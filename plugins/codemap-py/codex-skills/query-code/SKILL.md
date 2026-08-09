---
name: query-code
description: "Query Codemap."
---
NOT for: `$codemap-py:scan-codebase`, `$codemap-py:rename-refs`, `$codemap-py:test-impact`.

Use `CODEMAP_BIN`; choose the smallest complete query set.

| Need | Query |
| --- | --- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| callers plus test-module importers | `fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| broken Sphinx cross-references | `xrefs --broken <module>` |
| source including module imports / symbols | `symbol <name> --with-imports` / `symbols <module>` |
| imports, tests, quality | `deps`/`fn-deps`, `test-impact`/`mock-rdeps`, `undocumented`/`uncovered` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

Modules that directly import a module: `rdeps <module>`; filter/report test modules; reserve `test-impact <target>` for transitive affected-test selection.

`symbol <name>` accepts a bare function name (`authenticate`) or class method (`MyClass.method`); `module::symbol` belongs to `fn-*` call-graph queries. Feature scaffolding: query the requested qualified extension method `symbol MyClass.add_feature`, not a nearby `symbol MyClass` or `symbols <module>` listing. `query_complete` confirms coverage, not optional fields.

```bash
"$CODEMAP_BIN" query --compact <subcommand> [arguments]
```

Managed run:
```bash
cat "$CODEMAP_SKILL_FILE"
```
Run compact queries separately; do not use `batch`. Outside managed runs, use `bin/codemap-py` if `CODEMAP_BIN` is absent.

`fn-blast` takes one qualified name, never `--depth`; never invent flags or retry complete queries. Stop at `index.query_complete: true`; else name gaps. Ordinary repository reads remain allowed only for a distinct independent AST/oracle view. Missing index: request `$codemap-py:scan-codebase`; `SCAN_NO_AUTOBUILD=1` forbids implicit builds.

Preserve qualified names/caveats. Use `query --help` only when needed.
