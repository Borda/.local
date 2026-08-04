#!/usr/bin/env node
// enforce-audit-header.js — PreToolUse hook (matcher: AskUserQuestion)
//
// PURPOSE
//   /foundry:audit's follow-up gate (SKILL.md §Follow-up gate, fired from Step 7)
//   asks the user which fix level to run, quoting severity counts that Step 5's
//   consolidator agent produces in `$RUN_DIR/summary.jsonl`. Sibling skills hit a
//   real incident where the analogous prose-only ordering was skipped outright —
//   no consolidator spawned, no consolidated artifact written, yet the follow-up
//   `AskUserQuestion` (a hard tool call) still fired, so the user was asked to
//   pick a fix level based on an ad-hoc in-context summary. This hook makes the
//   ordering structural: while an audit run is in flight and its Step 5 aggregate
//   is absent from disk, the follow-up gate is denied.
//
// WHY summary.jsonl AND NOT report.md
//   /oss:review gates on its final report because there the report is written
//   (Step 5) *before* the question (Step 7a). foundry:audit is inverted: the
//   follow-up gate fires at Step 7, the fix loop runs at Steps 8–10, and
//   `$RUN_DIR/report.md` is only written at Step 11 — after the gate, in every
//   path (SKILL.md Step 7 → modes/fix.md line 5 → Step 11). Gating the gate on
//   report.md would therefore deadlock the skill: the question could never fire,
//   so Step 11 could never be reached to write the file. `summary.jsonl` is the
//   correct analogue — it is the consolidator's output, it is what SKILL.md
//   requires the orchestrator to read before emitting the report ("Before
//   emitting, read current $RUN_DIR/summary.jsonl ... recompute severity
//   totals"), and it is written at Step 5, strictly before the gate.
//
// WHY ONLY THE FOLLOW-UP GATE IS INSPECTED
//   audit legitimately asks other questions while a run is in flight, before
//   Step 5 has produced anything: the `! BREAKING` finding acknowledgment
//   (SKILL.md <notes>, fired mid-Step-4) and the unsupported-flag prompt. A
//   blanket deny would block those and stall the run. The follow-up gate is
//   identified instead by its HARD RULE fixed option labels — SKILL.md mandates
//   `Fix auto-fixable (Recommended)` and `Fix ALL` verbatim on every firing — so
//   only that one call is gated and every other question passes through.
//
// HOW IT WORKS
//   1. Inspect only PreToolUse calls for `AskUserQuestion`; everything else
//      exits 0 with no output (passthrough).
//   2. Resolve CSID the way SKILL.md's bash does (`${CLAUDE_CODE_SESSION_ID:-$PPID}`):
//      env `CLAUDE_CODE_SESSION_ID` first, then the hook payload's `session_id`
//      (same value Claude Code reports to hooks), then `process.ppid` as a
//      best-effort stand-in for bash's `$PPID`. Candidates are tried in order;
//      a candidate that names no sentinel simply does not match.
//   3. Look for `${TMPDIR:-/tmp}/audit-state-<CSID>/run-dir`, written by Step 3
//      the moment `$RUN_DIR` exists. No sentinel → allow: either no audit is
//      running, or it has not reached Step 3 yet. This is the pre-existing
//      sentinel — audit needed no new one, because Step 5's output path is
//      deterministically `$RUN_DIR/summary.jsonl`.
//   4. Sentinel present → read `$RUN_DIR` from it. make_run_dir.py is called
//      with the relative base `.reports/audit`, so the stored path is normally
//      relative; resolve it against the payload's `cwd` before use. Require the
//      result to look like an audit run dir and to exist on disk.
//   5. Question is the follow-up gate (fixed labels) and `$RUN_DIR/summary.jsonl`
//      is missing or empty → deny, naming Step 5. Anything else → allow.
//   6. Every can't-tell case (unreadable sentinel, implausible path, vanished
//      run dir, stale sentinel, unexpected tool_input shape) resolves to allow.
//
//   KNOWN LIMITATION — stale sentinel. `audit-state-<CSID>/` is never cleaned up
//   during a session, so a run that dies between Step 3 and Step 5 leaves the
//   sentinel behind with no aggregate, and nothing on disk distinguishes that
//   from a live run that skipped consolidation. Bounding on the sentinel's mtime
//   (written once, at Step 3) caps the blast radius: past STALE_MS the gate
//   stops firing. The label matching in step 5 above already limits collateral
//   damage to follow-up-gate-shaped questions only.
//   Secondary limitation: hooks are session-wide, so a subagent spawned mid
//   audit is gated too. Audit subagents are non-interactive by contract (they
//   write files and return envelopes), so this is intended.
//
//   NOT AFFECTED — `--skip-gate`. That flag suppresses the follow-up gate
//   entirely, so no AskUserQuestion with those labels is ever emitted and there
//   is nothing for this hook to deny. It needs no detection on disk.
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

// State dir written by SKILL.md Pre-flight (`audit-state-${CSID}`), holding the
// run-dir file written by Step 3. A directory of small state files, not the flat
// `-${CSID}`-suffixed single file other skills use.
const STATE_DIR_PREFIX = "audit-state-";
const RUN_DIR_SENTINEL = "run-dir";
// File the Step 5 consolidator writes into $RUN_DIR — the orchestrator's
// authoritative input for the gate's severity counts.
const AGGREGATE_FILENAME = "summary.jsonl";
// Step 3 always builds "<base>/.reports/audit/<TIMESTAMP>"; requiring the marker
// keeps the hook from acting on a sentinel holding anything else.
const RUN_DIR_MARKER = "/.reports/audit/";
// Enforcement window measured from the sentinel's mtime (see KNOWN LIMITATION).
// 4h, matching the skill's own preflight-cache TTL (SKILL.md `preflight_ok`,
// 14400s) — a full sweep plus a 5-pass fix-convergence loop legitimately runs
// far longer than a single-PR review, so oss:review's 2h would under-cover it.
const STALE_MS = 4 * 60 * 60 * 1000;
// Verbatim option labels the follow-up gate is required to use (SKILL.md
// §Follow-up gate, "HARD RULE — Fixed option labels"). (a) and (c) are mandatory
// on every firing; matching either is enough to recognise the gate.
const GATE_LABELS = ["fix auto-fixable", "fix all"];

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

/** Path of the first existing run-dir sentinel among `csids`, else null. */
function findSentinel(dir, csids) {
  for (const csid of csids) {
    const candidate = path.join(dir, STATE_DIR_PREFIX + csid, RUN_DIR_SENTINEL);
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch (_) {
      // absent / unreadable — try the next candidate
    }
  }
  return null;
}

/**
 * Absolute form of the sentinel's stored run dir, or null when it cannot be one.
 *
 * Step 3 passes the relative base `.reports/audit` to make_run_dir.py, so the
 * stored value is normally relative and only means anything against the audit's
 * own working directory.
 */
function resolveRunDir(value, cwd) {
  if (typeof value !== "string" || value === "") return null;
  const base = typeof cwd === "string" && path.isAbsolute(cwd) ? cwd : process.cwd();
  const resolved = path.resolve(base, value);
  return resolved.includes(RUN_DIR_MARKER) ? resolved : null;
}

/**
 * $RUN_DIR of an in-flight audit, or null when the sentinel cannot be trusted to
 * describe one (stale, unreadable, malformed, or already cleaned up).
 */
function activeRunDir(sentinelPath, cwd, now) {
  let content;
  try {
    if (now - fs.statSync(sentinelPath).mtimeMs > STALE_MS) return null;
    content = fs.readFileSync(sentinelPath, "utf8");
  } catch (_) {
    return null;
  }
  const runDir = resolveRunDir(content.split("\n")[0].trim(), cwd);
  if (!runDir) return null;
  try {
    return fs.statSync(runDir).isDirectory() ? runDir : null;
  } catch (_) {
    return null;
  }
}

/** True once the Step 5 consolidator has written a non-empty summary.jsonl. */
function aggregateWritten(runDir) {
  try {
    return fs.statSync(path.join(runDir, AGGREGATE_FILENAME)).size > 0;
  } catch (_) {
    return false;
  }
}

/**
 * True when `toolInput` is audit's follow-up gate rather than one of the other
 * questions a run legitimately asks (`! BREAKING` acknowledgment, unsupported
 * flag). Recognised by the verbatim fixed option labels; any unexpected shape
 * reads as "not the gate", keeping the hook fail-open.
 */
function isFollowUpGate(toolInput) {
  const questions = toolInput && Array.isArray(toolInput.questions) ? toolInput.questions : [];
  for (const question of questions) {
    const options = question && Array.isArray(question.options) ? question.options : [];
    for (const option of options) {
      const label = option && typeof option.label === "string" ? option.label.toLowerCase() : "";
      if (GATE_LABELS.some((known) => label.includes(known))) return true;
    }
  }
  return false;
}

/** Reason to deny the AskUserQuestion call, or null to allow it. */
function denyReason(sentinelPath, toolInput, cwd, now) {
  if (!isFollowUpGate(toolInput)) return null;
  const runDir = activeRunDir(sentinelPath, cwd, now);
  if (!runDir || aggregateWritten(runDir)) return null;
  const aggregateFile = path.join(runDir, AGGREGATE_FILENAME);
  return (
    `foundry:audit report gate — ${aggregateFile} does not exist, so Step 5 (aggregate and classify ` +
    "findings) has not completed and the follow-up gate's severity counts have no source. Go back: spawn " +
    `the foundry:curator consolidator and let it write aggregate.md and ${AGGREGATE_FILENAME}, then read ` +
    "that summary and emit the Step 7 report. Call AskUserQuestion only after those exist. If the " +
    "consolidator genuinely cannot run, report that failure and stop instead of asking the user."
  );
}

// ── Exports (test-only; no-op when run as a hook) ─────────────────────────────
// Helpers are exported for unit testing. The require.main guard below keeps the
// stdin main path from running on require (always taken in production).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    activeRunDir,
    aggregateWritten,
    csidCandidates,
    denyReason,
    findSentinel,
    isFollowUpGate,
    resolveRunDir,
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

      const reason = denyReason(sentinel, data.tool_input, data.cwd, Date.now());
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
