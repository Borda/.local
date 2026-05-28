# Resume Mode — run/SKILL.md sidecar

Loaded by `run/SKILL.md` when `--resume` flag is set.

## Resume Mode

Triggered by `--resume` flag (with optional `<file.md>` argument).

**Locating the run**:

- `resume` (no argument): scan `.experiments/state/`, select run with latest `started_at` and `status: running`.
- `resume <file.md>`: resolve path to absolute. Scan all run dirs, filter by `"program_file"` matching. Pick latest `started_at`. If no match: stop with error.

1. Read `state.json`. Restore `clarification_prompt` and `colab_hw` from it (may be null).
2. **Re-parse program file**: if `program_file` non-null, re-read/re-parse (R1 rules), update config. Applies edits made between runs. Note: edits during active loop take effect only on next `resume`.
3. **Validate `experiments.jsonl`**: read last line, parse as JSON. If truncated or invalid: invoke `AskUserQuestion` tool — question: "experiments.jsonl last line appears corrupt (truncated or invalid JSON). How to proceed?", (a) label: `truncate corrupt entry and resume`, (b) label: `abort — fix manually`. If (a), remove last line; if (b), stop.
4. Validate git HEAD: if diverged from `state.json.best_commit` unexpectedly, invoke `AskUserQuestion` tool — question: "HEAD has diverged from best_commit in state.json. Continue anyway?", (a) label: `yes, continue from current HEAD`, (b) label: `no, abort`. If (b), stop.
5. Continue loop from `state.json.iteration + 1`. `diary.md` NOT re-initialized — entries append to existing file.
