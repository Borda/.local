#!/usr/bin/env bash
# Install AI-Rig plugins for Claude Code and/or Codex from the GitHub remote.
# Codex sync also mirrors this checkout's normal-session model defaults and personal policy into $CODEX_HOME.
# Remote installs use pushed state — commit and push before running; release tags are optional pins.
# Run from the project root: bash sync.sh [claude] [codex] [clear] [--no-clean] [--codex-ref REF] [--external-plugin-timeout-seconds SECONDS] [--no-codex-global-agents]
#
# Arguments (order-independent):
#   claude   — sync Claude plugins + their installed setup skills (default: both).
#              Also purges plugins this rig has retired (see PURGE_PLUGINS below);
#              codex@openai-codex is purged only once bridge installs in the same run.
#   codex    — install or update Codex Rig, Codemap, and bridge, run Bridge's free static host check, then mirror this checkout's Codex session policy (default: both)
#   clear    — teardown instead of install: uninstall this marketplace's Claude plugins
#              + Codex Rig, Codemap, and bridge, and strip the managed block from $CODEX_HOME/AGENTS.md
#              (a timestamped backup is kept). Honors claude/codex scoping (default: both sides).
#              Leaves marketplace registrations and the external caveman plugin in place.
#   --no-clean — skip uninstall before reinstalling (default: uninstall first)
#   --codex-ref REF — pin Codex Rig to one Git ref (default: latest default branch)
#   --external-plugin-timeout-seconds SECONDS — bound each external marketplace/plugin command (default: 120)
#   --no-codex-global-agents — leave $CODEX_HOME/AGENTS.md unchanged; model defaults still mirror
#
# Setup skills shipped by installed non-Bridge managed plugins run headlessly at the end of Claude sync. Bridge is
# excluded from Claude model dispatch; Codex sync runs Bridge's installed static diagnosis directly without model
# inference. Bridge authentication and live MCP verification remain explicit skill actions.

set -e

SYNC_CLAUDE=false
SYNC_CODEX=false
CLEAN=true
CLEAR=false
CODEX_REF=""
EXTERNAL_PLUGIN_TIMEOUT_SECONDS="${EXTERNAL_PLUGIN_TIMEOUT_SECONDS:-120}"
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
        --external-plugin-timeout-seconds)
            shift
            if [[ $# -eq 0 || -z "$1" ]]; then
                echo "  ✗ --external-plugin-timeout-seconds requires a positive integer"
                exit 2
            fi
            EXTERNAL_PLUGIN_TIMEOUT_SECONDS="$1"
            ;;
        --external-plugin-timeout-seconds=*)
            EXTERNAL_PLUGIN_TIMEOUT_SECONDS="${1#*=}"
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
if [[ ! "$EXTERNAL_PLUGIN_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "  ✗ --external-plugin-timeout-seconds requires a positive integer"
    exit 2
fi

PLUGINS=(foundry oss develop research codemap-py bridge)
EXTERNAL_PLUGINS=(caveman@caveman)
MARKETPLACE=$(jq -r '.name' .claude-plugin/marketplace.json)
SETTINGS="$HOME/.claude/settings.json"
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"
INSTALLED_PLUGINS="$HOME/.claude/plugins/installed_plugins.json"
CACHE_DIR="$HOME/.claude/plugins/cache"
PROJECT_DIR="$(pwd)"
MARKETPLACE_REMOTE=$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null | sed 's/\.git$//')  # GitHub source for cache install
CODEX_SYNC_SCRIPT="$PROJECT_DIR/plugins/codex-rig/scripts/sync_codex.py"
CODEX_HOME_SYNC_SCRIPT="$PROJECT_DIR/scripts/sync_codex_session_policy.py"
TIMEOUT_RUNNER="$PROJECT_DIR/scripts/run_with_timeout.py"

if $CLEAR; then
    if $SYNC_CLAUDE; then
        echo "Clearing Claude marketplace plugins..."
        for p in "${PLUGINS[@]}"; do
            claude plugin uninstall "${p}@${MARKETPLACE}" 2>/dev/null && echo "  ✓ uninstalled ${p}" || echo "  – ${p} not installed, skipping"
        done
    fi
    if $SYNC_CODEX; then
        echo "Clearing Codex plugins..."
        python3 "$CODEX_SYNC_SCRIPT" clear
    fi
    echo "✓ Cleared (managed plugins uninstalled; marketplace registrations + caveman left in place)"
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

run_external_plugin_command() {
    local label="$1"
    shift
    python3 "$TIMEOUT_RUNNER" --timeout-seconds "$EXTERNAL_PLUGIN_TIMEOUT_SECONDS" --label "$label" -- "$@"
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
if ! run_external_plugin_command "caveman marketplace registration" claude plugin marketplace add JuliusBrussee/caveman 2>/dev/null; then
    echo "  ⚠ caveman marketplace registration failed or timed out; trying the existing registration"
fi
CAVEMAN_OK=false
if run_external_plugin_command "caveman marketplace refresh" claude plugin marketplace update caveman 2>/dev/null; then
    echo "  ✓ caveman refreshed"
    CAVEMAN_OK=true
else
    external_status=$?
    if [[ $external_status -eq 124 ]]; then
        echo "  ⚠ caveman refresh timed out after ${EXTERNAL_PLUGIN_TIMEOUT_SECONDS}s"
    else
        echo "  ⚠ caveman refresh failed (offline?)"
    fi
fi

echo "Updating external plugins..."
# Skip uninstall/reinstall when this plugin's marketplace refresh failed (offline) —
# otherwise a network blip uninstalls a working plugin and leaves it uninstalled.
for p in "${EXTERNAL_PLUGINS[@]}"; do
    case "$p" in
        caveman@caveman)     mkt_ok=$CAVEMAN_OK ;;
        *)                   mkt_ok=false ;;
    esac
    if [[ "$mkt_ok" != "true" ]]; then
        echo "  – skipping $p reinstall, marketplace refresh failed"
        continue
    fi
    if run_external_plugin_command "$p uninstall" claude plugin uninstall "$p" 2>/dev/null; then
        echo "  ✓ uninstalled $p"
    else
        external_status=$?
        if [[ $external_status -eq 124 ]]; then
            echo "  ⚠ $p uninstall timed out; skipping reinstall"
            continue
        fi
        echo "  – $p not installed, skipping uninstall"
    fi
    if run_external_plugin_command "$p install" claude plugin install "$p"; then
        print_claude_plugin_identity "$p"
    else
        external_status=$?
        if [[ $external_status -eq 124 ]]; then
            echo "  ✗ $p install timed out after ${EXTERNAL_PLUGIN_TIMEOUT_SECONDS}s"
        else
            echo "  ✗ $p install failed"
        fi
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
BRIDGE_INSTALLED=false
FAILED_INSTALLS=0
for p in "${PLUGINS[@]}"; do
    if claude plugin install "${p}@${MARKETPLACE}"; then
        print_claude_plugin_identity "${p}@${MARKETPLACE}"
        if [[ "$p" == "bridge" ]]; then
            BRIDGE_INSTALLED=true
        fi
    else
        echo "  ✗ ${p}@${MARKETPLACE} install failed"
        FAILED_INSTALLS=$((FAILED_INSTALLS + 1))
    fi
done

# Purge step — retire plugins this rig no longer uses. A failed uninstall is not an error
# here: the ordinary cause is the plugin already being absent, and nothing downstream
# depends on it having been present. Add an entry to retire it from every synced machine.
PURGE_PLUGINS=(ponytail@ponytail)
# codex@openai-codex is the one conditional entry — it is the integration the bridge
# replaces, so it is retired only once its replacement actually installed in this same run.
# A failed bridge install leaves the working legacy plugin in place for recovery.
if $BRIDGE_INSTALLED; then
    PURGE_PLUGINS+=(codex@openai-codex)
fi

echo "Purging retired plugins..."
for p in "${PURGE_PLUGINS[@]}"; do
    if claude plugin uninstall "$p" 2>/dev/null; then
        echo "  ✓ purged ${p}"
    else
        echo "  – ${p} not installed, nothing to purge"
    fi
done

echo "Initializing installed plugin setup skills..."
for p in "${PLUGINS[@]}"; do
    install_path=$(jq -r --arg plugin "${p}@${MARKETPLACE}" '
      (.plugins[$plugin] // [])
      | map(select(.installPath?))
      | sort_by(.installedAt // "")
      | last // {}
      | .installPath // ""
    ' "$INSTALLED_PLUGINS")
    if [[ -z "$install_path" ]]; then
        echo "  – ${p} not installed, skipping setup"
        continue
    fi
    if [[ "$p" == "bridge" ]]; then
        bridge_doctor="$install_path/bin/bridge_diagnose.py"
        if [[ ! -f "$bridge_doctor" || -L "$bridge_doctor" ]]; then
            echo "  ✗ bridge static diagnosis is incomplete or linked" >&2
            exit 1
        fi
        if ! python_version=$(python3 --version 2>&1); then
            echo "  ✗ bridge requires Python 3.10 or newer" >&2
            exit 1
        fi
        if [[ ! "$python_version" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
            echo "  ✗ bridge requires Python 3.10 or newer" >&2
            exit 1
        fi
        if (( BASH_REMATCH[1] < 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] < 10) )); then
            echo "  ✗ bridge requires Python 3.10 or newer; found $python_version" >&2
            exit 1
        fi
        # A Claude-only machine legitimately has no codex CLI; probing the codex
        # direction there would abort the whole sync before the Codex stage and
        # the summary. Check the direction that is actually installed, and keep
        # the hard failure for a present-but-broken host surface.
        if command -v codex >/dev/null 2>&1; then
            bridge_direction="codex"
        else
            echo "  – codex CLI not found; bridge diagnosis covers the claude direction only"
            bridge_direction="claude"
        fi
        if ! bridge_diagnosis=$(python3 "$bridge_doctor" --direction "$bridge_direction"); then
            echo "  ✗ bridge static diagnosis command failed" >&2
            exit 1
        fi
        if ! jq -e '(.ok == true and .live == false and .payload.complete == true)' <<<"$bridge_diagnosis" >/dev/null; then
            echo "  ✗ bridge static diagnosis failed" >&2
            exit 1
        fi
        echo "  ✓ bridge static diagnosis passed; no provider call made"
        continue
    fi
    setup_skill=""
    for candidate in "$install_path/skills/setup/SKILL.md" "$install_path/claude-skills/setup/SKILL.md"; do
        if [[ -f "$candidate" ]]; then
            setup_skill="$candidate"
            break
        fi
    done
    if [[ -z "$setup_skill" ]]; then
        echo "  – ${p} has no setup skill, skipping"
        continue
    fi
    echo "  → ${p}:setup"
    claude --print "/${p}:setup --approve"
done

fi  # SYNC_CLAUDE

if $SYNC_CODEX; then
CODEX_SYNC_ARGS=(install)
if [[ -n "$CODEX_REF" ]]; then
    CODEX_SYNC_ARGS+=(--codex-ref "$CODEX_REF")
fi
if ! $CLEAN; then
    CODEX_SYNC_ARGS+=(--no-clean)
fi
if ! $INSTALL_CODEX_GLOBAL_AGENTS; then
    CODEX_SYNC_ARGS+=(--no-codex-global-agents)
fi
python3 "$CODEX_SYNC_SCRIPT" "${CODEX_SYNC_ARGS[@]}"
CODEX_HOME_SYNC_ARGS=(
    --source-config "$PROJECT_DIR/.codex/config.toml"
    --source-policy "$PROJECT_DIR/.codex/global-session-policy.md"
    --codex-home "${CODEX_HOME:-$HOME/.codex}"
)
if ! $INSTALL_CODEX_GLOBAL_AGENTS; then
    CODEX_HOME_SYNC_ARGS+=(--skip-policy)
fi
python3 "$CODEX_HOME_SYNC_SCRIPT" "${CODEX_HOME_SYNC_ARGS[@]}"

fi  # SYNC_CODEX

# A per-plugin install failure is survivable — the other plugins installed and the retired
# ones were left alone — but the run did not do what it was asked to, so it must not exit 0
# and report success. Callers and CI branch on this; the summary line names the count.
if [[ ${FAILED_INSTALLS:-0} -gt 0 ]]; then
    echo "⚠ Done with ${FAILED_INSTALLS} failed install(s) — rerun after checking network and marketplace access"
    exit 1
fi
echo "✓ Done"
