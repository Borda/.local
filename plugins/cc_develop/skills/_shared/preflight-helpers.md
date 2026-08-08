# Preflight Helpers

Shared preflight protocols for develop skills. Read + run relevant section(s) based on active flags.

## Codemap + Semble Preflight

Run when `SEMBLE_ENABLED=true`. Codemap availability already validated by `codemap_resolve.py` in flag-parsing phase — no additional check needed when `CODEMAP_ENABLED=true`.

**If `CODEMAP_ENABLED=true`**: no-op — `codemap_resolve.py` confirmed `codemap-py query` on PATH and index present before setting `CODEMAP_ENABLED=true`.

**If `SEMBLE_ENABLED=true`**: verify `mcp__semble__search` in available tools. If not: print `! --semble requested but semble MCP server not configured. Configure: claude mcp add semble -s user -- uvx --from "semble[mcp]" semble` and stop.

## --plan Path Extraction

Run when skill accepts `--plan <path>` flag. Sets `$PLAN_FILE`.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLAN_FILE=""
if [[ "$ARGUMENTS" =~ --plan[[:space:]]+([^[:space:]]+) ]]; then
  PLAN_FILE="${BASH_REMATCH[1]}"
elif [[ "$ARGUMENTS" =~ --plan=([^[:space:]]+) ]]; then
  PLAN_FILE="${BASH_REMATCH[1]}"
fi
if [ -n "$PLAN_FILE" ] && [ ! -f "$PLAN_FILE" ]; then
  echo "! BREAKING — plan file not found: $PLAN_FILE"
  echo "Fix: pass an existing plan path via --plan <path> or --plan=<path>"
  exit 1
fi
# persist so later cross-Bash-call reads (compaction-contract boundaries in feature/fix/refactor) resolve it — shell var is lost between Bash() calls
echo "$PLAN_FILE" > "${TMPDIR:-/tmp}/dev-plan-file-${CSID}"
```

## Team Spawn Template

Spawn prompt template for foundry:sw-engineer teammate spawns. Replace `[ROLE_PHRASE]` and `[FILE_SLUG]` with skill-specific values before inserting.

- debug: `[ROLE_PHRASE]` = `[symptom]`, `[FILE_SLUG]` = `debug-hypothesis`
- feature: `[ROLE_PHRASE]` = `[feature description]`, `[FILE_SLUG]` = `feature`
- fix: `[ROLE_PHRASE]` = `[bug description]`, `[FILE_SLUG]` = `fix-hypothesis`
- refactor: `[ROLE_PHRASE]` = `[refactor goal]`, `[FILE_SLUG]` = `refactor`

```
You are a foundry:sw-engineer teammate working on: [ROLE_PHRASE].
Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
Your hypothesis: [hypothesis N]. Investigate ONLY this root cause.
Report findings to @lead using deltaT# or epsilonT# codes.
Compact Instructions: preserve file paths, errors, line numbers. Discard verbose tool output.
Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal your completion in your final delta message: "Status: complete | blocked — <reason>".
Write your full analysis to .temp/develop/[timestamp]/[FILE_SLUG]-[N]-[timestamp].md using the Write tool (use the run-dir timestamp provided in your spawn context, not a new timestamp). Return ONLY compact JSON: {"status":"done","file":"<path>","findings":N,"confidence":0.N,"summary":"<one-line description of what found/done>"}.
```
