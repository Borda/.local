#!/usr/bin/env node
// carryover-restore.js — SessionStart hook (matcher: clear)
//
// PURPOSE
//   `/foundry:carryover dump` writes a compact handover doc to
//   <cwd>/.claude/state/carryover/<slug>.md and points LATEST at its slug.
//   A skill cannot invoke /clear (no programmatic slash invocation outside the
//   Agent SDK), so the user sends it manually. This hook closes the loop from
//   the other side: on the fresh session it injects that doc back into context,
//   making restore free and reducing the flow to dump + /clear.
//
// INJECTION MECHANISM
//   Raw process.stdout.write of plain text. Per hooks.md, SessionStart is one of
//   the three events whose stdout is added as context Claude can see and act on.
//   Chosen over hookSpecificOutput.additionalContext because raw stdout is the
//   variant proven in this environment (caveman-activate.js).
//
// GATES (cheapest first — the common path costs one existsSync)
//   1. SessionStart event; source, when present, must be "clear".
//   2. LATEST pointer exists, non-blank, and is a plain basename (no / or ..).
//   3. Frontmatter says consumed: false.
//   4. Frontmatter `created` parses and is within 30 minutes of now.
//   Any gate failing → exit 0 with no stdout. Silence is the correct outcome:
//   almost every /clear has no pending carryover.
//
// SIZE GUARD
//   Over MAX_INJECT_CHARS the doc is not injected whole — only ## Goal, the
//   files table, ## Next step, and a `/carryover restore <slug>` pointer. A
//   context reset that immediately re-imports 8K+ chars defeats its own purpose.
//
// CONSUMPTION
//   After a successful write: frontmatter is rewritten to consumed: true and
//   LATEST is unlinked, so a second /clear never re-injects. Both are wrapped
//   independently — a failure to mark leaves the injection intact.
//
// EXIT CODES
//   0  always — inject (stdout) or stay silent. Never blocks session start.

"use strict";

const fs = require("fs");
const path = require("path");

const MAX_AGE_MS = 30 * 60 * 1000; // auto-restore window
const MAX_INJECT_CHARS = 8000; // above this, head + pointer only
const CARRYOVER_SUBDIR = path.join(".claude", "state", "carryover");

/**
 * Split a doc into its frontmatter block and body. Returns null when there is no leading `---` block.
 * `head` keeps BOTH delimiter lines and its trailing newline, so `head + body` round-trips the file
 * byte for byte — dropping the closing `---` would corrupt the doc on every consumption rewrite.
 */
function splitFrontmatter(text) {
  if (!text.startsWith("---")) return null;
  const close = text.indexOf("\n---", 3);
  if (close === -1) return null;
  const bodyStart = text.indexOf("\n", close + 1);
  if (bodyStart === -1) return { head: text, body: "" };
  return { head: text.slice(0, bodyStart + 1), body: text.slice(bodyStart + 1) };
}

/** Parse `key: value` lines out of a frontmatter block. Values keep their raw text. */
function parseFields(head) {
  const fields = {};
  for (const line of head.split("\n")) {
    const m = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (m) fields[m[1]] = m[2].trim();
  }
  return fields;
}

/** Extract one `## Heading` section (heading line included) up to the next `##` heading. */
function section(body, heading) {
  const lines = body.split("\n");
  const start = lines.findIndex((l) => l.trim() === heading);
  if (start === -1) return "";
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    if (/^##\s/.test(lines[i])) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join("\n").trimEnd();
}

/** Minutes elapsed since `createdMs`, floored. */
function ageMinutes(createdMs) {
  return Math.floor((Date.now() - createdMs) / 60000);
}

function buildOutput(slug, body, fields, docPath) {
  const age = ageMinutes(Date.parse(fields.created));
  const branch = fields.branch ? `, branch ${fields.branch}` : "";
  if (body.length <= MAX_INJECT_CHARS) {
    return `[carryover] restored from \`${slug}\` — dumped ${age} min ago${branch}. Source: ${docPath}\n\n${body.trim()}\n`;
  }
  const head = [section(body, "## Goal"), section(body, "## Files touched"), section(body, "## Next step")]
    .filter(Boolean)
    .join("\n\n");
  return (
    `[carryover] restored from \`${slug}\` — dumped ${age} min ago${branch}. ` +
    `Doc is ${body.length} chars, injecting head only. Source: ${docPath}\n\n` +
    `${head}\n\n→ /carryover restore ${slug} for the full document\n`
  );
}

/** Rewrite the frontmatter's consumed flag in place. Best-effort — caller ignores failure. */
function markConsumed(docPath, split) {
  const rewritten = split.head.replace(/^consumed:\s*false\s*$/m, "consumed: true");
  if (rewritten === split.head) return;
  fs.writeFileSync(docPath, rewritten + split.body, "utf8");
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);
    if (data.hook_event_name !== "SessionStart") process.exit(0);
    // Lenient on source: hooks.json already filters with matcher "clear". Reject
    // only an explicitly different source, so a payload without the field still works.
    if (data.source && data.source !== "clear") process.exit(0);

    const cwd = data.cwd;
    if (!cwd || typeof cwd !== "string") process.exit(0);

    const dir = path.join(cwd, CARRYOVER_SUBDIR);
    const latestPath = path.join(dir, "LATEST");
    if (!fs.existsSync(latestPath)) process.exit(0);

    const slug = fs.readFileSync(latestPath, "utf8").trim();
    // Blank LATEST = consumed by `/carryover restore`, which empties rather than deletes it.
    // Reject separators/traversal so the pointer can never reach outside the carryover dir.
    if (!slug || slug.includes("/") || slug.includes("\\") || slug.includes("..")) process.exit(0);

    const docPath = path.join(dir, `${slug}.md`);
    if (!fs.existsSync(docPath)) process.exit(0);

    const text = fs.readFileSync(docPath, "utf8");
    const split = splitFrontmatter(text);
    if (!split) process.exit(0);

    const fields = parseFields(split.head);
    if (fields.consumed !== "false") process.exit(0);

    const createdMs = Date.parse(fields.created || "");
    if (Number.isNaN(createdMs) || Date.now() - createdMs > MAX_AGE_MS) process.exit(0);

    process.stdout.write(buildOutput(slug, split.body, fields, path.join(CARRYOVER_SUBDIR, `${slug}.md`)));

    try {
      markConsumed(docPath, split);
    } catch (_) {}
    try {
      fs.unlinkSync(latestPath);
    } catch (_) {}

    process.exit(0);
  } catch (_) {
    // A hook bug must never block a session from starting.
    process.exit(0);
  }
});
