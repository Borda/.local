---
name: query-code
description: Query Codemap.
---

NOT for: $codemap-py:scan-codebase, $codemap-py:rename-refs, $codemap-py:test-impact.

Test-impact split: one-off structural fact → `test-impact <target>` here; full workflow → $codemap-py:test-impact.

## Runtime note

No Codex plugin-root variable. Resolve installed root as `PLUGIN_ROOT`; no shell persistence.

## Workflow

Exact file+symbol local edit: skip Codemap only with no unresolved caller/dependency/blast-radius/test-impact/import/source slice. Lifecycle boundary (callback/hook, cancellation/exception, scheduling/cleanup, state transfer): inspect source plus named test/oracle; `fn-rdeps` for caller, `fn-deps` for callee. Explicit structural/tool requirement overrides. Choose the smallest complete query set.

| Need | Query |
| -- | -- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| callers plus test-module importers | `fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| broken Sphinx cross-references | `xrefs --broken <module>` |

Routing shortlist, not the parser's full surface; read `PLUGIN_ROOT/bin/codemap-py query --help`, never guess. Direct/every/all/production/blast-radius callers → `fn-rdeps <module::symbol> --exclude-tests`; `fn-blast <module::symbol>` only for explicit transitive, closure, hops, or all-levels requests. Query first; no automatic scan/freshness probe. `test-impact <target>` selects transitive affected tests, not direct test-module imports; for those, `rdeps <module>` then filter/report tests.

`symbol <name>` accepts `authenticate` or `MyClass.method`; imports use `symbol <name> --with-imports`; `module::symbol` belongs to `fn-*` call-graph queries. Chain `module`+`qualified_name` → `<module>::<qualified_name>` (`mypackage.module::MyClass.method`). For a requested qualified extension method, query `symbol MyClass.add_feature`, not nearby `symbol MyClass`/`symbols <module>` listing.

`find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` finds same-name override candidates, not inheritance proof—verify ancestry/package boundaries in source. Run each compact query alone: `PLUGIN_ROOT/bin/codemap-py query --compact <subcommand> [arguments]`. Custom-root index: `--index <emitted-index-path> --root <same-root>`; `--root` is path resolution only.

`fn-blast`: never `--depth`; never invent flags. Complete untruncated results settle their graph fact: do not re-query/read/grep. Complete-query paths are caller-repo-relative, never Skill-relative. Ordinary repository reads remain allowed for a distinct independent AST/oracle view or source-body implementation/runtime detail. Else name/target only the gap. Missing index: request $codemap-py:scan-codebase.

Truncation at 20 items is a real cap unless `--limit 0` (`symbol`/`find-symbol` default). `rdeps --limit N` previews static `imported_by`; `dynamic_imported_by` and `config_refs` stay exhaustive. Default `rdeps` or `rdeps --limit 0` returns every static importer. `query_complete` is graph coverage only: true may mean 20-of-N. `index.confidence` is `exact` for the whole set, `partial` when capped/stale; `index.truncated`+`index.total_available` give N. Re-run capped lists with `--limit 0`; truncated `rdeps` never settles exhaustive callers.
