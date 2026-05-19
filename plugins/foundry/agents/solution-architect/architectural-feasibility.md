<!-- Loaded by foundry:solution-architect (opusplan + high) -->
# Architectural Feasibility (foundry:solution-architect specialized guidance)

Read this file only when invoked by `/research:run --researcher` (requires `research` plugin) to filter AI-generated experiment hypotheses. Skip for standalone ADR / API-design / migration-plan tasks.

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

Annotate each hypothesis with `{feasible: bool, blocker: str?, codebase_mapping: str}` and write combined queue to `.experiments/<YYYY-MM-DDTHH-MM-SSZ>/hypotheses.jsonl`.

### Constraints

- **Don't evaluate scientific merit** — `research:scientist` (requires `research` plugin)'s domain; assess architectural feasibility only
- **Don't write implementation code** — map where changes go, don't produce them
- **Preserve hypothesis order** — annotate in place; don't re-rank
