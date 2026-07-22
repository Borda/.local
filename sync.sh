#!/usr/bin/env bash
# Install AI-Rig plugins for Claude Code and/or Codex from the GitHub remote.
# Remote installs use pushed state — commit and push before running; release tags are optional pins.
# Run from the project root: bash sync.sh [claude] [codex] [clear] [--no-clean] [--codex-ref REF] [--no-codex-global-agents]
#
# Arguments (order-independent):
#   claude   — sync Claude plugins + foundry:setup (default: both)
#   codex    — install or update the Codex Rig plugin (default: both)
#   clear    — teardown instead of install: uninstall this marketplace's Claude plugins
#              + the Codex Rig plugin, and strip the managed block from $CODEX_HOME/AGENTS.md
#              (a timestamped backup is kept). Honors claude/codex scoping (default: both sides).
#              Leaves marketplace registrations and external plugins (caveman/ponytail/openai-codex) in place.
#   --no-clean — skip uninstall before reinstalling (default: uninstall first)
#   --codex-ref REF — pin Codex Rig to one Git ref (default: latest default branch)
#   --no-codex-global-agents — skip Codex Rig's managed block in $CODEX_HOME/AGENTS.md
#
# foundry:setup runs headlessly at end of script — no manual step needed.

set -e

SYNC_CLAUDE=false
SYNC_CODEX=false
CLEAN=true
CLEAR=false
CODEX_REF=""
INSTALL_CODEX_GLOBAL_AGENTS=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        claude)     SYNC_CLAUDE=true ;;
        codex)      SYNC_CODEX=true ;;
        clear)      CLEAR=true ;;
        --no-clean) CLEAN=false ;;
        --codex-ref)
            shift
            if [[ $# -eq 0 || -z "$1" ]]; then
                echo "  ✗ --codex-ref requires a non-empty Git ref"
                exit 2
            fi
            CODEX_REF="$1"
            ;;
        --codex-ref=*)
            CODEX_REF="${1#*=}"
            if [[ -z "$CODEX_REF" ]]; then
                echo "  ✗ --codex-ref requires a non-empty Git ref"
                exit 2
            fi
            ;;
        --no-codex-global-agents) INSTALL_CODEX_GLOBAL_AGENTS=false ;;
        *)
            echo "  ✗ unknown argument: $1"
            exit 2
            ;;
    esac
    shift
done

# Default: sync both
if ! $SYNC_CLAUDE && ! $SYNC_CODEX; then
    SYNC_CLAUDE=true
    SYNC_CODEX=true
fi
if [[ -n "$CODEX_REF" ]] && ! $SYNC_CODEX; then
    echo "  ✗ --codex-ref requires Codex sync"
    exit 2
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
CODEX_SYNC_SCRIPT="$PROJECT_DIR/plugins/codex-rig/scripts/sync_codex.py"

if $CLEAR; then
    if $SYNC_CLAUDE; then
        echo "Clearing Claude marketplace plugins..."
        for p in "${PLUGINS[@]}"; do
            claude plugin uninstall "${p}@${MARKETPLACE}" 2>/dev/null && echo "  ✓ uninstalled ${p}" || echo "  – ${p} not installed, skipping"
        done
    fi
    if $SYNC_CODEX; then
        echo "Clearing Codex Rig..."
        python3 "$CODEX_SYNC_SCRIPT" clear
    fi
    echo "✓ Cleared (Standard: plugins uninstalled; marketplace registrations + external plugins left in place)"
    exit 0
fi

print_claude_plugin_identity() {
    local plugin_id="$1"
    local identity
    identity=$(jq -r --arg plugin "$plugin_id" '
      (.plugins[$plugin] // [])
      | sort_by(.lastUpdated // "")
      | last // {}
      | [(.version // "unknown"), (.gitCommitSha // "unknown")]
      | @tsv
    ' "$INSTALLED_PLUGINS" 2>/dev/null || printf 'unknown\tunknown')
    local version="${identity%%$'\t'*}"
    local revision="${identity#*$'\t'}"
    [[ "$revision" != "unknown" ]] && revision="${revision:0:12}"
    echo "  ✓ ${plugin_id}: version ${version}, revision ${revision}"
}

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
    if claude plugin install "$p"; then
        print_claude_plugin_identity "$p"
    else
        echo "  ✗ $p install failed"
    fi
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
    if claude plugin install "${p}@${MARKETPLACE}"; then
        print_claude_plugin_identity "${p}@${MARKETPLACE}"
    fi
done

echo "Initializing Foundry (sync settings + symlinks)..."
claude --print "/foundry:setup --approve"

fi  # SYNC_CLAUDE

if $SYNC_CODEX; then
CODEX_SYNC_ARGS=(install)
if [[ -n "$CODEX_REF" ]]; then
    CODEX_SYNC_ARGS+=(--codex-ref "$CODEX_REF")
fi
if ! $INSTALL_CODEX_GLOBAL_AGENTS; then
    CODEX_SYNC_ARGS+=(--no-codex-global-agents)
fi
python3 "$CODEX_SYNC_SCRIPT" "${CODEX_SYNC_ARGS[@]}"

fi  # SYNC_CODEX

echo "✓ Done"
