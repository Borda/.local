<!-- file: codemap-gates.md — consumers: develop/oss wrappers (plugins/{develop,oss}/skills/_shared/codemap-gates.md) reference this contract by installed-plugin cache path -->

# Codemap gates contract — v2

Plugin-agnostic Gate A / Gate B machinery for missing-index and stale-index decisions. Consumer wrappers reference this file, supply only their **skip flag** (per-plugin flag disabling gates, e.g. `CODEMAP_RAW=auto` for develop, `CODEMAP_FORCE_OFF=false` for oss).

Read currency first: `IFS= read -r CODEMAP_CURRENCY < "${TMPDIR:-/tmp}/dev-codemap-currency-${CSID}" 2>/dev/null || CODEMAP_CURRENCY="no_index"` (consumers may point at own currency file; `CSID` exported by caller per `claude-config.md` TMPDIR Sentinel Scoping).

## Gate A — missing index

Fires when `CODEMAP_ENABLED=false` and the consumer's skip flag is **not** set to off. Invoke `AskUserQuestion`:
- Question: "No codemap index for this project — structural dependency context unavailable. How to proceed?"
- (a) Continue without codemap — proceed with file-read context only
- (b) Build index now — run `scan-index` in the foreground (wait until it finishes), then set `CODEMAP_ENABLED=true` and continue
- (c) Abort — stop; build index manually then re-invoke this skill

On (b): run `scan-index` in the foreground (wait until it finishes); set `CODEMAP_ENABLED=true`; continue. (Never model-invoke the `codemap-py:scan-codebase` skill — it is `disable-model-invocation:true`, user-slash-only; the model builds via the `scan-index` binary, exactly as codemap-py's own `inject-preamble.py` hook does.)
On (c): stop.

## Gate B — stale index

Fires when `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`. Invoke `AskUserQuestion`:
- Question: "Codemap index is stale — source files changed since last scan; context may miss recent changes. How to proceed?"
- (a) Rebuild now — run `scan-index` in the foreground (wait until it finishes), then continue with fresh index (note: the ambient hook may have already started a background refresh; `scan-index` will be blocked by the scan lockfile until it completes — up to 10 min)
- (b) Continue with stale data — proceed; results may miss recent changes
- (c) Skip codemap — set `CODEMAP_ENABLED=false`; proceed without structural context

On (a): run `scan-index` in the foreground (wait until it finishes); continue.
On (c): set `CODEMAP_ENABLED=false`.
