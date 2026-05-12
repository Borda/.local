| Severity | Examples |
| --- | --- |
| **critical** | Broken cross-reference (agent/skill not exist on disk), MEMORY.md inventory wrong, relative path silently fall back to wrong dir |
| **high** | Dead loop in follow-up chain, missing settings.json permission for tool in use, broken code example (undefined variable, wrong command syntax), agent/skill instruction directly contradicts `.claude/CLAUDE.md` directive, deprecated/invalid hook event name or type in use, `context:fork + disable-model-invocation:true` on same skill (skill cannot run), tool declared in `tools:`/`allowed-tools:` needed but absent causing silent failures, `deep-reasoning` or `plan-gated` agent declared on `sonnet` (underpowered for tier) |
| **medium** | Duplication across files, stale model name, README row missing for existing skill, hardcoded `/Users/<name>/` path, undocumented modes in inputs, deprecated frontmatter field or settings key, permissions-guide.md missing row for allow entry or has orphaned row, declared tool not referenced anywhere in workflow (unnecessary permission surface), `focused-execution` agent declared on `opus`/`opusplan` (overkill for tier) |
| **low** | Verbosity, minor formatting, incomplete follow-up chain, outdated version pin with "autoupdate" note, agent/skill omits CLAUDE.md principle but no contradiction, 💡 new CC feature not yet used, inline example restates prose or superseded by `AGENTS.md`/`CONTRIBUTING.md` |

## Antipatterns (severity under-classification — common calibration failures)

- `context:fork + disable-model-invocation:true` → always **critical**, not "possibly contradictory" (low)
- MEMORY.md inventory drift → always **critical**, not "out of sync" (medium) — stale roster fails at runtime
- `deep-reasoning` agent on `sonnet` → **high**, not "possibly underpowered" (medium) — tier table is authority
- Direct CLAUDE.md contradiction → **high**, not "best practice concern" (medium) — governance hierarchy applies
