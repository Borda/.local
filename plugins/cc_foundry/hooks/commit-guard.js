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
//   Detection is on what the command does, not how it is spelled. The
//   invocation prefix is stripped (`env git push`, `GIT_TRACE=1 git push`,
//   `/usr/bin/git push`), git's global options are stripped (`git -C /path
//   push`), the string is split on shell operators and substitution boundaries
//   (`cd /x && git push`, `echo $(git push ...)`), a short cluster carrying f
//   counts as force (`git push -fu`), and a `+`-prefixed refspec (`git push
//   origin +main`) counts as force even though it names no force flag.
//   A push assembled at run time — via a variable, alias, or script — is beyond
//   what any string inspection can see; the deny list is the backstop there.
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

// Git's own global options sit between `git` and the subcommand, so a naive
// tokens[1] === "push" test misses `git -C /path push --force` entirely. Strip
// them first. The value-taking forms must consume their argument, or the value
// itself would be mistaken for the subcommand.
const GIT_GLOBAL_FLAGS_WITH_VALUE = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"]);

/**
 * Drop `git`'s global options from a token list, returning the tokens from the
 * subcommand onward. Input must already start with the `git` token.
 */
function stripGitGlobalFlags(tokens) {
  let i = 1;
  while (i < tokens.length) {
    const t = tokens[i];
    if (!t.startsWith("-")) break;
    // `--git-dir=/x` and `-c k=v` carry their value inline; the bare forms take
    // the next token.
    if (t.includes("=") || !GIT_GLOBAL_FLAGS_WITH_VALUE.has(t)) {
      i += 1;
    } else {
      i += 2;
    }
  }
  return tokens.slice(i);
}

// Split a command string into the segments a shell would run separately, so a
// push hidden after `&&`, `;`, `|`, `||` or inside `$(...)` / backticks is still
// inspected. Splitting on the operator characters is deliberately coarse: an
// operator inside quotes produces extra segments, which can only ever cause an
// extra check, never a missed one. That is why `(` and `)` are split points even
// though they also appear in ordinary subshells.
function shellSegments(command) {
  return command.split(/(?:\|\||&&|[;&|\n`()])/);
}

// A segment may reach git through a prefix that hides the literal `git` token:
// environment assignments (`GIT_TRACE=1 git push`), an `env` wrapper
// (`env git push`, `env -i VAR=v git push`), or an absolute path
// (`/usr/bin/git push`). All three reach the same remote.
const ENVIRONMENT_ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;

/**
 * Return a segment's tokens starting at the `git` token, or null when the
 * segment does not invoke git. The invocation prefix is stripped and argv[0] is
 * compared by basename, so a path or wrapper cannot hide the invocation.
 */
function gitTokens(segment) {
  const tokens = segment.trim().split(/\s+/).filter(Boolean);
  let i = 0;
  let sawEnv = false;
  while (i < tokens.length) {
    const t = tokens[i];
    if (ENVIRONMENT_ASSIGNMENT.test(t) || (sawEnv && t.startsWith("-"))) {
      i += 1;
      continue;
    }
    if (t === "env" || t.endsWith("/env")) {
      sawEnv = true;
      i += 1;
      continue;
    }
    break;
  }
  const rest = tokens.slice(i);
  const argv0 = (rest[0] || "").split(/[/\\]/).pop();
  return argv0 === "git" || argv0 === "git.exe" ? rest : null;
}

/**
 * True when a single command segment is a `git push` in any spelling.
 * Tolerates an invocation prefix and git's own global options.
 */
function isGitPushSegment(segment) {
  const tokens = gitTokens(segment);
  return tokens !== null && stripGitGlobalFlags(tokens)[0] === "push";
}

// Of git push's short options only `-f` uses the letter f, so any short cluster
// containing it is a force. Long options are matched on the `--force` prefix
// alone, which must not be widened to a substring test: `--follow-tags` also
// contains an f and is not a force.
function isForceFlag(token) {
  if (token.startsWith("--")) return token.startsWith("--force");
  return token.startsWith("-") && token.length > 1 && token.includes("f");
}

// A push carrying force in any spelling can never be authorized — checked before
// any sentinel so a valid push sentinel cannot bypass the force block.
//
// Spellings caught:
//   * `-f`, and any short cluster carrying it (`git push -fu origin main`)
//   * any `--force*` (--force, --force-with-lease, --force-if-includes)
//   * a `+`-prefixed refspec (`git push origin +main`) — a force push that
//     names no force flag at all.
//
// Detection is on the invocation, not on one literal spelling of it: the
// segment's prefix and git's global options are stripped first, so `env`,
// `VAR=v`, an absolute path and `git -C /path` all resolve to the same check.
// What remains uncovered is a push assembled at run time — through a variable,
// an alias, or a script — which no string inspection can see.
function isForcePush(command) {
  return shellSegments(command).some((segment) => {
    if (!isGitPushSegment(segment)) return false;
    const args = stripGitGlobalFlags(gitTokens(segment)).slice(1);
    if (args.some(isForceFlag)) return true;
    // Refspecs are the non-flag arguments after the remote. A leading `+` on any
    // of them requests a non-fast-forward update — a force push by another name.
    return args.some((t) => !t.startsWith("-") && t.startsWith("+"));
  });
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
  // Anchoring on /^\s*git push\b/ would miss `git -C /path push` and any push
  // placed after a shell operator; both reach the same remote. Inspect every
  // segment instead.
  if (!shellSegments(command).some(isGitPushSegment)) process.exit(0);

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
