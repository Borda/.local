<!-- file: demo-notes.md — consumer: integration/modes/demo.md (referenced by basename). Methodology detail relocated out of the agent-read demo flow to keep demo.md lean. -->

# Demo mode — methodology notes

Reference detail for `modes/demo.md`. Not required to execute demo happy path — read when step needs deeper rationale (scoring formulas, diagnostic root causes, honest caveats, scenario matrix).

## D5a — SQ_DELTA=0 root causes (diagnostic detail)

When real-skill probe records `SQ_DELTA = 0`, injection block present but scan-query never fired. Root causes to check:

- Binary not on PATH inside the skill's bash context
- Index guard `[ -f ".cache/codemap/${PROJ}.json" ]` failing (wrong `PROJ` name or `CODEMAP_INDEX_DIR` set)
- Skill's injection block inside a branch never taken for this target

Flag as ⚠ in D8 report. Print diagnostic: "Injection block present but SQ_DELTA=0. Check: `command -v scan-query` inside skill context; verify index path matches `resolve_index_env.py` output."

## D5b — Synthetic A/B methodology

### Honest caveat (printed verbatim in D8)

> "Agent tool returns only final text — no per-arm token usage. Arms gated by prompt only (not hard tool deny-list). Self-reported tool-call counts (B/G/R/SQ) used as cost proxy. Recall scored against ground truth for psf/requests pinned task set only; other repos use tool-count proxy + cross-arm agreement."

### Arm prompts

**Plain arm** — no codemap:
```
Repo at <TARGET>. CONSTRAINT: do NOT use scan-query, scan_query, or any codemap tool. Use only Bash(grep ...), Read, Glob.
Question: <task.question>
Return ONLY compact JSON: {"answer": "<answer>", "b": <Bash_calls>, "g": <Glob_calls>, "r": <Read_calls>, "sq": 0}
```

**Codemap arm** — scan-query encouraged:
```
Repo at <TARGET>. scan-query available at <SQ> — use it, it is faster than grep.
Question: <task.question>
Return ONLY compact JSON: {"answer": "<answer>", "b": <Bash_calls>, "g": <Glob_calls>, "r": <Read_calls>, "sq": <scan_query_calls>}
```

### Scoring

Score recall vs `task.ground_truth` where available:

```
recall = hits_in_answer / len(ground_truth)
```

`hits_in_answer` = count of `ground_truth` items appearing verbatim in the answer string.

No ground truth (own repo or non-requests clone): `cross_arm_agreement` = 1.0 if both arms give same answer, else 0.0. Label clearly.

### Benchmark upgrade offer (only if file present)

```bash
ls benchmarks/run-codemap-bench.py 2>/dev/null  # timeout: 5000
```

If present: `AskUserQuestion` — "Rigorous token-measured benchmark available." Options: (a) Skip (Recommended), (b) Run benchmark (slower). On (b): print command, delegate to user.

## D7 — Sk=0 explanation (printed when skills.jsonl empty)

> "skills.jsonl empty. Expected when tasks run via scan-query binary directly — PreToolUse hook fires only on explicit `/codemap-py:*` Skill() calls. D4 seeded one entry; missing → check hook registration: `claude hooks list`."

## D8 — report template

Write with Write tool. Fill `<...>` placeholders from D2–D7 values; omit Real-skill probe section when `DEMO_MODE=synthetic`.

```markdown
---
Title:      Codemap Integration Demo — <date>
Date:       <YYYY-MM-DD>
Scope:      <TARGET> — <own-repo | psf/requests | other-clone>
Focus:      end-to-end validation (plumbing + real-skill probe + synthetic A/B + telemetry)
Agents:     integration/demo
Outcome:    PASS | PASS_WITH_WARNINGS
Demo mode:  real (user skills wired) | synthetic (no integration / cloned repo)
Confidence: 0.N — <key gaps>
Next steps: /codemap-py:debrief-coding --since today
Path:       → .reports/codemap/demo-<YYYY-MM-DD>.md
---

# Codemap Integration Demo — <date>

**Target**: <TARGET>  **Mode**: <demo_mode>

## Plumbing

<plumbing table from D2>

## Index

Modules: <module_count>  Degraded: <degraded_count>  Built in demo: <yes/no>

## Sample tasks

| task_id | cmd | timing_ms | result_count | exhaustive |
| --- | --- | --- | --- | --- |
| ...     | ... | ...       | ...          | ...        |

## Real-skill probe

*(Omit section if DEMO_MODE=synthetic.)*

Skill: `<skill_name>`  Target: `<probe_file>`

scan-query calls fired: **<SQ_DELTA>**  Status: ✓ live | ⚠ SQ_DELTA=0

<⚠ diagnostic text if SQ_DELTA=0>

Subcommands in delta: <breakdown from new cli.jsonl lines>

## Synthetic A/B

*<label: "synthetic reference arm" | "synthetic only — no integration wired">*

| task_id | plain_recall | codemap_recall | plain_tools (B+G+R) | codemap_tools (B+G+R) | codemap_sq |
| --- | --- | --- | --- | --- | --- |
| ...     | ...          | ...            | ...                 | ...                   | ...        |
| **avg** | ...          | ...            | ...                 | ...                   | ...        |

> **Caveat**: prompt-gated arms, tool-count cost proxy. <ground-truth note or cross-arm agreement note>

## Telemetry health

<telemetry table from D7>

<Sk=0 explanation if applicable>

## Debrief report

→ <debrief report path from D6>
```

## Scenarios (expected-outcome matrix)

1. **Fresh repo, no index** → D3 builds; index stats in report.
2. **Stale index** → D2 flags stale `age_hours`; D3 refreshes.
3. **Not wired → init offered (D2a)** → user accepts → init runs → injection present → DEMO_MODE=real → D5a real-skill probe runs.
4. **Not wired → synthetic only (D2a)** → DEMO_MODE=synthetic → D5a skipped → D5b synthetic A/B labelled accordingly.
5. **Wired but SQ_DELTA=0** → D5a flags injection-present-but-not-firing with diagnostic; PASS_WITH_WARNINGS.
6. **Skills never invoked (Sk=0)** → D7 flags; explained as expected artifact.
7. **Public-repo demo** → D1a gate → CLONED=true → DEMO_MODE=synthetic (no user skills in clone) → full synthetic A/B with recall scoring → D9 cleanup.
8. **Anonymized report** → `--anonymize` forwarded to debrief-coding; output safe to share.
