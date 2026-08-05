---
name: profile
description: 'Session clock-time analyzer. Reads the foundry plugin''s timings.jsonl and invocations.jsonl logs (written by task-log.js) and produces a per-session and per-skill wall-time breakdown — local-tool work vs subagent spawns vs Skill invocations vs AskUserQuestion idle vs main-loop reasoning residual. Useful for answering "why did /oss:resolve run 30 minutes?" or "what eats clock time in /develop:fix?". Pure log read — no instrumentation, no skill edits, no LLM calls. TRIGGER when: user asks where wall-clock time goes during a skill/session, why a skill is slow, what dominates total runtime, or wants a per-skill rollup over a recent window; phrases: "where does time go", "why so slow", "profile last session", "clock breakdown", "session timing". SKIP: token/cost questions (model field is null in current logs — out of scope); per-line Python perf (use foundry:perf-optimizer); known failure or hang (use /foundry:investigate).'
argument-hint: "[--since 24h|7d|30d] [--session-id ID] [--top-n N]"
allowed-tools: Read, Write, Bash, TaskCreate, TaskUpdate, AskUserQuestion
model: sonnet
effort: low
---

<objective>

Bucket session clock time from existing `~/.claude/logs/{timings,invocations}.jsonl` into:

1. **Local tools** — Bash/Read/Edit/Write/Grep/Glob and other main-process tools
2. **Agent / subagent spawns** — Task/Agent calls (sync + background)
3. **Skill** — `tool=Skill` wall durations
4. **AskUserQuestion idle** — human-wait, separate column, excluded from compute total
5. **Main-loop reasoning (residual)** — session wall minus buckets above

Outputs a markdown report at `.reports/profile/<UTC-timestamp>/report.md` plus a `.temp/output-profile-...md` copy. Includes per-session table, per-skill rollup, and top-N longest single calls.

NOT for: token or cost accounting (model field null in current logs); per-line Python perf (use `foundry:perf-optimizer`); known failure diagnosis (use `/foundry:investigate`).

</objective>

<inputs>

- **`--since DURATION`** (default `24h`) — window: `NNs|NNm|NNh|NNd`
- **`--session-id ID`** — optional; restrict to one session
- **`--top-n N`** (default `5`) — slowest single calls to list

If $ARGUMENTS empty, default window is 24h.

</inputs>

<workflow>

**Task tracking**: TaskCreate two tasks up front — 1 "Run analyzer + render report" (Steps 1–3), 2 "Step 4b: Print report header" (Step 4). Mark each `in_progress` before its first tool call; 1 completed once `report.md` exists, 2 completed right after the header and path are printed, before the executive summary.

## Step 1: Parse args + create run dir

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# timeout: 5000
SINCE="24h"
SESSION_ID=""
TOP_N="5"
for tok in $ARGUMENTS; do
  case "$tok" in
    --since=*)      SINCE="${tok#--since=}" ;;
    --since)        next_is_since=1 ;;
    --session-id=*) SESSION_ID="${tok#--session-id=}" ;;
    --top-n=*)      TOP_N="${tok#--top-n=}" ;;
    *)
      if [ "${next_is_since:-0}" = "1" ]; then SINCE="$tok"; next_is_since=0; fi
      ;;
  esac
done
STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
REPORT_DIR=".reports/profile/$STAMP"
mkdir -p "$REPORT_DIR"
{
  echo "REPORT_DIR=$REPORT_DIR"
  echo "SINCE=$SINCE"
  echo "SESSION_ID=$SESSION_ID"
  echo "TOP_N=$TOP_N"
} | tee "${TMPDIR:-/tmp}/foundry-profile-state-${CSID}"
```

Values persisted to `${TMPDIR:-/tmp}/foundry-profile-state-${CSID}`; Steps 2–3 re-source it (bash state does not persist across Bash calls, and `REPORT_DIR` carries a per-shell timestamp that cannot be re-derived).

## Step 2: Run analyzer

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# timeout: 60000
. "${TMPDIR:-/tmp}/foundry-profile-state-${CSID}" 2>/dev/null   # reload REPORT_DIR/SINCE/SESSION_ID/TOP_N (fresh shell)
OPT_SID=""
[ -n "$SESSION_ID" ] && OPT_SID="--session-id $SESSION_ID"
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_foundry}/bin/timing_analyzer.py" \
    --since "$SINCE" \
    --top-n "$TOP_N" \
    --output "$REPORT_DIR/report.md" \
    $OPT_SID 2>"$REPORT_DIR/warnings.log"
echo "exit=$?"
```

`OPT_SID` left unquoted so empty expands to nothing (no flag). Exit code 1 → no sessions in window — surface that and stop.

## Step 3: Mark run complete

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# timeout: 5000
. "${TMPDIR:-/tmp}/foundry-profile-state-${CSID}" 2>/dev/null   # reload REPORT_DIR/SINCE/SESSION_ID/TOP_N (fresh shell)
echo '{"status":"complete","since":"'"$SINCE"'","session_id":"'"$SESSION_ID"'","top_n":'"$TOP_N"'}' > "$REPORT_DIR/result.jsonl"
```

## Step 4: Emit terminal output

Read YAML header from `$REPORT_DIR/report.md` (first block between `---` lines) and print verbatim. Then print `→ $REPORT_DIR/report.md`. Then read Headline split block plus top 3 sessions from per-session table and surface as executive summary (per quality-gates.md output routing).

Also Write the long-output dump per quality-gates rule:

```text
Write(file_path=".temp/output-profile-<branch>-<YYYY-MM-DD>.md", content=<full report contents>)
```

Where `<branch>` = `$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')`.

Backed structurally by `hooks/enforce-profile-header.js`: while the Step 1 state file is live and `$REPORT_DIR/report.md` is absent, Step 5's `AskUserQuestion` is denied, so the gate can never be reached from an ad-hoc in-context summary.

## Step 5: Follow-up gate

Invoke `AskUserQuestion` (denied by `enforce-profile-header.js` until Step 2 has written `report.md` — if the analyzer found no sessions, report that and stop instead of asking):
- (a) Drill into slowest session — re-run with `--session-id <id>`
- (b) Re-run with different window (`--since 7d`, `--since 30d`)
- (c) Skip — done

</workflow>

<notes>

- **Scope vs `/foundry:investigate`**: investigate diagnoses failures; profile measures wall time when things ran fine but slow.
- **Scope vs `foundry:perf-optimizer`**: perf-optimizer profiles Python/ML code (CPU/GPU/IO); profile measures Claude Code session wall time.
- **No model split**: timings.jsonl `model` field is 100% null in the current task-log.js payload — report does not break down by model tier. Documented in report Confidence Gaps.
- **Subagent internals invisible**: hook fires only in main Claude Code process; subagent internal tool calls do NOT hit timings.jsonl. Agent rows are opaque envelopes — main-loop reasoning bucket underestimates when many subagent spawns dominate.
- **Background agent join**: rows with `duration_ms < 1s` (likely `run_in_background=true`) are matched against invocations.jsonl `started→completed` pairs by `(agent, desc)` substring within ±60s window. Concurrent same-type spawns may mispair.
- **Bash clip**: any `duration_ms > 1h` for `tool=Bash` is clipped at 3,600,000 ms to avoid runaway-shell pollution; clip count surfaced in legend.
- **Read-only**: skill never edits source files. No commits, no pushes.

</notes>
