#!/usr/bin/env node
// enforce-analyse-header.js — PreToolUse hook (matcher: AskUserQuestion)
//
// PURPOSE
//   Each /oss:analyse mode must write its report file and print that report's
//   `---` header block to the terminal before SKILL.md Step 6a's follow-up
//   `AskUserQuestion` fires (modes/thread.md "Print terminal block: read '---'
//   header from top of report file", modes/ecosystem.md "Print by reading lines
//   1–6 of report file", modes/vitality.md "Print compact block to terminal").
//   The sibling /oss:review workflow carried the same prose-only mandate and a
//   real run skipped it outright: no report written, no header printed, yet the
//   follow-up question (a hard tool call) still fired, so the user chose a next
//   step from an ad-hoc summary. This hook makes the ordering structural: while
//   an analyse run is in flight and knows where its report goes, but that report
//   is absent from disk, `AskUserQuestion` is denied.
//
// WHY THE SENTINEL IS WRITTEN BY THE MODE FILES
//   SKILL.md Step 1 writes `analyse-report-file-<CSID>` unconditionally, but at
//   that point `$REPORT_FILE` is empty for every analysis mode — it holds a path
//   only in DIRECT_PATH_MODE (`/oss:analyse path/to/report.md --reply`), where
//   the file is required to exist already. Each mode therefore rewrites the
//   sentinel with its own report path immediately *before* the Write that
//   creates it (thread.md and ecosystem.md just above their report-write step,
//   vitality.md in Step 4 where `$REPORT_FILE` is first built). That is exactly
//   the race window this gate needs, and it is uniform across all three modes.
//   An empty sentinel (Step 1, mode not yet reached) reads as "cannot tell" and
//   allows — which is what keeps Step 1's unsupported-flag question unblocked.
//
// HOW IT WORKS
//   1. Inspect only PreToolUse calls for `AskUserQuestion`; everything else
//      exits 0 with no output (passthrough).
//   2. Resolve CSID the way SKILL.md's bash does (`${CLAUDE_CODE_SESSION_ID:-$PPID}`):
//      env `CLAUDE_CODE_SESSION_ID` first, then the hook payload's `session_id`
//      (same value Claude Code reports to hooks), then `process.ppid` as a
//      best-effort stand-in for bash's `$PPID`. Candidates are tried in order;
//      a candidate that names no sentinel simply does not match.
//   3. Look for `${TMPDIR:-/tmp}/analyse-report-file-<CSID>`. No sentinel → allow:
//      no analyse run has started, so every other skill's questions pass through.
//   4. Sentinel present → read the report path from it. The skill builds report
//      paths relative to the repo root (`.reports/analyse/<mode>/…`), so resolve
//      against the payload's `cwd` and require the analyse-report marker.
//   5. Report file present and non-empty → allow. Missing or empty → deny,
//      naming the mode's report step in the reason.
//   6. Every can't-tell case (empty or unreadable sentinel, implausible path,
//      stale sentinel) resolves to allow.
//
//   KNOWN LIMITATION — stale sentinel. A run that dies between the mode's
//   sentinel write and its report Write leaves the sentinel behind with no
//   report, and nothing on disk distinguishes that from a live run that skipped
//   the print. Bounding on the sentinel's mtime caps the blast radius: past
//   STALE_MS the gate stops firing, so a session can never be permanently unable
//   to ask a question. The reverse cost — an analyse still running after
//   STALE_MS loses enforcement — only restores the prose-only mandate.
//   Secondary limitation: the gate proves the report exists, not that its header
//   was printed, and a same-day rerun of thread/ecosystem mode reuses the same
//   filename, so the previous run's file satisfies the check. Both match
//   enforce-review-header.js; the mode files keep the print itself as prose.
//   Third: hooks are session-wide, so a subagent spawned mid analyse is gated
//   too. Analyse subagents are non-interactive by contract (they write files and
//   return envelopes), so this is intended.
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

// Sentinel written by SKILL.md Step 1 and rewritten by each mode file
// (`analyse-report-file-${CSID}`).
const SENTINEL_PREFIX = "analyse-report-file-";
// Every mode writes under ".reports/analyse/<thread|vitality|ecosystem>/";
// requiring the marker keeps the hook from acting on a sentinel holding
// anything else — notably the arbitrary path DIRECT_PATH_MODE stores.
const REPORT_MARKER = "/.reports/analyse/";
// Enforcement window measured from the sentinel's mtime (see KNOWN LIMITATION).
// 2h, matching enforce-review-header.js: the mode files write the sentinel late
// in the run (vitality only reaches Step 4 after data fetch and axis scoring),
// so what has to fit inside the window is report generation plus the review
// passes that follow it, not the whole analyse.
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

/**
 * Absolute form of the sentinel's stored report path, or null when it cannot be
 * one. The modes build ".reports/analyse/…" relative to the repo root, so the
 * stored value only means anything against the analyse's working directory.
 */
function resolveReportFile(value, cwd) {
  if (typeof value !== "string" || value === "") return null;
  const base = typeof cwd === "string" && path.isAbsolute(cwd) ? cwd : process.cwd();
  const resolved = path.resolve(base, value);
  return resolved.includes(REPORT_MARKER) ? resolved : null;
}

/**
 * $REPORT_FILE of an in-flight analyse, or null when the sentinel cannot be
 * trusted to describe one (stale, unreadable, empty, or malformed).
 */
function activeReportFile(sentinelPath, cwd, now) {
  let content;
  try {
    if (now - fs.statSync(sentinelPath).mtimeMs > STALE_MS) return null;
    content = fs.readFileSync(sentinelPath, "utf8");
  } catch (_) {
    return null;
  }
  return resolveReportFile(content.split("\n")[0].trim(), cwd);
}

/** True once the mode has written a non-empty report file. */
function reportWritten(reportFile) {
  try {
    return fs.statSync(reportFile).size > 0;
  } catch (_) {
    return false;
  }
}

/** Reason to deny the AskUserQuestion call, or null to allow it. */
function denyReason(sentinelPath, cwd, now) {
  const reportFile = activeReportFile(sentinelPath, cwd, now);
  if (!reportFile || reportWritten(reportFile)) return null;
  return (
    `oss:analyse report gate — ${reportFile} does not exist, so this run's mode file has not written its ` +
    "report and Step 6a's follow-up question would describe an unsaved analysis. Go back: write the report " +
    "with the Write tool, then Read it and print its `---` header block to the terminal. Call " +
    "AskUserQuestion only after that header has actually appeared in your response. If the report genuinely " +
    "cannot be produced, report that failure and stop instead of asking the user."
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
    reportWritten,
    resolveReportFile,
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
