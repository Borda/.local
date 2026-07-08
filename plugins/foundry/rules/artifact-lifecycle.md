---
description: Canonical artifact directory layout, run-dir naming convention, and TTL policy for all skill outputs
paths:
  - '**'
---

## Artifact Layout (stub)

Runtime artifacts at **project root** dot-dirs — never inside `.claude/`:

- `.temp/<skill>/<ts>/` — intermediate/handover files · `.reports/<skill>/<ts>/` — final consolidated reports · `.plans/{blueprint,active,closed}` — specs/todos/results · `.notes/` — lessons, diary · `.cache/gh/` — GitHub API cache · `.experiments/`, `.developments/` — research/develop runs
- Run-dir timestamp: `$(date -u +%Y-%m-%dT%H-%M-%SZ)` (UTC, dashes, filesystem-safe); completed run contains `result.jsonl`
- TTL: dot-prefixed artifact dirs gitignored, auto-cleaned at 30 days; `.plans/active|closed` and `.notes/` manual — never auto-delete

> Full rule (complete layout tree, per-dir TTL conditions, naming examples) in `_full/artifact-lifecycle.md`. **Read when defining a new skill's output dirs or TTL behavior**:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/artifact-lifecycle.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/foundry/rules/_full/artifact-lifecycle.md"  # timeout: 5000
> ```
