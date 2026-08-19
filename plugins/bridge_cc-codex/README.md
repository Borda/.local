# 🌉 bridge_CC-Codex — Claude Code ↔ Codex

`bridge_CC-Codex` lets Claude Code and OpenAI Codex hand one another bounded implementation, advice, and review requests. Its normalized plugin identifier is `bridge`. It is one repository with two independently installable host integrations: the Claude Code half calls the `codex` CLI, and the Codex half calls Claude through the bridge's host-launched MCP server.

The bridge is useful with either host integration installed and has no dependency on another plugin from this repository. Existing-plugin replacement and consumer migration are deliberately outside this standalone package.

> Release: `0.2.0`.

______________________________________________________________________

<details>

<summary><strong>📋 Contents</strong></summary>

- [What it provides](#-what-it-provides)
- [Requirements](#-requirements)
- [Is MCP required?](#-is-mcp-required)
- [Install for Claude Code](#-install-for-claude-code)
- [Use from Claude Code](#-use-from-claude-code)
- [Install for Codex](#-install-for-codex)
- [Use from Codex](#-use-from-codex)
- [Model, effort, budget, and depth](#-model-effort-budget-and-depth)
- [Results and artifacts](#-results-and-artifacts)
- [Privacy and security boundaries](#-privacy-and-security-boundaries)
- [Updating, uninstalling, and human-owned gates](#-updating-uninstalling-and-human-owned-gates)
- [Maintainer documentation](#-maintainer-documentation)
- [License and attribution](#-license-and-attribution)

</details>

______________________________________________________________________

## 🎯 What it provides

The two hosts expose the same three operations:

| Operation   | Purpose                                                                 | Default access                                                         |
| ----------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `implement` | Complete a bounded change and report the resulting files and limits.    | Write-capable (`workspace-write` for Codex, `acceptEdits` for Claude). |
| `advise`    | Answer a focused question without editing files.                        | Read-only.                                                             |
| `review`    | Perform an adversarial review of the current diff or supplied artifact. | Read-only.                                                             |

Every call carries a model and reasoning-effort selection. If the caller omits `model`, the target CLI uses its configured host default and the envelope records `model: "host-default"`. When effort is omitted from a skill invocation, the skill classifies the complete task using the shipped effort policy and passes the selected level; direct CLI or MCP calls that bypass a skill use `medium`. Supported effort aliases are normalized before dispatch, invalid values are blocked, and an explicitly supplied supported-effort list may cause one recorded downgrade.

Every call also carries a soft wall-clock budget and a recursion `depth`. The budget is announced to the callee, which is asked to return a useful partial result with `remaining` and `blockers` instead of waiting indefinitely. The bridge enforces a hard cutoff at 1.2 times the soft budget. A depth of one or greater is refused, so a Claude → Codex → Claude loop cannot continue.

Results are compact envelopes rather than raw transcripts. The public envelope carries decision-critical `status`, `verdict`, `findings`, `files_touched`, `remaining`, and `blockers`, plus observed harness metadata such as model, effort, cost, duration, depth, `run_id`, and a session identifier when applicable. Incomplete work and blockers must stay in those public fields; transcript-only `details` hold additional evidence and never hide required work. The envelope carries workspace-relative `transcript_path` and, for faults, `incident` references; open those artifacts only when the compact result needs investigation. Detached calls return their job identifier separately. The model-authored core is validated separately from harness metadata; model output cannot claim observed cost, timing, process, or correlation fields.

## ✅ Requirements

- Claude Code with plugin support for the Claude half.
- OpenAI Codex CLI for Claude → Codex calls, available as `codex` on `PATH` and authenticated for the requested model.
- Claude Code CLI for Codex → Claude calls, available as `claude` on `PATH` and authenticated for the requested model.
- A `python` executable on `PATH` that reports Python 3.10 or newer for the bridge's Python entry points; the same launcher is used on POSIX and Windows.
- A writable project-local `.temp/bridge/` directory for bridge state and transcripts.

The bridge does not install either host, authenticate either account, select a model account, or grant permissions. Those are operator-owned prerequisites. The Codex-side MCP server is host-launched outside the model's sandbox so it can reach the Claude CLI's normal authentication path; a Claude CLI that is not logged in remains a reported setup/authentication failure.

## 🔌 Is MCP required?

MCP is complementary to the bridge as a whole but mandatory for the Codex → Claude Code direction. Claude Code → Codex calls launch `codex exec` directly and do not need MCP. Codex → Claude Code calls must use the packaged MCP server because a `claude --print` process started from a sandboxed Codex model turn cannot rely on the normal Claude authentication context, while the Codex host launches the MCP server outside that model sandbox.

If you install only the Claude Code half to call Codex, MCP is not required. If you install only the Codex half or want the complete bidirectional bridge, the `.mcp.json` declaration and `bin/bridge_mcp.py` are required transport components, not optional enhancements. The MCP boundary provides the three tools and prevents model-controlled workspace, background, or session selection.

## 📦 Install for Claude Code

The Codex-facing MCP surface has three tools: `bridge_implement`, `bridge_advise`, and `bridge_review`. MCP is required for Codex → Claude Code and full bidirectional use, but not for Claude Code → Codex-only use.

Add the AI-Rig marketplace and install `bridge_CC-Codex`:

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install bridge@borda-ai-rig
```

Start a fresh Claude Code session after installation. Run the static local CLI check with:

```text
/bridge:setup
```

The default setup check is static and free: it checks that each selected CLI exposes the required commands and flags in its help output, then summarizes the existing local health log. It does not prove provider authentication, schema acceptance, or successful inference. The optional live check makes one minimal authenticated call per selected direction and therefore consumes provider quota:

```text
/bridge:setup --live
```

## ⚡ Use from Claude Code

Invoke the namespaced skills directly. Pass a concrete task or question and select the model and effort when the host default is not appropriate:

```text
/bridge:implement --model <codex-model> --effort <effort> --timeout-seconds 600 "Run the focused test and fix the smallest verified defect."
/bridge:advise --model <codex-model> --effort <effort> --timeout-seconds 120 "Which files own this behavior, and what evidence should I collect first?"
/bridge:review --model <codex-model> --effort <effort> --timeout-seconds 300 "Review the current diff for correctness, regressions, and missing tests."
```

The verb skills accept the bridge's task text plus caller-selected `--timeout-seconds`, `--depth`, `--run-id`, `--workspace`, and (for implement) `--background` and `--session-id` fields. Omitted budget uses the per-verb default (`advise` 120 seconds, `review` 300 seconds, `implement` 600 seconds); omitted depth starts an outermost call at zero. A write-capable implementation is never automatically retried after timeout because its process may already have changed the worktree. Read-only advice and review may receive one bounded retry at the next lower supported effort tier, so the retry can finish within the same budget.

Long-running implementation work may be detached. Use the job identifier printed by the bridge to inspect or stop it:

```text
/bridge:status <job-id>
/bridge:result <job-id>
/bridge:cancel <job-id>
```

Background execution and lifecycle controls are available only for Claude Code → Codex `implement`. `advise` and `review` are foreground, ephemeral calls; the Codex → Claude MCP transport does not expose reverse background requests or separate status/result/cancel skills. After an implementation returns, re-read every path in `files_touched[]` before making another edit. Do not edit paths named by a still-running implementation task; the job record is the coordination boundary.

Session continuation is also limited to Claude Code → Codex `implement`: pass the explicit session identifier returned by a prior implementation, keep the same workspace, and never use a “most recent session” selector. Advice and review always start fresh ephemeral Codex runs. The reverse MCP path does not resume Claude sessions.

## 📦 Install for Codex

Register the repository marketplace and add the Codex plugin:

```bash
codex plugin marketplace add Borda/AI-Rig
codex plugin add bridge@borda-ai-rig
```

The Codex manifest declares the bridge MCP server, and the installed `.mcp.json` starts `bin/bridge_mcp.py` from the plugin root. The server treats the current directory selected by the Codex host as its trusted workspace; open the Codex session in the intended project and do not use write-capable calls if the installed host launches the MCP server from a different directory. If Codex asks you to trust or enable the installed MCP content, review the displayed command and approve it according to your local policy. Start a fresh Codex session after installation, then run the Codex-side setup skill:

```text
$bridge:setup
```

The Codex half degrades cleanly when `claude` is absent or unauthenticated: setup reports the prerequisite and bridge calls return a structured blocked result. A static setup pass does not establish that Claude accepts the bridge's structured-output request; use the explicitly approved live probe when that compatibility evidence is required. The bridge does not install Claude, read credentials from files, or fall back to a shell call inside the Codex sandbox.

## ⚡ Use from Codex

Use the Codex skills for the same three operations:

```text
$bridge:implement --model <claude-model> --effort <effort> --timeout-seconds 600 "Implement the bounded change and report the files touched."
$bridge:advise --model <claude-model> --effort <effort> --timeout-seconds 120 "Explain the smallest safe next step without editing files."
$bridge:review --model <claude-model> --effort <effort> --timeout-seconds 300 "Review the current diff and list actionable findings."
```

The skills invoke the bridge MCP tools `bridge_implement`, `bridge_advise`, and `bridge_review`. Each tool accepts `task`, optional `model` and `effort`, and optional `timeout_seconds`, `depth`, `run_id`, and supported-effort capability data. Omitted model, effort, depth, and run ID use the host-default, `medium`, zero, and a new UUID respectively. Reverse implementations accept at most 700 seconds; reverse advice and review accept at most 350 seconds because their one allowed timeout retry, including per-attempt termination and drain overhead, must also finish within the MCP host's 900-second deadline. The host-launched server binds the request to its launch workspace and rejects model-supplied workspace, background, and session fields, so a tool call cannot widen filesystem authority. The bridge supplies the budget preamble, invokes `claude -p` with the narrowest permission mode for the verb, and returns the same compact envelope used by the Claude half. The peer's bounded verbose `details` remain in the raw transcript referenced by the envelope; they are not copied into the caller's context. Do not invoke `claude -p` directly from a sandboxed Codex model turn: the bridge MCP server is the supported transport because it runs in the host context where the normal Claude authentication path is available.

## 🎚️ Model, effort, budget, and depth

The caller's explicit model is passed to the target CLI; the bridge does not discover or validate model availability before dispatch. An omitted model uses the target host default and is represented as `host-default` in the envelope. The caller's explicit effort is normalized before dispatch; supported values are `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`, with `trivial` and `none` accepted as aliases for `minimal`. An invalid value returns `blocked`; when a caller supplies supported-effort capabilities, one lower supported value may be recorded in `effort_substituted`.

The per-verb soft budgets are two minutes for `advise`, five minutes for `review`, and ten minutes for `implement`. A callee receives the budget in-band and is expected to scope its work to fit. The hard cutoff is 1.2× the soft budget. A `partial` result is valid work with explicit `remaining`; a `blocked` result names the permission, authentication, or input blocker; `timeout` identifies a cutoff; `refused` identifies recursion protection or another deliberate refusal.

`depth` starts at zero for a caller-originated request. Before launching the peer, the transport increments it in `CC_CODEX_BRIDGE_DEPTH`; the peer CLI and MCP process inherit that trusted value, and caller input cannot lower it. Negative depth is rejected, and a call received at trusted depth one or greater returns `refused: recursion-depth`. `run_id` is minted once at the outermost call and echoed through the call chain, so health records from both hosts can be correlated without conflating a Codex thread identifier with a Claude session identifier.

## 📊 Results and artifacts

Each child attempt writes its raw host transcript once. The public envelope returns the compact decision core, including decisions, blockers, and remaining work, with observed metadata and workspace-relative transcript or incident references; verbose peer `details` stay in the transcript as additional evidence and never substitute for required public fields. Bridge state is project-local:

```text
.temp/bridge/raw-<timestamp>.txt                    raw transcript, referenced by the envelope
.temp/bridge/jobs/<job-id>.json                     detached-job metadata and lifecycle state
.temp/bridge/jobs/<job-id>.cancel.json              durable cooperative-cancellation request
.temp/bridge/health.jsonl                           one health/cost record per completed bridge call
.temp/bridge/incidents/<timestamp>-<fault>.json     sanitized fault and recovery evidence
```

Incident records do not persist child command arguments or environment data. They preserve the classified fault, reason, model, effort, verb, budget, transcript path, and—when a write-capable process is killed—the observed worktree delta. The health log records direction, verb, model, effort, cost/tokens when reported by the host, duration, status, depth, and `run_id`. Setup summarizes blocked/timeout/refused counts, their latest timestamps, and reported cost by direction, verb, and model; static CLI findings are reported separately.

Artifacts are evidence, not authority. Read the envelope, source changes, tests, permissions, and remaining limits before accepting consequential work. Delete `.temp/bridge/` only under your project's normal retention policy and only after preserving any incident or review evidence you still need.

## 🔒 Privacy and security boundaries

The bridge sends the task text and the selected project context to the provider CLI named by the direction of the call. Provider billing, retention, account access, and model availability remain governed by the provider and your host configuration. The bridge does not upload artifacts to a separate service or persist credentials.

Use `advise` and `review` for read-only work. `implement` can modify the current worktree under the host's normal permission policy. Authentication failures, permission denials, unsupported models, and unknown faults are surfaced as structured results or incidents; the bridge never bypasses host permission prompts, invents a credential, retries a write-capable timeout, or silently replaces a requested effort tier.

## ⬆️ Updating, uninstalling, and human-owned gates

Update the marketplace snapshot through the host's normal plugin manager, then restart the host session. Uninstalling one half does not remove the other half or alter host credentials. Remote publication, marketplace refresh, provider login, MCP trust approval, and any permission escalation remain human-owned operations.

The bridge's checked-in manifests and host baseline describe the CLI surface it was verified against. If `setup` reports missing or changed flags, upgrade the host or use a bridge release that supports the installed host; do not patch the baseline at runtime. Run the local verification commands below after source changes. On Linux or macOS:

```bash
python -m pytest -q plugins/bridge_cc-codex
git diff --check -- plugins/bridge_cc-codex
disposable_parent_directory="$(mktemp -d)"
python plugins/bridge_cc-codex/scripts/build_package.py --output "$disposable_parent_directory/bridge"
python plugins/bridge_cc-codex/scripts/validate_package.py "$disposable_parent_directory/bridge"
```

On native Windows PowerShell:

```powershell
& python -m pytest -q plugins/bridge_cc-codex
git diff --check -- plugins/bridge_cc-codex
$disposableParentDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("bridge-" + [System.Guid]::NewGuid())
New-Item -ItemType Directory -Path $disposableParentDirectory | Out-Null
$disposablePackageDirectory = Join-Path $disposableParentDirectory "bridge"
& python plugins/bridge_cc-codex/scripts/build_package.py --output $disposablePackageDirectory
& python plugins/bridge_cc-codex/scripts/validate_package.py $disposablePackageDirectory
```

Run `/bridge:setup --live` or `$bridge:setup --live` only when you explicitly accept the provider calls and their cost. A live setup probe verifies one selected path at that moment; it is diagnostic evidence, not proof that a future task will succeed.

## 📚 Maintainer documentation

- [Architecture and transport](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/docs/architecture.md) explains both request directions, process boundaries, permissions, and exactly where MCP is required.
- [Security and privacy](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/docs/security.md) defines authority, data flow, artifacts, result integrity, recovery, and cancellation boundaries.
- [Operations and troubleshooting](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/docs/operations.md) covers prerequisites, diagnosis, foreground calls, detached jobs, common failures, and artifact inspection.
- [Development and release verification](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/docs/development.md) records the package layout, local gates, installed-shape validation, and release responsibilities.

## 📄 License and attribution

This plugin is distributed under the Apache License, Version 2.0; see [LICENSE](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/LICENSE). Repository attribution is in [NOTICE](https://github.com/Borda/AI-Rig/blob/main/plugins/bridge_cc-codex/NOTICE). The bridge's implementation is maintained as a self-contained package and does not require a sibling plugin.
