---
name: setup
description: "Post-install setup for foundry plugin. Run once after installing on a new machine, or after a plugin version upgrade to sync settings and symlinks. Merges statusLine, permissions.allow, enabledPlugins, and advisorModel into ~/.claude/settings.json; symlinks rules, TEAM_PROTOCOL.md, and skills into ~/.claude/."
argument-hint: "[--approve]"
allowed-tools: Read, Write, Bash, AskUserQuestion
effort: low
model: sonnet
---

<objective>

Set up foundry on new machine:

| Action | What happens |
| --- | --- |
| Detect Python 3.10+ (`python` / `py -3` / `python3`); install `~/.local/bin/python` shim if needed | ✓ |
| Merge `statusLine`, `permissions.allow`, `enabledPlugins`, `advisorModel` → `~/.claude/settings.json` | ✓ |
| `rules/*.md` → `~/.claude/rules/` | symlink |
| `TEAM_PROTOCOL.md` → `~/.claude/` | symlink |
| `skills/*` → `~/.claude/skills/` | symlink |
| `hooks/hooks.json` | auto — plugin system |
| Conflict review before overwriting existing user files | ✓ |

**Why symlink rules and skills (not copy)?** Rules, TEAM_PROTOCOL.md, and skills load at session startup. Symlinks = every session gets plugin's current version — no stale copies, no re-run after upgrades. Broken symlink after upgrade = obvious error; stale copy silently serves old content.

**Why symlink skills explicitly?** `claude plugin install` creates `~/.claude/skills/` symlinks on first install but does NOT update them on upgrade — old version directory stays in cache, symlinks go stale. Setup's stale-version detection (same pattern as rules) replaces them silently on every re-run.

**Why not symlink agents?** Agents must use full plugin prefix (`foundry:sw-engineer`, not `sw-engineer`) for unambiguous dispatch. Plugin system exposes agents at `foundry:` namespace — no `~/.claude/agents/` symlinks needed. (Stale agent symlinks from prior installs removed by setup's Phase 1 cleanup.)

**Why hooks need no action?** `hooks/hooks.json` inside plugin registers automatically when plugin enabled. Setup's only hook-adjacent step: write `statusLine.command` path (Step 4) — `statusLine` is top-level settings key, not part of `hooks.json`.

NOT for: editing project `.claude/settings.json` (Step 8 READS it to propagate advisorModel, never writes it).

</objective>

<inputs>

- **No arguments** — interactive mode; prompts on conflicts.
- **`--approve`** — non-interactive mode; auto-accepts all recommended answers. Use for scripted or CI setups.

</inputs>

<workflow>

## Flag detection

Parse `$ARGUMENTS` for `--approve` (case-insensitive). If found, set `APPROVE_ALL=true`; else `APPROVE_ALL=false`.

**Early git repository check** — Step 6 requires a git repository. In `--approve` mode there is no interactive fallback, so check immediately before Step 1:

```bash
if [ "$APPROVE_ALL" = "true" ] && [ ! -e ".git" ]; then
    printf "! --approve requires git repository — run from project root\n"
    exit 1
fi
```

When `APPROVE_ALL=true`, every `AskUserQuestion` below **skipped** — ★ recommended option applied automatically. Print `[--approve] auto-accepting recommended option` in place of question.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--approve\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Python detection

Probe Python 3.10+ — required before any `bin/*.py` calls. Windows Store stub returns exit 9009 when given args; caught by `2>/dev/null`:

```bash
PYTHON_CMD=""
SHIM_DIR="$HOME/.local/bin"
if command -v python >/dev/null 2>&1 && python --version 2>/dev/null | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])"; then
    PYTHON_CMD="python"
elif command -v py >/dev/null 2>&1 && py -3 --version 2>/dev/null | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])"; then
    PYTHON_CMD="py -3"
    mkdir -p "$SHIM_DIR"
    printf '#!/usr/bin/env bash\npy -3 "$@"\n' > "$SHIM_DIR/python"
    chmod +x "$SHIM_DIR/python"
    printf "  Python shim installed: %s/python → py -3\n" "$SHIM_DIR"
elif command -v python3 >/dev/null 2>&1 && python3 --version 2>/dev/null | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])"; then
    PYTHON_CMD="python3"
    mkdir -p "$SHIM_DIR"
    printf '#!/usr/bin/env bash\npython3 "$@"\n' > "$SHIM_DIR/python"
    chmod +x "$SHIM_DIR/python"
    printf "  Python shim installed: %s/python → python3\n" "$SHIM_DIR"
else
    printf "! Python 3.10+ not found — install Python 3.10+ and re-run /foundry:setup\n"
    exit 1
fi
printf "  Python: %s\n" "$PYTHON_CMD"

# ~/.local/bin is XDG-standard but not always on PATH
if [ -f "$SHIM_DIR/python" ] && ! echo ":$PATH:" | grep -q ":$SHIM_DIR:"; then
    printf "  ⚠ %s not on PATH — add to shell rc:\n      export PATH=\"\$HOME/.local/bin:\$PATH\"\n" "$SHIM_DIR"
fi
```

`~/.local/bin` is XDG-standard user-bin directory on modern macOS/Linux. Shim created only when `python` absent or resolves to Store stub. Idempotent — re-running setup overwrites shim with same content. If `~/.local/bin` not yet on `$PATH`, setup prints `export PATH="$HOME/.local/bin:$PATH"` line for user's shell rc.

## Step 1: Locate the installed plugin

Resolve validated install root via canonical resolver — registry lookup, cache-scan fallback (skips `.orphaned_at`, newest by semver), and both security gates (under cache dir + `plugin.json` name match) live in the script; do not re-implement inline:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLUGIN_ROOT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_foundry}/bin/resolve_plugin_root.py" --plugin-name foundry 2>/dev/null)  # timeout: 15000
case $? in
    0) ;;
    2) echo "! SECURITY: resolve_plugin_root.py rejected the candidate root — aborting setup"; exit 1 ;;
    *) PLUGIN_ROOT="" ;;  # not found; handled by empty-check below
esac
echo "$PLUGIN_ROOT" > "${TMPDIR:-/tmp}/setup-plugin-root-${CSID}"  # persist for later blocks (Check 41)
```

If `$PLUGIN_ROOT` empty after both attempts, stop and report: "foundry plugin not found — install it first with: `claude plugin marketplace add Borda/AI-Rig && claude plugin install foundry@borda-ai-rig`"

Confirm `$PLUGIN_ROOT/hooks/statusline.js` exists. If not, stop and report.

## Step 2: Back up settings.json

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
SETUP_BAK_TS=$(date -u +%Y%m%dT%H%M%SZ)
[ -f ~/.claude/settings.json ] || printf '{}\n' > ~/.claude/settings.json  # create empty in-bash if absent — no Write-tool permission prompt (headless-safe)
cp ~/.claude/settings.json "$HOME/.claude/settings.json.bak-${SETUP_BAK_TS}"  # timeout: 5000
echo "$SETUP_BAK_TS" > "${TMPDIR:-/tmp}/foundry-setup-bak-ts-${CSID}"  # persist for restore in Step 9
```

Report: "Backed up ~/.claude/settings.json → ~/.claude/settings.json.bak-<timestamp>"

## Step 3: Check for stale hooks block

```bash
jq -e 'has("hooks")' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If `hooks` key exists, user has pre-plugin-migration settings block — hooks fire twice.

If `APPROVE_ALL=true`: print `[--approve] auto-accepting: remove stale hooks block` and proceed to remove (apply option a below).

Otherwise, use `AskUserQuestion`:

(a) Remove stale `hooks` block now ★ recommended (backup in place from Step 2)
(b) Skip — I'll handle manually

On **(a)**: strip `hooks` key in-bash (no Write tool), continue:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq 'del(.hooks)' ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed stripping hooks — settings.json unchanged\n"; exit 1; }
```

On **(b)**: warn "Double-firing risk: existing hooks block will fire alongside plugin-registered hooks." Continue.

## Step 4: Merge statusLine

Check if statusLine already points to the **current** plugin's statusline.js (filename match alone is insufficient — a stale entry from an older plugin version survives upgrades and silently runs the previous hook). Verify both that the command contains `statusline.js` AND that the `$PLUGIN_ROOT` path (with its version segment) appears in the command string:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLUGIN_ROOT=$(cat "${TMPDIR:-/tmp}/setup-plugin-root-${CSID}" 2>/dev/null)  # reload (Check 41)
jq --arg root "$PLUGIN_ROOT" -e '
    (.statusLine.command // "") as $cmd
    | ($cmd | contains("statusline.js")) and ($cmd | contains($root))
' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If already set to the current `$PLUGIN_ROOT`: report "statusLine already set to current plugin version — skipping." If a stale entry exists (statusline.js present but `$PLUGIN_ROOT` does not match), the check returns non-zero and the merge below overwrites with the current path. Otherwise:

Writes `statusLine` key to `~/.claude/settings.json`:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq --arg cmd "node \"$PLUGIN_ROOT/hooks/statusline.js\"" \
    '.statusLine = {"async":true,"command":$cmd,"type":"command"}' \
    ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed updating statusLine — settings.json unchanged\n"; exit 1; }
```

Writeback happens in-bash above (`mv` — no Write-tool permission prompt, headless-safe). Report: `  statusLine: set to current plugin version`.

## Step 5: Merge permissions.allow and permissions.deny

Merge `$PLUGIN_ROOT/.claude-plugin/permissions-allow.json` into `~/.claude/settings.json` via jq below — add only entries not already present (exact string match):

Writes merged `permissions.allow` array:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq --slurpfile perms "$PLUGIN_ROOT/.claude-plugin/permissions-allow.json" \
    '.permissions.allow = ((.permissions.allow // []) + $perms[0] | unique)' \
    ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed merging permissions.allow — settings.json unchanged\n"; exit 1; }
```

Writeback happens in-bash above (`mv`). Report: "Added N new permissions.allow entries (M already present)."

Check whether `$PLUGIN_ROOT/.claude-plugin/permissions-deny.json` exists. If so, merge via jq below — add only entries not already present:

Writes merged `permissions.deny` array:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq --slurpfile deny "$PLUGIN_ROOT/.claude-plugin/permissions-deny.json" \
    '.permissions.deny = ((.permissions.deny // []) + $deny[0] | unique)' \
    ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed merging permissions.deny — settings.json unchanged\n"; exit 1; }
```

Writeback happens in-bash above (`mv`). Report: "Added N new permissions.deny entries (M already present)."

## Step 6: Copy permissions-guide.md

Note: this step writes to `.claude/permissions-guide.md` relative to the current working directory — setup must be run from project root (a git repository root). Guard:

```bash
[ -e ".git" ] || { printf "! BLOCKED — /foundry:setup must run from project root (git repository root)\n"; exit 1; }
```

Copy `$PLUGIN_ROOT/permissions-guide.md` to `.claude/permissions-guide.md` — only if destination absent (preserves project-local edits via `/manage`):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLUGIN_ROOT=$(cat "${TMPDIR:-/tmp}/setup-plugin-root-${CSID}" 2>/dev/null)  # reload: fresh shell (Check 41)
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
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq '.enabledPlugins["codex@openai-codex"] = true' \
    ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed updating enabledPlugins — settings.json unchanged\n"; exit 1; }
```

Writeback happens in-bash above (`mv`).

## Step 8: Merge advisorModel (from project settings)

```bash
ADV=""
if [ -f ".claude/settings.json" ]; then
    ADV=$(jq -r '.advisorModel // empty' .claude/settings.json 2>/dev/null)  # timeout: 5000
fi
```

If `$ADV` empty: report `  advisorModel: skipped (not pinned in project .claude/settings.json)` and continue.

Check if global already equals it:

```bash
jq --arg m "$ADV" -e '.advisorModel == $m' ~/.claude/settings.json >/dev/null 2>&1  # timeout: 5000
```

If already equal: report `  advisorModel already set to <value> — skipping.`

Otherwise:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_jq_result=$(jq --arg m "$ADV" '.advisorModel = $m' ~/.claude/settings.json)  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_jq_result" ] && printf '%s\n' "$_jq_result" > "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" && mv "${TMPDIR:-/tmp}/foundry_setup_tmp.json-${CSID}" ~/.claude/settings.json || { printf "! jq failed updating advisorModel — settings.json unchanged\n"; exit 1; }
```

Writeback happens in-bash above (`mv` — no Write-tool permission prompt). Report `  advisorModel: set to <value>`.

## Step 9: Validate

After all writes, confirm file parses as valid JSON:

```bash
jq empty ~/.claude/settings.json  # timeout: 5000
```

If `jq` exits non-zero: restore from backup: `export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"; SETUP_BAK_TS=$(cat "${TMPDIR:-/tmp}/foundry-setup-bak-ts-${CSID}" 2>/dev/null || ls -t "$HOME/.claude/settings.json.bak-"* 2>/dev/null | head -1 | sed 's/.*\.bak-//'); cp "$HOME/.claude/settings.json.bak-${SETUP_BAK_TS}" ~/.claude/settings.json`, report error, stop. If valid: continue.

## Step 10: Symlink rules and TEAM_PROTOCOL.md

Ensure target dir exists:

```bash
mkdir -p ~/.claude/rules  # timeout: 5000
```

**Phase 1 — Remove obsolete foundry-managed symlinks** (file/dir removed from current plugin version, or dangling target):

```bash
# re-resolve — Bash state not persistent across steps; use installed cache path, not local fallback
PLUGIN_ROOT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_foundry}/bin/resolve_plugin_root.py" --plugin-name foundry 2>/dev/null)  # timeout: 15000
[ -z "$PLUGIN_ROOT" ] && { printf "! setup Phase 1 — could not resolve PLUGIN_ROOT; run claude plugin install foundry@borda-ai-rig first\n"; exit 1; }
python "$PLUGIN_ROOT/bin/symlink_with_guard.py" cleanup --plugin-root "$PLUGIN_ROOT"  # timeout: 15000
```

The script iterates rules (`*.md`), `TEAM_PROTOCOL.md`, and skill dirs; removes any foundry-managed symlink (target contains `borda-ai-rig/foundry/`) that is both stale (target does not resolve under `$PLUGIN_ROOT`) and whose source no longer exists in current plugin tree. Each removal prints `  removed obsolete: <name>` / `  removed obsolete skill: <name>`.

Cleanup also scans `~/.claude/agents/` for foundry-managed symlinks (targets containing `borda-ai-rig/foundry/`) and removes them unconditionally — foundry agents served directly from plugin namespace, not via `~/.claude/agents/` symlinks. Each removal prints `  removed obsolete agent: <name>`.

**Phase 2 — Conflict scan** — identify entries needing user confirmation. Stale foundry symlinks (old version → current) are auto-replaced in Phase 4 without prompt:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
mkdir -p "$HOME/.claude/skills"  # timeout: 5000
mapfile -t LINK_CONFLICTS < <(python "$PLUGIN_ROOT/bin/symlink_with_guard.py" scan --plugin-root "$PLUGIN_ROOT")  # timeout: 30000
printf '%s\n' "${LINK_CONFLICTS[@]}" > "${TMPDIR:-/tmp}/foundry-setup-conflicts-${CSID}.txt"  # timeout: 3000; persist for Phase 4; Bash calls don't share state
```

The `scan` mode walks the same three patterns (rules `*.md`, `TEAM_PROTOCOL.md`, skill dirs) and prints one conflict per line. Entries surface only when the dest is a real file or a symlink whose target does NOT contain `borda-ai-rig/foundry/`. Output format matches the legacy bash array entries: `rules/<name> → <target>` · `rules/<name>  (real file)` · `TEAM_PROTOCOL.md → <target>` · `skills/<name> → <target>` · `skills/<name>  (real entry)`.

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

(a) Replace all ★ recommended
(b) Skip all conflicts — keep existing files unchanged
(c) Review one by one

On **(b)**: set `SKIP_CONFLICTS_MODE=true`.
On **(c)**: initialize `APPROVED_CONFLICT_ENTRIES=()` and `PER_ITEM_REVIEW_MODE=true`. **Cap**: if `${#LINK_CONFLICTS[@]} > 10`, emit warning "⚠ ${#LINK_CONFLICTS[@]} conflicts found — per-item review capped at 10; showing first 10. Run again for the rest." and process only the first 10. Iterate over each entry (up to cap); for each, invoke `AskUserQuestion` — "Replace `<entry>`? (a) Yes — replace · (b) Skip — keep existing". On (a): append the entry's identifier (basename for rules, `TEAM_PROTOCOL.md`, or `skill:<name>`) to `APPROVED_CONFLICT_ENTRIES`. On (b): leave it out. After the loop, persist: `export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"; printf '%s\n' "${APPROVED_CONFLICT_ENTRIES[@]}" > ${TMPDIR:-/tmp}/foundry-setup-approved-${CSID}.txt`. Items not in `$LINK_CONFLICTS` (current, stale foundry, absent) bypass this gate — handled silently in Phase 4.

**Phase 4 — Symlink** — for each approved, auto-replaced, or absent entry, `ln -sf` creates/replaces. Stale foundry symlinks from Phase 2 are included here (auto-replaced silently). Conflict guard depends on which Phase 3 branch fired:

- `SKIP_CONFLICTS_MODE=true` (option b): skip every entry that is a real file or non-foundry symlink — those are conflicts the user declined.
- `PER_ITEM_REVIEW_MODE=true` (option c): for entries that appear in `$LINK_CONFLICTS`, only replace when the entry's identifier is in `APPROVED_CONFLICT_ENTRIES`; otherwise skip. Entries not in `$LINK_CONFLICTS` (current / stale foundry / absent) always replace.
- Neither flag (option a or no conflicts): replace unconditionally.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# restore arrays from Phase 2/3; Bash calls don't share state
mapfile -t LINK_CONFLICTS < ${TMPDIR:-/tmp}/foundry-setup-conflicts-${CSID}.txt 2>/dev/null || LINK_CONFLICTS=()
mapfile -t APPROVED_CONFLICT_ENTRIES < ${TMPDIR:-/tmp}/foundry-setup-approved-${CSID}.txt 2>/dev/null || APPROVED_CONFLICT_ENTRIES=()

# is identifier in APPROVED_CONFLICT_ENTRIES?
_approved() {
    local needle="$1"
    for e in "${APPROVED_CONFLICT_ENTRIES[@]:-}"; do
        [ "$e" = "$needle" ] && return 0
    done
    return 1
}
# is this dest listed as conflict in Phase 2?
_in_conflicts() {
    local needle="$1"
    for c in "${LINK_CONFLICTS[@]:-}"; do
        # LINK_CONFLICTS entries start with "rules/<base>", "TEAM_PROTOCOL.md", or "skills/<name>"
        case "$c" in "$needle"*) return 0 ;; esac
    done
    return 1
}

for src in "$PLUGIN_ROOT/rules/"*.md; do
    dest="$HOME/.claude/rules/$(basename "$src")"
    base="$(basename "$src")"
    if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -e "$dest" ] && [ ! -L "$dest" ]; then
        echo "  skipped (user choice b): $base"; continue
    fi
    if [ "${PER_ITEM_REVIEW_MODE:-false}" = "true" ] && _in_conflicts "rules/$base" && ! _approved "rules/$base"; then
        echo "  skipped (user choice c — not approved): $base"; continue
    fi
    unlink "$dest" 2>/dev/null || true; ln -sf "$src" "$dest"  # timeout: 5000
    echo "  linked: $base"
done  # timeout: 10000
dest="$HOME/.claude/TEAM_PROTOCOL.md"
if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -e "$dest" ] && [ ! -L "$dest" ]; then
    echo "  skipped (user choice b): TEAM_PROTOCOL.md"
elif [ "${PER_ITEM_REVIEW_MODE:-false}" = "true" ] && _in_conflicts "TEAM_PROTOCOL.md" && ! _approved "TEAM_PROTOCOL.md"; then
    echo "  skipped (user choice c — not approved): TEAM_PROTOCOL.md"
else
    unlink "$dest" 2>/dev/null || true; ln -sf "$PLUGIN_ROOT/TEAM_PROTOCOL.md" "$dest"  # timeout: 5000
    echo "  linked: TEAM_PROTOCOL.md"
fi
# skills: 'setup' excluded — must invoke as /foundry:setup, not bare /setup
for src_dir in "$PLUGIN_ROOT/skills/"*/; do
    skill=$(basename "${src_dir%/}")
    [ "$skill" = "setup" ] && continue  # plugin-namespaced only; bare /setup ambiguous
    dest="$HOME/.claude/skills/$skill"
    if [ "${SKIP_CONFLICTS_MODE:-false}" = "true" ] && [ -e "$dest" ] && [ ! -L "$dest" ]; then
        echo "  skipped (user choice b): skill:$skill"; continue
    fi
    if [ "${PER_ITEM_REVIEW_MODE:-false}" = "true" ] && _in_conflicts "skills/$skill" && ! _approved "skill:$skill"; then
        echo "  skipped (user choice c — not approved): skill:$skill"; continue
    fi
    unlink "$dest" 2>/dev/null || true; ln -sf "${src_dir%/}" "$dest"  # timeout: 5000
    echo "  linked skill: $skill"
done  # timeout: 10000
```

## Step 11: Write CLAUDE.src.md → ~/.claude/CLAUDE.md

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
PLUGIN_ROOT=$(cat "${TMPDIR:-/tmp}/setup-plugin-root-${CSID}" 2>/dev/null)  # reload: fresh shell (Check 41)
[ -f "$HOME/.claude/CLAUDE.md" ] && cp "$HOME/.claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md.bak"  # timeout: 5000
cp "$PLUGIN_ROOT/CLAUDE.src.md" "$HOME/.claude/CLAUDE.md"  # timeout: 5000
printf "  wrote: CLAUDE.src.md → ~/.claude/CLAUDE.md\n"
```

## Step 12: Final report

Print summary:

- Python: `<PYTHON_CMD>` (shim installed at ~/.local/bin/python / already on PATH / n/a)
- statusLine: set / skipped
- permissions.allow: N entries added
- enabledPlugins: set / skipped
- advisorModel: set / skipped
- Rules removed obsolete: N (files no longer in current plugin version)
- Skills removed obsolete: N (skill dirs no longer in current plugin version)
- Agent symlinks removed from ~/.claude/agents/: N (stale foundry-managed symlinks purged)
- Rules linked: N → ~/.claude/rules/
- TEAM_PROTOCOL.md linked → ~/.claude/TEAM_PROTOCOL.md
- Skills linked: N → ~/.claude/skills/
- CLAUDE.md written → ~/.claude/CLAUDE.md
- Backup at: ~/.claude/settings.json.bak

</workflow>

<notes>

**Follow-up gate omitted** — setup is one-shot; no iterative follow-up action applies. Step 12 Final report is terminal output; no `AskUserQuestion` gate required.

**Testing setup changes**: Setup skill has no `.claude/skills/setup` entry — only reachable as `/foundry:setup` after plugin installed. To test: bump `version` in `plugins/cc_foundry/.claude-plugin/plugin.json`, run `claude plugin install foundry@borda-ai-rig` from repo root to refresh cache, invoke `/foundry:setup`. **Upgrade path**: After `claude plugin install foundry@borda-ai-rig` upgrades version, re-run `/foundry:setup` — Step 10 Phase 1 removes rules and skill symlinks no longer in new version; Phase 2–4 auto-replaces stale foundry symlinks (rules + skills) without prompting; real-file and non-foundry-path conflicts still surfaced for user review. Note: `bash sync.sh` calls `/foundry:setup` headlessly at end — skill symlinks updated automatically on every sync run.

</notes>
