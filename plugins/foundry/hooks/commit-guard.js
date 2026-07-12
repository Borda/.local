// commit-guard.js — multi-event hook
//
// PURPOSE
//   Claude must never commit or push autonomously.
//
//   COMMIT: prompt-discipline only, no hook enforcement. Claude must invoke
//   AskUserQuestion before every `git commit`, any branch, no exceptions —
//   this is a documented rule (rules/git-commit.md), not a runtime check.
//   The hook does not intercept `git commit` at all.
//
// PUSH AUTHORIZATION (hook-enforced)
//   Force-push is forbidden on every branch, always — a hard, unconditional
//   block. No sentinel bypasses it: the force check runs before any sentinel
//   lookup, so even a valid push sentinel cannot authorize `git push --force`.
//
//   Regular (non-force) `git push` requires a per-branch sentinel:
//     /tmp/claude-push-auth-<repo-slug>-<branch-slug>  (15-min TTL)
//   There is no auto-arm shortcut — a "push"-mentioning prompt never creates
//   it. The push sentinel can only be created by the user's own shell
//   (`! touch ...`) after Claude has confirmed the push via AskUserQuestion.
//   A Claude-run touch of an auth sentinel is read by the harness classifier
//   as forging the guard, so Claude must never create it itself.
//
// HOW IT WORKS
//   1. PreToolUse(Bash): fires only on `git push` calls.
//      Force-push forbidden unconditionally (exit 2 before any sentinel
//      check); otherwise checks the push sentinel present and fresh.
//   2. SessionStart: wipes all /tmp/claude-push-auth-* sentinels so
//      prior-session auth never carries over.
//   3. UserPromptSubmit: /clear → wipes all sentinel files for the repo.
//
// EXIT CODES
//   0  Allow (push sentinel present and fresh, or command isn't `git push`).
//   2  Block — push sentinel missing/expired, or push is a force-push
//      (force-push blocked unconditionally); stderr shown to Claude.

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execSync } = require("child_process");

function getSentinelDir() {
  return process.platform === "win32" ? os.tmpdir() : "/tmp";
}

const TTL_MS = 15 * 60 * 1000; // 15 min — push sentinel

function toSlug(s) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function runGit(cmd) {
  return execSync(cmd, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
}

function getRepoSlug() {
  try {
    return toSlug(path.basename(runGit("git rev-parse --show-toplevel")));
  } catch {
    return null;
  }
}

function getCurrentBranch() {
  try {
    return runGit("git branch --show-current") || null; // empty = detached HEAD
  } catch {
    return null;
  }
}

function getPushSentinelPath(repoSlug, branchSlug) {
  return `${getSentinelDir()}/claude-push-auth-${repoSlug}-${branchSlug}`;
}

// A push carrying -f / --force* can never be authorized — checked before any
// sentinel so a valid push sentinel cannot bypass the force block.
function isForcePush(command) {
  const tokens = command.trim().split(/\s+/);
  if (tokens[0] !== "git" || tokens[1] !== "push") return false;
  return tokens.slice(2).some((t) => t === "-f" || t.startsWith("--force"));
}

function checkSentinel(sentinelPath, ttlMs) {
  try {
    const stat = fs.statSync(sentinelPath);
    const ageMs = Date.now() - stat.mtimeMs;
    if (ageMs > ttlMs) {
      try {
        fs.unlinkSync(sentinelPath);
      } catch {}
      return "expired";
    }
    return "valid";
  } catch {
    return "missing";
  }
}

// Wipe all push-auth sentinel files for a given prefix pattern.
function wipeSentinels(prefix) {
  try {
    const files = fs.readdirSync(getSentinelDir());
    for (const f of files) {
      const isPushAuth = prefix ? f.startsWith(`claude-push-auth-${prefix}-`) : f.startsWith("claude-push-auth-");
      if (isPushAuth) {
        try {
          fs.unlinkSync(path.join(getSentinelDir(), f));
        } catch {}
      }
    }
  } catch {}
}

let raw = "";
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    process.exit(0);
  }

  const { hook_event_name, tool_name, tool_input } = data;

  // --- SessionStart: wipe leftover sentinels from prior sessions ---
  if (hook_event_name === "SessionStart") {
    const repoSlug = getRepoSlug();
    if (repoSlug) wipeSentinels(repoSlug);
    process.exit(0);
  }

  // --- UserPromptSubmit: wipe on /clear ---
  if (hook_event_name === "UserPromptSubmit") {
    const prompt = (data.prompt || data.user_message || "").trim();

    if (/^\/clear\b/.test(prompt)) {
      const repoSlug = getRepoSlug();
      if (repoSlug) wipeSentinels(repoSlug);
    }

    process.exit(0);
  }

  // --- PreToolUse: guard git push (git commit is prompt-discipline only) ---
  if (tool_name !== "Bash") process.exit(0);

  const command = (tool_input && tool_input.command) || "";
  if (!/^\s*git push\b/.test(command)) process.exit(0);

  // Force-push is forbidden on any branch, always — checked before any
  // sentinel, so a valid push sentinel never bypasses it.
  if (isForcePush(command)) {
    process.stderr.write(
      `git push blocked — force-push is forbidden on any branch. No override, no sentinel bypasses this.\n`,
    );
    process.exit(2);
  }

  const repoSlug = getRepoSlug();
  const branch = getCurrentBranch();

  if (!repoSlug || !branch) {
    process.stderr.write(
      "git push blocked — could not determine repo/branch for authorization check.\n" +
        "Ensure you are inside a git repository on a named branch (not detached HEAD).\n",
    );
    process.exit(2);
  }

  const branchSlug = toSlug(branch);
  const pushSentinel = getPushSentinelPath(repoSlug, branchSlug);
  const pushStatus = checkSentinel(pushSentinel, TTL_MS);
  if (pushStatus !== "valid") {
    const reason =
      pushStatus === "expired" ? "authorization expired (15-min TTL)" : "no push authorization for this branch";
    process.stderr.write(
      `git push blocked — ${reason}.\n` +
        `Pushes are never auto-armed. Invoke AskUserQuestion to confirm the push,\n` +
        `then ask the user to authorize from their own shell (Claude may not touch the sentinel —\n` +
        `the harness classifier reads a Claude-run touch as forging the guard):\n` +
        `  ! touch ${pushSentinel}\n` +
        `Then run git push. After push, the user removes it:\n` +
        `  ! rm -f ${pushSentinel}\n`,
    );
    process.exit(2);
  }

  process.exit(0);
});
