---
description: Root-cause diagnosis protocol — confirm root cause before fixing; post-fix validation loop; challenger feedback; anti-patterns
paths:
  - '**'
---

## Root-Cause Discipline

Never patch symptom. Symptoms = evidence — treat as signal, not problem.

### Diagnosis loop

1. **Observe symptoms** — collect all failure signals before forming hypothesis
2. **Hypothesize root cause** — name specific mechanism; not "config wrong" but "config key X missing from production loader → Y falls back to default Z → symptom"
3. **Confirm root cause** — find direct evidence in code, logs, or tests that hypothesized mechanism exists and is active; no confirmation = no fix
4. **Fix the mechanism, not the signal** — change structural cause; never add guard that suppresses symptom without removing cause
5. **Validate** — re-run all original failure signals; confirm every symptom resolved; if any remain → root cause was incomplete or not only one → return to step 2

**Loop bound**: max 3 diagnosis-fix iterations (matches §Safety breaks default); at limit — stop, report remaining symptoms, invoke `AskUserQuestion` before continuing.

### Falsification check

Before marking fix complete: "Could this symptom have a second independent root cause not addressed by this fix?" If yes → diagnose and fix that cause too before closing.

### Post-fix challenger invocation

**Dispatch rule**: post-fix re-invoke is a fresh orchestrator-initiated dispatch — not a nested call from within an active challenger run. Challenger's SKIP rule ("already inside an active challenger context") still applies if currently executing inside a challenger review; orchestrator waits for challenger to complete, then dispatches a new instance for post-fix verification.

After any non-trivial fix (multi-file change, behaviour change, fix to previously-masked bug):

1. Invoke `foundry:challenger` with diff and original symptom description
2. Challenger confirms: (a) root cause structurally consistent with diff, (b) all original symptoms resolved, (c) no new failure modes introduced
3. Residual or new symptoms found → root cause incomplete → return to diagnosis loop

**Non-trivial threshold**: fix touching >1 file, or any logic previously believed working. Single-line typo fixes in isolated files exempt.

### Anti-patterns

- **Symptom suppression**: `try/except`, default value, or conditional guard hiding failure signal without removing cause — forbidden
- **First-plausible-cause stop**: accepting first root cause that sounds reasonable without confirming with evidence
- **Partial validation**: checking only primary symptom after fix, not all reported symptoms
- **Fix-before-confirm**: writing fix before confirming root cause — risk of fixing wrong thing
- **Skipping challenger on "obvious" fixes** — obvious fixes have highest rate of incomplete root-cause identification; obviousness not an exemption
