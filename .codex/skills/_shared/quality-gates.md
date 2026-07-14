# Codex Quality Gates

All codex-native skills must emit the same gate fields.

## Required checks

1. `lint`: `ruff check` (or project lint command)
2. `format`: formatter check or formatter run result
3. `types`: `mypy` (or project type check command)
4. `tests`: impacted tests at minimum, full suite for broad changes
5. `review`: self-review diff/risks; check request conformance, constraints, disclosed deviations

## Required gate output

Each skill run must write:

- `status`: `pass`, `fail`, or `timeout`
- `checks_run`: list of check ids that were executed
- `checks_failed`: list of check ids that failed
- `findings`: severity counts `{critical, high, medium, low}`
- `confidence`: numeric `0.0` to `1.0`
- `artifact_path`: absolute or repo-relative path to result artifact

Confidence needs objective evidence. Before user output, apply bands: `<= 0.8` unacceptable; skill artifact returns `status=fail` or `status=timeout` with `confidence-not-acceptable` in `checks_failed`. `0.8 < confidence < 0.85` very questionable; return `status=fail` or `status=timeout` with `confidence-very-questionable`. `0.85 <= confidence < 0.9` cautious-low; proceed only with objective evidence, recovery actions, remaining limits. `>= 0.9` fair but not automatic; name evidence-backed material limits. Result JSON records `metadata.confidence_recovery`: initial score, evidence, recovery actions, recomputed score, band status, remaining limits. Chat reports score and material limits; artifact holds detailed recovery/closure evidence. Every scored skill/agent output lists confidence gaps or degradation reasons. Close each with evidence or explicit unresolved/deferred record. Preserve result fields `status`, `checks_failed`, and `confidence_gaps`. Write `metadata.confidence_gaps` and `metadata.confidence_gap_closures`; when `confidence < 1.0`, include one concrete gap/residual limit and a matching `closed`, `unresolved`, or `deferred` closure.

Each `run-gates.sh` writes `gates.json` with exactly five IDs. Entries contain `id`, `status`, `exit_code`, `duration_seconds`, `command_path`, `stdout`, `stderr`; `missing-command`, `not-applicable`, `timeout` also need reason. `not-applicable` passes only with explicit reason; `missing-command`/`timeout` fail. Result status/check lists reconcile with `gates.json`.

Optional but recommended:

- `recommendations`: list of concrete next improvements
- `follow_up`: list of prioritized next actions
- `metadata`: required with confidence for machine-readable gaps/closures; otherwise skill-specific evidence not hidden in prose notes

## Fail rules

- Any `critical` finding => `status=fail`
- Any failed check in `checks_failed` => `status=fail`
- Missing command/tool for a required gate => `status=fail`
- Explicitly unsupported target with reason and `status=not-applicable` => non-failing
- Missing artifact => `status=fail`
- Gate timeout => `status=timeout`
- For every skill/agent: `confidence <= 0.8` cannot pass; `0.8 < confidence < 0.85` cannot be complete; `0.85 <= confidence < 0.9` needs recorded recovery/limits; `confidence >= 0.9` still needs evidence.

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
- Use `.codex/skills/_shared/collect-pr.sh --checkout` for PR diff, metadata, comments/reviews/threads, unresolved threads, target/PR refresh where possible, local checkout evidence.
- PR checkout/update artifacts never record `git`/`gh` `--force`; force needs stop-and-ask confirmation with overwrite-risk rationale first.
- Use `.codex/skills/_shared/validate-artifacts.py` to validate common report, ledger, gate-log, and result JSON artifacts.
- Use `.codex/skills/_shared/severity-map.md` to map findings to severity levels.

## Behavior-Change Guardrails

Codex behavior changes must also update registrations, docs, calibration in same patch. Prefer existing agent/skill unless new role/workflow has distinct triggers, acceptance criteria, measurable gates.
