# Final Handoff Contract

The post-gate presentation checkpoint makes a workflow's final user-facing structure executable. Artifact workflows must write `<run-directory>/final-handoff.json`, render it with `python PLUGIN_ROOT/shared/final_handoff.py render --handoff <run-directory>/final-handoff.json --out-final <run-directory>/final.md --out-validation <run-directory>/final-handoff.validation.json`, bind the returned digests under `result.metadata.final_handoff`, pass all skill-specific and shared artifact validators, promote the candidate, then emit the validated `final.md` bytes verbatim. Do not manually reconstruct or summarize the response after validation.

Rendered section and table labels use portable Markdown bold text such as `**Outcome**` and `**Verification**`. Do not emit ATX/Setext headings, ANSI color escapes, or renderer-specific HTML styling; final reports must remain compact and readable in monochrome terminals, saved Markdown, and plain logs.

This is a post-gate checkpoint, not a sixth quality gate. Order is fixed: five gates; final-handoff creation and rendering; schema-v2 result candidate; skill validator; shared validator including `final_handoff.py check`; candidate promotion; verbatim final output. A failure in the checkpoint blocks promotion and completion.

## Schema

`final-handoff.json` has exactly these top-level fields: `schema_version`, `skill`, `branch`, `outcome`, `tables`, `source_records`, `source_coverage`, `verification`, `remaining`, `next_steps`, `confidence`, `artifacts`, and `caller_contract`. Schema version is `1`. The helper's executable validation is authoritative for nested types, closed vocabularies, exact columns, row/source uniqueness, completeness counts, confidence bands, closure evidence, and branch-specific table rules.

Normal artifact workflows use `branch=standard`; `code-review` uses `assessed`, `unavailable`, or `closed`. An explicitly requested exact caller output uses `caller-contract`, records the requested format and evidence, forbids normal tables, and emits only `caller_contract.output`. Never infer this override merely because concise output would be convenient.

For normal table branches, every material finding, decision, changed surface, experiment, recommendation, or source-owned remediation item must have one stable row ID. `source_records` is the complete source ledger; each table row names its represented source IDs; `source_coverage.omitted_source_records_total` must be zero. Remaining work names the related row ID, item, owner, and next action; `next_steps` contains exactly the remaining row IDs. Terminal `code-review` branches contain no tables or source records.

`verification` preserves all five gate records in canonical order and uses the corresponding gate `stdout` artifact path as evidence. `confidence.score`, gaps, gap closure status/evidence/rationale, and limits must exactly reconcile with the result's confidence metadata. `artifacts` must include the candidate/final result path.

## Exact table columns

| Skill | Columns |
| -- | -- |
| `audit` | `Item \| Severity / impact \| Decision \| Evidence \| Next action` |
| `calibrate` | `Check / metric \| Result \| Evidence \| Next action` |
| `change-analysis` | `Finding \| Impact \| Decision \| Evidence \| Next action` |
| `code-remediate` | `Item \| Severity \| Finding \| Sources \| Outcome \| Evidence / next action` |
| `implement` | `Surface \| Outcome \| Verification \| Remaining limit` |
| `investigate` | `Hypothesis \| Evidence \| Disposition \| Next action` |
| `kaggle` | `Artifact \| Mode \| Verification \| Runtime limit` |
| `manage` | `Surface \| Outcome \| Verification \| Remaining limit` |
| `optimize` | `Iteration \| Baseline \| After \| Delta \| Guard \| Decision` |
| `release` | `Change \| SemVer impact \| Status / blocker \| Evidence` |
| `research` | `Recommendation \| Evidence \| Decision \| Caveat / next check` |
| `sync` | `Surface \| Outcome \| Verification \| Remaining limit` |

An assessed `code-review` may use `PR Snapshot` with `Field | Value` and `Review Findings and Merge Blocks` with `Finding / area | Required change | Evidence | Status`. PR scope requires the snapshot; nonzero findings require the findings table. `code-remediate` rows are value-bound to `metadata.final_resolution_table.items`: cells are exactly `input_item_id`, `severity`, `item_name`, all complete source records in source order, `resolution_status — resolved_how`, and `evidence — owner/status: owner_status`; row IDs, `kind:source_id` values, and source evidence must also match exactly.

## Result compatibility

`write-result.py` creates schema-v2 results and requires `metadata.final_handoff` with schema version, three sibling paths, two SHA-256 digests, and branch. `validate-artifacts.py` checks those paths, exact rendered bytes, digests, gates, confidence, result artifact reference, and workflow-specific reconciliation. Historical results with no `schema_version` are read as schema v1 and remain valid without final-handoff artifacts; new results cannot opt into that compatibility path because the writer always emits schema v2.

## Transport limit and manager exception

The checkpoint proves the complete response bytes that the workflow must emit, but the current host has no post-send transcript hook that can prove the chat transport reproduced them. Treat any later manual rewrite as a contract violation; a future host transcript hook may close this residual transport gap without changing the artifact schema.

`agent-shims` remains the documented lifecycle exception because it has no canonical `.reports` result artifact and is excluded from the artifact/calibration roster. Its final chat contract remains advisory until that manager gains a canonical run/result lifecycle; do not claim executable final-response validation for it.
