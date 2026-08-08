// report-header-table.js — shared helper for the six `enforce-*-header.js`
// hooks (oss:review/analyse, develop:review, foundry:audit/profile,
// research:topic).
//
// PURPOSE
//   Each sibling hook already denies `AskUserQuestion` while the skill's
//   report file is missing (Step N: consolidate). None of them checked
//   whether the printed reply actually rendered the report's `---` header as
//   the two-column Markdown table `quality-gates.md` §Report File Format
//   mandates ("Universal terminal-print rule") — that mandate is prose-only.
//   A real run (oss:review, PR #1303) skipped the table and printed the raw
//   `---` fields verbatim; the file-existence gate had nothing to catch it.
//   This module gives every sibling hook a second, additive check: when the
//   report file exists but no table appears in the assistant's own text since
//   the last human turn, nudge instead of block (see NOT A DENY GATE below).
//
// HOW IT WORKS
//   1. `assistantTextSinceLastUserTurn(transcriptPath)` tail-reads the
//      session's JSONL transcript (same bounded-read technique as
//      `task-log.js`'s PreCompact branch — last ~200 KB, not the whole file),
//      walks backward from the end to the most recent **human** `user` row,
//      and concatenates every `assistant` row's `text` content blocks from
//      that point forward, skipping `isSidechain` rows (subagent output).
//      A "human" user row is one whose content is not a bare `tool_result`
//      array — the transcript also carries `tool_result` rows (the previous
//      tool call's return value), plus non-`user`/`assistant` rows
//      (`queue-operation`, `attachment`, `last-prompt`, `mode`,
//      `permission-mode`) that are not turn boundaries at all and must be
//      skipped, not mistaken for one.
//   2. `hasHeaderTable(text)` returns true when `text` contains a Markdown
//      pipe table (a `|`-delimited header row, a `| --- | --- |`-shaped
//      separator row, and at least `MIN_TABLE_ROWS` data rows) or the
//      documented `·`-separated one-line fallback
//      (`verdict: ... · findings: ...`) that SKILL.md permits when the
//      report read itself fails.
//   3. `tableReminder(skillLabel)` builds the `additionalContext` string a
//      caller attaches when `hasHeaderTable` is false.
//
// NOT A DENY GATE
//   Unlike the file-existence check each hook already performs, a missing
//   table never denies the tool call — `additionalContext` rides along with
//   `permissionDecision: "allow"`. Per PreToolUse docs, `additionalContext`
//   surfaces "next to the tool result", i.e. after the question is already
//   answered — corrective, not preventive, and deliberately so: a hard deny
//   here would risk false blocks (a table printed several tool calls earlier
//   in the same turn, or the documented `·`-fallback line) with no way for
//   the model to tell a false block from a real one. A missed reminder still
//   regresses to the pre-existing prose-only mandate, never worse.
//
// DISTRIBUTION
//   Canonical copy lives in cc_foundry; byte-identical copies in cc_oss,
//   cc_develop, cc_research via `propagate_shared.py` (same mechanism as
//   `agent-router.js` / `sentinel-read-allow.js`). Every caller `require`s
//   this file inside a try/catch and fails open on throw, so a standalone
//   plugin install missing its copy never breaks the file-existence gate it
//   already relies on.

"use strict";

const fs = require("fs");

// Below this many data rows a pipe-table match is treated as noise (a stray
// `|` in prose), not a rendered report header. The smallest report this
// module guards (foundry:profile / research:topic) still carries at least
// this many fields — keep at or below that skill's minimum field count.
const MIN_TABLE_ROWS = 3;

// Bounded tail read, mirroring task-log.js's PreCompact transcript scan:
// the file can grow to many MB over a long session, and only the most
// recent turns matter here.
const TAIL_BYTES = 200 * 1024;

/** True when `content` (a message's `content` field) is NOT a bare tool_result array — i.e. a real human turn. */
function isHumanUserContent(content) {
  if (typeof content === "string") return content.trim().length > 0;
  if (!Array.isArray(content)) return false;
  return content.some((block) => block && block.type !== "tool_result");
}

/** Parse one JSONL line to a row object, or null on any failure. */
function parseRow(line) {
  try {
    return JSON.parse(line);
  } catch (_) {
    return null;
  }
}

/**
 * Concatenated `text` content of every non-sidechain assistant row since the
 * most recent human `user` row, walking backward from end of transcript.
 * Returns "" when the transcript can't be read or no assistant text is found
 * — callers treat "" exactly like "no table printed" (never a crash).
 */
function assistantTextSinceLastUserTurn(transcriptPath) {
  if (!transcriptPath) return "";
  let buf;
  try {
    const stats = fs.statSync(transcriptPath);
    const readSize = Math.min(TAIL_BYTES, stats.size);
    buf = Buffer.alloc(readSize);
    const fd = fs.openSync(transcriptPath, "r");
    try {
      fs.readSync(fd, buf, 0, readSize, stats.size - readSize);
    } finally {
      fs.closeSync(fd);
    }
  } catch (_) {
    return "";
  }

  const lines = buf.toString("utf8").split("\n").filter(Boolean);
  const texts = [];
  for (let i = lines.length - 1; i >= 0; i--) {
    const row = parseRow(lines[i]);
    if (!row) continue;
    if (row.type === "user") {
      const content = row.message && row.message.content;
      if (isHumanUserContent(content)) break; // turn boundary — stop walking back
      continue; // tool_result row — not a boundary
    }
    if (row.type !== "assistant" || row.isSidechain) continue;
    const content = row.message && row.message.content;
    if (!Array.isArray(content)) continue;
    for (const block of content) {
      if (block && block.type === "text" && typeof block.text === "string") {
        texts.push(block.text);
      }
    }
  }
  return texts.reverse().join("\n");
}

/**
 * True when `text` contains either a rendered `| Field | Value |` table with
 * at least `MIN_TABLE_ROWS` data rows, or the documented `·`-separated
 * one-line fallback SKILL.md permits when the report read genuinely fails.
 */
function hasHeaderTable(text) {
  if (!text) return false;
  if (/verdict:.*·.*·/.test(text)) return true; // `·`-fallback line

  const lines = text.split("\n");
  let sawSeparator = false;
  let dataRows = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|")) {
      if (sawSeparator && dataRows >= MIN_TABLE_ROWS) return true;
      sawSeparator = false;
      dataRows = 0;
      continue;
    }
    if (/^\|[\s:|-]+\|$/.test(trimmed)) {
      sawSeparator = true;
      continue;
    }
    if (sawSeparator) dataRows++;
  }
  return sawSeparator && dataRows >= MIN_TABLE_ROWS;
}

/** Build the `additionalContext` reminder for a skill whose table check failed. */
function tableReminder(skillLabel, printStep) {
  return (
    `${skillLabel} report header gate — the report file exists, but no ` +
    `| Field | Value | table (or the ·-separated fallback line) was found in ` +
    `your reply since the last user turn. quality-gates.md §Report File Format's ` +
    `Universal terminal-print rule requires the report's --- YAML block to be ` +
    `rendered as a two-column Markdown table, never printed raw. If ${printStep} ` +
    "hasn't happened yet in this reply, do it now, in this same turn, before anything else."
  );
}

module.exports = {
  assistantTextSinceLastUserTurn,
  hasHeaderTable,
  isHumanUserContent,
  tableReminder,
  MIN_TABLE_ROWS,
};
