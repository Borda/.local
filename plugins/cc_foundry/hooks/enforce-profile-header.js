#!/usr/bin/env node
// enforce-profile-header.js — PreToolUse hook (matcher: AskUserQuestion)
//
// PURPOSE
//   /foundry:profile must print the report's `---` YAML header block plus the
//   `→ $REPORT_DIR/report.md` path to the terminal (SKILL.md Step 4) before
//   Step 5's follow-up `AskUserQuestion` fires. That ordering was a prose-only
//   mandate — and profile carries it with weaker scaffolding than its siblings:
//   its single tracked task covers "run analyzer + render report" as a whole, so
//   nothing structural distinguishes a run that printed the header from one that
//   jumped straight to the question. A sibling skill (/oss:review) hit exactly
//   that incident: no report written, no header printed, yet the follow-up
//   `AskUserQuestion` (a hard tool call) still fired and the user was asked to
//   choose a drill-down from an ad-hoc in-context summary. This hook makes the
//   ordering structural: while a profile run is in flight and its report is
//   absent from disk, `AskUserQuestion` is denied.
//
// WHAT THIS GATE DOES AND DOES NOT PROVE
//   It proves the artifact Step 4 must read actually exists. It cannot prove the
//   header was pasted into the response — no hook observes assistant text. The
//   failure mode it removes is the expensive one (question asked with no report
//   behind it at all); printing from a report that demonstrably exists stays a
//   prose mandate, backed by the deny reason naming Step 4 explicitly.
//
// WHY report.md AND NOT result.jsonl
//   Step 2 writes `$REPORT_DIR/report.md` (the analyzer's `--output`), Step 3
//   writes `result.jsonl`, Step 4 prints, Step 5 asks. Both artifacts precede the
//   question, so either would work as a marker; report.md is the file Step 4 is
//   required to read and the one whose absence makes the print impossible, which
//   makes it the honest thing to gate on and the actionable thing to name.
//
// ANALYZER-FOUND-NOTHING PATH IS DENIED BY DESIGN
//   `timing_analyzer.py` exits 1 without writing report.md when no session falls
//   in the window. SKILL.md Step 2 requires the run to "surface that and stop" —
//   no follow-up question is authorised on that path — so denying it matches the
//   skill contract rather than fighting it. The deny reason says as much: report
//   the failure and stop instead of asking.
//
// HOW IT WORKS
//   1. Inspect only PreToolUse calls for `AskUserQuestion`; everything else
//      exits 0 with no output (passthrough).
//   2. Resolve CSID the way SKILL.md's bash does (`${CLAUDE_CODE_SESSION_ID:-$PPID}`):
//      env `CLAUDE_CODE_SESSION_ID` first, then the hook payload's `session_id`
//      (same value Claude Code reports to hooks), then `process.ppid` as a
//      best-effort stand-in for bash's `$PPID`. Candidates are tried in order;
//      a candidate that names no sentinel simply does not match.
//   3. Look for `${TMPDIR:-/tmp}/foundry-profile-state-<CSID>`, written by Step 1
//      the moment `$REPORT_DIR` exists. No sentinel → allow: either no profile is
//      running, or it has not reached Step 1 yet, so every other skill's
//      questions stay unblocked.
//   4. Sentinel present → parse `REPORT_DIR` out of it. Unlike the flat one-path
//      sentinels other skills write, this file is a shell fragment of `KEY=VALUE`
//      lines (`REPORT_DIR`, `SINCE`, `SESSION_ID`, `TOP_N`) that Steps 2–3
//      re-source with `.`. It is parsed line-wise, never executed. Step 1 builds
//      the relative `.reports/profile/$STAMP`, so the stored value is normally
//      relative; resolve it against the payload's `cwd` before use, then require
//      it to look like a profile report dir and to exist on disk.
//   5. `$REPORT_DIR/report.md` present and non-empty → allow. Missing or empty →
//      deny, naming Step 2 / Step 4 in the reason.
//   6. Every can't-tell case (unreadable sentinel, no `REPORT_DIR` line,
//      implausible path, vanished report dir, stale sentinel) resolves to allow.
//
//   KNOWN LIMITATION — stale sentinel. The state file is never cleaned up during
//   a session, so a run that dies between Step 1 and Step 2 leaves it behind with
//   no report, and nothing on disk distinguishes that from a live run that
//   skipped the print. Bounding on the sentinel's mtime (written once, at Step 1)
//   caps the blast radius: past STALE_MS the gate stops firing, so a session can
//   never be permanently unable to ask a question. The reverse cost — a profile
//   still running after STALE_MS loses enforcement — only restores the pre-hook
//   status quo.
//   Secondary limitation: hooks are session-wide, so a subagent spawned mid
//   profile is gated too. profile spawns none (it is a pure log read: three Bash
//   calls, one Read, one Write), so nothing is affected in practice.
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

// Shell-fragment state file written by SKILL.md Step 1
// (`foundry-profile-state-${CSID}`), re-sourced by Steps 2–3.
const SENTINEL_PREFIX = "foundry-profile-state-";
// Key holding the run dir inside that fragment.
const STATE_KEY = "REPORT_DIR";
// File `timing_analyzer.py` writes as its `--output` (Step 2) and Step 4 reads.
const REPORT_FILENAME = "report.md";
// Step 1 always builds ".reports/profile/$STAMP"; requiring the marker keeps the
// hook from acting on a state file holding anything else.
const REPORT_DIR_PARTS = [".reports", "profile"];
// Enforcement window measured from the sentinel's mtime (see KNOWN LIMITATION).
// profile declares no <constants> block; its own longest step is the Step 2
// analyzer at a 60s Bash timeout, and the whole skill is three Bash calls with no
// agent spawns, so 2h (matching oss:review, the shortest sibling window) is
// already orders of magnitude past any legitimate run.
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

/** CSID candidates in the resolution order SKILL.md's bash uses, deduplicated. */
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

/** Path of the first existing profile state file among `csids`, else null. */
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

/**
 * Value of `REPORT_DIR` in a `KEY=VALUE` shell fragment, or null when absent.
 *
 * Deliberately mirrors what `.` (source) would bind rather than being maximally
 * permissive — a hook that read a different path than the skill's own shell does
 * would gate the wrong directory. So: leading whitespace and an `export ` prefix
 * are allowed (bash binds both) but whitespace around `=` is not, the last
 * assignment wins (later lines overwrite earlier ones), trailing whitespace is
 * dropped, and one layer of matching surrounding quotes is peeled.
 *
 * Split on `\r?\n`, not `\n`: JS treats `\r` as a line terminator, so a CRLF
 * file leaves a trailing `\r` that `.` cannot match and `$` cannot look past,
 * making every assignment silently unparsable.
 */
function parseStateValue(content, key) {
  if (typeof content !== "string") return null;
  let found = null;
  for (const line of content.split(/\r?\n/)) {
    const match = line.match(/^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match || match[1] !== key) continue;
    let value = match[2].replace(/[ \t]+$/, "");
    const quote = value[0];
    if ((quote === '"' || quote === "'") && value.length >= 2 && value[value.length - 1] === quote) {
      value = value.slice(1, -1);
    }
    found = value;
  }
  return found === null || found === "" ? null : found;
}

/** Select the path implementation matching a Windows or POSIX sentinel path. */
function reportPathApi(value, cwd) {
  const isWindowsPath = (candidate) =>
    typeof candidate === "string" && (/^[A-Za-z]:[\\/]/.test(candidate) || candidate.startsWith("\\\\"));
  return isWindowsPath(value) || isWindowsPath(cwd) ? path.win32 : path.posix;
}

/** True when normalized path components contain a descendant of the expected report directory. */
function isReportPath(value, api, reportParts) {
  const parts = api.normalize(value).split(api.sep).filter(Boolean);
  const normalize = api === path.win32 ? (part) => part.toLowerCase() : (part) => part;
  const marker = reportParts.map(normalize);
  return parts.some(
    (_, index) =>
      index + marker.length < parts.length && marker.every((part, offset) => normalize(parts[index + offset]) === part),
  );
}

/**
 * Absolute form of the state file's stored report dir, or null when it cannot be
 * one.
 *
 * Step 1 assigns the relative `.reports/profile/$STAMP`, so the stored value is
 * normally relative and only means anything against the profile's own working
 * directory.
 */
function resolveReportDir(value, cwd) {
  if (typeof value !== "string" || value === "") return null;
  const api = reportPathApi(value, cwd);
  const base = typeof cwd === "string" && api.isAbsolute(cwd) ? cwd : process.cwd();
  const resolved = api.resolve(base, value);
  return isReportPath(resolved, api, REPORT_DIR_PARTS) ? resolved : null;
}

/**
 * $REPORT_DIR of an in-flight profile run, or null when the sentinel cannot be
 * trusted to describe one (stale, unreadable, malformed, or already cleaned up).
 */
function activeReportDir(sentinelPath, cwd, now) {
  let content;
  try {
    if (now - fs.statSync(sentinelPath).mtimeMs > STALE_MS) return null;
    content = fs.readFileSync(sentinelPath, "utf8");
  } catch (_) {
    return null;
  }
  const reportDir = resolveReportDir(parseStateValue(content, STATE_KEY), cwd);
  if (!reportDir) return null;
  try {
    return fs.statSync(reportDir).isDirectory() ? reportDir : null;
  } catch (_) {
    return null;
  }
}

/** True once the Step 2 analyzer has written a non-empty report.md. */
function reportWritten(reportDir) {
  try {
    return fs.statSync(path.join(reportDir, REPORT_FILENAME)).size > 0;
  } catch (_) {
    return false;
  }
}

/** Reason to deny the AskUserQuestion call, or null to allow it. */
function denyReason(sentinelPath, cwd, now) {
  const reportDir = activeReportDir(sentinelPath, cwd, now);
  if (!reportDir || reportWritten(reportDir)) return null;
  const reportFile = path.join(reportDir, REPORT_FILENAME);
  return (
    `foundry:profile report gate — ${reportFile} does not exist, so Step 2 (run analyzer) and Step 4 ` +
    "(emit terminal output) have not completed. Go back: run timing_analyzer.py so it writes " +
    `${REPORT_FILENAME}, then Read that file and print its \`---\` header block plus the ` +
    "`→ <path>` line to the terminal. Call AskUserQuestion only after that header has actually " +
    "appeared in your response. If the analyzer found no sessions in the window (exit 1), report that " +
    "and stop — Step 2 authorises no follow-up question on that path."
  );
}

// ── Exports (test-only; no-op when run as a hook) ─────────────────────────────
// Helpers are exported for unit testing. The require.main guard below keeps the
// stdin main path from running on require (always taken in production).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    activeReportDir,
    csidCandidates,
    denyReason,
    findSentinel,
    parseStateValue,
    reportWritten,
    resolveReportDir,
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

      const reason = denyReason(sentinel, data.cwd, Date.now());
      if (!reason) {
        // Additive nudge, not a deny — see report-header-table.js for why a
        // missing table rides as additionalContext instead of blocking.
        try {
          const { assistantTextSinceLastUserTurn, hasHeaderTable, tableReminder } = require("./report-header-table.js");
          const text = assistantTextSinceLastUserTurn(data.transcript_path);
          if (text && !hasHeaderTable(text)) {
            process.stdout.write(
              JSON.stringify({
                hookSpecificOutput: {
                  hookEventName: "PreToolUse",
                  permissionDecision: "allow",
                  additionalContext: tableReminder("foundry:profile", "Step 4b (print report header)"),
                },
              }),
            );
          }
        } catch (_) {
          // Missing/broken copy of the shared detector — fall through to plain allow.
        }
        process.exit(0);
      }

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
