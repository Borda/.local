#!/usr/bin/env node
// artifact-guard.js — PostToolUse hook
//
// PURPOSE
//   Closes the gap between the compression rules in quality-gates.md
//   (.reports/ = normal caveman, .temp/ = ultra caveman, ~10K token soft
//   cap) and reality — those rules are prose instructions agents must
//   remember mid-task, with no write-time signal when they drift. This
//   hook gives the writing agent same-turn feedback instead of relying on
//   a later audit pass over files that, by the time anyone reads them
//   again, are already "done."
//
// HOW IT WORKS
//   1. Fires on every PostToolUse event for the Write and Edit tools.
//   2. Resolves the written file's path relative to the project root;
//      skips anything outside the project or outside .reports/ or .temp/,
//      and anything not a .md file — this hook only judges prose artifacts.
//   3. Reads the file's on-disk size (already written by the time
//      PostToolUse fires) and estimates tokens via bytes/4.
//   4. Cap is a soft compression target, not a truncation trigger — see
//      quality-gates.md §Prose Compression. Over-cap feedback asks the
//      agent to cut filler/duplication first; it never tells the agent to
//      drop findings, and structurally large artifacts (multi-agent
//      aggregates) are expected to legitimately run over.
//   5. For .temp/ files (ultra-caveman tier) also runs a crude prose-style
//      proxy: article density (the/a/an per 100 words). High density reads
//      as full-sentence prose, not the fragments-only style the tier
//      expects — flagged as a heuristic, not a hard rule.
//   6. Any trigger writes a single combined message to stderr and exits 2
//      so Claude sees it and can act; nothing to report exits 0 silently.
//
// EXIT CODES
//   0  File under cap and (if .temp/) article density under threshold, or
//      file/path out of scope for this hook.
//   1  (unused — logging hook; internal errors fall through to exit 0)
//   2  Cap and/or tier-style feedback surfaced for Claude to act on.

const fs = require("fs");
const path = require("path");

const TOKEN_CAP = 10000;
const ARTICLE_DENSITY_THRESHOLD_PCT = 4;

function estimateTokens(byteLength) {
  return Math.ceil(byteLength / 4);
}

function articleDensityPct(text) {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return 0;
  const articles = text.match(/\b(the|a|an)\b/gi) || [];
  return (articles.length / words.length) * 100;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);
    const { hook_event_name, tool_name, tool_input } = data;

    if (hook_event_name !== "PostToolUse") process.exit(0);
    if (tool_name !== "Write" && tool_name !== "Edit") process.exit(0);

    const filePath = tool_input?.file_path;
    if (!filePath) process.exit(0);

    const root = process.cwd();
    const rel = path.relative(root, filePath);
    if (rel.startsWith("..") || path.isAbsolute(rel)) process.exit(0);
    if (!rel.endsWith(".md")) process.exit(0);

    const relNormalized = rel.split(path.sep).join("/");
    const inReports = relNormalized.startsWith(".reports/");
    const inTemp = relNormalized.startsWith(".temp/");
    if (!inReports && !inTemp) process.exit(0);

    let stat;
    try {
      stat = fs.statSync(filePath);
    } catch (_) {
      process.exit(0); // file gone or unreadable — nothing to check
    }

    const tokens = estimateTokens(stat.size);
    const messages = [];

    if (tokens > TOKEN_CAP) {
      messages.push(
        `${relNormalized}: ~${tokens} tokens, soft cap ~${TOKEN_CAP}. ` +
          `Cap is a compression target, not a truncation trigger — trim filler/duplication first, ` +
          `never drop findings or CRITICAL/HIGH content to fit. Large aggregate/batch reports legitimately ` +
          `run over; only fix if the size comes from verbosity, not substance.`,
      );
    }

    if (inTemp) {
      let content;
      try {
        content = fs.readFileSync(filePath, "utf8");
      } catch (_) {
        content = "";
      }
      const density = articleDensityPct(content);
      if (density > ARTICLE_DENSITY_THRESHOLD_PCT) {
        messages.push(
          `${relNormalized}: article density ~${density.toFixed(1)}% — reads as full-sentence prose. ` +
            `.temp/ handover files are ultra-caveman tier (fragments only, zero filler) per quality-gates.md. ` +
            `Heuristic only — ignore if the content is inherently fragment-hostile (code, tables, YAML).`,
        );
      }
    }

    if (messages.length === 0) process.exit(0);

    process.stderr.write(messages.join("\n"));
    process.exit(2);
  } catch (_) {
    // Logging hook — never block or crash Claude on internal errors.
    process.exit(0);
  }
});
