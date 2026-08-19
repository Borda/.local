# Security and privacy

The bridge adds a local process boundary; it does not create an account, grant a provider permission, or replace either host's authentication and approval policy. Install and use it only in a workspace where the selected peer command-line interface is trusted to receive the requested task and project context.

## Authority boundaries

- The caller chooses the verb, task, model, effort, and soft timeout within the published input contract.
- The host supplies the workspace for Codex-to-Claude Code MCP calls. The reverse MCP tools reject model-supplied `workspace`, `background`, and `session_id` values.
- Git membership is not a trust boundary: `--skip-git-repo-check` permits an explicitly selected non-Git workspace but does not choose or widen it. The caller and host must trust the selected directory.
- `implement` may change the selected worktree under the peer host's normal permission mode; `advise` and `review` are read-only bridge operations.
- The bridge never grants an approval, bypasses an authentication prompt, reads credential files, or invents a model account.
- A recursion depth of one or greater is refused before another peer process is launched.

The host's normal permission controls remain authoritative. Review the workspace and permission mode before allowing a write-capable implementation, especially when a detached job may continue after the calling turn ends.

## Data flow and persistence

The task text and selected project context are passed to the provider command-line interface named by the request direction. Provider account access, billing, retention, and model availability remain governed by that provider and its host configuration. The bridge does not upload artifacts to a separate service and does not persist credentials.

Each child attempt writes one raw transcript under `.temp/bridge/`. Detached jobs write metadata under `.temp/bridge/jobs/`; faults write sanitized records under `.temp/bridge/incidents/`; completed calls append one health record to `.temp/bridge/health.jsonl`. Raw transcripts can contain task text and provider output, so protect the workspace and apply the project's retention policy before sharing or deleting these files.

Incident records intentionally omit child command arguments and environment data because those values can contain task text or credentials. They retain the classified fault, reason, model, effort, verb, budget, transcript path, and any observed worktree delta from a killed implementation. The health record is operational telemetry and should be handled as workspace data.

## Result integrity

The only write-capable operation is `implement`. Public `status`, `verdict`, `findings`, `files_touched`, `remaining`, and `blockers` carry decisions, blockers, and remaining work, while transcript-only `details` hold additional evidence and never hide required work.

The peer/model-to-harness result contains the six decision fields in `schemas/envelope.schema.json`—`status`, `verdict`, `findings`, `files_touched`, `remaining`, and `blockers`—plus bounded verbose `details`. The harness persists `details` in the raw transcript, strips them from the harness-to-caller public envelope, adds observed metadata and workspace-relative `transcript_path` and `incident` references, then validates the complete public result against `schemas/harness-envelope.schema.json`. Decisions, blockers, and remaining work remain public; transcript-only `details` provide additional evidence and never hide required work. Timeouts and recursion refusals are constructed by the harness and are never claimed by model output.

Treat the compact envelope, `files_touched`, transcript paths, cost, timing, and status as evidence to inspect, not as permission to accept a consequential change automatically. Opening the transcript is an opt-in detail inspection; re-read changed files and run the relevant project checks before incorporating an implementation result.

## Recovery and cancellation

Only one bounded remedy is attempted for a fault. Read-only `advise` and `review` requests may receive one timeout or supported-effort retry; a write-capable `implement` request is never automatically retried — after a timeout or a structured effort failure alike — because edits may already have landed. Cancellation writes a contained marker bound to the canonical job identifier; the live supervisor polls that marker and terminates only the child process tree it launched, so lifecycle commands never signal a persisted PID that another process could later reuse. On Windows, supervisor-owned process-tree termination uses the native `taskkill` utility when the normal process-group control is unavailable.
