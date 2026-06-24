<!-- file: codemap-gates.md — consumers: oss/skills/review, resolve -->

**Gate A — missing index** (`CODEMAP_ENABLED=false` and `CODEMAP_FORCE_OFF=false`): invoke `AskUserQuestion`:
- Question: "No codemap index for this project — structural dependency context unavailable. How to proceed?"
- (a) Continue without codemap — proceed with file-read context only
- (b) Build index now — `Skill(skill="codemap:scan-codebase")` then set `CODEMAP_ENABLED=true` and continue
- (c) Abort — stop; build index manually then re-invoke this skill

On (b): invoke `Skill(skill="codemap:scan-codebase")`; set `CODEMAP_ENABLED=true`; continue.
On (c): stop.

**Gate B — stale index** (`CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`): invoke `AskUserQuestion`:
- Question: "Codemap index is stale — source files changed since last scan; context may miss recent changes. How to proceed?"
- (a) Rebuild now — `Skill(skill="codemap:scan-codebase")` then continue with fresh index (note: the ambient hook may have already started a background refresh; `scan-codebase` will be blocked by the scan lockfile until it completes — up to 10 min)
- (b) Continue with stale data — proceed; results may miss recent changes
- (c) Skip codemap — set `CODEMAP_ENABLED=false`; proceed without structural context

On (a): invoke `Skill(skill="codemap:scan-codebase")`; continue.
On (c): set `CODEMAP_ENABLED=false`.
