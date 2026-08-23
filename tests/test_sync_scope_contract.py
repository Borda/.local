"""Contract checks for root sync host scoping and shared lifecycle flags."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT / "sync.sh"


def test_codex_scope_receives_the_global_no_clean_override() -> None:
    """Keep claude and codex arguments limited to host selection."""
    text = SYNC_SCRIPT.read_text(encoding="utf-8")
    codex_block = text.split("if $SYNC_CODEX; then", maxsplit=1)[1].split("fi  # SYNC_CODEX", maxsplit=1)[0]

    assert "if ! $CLEAN; then" in codex_block
    assert "CODEX_SYNC_ARGS+=(--no-clean)" in codex_block
