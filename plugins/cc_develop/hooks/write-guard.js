#!/usr/bin/env node
// write-guard.js — PreToolUse hook (matchers: Edit, Write, NotebookEdit)
//
// PURPOSE
//   Ship the PROTECT list in the plugin instead of re-adding an ALLOW list by
//   hand to every repository's settings.local.json. Allow rules are inherently
//   project-specific (one repo's sources live in `src/`, another's in `lib/`),
//   so they drift per machine and per project and never generalize. The set of
//   files where an unreviewed agent write actually costs something is the same
//   in essentially every repository, which is what makes it shippable policy.
//
//   This hook grants NOTHING. It forces a confirmation on writes to that
//   protected set; everything else is silent passthrough, so the session's own
//   permission mode still governs the ordinary case. Pair it with `acceptEdits`
//   to remove routine friction while CI definitions, lockfiles and agent
//   instructions still stop you.
//
// SECURITY MODEL — deliberately the inverse of blueprint-allow.js
//   blueprint-allow.js can safely emit "allow" because it has PROVENANCE: the
//   exact command text came from a reviewed, versioned plugin file, so allowing
//   it means "you already reviewed this". An Edit has no provenance — its
//   content is arbitrary new code. So this hook never emits "allow"; auto-
//   allowing writes by directory convention would just be acceptEdits with
//   worse visibility. Guard, do not grant.
//
// WHAT IS PROTECTED, AND WHY THESE
//   Only files that are (a) named identically across essentially every repo,
//   and (b) costly when written without review: CI definitions, agent
//   instructions (the file that tells the next agent what to do), release
//   metadata, dependency lockfiles, and Claude's own permission config.
//   Source and tests are deliberately NOT protected — that is the routine work.
//
// UNVERIFIED PREMISE — carried deliberately
//   "ask" is a documented permissionDecision value, but whether it overrides an
//   already-auto-approving permission mode (acceptEdits / an allow rule) is not
//   stated in the docs section, which truncates there. If it does NOT override,
//   this hook degrades to a silent no-op — it never false-blocks. Settle it live:
//   in a default-permission session with acceptEdits on, edit CHANGELOG.md and
//   look for a prompt carrying this hook's permissionDecisionReason. No prompt
//   means "ask" does not override, and the decision has to become "deny".
//
// EXIT CODES
//   0  always — passthrough (no output) or a decision on stdout. Never crashes
//      the session, matching every other hook in this plugin.

"use strict";

const GUARDED_TOOLS = new Set(["Edit", "Write", "NotebookEdit"]);

// Matched against the POSIX-normalized path. Windows hosts hand us backslashes,
// so every pattern assumes "/" and the caller normalizes first — a separator
// mismatch would silently disable the whole guard on one OS.
// Anchored with `(^|\/)` so a path merely CONTAINING the name never matches:
// `src/my_changelog_helper.py` and `src/github/client.py` stay routine work.
// Case-INSENSITIVE by design: macOS and Windows filesystems are case-folding, so
// a write addressed as `changelog.md` lands in the real `CHANGELOG.md`. Under a
// case-sensitive matcher that path classifies as unprotected, and passthrough
// means auto-approved whenever the hook is paired with acceptEdits — the exact
// configuration it exists for. The cost is a false ask on case-sensitive Linux
// for a genuinely distinct `docs/claude.md`; one extra confirmation is the
// cheaper side of that trade.
const PROTECTED = [
  { re: /(^|\/)\.github\//i, why: "CI/workflow definition" },
  { re: /(^|\/)CLAUDE\.md$/i, why: "agent instructions" },
  { re: /(^|\/)AGENTS\.md$/i, why: "agent instructions" },
  { re: /(^|\/)\.claude\/settings(\.local)?\.json$/i, why: "Claude permission config" },
  { re: /(^|\/)\.pre-commit-config\.yaml$/i, why: "lint/format gate" },
  { re: /(^|\/)CHANGELOG\.md$/i, why: "release metadata" },
  { re: /(^|\/)(uv|poetry|package-lock|yarn|Cargo|pnpm-lock)\.(lock|json|yaml)$/i, why: "dependency lockfile" },
  { re: /(^|\/)pyproject\.toml$/i, why: "package/release metadata" },
];

/**
 * Normalize a filesystem path to POSIX separators for pattern matching.
 *
 * @param {string} p Raw path from tool_input.
 * @returns {string} Path with "/" separators.
 */
function toPosix(p) {
  return String(p).replace(/\\/g, "/");
}

/**
 * Classify a path against the protected set.
 *
 * @param {string} filePath Raw path from tool_input.
 * @returns {{why: string}|null} Match reason, or null when unprotected.
 */
function classify(filePath) {
  if (!filePath) return null;
  const posix = toPosix(filePath);
  for (const entry of PROTECTED) {
    if (entry.re.test(posix)) return { why: entry.why };
  }
  return null;
}

/**
 * Build the hook decision for one tool call, or null for passthrough.
 *
 * `notebook_path` is read alongside `file_path` because NotebookEdit names its
 * target differently; without it that matcher would ship unguarded.
 *
 * @param {object} data Parsed hook payload.
 * @returns {object|null} hookSpecificOutput envelope, or null.
 */
function decide(data) {
  if (!data || !GUARDED_TOOLS.has(data.tool_name)) return null;
  const input = data.tool_input || {};
  const hit = classify(input.file_path || input.notebook_path);
  if (!hit) return null;
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: `protected file (${hit.why}) — confirm this write`,
    },
  };
}

module.exports = { classify, decide, toPosix, PROTECTED, GUARDED_TOOLS };

if (require.main === module) {
  let raw = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => (raw += c));
  process.stdin.on("end", () => {
    let out = null;
    try {
      out = decide(JSON.parse(raw));
    } catch (_) {
      out = null; // malformed payload → passthrough, never block
    }
    if (out) process.stdout.write(JSON.stringify(out));
    process.exit(0);
  });
}
