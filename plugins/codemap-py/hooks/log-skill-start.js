#!/usr/bin/env node
// log-skill-start.js — PreToolUse hook: log codemap-py:* skill invocations.
// Fires before every Skill() tool call; ignores non-codemap-py skills.
// Writes skill_start event to .cache/codemap/logs/skills.jsonl.
// Also writes session ID to a per-project tmpfile so scan-query wrapper can join records.

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

function isoNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function main() {
  let input;
  try {
    const raw = fs.readFileSync(0, "utf8");
    input = JSON.parse(raw);
  } catch {
    process.exit(0);
  }

  const { tool_name, tool_input, session_id: hookSession } = input;
  if (tool_name !== "Skill") process.exit(0);

  const skill = String((tool_input || {}).skill || "");
  if (!skill.startsWith("codemap-py:")) process.exit(0);

  const cwd = process.cwd();
  const proj = path.basename(cwd);
  const logDir = path.join(cwd, ".cache", "codemap", "logs");
  const sidFile = path.join(os.tmpdir(), `codemap-${proj}-session`);

  // Reuse session ID from tmpfile (normally seeded by seed-session.js at
  // SessionStart); generate one only if the hook never ran (e.g. plugin
  // installed mid-session).
  let sid = "";
  try {
    sid = fs.readFileSync(sidFile, "utf8").trim();
  } catch {
    /* absent */
  }
  if (!sid) {
    sid = crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString("hex");
    try {
      fs.writeFileSync(sidFile, sid, { flag: "w" });
    } catch {
      /* best-effort */
    }
  }

  // Per-session filename mirrors the CLI layer (_telemetry.py); keeps concurrent
  // sessions from interleaving appends. Falls back to skills.jsonl when sid empty.
  const safeSid = sid.replace(/[^A-Za-z0-9_-]/g, "-");
  const logFile = path.join(logDir, safeSid ? `skills_${safeSid}.jsonl` : "skills.jsonl");

  const intent = String((tool_input || {}).args || "").slice(0, 300);

  const record = {
    ts: isoNow(),
    layer: "skill",
    session: sid,
    skill,
    event: "start",
    intent,
    hook_session: hookSession || "",
  };

  try {
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(logFile, JSON.stringify(record) + "\n");
  } catch {
    /* never block the tool call */
  }

  process.exit(0);
}

main();
