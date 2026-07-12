# Helper CLI Contract

Shared helper option schemas live in `--help`, not in individual skills. Before constructing or changing an invocation, run the relevant local command:

```bash
.codex/calibration/run.py --help
.codex/calibration/run_live_ab.py --help
.codex/calibration/score_behavioral.py --help
.codex/skills/_shared/run-gates.sh --help
.codex/skills/_shared/collect-diff.sh --help
.codex/skills/_shared/collect-pr.sh --help
.codex/skills/_shared/find-review-report.py --help
.codex/skills/_shared/select-git-remote.py --help
.codex/skills/_shared/write-result.py --help
.codex/skills/_shared/validate-artifacts.py --help
.codex/skills/code-review/validate_artifacts.py --help
.github/codex-harness.sh --help
```

For any skill-specific local CLI, run that CLI's `--help` as well. Do not copy full flag lists or command templates into `SKILL.md`. A skill should state only:

- its gate commands or explicit skip reasons
- its metadata variable and confidence gaps
- its shared validator skill name
- any skill-specific validator that runs before the shared validator
- additional required artifacts and pass/fail rules

Canonical result lifecycle:

1. `run-gates.sh` writes `gates.json` and per-gate evidence.
2. `write-result.py` writes `result.candidate.json` and reconciles status with gate evidence.
3. Skill-specific validation runs when configured.
4. `validate-artifacts.py` validates the shared and skill-specific artifact contract.
5. Only a validated candidate is renamed to `result.json`.

Never hand-write `result.json`, promote an unvalidated candidate, or infer flags from stale examples.
