## Personal Model Selection

Normal parent sessions use `gpt-5.6-terra` at `high`. Do not select or spawn `gpt-5.6-sol` automatically for an architecture, public-API, security, migration, or review label.

Use the Sol-pinned `solution-architect` or `security-auditor` only when the user explicitly requests a Sol advisory pass or explicitly selects that agent. Keep the main parent session on Terra. A Sol child is a bounded advisory: return its evidence in the workflow artifact and handover, then continue scope, implementation, verification, and the final response in the Terra parent.
