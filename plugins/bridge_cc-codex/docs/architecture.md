# Architecture and transport

`bridge_CC-Codex` is a self-contained package with the normalized plugin identifier `bridge` and two host integrations. The Claude Code integration starts the Codex command-line interface through `bin/bridge_call.py`; the Codex integration exposes three tools through the stdio MCP server declared in `.mcp.json` and starts Claude Code through that server.

## Request directions

| Direction | Entry point | Peer process | Transport requirement |
| -- | -- | -- | -- |
| Claude Code to Codex | `claude-skills/implement`, `claude-skills/advise`, `claude-skills/review` and `bin/bridge_call.py` | `codex exec` | Direct local command-line invocation; MCP is not required. |
| Codex to Claude Code | `codex-skills/implement`, `codex-skills/advise`, `codex-skills/review` and `bridge_mcp.py` | `claude --print` | The bridge MCP server is required for this direction. |

MCP is therefore complementary to the bridge as a whole, but mandatory for its Codex-to-Claude Code half. A one-way Claude Code-to-Codex installation can operate without MCP. A full bidirectional installation needs the MCP declaration so the Codex host can launch `bin/bridge_mcp.py` outside the model sandbox and use the Claude Code command-line interface through the host's normal authentication context.

The reverse transport is intentionally not implemented as a shell command issued by a sandboxed Codex model turn. The host-launched server owns the process boundary, validates JSON-RPC input, invokes `claude --print`, and returns one compact bridge envelope. The peer/model-to-harness result contains the six decision fields plus bounded verbose `details`; the harness persists `details` in the raw transcript and strips them from the public envelope, which carries decisions, blockers, and remaining work in its decision-critical fields, along with observed metadata and workspace-relative transcript or incident references. Transcript-only `details` provide additional evidence and never hide required work. This keeps the supported authentication path and the transport boundary in one installed package while keeping routine host context small.

## MCP surface

The server implements the MCP methods required for startup and tool use: `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`. `tools/list` advertises exactly three tools:

- `bridge_implement` performs one bounded write-capable request.
- `bridge_advise` performs one read-only request.
- `bridge_review` performs one read-only adversarial review.

Every tool requires a non-empty `task` and accepts optional `model`, `effort`, `timeout_seconds`, `depth`, `run_id`, and `supported_efforts`. The server supplies the trusted workspace selected by the host. `workspace`, `background`, and `session_id` are not accepted as model-controlled MCP arguments, so a tool call cannot select a different workspace or request detached execution through the reverse route.

## Process and result boundaries

`bin/bridge_call.py` is the shared supervisor for both directions. It selects the peer command, applies the verb's permission mode, supplies the structured result schema, enforces the soft-budget hard cutoff, validates the model-authored six-field core, adds observed harness metadata, and writes bridge artifacts under `.temp/bridge/` in the selected workspace. Review requests use a read-only general Codex execution with an explicit adversarial-review prompt and the same structured result contract; they do not depend on Codex's native review subcommand.

The public result is a JSON object with decision-critical `status`, `verdict`, `findings`, `files_touched`, `remaining`, and `blockers`, plus harness-owned metadata such as `model`, `effort`, `duration_seconds`, `depth`, `run_id`, `transcript_path`, `verb`, and `direction`. Decisions, blockers, and remaining work stay in the public envelope; peer `details` are transcript-only additional evidence and cannot hide required work. A fault's `incident` field points to a compact diagnostic record. Model output cannot claim process timing, cost, lifecycle, identity, or correlation metadata.

The recursion guard starts an outer request at `depth` zero, propagates the trusted value through `CC_CODEX_BRIDGE_DEPTH`, and refuses a peer dispatch at depth one or greater. A new `run_id` correlates records across the two hosts without treating a Codex thread identifier as a Claude session identifier.

## Permission model

`implement` uses `workspace-write` for Codex and `acceptEdits` for Claude Code. `advise` and `review` use read-only modes, and reverse read-only requests also disallow Claude tools named `Edit` and `Write`. Claude-side detached execution and Codex session continuation are available only through the Claude Code-to-Codex command-line route; the reverse MCP surface intentionally exposes neither capability.
