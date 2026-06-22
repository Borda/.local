# Demo mode — end-to-end validation

Validates codemap plugged in correctly and yields expected gains.
State variable `DEMO_MODE` (real | synthetic) drives D5a/D5b path selection.

**Full flow**: plumbing → integration gate → index ensure → sample tasks → real-skill probe (if wired) → synthetic A/B → telemetry diagnostic → final report.

## D0 — Parse args

Parse `$ARGUMENTS` for these flags (all optional):

- `--repo <path|url>` — target repo; path = use as-is; URL = trigger D1a clone gate
- `--public` — force D1a clone gate even if current repo has `.py` files
- `--anonymize` — forward to `debrief-coding` in D6; safe-to-share report
- `--keep-clone` — skip D9 cleanup prompt
- `--output <path>` — override report path in D8

Leave `CODEMAP_LOGGING=true` (default). Each bash block that needs to operate in `$TARGET` must use a separate `cd "$TARGET"` call first — never chain as `cd "$TARGET" && command` in a single bash block (violates CLAUDE.md compound-bash rule; permission matcher only checks first token).

Set `TARGET` from `--repo` value (path case) or after D1a clone. Resolve `SQ` via `bin/locate_scan_query.py`. Initialize `CLONED=false`, `DEMO_MODE=synthetic`.

## D1 — Resolve target

```bash
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py")  # timeout: 5000
```

Decision:
- `--repo <path>` given → `TARGET="<path>"`. Skip to D2.
- `--repo <url>` given → set `CLONE_URL`; go to D1a.
- `--public` flag set → go to D1a.
- `find . -maxdepth 3 -name "*.py" | head -1` finds a file → `TARGET=$(git rev-parse --show-toplevel)`. Skip to D2.
- Otherwise → go to D1a.

## D1a — Clone gate (mandatory `AskUserQuestion`)

> Must invoke `AskUserQuestion` — never clone without explicit confirmation.

Ask: "No local Python repo detected. Which public repo to clone for the demo?"

Options:
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

Set `CLONED=true`. Cloned repos have no user skills installed → `DEMO_MODE` stays `synthetic`; skip D2a integration gate.

## D2 — Plumbing check (C1–C5 inline)

Run bin scripts inline — demo controls cwd and parses C4 JSON directly. First resolve the index path so freshness and smoke scripts receive `--index-path`.

```bash
# timeout: 5000
_DEMO_PROJ=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$TARGET")
SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py")
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" \
    --output-prefix "codemap-demo-${_DEMO_PROJ}" 2>/dev/null
_DEMO_INDEX=$(cat "${TMPDIR:-/tmp}/codemap-demo-${_DEMO_PROJ}-resolve-index" 2>/dev/null || echo "")
```

```bash
# timeout: 5000
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_freshness.py" \
    "${_DEMO_INDEX}"
```

```bash
# timeout: 15000
C4_JSON=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_index_smoke.py" \
    --index-path "${_DEMO_INDEX}" 2>&1)
```

```bash
# timeout: 10000
C5_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" 2>&1)
```

Derive from outputs:

| Check | OK signal | Derived boolean |
| --- | --- | --- |
| C1 scan-query | exit 0 + non-empty `$SQ` | `scan_query_ok` |
| C2 index path | exit 0 | `index_path_ok` |
| C3 freshness | exit 0 | `index_fresh` |
| C4 smoke | `"ok": true` in JSON | `smoke_ok`; extract `stale`, `age_hours`, `error` |
| C5 injection | exit 0 | `injection_present`; parse stdout for list of wired file paths → `WIRED_FILES[]` |

Parsing `WIRED_FILES[]` from C5 stdout — collect every line matching a `.md` path that contains the injection marker:

```bash
WIRED_FILES=$(echo "$C5_OUT" | grep -E '\.(md)' | grep -v "missing\|not found\|✗")
```

Build plumbing summary table (printed in D8):

| Check | Status | Detail |
| --- | --- | --- |
| scan-query | ✓/✗ | path |
| index | ✓/⚠/✗ | path or "missing" |
| freshness | ✓/⚠ | age_hours |
| smoke | ✓/✗ | error if any |
| injection | ✓/⚠/✗ | N files wired / "none" |

If `scan_query_ok=false`: print remediation hint (`claude plugin install codemap@borda-ai-rig`) and stop.

## D2a — Integration gate

Skip this step if `CLONED=true` — cloned repos have no user skills.

Branch on `injection_present`:

**`injection_present=true`**: set `DEMO_MODE=real`. Continue to D3.

**`injection_present=false`**: invoke `AskUserQuestion`:

"Codemap not wired into any installed skills yet. The demo can run `init` now to wire it in, or proceed with a synthetic A/B only."

Options:
- (a) Run `init` now — wire codemap then validate (Recommended)
- (b) Synthetic A/B only — skip real-skill probe, label results accordingly
- (c) Cancel

On (a): `Skill(skill="codemap:integration", args="init")`. After init, re-run C5:

```bash
cd "$TARGET"
C5_OUT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/check_injection.py" 2>&1)  # timeout: 10000
```

Re-derive `injection_present` and `WIRED_FILES[]`. If `injection_present=true` → `DEMO_MODE=real`. If still false → `DEMO_MODE=synthetic`; record "init ran but no files were wired" as a finding.

On (b): `DEMO_MODE=synthetic`. Continue.
On (c): stop.

## D3 — Ensure index

If `smoke_ok=false` or index missing:

```bash
Skill(skill="codemap:scan-codebase")
```

Re-run C3+C4 to verify. Record `module_count`, `degraded_count` from C4 JSON.

If still failing after build: warn, continue (A/B degrades gracefully — arms fall back to grep).

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

**Run only when `DEMO_MODE=real` and `CLONED=false`.**

Goal: prove codemap injection fires inside the user's actual installed skill — not a synthetic agent.

### Pick skill

Map `WIRED_FILES[]` paths to installed skill names. Extract plugin and skill name from path pattern:

- `…/plugins/<plugin>/skills/<skill>/SKILL.md` → `<plugin>:<skill>`
- `…/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/<skill>/SKILL.md` → `<plugin>:<skill>`

Priority order for selection: `develop:fix` > `develop:refactor` > `develop:review` > `oss:review` > `develop:feature`. Pick first match found in `WIRED_FILES[]` resolved names.

If no matching priority skill found in wired list: log warning, skip D5a, run D5b only.

### Pick task target

For `develop:fix` / `develop:refactor`:

```bash
# timeout: 5000
_CM_PROJ=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null || basename "$TARGET")
# prefer recently modified .py file (more likely to have real issues)
# grep only on lines that look like file paths (contain a slash or end in .py) to avoid matching commit subjects
PROBE_FILE=$(git -C "$TARGET" log --oneline -30 --diff-filter=M --name-only -- '*.py' 2>/dev/null | grep -E '^[^[:space:]]+\.py$' | head -1)
# fallback: most central module path from index via scan-query central
[ -z "$PROBE_FILE" ] && PROBE_FILE=$("$SQ" --timeout 5 central --top 1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); mods=d.get('central',[]); print(mods[0].get('path','') if mods else '')" 2>/dev/null || echo "")
```

For `develop:review`: use `git diff HEAD~1 --name-only | grep '\.py$' | head -1`. If empty: skip to next priority skill.

For `oss:review`: requires PR number — skip (not suitable for demo).

### Snapshot before

```bash
cd "$TARGET"
CLI_LINES_BEFORE=$(wc -l < .cache/codemap/logs/cli.jsonl 2>/dev/null || echo 0)  # timeout: 5000
```

### Run real skill

```bash
Skill(skill="<PICKED_SKILL>", args="$PROBE_FILE")
```

> The skill runs normally. Codemap injection fires (or doesn't) as it would in real developer use.

### Snapshot after + compute delta

```bash
cd "$TARGET"
CLI_LINES_AFTER=$(wc -l < .cache/codemap/logs/cli.jsonl 2>/dev/null || echo 0)  # timeout: 5000
SQ_DELTA=$((CLI_LINES_AFTER - CLI_LINES_BEFORE))
```

Parse the new cli.jsonl lines to get subcommand breakdown and timing.

### Interpret result

- `SQ_DELTA > 0`: injection live. Record `skill_name`, `probe_file`, `sq_delta`, subcommand breakdown.
- `SQ_DELTA = 0`: injection block present but scan-query never fired. Root causes:
  - Binary not on PATH inside skill's bash context
  - Index guard `[ -f ".cache/codemap/${PROJ}.json" ]` failing (wrong PROJ name or CODEMAP_INDEX_DIR set)
  - Skill's injection block inside a branch never taken for this target

  Flag as ⚠ in D8 report. Print diagnostic: "Injection block present but SQ_DELTA=0. Check: `command -v scan-query` inside skill context; verify index path matches `resolve_index_env.py` output."

## D5b — Synthetic A/B

Runs in all cases. Labeled by `DEMO_MODE`:
- `real`: "synthetic reference arm — quantifies gain independent of real-skill probe above"
- `synthetic`: "synthetic only — no user skills wired / cloned repo"

> **Honest caveat** (printed verbatim in D8):
> "Agent tool returns only final text — no per-arm token usage. Arms gated by prompt only (not hard tool deny-list). Self-reported tool-call counts (B/G/R/SQ) used as cost proxy. Recall scored against ground truth for psf/requests pinned task set only; other repos use tool-count proxy + cross-arm agreement."

For each `ab_tasks` entry from `templates/demo-tasks.json`:

**Plain arm** — no codemap:
```
Repo at <TARGET>. CONSTRAINT: do NOT use scan-query, scan_query, or any codemap tool. Use only Bash(grep ...), Read, Glob.
Question: <task.question>
Return ONLY compact JSON: {"answer": "<answer>", "b": <Bash_calls>, "g": <Glob_calls>, "r": <Read_calls>, "sq": 0}
```

**Codemap arm** — scan-query encouraged:
```
Repo at <TARGET>. scan-query available at <SQ> — use it, it is faster than grep.
Question: <task.question>
Return ONLY compact JSON: {"answer": "<answer>", "b": <Bash_calls>, "g": <Glob_calls>, "r": <Read_calls>, "sq": <scan_query_calls>}
```

Score recall vs `task.ground_truth` where available:

```
recall = hits_in_answer / len(ground_truth)
```

`hits_in_answer` = count of `ground_truth` items appearing verbatim in the answer string.

No ground truth (own repo or non-requests clone): `cross_arm_agreement` = 1.0 if both arms give same answer, else 0.0. Label clearly.

**Benchmark upgrade offer** (only if file present):

```bash
ls benchmarks/run-codemap-bench.py 2>/dev/null  # timeout: 5000
```

If present: `AskUserQuestion` — "Rigorous token-measured benchmark available." Options: (a) Skip (Recommended), (b) Run benchmark (slower). On (b): print command, delegate to user.

## D6 — Usage report

```bash
# timeout: 30000
# debrief-coding only accepts YYYY-MM-DD format — derive today's date explicitly
_TODAY=$(date +%Y-%m-%d)
Skill(skill="codemap:debrief-coding", args="--since ${_TODAY}${ANONYMIZE_FLAG}")
```

`ANONYMIZE_FLAG` = ` --anonymize` if flag was passed, else empty. Run with cwd=`$TARGET` — debrief-coding resolves logs relative to cwd.

Capture report path from debrief-coding output.

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

**Sk=0 explanation** (print when skills.jsonl empty):
> "skills.jsonl empty. Expected when tasks run via scan-query binary directly — PreToolUse hook fires only on explicit `/codemap:*` Skill() calls. D4 seeded one entry; if missing, check hook registration: `claude hooks list`."

## D8 — Final demo report

Output path: `--output` if given, else `.reports/codemap/demo-<YYYY-MM-DD>.md`.

```bash
mkdir -p .reports/codemap  # timeout: 5000
```

**Outcome**: `PASS` if scan_query_ok AND smoke_ok AND (SQ_DELTA > 0 OR DEMO_MODE=synthetic). `PASS_WITH_WARNINGS` if any ⚠ (injection present but SQ_DELTA=0, or D2a init-ran-but-nothing-wired). `FAIL` only if scan_query_ok=false (stopped before report) — this section never reached on FAIL.

Write report with Write tool:

```markdown
---
Title:      Codemap Integration Demo — <date>
Date:       <YYYY-MM-DD>
Scope:      <TARGET> — <own-repo | psf/requests | other-clone>
Focus:      end-to-end validation (plumbing + real-skill probe + synthetic A/B + telemetry)
Agents:     integration/demo
Outcome:    PASS | PASS_WITH_WARNINGS
Demo mode:  real (user skills wired) | synthetic (no integration / cloned repo)
Confidence: 0.N — <key gaps>
Next steps: /codemap:debrief-coding --since today
Path:       → .reports/codemap/demo-<YYYY-MM-DD>.md
---

# Codemap Integration Demo — <date>

**Target**: <TARGET>  **Mode**: <demo_mode>

## Plumbing

<plumbing table from D2>

## Index

Modules: <module_count>  Degraded: <degraded_count>  Built in demo: <yes/no>

## Sample tasks

| task_id | cmd | timing_ms | result_count | exhaustive |
| --- | --- | --- | --- | --- |
| ...     | ... | ...       | ...          | ...        |

## Real-skill probe

*(Omit section if DEMO_MODE=synthetic.)*

Skill: `<skill_name>`  Target: `<probe_file>`

scan-query calls fired: **<SQ_DELTA>**  Status: ✓ live | ⚠ SQ_DELTA=0

<⚠ diagnostic text if SQ_DELTA=0>

Subcommands in delta: <breakdown from new cli.jsonl lines>

## Synthetic A/B

*<label: "synthetic reference arm" | "synthetic only — no integration wired">*

| task_id | plain_recall | codemap_recall | plain_tools (B+G+R) | codemap_tools (B+G+R) | codemap_sq |
| --- | --- | --- | --- | --- | --- |
| ...     | ...          | ...            | ...                 | ...                   | ...        |
| **avg** | ...          | ...            | ...                 | ...                   | ...        |

> **Caveat**: prompt-gated arms, tool-count cost proxy. <ground-truth note or cross-arm agreement note>

## Telemetry health

<telemetry table from D7>

<Sk=0 explanation if applicable>

## Debrief report

→ <debrief report path from D6>
```

Print report path on completion.

## D9 — Cleanup gate

If `CLONED=true` and `--keep-clone` not set:

`AskUserQuestion` — "Demo used cloned repo at `$TARGET`. Delete it?"
Options: (a) Keep clone, (b) Delete clone (Recommended).

On (b):
```bash
rm -rf "$SANDBOX"  # timeout: 15000
```

## Scenarios

1. **Fresh repo, no index** → D3 builds; index stats in report.
2. **Stale index** → D2 flags stale `age_hours`; D3 refreshes.
3. **Not wired → init offered (D2a)** → user accepts → init runs → injection present → DEMO_MODE=real → D5a real-skill probe runs.
4. **Not wired → synthetic only (D2a)** → DEMO_MODE=synthetic → D5a skipped → D5b synthetic A/B labelled accordingly.
5. **Wired but SQ_DELTA=0** → D5a flags injection-present-but-not-firing with diagnostic; PASS_WITH_WARNINGS.
6. **Skills never invoked (Sk=0)** → D7 flags; explained as expected artifact.
7. **Public-repo demo** → D1a gate → CLONED=true → DEMO_MODE=synthetic (no user skills in clone) → full synthetic A/B with recall scoring → D9 cleanup.
8. **Anonymized report** → `--anonymize` forwarded to debrief-coding; output safe to share.
