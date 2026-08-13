"""Regression tests for cc_develop's codemap prose and inline bash.

Pinned failure modes:

* E-H1 — every hand-copied index-guard block defaulted to a CWD-relative ``.cache/codemap``
  while the provider anchors on the git toplevel, so a skill invoked from a subdirectory
  reported a false ``no_index``. The sweep below is tree-wide on purpose: the guard is
  hand-copied (E-H2), so a per-file assertion would let the next copy drift in unnoticed.
* E-M5 — the gates wrapper named a build command its own loaded contract does not use,
  inside the sentence instructing the reader to apply that contract verbatim. Resolved by
  E-N7 from the contract side, so what is pinned below inverted — see there.
* E-N7 — the shipped contract now names the gated ``codemap-py index`` launcher itself, so
  the wrapper's "apply verbatim, with one override" clause described a disagreement that no
  longer exists. A wrapper claiming to override a contract it agrees with is as misleading as
  the E-M5 contradiction was: both leave the reader unable to tell which command wins.
* E-L2 — the retired ``codemap:`` skill prefix.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEVELOP = _REPO_ROOT / "plugins" / "cc_develop"
_GATES = _DEVELOP / "skills" / "_shared" / "codemap-gates.md"

# The CWD-relative default this finding removes; matched literally so a re-introduction fails.
_CWD_RELATIVE_DEFAULT = "${CODEMAP_INDEX_DIR:-.cache/codemap}"


def _load(path: Path, name: str) -> ModuleType:
    """Load *path* under a unique module name — both plugins ship a ``codemap_resolve``."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tracked_text_files(root: Path) -> list[Path]:
    """Return every markdown/python source file under *root*, excluding tests."""
    return [
        p
        for p in root.rglob("*")
        if p.suffix in {".md", ".py"} and p.is_file() and "tests" not in p.relative_to(root).parts
    ]


def test_no_cwd_relative_index_dir_anywhere_in_the_plugin():
    """E-H1: the index lives under the git toplevel; anchoring on the CWD is a false no_index."""
    offenders = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in _tracked_text_files(_DEVELOP)
        if _CWD_RELATIVE_DEFAULT in p.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"CWD-relative codemap index dir in: {offenders}"


def test_every_index_dir_override_is_root_anchored():
    """Each surviving `CODEMAP_INDEX_DIR:-` default must name the resolved repository root."""
    for path in _tracked_text_files(_DEVELOP):
        for default in re.findall(r"\$\{CODEMAP_INDEX_DIR:-([^}]*)\}", path.read_text(encoding="utf-8")):
            assert default.startswith("$_ROOT/"), f"{path.name}: unanchored default {default!r}"


def test_gates_resolve_and_read_the_shipped_contract():
    """The wrapper must load the shipped contract rather than transcribe it."""
    text = _GATES.read_text(encoding="utf-8")

    assert 'cat "$_CM_SHARED/codemap-gates.md"' in text
    assert re.search(r"Contract \(`v\d+`\)", text)
    assert "Fallback when codemap-py plugin absent" in text


def test_build_command_is_applied_from_the_contract_without_an_override():
    """E-N7: the contract now names the gated launcher, so no override may be claimed.

    This assertion is the inverse of the one E-M5 left here. E-M5 required the wrapper to
    *state* its override (contract said ``scan-index``, consumers ran ``codemap-py index``),
    and required the overridden alias to be named or the reader could not apply it. The
    contract was corrected, so the override became a fiction: it announces a deviation from
    text that already agrees, and re-introduces the retired alias into a wrapper that never
    invokes it. What is pinned now is agreement — the build command is named, the override
    language and the alias are gone.
    """
    text = _GATES.read_text(encoding="utf-8")

    assert "codemap-py index" in text
    assert "apply verbatim, with one override" not in text, "the contract no longer disagrees"
    assert "scan-index" not in text, "the retired alias has no reason to appear in a wrapper"


def test_gates_read_the_sentinel_the_resolver_writes():
    """A prefix mismatch would leave the stale gate permanently blind."""
    gate = _load(_DEVELOP / "bin" / "dev_codemap_gate.py", "dev_gate_sentinel_check")

    assert f"{gate.CURRENCY_PREFIX}-${{CSID}}" in _GATES.read_text(encoding="utf-8")


def test_no_retired_codemap_skill_prefix():
    """E-L2: the plugin is `codemap-py:`; the bare `codemap:<skill>` prefix is retired.

    The skill name must follow the colon immediately — a prose colon ("With codemap: effort
    sizing is structural") and the ``# codemap: integrated-via-shared`` marker are not
    plugin references and must not be flagged.
    """
    offenders = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in _tracked_text_files(_DEVELOP)
        if re.search(r"(?<![\w-])codemap:[a-z]", p.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"retired `codemap:<skill>` prefix in: {offenders}"
