Each invocation, ask curator to check:

- **Purpose and logical coherence**: role clearly defined? Scope right — not too broad, not too narrow? New user know when to reach for it vs similar one?

- **Structural completeness** (tag/fence symmetry handled by deterministic bin/ checkers — do not restate): required sections present, step numbering sequential, **no orphaned empty blocks** — any structural tag (`<constants>`, `<notes>`, `<calibration>`, `<inputs>`, `<not-for>`, `<role>`, `<initialization>`, `<antipatterns-to-flag>`) containing only whitespace = dead markup, remove; flag **medium** (gate-level); auto-fix safe (no content to lose)

- **Cross-reference validity**: every agent/skill name mentioned must exist on disk. Cross-reference against Step 2 inventory. Name not in Step 2 inventory = **broken cross-reference** (critical). No conditional language ("if X doesn't exist") — by Step 3, inventory known. If inventory not collected (e.g., running in isolation), flag: "unverified reference — requires disk inventory check." **Antipattern to flag**: writing "potentially missing" / "likely doesn't exist" / "if this agent doesn't exist" / "pending verification" / "should be checked against inventory" when Step 2 ran. These phrases = agent not using inventory. Name in workflow, absent from Step 2 list = confirmed broken cross-reference — report critical, not conditional. Conditional language acceptable only when Step 2 genuinely not run.

- **Verbosity and duplication**: bloated steps, repeated instructions, copy-paste between files. **Token count is verbosity metric, not line count**:

  - prefer breaking long lines into shorter ones for clarity (line breaks help model processing)
  - flag splits that add words, padding, or prose beyond minimal formatting overhead (newline, list marker)
  - N+1 backtick outer fence when inner content has N-backtick fences = correct CommonMark nesting — not formatting overhead; do not flag as non-standard

- **Edit quality gate** — self-challenge every addition, edit, deletion:

  - best approach: simpler path exists → flag it; no unnecessary complexity or speculative abstractions
  - no side effects: cross-refs still resolve, existing callers unaffected, no behavior regression
  - complete and clean: no gaps, no dead instructions, no orphaned cross-refs, no leftover stubs
  - verified: every claim backed by code/disk evidence — no hypothesis stated as fact

- **Content freshness**: outdated model names or tool/CLI names in config text — agent file names model that no longer exists, or uses deprecated CLI flag

- **Example value vs. token cost**: for each inline example (code block or `## Example` section), judge whether it earns tokens — demonstrates non-obvious pattern or nuanced judgment call prose alone cannot convey? Flag examples that restate surrounding prose in code, illustrate obvious/trivial cases, or better served by project-local `AGENTS.md`. If project has own `AGENTS.md` or `CONTRIBUTING.md`, generic examples in agent files less justified. **Scope constraint**: report only findings within above checklist. No out-of-scope findings (e.g., "no error handling described," "missing inputs section for a skill") unless that specific check in list. Extra findings = noise — dilute precision, distract from confirmed issues.
