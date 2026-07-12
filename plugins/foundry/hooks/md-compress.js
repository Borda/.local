#!/usr/bin/env node
// md-compress.js — PreToolUse hook (Edit only)
//
// PURPOSE
//   MD files (config, reports, plans, handover, skills) are dense with
//   pipe-table column padding that wastes tokens without adding meaning.
//   On Edit, this hook normalizes the file at its real on-disk path before
//   the edit runs, and normalizes old_string the same way, so a padded
//   old_string still matches.
//
//   NOTE — two prior designs were tried and rejected here, both on Read:
//   1. Serve Read from a session-scoped temp file, redirecting file_path,
//      to keep Read side-effect-free. Broke the Edit tool's own "must Read
//      this path before Edit" precondition — Claude's Read got recorded
//      against the temp path, so Edit on the real path always failed with
//      "File has not been read yet", even right after a successful Read.
//   2. Normalize the real file in place on Read too (mirroring Edit), to
//      fix (1) while still saving Read-time tokens. This fixed the Edit
//      precondition, but silently rewrote table alignment in every .md
//      file Claude so much as looked at — including files nobody asked to
//      touch — clobbering deliberately-aligned GFM tables repo-wide with
//      no mdformat pass to restore them (mdformat-gfm's default table
//      style does not re-pad columns).
//   Read is now a pure no-op for this hook — no compression, no disk
//   writes, ever. Since Read never redirects or rewrites, Read's tracked
//   path and Edit's target path are always identical by construction,
//   which is what actually fixes the "File has not been read yet" bug —
//   no Read-time mutation is needed for that fix.
//
//   Post-edit (lint-on-save.js): runs pre-commit after every Write/Edit,
//     applying mdformat + trailing-whitespace. File stays normalized.
//
// COMPRESSIONS (outside fenced code blocks only)
//     1. Table column padding: collapses 2+ spaces on pipe-table lines to 1.
//     2. Consecutive blank lines: collapses runs of 2+ blanks to 1.
//     3. Trailing whitespace: strips trailing spaces on every non-fence line.
//
// HOW IT WORKS — Edit path (the only path)
//   1. Skip non-Edit tools or non-.md/.markdown files (exit 0).
//   2. Read source file; if unreadable or empty, exit 0.
//   3. Run compressMarkdown; if unchanged, skip disk write.
//   4. Write normalized content back to source file in place, atomically
//      (write-then-rename), so old_string matches.
//   5. Emit updatedInput with old_string = compressMarkdown(old_string) if present,
//      plus all other Edit fields unchanged.
//
// EXIT CODES
//   0  passthrough (non-Edit tool, non-.md file, read error, no-op, or successful rewrite)

"use strict";

const fs = require("fs");
const path = require("path");

/**
 * Compress markdown content:
 *  - Outside fenced code blocks:
 *    • Strip trailing whitespace from each line
 *    • On pipe-table lines: collapse runs of 2+ spaces to 1
 *    • Collapse runs of 2+ consecutive blank lines to 1
 *
 * @param {string} content
 * @returns {string}
 */
function compressMarkdown(content) {
  const lines = content.split("\n");
  const out = [];
  let inFence = false;
  let fenceChar = "";
  let fenceLen = 0;
  let consecutiveBlanks = 0;

  for (const line of lines) {
    const trimmed = line.trimStart();

    // --- Fence tracking ---
    if (!inFence) {
      const m = trimmed.match(/^(`{3,}|~{3,})/);
      if (m) {
        inFence = true;
        fenceChar = m[1][0];
        fenceLen = m[1].length;
        consecutiveBlanks = 0;
        out.push(line); // preserve fence line as-is
        continue;
      }
    } else {
      const m = trimmed.match(/^(`{3,}|~{3,})/);
      // CommonMark: a closing fence must use the same char AND be at least as
      // long as the opener — a 3-backtick line does NOT close a 4-backtick fence.
      if (m && m[1][0] === fenceChar && m[1].length >= fenceLen) {
        inFence = false;
        fenceChar = "";
        fenceLen = 0;
      }
      out.push(line); // preserve all content inside fence as-is
      continue;
    }

    // --- Outside fence ---

    // Strip trailing whitespace
    const stripped = line.trimEnd();

    // Blank line handling: collapse consecutive blank lines
    if (stripped === "") {
      consecutiveBlanks++;
      if (consecutiveBlanks <= 1) {
        out.push(""); // allow exactly one blank line through
      }
      // subsequent blanks in the same run are dropped
      continue;
    }

    consecutiveBlanks = 0;

    // Pipe-table lines: collapse internal padding (2+ spaces → 1)
    if (stripped.startsWith("|")) {
      out.push(stripped.replace(/ {2,}/g, " "));
    } else {
      out.push(stripped);
    }
  }

  return out.join("\n");
}

/**
 * Read a markdown file, normalize it, and write the result back in place
 * if it changed. Returns the normalized content, or null if the file
 * could not be read.
 *
 * @param {string} absPath
 * @returns {string | null}
 */
function normalizeFileInPlace(absPath) {
  let content;
  try {
    content = fs.readFileSync(absPath, "utf8");
  } catch (_) {
    return null;
  }
  if (!content) return null;

  const normalized = compressMarkdown(content);
  if (normalized !== content) {
    // Write-then-rename: atomic on the same filesystem, so a crash or a
    // concurrent read mid-write never sees a truncated file.
    const tmpPath = `${absPath}.md-compress-${process.pid}.tmp`;
    try {
      fs.writeFileSync(tmpPath, normalized, "utf8");
      fs.renameSync(tmpPath, absPath);
    } catch (_) {
      try {
        fs.unlinkSync(tmpPath);
      } catch (_) {}
      // Can't write — caller falls back to the on-disk (unnormalized) content.
      return content;
    }
  }
  return normalized;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);

    // Only Edit is handled — see NOTE above for why Read is a pure no-op.
    if (data.tool_name !== "Edit") {
      process.exit(0);
    }

    // Normalize file in-place before Edit runs so old_string matches.
    // Also emit updatedInput with old_string normalized so padded old_string
    // from a pre-normalization read still finds its match in the now-normalized file.
    const editInput = data.tool_input || {};
    const editPath = editInput.file_path || "";
    if (!/\.(?:md|markdown)$/i.test(editPath)) process.exit(0);
    const editAbs = path.resolve(editPath);
    if (normalizeFileInPlace(editAbs) === null) process.exit(0);

    // Emit updatedInput with normalized old_string (if present) so that
    // padded old_string constructed from a pre-normalization read still matches.
    const oldString = editInput.old_string;
    if (typeof oldString === "string" && oldString.length > 0) {
      const normalizedOld = compressMarkdown(oldString);
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            updatedInput: {
              ...editInput,
              old_string: normalizedOld,
            },
          },
        }),
      );
    }
    process.exit(0);
  } catch (_) {
    // Never crash or block Claude due to a hook bug
    process.exit(0);
  }
});
