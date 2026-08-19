# Recursion guard

> A new outer call mints one `run_id` and starts at depth zero. Before the peer starts, the transport writes incremented depth to `CC_CODEX_BRIDGE_DEPTH`; the peer CLI and plugin MCP process inherit it. A caller may report a greater depth but cannot lower the inherited value, and negative depth is rejected. A host receiving trusted depth one or greater returns `refused: recursion-depth` without dispatching a peer.

> Inner Codex calls use `--ignore-user-config`; inner Claude calls use `--setting-sources ""` with `--strict-mcp-config`. These settings are a second independent stop and do not replace the in-band depth check: they strip the bridge's own plugin surface from the child, so even a hop that loses the depth variable to a curated host environment cannot reach the bridge tools again.

> Health and incident records include both depth and run_id so all hops in one call tree can be correlated without a separate tracing system.
