#!/usr/bin/env node
// log-tool-use.js — PostToolUse(Grep|Read|Glob) hook.
// Appends one line per search/read tool call to `tools_<session>.jsonl` (same
// .cache/codemap/logs/ dir + same session join key as _telemetry.py's cli shard).
// This is the raw grep/read-volume signal codemap's fixes aim to reduce: the
// baseline is captured before Phase 1 lands, and tools.jsonl growth after lets
// debrief-coding show the delta.
//
// Hard budget <5ms: no subprocess, no tool_response read, no JSON parse of tool
// output — only the small stdin envelope is parsed for tool_name + one target
// field (pattern / path / file_path). git-root discovery is cached in a session
// tmpfile written by seed-session.js, so no per-call `git` spawn.
// Fail-open: any error exits 0 so a broken hook never blocks a tool call.
// Opt out: set CODEMAP_LOGGING=false (mirrors _telemetry.py's env gate).

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const LOG_MAX_BYTES = 10 * 1024 * 1024;
const SAFE = /[^A-Za-z0-9_-]/g;

// Search commands run through Bash (rg/grep at a command position). The 2026-07
// usage audit found native Grep/Glob absent from the harness toolset — all grep
// volume flows through Bash, so without this the tools layer only ever sees Read
// and the grep-reduction baseline is unmeasurable.
const BASH_SEARCH = /(^|[|;&(]\s*)(rg|grep|egrep|fgrep)\s/;

// Plugin version stamped into every record as `v` (before/after comparison across
// releases). One small readFileSync per process — well inside the 5ms budget.
function pluginVersion() {
  try {
    const manifest = path.join(__dirname, "..", ".claude-plugin", "plugin.json");
    return String(JSON.parse(fs.readFileSync(manifest, "utf8")).version || "?");
  } catch {
    return "?";
  }
}

// Match _telemetry.py session_id(): read the git-root basename session tmpfile
// seeded once per session by seed-session.js. No git spawn here — that would blow
// the 5ms budget on every tool call. Missing file → "" → unsuffixed tools.jsonl.
function sessionId() {
  const proj = path.basename(process.cwd());
  const sidFile = path.join(os.tmpdir(), `codemap-${proj}-session`);
  try {
    return fs.readFileSync(sidFile, "utf8").trim();
  } catch {
    return "";
  }
}

function logPathFor(session, logDir) {
  const name = session ? `tools_${session.replace(SAFE, "-")}.jsonl` : "tools.jsonl";
  return path.join(logDir, name);
}

function rotate(logFile) {
  for (let i = 2; i >= 1; i--) {
    const src = `${logFile}.${i}`;
    if (fs.existsSync(src)) fs.renameSync(src, `${logFile}.${i + 1}`);
  }
  if (fs.existsSync(logFile)) fs.renameSync(logFile, `${logFile}.1`);
}

// The one target field, by tool: Grep→pattern, Glob→pattern, Read→file_path,
// Bash→command (truncated). `path` (Grep/Glob search root) is secondary; recorded
// only when present so the debrief can attribute greps to a subtree without a
// second field per tool.
function targetFor(toolName, input) {
  if (toolName === "Read") return String(input.file_path || "");
  if (toolName === "Bash") return String(input.command || "").slice(0, 200);
  return String(input.pattern || input.path || "");
}

function main() {
  if (String(process.env.CODEMAP_LOGGING || "true").toLowerCase() === "false") process.exit(0);

  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(0, "utf8"));
  } catch {
    process.exit(0);
  }

  const toolName = String(payload?.tool_name || "");
  if (toolName !== "Grep" && toolName !== "Read" && toolName !== "Glob" && toolName !== "Bash") process.exit(0);

  const input = payload?.tool_input || {};
  if (toolName === "Bash") {
    const cmd = String(input.command || "");
    // Only search-shaped Bash counts toward grep volume; codemap's own CLI is not
    // a manual grep even when its wrapper pipes through grep.
    if (!BASH_SEARCH.test(cmd) || cmd.includes("scan-query")) process.exit(0);
  }
  const record = {
    ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    layer: "tool",
    v: pluginVersion(),
    tool: toolName,
    session: sessionId(),
    target: targetFor(toolName, input),
  };
  // Never touch payload.tool_response — parsing search/read output is the exact
  // cost this hook must not pay (accept criterion + 5ms budget).

  try {
    const logDir = process.env.CODEMAP_LOG_DIR || path.join(".cache", "codemap", "logs");
    const logFile = logPathFor(record.session, logDir);
    fs.mkdirSync(path.dirname(logFile), { recursive: true });
    let size = 0;
    try {
      size = fs.statSync(logFile).size;
    } catch {
      /* new file */
    }
    if (size > LOG_MAX_BYTES) rotate(logFile);
    fs.appendFileSync(logFile, JSON.stringify(record) + "\n");
    maybeNudgeRepeatedRead(record, logFile);
  } catch {
    /* best-effort — telemetry must never break a tool call */
  }
  process.exit(0);
}

// Read-redundancy nudge: the 2026-07 usage audit found single source files Read
// up to 139× per project while structural queries went unused. When the SAME
// non-test .py file hits its 3rd Read in this session, emit one stdout hint
// (PostToolUse stdout reaches the transcript). Fires exactly at count 3 —
// once per file per session, never a stream of nags.
const NUDGE_AT = 3;

function maybeNudgeRepeatedRead(record, logFile) {
  if (record.tool !== "Read" || !record.target.endsWith(".py")) return;
  if (/\/tests?\//.test(record.target)) return;
  let count = 0;
  for (const line of fs.readFileSync(logFile, "utf8").split("\n")) {
    if (line.includes('"Read"') && line.includes(JSON.stringify(record.target))) count++;
  }
  if (count === NUDGE_AT) {
    const base = path.basename(record.target, ".py");
    console.log(
      `[codemap] ${base}.py read ${NUDGE_AT}x this session — structural queries may be cheaper: ` +
        `scan-query symbol --with-imports <name>, rdeps <module>, fn-rdeps <module::fn>`,
    );
  }
}

main();
