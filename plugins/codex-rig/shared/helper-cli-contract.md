# Helper CLI Contract

Helper option schemas live in `--help`, not skills. In a plugin, derive `PLUGIN_ROOT` from the selected `SKILL.md`
path and require every helper in `package-manifest.json`; never choose a cache with glob/latest/mtime logic or use a
source-tree fallback. The list below is the full release closure: run an entry only when the current package manifest
contains it. Before creating or changing an invocation, run the relevant packaged command:

- `python PLUGIN_ROOT/shared/create_run.py --help`
- `python PLUGIN_ROOT/shared/run_gates.py --help`
- `python PLUGIN_ROOT/shared/collect_diff.py --help`
- `python PLUGIN_ROOT/shared/collect_pr.py --help`
- `python PLUGIN_ROOT/runtime/calibration/run.py --help`
- `python PLUGIN_ROOT/runtime/calibration/run_live_ab.py --help`
- `python PLUGIN_ROOT/runtime/calibration/score_behavioral.py --help`
- `python PLUGIN_ROOT/shared/find-review-report.py --help`
- `python PLUGIN_ROOT/shared/select-git-remote.py --help`
- `python PLUGIN_ROOT/shared/write-result.py --help`
- `python PLUGIN_ROOT/shared/validate-artifacts.py --help`
- `python PLUGIN_ROOT/skills/code-review/validate_artifacts.py --help`

Create every skill run with `python PLUGIN_ROOT/shared/create_run.py --skill <skill-id>`. Retain its single printed
path and pass that literal path explicitly to every later helper and artifact operation. Never persist the path in a
shell variable or assume state survives between command/tool calls.

Also run each skill-specific local CLI's `--help`. Do not copy full flags/templates into `SKILL.md`; state only:

- gate commands or skip reasons
- metadata variable and confidence gaps
- shared validator skill name
- prior skill-specific validator
- extra artifacts and pass/fail rules

Result lifecycle:

1. `run_gates.py` writes `gates.json` and per-gate evidence.
2. `write-result.py` writes `result.candidate.json` and reconciles status with gate evidence.
3. Run configured skill-specific validation.
4. `validate-artifacts.py` validates the shared and skill-specific artifact contract.
5. Rename only validated candidate to `result.json`.

Never hand-write `result.json`, promote unvalidated candidate, or infer flags from stale examples.
