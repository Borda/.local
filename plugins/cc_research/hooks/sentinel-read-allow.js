#!/usr/bin/env node
// sentinel-read-allow.js — PreToolUse hook (matcher: Bash)
//
// PURPOSE
//   Plugin skills persist cross-block state via TMPDIR sentinel files read with
//   `VAR=$(cat "${TMPDIR:-/tmp}/<name>-${CSID}")`. The `$(...)` command
//   substitution makes settings.json prefix allow-rules fail-closed, so every
//   such command — written verbatim in versioned plugin MD files — raises a
//   "Contains expansion" permission prompt in subagents. This hook auto-allows
//   exactly that pre-canned blueprint idiom; everything else passes through
//   (exit 0, no output) to normal permission + deny checking. Custom or
//   on-the-fly code therefore stays gated.
//
// SECURITY MODEL — why the allow is safe
//   Unlike rtk-rewrite.js we emit NO updatedInput: the ORIGINAL command string
//   is allowed unchanged, so settings.json deny rules keep matching it (deny is
//   evaluated regardless of a hook allow decision). The allow fires only when
//   ALL of the following are proven:
//
//     1. ≥1 blueprint ANCHOR is present: a substitution matching a blueprint
//        shape — the sentinel read (path starts with the literal
//        `${TMPDIR:-/tmp}/`) or the timestamp idiom `$(date [-u] +FORMAT)` — or
//        the substitution-free rewritten idiom `IFS= read -r VAR < "${TMPDIR:-
//        /tmp}/…"` (READ_FORM). The read form needs the hook too: prefix
//        allow-rules match on the first token, and its first token is the
//        `IFS=` assignment, so no allow entry can ever match it.
//        UNQUOTED paths/defaults use a strict filename
//        charset (FNCHAR) that excludes EVERY shell metacharacter, so an
//        unquoted span can never carry `;`/`>`/`&`/`|`/`<` that the shell would
//        act on (`$(cat ${TMPDIR:-/tmp}/x;rm y)` is rejected). Quoted paths keep
//        their bytes literal (content between `"` is data), and both forbid `$(`,
//        backticks, and backslashes and confine `${...}` to plain parameter
//        expansions — so no nested command substitution can hide in a span.
//     2. No `..` traversal anywhere; after removing safe spans, NO other `$(`,
//        backtick, `<(`, `>(`, or heredoc remains.
//     3. Quoted regions are masked by a state-machine scanner (handles \" and
//        '...'), so quote tricks cannot smuggle a separator past segmentation.
//     4. No loader/lookup-poisoning assignment (PATH, LD_PRELOAD, IFS≠empty, …).
//     5. The only WRITE-capable redirects reject: stderr-silence / stdout-to-null
//        (`2>/dev/null`, `2>&1`, `N>/dev/null`, `N>&M`) are stripped, then any
//        remaining `>` rejects. Input `<` is allowed — the `read < file` idiom
//        needs it and it is no more capable than a whitelisted token reading the
//        same path as an argument (`Bash(cat:*)` already reads any file).
//     6. Every segment (split on newline ; & | && ||), after stripping leading
//        VAR=... assignments, starts with a strictly non-writing whitelisted
//        token (see SAFE_TOKENS — find/mkdir/touch/sort/jq/date deliberately
//        excluded because segment validation does not inspect arguments).
//        Guarded CLIs (git, gh, rm, curl, ...) are NOT whitelisted → passthrough.
//
//   False negatives (odd-but-safe commands passing through to a prompt) are
//   acceptable; false positives (allowing a mutation, a write, a spawned
//   process, or lookup-path hijack) are not — every ambiguity resolves toward
//   passthrough. ACCEPTED residual: a whitelisted read-only token can disclose
//   an arbitrary readable file it is given as an operand (incl. via an unquoted
//   `${VAR}` that word-splits) — non-escalating, since `Bash(cat:*)` et al.
//   already read any file promptless. Reviewed adversarially (Codex) 2026-07-22,
//   two passes; all confirmed bypasses closed.
//
// EXIT CODES
//   0  always — passthrough (no output) or allow (JSON to stdout)

"use strict";

// ── Sentinel-read shape ───────────────────────────────────────────────────────
// ${VAR} / ${VAR:-plain-default} — no nested `$(`/backtick/backslash/parens.
const PE = "\\$\\{[A-Za-z_]\\w*(?::-[^}$`()\\\\]*)?\\}";
// $VAR
const PV = "\\$[A-Za-z_]\\w*";
// Strict filename charset for UNQUOTED contexts — every shell metacharacter
// (; & | < > ( ) { } $ ` ' " \ space) is excluded so an unquoted path/default
// can NEVER carry a command separator, redirect, or substitution that the
// shell would execute. Only literal filename bytes + `${...}`/`$VAR` via the
// alternations below. (`..` traversal is rejected separately in isAllowable.)
const FNCHAR = "[A-Za-z0-9_./-]";
// Quoted sentinel path: "${TMPDIR:-/tmp}/..." — content between the double
// quotes is shell-LITERAL, so `;`/`>`/`&` inside are harmless data. Only `$`
// and backtick (which would re-enable expansion) are excluded; `${...}`/`$VAR`
// are re-admitted via the alternation. No injection is possible from here.
const QPATH = '"\\$\\{TMPDIR:-/tmp\\}/(?:[^"$`\\\\]|' + PE + "|" + PV + ')*"';
// Unquoted sentinel path: ${TMPDIR:-/tmp}/... — strict charset + `${...}` only.
// Bare `$VAR` (PV) is intentionally NOT admitted here: no blueprint unquoted
// path uses it (they use `${CSID}`/`${_CM_PROJ}` = PE), and an attacker-set
// `$X=" /etc/passwd"` would word-split into an arbitrary-read operand.
const UPATH = "\\$\\{TMPDIR:-/tmp\\}/(?:" + FNCHAR + "|" + PE + ")*";
// `|| echo <default>` — double-quoted (literal, `$`/backtick excluded),
// single-quoted (fully literal), $VAR/${VAR}, or a strict-charset bare word.
const DFLT = '(?:"(?:[^"$`\\\\]|' + PE + "|" + PV + ")*\"|'[^']*'|" + PE + "|" + PV + "|" + FNCHAR + "+)";
const SENTINEL_READ =
  "\\$\\(\\s*cat\\s+(?:" +
  QPATH +
  "|" +
  UPATH +
  ")" +
  "(?:\\s+2>/dev/null)?(?:\\s*\\|\\|\\s*echo\\s+" +
  DFLT +
  ")?\\s*\\)";
// Blueprint timestamp idiom: `$(date -u +%Y-%m-%dT%H-%M-%SZ)` / `$(date +%s)` — a lone
// +FORMAT argument only; any extra argument or separator falls outside the class → reject.
const DATE_STAMP = "\\$\\(\\s*date\\s+(?:-u\\s+)?\\+[%\\w:.+-]*\\s*\\)";
const SAFE_SUBST = new RegExp(SENTINEL_READ + "|" + DATE_STAMP, "g");
// Substitution-free rewritten sentinel idiom (see claude-config.md §TMPDIR
// Sentinel Scoping): `IFS= read -r VAR < "${TMPDIR:-/tmp}/…"`. Counts as a
// blueprint anchor only — it adds no capability (read < is already permitted
// in §5 and `read` is in SAFE_TOKENS); its sole job is to let a command with
// ZERO substitutions qualify, because the leading `IFS=` assignment means no
// prefix allow-rule can ever match the rewritten form.
const READ_FORM = new RegExp("(?:IFS=\\s+)?read\\s+-r\\s+[A-Za-z_]\\w*\\s*<\\s*(?:" + QPATH + "|" + UPATH + ")");

// Strictly non-writing, non-spawning first tokens. A whitelisted token must not
// be able to write a file, create a dir, spawn a process, or change host state
// with ANY flag or operand — because segment validation checks only the leading
// token, never its arguments. Deliberately EXCLUDED for that reason:
//   find   — `-exec`/`-execdir`/`-ok` spawn arbitrary commands, `-delete` removes,
//            `-fprintf`/`-fprint` write files
//   mkdir  — creates directories
//   touch  — creates/updates files
//   sort   — `-o FILE`/`--output` writes
//   date   — `--set` mutates the clock (and only ever appears inside `$(date +FMT)`,
//            handled by DATE_STAMP — never needed as a bare segment token)
//   jq     — complex; keep out of an allow path that skips argument inspection
// Also excluded (pass through to the real allow/deny matcher): git, gh, rm, mv,
// cp, curl, sed, awk, xargs, python, node, tee, dd, ...
const SAFE_TOKENS = new Set([
  "cat",
  "ls",
  "grep",
  "head",
  "tail",
  "wc",
  "echo",
  "printf",
  "basename",
  "dirname",
  "cut",
  "tr",
  "uniq",
  "test",
  "[",
  "[[",
  "true",
  ":",
  "export",
  "read",
]);

/**
 * Mask quoted regions with 'Q' so shell metacharacters inside quotes cannot
 * confuse segmentation. Handles \x escapes outside and inside double quotes.
 * Assumes no `$(`/backtick remains (checked by caller) — quoted content is
 * then pure data + parameter expansion.
 */
function maskQuotes(s) {
  let out = "";
  let state = "plain"; // plain | single | double
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (state === "plain") {
      if (c === "\\") {
        out += "QQ";
        i++;
        continue;
      } // escaped char = data
      if (c === "'") {
        state = "single";
        out += "Q";
        continue;
      }
      if (c === '"') {
        state = "double";
        out += "Q";
        continue;
      }
      out += c;
    } else if (state === "single") {
      if (c === "'") {
        state = "plain";
      }
      out += "Q";
    } else {
      // double
      if (c === "\\") {
        out += "QQ";
        i++;
        continue;
      }
      if (c === '"') {
        state = "plain";
      }
      out += "Q";
    }
  }
  // Unterminated quote = malformed command → force rejection downstream.
  return state === "plain" ? out : out + "$(";
}

/** True when every segment of `masked` starts with a whitelisted token. */
function segmentsAreReadOnly(masked) {
  const segments = masked.split(/[\n;|&]+/);
  for (const seg of segments) {
    const t = seg.trim();
    if (!t) continue;
    // Strip leading VAR=... assignments (covers `IFS= read`, `RUN_DIR=SREAD`).
    const rest = t.replace(/^(?:[A-Za-z_]\w*=\S*\s*)+/, "");
    if (!rest) continue; // pure assignment segment
    const first = rest.match(/^\S+/)[0];
    if (!SAFE_TOKENS.has(first)) return false;
  }
  return true;
}

// Assignments that could redirect which binary a later whitelisted token runs,
// or alter parsing/loader behaviour — reject even though the token itself is
// "safe" (e.g. `export PATH=/tmp/evil:$PATH; V=$(cat …)` would run a planted
// `cat`). `IFS=` is allowed ONLY when empty (the `IFS= read` idiom); a non-empty
// IFS assignment is rejected.
const SENSITIVE_ASSIGN =
  /(?:^|[\s;|&(){])(?:export\s+|declare\s+\S+\s+|typeset\s+\S+\s+)?(?:PATH|LD_PRELOAD|LD_LIBRARY_PATH|DYLD_INSERT_LIBRARIES|DYLD_LIBRARY_PATH|BASH_ENV|ENV|SHELLOPTS|BASHOPTS|GLOBIGNORE|PS4|CDPATH|BASH_FUNC)=/;
const NONEMPTY_IFS = /(?:^|[\s;|&(])(?:export\s+)?IFS=[^\s;|&]/;

/** Decide whether `cmd` is provably just blueprint sentinel-reads + read-only follow-ups. */
function isAllowable(cmd) {
  if (cmd.includes("`")) return false;
  // Path traversal has no place in a blueprint sentinel path; reject anywhere.
  if (cmd.includes("..")) return false;
  // Loader / lookup-poisoning assignments defeat the read-only-token guarantee.
  if (SENSITIVE_ASSIGN.test(cmd) || NONEMPTY_IFS.test(cmd)) return false;
  // Replace safe substitution spans (sentinel reads / date stamps); require at
  // least one blueprint anchor: a safe substitution OR the rewritten read-form
  // sentinel idiom. Without an anchor (e.g. plain `ls -la`), passthrough — this
  // hook only fronts for blueprint idioms the prefix matcher cannot express.
  let spans = 0;
  const remaining = cmd.replace(SAFE_SUBST, () => {
    spans++;
    return "SREAD";
  });
  if (spans === 0 && !READ_FORM.test(cmd)) return false;
  // Any other substitution / process substitution / heredoc → not our idiom.
  if (remaining.includes("$(") || remaining.includes("<(") || remaining.includes(">(")) return false;
  if (remaining.includes("<<")) return false;
  const masked = maskQuotes(remaining);
  if (masked.includes("$(")) return false; // unterminated-quote marker
  // Strip stderr-silence / stdout-to-null forms, then reject any remaining WRITE
  // redirect (`>`, `>>`, `>|`, fd-dup `N>&M`). Input `<` is intentionally allowed:
  // the `read` blueprint form (`IFS= read -r VAR < "$F"`) needs it, and it grants
  // nothing beyond what a whitelisted read-only token already does with a path
  // argument (`Bash(cat:*)` etc. already read any file without a prompt).
  const noRedirects = masked.replace(/(?:\d*>\/dev\/null|\d*>&\d+|2>&1)/g, "");
  if (noRedirects.includes(">")) return false;
  return segmentsAreReadOnly(noRedirects);
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(raw);
    if (data.tool_name !== "Bash") {
      process.exit(0);
    }
    const cmd = ((data.tool_input && data.tool_input.command) || "").trim();
    if (!cmd || !isAllowable(cmd)) {
      process.exit(0);
    }
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason:
            "plugin blueprint idiom — ${TMPDIR:-/tmp} sentinel read (subst or read-form) / date stamp only, all segments read-only",
        },
      }),
    );
    process.exit(0);
  } catch (_) {
    // Never crash or block Claude due to a hook bug
    process.exit(0);
  }
});
