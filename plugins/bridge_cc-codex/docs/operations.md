# Operations and troubleshooting

This document covers local setup, routine invocation, detached-job lifecycle, and the failure signals emitted by `bridge`. The bridge never repairs host authentication or CLI configuration automatically; use the host's own login and permission workflow when setup reports a prerequisite failure.

## Prerequisites

For Claude Code to Codex calls, make `codex` available on `PATH` and authenticate it for the requested model. For Codex to Claude Code calls, make `claude` available on `PATH` and authenticate it for the requested model. Both directions require a `python` executable on `PATH` that reports Python 3.10 or newer. The selected workspace must permit creation of `.temp/bridge/`.

The selected workspace does not need to be a Git repository. The bridge uses Codex's supported `--skip-git-repo-check` option when needed; that option only permits execution outside Git and never chooses or widens the workspace. The caller and host remain responsible for selecting and trusting the intended directory.

Run a static diagnosis before a live probe. From a Claude Code session, use:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_diagnose.py"
```

From a Codex session, diagnose the Claude direction with:

```bash
python "${PLUGIN_ROOT}/bin/bridge_diagnose.py" --direction claude
```

The setup procedure first confirms that `python --version` reports Python 3.10 or newer. Its static check then inspects command availability and the required help surface against `rules/cli-baseline.json`, and summarizes existing bridge health records. It does not prove authentication, structured-output schema compatibility, or provider inference. Add `--live` only after explicitly accepting one authenticated provider call per selected direction and its possible quota cost.

## Foreground calls

Claude Code skills use `/bridge:implement`, `/bridge:advise`, and `/bridge:review`. Codex skills use `$bridge:implement`, `$bridge:advise`, and `$bridge:review`. Each call requires a concrete task and supports explicit `--model`, `--effort`, and `--timeout-seconds` values. Omitted budgets default to 600 seconds for `implement`, 120 seconds for `advise`, and 300 seconds for `review`; the hard cutoff is 1.2 times the soft budget. Reverse implementations accept at most 700 seconds; reverse advice and review accept at most 350 seconds so their optional second attempt, per-attempt termination and drain overhead, and the response margin remain inside the 900-second host deadline.

For direct local diagnostics or automation, the Claude-facing supervisor accepts the following shape:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" advise --task "Summarize the current diff without editing files."
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" review --task "Review the current diff for regressions and missing tests."
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" implement --task "Run the focused test and fix the smallest verified defect." --timeout-seconds 600
```

The Codex-facing MCP tools are the supported reverse entry point; do not invoke `claude --print` directly from a sandboxed Codex model turn. Implement is write-capable under the host's normal permission mode, advice is read-only, and review is routed through a read-only general Codex execution with an explicit adversarial-review prompt rather than Codex's native review subcommand.

On native Windows PowerShell, use the same `python` launcher after confirming it reports Python 3.10 or newer; use the installed plugin-root variable with backslash or slash separators.

## Detached jobs

Only Claude Code-to-Codex `implement` supports detached execution. Start it with `--background`; the command returns a job identifier. Inspect or stop that identifier with:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" status --job-id JOB_ID
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" result --job-id JOB_ID
python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" cancel --job-id JOB_ID
```

Use the same workspace for lifecycle commands. While a job is running, do not edit paths named by its task. `status` reports lifecycle metadata; `result` returns the completed envelope; `cancel` writes a durable, identity-checked cancellation marker for the live supervisor and returns `cancel_requested`. Poll `status` or `result` for the final `cancelled` state; the supervisor, never the lifecycle caller, terminates its verified child process tree and records the observed worktree delta when available.

A recorded `running` job whose supervisor process no longer exists — or a `queued` record older than two minutes that no supervisor ever claimed — is reported as `stalled` instead of `running` or `queued`, so a supervisor killed without writing its final record cannot keep a caller polling forever. A supervisor that fails with an internal error before producing an envelope records the terminal `failed` state with its error text. Treat `stalled` and `failed` as terminal: cancellation is refused for a stalled job because no supervisor remains to consume the marker, and you should inspect the job record, the raw transcript, and the worktree before re-dispatching, because a killed write-capable child may have landed partial edits.

## Common failures

| Signal | Meaning | Operator action |
| --- | --- | --- |
| `blocked` | The request was rejected or a required CLI, authentication, permission, model, or input contract was unavailable. | Read `blockers`, run static diagnosis, and resolve the host prerequisite or narrow the request. |
| `timeout` | The hard cutoff elapsed before a valid result returned. | Read the transcript and workspace state; narrow the task or increase the explicit budget. Do not assume no edits occurred. |
| `refused` with `recursion-depth` | The trusted call chain already contains a peer dispatch. | Start a fresh outer call rather than attempting another cross-host hop. |
| `effort_substituted` | The requested effort was valid but unsupported by the target capability declaration. | Review the recorded requested and applied levels; repeat only with an intentional supported choice. |
| Missing command or changed flags | A host CLI is absent or no longer matches `rules/cli-baseline.json`. | Install or upgrade the host CLI, or use a bridge version that supports it; never edit the baseline at runtime. |

## Artifact inspection

The bridge stores raw transcripts at `.temp/bridge/raw-<timestamp>.txt`, detached-job records at `.temp/bridge/jobs/<job-id>.json`, durable cancellation markers at `.temp/bridge/jobs/<job-id>.cancel.json`, health records at `.temp/bridge/health.jsonl`, and sanitized fault records at `.temp/bridge/incidents/<timestamp>-<fault>.json`. The compact envelope's public fields carry decisions, blockers, and remaining work; its `transcript_path` is the authoritative pointer to transcript-only `details` and raw child output for additional evidence. Details never hide required work, and `incident` points to a compact diagnostic file when a fault is classified. Preserve incident and review evidence before applying local retention or cleanup.
