---
description: Root-cause diagnosis protocol — confirm root cause before fixing; post-fix validation loop; challenger feedback; anti-patterns
paths:
  - '**'
---

## Root-Cause Discipline (stub)

**Never patch symptom.** Diagnosis loop: observe ALL symptoms → hypothesize specific mechanism → **confirm with evidence** (code/logs/tests — no confirmation = no fix) → fix mechanism, not signal → validate ALL original symptoms. Max 3 iterations, then stop + AskUserQuestion.

- Memory/training knowledge ≠ evidence — every premise grounded in source read now; "Where is this documented?" before building on it
- Falsification before closing: could a second independent root cause remain? If yes, diagnose it too
- Post-fix, non-trivial (>1 file, or logic previously believed working): dispatch `foundry:challenger` via `Agent()` — batched per session (one challenger for grouped fixes), file-handoff envelope, read full findings only on FAIL
- Anti-patterns (forbidden): symptom suppression (`try/except`/guard hiding failure), first-plausible-cause stop, partial validation, fix-before-confirm, ungrounded premise as design pillar

> Full protocol (diagnosis-loop detail, challenger dispatch rules, Tier-1/2 evidence standards) in `_full/debugging.md`. **Read before any multi-file or behaviour-changing fix**:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/debugging.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/foundry/rules/_full/debugging.md"  # timeout: 5000
> ```
