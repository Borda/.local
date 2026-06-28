---
name: audit
description: Minimal codex-native audit loop. Use to scan codex configuration/workflow drift and emit ranked gaps with measurable gates.
---

# Audit

Run a linear configuration and workflow audit loop.

## Input Schema

```json
{
  "scope": "config|skills|agents|all",
  "target": "optional path",
  "mode": "upgrade|adversarial",
  "skip_gate": false,
  "done_when": "drift and broken references are ranked with gate result; fix level chosen interactively unless skip_gate=true"
}
```

## Workflow (Exact Commands)

01. Create run directory.

    ```bash
    TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
    OUT_DIR=".reports/codex/audit/$TS"
    mkdir -p "$OUT_DIR"
    ```

02. Normalize scope and collect inventory.

    Scopes:

    - `config`: `.codex/config.toml`, project instructions, permission/routing entries.
    - `skills`: `.codex/skills/**` plus calibration coverage for skills.
    - `agents`: `.codex/agents/*.toml` plus spawn/routing coverage.
    - `all`: every scope above.

    ```bash
    find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/inventory.txt"
    ```

03. Build an audit ledger before running gates.

    Write `$OUT_DIR/audit-ledger.md` with these sections:

    - `Inventory`: configured vs present agents/skills.
    - `Broken References`: missing files, stale paths, unresolved shared resources.
    - `Runtime Leaks`: non-native runner fields or external runtime assumptions in native files.
    - `Coverage`: calibration benchmark and behavioral coverage.
    - `Overlap`: duplicate or fuzzy ownership decisions.
    - `Recommendations`: ranked fix plan.

04. Run shared quality gates.

    ```bash
    .codex/skills/_shared/run-gates.sh \
        --out "$OUT_DIR" \
        --lint "${LINT_CMD:-bash -lc 'if command -v ruff >/dev/null 2>&1; then ruff check .codex; else UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/codex-uv-cache} uv run --no-sync ruff check .codex; fi'}" \
        --format "${FORMAT_CMD:-bash -lc 'if command -v ruff >/dev/null 2>&1; then ruff format --check .codex; else UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/codex-uv-cache} uv run --no-sync ruff format --check .codex; fi'}" \
        --types "${TYPES_CMD:-true}" \
        --tests "${TESTS_CMD:-true}" \
        --review "${REVIEW_CMD:-git diff --check}"
    ```

05. Detect drift and broken references.

    ```bash
    rg -n "config_file|skills/|quality-gates|run-gates.sh|write-result.sh" .codex >"$OUT_DIR/reference-scan.txt"
    ```

06. Audit spawn-pattern coverage and overlap in `AGENTS.md` (instruction-level check).

    ```bash
    rg -n "^### Spawn $(.+) when:" .codex/AGENTS.md >"$OUT_DIR/spawn-sections.txt"
    rg -n "Automatic spawn patterns \\(all agents\\)|Collaboration team patterns" .codex/AGENTS.md >"$OUT_DIR/spawn-policy-sections.txt"
    ```

07. Review native skill and agent contract consistency.

    Each configured skill should have:

    - `Input Schema`
    - `Workflow`
    - `Fail-Fast Rules`
    - `Quality Gates`
    - `Calibration Hooks`
    - `Output Contract`

    Each configured agent should have:

    - `## Scope` or clear role boundary text
    - `## Evidence Standard`
    - `## Boundaries`
    - `## Output Contract` or explicit output format

08. Review agent-roster consistency.

    ```bash
    rg -n "^(name|description|developer_instructions)" .codex/agents >"$OUT_DIR/agent-roster-scan.txt"
    ```

    Classify overlap findings explicitly as `keep`, `sharpen`, or `merge-prune`:

    - `keep`: distinct decision surface remains
    - `sharpen`: role stays, but boundary text should tighten
    - `merge-prune`: role no longer owns a distinct acceptance criterion

09. Classify findings using `../_shared/severity-map.md`.

10. Write mandatory result artifact.

```bash
.codex/skills/_shared/write-result.sh \
    --out "$OUT_DIR/result.json" \
    --status "$STATUS" \
    --checks-run "lint,format,types,tests,review" \
    --checks-failed "$CHECKS_FAILED" \
    --critical "$CRITICAL" \
    --high "$HIGH" \
    --medium "$MEDIUM" \
    --low "$LOW" \
    --confidence "$CONFIDENCE" \
    --artifact-path "$OUT_DIR/result.json"
```

## Fail-fast Rules

1. Missing `.codex` inventory => fail.
2. Shared gate script missing => fail.
3. Broken config/skill references in critical paths => fail.
4. Missing spawn coverage for any configured agent => fail.
5. Unclear or overlapping spawn intent without explicit collaboration-team guidance => fail.
6. Agent overlap left without a keep/sharpen/merge-prune decision => fail.
7. Missing native skill or agent contract section on a configured entry => fail unless an explicit exception is recorded.
8. Non-native runtime assumptions in `.codex/skills/*/SKILL.md` or `.codex/agents/*.toml` => fail.
9. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: inventory, contract ledger, reference scan, overlap decisions, and `git diff --check`.
- `calibration`: run or explicitly justify skipping `.codex/calibration/run.sh` when skill/agent behavior changed.

Conditional checks:

- `lint`/`format`: enabled when generated Python, TOML, shell, or Markdown formatters are available.
- `tests`: enabled when audit includes executable probes or behavior-changing fixes.

## Calibration Hooks

Update calibration when audit scope, contract requirements, or routing checks change:

- benchmark patterns: `audit`, every configured skill, every configured agent
- behavioral cases: runtime leak detection, stale reference handling, overlap classification, unsafe sync recommendation

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail|timeout",
  "checks_run": [
    "lint",
    "format",
    "types",
    "tests",
    "review"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "artifact_path": ".reports/codex/audit/<timestamp>/result.json",
  "recommendations": [],
  "follow_up": []
}
```
