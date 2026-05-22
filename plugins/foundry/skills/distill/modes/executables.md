# Mode: Executables Extraction

<!-- file: executables.md — consumers: distill/SKILL.md -->

Triggered when `$ARGUMENTS == "executables"`. Reads latest `/audit --efficiency` Check 33 reports if present; runs the bin/ extraction scan inline otherwise. Then gates, extracts with user confirmation, and re-audits changed files.

## Step E1: Locate or run scan

```bash
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/make_run_dir.py" .reports/distill 2>/dev/null || echo ".reports/distill/$(date -u +%Y-%m-%dT%H-%M-%SZ)")  # timeout: 5000
mkdir -p "$RUN_DIR"  # timeout: 5000

# Optional path override: /distill executables <run-dir-or-report-path>
EXEC_ARGS="${ARGUMENTS#executables}"
EXEC_ARGS="${EXEC_ARGS# }"  # strip leading space
if [ -n "$EXEC_ARGS" ]; then
  if [ -d "$EXEC_ARGS" ]; then
    mapfile -t CHECK33_FILES < <(ls "$EXEC_ARGS"/efficiency-check33-*.md 2>/dev/null)
  elif [ -f "$EXEC_ARGS" ]; then
    CHECK33_FILES=("$EXEC_ARGS")
  else
    printf "! MISSING — path not found: %s\n" "$EXEC_ARGS"
    exit 1
  fi
else
  # Auto-detect: latest run dir that contains check33 files
  LATEST_RUN=$(find .reports/audit -maxdepth 1 -type d -name "20*" 2>/dev/null \
    | sort -r \
    | while IFS= read -r d; do
        ls "$d"/efficiency-check33-*.md 2>/dev/null | head -1 | grep -q . && echo "$d" && break
      done)  # timeout: 5000
  mapfile -t CHECK33_FILES < <(ls "$LATEST_RUN"/efficiency-check33-*.md 2>/dev/null)
fi
echo "Check 33 files: ${#CHECK33_FILES[@]} (from ${LATEST_RUN:-$EXEC_ARGS})"
```

**If `CHECK33_FILES` non-empty**: proceed to Step E2 using those files.

**If `CHECK33_FILES` empty** (no prior `/audit --efficiency` run): print `[→ No efficiency report found — running bin/ extraction scan]` and execute the scan inline:

Determine LOCAL_MODE-aware scan path and extract code blocks:

```bash
[ -d "plugins/" ] && _SCAN_DIR="plugins/" || _SCAN_DIR=".claude/"  # timeout: 3000
# Structured extraction: produce JSONL for each plugin dir, pass to curator
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/extract_code_blocks.py" "$_SCAN_DIR" --min-tokens 5 > "$RUN_DIR/blocks.jsonl"  # timeout: 30000
```

Spawn **foundry:curator** per plugin directory found under `$_SCAN_DIR` (one spawn per plugin, all in parallel — issue all in a single response). Pass curator the relevant slice of `$RUN_DIR/blocks.jsonl` (filter lines where `"file"` prefix matches the plugin dir). Each spawn prompt:

> Use the attached block JSONL (pre-extracted via extract_code_blocks.py — each line is `{"file":..., "lang_marker":..., "line_start":..., "token_estimate":..., "content":...}`). Follow the full Check 33 Phase B2 protocol from `audit/modes/efficiency.md` exactly: assign block IDs, write purpose statements, build purpose clusters, compute syntactic similarity, produce Table 1 (purpose clusters) and Table 2 (extraction scoring). Write to `$RUN_DIR/efficiency-check33-<plugin>.md`. Return ONLY: `{"status":"done","file":"<path>","clusters":N,"findings":N,"severity":{"high":N,"medium":N,"low":N},"confidence":0.N}`

After all spawns complete: update `CHECK33_FILES` to point to the new files in `$RUN_DIR`.

**Health monitoring for scan spawns** (CLAUDE.md §8):

```bash
SCAN_CHECKPOINT="/tmp/distill-exec-scan-$(date +%s)"  # timeout: 3000
touch "$SCAN_CHECKPOINT"                               # timeout: 3000
```

Every 5 min: `find "$RUN_DIR" -newer "$SCAN_CHECKPOINT" -type f | wc -l` — new files = alive; zero for 15 min = stalled. One 5-min extension if last file tail explains delay. On timeout: surface with ⏱; use partial results.

## Step E2: Parse candidates

For each file in `CHECK33_FILES`, read and extract clusters where `Verdict = HIGH` or `Verdict = MEDIUM`. Build candidate list: cluster ID, files affected, language, block purpose, occurrence count, verdict, recommended extraction target, differs-by param slots.

If no HIGH or MEDIUM clusters found: print `✓ No extraction candidates — all clusters HOLD or LOW verdict.` End with `## Confidence` block and stop.

## Step E3: Present candidates and gate

Print candidate summary table:

```text
Bin/ extraction candidates:

| Cluster | Verdict | Blocks | Language | Purpose | Recommended target |
|---------|---------|--------|----------|---------|--------------------|
| C1      | HIGH    | 3      | bash     | resolves _shared/ path | bin/find-shared.sh |
```

Then call `AskUserQuestion` — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "Extract candidates to bin/ scripts?"
- (a) label: `HIGH only` — description: extract only HIGH-verdict clusters
- (b) label: `HIGH + MEDIUM` — description: extract all HIGH and MEDIUM clusters
- (c) label: `Skip` — description: no extraction; review candidates manually

## Step E4: Extract

For each selected cluster, resolve `$_FS` path and spawn **foundry:sw-engineer** (one per cluster, all in parallel — issue all in a single response):

```text
Agent(subagent_type="foundry:sw-engineer", prompt="
_FS=$(python \"\${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py\" foundry skills/_shared 2>/dev/null || echo \"plugins/foundry/skills/_shared\")
Read $_FS/bin-authoring-guide.md for bin/ script conventions.
Task: extract cluster <cluster-id> to bin/.
Cluster: purpose=<purpose>, language=<lang>, param slots=<differs-by values>.
Source files: <list of source .md files>.
**SURGICAL EDIT CONSTRAINT — mandatory**: modify ONLY the identified target block in each source file. Do NOT edit frontmatter, surrounding prose, other code blocks, check tables, or any content outside the target block. If you notice other issues in the file, record them in the summary — do not fix them.
Steps:
1. Create bin/<recommended-target> as standalone executable following bin-authoring-guide.md: module docstring, type hints, __name__ guard (Python) or shebang+set -euo pipefail (bash). CLI params: one named arg per param slot.
2. In each source .md file replace ONLY the target inline block with one-liner invocation:
   \`\`\`bash
   RESULT=$(\"\${CLAUDE_PLUGIN_ROOT:-plugins/<plugin>}/bin/<script>\" --param1 val1 ...)  # timeout: <estimated_ms>
   \`\`\`
   Preserve surrounding variable assignments consuming block output.
3. Diff gate — for each modified source file run: git diff HEAD -- <file> | grep "^[+-]" | grep -v "^[+-][+-][+-]"
   Count non-target changed lines. If any lines outside the target block changed: revert the file (git checkout HEAD -- <file>) and re-apply edit targeting only the block. Report diff line counts in summary.
4. Verify: grep source files to confirm old block body absent; confirm bin/ script exists; run python plugins/foundry/bin/check_orphaned_bin.py and confirm exit 0.
5. Create test file: write `plugins/<plugin>/tests/test_<script-basename>.py` (or the matching `tests/` dir for the plugin) with at minimum pytest tests covering the public CLI entry point (use monkeypatch/capsys/tmp_path). Follow the test style in `tests/` alongside the bin/ script — check existing tests for fixture and import patterns. Non-empty file required; empty file fails Check R4.
Write extraction summary to $RUN_DIR/extract-<cluster-id>.md. Include: diff line counts per file, any reverts performed, incidental issues noticed but NOT fixed.
Return ONLY: {\"status\":\"done\",\"file\":\"$RUN_DIR/extract-<cluster-id>.md\",\"bin_script\":\"<path>\",\"source_files_updated\":N,\"test_file_created\":bool,\"confidence\":0.N}
")
```

**Health monitoring for extraction spawns** (CLAUDE.md §8):

```bash
EXTRACT_CHECKPOINT="/tmp/distill-exec-extract-$(date +%s)"  # timeout: 3000
touch "$EXTRACT_CHECKPOINT"                                  # timeout: 3000
```

Every 5 min: `find "$RUN_DIR" -newer "$EXTRACT_CHECKPOINT" -name "extract-*.md" | wc -l` — zero for 15 min = stalled. One 5-min extension if tail explains delay. On timeout: surface with ⏱; continue with completed clusters.

## Step E5: Re-audit changed files

After all E4 agents complete, collect modified .md files from envelopes. Spawn **foundry:curator** per modified file (all in parallel — issue all in a single response):

```text
Agent(subagent_type="foundry:curator", prompt="Re-audit <file> after bin/ extraction. Check: (1) no inline block body remains — only bin/ invocation one-liner; (2) timeout annotation present on invocation line; (3) variable assignments consuming block output still correct; (4) no orphaned variable references; (5) run git diff HEAD -- <file> and flag any changed lines outside the target block — these are unauthorized side-edits; surface as high finding if found. Write findings to $RUN_DIR/reaudit-<slug>.md. Return ONLY: {\"status\":\"done\",\"file\":\"$RUN_DIR/reaudit-<slug>.md\",\"issues\":N,\"side_edits_detected\":bool,\"confidence\":0.N}")
```

## Step E6: Summary

Print:

```text
Extraction complete — <date>
  Extracted: N clusters → bin/ scripts
    <script-path>: <purpose> (<N> call sites updated)
  Source files updated: N
  Re-audit: clean / N issues (see $RUN_DIR/)
```

Remind: run `/foundry:init` to propagate bin/ scripts to `~/.claude/` plugin cache. Then run `/audit --efficiency` to confirm `clusters == 0`.

End response with `## Confidence` block per CLAUDE.md output standards.
