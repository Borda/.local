# Native Skill Contract

Codex-native skills are portable local workflows. Their runnable contract is the shared Codex result schema and the local `.codex/` layout.

## Required Sections

Every native `SKILL.md` should keep these sections or clear equivalents:

- YAML-style frontmatter with unindented `---` markers, `name:`, and `description:` before the first Markdown heading.
- `Input Schema`: required inputs, optional inputs, mode flags, and done condition.
- `Workflow`: linear steps with stable local commands where commands are useful.
- `Quality Gates`: check mapping and pass/fail decision rules.
- `Fail-Fast Rules`: conditions that stop or fail the run.
- `Calibration Hooks`: expected calibration updates when behavior changes.
- `Output Contract`: shared JSON result fields from `quality-gates.md`.

Long workflow sections should keep `## Workflow` as the contract-level section and use `### NN:` subheaders for ordered steps. Do not promote workflow steps to `##` headings because that makes them peers of the required contract sections.

## Portability Rules

- Keep `.reports/codex/<skill>/<timestamp>/result.json` as the canonical artifact.
- Use `.codex/skills/_shared/run-gates.sh` and executable `write-result.py` when the skill changes files or runs code checks.
- Use `.codex/skills/_shared/collect-diff.sh` for scope-aware `working-tree`, `path`, or `commit` diff collection instead of duplicating git plumbing.
- Use `.codex/skills/_shared/collect-pr.sh --checkout` for PR diff, metadata, comments, reviews, review threads, unresolved review-thread collection, target-branch refresh, PR branch refresh where possible, and local PR checkout evidence instead of ad hoc `gh` calls or raw URL file snapshots.
- Use `.codex/skills/_shared/find-review-report.py` for path-free PR review report lookup instead of embedding ad hoc JSON parsing in skill instructions.
- Never run `git` or `gh` with `--force` automatically. If a forced checkout or update appears necessary, stop and ask the user with the concrete reason and overwrite risk.
- Use `.codex/skills/_shared/validate-artifacts.py` for common skill artifact shape checks when a skill has durable notes, ledgers, or JSONL evidence.
- Prefer local files, `git`, `rg`, project commands, and explicit source citations.
- Treat external services and browser access as optional aids that require an explicit caveat when unavailable.
- Do not require external runner metadata, hidden cache paths, interactive widgets, slash-command syntax, or non-Codex path variables for native operation.

## Evidence Rules

- Code claims need file and line references.
- Current external claims need live primary-source verification or a stale/unverified caveat.
- Root-cause claims need evidence, a falsification check, and at least one rejected alternative.
- Metric claims need a baseline, a guard, and a comparison.
- Release claims need SemVer reasoning and changelog/migration evidence.
- Confidence scores need the shared confidence band policy for every skill and agent: `<= 0.8` is not acceptable, `0.8 < confidence < 0.85` is very questionable, `0.85 <= confidence < 0.9` is cautious-low, and `>= 0.9` is fair but not automatic.
- Skill result JSON uses `metadata.confidence_recovery` with initial score, final score, band status, objective evidence, recovery actions, and remaining limits. Skills still at `<= 0.8` after recovery use `confidence-not-acceptable`; skills still at `0.8 < confidence < 0.85` use `confidence-very-questionable`. Agent outputs use visible confidence-recovery prose or a compact table with the same fields.
- Confidence gaps need additional evidence that closes the gap or an explicit unresolved/deferred record that carries the gap forward. Skill result JSON uses `metadata.confidence_gap_closures`; agent outputs use a visible confidence-gap closure list or table.

## Calibration Hooks

Behavior changes to native skills must update at least one of:

- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/calibration/behavioral-observations.jsonl`
- `.codex/calibration/run.py`

If a change intentionally does not update calibration, the review artifact must explain why.
