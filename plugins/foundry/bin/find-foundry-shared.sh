#!/usr/bin/env bash
# Resolves foundry plugin's _shared/ directory via tiered cascade.
# Tier 0: CLAUDE_PLUGIN_ROOT (canonical at runtime — fastest, most correct)
# Tier 1: installed_plugins.json registry (active installed version)
# Tier 2: cache semver scan, skipping orphaned dirs
# Tier 3: source-tree fallback (local dev only; warns to stderr)
# Prints resolved path to stdout; exits 0 always (caller validates existence).

# Tier 0: CLAUDE_PLUGIN_ROOT set → use it directly
if [ -n "$CLAUDE_PLUGIN_ROOT" ] && [ -d "$CLAUDE_PLUGIN_ROOT/skills/_shared" ]; then
    echo "$CLAUDE_PLUGIN_ROOT/skills/_shared"
    exit 0
fi

# Tier 1: installed_plugins.json registry
HELPER="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/get_plugin_install_path.py}"
[ -z "$HELPER" ] && HELPER=$(ls "$HOME/.claude/plugins/cache/borda-ai-rig/foundry/"*/bin/get_plugin_install_path.py 2>/dev/null | sort -V | tail -1)
[ -z "$HELPER" ] && HELPER="plugins/foundry/bin/get_plugin_install_path.py"
if [ -f "$HELPER" ]; then
    install_path=$(python "$HELPER" borda-ai-rig foundry 2>/dev/null)
    if [ -n "$install_path" ] && [ -d "$install_path/skills/_shared" ]; then
        echo "$install_path/skills/_shared"
        exit 0
    fi
fi

# Tier 2: cache semver scan, skip orphaned dirs
path=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry" -maxdepth 3 -type d -name "_shared" 2>/dev/null \
    | while IFS= read -r p; do
        ver_dir=$(dirname "$(dirname "$p")")
        [ -f "$ver_dir/.orphaned_at" ] && continue
        echo "$p"
      done \
    | sort -V | tail -1)
if [ -n "$path" ]; then
    echo "$path"
    exit 0
fi

# Tier 3: source-tree fallback (local dev)
printf "find-foundry-shared: foundry plugin not in cache or registry — using source-tree fallback (local dev only)\n" >&2
echo "plugins/foundry/skills/_shared"
