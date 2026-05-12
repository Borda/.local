<!-- oss:release adversarial review — executed via: Read $SKILL_DIR/modes/adversarial-review.md; execute -->
<!-- Variables available: $SKILL_DIR, $_OSS_SHARED, $BRANCH, $RANGE, $GATHER_FILE, assembled draft content -->

Challenge every factual claim in the assembled draft against the actual codebase and project docs. Runs before voice/tone polish — facts must be correct before prose is refined.

**Scope**: applies to `notes` mode (DRAFT.md) and `prepare` mode (releases/$VERSION/DRAFT.md) and `--migration` flag output. Skip for `--summary` (internal audience) and `--changelog` entries (structured format, not claim-heavy prose).

```bash
# Adversarial review run dir — expand to literal value before spawning
ADVERSARIAL_DIR=".temp/release-adversarial-$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')-$(date +%Y-%m-%d)"
mkdir -p "$ADVERSARIAL_DIR"  # timeout: 5000
```

Write full assembled draft content to `$ADVERSARIAL_DIR/draft-to-review.md` using Write tool.

Spawn adversarial reviewer:

```text
Agent(subagent_type="general-purpose", prompt="Adversarial review of a release draft against the project codebase and docs. Working directory: <REPO_ROOT>.

Read the release draft at: <$ADVERSARIAL_DIR/draft-to-review.md>

Challenge across 4 dimensions — treat every claim as unproven until verified:

1. FACTUAL ACCURACY — for every claim ('adds X', 'fixes Y', 'removes Z', 'improves performance'), verify against HEAD: git grep or read the relevant file. Quote the file:line that confirms or refutes. A claim with no verifiable trace in HEAD = finding.
2. COMPLETENESS — <gather context below>: significant commits (breaking changes, new public API) not mentioned in draft = finding. Minor/internal commits being absent is expected.
3. SEMVER CORRECTNESS — if draft says 'no breaking changes', scan for removed or renamed public API, changed function signatures, removed config keys using git diff. Flag any contradiction.
4. DOCS ALIGNMENT — for each new API or behavior claimed in draft, confirm docs/ or README covers it. Missing doc = finding.

<gather context>
$([ -n \"<GATHER_FILE>\" ] && [ -f \"<GATHER_FILE>\" ] && echo 'Full commit/PR classification in: <GATHER_FILE> — read it for the ground-truth change list.' || echo 'Use the git range <RANGE> directly: git log <RANGE> --no-merges --oneline to get the change list.')
</gather context>

For each finding: severity (critical=claim directly contradicts codebase | high=significant missing change or SemVer misclassification | medium=overstated claim or minor missing item | low=style/wording inaccuracy). For critical and high findings: quote exact draft text and quote codebase evidence.

Write full findings report to <$ADVERSARIAL_DIR/adversarial-review.md> using the Write tool.
Return ONLY on your final line: {\"status\":\"done\",\"file\":\"<$ADVERSARIAL_DIR/adversarial-review.md>\",\"critical\":N,\"high\":N,\"medium\":N,\"low\":N,\"confidence\":0.N}")
```

Expand `<REPO_ROOT>`, `<RANGE>`, `<GATHER_FILE>`, `<$ADVERSARIAL_DIR>` to their literal values before spawning — never pass variable names literally.

**Gate — read `$ADVERSARIAL_DIR/adversarial-review.md`**:
- **Critical or high findings**: fix in draft before proceeding; re-run adversarial review on fixed sections once (max 1 re-run); if findings persist after re-run, surface to user and stop
- **Medium or low findings**: append as `> ⚠️ Reviewer notes: <summary>` to the response; include in Human gate handoff; do not block Polish step
- **0 findings**: proceed directly to Polish
