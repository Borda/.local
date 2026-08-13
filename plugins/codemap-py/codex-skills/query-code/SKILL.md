---
name: query-code
description: "Query Codemap."
---
NOT for: $codemap-py:scan-codebase, $codemap-py:rename-refs, $codemap-py:test-impact.

Test-impact split: one-off structural fact → `test-impact <target>` subcommand here; full workflow (index ensure, parse, pytest cmd, caveat) → $codemap-py:test-impact.

## Runtime note

No `bin/` PATH entry, no `$CLAUDE_PLUGIN_ROOT` equivalent. Resolve the installed plugin root once, substitute for `PLUGIN_ROOT` below, keep in reasoning — shell state dies between tool calls.

## Workflow

Exact-file+symbol local edit: skip Codemap only with no unresolved caller/dependency/blast-radius/test-impact/import/source slice. Lifecycle boundary (callback/hook, cancellation/exception, scheduling/cleanup, state transfer): inspect source+named test/oracle; use `fn-rdeps` for caller or `fn-deps` for callee responsibility. Explicit structural/tool requirement overrides.

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

Routing shortlist, not the parser's full surface — `PLUGIN_ROOT/bin/codemap-py query --help` lists every subcommand; read it, never guess a name.

Direct/every/all/production/blast-radius callers → `fn-rdeps <module::symbol> --exclude-tests`; `fn-blast <module::symbol>` only for explicit transitive, closure, hops, or all-levels requests.

Direct test-module imports: `rdeps <module>`; filter/report tests. `test-impact <target>` only selects transitive affected tests.

`symbol <name>` accepts bare `authenticate` or `MyClass.method`; imports use `symbol <name> --with-imports`; `module::symbol` belongs to `fn-*` call-graph queries. Chain `module`+`qualified_name` → `<module>::<qualified_name>` (`mypackage.module::MyClass.method`). For scaffolding, query the requested qualified extension method (`symbol MyClass.add_feature`), not nearby `symbol MyClass`/`symbols <module>` listing.

`find-symbol '<ClassSuffix>\.<method>$' --exclude-tests --limit 0` finds same-name override candidates; names are candidates, not inheritance proof—verify ancestry/package boundaries in source.

Run each compact query alone: `PLUGIN_ROOT/bin/codemap-py query --compact <subcommand> [arguments]`.

`fn-blast`: never `--depth`; never invent flags. `query_complete: true`: complete-query paths are caller-repo-relative, never Skill-relative; do not re-query/read/grep that graph fact. Otherwise name gaps. Ordinary repository reads remain allowed only for a distinct independent AST/oracle view. Missing index: request $codemap-py:scan-codebase.

Truncation at 20 items is a real cap, not an exhaustive list, unless `--limit 0` is passed (`symbol`/`find-symbol` default). `query_complete` scores graph coverage only, never the cap — `query_complete: true` on a capped list is still 20-of-N. `index.confidence`: `exact` = whole set, `partial` = capped/stale; `index.truncated`+`index.total_available` give the real total. Re-run with `--limit 0` before calling a capped list complete.
