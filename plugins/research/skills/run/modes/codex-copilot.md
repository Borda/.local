<!-- Codex co-pilot mode include: loaded by research:run when --codex flag is set -->

<!-- Implements Phase 2c of the R5 iteration loop -->

## Phase 2c — Codex co-pilot (`--codex` only)

> **Cost-bounded gate.** Run when `--codex` confirmed at R2 AND both gates pass:
>
> 1. **Cost ceiling** — `CODEX_ITER < MAX_CODEX_RUNS` (default `MAX_CODEX_RUNS=10`; even with `MAX_ITERATIONS=20` Codex runs at most 10 times).
> 2. **Diminishing returns** — last 2 Codex passes did NOT both produce no code changes. After 2 consecutive no-op Codex passes, skip Codex for remaining iterations and append note to `diary.md`: `"Codex skipped from iter N — 2 consecutive no-ops"`.
>
> Init before R5 loop: `CODEX_ITER=0`, `CODEX_NOOP_STREAK=0`, `CODEX_DISABLED=false`.
> After each Phase 2c: increment `CODEX_ITER`; no-op → `((CODEX_NOOP_STREAK++))`, changes → `CODEX_NOOP_STREAK=0`. If `CODEX_NOOP_STREAK >= 2` set `CODEX_DISABLED=true`.

Gate fail (`CODEX_DISABLED=true` or `CODEX_ITER >= MAX_CODEX_RUNS`): skip Phase 2c, continue to Phase 3.

Else print narration, update R5b before Agent call:

```text
[→ Iter N/max · Phase 2c: Codex co-pilot — running (CODEX_ITER/MAX_CODEX_RUNS)]
```

TaskUpdate R5b subject: `R5b: Codex co-pilot — iter N/max_iterations running`, status: `in_progress`

Codex runs second pass when active, building on Claude's kept change or fresh attempt after revert/no-op. Codex commit evaluated by Phase 7 against `best_metric` (same rule as any iteration); "delta ≥ 0.1%" = delta against `best_metric`, not previous Claude iteration. Codex wins only if delta ≥ 0.1% AND guard passes.

- Claude Phase 2 **kept**: Codex second pass on current state — builds on Claude's work.
- Claude Phase 2 **reverted/no-op**: working tree restored; Codex fresh attempt on clean tree.

Run Codex ideation:

```text
Agent(
  subagent_type="codex:codex-rescue",
  prompt="Goal: <goal>. Run clarification: <clarification_prompt>  ← omit this clause entirely if clarification_prompt is null. Current metric: <metric_key>=<current_value> (baseline: <baseline>, direction: <higher|lower>). Scope files: <scope_files>. Read context from .experiments/state/<run-id>/context-<i>.md. Starting state: Claude's change was [kept|reverted|no-op]. [If kept: try to improve further from the current state. If reverted/no-op: propose a fresh approach.] Propose and implement ONE atomic optimization change most likely to improve the metric without breaking <guard_cmd>. Write your full reasoning to .experiments/state/<run-id>/codex-ideation-<i>.md."
)
```

- Claude **kept** + Codex proposes: proceed Phases 3–7 (commit, verify, guard, decide). Codex wins only if delta ≥ 0.1% AND guard passes.
- Claude **kept** + Codex no-op: append `codex-no-op` record, continue — Claude's result stands.
- Claude **reverted/no-op** + Codex proposes: proceed Phases 3–7.
- Claude **reverted/no-op** + Codex no changes: append `status: codex-no-op` (`ideation_source: "codex"`), continue.
- Set `"ideation_source": "codex"` in Phase 8 JSONL record for any Codex-proposed change.

After Codex completes (any outcome):

TaskUpdate R5b subject: `R5b: Codex co-pilot — iter N done (<outcome>)`

**Stuck escalation with `--codex`**: Phase 9 detects `STUCK_THRESHOLD` discards and `--codex` active → increase Codex effort — add to prompt: "Previous N attempts all reverted. Focus on fundamentally different approach (different file, different algorithm, different abstraction)."
