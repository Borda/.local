<!-- Loaded by foundry:solution-architect (opusplan + high) -->
# Architectural Feasibility (foundry:solution-architect specialized guidance)

Read this file only when invoked by `/research:run --architect` (requires `research` plugin) to filter AI-generated experiment hypotheses. Skip for standalone ADR / API-design / migration-plan tasks.

## Hypothesis Architectural Feasibility

### Input

- **`RUN_DIR=<path>` — REQUIRED spawn-prompt input**. Caller MUST include `RUN_DIR=<path>` (absolute or repo-relative) in the spawn prompt; this anchors `hypotheses.jsonl` for crash recovery and re-invocation. **Guard**: at the start of the workflow, if `$RUN_DIR` is not found in the input prompt, exit immediately with error `"RUN_DIR not provided in spawn prompt — caller must include RUN_DIR=<path>"`. Do not proceed without it.
- JSONL list of hypotheses from `research:scientist` (requires `research` plugin), each with:
  `{hypothesis, rationale, confidence, expected_delta, priority}`
- Project codebase (read root + `src/` + existing `.experiments/<run>/` if present)

### Assessment per hypothesis

For each hypothesis:

1. **Codebase mapping** — can hypothesis be implemented given current code structure? Name specific files, classes, functions that would change
2. **Feasibility verdict** — `true` if codebase supports change with reasonable effort; `false` if requires structural changes outside experiment scope (new dependencies, architectural refactors, missing data pipelines)
3. **Blocker** — if `feasible: false`, name specific blocker (e.g., "requires adding new DataLoader class not present in codebase")

### Output

Preserve **every input field verbatim** (`hypothesis`, `rationale`, `confidence`, `expected_delta`, `priority`, plus any additional fields present in the input JSONL); downstream consumers (`research:judge`, `research:run`) read these fields and break when fields are silently dropped. Then append architectural annotation:

```jsonc
// Per-hypothesis line (success path) — all input fields preserved, annotation appended:
{
  "hypothesis": "<from input — verbatim>",
  "rationale": "<from input — verbatim>",
  "confidence": <from input — verbatim>,
  "expected_delta": "<from input — verbatim>",
  "priority": <from input — verbatim>,
  // ... any other input fields preserved verbatim ...
  "feasible": true | false,
  "codebase_mapping": "<files/classes/functions that would change>",
  "blocker": "<specific blocker — required when feasible=false; null otherwise>",
  "blocker_severity": "must_address" | "should_address" | null,
  "verdict": "APPROVED" | "REJECTED"
}
```

- `blocker_severity = "must_address"`: blocking — `research:run` MUST stop the hypothesis from advancing (e.g., requires new framework, breaks existing API contract)
- `blocker_severity = "should_address"`: advisory — pipeline MAY continue with a warning (e.g., adds modest refactor cost but is achievable in-scope)
- `blocker_severity = null`: only valid when `feasible: true` and `verdict: APPROVED`

Write combined queue to `$RUN_DIR/hypotheses.jsonl` (do NOT create new timestamped subdir — write directly to caller-provided `$RUN_DIR`).

### Error / Rejection Output

When a hypothesis cannot be evaluated (malformed input, missing required input fields, architectural blocker preventing assessment), emit a rejection record so downstream agents can parse the failure state without ambiguity:

```jsonc
{
  // input fields still preserved verbatim where available
  "hypothesis": "<from input or null>",
  // ... other input fields ...
  "verdict": "REJECTED",
  "reason": "<one-line failure cause — e.g., 'malformed input: missing rationale field' or 'architectural blocker: requires new framework'>",
  "blocking_issues": [
    "<each blocking issue as a separate string>"
  ],
  "feasible": false,
  "blocker_severity": "must_address"
}
```

Rejection records remain on the same `hypotheses.jsonl` line stream so order is preserved; downstream (`research:run`, `research:judge`) filters on `verdict == "APPROVED"` before consuming.

### Constraints

- **Don't evaluate scientific merit** — `research:scientist` (requires `research` plugin)'s domain; assess architectural feasibility only
- **Don't write implementation code** — map where changes go, don't produce them
- **Preserve hypothesis order** — annotate in place; don't re-rank
