<!-- file: codemap-context.md — consumers: inject_codemap.py injection block; enriched by later contract work -->

# Codemap context contract — v1

The injected block (see `bin/_injection_block.py`) runs a few short queries inline and
points here for the full query map. Keep this file's contract version in sync with
`BLOCK_VERSION` in `_injection_block.py`.

## Core query map

- `central --top 3` — global blast-radius baseline; always safe, runs with no target.
- `fn-rdeps <module>::<function>` — direct callers of a function; run when a target symbol is known.
- `rdeps <module>` — reverse module dependencies; run when only a module (no function) is known.

Derive `TARGET_MODULE` from the task input: strip leading `./` and `src/`, strip trailing
`.py`, replace `/` with `.`. Derive `TARGET_FN` from the symbol under change when known.

## Evidence-line rule

Every run of the block emits one `codemap_evidence:` line summarising retrieval reliability:

```
codemap_evidence: queries_run=<n> hits=<h> completeness=<exhaustive|partial|stale|unknown>
```

Consumers may skip re-querying (grep/read) only when `completeness=exhaustive`. When the index
is absent or `scan-query` is unreachable, the block emits nothing and callers fall back to
their normal exploration path.
