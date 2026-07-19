# Native Skill Contract

Codex-native skills are portable local workflows. Runnable contract: shared result schema plus the selected package
layout recorded in `package-manifest.json`.

## Required Sections

Every native `SKILL.md` keeps these sections or clear equivalents:

- YAML-style frontmatter: unindented `---`, `name:`, `description:` before first Markdown heading.
- `Input Schema`: required inputs, optional inputs, mode flags, and done condition.
- `Workflow`: linear steps with stable local commands where commands are useful.
- `Quality Gates`: check mapping and pass/fail decision rules.
- `Fail-Fast Rules`: conditions that stop or fail the run.
- `Calibration Hooks`: expected calibration updates when behavior changes.
- `Output Contract`: shared JSON result fields from `quality-gates.md`.

Long workflows keep contract-level `## Workflow` with `### NN:` ordered subheaders. Do not make workflow steps `##` peers of contract sections.

## Portability Rules

- Keep `.reports/codex/<skill>/<timestamp>/result.json` as the canonical artifact.
- New human-readable report artifacts use Caveman Ultra: each fact once, no filler or repeated context. Do not compress or omit machine-readable JSON, commands, paths, code, logs, patches, required tables, evidence, failures, risks, owner/action, or confidence limits. Use clear concise prose where Ultra would make security, irreversible, or ordered instructions ambiguous.
- Use `PLUGIN_ROOT/shared/run-gates.sh` and executable `write-result.py` when the skill changes files or runs code checks.
- Use `PLUGIN_ROOT/shared/helper-cli-contract.md` for gate/write/validate lifecycle. Helper `--help` owns options; skills do not duplicate full local CLI invocations.
- Use `PLUGIN_ROOT/shared/collect-diff.sh` for scope-aware `working-tree`, `path`, `commit` diffs; do not duplicate git plumbing.
- Use `PLUGIN_ROOT/shared/collect-pr.sh --checkout` for PR diff, metadata, comments/reviews/threads, unresolved threads, target/PR refresh where possible, local checkout evidence; no ad hoc `gh`/raw URL snapshots.
- Use `PLUGIN_ROOT/shared/find-review-report.py` for path-free PR report lookup; no ad hoc JSON parsing in instructions.
- Delegation/in-main substitute passes use `PLUGIN_ROOT/shared/specialist-orchestration.md`, narrow context packs, explicit output contracts, parent consolidation.
- Put bulky skill result JSON examples in sibling `result-template.json`. In `SKILL.md`, reference it; do not embed long "Minimum artifact payload" blocks.
- Never automatically run `git`/`gh` `--force`. Stop and ask with concrete reason and overwrite risk if needed.
- Use `PLUGIN_ROOT/shared/validate-artifacts.py` for common shapes when durable notes, ledgers, JSONL exist.
- Prefer local files, `git`, `rg`, project commands, explicit citations.
- External services/browser optional; caveat when unavailable.
- Native operation requires no external-runner metadata, hidden cache, widget, slash syntax, non-Codex path variable.

## Evidence Rules

- Code claims: file/line refs. Current external: live primary source or stale/unverified caveat. Root cause: evidence, falsification, rejected alternative. Metric: baseline, guard, comparison. Release: SemVer plus changelog/migration evidence.
- Every skill/agent score uses bands: `<= 0.8` unacceptable; `0.8 < confidence < 0.85` very questionable; `0.85 <= confidence < 0.9` cautious-low; `>= 0.9` fair but not automatic.
- Skill JSON `metadata.confidence_recovery`: initial/final score, band, objective evidence, recovery, limits. Post-recovery `<= 0.8`: `confidence-not-acceptable`; `0.8 < confidence < 0.85`: `confidence-very-questionable`. Agent output has visible prose/table same fields.
- Close gaps with evidence or explicit unresolved/deferred record. Skill JSON uses `metadata.confidence_gap_closures`; agents show closure list/table.

## Calibration Hooks

Native-skill behavior changes update at least one:

- `PLUGIN_ROOT/runtime/calibration/benchmarks.json`
- `PLUGIN_ROOT/runtime/calibration/behavioral-cases.json`
- `PLUGIN_ROOT/runtime/calibration/behavioral-observations.jsonl`
- `PLUGIN_ROOT/runtime/calibration/run.py`

If intentionally no calibration update, review artifact explains why.
