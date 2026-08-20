---
name: query-code
description: "Query Codemap."
---

NOT for: $codemap-py:scan-codebase, $codemap-py:rename-refs, $codemap-py:test-impact.

Test-impact split: one-off structural fact → `test-impact <target>` here; full workflow → $codemap-py:test-impact.

## Runtime note

Codex exposes no plugin-root variable. Resolve the installed root as `PLUGIN_ROOT` once; shell state does not persist.

## Workflow

Exact-file+symbol local edit: skip Codemap only with no unresolved caller/dependency/blast-radius/test-impact/import/source slice. A lifecycle boundary (callback/hook, cancellation/exception, scheduling/cleanup, state transfer) requires inspect source plus named test/oracle; use `fn-rdeps` for caller or `fn-deps` for callee responsibility. Explicit structural/tool requirement overrides. Choose the smallest complete query set.

| Need | Query |
| --- | --- |
| production module importers / blast radius | `rdeps <module> --exclude-tests` |
| production centrality / highest in-degree | `central --top N --exclude-tests` |
| internal-import coupling (not centrality) | `coupled --top N` |
| direct production callers | `fn-rdeps <module::symbol> --exclude-tests` |
| callers plus test-module importers | `fn-rdeps <module::symbol> --exclude-tests`, then `rdeps <module>` |
| transitive callers / function blast | `fn-blast <module::symbol>` |
| broken Sphinx cross-references | `xrefs --broken <module>` |

Routing shortlist, not the parser's full surface; read `PLUGIN_ROOT/bin/codemap-py query --help`, never guess. Direct/every/all/production/blast-radius callers → `fn-rdeps <module::symbol> --exclude-tests`; `fn-blast <module::symbol>` only for explicit transitive, closure, hops, or all-levels requests. Query first; no unconditional pre-scan/freshness probe. Use `test-impact` for test choice, not direct test-module imports. Direct test-module imports: `rdeps <module>`; filter/report tests. `test-impact <target>` selects transitive affected tests.

`symbol <name>` accepts `authenticate` or `MyClass.method`; imports use `symbol <name> --with-imports`. `module::symbol` belongs to `fn-*` call-graph queries. Chain returned `module`+`qualified_name` → `<module>::<qualified_name>` (`mypackage.module::MyClass.method`). For a requested qualified extension method, query `symbol MyClass.add_feature`, not nearby `symbol MyClass`/`symbols <module>` listing.

`find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` finds same-name override candidates; names are candidates, not inheritance proof—verify ancestry/package boundaries in source. Run each compact query alone: `PLUGIN_ROOT/bin/codemap-py query --compact <subcommand> [arguments]`.

`fn-blast`: never `--depth`; never invent flags. A complete, untruncated result settles its graph fact: do not re-query/read/grep it. Complete-query paths are caller-repo-relative, never Skill-relative. Ordinary repository reads remain allowed for a distinct independent AST/oracle view or source-body implementation/runtime detail. Otherwise name the gap and target only it. Missing index: request $codemap-py:scan-codebase.

Truncation at 20 items is a real cap unless `--limit 0` is passed (`symbol`/`find-symbol` default). `query_complete` scores graph coverage only: true may mean 20-of-N. `index.confidence` is `exact` for the whole set and `partial` when capped/stale; `index.truncated`+`index.total_available` give N. Re-run capped lists with `--limit 0` before applying the stop rule.
