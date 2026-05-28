<!-- file: team.md — consumers: topic/SKILL.md -->

## Team Mode (`--team`)

Use when topic warrants exploring multiple competing method families with adversarial cross-evaluation.

Trigger when: 3+ distinct method families exist AND field has no clear leading method (benchmark spread \<5% between top methods, or no SOTA consensus past 12 months). Skip for topics with clear dominant approach — default single researcher sufficient.

**Workflow:**

1. Lead completes Step 1 (codebase context) as normal
2. Spawn 2–3 **researcher** teammates, each assigned distinct method cluster
3. Broadcast constraints to all: `broadcast {topic: <topic>, constraints: <framework/compute/dataset from Step 1>}`
4. Each teammate researches independently, reports with `deltaT# HOOK:verify` (AgentSpeak v2 completion signal — see TEAM_PROTOCOL.md) and compressed comparison table
5. Lead routes key findings from one researcher to others for cross-challenge: `@AR2: AR1 found [finding] — does it hold under [condition]?`
6. Lead synthesizes into Step 3 report, noting where researchers agreed or diverged

**Note on CLAUDE.md §6 (background agent monitoring)**: Team mode spawns in-process teammates via TeamCreate — not background agents writing to run directory. In-process teammates send TeammateIdle notifications on completion — synchronous completion signals. File-activity polling protocol (§8) doesn't apply; TeammateIdle is equivalent liveness signal.

Pre-compute before spawning:

```bash
TEAM_PROTOCOL_PATH="$HOME/.claude/TEAM_PROTOCOL.md"
```

**Spawn prompt template:**

```markdown
# Substitute pre-computed values — do not pass raw $(date) expressions or shell vars into spawn prompts
You are an researcher teammate researching: [topic].
Read ~/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
Your cluster: [method family N] (e.g., "attention-free architectures" vs "linear attention variants").
Research the top 3 methods in your cluster: comparison table + recommendation given constraints.
Write your full findings (comparison table, analysis, Confidence block) to `.temp/output-research-<teammate-name>-<SPAWN_BRANCH>-<SPAWN_DATE>.md` (substitute pre-computed values from bash block below) using the Write tool.
Report completion with deltaT# HOOK:verify and include: papers=N recommendation="<method>" confidence=0.N file=.temp/output-research-<teammate-name>-<date>.md
Compact Instructions: preserve paper titles, benchmarks, code links. Discard protocol handshakes.
Task tracking: call TaskUpdate(in_progress) when you start your assigned task; call TaskUpdate(completed) when done, before sending your delta message.
```

Lead synthesizes by reading teammate file paths from delta messages. Pre-compute:
```bash
SPAWN_BRANCH="$(git branch --show-current 2>/dev/null | tr "/" "-" || echo "main")"  # timeout: 3000
SPAWN_DATE="$(date -u +%Y-%m-%d)"  # timeout: 3000
# Anti-overwrite per teammate: resolve counter-suffix before each spawn
# For teammate N with name TNAME: _TOUT=".temp/output-research-$TNAME-$SPAWN_BRANCH-$SPAWN_DATE.md"; _TN=2; while [ -e "$_TOUT" ]; do _TOUT=".temp/output-research-$TNAME-$SPAWN_BRANCH-$SPAWN_DATE-$_TN.md"; _TN=$((_TN+1)); done  # timeout: 5000
# Substitute resolved path (not template) into each teammate spawn prompt
mkdir -p .temp  # timeout: 3000
```
For 3 teammates, spawn consolidator researcher agent: "Read the research files at [paths from deltas]. Synthesize into the Step 3 unified report structure. Write to `.reports/research/topic-<SPAWN_BRANCH>-<SPAWN_DATE>.md` (substitute pre-computed values from bash block above). Return ONLY compact JSON: `{"status":"done","papers":N,"best_method":"<name>","confidence":0.N,"file":"<path>"}`"
