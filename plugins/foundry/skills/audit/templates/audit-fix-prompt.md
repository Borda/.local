<!-- file: audit-fix-prompt.md — consumers: audit/SKILL.md Step 8 -->
<!-- Canonical multi-file fix orchestration. NOT derived from fix-prompt.md (per-file only). Keep both in sync when changing shared audit-fix behavior. -->

Read `<RUN_DIR>/summary.jsonl` — this is the findings list (one JSON object per line).
Read `$AUDIT_TPL/fix-prompt.md` for the per-file fix prompt template.
**Dependency classification**: (1) Coalesce all same-file findings into one group first. (2) Classify each coalesced group: parallel-safe = category in PARALLEL_SAFE_CATEGORIES {hardcoded-path, missing-confidence-block, typo, heading-hierarchy, duplicate-lines, broken-bash-fence, stale-version-ref, missing-frontmatter-field} AND fix writes only to its own file AND no other group writes to a file this group reads. All others sequential.
**Adversarial pre-apply gate**: for each unique file in the findings list, spawn **foundry:challenger** AND **foundry:curator** in parallel — challenge/validate each finding batch: "Is each finding real? Is the fix appropriate? Does any fix risk removing load-bearing behavioral content?" Each writes verdict to `<RUN_DIR>/gate-<file-basename>.md`; return `{"verdict":"approved"|"blocked","reason":"<one-line>","file":"<path>"}`. If either returns `blocked`: mark findings for that file as blocked (add to `blocked_findings` list with reason); skip fix agent. Proceed to fix agent only if both return `approved`.
Issue all gate spawns in a single response (parallel). After gate verdicts received:
**Phase 1 — Parallel basket**: issue all parallel-safe approved fix spawns in a single response. Wait for all to complete.
**Phase 2 — Sequential basket**: spawn foundry:curator mini-agent to re-read files modified in Phase 1 that are dependency inputs for Phase 2 fixes (do NOT inline-read — orchestration contract). Use category→dependency rules: broken-cross-ref reads target agent/skill file; inventory-drift reads MEMORY.md; README-sync reads agent/skill source files. Serialize groups where group A output is group B input; parallel within independent groups.
For each file that passed the gate, spawn one fix agent (foundry:curator for .md files, foundry:sw-engineer for .js/.py files) with all approved findings batched into a single prompt.
After all fix agents complete:
**Step R1 — curator re-audit**: spawn foundry:curator re-audit agents (one per changed file) to confirm fixes held.
**Step R2 — challenger residual scan**: for every file where a CRITICAL finding was fixed, spawn foundry:challenger with prompt: "Fresh adversarial read of `<file>`. No context from prior audit. Find any CRITICAL issues present NOW. Return ONLY: {\"file\":\"<path>\",\"new_criticals\":N,\"findings\":[{\"id\":\"<slug>\",\"summary\":\"<one-line>\"}]}". Issue all challenger spawns in single response (parallel). Write each result to `<RUN_DIR>/residual-<file-basename>.md`. Collect total `new_criticals` across all results.
Set `re_audit_clean: true` only if: curator confirms all fixes held AND total new_criticals = 0. Otherwise `re_audit_clean: false`.
Write a completion summary to `<RUN_DIR>/fix-summary.md`:
  - findings_total: N
  - fixed: N
  - blocked: N (gate-rejected; listed in blocked_findings)
  - failed: N
  - residual_criticals: N (new criticals from post-fix challenger scan; 0 when no CRITICAL findings were fixed)
  - re_audit_clean: true|false (true = fixes held AND residual_criticals = 0)
  - blocked_findings: [{id, file, reason}, ...]
Return ONLY: {"status":"done","file":"<RUN_DIR>/fix-summary.md","fixed":N,"blocked":N,"failed":N,"residual_criticals":N,"re_audit_clean":true|false,"confidence":0.N}
