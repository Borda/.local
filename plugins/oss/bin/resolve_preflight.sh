#!/usr/bin/env bash
# resolve_preflight.sh — preflight checks for /oss:resolve Step 1.
#
# Verifies tool availability (codex optional, gh required), authentication,
# remote state. Pulls latest if remote ahead. Caches positive results under
# .claude/state/preflight/ with a 4h TTL so repeat invocations short-circuit.
#
# Output:
#   stdout — KEY=value lines (eval'd by caller): CODEX_AVAILABLE, GH_OK
#   stderr — human-readable status (echoed to terminal)
#
# Exit:
#   0 — all required checks passed (codex absence is non-fatal)
#   1 — required check failed (gh missing, gh unauthenticated, git pull
#       conflict, or other hard error)
#
# Caller pattern:
#   eval "$("${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_preflight.sh" 2>/dev/null)"  # timeout: 15000
set -euo pipefail

# Status messages go to stderr so they appear in the terminal but do not
# pollute the KEY=value output that the caller eval's.
log() { printf '%s\n' "$*" >&2; }

# Preflight cache helpers — TTL 4 hours, keyed per binary.
_PREFLIGHT_DIR=".claude/state/preflight"
preflight_ok() {
    local f="$_PREFLIGHT_DIR/$1.ok"
    [ -f "$f" ] && [ $(($(date +%s) - $(cat "$f"))) -lt 14400 ]
}
preflight_pass() {
    mkdir -p "$_PREFLIGHT_DIR"
    date +%s >"$_PREFLIGHT_DIR/$1.ok"
}

# --- codex (optional) ---------------------------------------------------------
CODEX_AVAILABLE=false
if preflight_ok codex; then
    CODEX_AVAILABLE=true
    log "codex (openai-codex): ok (cached)"
elif claude plugin list 2>/dev/null | grep -q 'codex@openai-codex'; then
    preflight_pass codex
    CODEX_AVAILABLE=true
    log "codex (openai-codex): ok"
else
    log "codex (openai-codex): missing — complex multi-file action items will be skipped; simple items implemented via foundry:sw-engineer (see Step 8 degradation)"
fi

# --- gh (required) ------------------------------------------------------------
if preflight_ok gh; then
    log "gh: ok (cached)"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    preflight_pass gh
    AUTH_LINE=$(gh auth status 2>&1 | grep 'Logged in' | head -1 | xargs || true)
    log "gh: ok ($AUTH_LINE)"
elif command -v gh >/dev/null 2>&1; then
    log "Pre-flight failed: gh found but not authenticated — run: gh auth login"
    exit 1
else
    log "Pre-flight failed: gh not found — install: brew install gh"
    exit 1
fi

# --- git state ----------------------------------------------------------------
# Show current remotes — confirms correct repo and surfaces fork remotes.
git remote -v >&2 || true

# Sync with remote — prevents `git merge --continue` being called out of state.
UPSTREAM=$(git rev-parse --abbrev-ref '@{u}' 2>/dev/null || true)
if [ -n "$UPSTREAM" ]; then
    git fetch origin 2>/dev/null || true
    REMOTE_AHEAD=$(git log HEAD..'@{u}' --oneline 2>/dev/null | wc -l | tr -d ' ')
    if [ "${REMOTE_AHEAD:-0}" -gt 0 ]; then
        log "Remote is $REMOTE_AHEAD commit(s) ahead — running git pull..."
        if git pull >&2; then
            log "✓ git pull: merged"
        else
            log "Pre-flight failed: git pull had conflicts — resolve manually before running /resolve"
            exit 1
        fi
    else
        log "✓ git: up to date"
    fi
fi

# --- emit KEY=value to stdout for caller eval ---------------------------------
printf 'CODEX_AVAILABLE=%s\n' "$CODEX_AVAILABLE"
printf 'GH_OK=true\n'
