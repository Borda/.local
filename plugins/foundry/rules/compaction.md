---
description: Compaction contract — verbatim skill state survival across auto-compact via .claude/state/skill-contract.md
paths:
  - '**'
---

## Compaction Contract

### Verbatim-file principle

Must-keep details (run-dir, task IDs, key decisions, report paths) go in `.claude/state/skill-contract.md` — not relied on in the prose summary. The PreCompact hook (`task-log.js`) appends the contract file **verbatim** to `session-context.md`; post-compaction re-read restores it losslessly.

Prose Compact Instructions remain best-effort. Don't over-promise zero loss for anything not in the contract.

### When and where to refresh

Refresh at the boundary **after** an expanding phase (parallel fan-out, iteration loop, large gather), **before** the next phase starts. Not after every step.

Block format and placement rule: see `compaction-contract.md`.

The hook rides auto-compact (85% context threshold) — no manual trigger. Compaction timing is best-effort; only the verbatim survival of *whatever contract exists* is deterministic.

### `keep:` semantics

Skills accepting `[--keep "<items>"]` append the user's string verbatim to the contract's `preserve:` line at Step 0. Free-form text; the skill documents it in `argument-hint`. Optional per-invocation user preserve list — see skill-specific `<compaction>` block for details.

### Clear on completion

Delete `.claude/state/skill-contract.md` at skill completion. The hook appends whatever the file holds — a skill that forgets to clear leaks stale preserve items into a later unrelated compaction. Clearing is mandatory, not optional.

### Stale-contract caution

If a skill crashes before clearing, `.claude/state/skill-contract.md` persists. Mitigation: at Step 0, delete any pre-existing contract file before writing the first boundary contract.
