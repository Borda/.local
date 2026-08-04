#!/usr/bin/env node
// enforce-topic-header.js — PreToolUse hook (matcher: AskUserQuestion)
//
// PURPOSE
//   /research:topic must print its report's `---` header block to the terminal
//   before the `## Follow-up gate` AskUserQuestion fires — the mandate is stated
//   in SKILL.md (Step 3, both mandatory termination gates) and in modes/team.md
//   ("MANDATORY, not optional narration"). A sibling skill (oss:review) shipped
//   the same prose-only mandate and a real run skipped it: no report written, no
//   header printed, yet AskUserQuestion (a hard tool call) still fired, so the
//   user saw an ad-hoc summary instead of the report header. This hook converts
//   the mandate into a structural gate: while a topic run is in flight and its
//   report file is absent from disk, AskUserQuestion is denied.
//
// HOW IT WORKS
//   1. Inspect only PreToolUse calls for `AskUserQuestion`; everything else
//      exits 0 with no output (passthrough).
//   2. Resolve CSID the way the skill's bash does (`${CLAUDE_CODE_SESSION_ID:-$PPID}`):
//      env `CLAUDE_CODE_SESSION_ID` first, then the hook payload's `session_id`
//      (same value Claude Code reports to hooks), then `process.ppid` as a
//      best-effort stand-in for bash's `$PPID`. Candidates are tried in order;
//      a candidate that names no sentinel simply does not match.
//   3. Look for `${TMPDIR:-/tmp}/research-topic-report-file-<CSID>`, written the
//      moment the final report path is resolved — Step 3 (single-agent),
//      modes/team.md (before the consolidator spawn), modes/plan.md (Step P1).
//      No sentinel → allow: either no topic run is active, or it has not reached
//      its report-path resolution yet (so the skill's own earlier questions and
//      every other skill's questions stay unblocked).
//   4. Sentinel present → read the report path from it, require it to look like
//      a topic report (`<abs>/.reports/research/topic-*.md`) and its parent dir
//      to exist, then check the file itself. Present and non-empty → allow.
//      Missing or empty → deny, naming the print step to redo.
//   5. Every can't-tell case (unreadable sentinel, implausible path, vanished
//      `.reports/research/` dir, stale sentinel) resolves to allow.
//
//   DIFFERENCE FROM oss/hooks/enforce-review-header.js — that hook's sentinel
//   holds a *directory* containing a fixed `review-report.md`; here the sentinel
//   holds the *file* path directly, because each research:topic mode resolves
//   its own report filename (counter-suffixed against same-day reruns).
//
//   KNOWN LIMITATION — stale sentinel. A run that dies between path resolution
//   and the write leaves the sentinel behind with no report, and nothing on disk
//   distinguishes that from a live run that skipped the print. Bounding on the
//   sentinel's mtime (written once, at path resolution) caps the blast radius:
//   past STALE_MS the gate stops firing, so a session can never be permanently
//   unable to ask a question. The reverse cost — a topic run still going after
//   STALE_MS loses enforcement — only restores the pre-hook status quo.
//   Secondary limitation: hooks are session-wide, so a subagent spawned mid run
//   is gated too. Topic teammates and the consolidator are non-interactive by
//   contract (they write files and return envelopes), so this is intended.
//
// EXIT CODES
//   0  always — passthrough (no output) or decision JSON on stdout.
//      Deliberate deviation from the "gatekeeper crash → block" guidance in
//      hook-authoring.md: this gate protects workflow integrity, not a security
//      boundary. Failing closed on a hook bug would strand the session with no
//      way to ask the user anything, while failing open merely restores the
//      prose-only mandate. Matches sentinel-read-allow.js, which also emits a
//      permissionDecision yet exits 0 on any internal error.

"use strict";

const fs = require("fs");
const path = require("path");

// Sentinel written once the final report path is resolved (`research-topic-report-file-${CSID}`).
const SENTINEL_PREFIX = "research-topic-report-file-";
// Every mode writes "<root>/.reports/research/topic-<...>.md"; requiring the marker
// keeps the hook from acting on a sentinel holding anything else.
const REPORT_PATH_MARKER = "/.reports/research/topic-";
// Enforcement window measured from the sentinel's mtime (see KNOWN LIMITATION).
const STALE_MS = 2 * 60 * 60 * 1000;

/** Sentinel base dir — mirrors `${TMPDIR:-/tmp}` used by every skill bash block. */
function sentinelDir() {
  return process.env.TMPDIR || "/tmp";
}

/** Filename-safe CSID token, or null when the candidate cannot name a sentinel. */
function sanitizeCsid(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return /^[A-Za-z0-9_-]+$/.test(trimmed) ? trimmed : null;
}

/** CSID candidates in the resolution order the skill's bash uses, deduplicated. */
function csidCandidates(env, payload, ppid) {
  const raw = [
    env ? env.CLAUDE_CODE_SESSION_ID : null,
    payload ? payload.session_id : null,
    ppid == null ? null : String(ppid),
  ];
  const out = [];
  for (const candidate of raw) {
    const csid = sanitizeCsid(candidate);
    if (csid && !out.includes(csid)) out.push(csid);
  }
  return out;
}

/** Path of the first existing report-file sentinel among `csids`, else null. */
function findSentinel(dir, csids) {
  for (const csid of csids) {
    const candidate = path.join(dir, SENTINEL_PREFIX + csid);
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch (_) {
      // absent / unreadable — try the next candidate
    }
  }
  return null;
}

/** True when `value` has the shape the modes write: absolute .reports/research/topic-*.md path. */
function isTopicReportFile(value) {
  return (
    typeof value === "string" && path.isAbsolute(value) && value.endsWith(".md") && value.includes(REPORT_PATH_MARKER)
  );
}

/**
 * Report path of an in-flight topic run, or null when the sentinel cannot be
 * trusted to describe one (stale, unreadable, malformed, or its output dir gone).
 */
function activeReportFile(sentinelPath, now) {
  let content;
  try {
    if (now - fs.statSync(sentinelPath).mtimeMs > STALE_MS) return null;
    content = fs.readFileSync(sentinelPath, "utf8");
  } catch (_) {
    return null;
  }
  const reportFile = content.split("\n")[0].trim();
  if (!isTopicReportFile(reportFile)) return null;
  // The mode creates `.reports/research/` before writing the sentinel — its absence
  // means the tree moved or was cleaned up, not that the report is merely pending.
  try {
    return fs.statSync(path.dirname(reportFile)).isDirectory() ? reportFile : null;
  } catch (_) {
    return null;
  }
}

/** True once a non-empty report has been written to `reportFile`. */
function reportWritten(reportFile) {
  try {
    return fs.statSync(reportFile).size > 0;
  } catch (_) {
    return false;
  }
}

/** Reason to deny the AskUserQuestion call, or null to allow it. */
function denyReason(sentinelPath, now) {
  const reportFile = activeReportFile(sentinelPath, now);
  if (!reportFile || reportWritten(reportFile)) return null;
  return (
    `research:topic report gate — ${reportFile} does not exist, so the report has not been written and its ` +
    "`---` header cannot have been printed. Go back to the report step of whichever path is running (Step 3 " +
    "single-agent, modes/team.md consolidation, or modes/plan.md Step P3), write the report to that exact " +
    'path, then print its `---` header block to the terminal and mark the "Print report header" task ' +
    "completed. Call AskUserQuestion only after that header has actually appeared in your response. If the " +
    "report genuinely cannot be produced, report that failure and stop instead of asking the user."
  );
}

// ── Exports (test-only; no-op when run as a hook) ─────────────────────────────
// Helpers are exported for unit testing. The require.main guard below keeps the
// stdin main path from running on require (always taken in production).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    activeReportFile,
    csidCandidates,
    denyReason,
    findSentinel,
    isTopicReportFile,
    reportWritten,
    sanitizeCsid,
  };
}

// ── Main ──────────────────────────────────────────────────────────────────────

if (require.main === module) {
  let raw = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (d) => (raw += d));
  process.stdin.on("end", () => {
    try {
      const data = JSON.parse(raw);
      if (data.hook_event_name && data.hook_event_name !== "PreToolUse") process.exit(0);
      if (data.tool_name !== "AskUserQuestion") process.exit(0);

      const sentinel = findSentinel(sentinelDir(), csidCandidates(process.env, data, process.ppid));
      if (!sentinel) process.exit(0);

      const reason = denyReason(sentinel, Date.now());
      if (!reason) process.exit(0);

      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: reason,
          },
        }),
      );
      process.exit(0);
    } catch (_) {
      // Workflow gate, not a security boundary — never strand the session on a hook bug.
      process.exit(0);
    }
  });
}
