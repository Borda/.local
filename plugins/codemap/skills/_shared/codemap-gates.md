<!-- file: codemap-gates.md — consumers: develop/oss wrappers (plugins/{develop,oss}/skills/_shared/codemap-gates.md) reference this contract by installed-plugin cache path -->

# Codemap gates contract — v2

Plugin-agnostic Gate A / Gate B machinery for missing-index and stale-index decisions. Consumer wrappers reference this file, supply only their **skip flag** (per-plugin flag disabling gates, e.g. `CODEMAP_RAW=auto` for develop, `CODEMAP_FORCE_OFF=false` for oss).

Read currency first: `CODEMAP_CURRENCY=$(cat "${TMPDIR:-/tmp}/dev-codemap-currency" 2>/dev/null || echo "no_index")` (consumers may point at own currency file).

## Gate A — missing index

Fires when `CODEMAP_ENABLED=false` and the consumer's skip flag is **not** set to off. Invoke `AskUserQuestion`:
- Question: "No codemap index for this project — structural dependency context unavailable. How to proceed?"
- (a) Continue without codemap — proceed with file-read context only
- (b) Build index now — `Skill(skill="codemap:scan-codebase")` then set `CODEMAP_ENABLED=true` and continue
- (c) Abort — stop; build index manually then re-invoke this skill

On (b): invoke `Skill(skill="codemap:scan-codebase")`; set `CODEMAP_ENABLED=true`; continue.
On (c): stop.

## Gate B — stale index

Fires when `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`. Invoke `AskUserQuestion`:
- Question: "Codemap index is stale — source files changed since last scan; context may miss recent changes. How to proceed?"
- (a) Rebuild now — `Skill(skill="codemap:scan-codebase")` then continue with fresh index (note: the ambient hook may have already started a background refresh; `scan-codebase` will be blocked by the scan lockfile until it completes — up to 10 min)
- (b) Continue with stale data — proceed; results may miss recent changes
- (c) Skip codemap — set `CODEMAP_ENABLED=false`; proceed without structural context

On (a): invoke `Skill(skill="codemap:scan-codebase")`; continue.
On (c): set `CODEMAP_ENABLED=false`.
