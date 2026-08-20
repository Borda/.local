---
name: setup
description: "Post-install setup for the research plugin. Run once after installing on a new machine, or after a plugin version upgrade, to deliver this plugin's rules/*.md into ~/.claude/rules/ as namespaced symlinks. TRIGGER when: user installed or upgraded the research plugin and its rules are not loading; phrases: 'set up research', 'research rules not loading', 'after upgrading research'. SKIP: settings/statusLine/TEAM_PROTOCOL setup (use /foundry:setup (requires `foundry` plugin)); editing rule content (edit the plugin source)."
argument-hint: '[--approve]'
allowed-tools: Bash, AskUserQuestion
effort: low
model: sonnet
---

<objective>

Deliver research's rules to Claude's user-level rule namespace.

| Action | What happens |
| -- | -- |
| `rules/*.md` → `~/.claude/rules/research-<name>.md` | symlink |
| Stale link from an older research version | refreshed silently |
| Link whose source left the plugin | removed |
| Real file or foreign link at a destination | preserved, reported as conflict |
| Anything outside `~/.claude/rules/` | never touched |

**Why namespaced?** Claude loads user rules from one flat directory. Four plugins ship a `rules/quality-gates.md`; installing source basenames would collide. Every rule installs as `<plugin>-<source-name>.md`, so `quality-gates.md` becomes `research-quality-gates.md`. The prefix is inert — verified against Claude Code 2.1.220 that a filename prefix changes neither unconditional loading nor `paths:` frontmatter matching.

**Why symlink, not copy?** Rules load at session start. A symlink serves the installed version after every upgrade; a copy silently serves stale content forever.

**Why does research deliver only its own rules?** Each plugin installs independently. A plugin that shipped a sibling's rules would break standalone installation and couple releases.

NOT for: `~/.claude/settings.json`, statusLine, `TEAM_PROTOCOL.md`, or plugin-cache purging — those are `/foundry:setup` (requires `foundry` plugin). Writes nothing under `~/.codex/`.

</objective>

<inputs>

- **No arguments** — interactive; prompts before replacing a conflicting destination.
- **`--approve`** — non-interactive; replaces conflicting destinations without asking. Used by `bash sync.sh`.

</inputs>

<workflow>

## Step 0: Flags

Parse `$ARGUMENTS` for `--approve` (case-insensitive) → `APPROVE_ALL=true`, else `false`. Any other `--<token>` → print `` ! Unknown flag(s): `--<token>`. Supported: `--approve`. `` and stop.

## Step 1: Python

```bash
PYTHON_CMD=""
for c in python python3; do
    command -v "$c" >/dev/null 2>&1 && "$c" --version 2>/dev/null | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])" && PYTHON_CMD="$c" && break
done
if [ -z "$PYTHON_CMD" ] && command -v py >/dev/null 2>&1 && py -3 --version 2>/dev/null | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])"; then
    PYTHON_CMD="py -3"
fi
[ -z "$PYTHON_CMD" ] && { printf "! Python 3.10+ not found — install it and re-run /research:setup\n"; exit 1; }
printf "  Python: %s\n" "$PYTHON_CMD"
```

## Step 2: Dry run — see what would change

`$CLAUDE_PLUGIN_ROOT` is the installed plugin version. `sync_rules.py` re-validates it (manifest exists, parses, declares `research`; `rules/` is a real directory holding at least one non-empty regular `*.md`) and aborts before touching anything if any check fails.

```bash
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}"
python "$PLUGIN_ROOT/bin/sync_rules.py" --plugin-name research --plugin-root "$PLUGIN_ROOT" --dry-run  # timeout: 15000
```

Non-zero exit → print stderr verbatim and stop; nothing was modified.

## Step 3: Apply

Run without `--dry-run`. Add `--approve` only when `APPROVE_ALL=true`:

```bash
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}"
python "$PLUGIN_ROOT/bin/sync_rules.py" --plugin-name research --plugin-root "$PLUGIN_ROOT"  # timeout: 15000
```

Output lines, one per destination: `linked:` · `unchanged:` · `replaced (--approve):` · `removed obsolete:` · `conflict, kept as-is:` · `FAILED:`.

Ownership is proved before any replace or remove: the existing link must resolve under the current plugin root, or under the same `~/.claude/plugins/cache/<marketplace>/research/` lineage as the current install. A link into another marketplace, another plugin, a source checkout, or a dotfiles tree is never adopted — path substrings are not evidence of ownership.

## Step 4: Conflicts

No `conflict, kept as-is:` lines → skip to Step 5.

`APPROVE_ALL=true` → conflicts were already replaced in Step 3; skip to Step 5.

Otherwise invoke `AskUserQuestion`, listing each conflicting destination and its current state:

- (a) **Keep them** — those rules stay undelivered
- (b) **Replace all with plugin links** ★ recommended — existing content is overwritten
- (c) **Abort** — leave everything as it is

On **(b)**, re-run Step 3's command with `--approve` appended and report the resulting `replaced (--approve):` lines. On (a) or (c), report which rules remain undelivered.

## Step 5: Report

- Rules linked: N → `~/.claude/rules/research-*.md`
- Unchanged: N · Obsolete removed: N · Conflicts kept: N (name each)
- Failures: N (name each; a failure means the platform refused the symlink — rules are never copied as a fallback)

</workflow>

<notes>

**Upgrade path**: `claude plugin install research@borda-ai-rig` then `/research:setup`. Links from the previous version share the install-cache lineage, so they refresh without prompting; a rule dropped in the new version has its link removed. `bash sync.sh claude` runs `/research:setup --approve` headlessly for every installed managed plugin that ships a setup skill, so a normal sync needs no manual step.

**Uninstall leaves state behind**: Claude Code runs no cleanup hook on uninstall, and neither `claude plugin uninstall` nor `bash sync.sh clear` removes what setup created. After removing the plugin, delete `~/.claude/rules/research-*.md` by hand — they become dangling symlinks once the plugin cache version is gone.

**Testing**: setup is reachable only as `/research:setup` after the plugin is installed. To exercise it locally, bump `version` in `plugins/cc_research/.claude-plugin/plugin.json`, run `claude plugin install research@borda-ai-rig` from the repo root to refresh the cache, then invoke the skill. `bin/sync_rules.py` is a byte-identical propagated copy of the canonical helper; its regression suite lives beside that canonical copy in the AI-Rig repository.

**Follow-up gate omitted** — setup is one-shot; Step 5 is terminal output.

</notes>
