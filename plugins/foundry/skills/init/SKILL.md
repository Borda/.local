---
name: init
description: "Post-install setup for foundry plugin. Merges statusLine, permissions.allow, and enabledPlugins into ~/.claude/settings.json; symlinks rules, TEAM_PROTOCOL.md, and skills into ~/.claude/."
allowed-tools: Read, Write, Bash, AskUserQuestion
effort: low
model: sonnet
argument-hint: "[--approve]"
---

<objective>

Set up foundry on new machine:

| Action | What happens |
| --- | --- |
| Merge `statusLine`, `permissions.allow`, `enabledPlugins` → `~/.claude/settings.json` | ✓ |
| `rules/*.md` → `~/.claude/rules/` | symlink |
| `TEAM_PROTOCOL.md` → `~/.claude/` | symlink |
| `skills/*` → `~/.claude/skills/` | symlink |
| `hooks/hooks.json` | auto — plugin system |
| Conflict review before overwriting existing user files | ✓ |

**Why symlink rules and skills (not copy)?** Rules, TEAM_PROTOCOL.md, and skills load at session startup. Symlinks = every session gets plugin's current version — no stale copies, no re-run after upgrades. Broken symlink after upgrade = obvious error; stale copy silently serves old content.

**Why symlink skills explicitly?** `claude plugin install` creates `~/.claude/skills/` symlinks on first install but does NOT update them on upgrade — old version directory stays in cache, symlinks go stale. Init's stale-version detection (same pattern as rules) replaces them silently on every re-run.

**Why not symlink agents?** Agents must always use full plugin prefix (`foundry:sw-engineer`, not `sw-engineer`) for unambiguous dispatch. Plugin system exposes agents at `foundry:` namespace — no `~/.claude/agents/` symlinks needed.

**Why hooks need no action?** `hooks/hooks.json` inside plugin registers automatically when plugin enabled. Init's only hook-adjacent step: write `statusLine.command` path (Step 4) — `statusLine` is top-level settings key, not part of `hooks.json`.

NOT for: editing project `.claude/settings.json`.

</objective>

<inputs>

- **No arguments** — interactive mode; prompts on conflicts.
- **`--approve`** — non-interactive mode; auto-accepts all recommended answers. Use for scripted or CI setups.

</inputs>

<workflow>

## Flag detection

Parse `$ARGUMENTS` for `--approve` (case-insensitive). If found, set `APPROVE_ALL=true`; else `APPROVE_ALL=false`.

When `APPROVE_ALL=true`, every `AskUserQuestion` below **skipped** — ★ recommended option applied automatically. Print `[--approve] auto-accepting recommended option` in place of question.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Step 1: Locate the installed plugin

Execute this exact jq command — do not parse the JSON manually:

```bash
# Primary: registry lookup — sort by installedAt desc, pick latest install path
PLUGIN_ROOT=$(jq -r '
    .plugins
    | to_entries[]
    | select(.key | ascii_downcase | contains("foundry"))
    | .value[]
    | select(.installPath != null)
    | [.installedAt, .installPath]
    | @tsv
' "$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null \
    | sort -rk1 | head -1 | cut -f2)  # timeout: 5000

# Fallback: filesystem scan — skip orphaned dirs, semver-sort descending, pick latest
if [ -z "$PLUGIN_ROOT" ]; then
    PLUGIN_ROOT=$(find ~/.claude/plugins/cache -maxdepth 5 -name "plugin.json" 2>/dev/null \
            | xargs grep -l '"name"[[:space:]]*:[[:space:]]*"foundry"' 2>/dev/null \
            | while IFS= read -r f; do
                dir=$(dirname "$(dirname "$f")")
                [ -f "$dir/.orphaned_at" ] && continue
                echo "$dir"
              done \
            | sort -Vr | head -1)  # timeout: 10000
    [ -n "$PLUGIN_ROOT" ] && printf "  Note: foundry not in installed_plugins.json — using cache scan result; consider reinstalling\n"
fi
```

If `$PLUGIN_ROOT` empty after both attempts, stop and report: "foundry plugin not found — install it first with: `claude plugin marketplace add /path/to/Borda-AI-Rig && claude plugin install foundry@borda-ai-rig`"

Confirm `$PLUGIN_ROOT/hooks/statusline.js` exists. If not, stop and report.

## Step 2: Back up settings.json

If `~/.claude/settings.json` does not exist, create it using the Write tool with content `{}`.

```bash
INIT_BAK_TS=$(date -u +%Y%m%dT%H%M%SZ)
cp ~/.claude/settings.json "$HOME/.claude/settings.json.bak-${INIT_BAK_TS}"  # timeout: 5000
```

Report: "Backed up ~/.claude/settings.json → ~/.claude/settings.json.bak-<timestamp>"

## Step 3: Check for stale hooks block

```bash
jq -e 'has("hooks")' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If `hooks` key exists, user has pre-plugin-migration settings block — hooks fire twice.

If `APPROVE_ALL=true`: print `[--approve] auto-accepting: remove stale hooks block` and proceed to remove (apply option a below).

Otherwise, use `AskUserQuestion`:

- a) Remove stale `hooks` block now ★ recommended (backup in place from Step 2)
- b) Skip — I'll handle manually

On **(a)**: use jq to strip `hooks` key, write back with Write tool, continue. On **(b)**: warn "Double-firing risk: existing hooks block will fire alongside plugin-registered hooks." Continue.

## Step 4: Merge statusLine

Check if statusLine already points to statusline.js:

```bash
jq -e '(.statusLine.command // "") | contains("statusline.js")' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If already set: report "statusLine already set — skipping." Otherwise:

Writes `statusLine` key to `~/.claude/settings.json`:

```bash
jq --arg cmd "node \"$PLUGIN_ROOT/hooks/statusline.js\"" \
    '.statusLine = {"async":true,"command":$cmd,"type":"command"}' \
    ~/.claude/settings.json > /tmp/foundry_init_tmp.json  # timeout: 5000
```

Write `/tmp/foundry_init_tmp.json` back to `~/.claude/settings.json` using Write tool.

## Step 5: Merge permissions.allow and permissions.deny

Read `$PLUGIN_ROOT/.claude-plugin/permissions-allow.json` using Read tool. Merge into `~/.claude/settings.json` — add only entries not already present (exact string match):

Writes merged `permissions.allow` array:

```bash
jq --slurpfile perms "$PLUGIN_ROOT/.claude-plugin/permissions-allow.json" \
    '.permissions.allow = ((.permissions.allow // []) + $perms[0] | unique)' \
    ~/.claude/settings.json > /tmp/foundry_init_tmp.json  # timeout: 5000
```

Write back with Write tool. Report: "Added N new permissions.allow entries (M already present)."

Check whether `$PLUGIN_ROOT/.claude-plugin/permissions-deny.json` exists. If so, read with Read tool and merge — add only entries not already present:

Writes merged `permissions.deny` array:

```bash
jq --slurpfile deny "$PLUGIN_ROOT/.claude-plugin/permissions-deny.json" \
    '.permissions.deny = ((.permissions.deny // []) + $deny[0] | unique)' \
    ~/.claude/settings.json > /tmp/foundry_init_tmp.json  # timeout: 5000
```

Write back with Write tool. Report: "Added N new permissions.deny entries (M already present)."

## Step 6: Copy permissions-guide.md

Note: this step writes to `.claude/permissions-guide.md` relative to the current working directory — init must be run from project root (a git repository root). Guard:

```bash
[ -e ".git" ] || { echo "! Run /foundry:init from project root (git repository root)"; exit 1; }
```

Copy `$PLUGIN_ROOT/permissions-guide.md` to `.claude/permissions-guide.md` — only if destination absent (preserves project-local edits via `/manage`):

```bash
if [ ! -f ".claude/permissions-guide.md" ]; then  # timeout: 5000
    cp "$PLUGIN_ROOT/permissions-guide.md" ".claude/permissions-guide.md"
    printf "  copied: permissions-guide.md\n"
else
    printf "  permissions-guide.md already present — skipping\n"
fi
```

## Step 7: Merge enabledPlugins

```bash
jq -e '.enabledPlugins["codex@openai-codex"] == true' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If already `true`: report "enabledPlugins already set — skipping." Otherwise:

Writes `enabledPlugins["codex@openai-codex"]` key:

```bash
jq '.enabledPlugins["codex@openai-codex"] = true' \
    ~/.claude/settings.json > /tmp/foundry_init_tmp.json  # timeout: 5000
```

Write back with Write tool.

## Step 8: Validate

After all writes, confirm file parses as valid JSON:

```bash
jq empty ~/.claude/settings.json  # timeout: 5000
```

If `jq` exits non-zero: restore from backup (`cp "$HOME/.claude/settings.json.bak-${INIT_BAK_TS}" ~/.claude/settings.json`), report error, stop. If valid: continue.

## Step 9: Symlink rules and TEAM_PROTOCOL.md

Ensure target dir exists:

```bash
mkdir -p ~/.claude/rules  # timeout: 5000
```

**Phase 1 — Remove obsolete foundry-managed symlinks** (file/dir removed from current plugin version, or dangling target):

```bash
# timeout: 15000
for dest in "$HOME/.claude/rules/"*.md; do
    [ -L "$dest" ] || continue
    target=$(readlink "$dest")
    echo "$target" | grep -q "borda-ai-rig/foundry/" || continue  # not foundry-managed — skip
    echo "$target" | grep -q "$PLUGIN_ROOT" && continue           # already current — skip
    base=$(basename "$dest")
    if [ ! -f "$PLUGIN_ROOT/rules/$base" ]; then
        rm "$dest"
        printf "  removed obsolete: %s\n" "$base"
    fi
done
if [ -L "$HOME/.claude/TEAM_PROTOCOL.md" ]; then
    target=$(readlink "$HOME/.claude/TEAM_PROTOCOL.md")
    if echo "$target" | grep -q "borda-ai-rig/foundry/" \
    && ! echo "$target" | grep -q "$PLUGIN_ROOT" \
    && [ ! -f "$PLUGIN_ROOT/TEAM_PROTOCOL.md" ]; then
        unlink "$HOME/.claude/TEAM_PROTOCOL.md"
        printf "  removed obsolete: TEAM_PROTOCOL.md\n"
    fi
fi
# Skills — remove symlinks for dirs no longer in current plugin version
for dest in "$HOME/.claude/skills/"*/; do
    skill_link="${dest%/}"
    [ -L "$skill_link" ] || continue
    target=$(readlink "$skill_link")
    echo "$target" | grep -q "borda-ai-rig/foundry/" || continue  # not foundry-managed — skip
    echo "$target" | grep -q "$PLUGIN_ROOT" && continue           # already current — skip
    skill=$(basename "$skill_link")
    if [ ! -d "$PLUGIN_ROOT/skills/$skill" ]; then
        unlink "$skill_link"
        printf "  removed obsolete skill: %s\n" "$skill"
    fi
done
```

**Phase 2 — Conflict scan** — identify entries needing user confirmation. Stale foundry symlinks (old version → current) are auto-replaced in Phase 4 without prompt:

```bash
LINK_CONFLICTS=()
# timeout: 30000
for src in "$PLUGIN_ROOT/rules/"*.md; do
    dest="$HOME/.claude/rules/$(basename "$src")"
    if [ -L "$dest" ]; then
        target=$(readlink "$dest")
        if echo "$target" | grep -q "$PLUGIN_ROOT"; then
            : # current — skip
        elif echo "$target" | grep -q "borda-ai-rig/foundry/"; then
            : # stale foundry version — auto-replace in Phase 4 (no prompt)
        else
            LINK_CONFLICTS+=("rules/$(basename "$src") → $target")
        fi
    elif [ -f "$dest" ]; then
        LINK_CONFLICTS+=("rules/$(basename "$src")  (real file)")
    fi
done
src="$PLUGIN_ROOT/TEAM_PROTOCOL.md"; dest="$HOME/.claude/TEAM_PROTOCOL.md"
if [ -L "$dest" ]; then
    target=$(readlink "$dest")
    if echo "$target" | grep -q "$PLUGIN_ROOT"; then
        : # current — skip
    elif echo "$target" | grep -q "borda-ai-rig/foundry/"; then
        : # stale foundry version — auto-replace in Phase 4 (no prompt)
    else
        LINK_CONFLICTS+=("TEAM_PROTOCOL.md → $target")
    fi
elif [ -f "$dest" ]; then
    LINK_CONFLICTS+=("TEAM_PROTOCOL.md  (real file)")
fi
# Skills conflict scan
mkdir -p "$HOME/.claude/skills"  # timeout: 5000
for src_dir in "$PLUGIN_ROOT/skills/"*/; do
    skill=$(basename "${src_dir%/}")
    dest="$HOME/.claude/skills/$skill"
    if [ -L "$dest" ]; then
        target=$(readlink "$dest")
        if echo "$target" | grep -q "$PLUGIN_ROOT"; then
            : # current — skip
        elif echo "$target" | grep -q "borda-ai-rig/foundry/"; then
            : # stale foundry version — auto-replace in Phase 4 (no prompt)
        else
            LINK_CONFLICTS+=("skills/$skill → $target")
        fi
    elif [ -e "$dest" ]; then
        LINK_CONFLICTS+=("skills/$skill  (real entry)")
    fi
done
```

**Phase 3 — Handle remaining conflicts** (real files or symlinks to non-foundry paths):

If `$LINK_CONFLICTS` empty: skip to Phase 4.

If `APPROVE_ALL=true`: print `[--approve] auto-accepting: replace all symlink conflicts` and replace all (apply option a below). # --approve mode: auto-accept all conflicts; AskUserQuestion skipped

Otherwise, use `AskUserQuestion`:

```markdown
These entries in ~/.claude/ would be replaced with symlinks to the foundry plugin:
  - <name>  (<current state>)
  - …
```

Options:

- a) Replace all ★ recommended
- b) Skip all conflicts — keep existing files unchanged
- c) Review one by one

On **(b)**: set `SKIP_CONFLICTS_MODE=true`.
On **(c)**: loop with `AskUserQuestion` — "Replace `<name>`? (y) Yes / (n) Skip". Append approved names to `APPROVED_CONFLICT_ENTRIES` array.

**Phase 4 — Symlink** — for each approved, auto-replaced, or absent entry, `ln -sf` creates/replaces. Stale foundry symlinks from Phase 2 are included here (auto-replaced silently). Conflict guard: if `SKIP_CONFLICTS_MODE=true`, skip real files (`[ -f "$dest" ] && [ ! -L "$dest" ]`) — those were entries user declined:

```bash
for src in "$PLUGIN_ROOT/rules/"*.md; do
    dest="$HOME/.claude/rules/$(basename "$src")"
    if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -f "$dest" ] && [ ! -L "$dest" ]; then
        echo "  skipped (user choice b): $(basename "$src")"; continue
    fi
    unlink "$dest" 2>/dev/null || true; ln -sf "$src" "$dest"  # timeout: 5000
    echo "  linked: $(basename "$src")"
done  # timeout: 10000
dest="$HOME/.claude/TEAM_PROTOCOL.md"
if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -f "$dest" ] && [ ! -L "$dest" ]; then
    echo "  skipped (user choice b): TEAM_PROTOCOL.md"
else
    unlink "$dest" 2>/dev/null || true; ln -sf "$PLUGIN_ROOT/TEAM_PROTOCOL.md" "$dest"  # timeout: 5000
    echo "  linked: TEAM_PROTOCOL.md"
fi
# Skills — ln -sf each skills/ subdir; handles stale foundry and absent entries
for src_dir in "$PLUGIN_ROOT/skills/"*/; do
    skill=$(basename "${src_dir%/}")
    dest="$HOME/.claude/skills/$skill"
    if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -e "$dest" ] && [ ! -L "$dest" ]; then
        echo "  skipped (user choice b): skill:$skill"; continue
    fi
    unlink "$dest" 2>/dev/null || true; ln -sf "${src_dir%/}" "$dest"  # timeout: 5000
    echo "  linked skill: $skill"
done  # timeout: 10000
```

## Step 10: Final report

Print summary:

- statusLine: set / skipped
- permissions.allow: N entries added
- enabledPlugins: set / skipped
- Rules removed obsolete: N (files no longer in current plugin version)
- Rules linked: N → ~/.claude/rules/
- TEAM_PROTOCOL.md linked → ~/.claude/TEAM_PROTOCOL.md
- Skills linked: N → ~/.claude/skills/
- Backup at: ~/.claude/settings.json.bak

</workflow>

<notes>

**Follow-up gate omitted** — init is a one-shot setup skill; no iterative follow-up action applies. Step 10 summary is the terminal output; no `AskUserQuestion` gate required.

**Testing init changes**: Init skill has no `.claude/skills/init` entry — only reachable as `/foundry:init` after plugin installed. To test: bump `version` in `plugins/foundry/.claude-plugin/plugin.json`, run `claude plugin install foundry@borda-ai-rig` from repo root to refresh cache, invoke `/foundry:init`. **Upgrade path**: After `claude plugin install foundry@borda-ai-rig` upgrades version, re-run `/foundry:init` — Step 9 Phase 1 removes rules and skill symlinks that no longer exist in new version; Phase 2–4 auto-replaces stale foundry symlinks (rules + skills) without prompting; real-file and non-foundry-path conflicts still surfaced for user review. Note: `bash sync.sh` calls `/foundry:init` headlessly at end — skill symlinks are updated automatically on every sync run.

</notes>
