---
name: query-code
description: Query Codemap's Python structural index for dependencies, callers, symbols, blast radius, and static quality gaps.
---

# Query Code

NOT for: rebuilding the index (use `$codemap-py:scan-codebase`) or renaming symbols (use `$codemap-py:rename-refs`).

Use the verified `CODEMAP_BIN` launcher. Make one query first: a task-shaped compact query. Do not spend calls on help, probes, or repeated structural queries. Direction: “affected if X changes” means reverse dependencies.

| Need | Query |
| --- | --- |
| module importers / blast radius | `rdeps <module>` |
| direct callers | `fn-rdeps <module::symbol>` |
| imports / callees | `deps <module>` / `fn-deps <module::symbol>` |
| source / symbols | `symbol <name>` / `symbols <module>` |
| test impact / mocks | `test-impact <target>` / `mock-rdeps <target>` |
| documentation / static test gaps | `undocumented [module]` / `uncovered [module]` |
| coupling ranking | `coupled --top N` (ranked by internal import count) |

```bash
"$CODEMAP_BIN" query --compact <subcommand> [arguments]
```

In the benchmark Skill arm, first activate this exact Skill in its own tool call:

```bash
cat "$CODEMAP_SKILL_FILE"
```

Then run the compact query in a separate tool call; its complete command is exactly the public form above. Do not substitute the activation with another read command or the query with index/cache inspection. Outside managed runs, use the installed plugin's `bin/codemap-py` only if `CODEMAP_BIN` is absent; do not guess a cache version.

Use CLI JSON for Codemap evidence. If `index.query_complete` is true, stop additional Codemap queries and redundant structural verification. Ordinary repository reads remain allowed when the task explicitly asks for a distinct independent AST/oracle view absent from the query output; compute and label that view separately rather than treating Codemap static findings as ground truth. If false, report `completeness_reason` and only investigate named gaps (`degraded`, `not_covered`, `root_mismatch`, or `stale`). A missing frozen index is a hard stop: report it and ask for `$codemap-py:scan-codebase`. `SCAN_NO_AUTOBUILD=1` forbids implicit index refresh/build, not an explicit user-requested index build.

Preserve qualified names and state any completeness caveat. Use `"$CODEMAP_BIN" query --help` only when the needed command is not listed above.
