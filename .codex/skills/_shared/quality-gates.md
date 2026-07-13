# Codex Quality Gates

All codex-native skills must emit the same gate fields.

## Required checks

1. `lint`: `ruff check` (or project lint command)
2. `format`: formatter check or formatter run result
3. `types`: `mypy` (or project type check command)
4. `tests`: impacted tests at minimum, full suite for broad changes
5. `review`: explicit self-review of diff and risks; check request conformance for the deliverable, constraints, and disclosed deviations

## Required gate output

Each skill run must write:

- `status`: `pass`, `fail`, or `timeout`
- `checks_run`: list of check ids that were executed
- `checks_failed`: list of check ids that failed
- `findings`: severity counts `{critical, high, medium, low}`
- `confidence`: numeric `0.0` to `1.0`
- `artifact_path`: absolute or repo-relative path to result artifact

Confidence must be backed by objective evidence. Every skill and agent output must apply the shared confidence band policy before user-facing output: `<= 0.8` is not acceptable as a completion or review signal and must return `status=fail` or `status=timeout` for skill artifacts with `confidence-not-acceptable` in `checks_failed`; `0.8 < confidence < 0.85` is very questionable and must return `status=fail` or `status=timeout` for skill artifacts with `confidence-very-questionable` in `checks_failed`; `0.85 <= confidence < 0.9` is cautious-low and may proceed only with objective evidence, recovery actions, and remaining limits; `>= 0.9` is fair but not automatic and must remain evidence-backed with any material residual limits named. Skill result JSON must record `metadata.confidence_recovery` with initial score, evidence, recovery actions, recomputed score, band status, and remaining limits. Chat reports the score and material limits; detailed recovery and closure evidence stays in the artifact when one exists. Any skill or agent output that includes a confidence score must also list confidence gaps or degradation reasons. Every confidence gap must either have additional evidence that closes the gap or an explicit unresolved/deferred record that carries it forward. In result JSON, write `metadata.confidence_gaps` and `metadata.confidence_gap_closures`; if `confidence < 1.0`, `confidence_gaps` must contain at least one concrete gap or residual limit, and each non-empty gap must have a matching closure record with `status` set to `closed`, `unresolved`, or `deferred`.

Each `run-gates.sh` invocation must write `gates.json` with exactly the five required IDs. Every entry contains `id`, `status`, `exit_code`, `duration_seconds`, `command_path`, `stdout`, and `stderr`; `missing-command`, `not-applicable`, and `timeout` also require a reason. `not-applicable` is non-failing only with that explicit reason. `missing-command` and `timeout` fail. The result artifact must reconcile its status and check lists with `gates.json`.

Optional but recommended:

- `recommendations`: list of concrete next improvements
- `follow_up`: list of prioritized next actions
- `metadata`: required when confidence is reported so confidence gaps and closures are machine-readable; otherwise a skill-specific JSON object for evidence that should not be hidden in prose notes

## Fail rules

- Any `critical` finding => `status=fail`
- Any failed check in `checks_failed` => `status=fail`
- Missing command/tool for a required gate => `status=fail`
- Explicitly unsupported target with `status=not-applicable` and a reason => non-failing
- Missing artifact => `status=fail`
- If execution stops due to gate timeout => `status=timeout`
- For every skill and agent, `confidence <= 0.8` cannot pass, `0.8 < confidence < 0.85` is very questionable and cannot be treated as complete, `0.85 <= confidence < 0.9` is cautious-low and needs recorded recovery actions plus remaining limits, and `confidence >= 0.9` is fair but still must not be taken blindly.

## Artifact path contract

- Path: `.reports/codex/<skill>/<YYYY-MM-DDTHH-MM-SSZ>/result.json`
- Optional: `notes.md` in same directory

## Native contract

Skill files should follow `native-skill-contract.md`. Configured skills require:

- `Input Schema`
- `Workflow`
- `Fail-Fast Rules`
- `Quality Gates`
- `Calibration Hooks`
- `Output Contract`

Configured agents require:

- `Boundaries`
- `Evidence Standard`
- `Output Contract`
- clear `TRIGGER`, `SKIP`, and `NOT for` routing clauses

## Execution helpers

- Use `.codex/skills/_shared/run-gates.sh` to execute the five checks consistently.
- Use executable `.codex/skills/_shared/write-result.py` to write canonical JSON result payloads.
- Use `.codex/skills/_shared/collect-diff.sh` to collect scope-aware git diff artifacts consistently.
- Use `.codex/skills/_shared/collect-pr.sh --checkout` to collect PR diff, metadata, comments, reviews, review threads, unresolved review threads, target-branch refresh evidence, PR branch refresh evidence where possible, and local PR checkout evidence consistently.
- PR checkout/update artifacts must not record `git` or `gh` commands with `--force`; a forced operation requires a stop-and-ask user confirmation with overwrite-risk rationale before it is run.
- Use `.codex/skills/_shared/validate-artifacts.py` to validate common report, ledger, gate-log, and result JSON artifacts.
- Use `.codex/skills/_shared/severity-map.md` to map findings to severity levels.

## Behavior-Change Guardrails

When a change modifies Codex behavior, it must also update registrations, docs, and calibration coverage in the same patch. Prefer enhancing an existing agent or skill over adding a new one unless the new role or workflow has distinct triggers, acceptance criteria, and measurable gates.
