# Demo mode — end-to-end validation

Validates codemap plugged in correctly and yields expected gains. State var `DEMO_MODE` (real | synthetic) drives D5a/D5b path selection.

**Full flow**: plumbing → integration gate → index ensure → sample tasks → real-skill probe (if wired) → synthetic A/B → telemetry diagnostic → final report.

> methodology detail (scoring formulas, SQ_DELTA=0 root causes, honest caveats, scenario matrix): demo-notes.md

## D0 — Parse args

Parse `$ARGUMENTS` (all optional):

- `--repo <path|url>` — target; path = use as-is; URL = trigger D1a clone gate
- `--public` — force D1a clone gate even if current repo has `.py` files
- `--anonymize` — forward to `debrief-coding` in D6; safe-to-share report
- `--keep-clone` — skip D9 cleanup prompt
- `--output <path>` — override report path in D8
- `--probe-skill <name>` — pin the D5a real-skill probe to `<plugin>:<skill>` (e.g. `develop:review`); overrides the built-in priority list when the named skill is wired. Unset → fall through to the priority list.

Leave `CODEMAP_LOGGING=true` (default). Each bash block needing `$TARGET` must use a separate `cd "$TARGET"` call first — never chain `cd "$TARGET" && command` (violates CLAUDE.md compound-bash rule; permission matcher only checks first token).

Set `TARGET` from `--repo` (path case) or after D1a clone. Resolve `SQ` via `bin/locate_scan_query.py`. Init `CLONED=false`, `DEMO_MODE=synthetic`, `PROBE_SKILL` from `--probe-skill` (empty if unset).

## D1 — Resolve target

```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py")  # timeout: 5000
```

Decision:
- `--repo <path>` → `TARGET="<path>"`. Skip to D2.
- `--repo <url>` → set `CLONE_URL`; go to D1a.
- `--public` set → go to D1a.
- `find . -maxdepth 3 -name "*.py" | head -1` finds a file → `TARGET=$(git rev-parse --show-toplevel)`. Skip to D2.
- Otherwise → go to D1a.

## D1a — Clone gate (mandatory `AskUserQuestion`)

> Must invoke `AskUserQuestion` — never clone without explicit confirmation.

Ask: "No local Python repo detected. Which public repo to clone for the demo?" Options:
- (a) Cancel — stop demo
- (b) psf/requests (Recommended) — pinned task set with ground truth available
- (c) pallets/click — no pinned task set (tool-count proxy only)
- (d) Other URL — user pastes

On cancel: stop. On selection:

```bash
CLONE_URL="https://github.com/<selected-repo>"
SANDBOX="${TMPDIR:-/tmp}/codemap-demo-$$"
mkdir -p "$SANDBOX"
git clone --depth 1 "$CLONE_URL" "$SANDBOX/$(basename "$CLONE_URL" .git)"  # timeout: 60000
TARGET="$SANDBOX/$(basename "$CLONE_URL" .git)"
```

Set `CLONED=true`. Cloned repos have no user skills → `DEMO_MODE` stays `synthetic`; skip D2a integration gate.

## D2 — Plumbing check (C1–C4 inline)

Run bin scripts inline — demo controls cwd and parses C3 JSON directly. First resolve the index path so the smoke script receives `--index-path`.

```bash
# timeout: 5000
_DEMO_PROJ=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$TARGET")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-demo-${_DEMO_PROJ}" 2>/dev/null
_DEMO_INDEX=$(cat "${TMPDIR:-/tmp}/codemap-demo-${_DEMO_PROJ}-resolve-index" 2>/dev/null || echo "")
```

```bash
# timeout: 15000
C3_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" \
    --index-path "${_DEMO_INDEX}" 2>&1)
```

```bash
# timeout: 10000
C4_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" 2>&1)
```

Derive from outputs:

| Check | OK signal | Derived boolean |
| --- | --- | --- |
| C1 scan-query | exit 0 + non-empty `$SQ` | `scan_query_ok` |
| C2 index path | exit 0 | `index_path_ok` |
| C3 smoke | `"ok": true` in JSON | `smoke_ok`; extract `stale`, `age_hours`, `error` |
| C4 injection | exit 0 | `injection_present`; parse stdout for wired file paths → `WIRED_FILES[]` |

Parse `WIRED_FILES[]` from C4 stdout — every line matching a `.md` path with the injection marker:

```bash
WIRED_FILES=$(echo "$C4_OUT" | grep -E '\.(md)' | grep -v "missing\|not found\|✗")
```

Build plumbing summary table (printed in D8):

| Check | Status | Detail |
| --- | --- | --- |
| scan-query | ✓/✗ | path |
| index | ✓/⚠/✗ | path or "missing" |
| smoke | ✓/✗ | age_hours / error if any |
| injection | ✓/⚠/✗ | N files wired / "none" |

If `scan_query_ok=false`: print remediation hint (`claude plugin install codemap@borda-ai-rig`) and stop.

## D2a — Integration gate

Skip if `CLONED=true` — cloned repos have no user skills.

Branch on `injection_present`:

**`true`**: set `DEMO_MODE=real`. Continue to D3.

**`false`**: invoke `AskUserQuestion`: "Codemap not wired into any installed skills yet. The demo can run `init` now to wire it in, or proceed with a synthetic A/B only." Options:
- (a) Run `init` now — wire codemap then validate (Recommended)
- (b) Synthetic A/B only — skip real-skill probe, label results accordingly
- (c) Cancel

On (a): `Skill(skill="codemap:integration", args="init")`. After init, re-run C4:

```bash
cd "$TARGET"
C4_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" 2>&1)  # timeout: 10000
```

Re-derive `injection_present` and `WIRED_FILES[]`. If `injection_present=true` → `DEMO_MODE=real`. If still false → `DEMO_MODE=synthetic`; record "init ran but no files were wired" as a finding.

On (b): `DEMO_MODE=synthetic`. Continue. On (c): stop.

## D3 — Ensure index

If `smoke_ok=false` or index missing:

```bash
Skill(skill="codemap:scan-codebase")
```

Re-run C3 to verify. Record `module_count`, `degraded_count` from C3 JSON. If still failing after build: warn, continue (A/B degrades gracefully — arms fall back to grep).

## D4 — Sample tasks (populate cli.jsonl)

Load `${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/skills/integration/templates/demo-tasks.json`. Select task set by `basename "$TARGET"`:
- `requests` → `psf_requests` set (ground truth available)
- anything else → `generic` set

For each sample task:

```bash
cd "$TARGET"
START_MS=$(($(date +%s) * 1000))
RESULT=$("$SQ" <subcommand> <args> 2>&1)  # timeout: 30000
END_MS=$(($(date +%s) * 1000))
TIMING_MS=$((END_MS - START_MS))
```

Record per-call: `task_id`, `cmd`, `timing_ms`, `result_count` (parse from JSON), `exhaustive`, `not_covered`.

Seed `skills.jsonl` and session id via one explicit Skill() call:

```bash
Skill(skill="codemap:query-code", args="central --top 3")
```

PreToolUse hook writes one `skills.jsonl` entry and stamps `${TMPDIR}/codemap-<proj>-session`.

## D5a — Real-skill probe

**Run only when `DEMO_MODE=real` and `CLONED=false`.** Goal: prove codemap injection fires inside the user's actual installed skill — not a synthetic agent.

### Pick skill

Map `WIRED_FILES[]` paths to installed skill names:

- `…/plugins/<plugin>/skills/<skill>/SKILL.md` → `<plugin>:<skill>`
- `…/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/<skill>/SKILL.md` → `<plugin>:<skill>`

Selection precedence (first that resolves wins). Set `PROBE_SOURCE` alongside `PICKED_SKILL` — it drives the D5a confidence tier and the D8 "which probe ran" line:

1. **`--probe-skill <name>` (user arg)** — if `PROBE_SKILL` is set AND appears in the resolved `WIRED_FILES[]` names → `PICKED_SKILL=$PROBE_SKILL`, `PROBE_SOURCE=user-arg`. If set but not wired: print `⚠ --probe-skill <name> not wired; falling back to priority list`, then continue to step 2.
2. **Built-in priority list** — `develop:fix` > `develop:refactor` > `develop:review` > `oss:review` > `develop:feature`; pick first match in resolved names → `PROBE_SOURCE=priority-list`.
3. **No match** — log warning, skip D5a, run D5b only → `PROBE_SOURCE=synthetic`.

Confidence tier by `PROBE_SOURCE` (feeds the D8 report-header Confidence): `user-arg` (operator pinned a real installed skill, strongest signal) > `priority-list` (real skill, auto-picked) > `synthetic` (no real-skill probe ran). State the chosen probe and its source verbatim in the D8 Real-skill probe section.

### Pick task target

For `develop:fix` / `develop:refactor`:

```bash
# timeout: 5000
_CM_PROJ=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$TARGET")
# prefer recently modified .py — more likely to have real issues
# grep to file-path-looking lines only; avoids matching commit subjects
PROBE_FILE=$(git -C "$TARGET" log --oneline -30 --diff-filter=M --name-only -- '*.py' 2>/dev/null | grep -E '^[^[:space:]]+\.py$' | head -1)
# fallback: most central module from index
[ -z "$PROBE_FILE" ] && PROBE_FILE=$("$SQ" --timeout 5 central --top 1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); mods=d.get('central',[]); print(mods[0].get('path','') if mods else '')" 2>/dev/null || echo "")
```

For `develop:review`: use `git diff HEAD~1 --name-only | grep '\.py$' | head -1`. If empty: skip to next priority skill. For `oss:review`: requires PR number — skip (not suitable for demo).

### Snapshot before

```bash
cd "$TARGET"
CLI_LINES_BEFORE=$(wc -l < .cache/codemap/logs/cli.jsonl 2>/dev/null || echo 0)  # timeout: 5000
```

### Run real skill

```bash
Skill(skill="$PICKED_SKILL", args="$PROBE_FILE")
```

> The skill runs normally. Codemap injection fires (or doesn't) as it would in real developer use.

### Snapshot after + compute delta

```bash
cd "$TARGET"
CLI_LINES_AFTER=$(wc -l < .cache/codemap/logs/cli.jsonl 2>/dev/null || echo 0)  # timeout: 5000
SQ_DELTA=$((CLI_LINES_AFTER - CLI_LINES_BEFORE))
```

Parse the new cli.jsonl lines for subcommand breakdown and timing.

### Interpret result

- `SQ_DELTA > 0`: injection live. Record `skill_name`, `probe_file`, `sq_delta`, subcommand breakdown.
- `SQ_DELTA = 0`: injection block present but scan-query never fired. Flag as ⚠ in D8 with diagnostic. Root causes + diagnostic text: demo-notes.md § D5a.

## D5b — Synthetic A/B

Runs in all cases. Labeled by `DEMO_MODE`:
- `real`: "synthetic reference arm — quantifies gain independent of real-skill probe above"
- `synthetic`: "synthetic only — no user skills wired / cloned repo"

Arm prompts (plain / codemap), recall scoring formula, honest caveat printed verbatim in D8, and the benchmark-upgrade offer: demo-notes.md § D5b. Run both arms per `ab_tasks` entry from `templates/demo-tasks.json`.

### Correctness signal

The signal type drives the D8 report-header Confidence cap — it must be reported honestly, never inflated:

- `basename "$TARGET"` = `requests` (matches the pinned psf/requests benchmark set) → `SIGNAL=ground_truth`; score recall vs `task.ground_truth`.
- Otherwise → `SIGNAL=agreement`; compute `cross_arm_agreement` (1.0 both arms give the same answer, else 0.0) and label it **"agreement"**, never "accuracy" — agreement is cross-arm consistency, not correctness.

### Measured per-arm cost

Each arm runs under its own session, so its scan-query / Grep / Read / Glob calls land in that session's telemetry shards. Assign a distinct session id per arm before running it, so the tool-use and cli hooks stamp the arm's records:

```bash
# timeout: 5000
_AB_STAMP=$(date +%s)
PLAIN_SESSION="demo-plain-${_AB_STAMP}"
CODEMAP_SESSION="demo-codemap-${_AB_STAMP}"
_DEMO_PROJ=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$TARGET")
```

Seed the arm's own session id into `${TMPDIR:-/tmp}/codemap-${_DEMO_PROJ}-session` immediately before that arm's `Agent()`/`Skill()` call — `PLAIN_SESSION` before the plain arm, `CODEMAP_SESSION` before the codemap arm (the tool-use + cli hooks read this file to stamp each record with the current session). The arms' self-reported `b`/`g`/`r`/`sq` counts are discarded — cost is read back from telemetry, not from the arm's word.

After both arms finish, derive measured per-arm token totals + the signal-capped confidence with `measure_demo_arms.py` (all JSON/number crunching lives in the bin script — never inline here):

```bash
# timeout: 15000
cd "$TARGET"
AB_MEASURED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/measure_demo_arms.py" \
    --logs .cache/codemap/logs \
    --plain-session "$PLAIN_SESSION" \
    --codemap-session "$CODEMAP_SESSION" \
    --signal "$SIGNAL" --json)
```

`AB_MEASURED` JSON carries `plain.tokens`, `codemap.tokens`, `token_delta`, the effective `signal_type` (downgraded to `plumbing` if either arm produced no telemetry), and the capped `confidence`. Feed `plain.tokens` / `codemap.tokens` into the D8 A/B table and `signal_type` + `confidence` into the D8 report-header Confidence line.

## D6 — Usage report

```bash
# timeout: 30000
# debrief-coding requires YYYY-MM-DD; explicit derivation
_TODAY=$(date +%Y-%m-%d)
Skill(skill="codemap:debrief-coding", args="--since ${_TODAY}${ANONYMIZE_FLAG}")
```

`ANONYMIZE_FLAG` = ` --anonymize` if flag passed, else empty. Run with cwd=`$TARGET` — debrief-coding resolves logs relative to cwd. Capture report path from debrief-coding output.

## D7 — Logging-pipeline diagnostic

```bash
cd "$TARGET"
ls .cache/codemap/logs/cli.jsonl 2>/dev/null     # timeout: 5000
ls .cache/codemap/logs/skills.jsonl 2>/dev/null  # timeout: 5000
wc -l .cache/codemap/logs/skills.jsonl 2>/dev/null  # timeout: 5000
```

Derive:

| Layer | Status | Detail |
| --- | --- | --- |
| cli.jsonl | ✓/✗ | N records |
| skills.jsonl | ✓/⚠/✗ | N records; ⚠ if empty → Sk=0 |
| session correlation | ✓/⚠ | cli + skill share session id? |

`Sk=0` explanation (print when skills.jsonl empty): demo-notes.md § D7.

## D8 — Final demo report

Output path: `--output` if given, else `.reports/codemap/demo-<YYYY-MM-DD>.md`.

```bash
mkdir -p .reports/codemap  # timeout: 5000
```

**Outcome**: `PASS` if scan_query_ok AND smoke_ok AND (SQ_DELTA > 0 OR DEMO_MODE=synthetic). `PASS_WITH_WARNINGS` if any ⚠ (injection present but SQ_DELTA=0, or D2a init-ran-but-nothing-wired). `FAIL` only if scan_query_ok=false (stopped before report) — this section never reached on FAIL.

**Report-header Confidence**: the measured A/B signal sets the ceiling (`confidence` field of `AB_MEASURED`): `ground_truth` → up to 0.9, `agreement` → cap 0.7, `plumbing` (either arm produced no telemetry) → cap 0.5. Then the D5a probe source may only *lower* it — a `synthetic` probe source (no real-skill probe ran) subtracts 0.1, a `priority-list` source is neutral, and a `user-arg` source (operator pinned a wired skill) keeps the ceiling. Never report above the `AB_MEASURED` cap. State the driving signal type and probe source in the header `Confidence` gaps note.

Write report with Write tool using the full report skeleton (YAML header + Plumbing / Index / Sample tasks / Real-skill probe / Synthetic A/B / Telemetry health / Debrief sections): demo-notes.md § D8 report template. Fill placeholders from the values collected in D2–D7; omit the Real-skill probe section when `DEMO_MODE=synthetic`. In the Synthetic A/B table use the measured `plain.tokens` / `codemap.tokens` from `AB_MEASURED` (not any self-reported arm count), and print the `signal_type` label next to the correctness column. Print report path on completion.

## D9 — Cleanup gate

If `CLONED=true` and `--keep-clone` not set:

`AskUserQuestion` — "Demo used cloned repo at `$TARGET`. Delete it?" Options: (a) Keep clone, (b) Delete clone (Recommended).

On (b):
```bash
rm -rf "$SANDBOX"  # timeout: 15000
```
