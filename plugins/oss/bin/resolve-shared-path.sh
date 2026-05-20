#!/usr/bin/env bash
# Resolves a plugin's _shared/ (or named subdir) from registry with cache fallback.
# Tier 0: installed_plugins.json registry (authoritative installed version)
# Tier 1: cache semver scan, skipping orphaned version dirs
# Tier 2: source-tree fallback (local dev only; warns to stderr)
# Prints resolved path to stdout; exits 0 always (caller validates existence).
# Usage: resolve-shared-path.sh <plugin-name> <subdir>
#   plugin-name: e.g. oss, foundry
#   subdir:      e.g. skills/_shared
PLUGIN="${1:?Usage: resolve-shared-path.sh <plugin-name> <subdir>}"
SUBDIR="${2:?Usage: resolve-shared-path.sh <plugin-name> <subdir>}"
if ! [[ "$PLUGIN" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "resolve-shared-path: invalid PLUGIN: '$PLUGIN'" >&2
    exit 2
fi
if ! [[ "$SUBDIR" =~ ^[a-zA-Z0-9_/-]+$ ]] || [[ "$SUBDIR" == *".."* ]]; then
    echo "resolve-shared-path: invalid SUBDIR: '$SUBDIR'" >&2
    exit 2
fi

# Tier 0: installed_plugins.json registry — look up the active install path.
HELPER="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/get_plugin_install_path.py}"
[ -z "$HELPER" ] && HELPER=$(ls "$HOME/.claude/plugins/cache/borda-ai-rig/foundry/"*/bin/get_plugin_install_path.py 2>/dev/null | sort -V | tail -1)
[ -z "$HELPER" ] && HELPER="plugins/foundry/bin/get_plugin_install_path.py"
if [ -f "$HELPER" ]; then
    install_path=$(python "$HELPER" borda-ai-rig "$PLUGIN" 2>/dev/null)
    if [ -n "$install_path" ] && [ -d "$install_path/$SUBDIR" ]; then
        echo "$install_path/$SUBDIR"
        exit 0
    fi
fi

# Tier 1: cache semver scan, skip orphaned dirs.
# The bash glob expands `*` to a single version segment, so for a SUBDIR like
# `skills/_shared` the matched path is `.../<plugin>/<version>/skills/_shared`.
# Walk up from the match until we find a dir whose parent's basename equals
# `<plugin>` — that is the version dir. Skip if it carries `.orphaned_at`.
path=$(ls -d "${HOME}/.claude/plugins/cache/borda-ai-rig/${PLUGIN}/"*"/${SUBDIR}" 2>/dev/null \
    | while IFS= read -r p; do
        ver_dir="$p"
        # Walk up until parent is <plugin> (i.e. ver_dir is the version segment).
        while [ "$(basename "$(dirname "$ver_dir")")" != "$PLUGIN" ] && [ "$ver_dir" != "/" ] && [ -n "$ver_dir" ]; do
            ver_dir=$(dirname "$ver_dir")
        done
        # If we walked off the top without finding the plugin parent, skip safely.
        [ "$ver_dir" = "/" ] && continue
        [ -f "$ver_dir/.orphaned_at" ] && continue
        echo "$p"
      done \
    | sort -V | tail -1)
if [ -n "$path" ]; then
    echo "$path"
    exit 0
fi

# Tier 2: source-tree fallback (local dev only).
printf "resolve-shared-path: %s/%s not in cache or registry — using source-tree fallback (local dev only)\n" "$PLUGIN" "$SUBDIR" >&2
echo "plugins/${PLUGIN}/${SUBDIR}"
