#!/usr/bin/env node
// md-compress.js — PreToolUse hook
//
// PURPOSE
//   MD files (config, reports, plans, handover, skills) are dense with
//   pipe-table column padding that wastes tokens without adding meaning.
//   This hook is one leg of a two-hook system keeping file state consistent
//   between what Claude reads and what it edits:
//
//   Read path (this hook): compresses markdown content and serves it from a
//     session-scoped temp file — original file is NEVER modified on Read.
//     Emits updatedInput redirecting Claude to the temp file.
//
//   Edit path (this hook): normalizes source file in-place before Edit runs.
//     Ensures old_string from a prior compressed read still finds its match
//     even if the file was modified with padding between Read and Edit.
//     Also emits updatedInput with old_string normalized so padded old_string
//     from a pre-compression read matches the now-normalized file.
//
//   Post-edit (lint-on-save.js): runs pre-commit after every Write/Edit,
//     applying mdformat + trailing-whitespace. File stays normalized.
//
// COMPRESSIONS (outside fenced code blocks only)
//     1. Table column padding: collapses 2+ spaces on pipe-table lines to 1.
//     2. Consecutive blank lines: collapses runs of 2+ blanks to 1.
//     3. Trailing whitespace: strips trailing spaces on every non-fence line.
//
// HOW IT WORKS — Read path
//   1. Parse stdin JSON; skip non-Read/Edit tools or non-.md files (exit 0).
//   2. Read source file; skip on error (exit 0).
//   3. Run compressMarkdown; if unchanged, exit 0 (passthrough, no temp file).
//   4. Write compressed content to session-scoped temp file (original untouched).
//   5. Emit updatedInput with file_path = tempFilePath (preserving limit/offset).
//
// HOW IT WORKS — Edit path
//   1. Detect Edit tool on a .md/.markdown file.
//   2. Read source file; if unreadable or empty, exit 0.
//   3. Run compressMarkdown; if unchanged, skip disk write.
//   4. Write normalized content back to source file in place (so old_string matches).
//   5. Emit updatedInput with old_string = compressMarkdown(old_string) if present,
//      plus all other Edit fields unchanged.
//
// EXIT CODES
//   0  passthrough (non-.md file, read error, no-op, or successful rewrite)

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

function getSentinelDir() {
  return process.platform === "win32" ? os.tmpdir() : "/tmp";
}

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
  let consecutiveBlanks = 0;

  for (const line of lines) {
    const trimmed = line.trimStart();

    // --- Fence tracking ---
    if (!inFence) {
      const m = trimmed.match(/^(`{3,}|~{3,})/);
      if (m) {
        inFence = true;
        fenceChar = m[1][0];
        consecutiveBlanks = 0;
        out.push(line); // preserve fence line as-is
        continue;
      }
    } else {
      const m = trimmed.match(/^(`{3,}|~{3,})/);
      if (m && m[1][0] === fenceChar) {
        inFence = false;
        fenceChar = "";
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

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);

    // Only handle Read and Edit tool calls
    if (data.tool_name !== "Read" && data.tool_name !== "Edit") {
      process.exit(0);
    }

    // Edit path: normalize file in-place before Edit runs so old_string matches.
    // Also emit updatedInput with old_string normalized so padded old_string
    // from a compressed-read still finds its match in the now-normalized file.
    if (data.tool_name === "Edit") {
      const editInput = data.tool_input || {};
      const editPath = editInput.file_path || "";
      if (!/\.(?:md|markdown)$/i.test(editPath)) process.exit(0);
      const editAbs = path.resolve(editPath);
      let editContent;
      try {
        editContent = fs.readFileSync(editAbs, "utf8");
      } catch (_) {
        process.exit(0);
      }
      if (!editContent) process.exit(0);
      const editNorm = compressMarkdown(editContent);
      if (editNorm !== editContent) {
        try {
          fs.writeFileSync(editAbs, editNorm, "utf8");
        } catch (_) {}
      }
      // Emit updatedInput with normalized old_string (if present) so that
      // padded old_string constructed from a compressed read still matches.
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
    }

    // Read path
    const input = data.tool_input || {};
    const filePath = input.file_path || "";

    // Only process markdown files
    if (!/\.(?:md|markdown)$/i.test(filePath)) {
      process.exit(0);
    }

    // Resolve absolute path
    const absPath = path.resolve(filePath);

    // Read source file
    let content;
    try {
      content = fs.readFileSync(absPath, "utf8");
    } catch (_) {
      process.exit(0); // unreadable — pass through unchanged
    }

    if (!content) {
      process.exit(0); // empty — nothing to compress
    }

    // Compress
    const compressed = compressMarkdown(content);

    // If content unchanged after compression, passthrough — no temp file needed.
    // This also handles repeated reads of already-normalized files.
    if (compressed === content) {
      process.exit(0);
    }

    // Compute session-scoped temp dir.
    // session_id follows same sanitization as lint-on-save.js.
    const sessionId = data.session_id || "default";
    const sid = sessionId.replace(/[^a-zA-Z0-9_-]/g, "_");
    const tmpDir = `${getSentinelDir()}/claude-state-${sid}/md-compress`;

    // Ensure temp dir exists (mkdirSync with recursive is safe if already present).
    try {
      fs.mkdirSync(tmpDir, { recursive: true });
    } catch (_) {
      // If we can't create temp dir, passthrough rather than crash
      process.exit(0);
    }

    // Temp file name: sha1 of original absolute path (first 16 hex chars) + .md
    const hash = crypto.createHash("sha1").update(absPath).digest("hex").slice(0, 16);
    const tempFilePath = `${tmpDir}/${hash}.md`;

    // Write compressed content to temp file — original file is NEVER touched.
    try {
      fs.writeFileSync(tempFilePath, compressed, "utf8");
    } catch (_) {
      // Can't write temp file — passthrough unchanged
      process.exit(0);
    }

    // Emit updatedInput redirecting Claude to the temp file.
    // Preserve limit / offset / lines fields from original input.
    const updatedInput = { ...input, file_path: tempFilePath };

    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          updatedInput,
        },
      }),
    );
    process.exit(0);
  } catch (_) {
    // Never crash or block Claude due to a hook bug
    process.exit(0);
  }
});
