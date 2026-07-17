#!/usr/bin/env bash
# Sync plugin changes to ~/.claude/ and/or ~/.codex/
# Claude plugins install from the GitHub remote (versioned cache) — commit + push before running.
# Run from the project root: bash sync.sh [claude] [codex] [--no-clean]
#
# Arguments (order-independent):
#   claude   — sync Claude plugins + foundry:setup (default: both)
#   codex    — sync .codex/ configs to ~/.codex/   (default: both)
#   --no-clean — skip uninstall before reinstalling (default: uninstall first)
#
# foundry:setup runs headlessly at end of script — no manual step needed.

set -e

SYNC_CLAUDE=false
SYNC_CODEX=false
CLEAN=true

for arg in "$@"; do
    case "$arg" in
        claude)     SYNC_CLAUDE=true ;;
        codex)      SYNC_CODEX=true ;;
        --no-clean) CLEAN=false ;;
    esac
done

# Default: sync both
if ! $SYNC_CLAUDE && ! $SYNC_CODEX; then
    SYNC_CLAUDE=true
    SYNC_CODEX=true
fi

PLUGINS=(foundry oss develop research codemap)
EXTERNAL_PLUGINS=(codex@openai-codex caveman@caveman ponytail@ponytail)
MARKETPLACE=$(jq -r '.name' .claude-plugin/marketplace.json)
SETTINGS="$HOME/.claude/settings.json"
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"
INSTALLED_PLUGINS="$HOME/.claude/plugins/installed_plugins.json"
CACHE_DIR="$HOME/.claude/plugins/cache"
PROJECT_DIR="$(pwd)"
MARKETPLACE_REMOTE=$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null | sed 's/\.git$//')  # GitHub source for cache install

if $SYNC_CLAUDE; then

# Migrate all stale marketplace names registered for this path
# Checks known_marketplaces.json (authoritative CLI registry) for stale names
while IFS= read -r stale; do
    [[ -z "$stale" ]] && continue
    echo "Migrating marketplace '$stale' → '$MARKETPLACE'..."

    # 1. Rename cache dir (or remove stale if target already exists)
    if [[ -d "$CACHE_DIR/$stale" && ! -d "$CACHE_DIR/$MARKETPLACE" ]]; then
        mv "$CACHE_DIR/$stale" "$CACHE_DIR/$MARKETPLACE"
        echo "  ✓ cache dir renamed"
    elif [[ -d "$CACHE_DIR/$stale" ]]; then
        rm -rf "$CACHE_DIR/$stale"
        echo "  ✓ stale cache dir removed"
    fi

    # 2. known_marketplaces.json — rename marketplace key
    tmp=$(mktemp)
    jq --arg old "$stale" --arg new "$MARKETPLACE" '
      .[$new] = .[$old] | del(.[$old])
    ' "$KNOWN_MARKETPLACES" > "$tmp" && mv "$tmp" "$KNOWN_MARKETPLACES"

    # 3. installed_plugins.json — rename plugin keys + update installPath strings
    tmp=$(mktemp)
    jq --arg old "$stale" --arg new "$MARKETPLACE" '
      .plugins = (
        .plugins
        | with_entries(.key |= gsub($old; $new))
        | walk(if type == "string" then gsub($old; $new) else . end)
      )
    ' "$INSTALLED_PLUGINS" > "$tmp" && mv "$tmp" "$INSTALLED_PLUGINS"

    # 4. settings.json — remove stale entry + gsub all string occurrences
    tmp=$(mktemp)
    jq --arg old "$stale" --arg new "$MARKETPLACE" '
      del(.extraKnownMarketplaces[$old]) |
      walk(
        if type == "string" then gsub($old; $new)
        elif type == "object" then with_entries(.key |= gsub($old; $new))
        else .
        end
      )
    ' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"

    echo "  ✓ registries updated ($stale → $MARKETPLACE)"
done < <(jq -r --arg path "$PROJECT_DIR" --arg new "$MARKETPLACE" '
  to_entries
  | map(select(.value.source.path == $path and .key != $new))
  | .[].key
' "$KNOWN_MARKETPLACES")

if $CLEAN; then
    echo "Uninstalling existing plugins..."
    for p in "${PLUGINS[@]}"; do
        claude plugin uninstall "${p}@${MARKETPLACE}" 2>/dev/null && echo "  ✓ uninstalled ${p}" || echo "  – ${p} not installed, skipping"
    done
fi

echo "Refreshing external plugin marketplaces..."
claude plugin marketplace add openai/codex-plugin-cc 2>/dev/null && echo "  ✓ openai-codex refreshed" || echo "  ⚠ openai-codex refresh failed (offline?)"
claude plugin marketplace add JuliusBrussee/caveman   2>/dev/null && echo "  ✓ caveman refreshed"      || echo "  ⚠ caveman refresh failed (offline?)"
claude plugin marketplace add DietrichGebert/ponytail 2>/dev/null && echo "  ✓ ponytail refreshed"     || echo "  ⚠ ponytail refresh failed (offline?)"

echo "Updating external plugins..."
for p in "${EXTERNAL_PLUGINS[@]}"; do
    claude plugin uninstall "$p" 2>/dev/null && echo "  ✓ uninstalled $p" || echo "  – $p not installed, skipping"
    claude plugin install "$p" && echo "  ✓ $p" || echo "  ✗ $p install failed"
done

echo "Registering marketplace (GitHub source → versioned cache install)..."
# GitHub source installs the pushed commit into ~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/,
# so CLAUDE_PLUGIN_ROOT resolves under ~/.claude/ (not this live working tree). A local
# directory source (`add ./`) always live-links and never caches — see plugin-marketplaces docs.
# GitHub source installs the REMOTE commit — warn loudly if it differs from local HEAD
LOCAL_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null)
REMOTE_SHA=$(git ls-remote "$MARKETPLACE_REMOTE" HEAD 2>/dev/null | awk '{print $1}')
if [ -z "$REMOTE_SHA" ]; then
    echo "  ⚠ cannot reach $MARKETPLACE_REMOTE — skipping SHA check (offline or auth?)"
elif [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "  ┌──────────────────────────────────────────────────────────────"
    echo "  │ ⚠ LOCAL ≠ REMOTE — cache will install the REMOTE commit, not your local work"
    echo "  │   local  HEAD: $LOCAL_SHA"
    echo "  │   remote HEAD: $REMOTE_SHA"
    echo "  │   → commit + push first, or these plugins install a stale/different version"
    echo "  └──────────────────────────────────────────────────────────────"
fi
claude plugin marketplace remove "$MARKETPLACE" 2>/dev/null || true  # drop any stale directory-source registration
claude plugin marketplace add "$MARKETPLACE_REMOTE"

echo "Installing plugins..."
for p in "${PLUGINS[@]}"; do
    claude plugin install "${p}@${MARKETPLACE}" && echo "  ✓ ${p}"
done

echo "Initializing Foundry (sync settings + symlinks)..."
claude --print "/foundry:setup --approve"

fi  # SYNC_CLAUDE

if $SYNC_CODEX; then

echo "Syncing .codex configs to ~/.codex/..."
CODEX_SRC="$PROJECT_DIR/.codex"
CODEX_DST="$HOME/.codex"
for f in config.toml hooks.json AGENTS.md README.md; do
    [[ -f "$CODEX_SRC/$f" ]] && cp "$CODEX_SRC/$f" "$CODEX_DST/$f" && echo "  ✓ $f"
done
for d in agents skills hooks; do
    [[ -d "$CODEX_SRC/$d" ]] && rsync -a --no-perms "$CODEX_SRC/$d/" "$CODEX_DST/$d/" && echo "  ✓ $d/"
done

fi  # SYNC_CODEX

echo "✓ Done"
