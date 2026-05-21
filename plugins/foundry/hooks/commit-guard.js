// commit-guard.js — multi-event hook
//
// PURPOSE
//   Claude must never commit autonomously. The commit discipline rule
//   ("never commit without explicit user request in same message") lives in
//   a prompt instruction — not enforced at runtime. This hook enforces it
//   at the tool level: every `git commit` Bash call is blocked unless a
//   skill explicitly opted in via a sentinel file for that repo+branch.
//
//   Sentinel path: /tmp/claude-commit-auth-<repo-slug>-<branch-slug>
//   TTL: 15 min — auto-expires if a skill crashes before cleanup.
//
// DEFAULT BRANCH PROTECTION (second gate)
//   Commits to the repo's default branch require a second sentinel:
//     /tmp/claude-commit-default-<repo-slug>-<branch-slug>
//   TTL: 5 min — tighter window; must be created immediately before commit.
//   Path B (ad-hoc): AskUserQuestion must explicitly confirm default branch
//     commit; only then touch both sentinels.
//   Path A (skill pre-auth): skill must touch both sentinels if it commits
//     to the default branch (rare — most skills work on feature branches).
//
//   Default branch resolved by priority:
//     1. git symbolic-ref refs/remotes/origin/HEAD
//     2. gh repo view --json defaultBranchRef
//     3. git remote show origin | grep "HEAD branch:"
//     4. null → skip default-branch gate (cannot determine)
//
// HOW IT WORKS
//   1. PreToolUse(Bash): only fires on `git commit` calls.
//      Derives repo slug + branch slug → checks sentinel path present and fresh.
//      Sentinel valid → check default branch → exit 0 or exit 2.
//   2. SessionStart: wipes all /tmp/claude-commit-auth-* and
//      /tmp/claude-commit-default-* sentinels so prior-session auth never carries over.
//   3. UserPromptSubmit:
//      a. /clear → wipes all sentinel files for the current repo.
//      b. Explicit commit instruction detected ("commit", "commit this", "make a commit",
//         etc.) → auto-creates Gate 1 sentinel for current repo+branch. This removes the
//         touch/rm approval-click overhead: sentinel already exists when Claude calls
//         `git commit`, so no intermediate Bash calls needed.
//         Gate 2 (default-branch protection) is NOT auto-created — default branch commits
//         still require AskUserQuestion confirmation from Claude.
//
// EXIT CODES
//   0  Allow (sentinel present and fresh, default-branch gate passed).
//   2  Block — no sentinel, expired, or default-branch gate failed; stderr shown to Claude.

"use strict";

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const TTL_MS = 15 * 60 * 1000; // 15 min — regular sentinel
const DEFAULT_BRANCH_TTL_MS = 5 * 60 * 1000; // 5 min — default-branch sentinel

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

// Resolve default branch by three methods in priority order.
// Returns branch name string or null if unresolvable.
function getDefaultBranch() {
  // 1. git symbolic-ref — fastest, works offline, requires `git fetch` to have run
  try {
    const ref = runGit("git symbolic-ref refs/remotes/origin/HEAD");
    if (ref) return ref.replace(/^refs\/remotes\/[^/]+\//, "");
  } catch {}

  // 2. gh CLI — accurate, requires auth; skip if gh not available
  try {
    const name = runGit("gh repo view --json defaultBranchRef --jq .defaultBranchRef.name");
    if (name && name !== "null") return name;
  } catch {}

  // 3. git remote show — makes network call; slowest fallback
  try {
    const out = runGit("git remote show origin");
    const m = out.match(/HEAD branch:\s+(\S+)/);
    if (m) return m[1];
  } catch {}

  return null; // cannot determine — skip default-branch gate
}

function getSentinelPath(repoSlug, branchSlug) {
  return `/tmp/claude-commit-auth-${repoSlug}-${branchSlug}`;
}

function getDefaultBranchSentinelPath(repoSlug, branchSlug) {
  return `/tmp/claude-commit-default-${repoSlug}-${branchSlug}`;
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

// Wipe all sentinel files for a given prefix pattern.
function wipeSentinels(prefix) {
  try {
    const files = fs.readdirSync("/tmp");
    for (const f of files) {
      const isAuth = prefix ? f.startsWith(`claude-commit-auth-${prefix}-`) : f.startsWith("claude-commit-auth-");
      const isDefault = prefix
        ? f.startsWith(`claude-commit-default-${prefix}-`)
        : f.startsWith("claude-commit-default-");
      if (isAuth || isDefault) {
        try {
          fs.unlinkSync(path.join("/tmp", f));
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

  // --- UserPromptSubmit: wipe on /clear; auto-sentinel on explicit commit request ---
  if (hook_event_name === "UserPromptSubmit") {
    const prompt = (data.prompt || data.user_message || "").trim();

    if (/^\/clear\b/.test(prompt)) {
      const repoSlug = getRepoSlug();
      if (repoSlug) wipeSentinels(repoSlug);
      process.exit(0);
    }

    // Auto-create Gate 1 sentinel when user explicitly requests a commit.
    // Patterns: "commit [this/it/...]", "please commit", "make a commit", etc.
    // Gate 2 (default-branch) is intentionally NOT auto-created — requires AskUserQuestion.
    const COMMIT_RE = /^commit\b|\bplease\s+commit\b|\bmake\s+a\s+commit\b|\bgo\s+ahead\s+and\s+commit\b/i;
    if (COMMIT_RE.test(prompt)) {
      const repoSlug = getRepoSlug();
      const branch = getCurrentBranch();
      if (repoSlug && branch) {
        const branchSlug = toSlug(branch);
        const sentinel = getSentinelPath(repoSlug, branchSlug);
        try {
          fs.writeFileSync(sentinel, "");
        } catch {}
      }
    }

    process.exit(0);
  }

  // --- PreToolUse: guard git commit ---
  if (tool_name !== "Bash") process.exit(0);

  const command = (tool_input && tool_input.command) || "";
  if (!/^\s*git commit\b/.test(command)) process.exit(0);

  // Resolve repo + branch slugs
  const repoSlug = getRepoSlug();
  const branch = getCurrentBranch();

  if (!repoSlug || !branch) {
    process.stderr.write(
      "git commit blocked — could not determine repo/branch for authorization check.\n" +
        "Ensure you are inside a git repository on a named branch (not detached HEAD).\n",
    );
    process.exit(2);
  }

  const branchSlug = toSlug(branch);
  const sentinel = getSentinelPath(repoSlug, branchSlug);

  // Gate 1: regular sentinel
  const sentinelStatus = checkSentinel(sentinel, TTL_MS);
  if (sentinelStatus === "missing") {
    process.stderr.write(
      `git commit blocked — no commit authorization for this branch.\n` +
        `Skills like /oss:resolve and /research:run set this automatically.\n` +
        `For ad-hoc commits: invoke AskUserQuestion to confirm, ` +
        `then touch ${sentinel} before git commit, rm -f ${sentinel} after.\n`,
    );
    process.exit(2);
  }
  if (sentinelStatus === "expired") {
    process.stderr.write(
      `git commit blocked — authorization expired (15-min TTL).\n` +
        `Re-run the skill or touch ${sentinel} after user confirmation.\n`,
    );
    process.exit(2);
  }

  // Gate 2: default-branch protection
  const defaultBranch = getDefaultBranch();
  if (defaultBranch && branch === defaultBranch) {
    const dbSentinel = getDefaultBranchSentinelPath(repoSlug, branchSlug);
    const dbStatus = checkSentinel(dbSentinel, DEFAULT_BRANCH_TTL_MS);
    if (dbStatus === "missing") {
      process.stderr.write(
        `git commit blocked — committing to default branch '${branch}' requires explicit confirmation.\n` +
          `Invoke AskUserQuestion to confirm committing directly to '${branch}',\n` +
          `then touch both sentinels before git commit:\n` +
          `  touch ${sentinel}\n` +
          `  touch ${dbSentinel}\n` +
          `Remove both after commit:\n` +
          `  rm -f ${sentinel} ${dbSentinel}\n`,
      );
      process.exit(2);
    }
    if (dbStatus === "expired") {
      process.stderr.write(
        `git commit blocked — default-branch authorization expired (5-min TTL).\n` +
          `Touch ${dbSentinel} immediately before git commit (5-min window).\n`,
      );
      process.exit(2);
    }
  }

  process.exit(0);
});
