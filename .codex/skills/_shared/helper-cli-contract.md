# Helper CLI Contract

Helper option schemas live in `--help`, not skills. Before creating/changing invocation, run relevant local command:

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

Also run each skill-specific local CLI's `--help`. Do not copy full flags/templates into `SKILL.md`; state only:

- gate commands or skip reasons
- metadata variable and confidence gaps
- shared validator skill name
- prior skill-specific validator
- extra artifacts and pass/fail rules

Result lifecycle:

1. `run-gates.sh` writes `gates.json` and per-gate evidence.
2. `write-result.py` writes `result.candidate.json` and reconciles status with gate evidence.
3. Run configured skill-specific validation.
4. `validate-artifacts.py` validates the shared and skill-specific artifact contract.
5. Rename only validated candidate to `result.json`.

Never hand-write `result.json`, promote unvalidated candidate, or infer flags from stale examples.
