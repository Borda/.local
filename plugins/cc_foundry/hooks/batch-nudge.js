#!/usr/bin/env node
// batch-nudge.js — parallel-tool-call batching nudge
//
// PURPOSE
//   Detects a streak of independent, batchable tool calls issued one at a time
//   with model-reasoning-sized gaps between them (evidence they arrived as
//   separate turns, not a parallel dispatch from one message) and surfaces a
//   one-line reminder to batch independent calls — the rule stated in
//   CLAUDE.md §Using your tools but never previously enforced (measured gap:
//   plugins/CLAUDE.md 749 solo Bash calls across logged sessions, restated in
//   prose only). Informational only — never blocks a tool call.
//
// HEURISTIC (see plugins/.plans/active/todo_agent-cost-model-and-fanout-design.md
// item 4 for the empirical basis)
//   Two Read calls issued in the SAME assistant message (genuinely parallel
//   dispatch) landed ~300ms apart in PostToolUse timestamps — far under a model
//   round-trip (multi-second: read result, reason, decide next call). So: track
//   the gap between this batchable call's PreToolUse and the previous batchable
//   call's PreToolUse. Small gap (<GAP_MS) → likely same-message dispatch →
//   reset streak. Large gap (>=GAP_MS) → a separate decision → increment streak.
//   A non-batchable tool (Edit/Write/Agent/...) in between usually means a real
//   dependency break (e.g. Read → Edit), not a missed-batch opportunity →
//   resets the streak rather than counting it.
//
// WHY POSTTOOLUSE, NOT PRETOOLUSE, FOR THE NUDGE
//   PreToolUse exit 2 DENIES the call — the model would retry the identical
//   single call and deny again (infinite loop). PostToolUse exit 2 fires after
//   the tool already ran: stderr is surfaced to Claude as feedback without
//   blocking anything. Verified against the hooks reference before building
//   (code.claude.com/docs/en/hooks.md#exit-code-2-behavior-per-event).
//
// STATE
//   /tmp/claude-state-<session_id>/batch/last.json           — {tool, ts} of the
//     most recent batchable PreToolUse (whichever fired last)
//   /tmp/claude-state-<session_id>/batch/streak.json         — {count}
//   /tmp/claude-state-<session_id>/batch/pending/<id>.json   — marker written at
//     PreToolUse when streak crosses NUDGE_THRESHOLD; consumed by this call's
//     own PostToolUse to emit the stderr nudge, then the streak resets (cooldown
//     — one nudge per streak, not one per call once past threshold).
//
// EXIT CODES
//   0  always on PreToolUse (never blocks) and on PostToolUse when no nudge due
//   2  PostToolUse only, when this call's PreToolUse marked it as the one that
//      crossed NUDGE_THRESHOLD — stderr carries the reminder

const fs = require("fs");
const os = require("os");
const path = require("path");

const GAP_MS = 1500; // below this, two batchable calls are treated as one dispatch
const NUDGE_THRESHOLD = 4; // consecutive sequential-decision batchable calls before nudging

function getSentinelDir() {
  return process.platform === "win32" ? os.tmpdir() : "/tmp";
}

// Batchable tool types — independent, read-only, safe to fire in parallel.
const BATCHABLE_TOOLS = new Set(["Read", "Grep", "Glob"]);
// Read-only Bash first-tokens worth tracking (mirrors sentinel-read-allow.js SAFE_TOKENS,
// narrowed to commands that are near-certainly independent of each other's output).
const READONLY_BASH_PREFIXES = new Set(["git", "ls", "find", "grep", "cat", "head", "tail", "wc"]);

function isBatchable(toolName, toolInput) {
  if (BATCHABLE_TOOLS.has(toolName)) return true;
  if (toolName !== "Bash") return false;
  const cmd = ((toolInput && toolInput.command) || "").trim();
  if (!cmd) return false;
  // Only judge the first segment — a compound command (&&, ;, |) may write, so skip it entirely
  // rather than risk misclassifying a mutating command as batchable.
  if (/[;&|]/.test(cmd)) return false;
  const first = cmd.match(/^\S+/);
  return !!first && READONLY_BASH_PREFIXES.has(first[0]);
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);
    const { hook_event_name, tool_name, tool_input, session_id, tool_use_id } = data;
    const sid = (session_id || "default").replace(/[^a-zA-Z0-9_-]/g, "_");
    const tmpDir = path.join(getSentinelDir(), `claude-state-${sid}`, "batch");
    const pendingDir = path.join(tmpDir, "pending");
    const lastFile = path.join(tmpDir, "last.json");
    const streakFile = path.join(tmpDir, "streak.json");

    if (hook_event_name === "UserPromptSubmit") {
      // New user turn — a fresh streak boundary regardless of what came before.
      try {
        fs.mkdirSync(tmpDir, { recursive: true });
        fs.writeFileSync(streakFile, JSON.stringify({ count: 0 }));
      } catch (_) {}
      process.exit(0);
    }

    if (hook_event_name === "PreToolUse") {
      const batchable = isBatchable(tool_name, tool_input);
      let streak = 0;
      try {
        streak = JSON.parse(fs.readFileSync(streakFile, "utf8")).count || 0;
      } catch (_) {}

      if (!batchable) {
        // Non-batchable tool in the middle of a run usually means a real dependency
        // (e.g. Read result feeding an Edit) — not a missed-batch opportunity.
        try {
          fs.mkdirSync(tmpDir, { recursive: true });
          fs.writeFileSync(streakFile, JSON.stringify({ count: 0 }));
        } catch (_) {}
        process.exit(0);
      }

      let gap = Infinity;
      try {
        const last = JSON.parse(fs.readFileSync(lastFile, "utf8"));
        gap = Date.now() - last.ts;
      } catch (_) {} // no prior record — first batchable call this run, no judgment yet

      const newStreak = gap < GAP_MS ? 0 : streak + 1;
      try {
        fs.mkdirSync(tmpDir, { recursive: true });
        fs.writeFileSync(lastFile, JSON.stringify({ tool: tool_name, ts: Date.now() }));
        fs.writeFileSync(streakFile, JSON.stringify({ count: newStreak >= NUDGE_THRESHOLD ? 0 : newStreak }));
      } catch (_) {}

      if (newStreak >= NUDGE_THRESHOLD && tool_use_id) {
        try {
          fs.mkdirSync(pendingDir, { recursive: true });
          fs.writeFileSync(path.join(pendingDir, `${tool_use_id}.json`), JSON.stringify({ streak: newStreak }));
        } catch (_) {}
      }
      process.exit(0);
    }

    if (hook_event_name === "PostToolUse" && tool_use_id) {
      const markerFile = path.join(pendingDir, `${tool_use_id}.json`);
      let marker = null;
      try {
        marker = JSON.parse(fs.readFileSync(markerFile, "utf8"));
        fs.unlinkSync(markerFile);
      } catch (_) {}
      if (marker) {
        process.stderr.write(
          `Batching reminder: ${marker.streak} independent ${tool_name}-class calls issued one at a time ` +
            `(>${GAP_MS}ms apart each). If upcoming calls don't depend on each other's output, put them in ` +
            "the same response as parallel tool_use blocks — see CLAUDE.md §Using your tools.",
        );
        process.exit(2);
      }
      process.exit(0);
    }

    process.exit(0);
  } catch (_) {
    // Never crash or block Claude due to a hook bug.
    process.exit(0);
  }
});
