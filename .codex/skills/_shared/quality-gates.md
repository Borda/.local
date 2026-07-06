# Codex Quality Gates

All codex-native skills must emit the same gate fields.

## Required checks

1. `lint`: `ruff check` (or project lint command)
2. `format`: formatter check or formatter run result
3. `types`: `mypy` (or project type check command)
4. `tests`: impacted tests at minimum, full suite for broad changes
5. `review`: explicit self-review of diff and risks

## Required gate output

Each skill run must write:

- `status`: `pass`, `fail`, or `timeout`
- `checks_run`: list of check ids that were executed
- `checks_failed`: list of check ids that failed
- `findings`: severity counts `{critical, high, medium, low}`
- `confidence`: numeric `0.0` to `1.0`
- `artifact_path`: absolute or repo-relative path to result artifact

Each `run-gates.sh` invocation must also write `gates.json` with one entry per check containing `id`, `status`, `exit_code`, `duration_seconds`, `command_path`, `stdout`, and `stderr`.

Optional but recommended:

- `recommendations`: list of concrete next improvements
- `follow_up`: list of prioritized next actions
- `metadata`: skill-specific JSON object for machine-readable evidence that should not be hidden in prose notes

## Fail rules

- Any `critical` finding => `status=fail`
- Any failed check in `checks_failed` => `status=fail`
- Missing artifact => `status=fail`
- If execution stops due to gate timeout => `status=timeout`

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
- Use `.codex/skills/_shared/write-result.sh` to write canonical JSON result payloads.
- Use `.codex/skills/_shared/collect-diff.sh` to collect scope-aware git diff artifacts consistently.
- Use `.codex/skills/_shared/collect-pr.sh --checkout` to collect PR diff, metadata, comments, reviews, review threads, unresolved review threads, target-branch refresh evidence, PR branch refresh evidence where possible, and local PR checkout evidence consistently.
- PR checkout/update artifacts must not record `git` or `gh` commands with `--force`; a forced operation requires a stop-and-ask user confirmation with overwrite-risk rationale before it is run.
- Use `.codex/skills/_shared/validate-artifacts.py` to validate common report, ledger, gate-log, and result JSON artifacts.
- Use `.codex/skills/_shared/severity-map.md` to map findings to severity levels.

## Behavior-Change Guardrails

When a change modifies Codex behavior, it must also update registrations, docs, and calibration coverage in the same patch. Prefer enhancing an existing agent or skill over adding a new one unless the new role or workflow has distinct triggers, acceptance criteria, and measurable gates.
