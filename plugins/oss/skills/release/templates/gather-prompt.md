<!-- file: gather-prompt.md — consumers: oss/skills/release/SKILL.md (Delegation strategy) -->
Working directory: <REPO_ROOT>. Run all git commands from that directory (use: git -C <REPO_ROOT> <cmd> or cd <REPO_ROOT> first). For git range <RANGE>:

Run gather phase: git log, git diff --stat, gh pr list.

Run classify phase: classify NET state at HEAD, not each intermediate commit. When multiple commits within range touch same API or feature (add then modify, add then remove, add then rewrite), describe only what exists in HEAD — don't include features added and later undone within same range regardless of whether removal was explicit revert commit or follow-up PR. When entry survives (net-effect non-zero), collect ALL PR numbers contributing to final state under SAME category — never attribute to only initial or last PR. Group under one bullet with cumulated PR refs ONLY when all contributing PRs classify into same section (both Added, both Changed, both Fixed); when PR fixes bug or changes behavior in feature added by earlier PR in same range, that fix gets own 🔧 Fixed or 🌱 Changed entry — never folded into Added. Exception: trivial fixes (one-line cleanup, doc tweak inside new code with no standalone user-visible effect) fold into parent Added bullet.

Run explore phase: top 3–5 most significant changed files (read actual diffs).

Run truth check phase: for each item classified as 🚀 Added or ⚠️ Breaking Changes naming specific symbol (function, class, method, config key, CLI flag), verify symbol actually DEFINED in codebase at HEAD — not just mentioned in comment, docstring, or leftover reference. Prefer codemap over grep: first check if codemap index available (`scan-query list 2>/dev/null | wc -l` — non-zero = available), then run `scan-query find-symbol '^<symbol>$' 2>/dev/null`; empty output = absent. When codemap unavailable, fall back to definition-pattern grep: `git -C <REPO_ROOT> grep -wl 'def <symbol>\|class <symbol>' HEAD -- '*.py' 2>/dev/null` for Python, then `git -C <REPO_ROOT> grep -wl '<symbol>' HEAD -- '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null` for other languages. If both return nothing symbol is absent — remove from classified section entirely, log 'REMOVED: <item> — symbol not found in HEAD'. Repeat for any newly revealed dependencies. Track count of removed items (unconfirmed_total) and how many were in ⚠️ Breaking Changes (unconfirmed_breaking).

Write full findings — commit list, verified-only classified change table, diff excerpts, and REMOVED log — to <GATHER_FILE> using the Write tool.

Return ONLY: {"status":"done","file":"<GATHER_FILE>","changes":N,"breaking":N,"unconfirmed":N,"unconfirmed_breaking":N,"confidence":0.N}
