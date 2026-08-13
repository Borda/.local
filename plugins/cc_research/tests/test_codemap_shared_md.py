"""Regression tests for the codemap prose/bash shared by research skills and the scientist agent.

Pinned failure modes:

* E-M4 — research's gates were an unversioned inline copy: no contract resolution block, no
  ``cat`` of the shipped contract, no version marker, so the provider could move to v3 with
  research silently frozen at its transcribed v2 text.
* E-M5 — the wrappers named a build command their own loaded contract does not use, inside
  the same sentence that says "apply verbatim". Resolved by E-N7 from the contract side.
* E-N7 — the shipped contract now names the gated ``codemap-py index`` launcher itself, so
  the wrapper's "apply verbatim, with one override" clause announced a deviation from text it
  already agrees with, and kept the retired alias alive in a wrapper that never invokes it.
* E-M7 — ``PROJ=$(basename "$(git rev-parse ...)") || PROJ=$(basename "$PWD")`` never fired its
  fallback: ``basename ""`` exits 0, so in a non-git project PROJ was empty and codemap was
  silently off.
* E-H1 — ``_IDX`` defaulted to a CWD-relative ``.cache/codemap``.
* E-L2 — the retired ``codemap:`` skill prefix.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RESEARCH = _REPO_ROOT / "plugins" / "cc_research"
_GATES = _RESEARCH / "skills" / "_shared" / "codemap-gates.md"
_CONTEXT = _RESEARCH / "skills" / "_shared" / "codemap-context.md"
_SCIENTIST = _RESEARCH / "agents" / "scientist.md"

_BASH_BLOCK_FILES = [_CONTEXT, _SCIENTIST]


def _bash_blocks(path: Path) -> list[str]:
    """Return the bodies of every ```bash fenced block in *path*."""
    return re.findall(r"```bash\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL)


# --------------------------------------------------------------------------------------
# E-M4 / E-M5 — versioned wrapper over the shipped contract
# --------------------------------------------------------------------------------------


def test_gates_resolve_and_read_the_shipped_contract():
    """E-M4: an inline transcription cannot follow the provider; the wrapper must cat the contract."""
    text = _GATES.read_text(encoding="utf-8")

    assert "claude-skills/_shared" in text, "no installed-cache resolution block"
    assert 'cat "$_CM_SHARED/codemap-gates.md"' in text, "contract is never loaded"
    assert re.search(r"Contract \(`v\d+`\)", text), "no contract version marker"
    assert "Fallback when codemap-py plugin absent" in text, "no graceful degradation"


def test_gates_do_not_transcribe_the_contract_body():
    """E-M4: re-listing the gate options inline is exactly the drift the wrapper removes."""
    text = _GATES.read_text(encoding="utf-8")

    assert "No codemap index for this project" not in text
    assert "Continue with stale data" not in text


def test_build_command_is_applied_from_the_contract_without_an_override():
    """E-N7: the contract now names the gated dispatcher, so the override may not be claimed.

    Inverted from E-M5: that finding required the override to be *stated* (and the alias named,
    or the reader could not apply it) because the contract genuinely said something else. With
    the contract aligned, "with one override" describes a disagreement that no longer exists —
    so agreement is what gets pinned, and the retired alias must not survive in the wrapper.
    """
    text = _GATES.read_text(encoding="utf-8")

    assert "codemap-py index" in text
    assert "apply verbatim, with one override" not in text, "the contract no longer disagrees"
    assert "scan-index" not in text, "the retired alias has no reason to appear in a wrapper"


def test_no_retired_codemap_skill_prefix():
    """E-L2: the plugin is `codemap-py:`; the bare `codemap:<skill>` prefix is retired.

    The skill name must follow the colon immediately, so a prose colon is not flagged.
    """
    for path in (_GATES, _CONTEXT, _SCIENTIST):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<![\w-])codemap:[a-z]", text), f"retired `codemap:<skill>` prefix in {path.name}"


# --------------------------------------------------------------------------------------
# E-H1 — root-anchored index directory
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", _BASH_BLOCK_FILES, ids=lambda p: p.name)
def test_index_dir_is_root_anchored(path: Path):
    """E-H1: a CWD-relative default reports no_index whenever the session sits in a subdir."""
    blocks = [b for b in _bash_blocks(path) if "_IDX=" in b]
    assert blocks, f"no _IDX block found in {path.name}"
    for block in blocks:
        assert "${CODEMAP_INDEX_DIR:-.cache/codemap}" not in block, "CWD-relative default"
        assert "${CODEMAP_INDEX_DIR:-$_ROOT/.cache/codemap}" in block


# --------------------------------------------------------------------------------------
# E-M7 — the project-name fallback actually fires
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", _BASH_BLOCK_FILES, ids=lambda p: p.name)
def test_project_name_fallback_fires_outside_a_git_repository(path: Path, tmp_path: Path, posix_bash: str):
    """E-M7: `basename ""` exits 0, so the old `||` fallback was unreachable and PROJ went empty."""
    block = next(b for b in _bash_blocks(path) if "_ROOT=" in b)
    snippet = "\n".join(
        line for line in block.splitlines() if line.strip().startswith(("_ROOT=", '[ -n "$_ROOT"', "PROJ="))
    )
    assert snippet.strip(), f"no root/PROJ derivation found in {path.name}"

    workdir = tmp_path / "loose project"
    workdir.mkdir()
    result = subprocess.run(
        [posix_bash, "-c", f'{snippet}\nprintf "%s" "$PROJ"'],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # A stray parent repo would mask the non-git path this test exists to exercise. The
        # ceiling is what does that; the environment is otherwise inherited, because replacing
        # it with a POSIX PATH literal also dropped SystemRoot, COMSPEC and the rest of the
        # set a Windows child needs before it can start at all.
        env=os.environ | {"GIT_CEILING_DIRECTORIES": str(tmp_path)},
        check=True,
    )

    assert result.stdout == "loose project", f"{path.name}: PROJ was {result.stdout!r}"
