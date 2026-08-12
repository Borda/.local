---
name: query-code
description: "Query Codemap."
---
NOT for: `$codemap-py:scan-codebase`, `$codemap-py:rename-refs`, `$codemap-py:test-impact`.

Exact file and symbol; localized edit; no unresolved caller/dependency/blast radius/test impact/import/source slice: skip Codemap. Explicit structural query/tool requirement overrides.

Choose the smallest complete query set.

| Need | Query |
| --- | --- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| callers plus test-module importers | `fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| broken Sphinx cross-references | `xrefs --broken <module>` |

For caller requests, use `fn-rdeps <module::symbol> --exclude-tests` for direct, every, all, production, and blast-radius wording; use `fn-blast <module::symbol>` only when the user explicitly asks for transitive callers, closure, hops, or all levels.

`rdeps <module>` finds modules that directly import a module; filter/report test modules. Reserve `test-impact <target>` for transitive affected-test selection.

`symbol <name>` accepts a bare function name (`authenticate`) or method (`MyClass.method`); imports use `symbol <name> --with-imports`. `module::symbol` belongs to `fn-*` call-graph queries. Chain `module` + `qualified_name` as `<module>::<qualified_name>` (for example, `mypackage.module::MyClass.method`). For scaffolding, query the requested qualified extension method (`symbol MyClass.add_feature`), not a nearby `symbol MyClass` or `symbols <module>` listing.

`find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` finds same-name implementation/override candidates. Name matching is candidate discovery only, not proof of inheritance; verify ancestry and package boundaries in source.

Run each compact query alone: `"$CODEMAP_BIN" query --compact <subcommand> [arguments]`.

`fn-blast`: never `--depth`; never invent flags. If `index.query_complete: true`, complete-query paths are caller-repo-relative, never Skill-relative; do not re-query/read/grep. Otherwise name gaps. Ordinary repository reads remain allowed for a distinct independent AST/oracle view. Missing index: request `$codemap-py:scan-codebase`.
