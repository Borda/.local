#!/usr/bin/env bash
# setup_release_dir.sh RELEASE_DIR CHANGELOG_FILE
# Create release directory, symlink the canonical changelog into it, and back
# up any pre-existing release artifacts before overwrite.
# Extracted from oss:release prepare Phase 3 setup block (P2).
#
# Re-running prepare for the same version is legitimate (post-audit-fix retry);
# silently overwriting hand-edited notes is destructive, hence the backups.
# CHANGELOG.md is excluded from the backup loop — it is a symlink; re-linking
# on re-run is safe and intentional.
set -euo pipefail

RELEASE_DIR="${1:?release_dir required}"
CHANGELOG_FILE="${2:?changelog_file required}"

timeout 5 mkdir -p "$RELEASE_DIR"

# Symlink canonical changelog — no duplication, single source of truth.
ln -sf "$(realpath "$CHANGELOG_FILE")" "$RELEASE_DIR/CHANGELOG.md"

for f in HIGHLIGHTS.md DRAFT.md SUMMARY.md MIGRATION.md demo.py; do
    if [ -f "$RELEASE_DIR/$f" ]; then
        cp "$RELEASE_DIR/$f" "$RELEASE_DIR/$f.bak"
        echo "⚠ $RELEASE_DIR/$f exists — backed up to $f.bak before overwrite"
    fi
done
