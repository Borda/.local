"""Frozen-grammar corpus tests for the codemap scan-index extractor.

These tests pin two properties of ``bin/scan-index`` against a small corpus of
Python source that straddles the CPython 3.11/3.12 grammar boundary
(``tests/corpus/``):

1. Determinism — scanning the same tree twice yields byte-identical index JSON
   once the two volatile top-level keys (``scanned_at``, ``git_sha``) are stripped.
   No ``datetime.now`` value or other run-to-run entropy leaks into the index body.
2. Grammar degradation tracks the running interpreter — a module whose syntax the
   running CPython cannot parse is recorded as ``status="degraded"`` and never
   silently dropped or partially indexed; a module the running CPython accepts is
   indexed normally. The corpus's post-3.11 modules therefore degrade on the 3.10
   and 3.11 matrix cells and index cleanly on 3.12+, which is where the multi-minor
   comparison actually happens.

The extractor is always invoked through ``sys.executable`` so the grammar it parses
with is exactly the interpreter running this test — that identity is what makes the
degradation correlation exact on every matrix cell.

Why not use ``ast.parse(feature_version=(3, 11))`` as the degradation oracle: on a
3.12+ host ``feature_version`` down-gates the PEG grammar (so PEP 695 type-parameter
syntax is rejected) but does NOT down-gate the tokenizer, so PEP 701 f-string quote
reuse still parses. It is a reliable oracle only for grammar-gated features, so it is
used below solely to assert — interpreter-independently — that the corpus contains
grammar-level post-3.11 syntax. The real per-file degradation oracle is the running
interpreter's own parse.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
_SCAN_INDEX = _TESTS_DIR.parent / "bin" / "scan-index"

# Top-level index keys that legitimately vary between two scans of identical source.
_VOLATILE_KEYS = ("scanned_at", "git_sha")

# Corpus modules whose syntax first became valid in CPython 3.12.
_POST_311_MODULES = ("pep695_type_params", "fstring_nesting_312")
_ACCEPTED_MODULE = "accepted_311"


def _corpus_files(corpus_dir: Path) -> list[Path]:
    """Return the corpus ``*.py`` modules, excluding the pytest ``conftest.py`` guard."""
    return sorted(p for p in corpus_dir.glob("*.py") if p.name != "conftest.py")


def _running_grammar_rejects(source: str) -> bool:
    """Return True when the running interpreter cannot parse *source*.

    Mirrors exactly what ``scan-index`` sees, because both this test and the
    extractor subprocess run under the same ``sys.executable``.
    """
    try:
        ast.parse(source)
    except SyntaxError:
        return True
    return False


def _make_corpus_tree(tmp_path: Path, corpus_dir: Path) -> Path:
    """Copy the corpus into a fresh, git-free source tree and return its path.

    The tree carries no ``.git`` so ``git_sha`` resolves identically (None) on every
    scan regardless of the host repository. A single tree is reused across the two
    scans of a determinism test so ``scan_root`` — a legitimately path-dependent
    field the spec keeps — is held constant.
    """
    src = tmp_path / "src"
    src.mkdir(parents=True)
    for f in _corpus_files(corpus_dir):
        shutil.copy2(f, src / f.name)
    return src


def _scan(src: Path, index_dir: Path) -> dict:
    """Run ``scan-index`` over *src*, writing into *index_dir*, and return the index dict."""
    import os

    index_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(_SCAN_INDEX), "--root", str(src)],
        env={**os.environ, "CODEMAP_INDEX_DIR": str(index_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"scan-index failed: {result.stderr}"
    written = list(index_dir.rglob("*.json"))
    assert len(written) == 1, f"expected exactly one index file, got {written}"
    return json.loads(written[0].read_text())


def _module_status(index: dict) -> dict:
    """Map module name -> status string from an index payload."""
    return {m["name"]: m.get("status") for m in index["modules"]}


def _strip_volatile(index: dict) -> dict:
    return {k: v for k, v in index.items() if k not in _VOLATILE_KEYS}


def _canonical(index: dict) -> str:
    return json.dumps(index, sort_keys=True, ensure_ascii=False)


def test_corpus_is_present_and_named(corpus_dir: Path) -> None:
    """The three frozen corpus modules must exist under their pinned names."""
    names = {p.stem for p in _corpus_files(corpus_dir)}
    assert _ACCEPTED_MODULE in names
    for mod in _POST_311_MODULES:
        assert mod in names, f"missing frozen corpus module: {mod}"


def test_corpus_contains_grammar_gated_post311_syntax(corpus_dir: Path) -> None:
    """Interpreter-independent frozen-grammar guarantee via ``feature_version``.

    PEP 695 type parameters are grammar-gated, so ``feature_version=(3, 11)``
    rejects them on every host interpreter — this asserts the corpus really does
    exercise post-3.11 grammar, without depending on which minor runs the test.
    The accepted baseline must conversely parse clean under the 3.11 grammar.
    """
    pep695 = (corpus_dir / "pep695_type_params.py").read_text()
    accepted = (corpus_dir / "accepted_311.py").read_text()
    with pytest.raises(SyntaxError):
        ast.parse(pep695, feature_version=(3, 11))
    ast.parse(accepted, feature_version=(3, 11))  # must not raise


def test_scan_index_is_deterministic(tmp_path: Path, corpus_dir: Path) -> None:
    """Two scans of identical source produce identical index JSON minus volatile keys."""
    src = _make_corpus_tree(tmp_path, corpus_dir)
    first = _scan(src, tmp_path / "idx_a")
    second = _scan(src, tmp_path / "idx_b")
    assert _canonical(_strip_volatile(first)) == _canonical(_strip_volatile(second))


def test_degraded_records_are_stable(tmp_path: Path, corpus_dir: Path) -> None:
    """The set of degraded module records is identical across two scans."""
    src = _make_corpus_tree(tmp_path, corpus_dir)
    first = _scan(src, tmp_path / "idx_a")
    second = _scan(src, tmp_path / "idx_b")
    degraded_first = sorted((m["name"], m.get("reason")) for m in first["modules"] if m.get("status") == "degraded")
    degraded_second = sorted((m["name"], m.get("reason")) for m in second["modules"] if m.get("status") == "degraded")
    assert degraded_first == degraded_second


def test_degradation_tracks_running_grammar(tmp_path: Path, corpus_dir: Path) -> None:
    """scan-index degrades a module iff the running interpreter cannot parse it.

    This is the exact correlation that holds on every matrix cell: the extractor
    and this test share ``sys.executable``, so their parse verdicts must agree.
    """
    index = _scan(_make_corpus_tree(tmp_path, corpus_dir), tmp_path / "idx")
    status = _module_status(index)
    for f in _corpus_files(corpus_dir):
        rejected = _running_grammar_rejects(f.read_text())
        expected = "degraded" if rejected else "ok"
        assert status.get(f.stem) == expected, (
            f"{f.name}: running-grammar rejected={rejected} but scan-index status={status.get(f.stem)!r}"
        )


def test_post311_modules_degrade_below_312(tmp_path: Path, corpus_dir: Path) -> None:
    """Version-conditioned expectation — the multi-minor teeth of the corpus.

    On 3.10 and 3.11 the two post-3.11 modules must be degraded; on 3.12+ they must
    index cleanly. The accepted baseline indexes on every supported minor.
    """
    index = _scan(_make_corpus_tree(tmp_path, corpus_dir), tmp_path / "idx")
    status = _module_status(index)
    assert status.get(_ACCEPTED_MODULE) == "ok"
    below_312 = sys.version_info < (3, 12)
    for mod in _POST_311_MODULES:
        if below_312:
            assert status.get(mod) == "degraded", f"{mod} should degrade on {sys.version_info[:2]}"
        else:
            assert status.get(mod) == "ok", f"{mod} should index on {sys.version_info[:2]}"
