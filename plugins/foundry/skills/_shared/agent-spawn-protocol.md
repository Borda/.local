# Agent Spawn Protocol — Background Health Monitoring (CLAUDE.md §6)

Reference from any skill that spawns background agents:
`Read $_FOUNDRY_SHARED/agent-spawn-protocol.md — apply §8 monitoring for <skill-name> run`

Replace: `<SKILL>` = skill name (e.g. `calibrate`), `<RUN_DIR>` = run directory variable, `<ID>` = agent identifier suffix.

## §8 Implementation Template

```bash
# §8-1: Launch sentinel — record time and create checkpoint
LAUNCH_AT=$(date +%s)
touch /tmp/<SKILL>-check-<ID>

# Spawn background agent
Agent(subagent_type="...", run_in_background=true, prompt="...", ...)

# §8-2: Poll every 5 min — new files in run dir = alive; zero = stalled
MONITOR_INTERVAL=300
HARD_CUTOFF=900   # 15 min
EXTENSION=300     # one extension allowed
stall_count=0
while true; do
    sleep $MONITOR_INTERVAL
    elapsed=$(( $(date +%s) - LAUNCH_AT ))
    new_files=$(find <RUN_DIR> -newer /tmp/<SKILL>-check-<ID> -type f 2>/dev/null | wc -l)
    touch /tmp/<SKILL>-check-<ID>   # advance checkpoint
    if [ "$new_files" -gt 0 ]; then
        stall_count=0
        [ "$elapsed" -ge "$HARD_CUTOFF" ] && break   # agent finished within hard cutoff
        continue
    fi
    # No new files — potential stall
    stall_count=$(( stall_count + 1 ))
    if [ "$stall_count" -eq 1 ] && [ "$elapsed" -lt $(( HARD_CUTOFF + EXTENSION )) ]; then
        # §8-4: One extension if tail output explains delay
        tail_out=$(tail -20 <RUN_DIR>/output.md 2>/dev/null || echo "")
        [ -n "$tail_out" ] && continue   # activity found — grant extension
    fi
    # §8-3: Hard cutoff reached or second unexplained stall
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

## Rules

- Never omit timed-out signal (⏱) — surface partial results always
- Skills tighten (not loosen) HARD_CUTOFF and MONITOR_INTERVAL in own `<constants>`
- Clean sentinel with `rm -f` on normal and timeout exit (use `trap` for crash safety)
- Canonical reference: CLAUDE.md §6
