# Agent Spawn Protocol — Background Health Monitoring (CLAUDE.md §6)

Reference from any skill that spawns background agents:
`Read $_FOUNDRY_SHARED/agent-spawn-protocol.md — apply §8 monitoring for <skill-name> run`

Replace: `<SKILL>` = skill name (e.g. `calibrate`), `<RUN_DIR>` = run directory variable, `<ID>` = agent identifier suffix.

## §8 Implementation Template

```bash
LAUNCH_AT=$(date +%s)
touch /tmp/<SKILL>-check-<ID>

# Spawn background agent
Agent(subagent_type="...", run_in_background=true, prompt="...", ...)

MONITOR_INTERVAL=300
HARD_CUTOFF=900   # 15 min
EXTENSION=300     # one extension allowed
stall_count=0
while true; do
    sleep $MONITOR_INTERVAL
    elapsed=$(( $(date +%s) - LAUNCH_AT ))
    new_files=$(find <RUN_DIR> -newer /tmp/<SKILL>-check-<ID> -type f 2>/dev/null | wc -l)
    touch /tmp/<SKILL>-check-<ID>
    if [ "$new_files" -gt 0 ]; then
        stall_count=0
        [ "$elapsed" -ge "$HARD_CUTOFF" ] && break
        continue
    fi
    stall_count=$(( stall_count + 1 ))
    if [ "$stall_count" -eq 1 ] && [ "$elapsed" -lt $(( HARD_CUTOFF + EXTENSION )) ]; then
        # one extension if tail output explains delay
        tail_out=$(tail -20 <RUN_DIR>/output.md 2>/dev/null || echo "")
        [ -n "$tail_out" ] && continue
    fi
    printf "⏱ Agent <ID> timed out after %ds — reading partial results\n" "$elapsed"
    partial=$(tail -100 <RUN_DIR>/output.md 2>/dev/null || echo "")
    if [ -z "$partial" ]; then
        echo '{"verdict":"timed_out"}' > <RUN_DIR>/result.jsonl
    fi
    break
done
rm -f /tmp/<SKILL>-check-<ID>
```

## Constants to declare in `<constants>` block

```
MONITOR_INTERVAL = 300   (5 min poll; skills may tighten, not loosen)
HARD_CUTOFF      = 900   (15 min hard limit; skills may tighten)
EXTENSION        = 300   (one +5 min extension allowed)
```

## §8b health_sentinel.py spawn boilerplate (preferred)

Skills that spawn one or more background agents use the `health_sentinel.py` helper rather than the raw `touch`/`find` template above — it validates the run dir and emits a quoted sentinel path. Paste this immediately after each `Agent(... run_in_background=true ...)` spawn, substituting `<ID>` (unique per spawn) and the find glob for that agent's output files:

```bash
MONITOR_INTERVAL=300; HARD_CUTOFF=900; EXTENSION=300   # see <constants> block
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/health_sentinel.py" start <SKILL>-<ID> 2>/dev/null)"  # timeout: 5000
[ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
# Persist SENTINEL and LAUNCH_AT across Bash() call boundaries — shell state does not persist
echo "${SENTINEL:-}" > "${TMPDIR:-/tmp}/<SKILL>-<ID>-sentinel"
echo "${LAUNCH_AT:-}" > "${TMPDIR:-/tmp}/<SKILL>-<ID>-launch-at"
```

Poll per `$MONITOR_INTERVAL`: re-read `SENTINEL=$(cat "${TMPDIR:-/tmp}/<SKILL>-<ID>-sentinel" 2>/dev/null)`, then `find <output-dir> -newer "$SENTINEL" -name "<glob>" | wc -l` — new files = alive; zero for `$HARD_CUTOFF` seconds = stalled. On timeout: read partial output, surface with ⏱.

## Rules

- Never omit timed-out signal (⏱) — surface partial results always
- Skills tighten (not loosen) HARD_CUTOFF and MONITOR_INTERVAL in own `<constants>`
- Clean sentinel with `rm -f` on normal and timeout exit (use `trap` for crash safety)
- Canonical reference: CLAUDE.md §6
