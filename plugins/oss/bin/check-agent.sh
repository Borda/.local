#!/usr/bin/env bash
# Checks if a plugin agent is installed in the cache.
# Prints "true" or "false" to stdout; exits 0 always.
# Usage: check-agent.sh <plugin-name> <agent-name>
#   plugin-name: e.g. oss, foundry
#   agent-name:  e.g. shepherd (without .md extension)
PLUGIN="${1:?Usage: check-agent.sh <plugin-name> <agent-name>}"
AGENT="${2:?Usage: check-agent.sh <plugin-name> <agent-name>}"
if ! [[ "$PLUGIN" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "check-agent: invalid PLUGIN: '$PLUGIN'" >&2; exit 2
fi
if ! [[ "$AGENT" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "check-agent: invalid AGENT: '$AGENT'" >&2; exit 2
fi
if ls "${HOME}/.claude/plugins/cache/borda-ai-rig/${PLUGIN}/"*/agents/"${AGENT}.md" 2>/dev/null | grep -q .; then
    echo "true"
elif [ -f ".claude/agents/${AGENT}.md" ]; then
    echo "true"
else
    echo "false"
fi
