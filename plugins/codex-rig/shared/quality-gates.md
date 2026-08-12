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

Each `run_gates.py` invocation writes `gates.json` with exactly five IDs. Entries contain `id`, `status`, `exit_code`, `duration_seconds`, `command_path`, `stdout`, `stderr`; `missing-command`, `not-applicable`, `timeout` also need reason. `not-applicable` passes only with explicit reason; `missing-command`/`timeout` fail. Result status/check lists reconcile with `gates.json`.

Optional but recommended:

- `recommendations`: list of concrete next improvements
- `follow_up`: list of prioritized next actions
- `metadata`: required with confidence for machine-readable gaps/closures; otherwise skill-specific evidence not hidden in prose notes

## Fail rules

- Any `critical` finding => `status=fail`
- Any failed check in `checks_failed` => `status=fail`
- Missing command/tool for a required gate => `status=fail`
- Explicitly unsupported gate with reason => that gate's per-check `gates.json` entry `status=not-applicable`; non-failing, excluded from `checks_failed` (top-level run `status` stays `pass`/`fail`/`timeout` only — see "Required gate output")
- All five `gates.json` entries `not-applicable` => top-level run `status=pass` (zero failures to report)
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

- Use `python PLUGIN_ROOT/shared/run_gates.py` to execute the five checks consistently.
- Use executable `PLUGIN_ROOT/shared/write-result.py` to write canonical JSON result payloads.
- Use `python PLUGIN_ROOT/shared/collect_diff.py` to collect scope-aware git diff artifacts consistently.
- `github_read.py` is the plugin-wide GitHub data boundary. Use it for all issue/release/repository reads and an explicit GraphQL query for Discussions; use `collect_pr.py --checkout` for complete PR evidence. Never invoke `gh` directly. The broker prefers authenticated `gh` but never inspects credentials; it permits only audited built-in view groups (`gist`, `issue`, `pr`, `project`, `release`, `repo`, `ruleset`, `run`, `workflow`), REST GET, and GraphQL query argv, and persists no CLI failure output. Its public `api.github.com` fallback is unauthenticated and cannot replace private-only evidence, so complete PR collection fails closed if its review-thread query cannot run. `gh pr checkout` changes only the local checkout. Codex Git marketplace add/upgrade remains a separately authorized lifecycle operation.
- Apply `native-skill-contract.md` Networked CLI Approval to each intentional shell-network path: keep persistent workspace networking disabled and approve the complete owning command, not only a nested executable.
- PR checkout/update artifacts never record `git`/`gh` `--force`; force needs stop-and-ask confirmation with overwrite-risk rationale first.
- Use `PLUGIN_ROOT/shared/validate-artifacts.py` to validate common report, ledger, gate-log, and result JSON artifacts.
- Use `PLUGIN_ROOT/shared/severity-map.md` to map findings to severity levels.

## Behavior-Change Guardrails

Codex behavior changes must also update registrations, docs, calibration in same patch. Prefer existing agent/skill unless new role/workflow has distinct triggers, acceptance criteria, measurable gates.
