<!-- file: codemap-gates.md — consumers: research/skills/run, verify -->

Read `IFS= read -r CODEMAP_CURRENCY < "${TMPDIR:-/tmp}/research-codemap-currency-${CSID}" 2>/dev/null || CODEMAP_CURRENCY="no_index"`.

**Gate A — missing index** (`CODEMAP_ENABLED=false` and `CODEMAP_RAW=auto`): invoke `AskUserQuestion`:
- Question: "No codemap index for this project — structural dependency context unavailable. How to proceed?"
- (a) Continue without codemap — proceed with file-read context only
- (b) Build index now — run `scan-index` in the foreground (wait until it finishes), then set `CODEMAP_ENABLED=true` and continue
- (c) Abort — stop; build index manually then re-invoke this skill

On (b): run `scan-index` in the foreground (wait until it finishes); set `CODEMAP_ENABLED=true`; continue. (Never model-invoke the `codemap:scan-codebase` skill — it is `disable-model-invocation:true`, user-slash-only; the model builds via the `scan-index` binary, exactly as codemap's own `inject-preamble.js` hook does.)
On (c): stop.

**Gate B — stale index** (`CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`): invoke `AskUserQuestion`:
- Question: "Codemap index is stale — source files changed since last scan; context may miss recent changes. How to proceed?"
- (a) Rebuild now — run `scan-index` in the foreground (wait until it finishes), then continue with fresh index (note: ambient hook may have already started background refresh; `scan-index` blocked by scan lockfile until it completes — up to 10 min)
- (b) Continue with stale data — proceed; results may miss recent changes
- (c) Skip codemap — set `CODEMAP_ENABLED=false`; proceed without structural context

On (a): run `scan-index` in the foreground (wait until it finishes); continue.
On (c): set `CODEMAP_ENABLED=false`.
