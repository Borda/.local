"""codemap-py CLI gate wiring and doctor resolver (plan §4.4; review F1/F2).

Proves the shipped ``codemap-py index/query`` enters the RW gate (a live writer
lease forces ``query`` to return a bounded ``index_busy``) and that ``doctor``
reports the exact path from the single §4.4 resolver, including the
``CODEMAP_INDEX_DIR`` root-key layout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_BIN = _PLUGIN_ROOT / "bin"
_LAUNCHER = _BIN / ("codemap-py.cmd" if sys.platform == "win32" else "codemap-py")
_SCRIPTS = _PLUGIN_ROOT / "scripts"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _index_identity  # noqa: E402  (needs the bin/ path insert above)
import _rwgate  # noqa: E402  (needs the bin/ path insert above)
import codemap_py_cli as _cli  # noqa: E402  (needs the scripts/ path insert above)

# These tests exercise resolver equality and gate wiring THROUGH the launcher, so
# they need an eligible interpreter on the cell. The unsupported-interpreter
# rejection contract itself (exit 127, empty stdout) is asserted — never skipped —
# by test_interpreter.py on the same cell.
_RUNNING_SUPPORTED = _cli.is_supported(sys.implementation.name, sys.version_info.major, sys.version_info.minor)
pytestmark = pytest.mark.skipif(
    not _RUNNING_SUPPORTED,
    reason="CLI behavior needs a supported CPython; the 127 rejection contract is covered by test_interpreter.py",
)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Invoke the launcher, inheriting the (monkeypatched) environment."""
    return subprocess.run([str(_LAUNCHER), *args], capture_output=True, text=True, timeout=30, check=False)


@pytest.mark.parametrize("with_override", [pytest.param(False, id="default"), pytest.param(True, id="override")])
def test_doctor_index_path_matches_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_override: bool
) -> None:
    """doctor's index_path equals _index_identity.resolve_index() (incl. root-key)."""
    if with_override:
        monkeypatch.setenv("CODEMAP_INDEX_DIR", str(tmp_path))
    else:
        monkeypatch.delenv("CODEMAP_INDEX_DIR", raising=False)
    expected = str(_index_identity.resolve_index().index_path)

    result = _run_cli(["doctor", "--json"])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["index_path"] == expected


def test_doctor_override_uses_root_key_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under CODEMAP_INDEX_DIR the resolved path is nested in the root-key dir (F2)."""
    monkeypatch.setenv("CODEMAP_INDEX_DIR", str(tmp_path))
    identity = _index_identity.resolve_index()

    result = _run_cli(["doctor", "--json"])
    reported = Path(json.loads(result.stdout)["index_path"])
    assert reported.parent.name == identity.root_key
    assert reported.parent.parent == tmp_path.resolve()


def _hold_writer_intent(index_path: str, ready: Path, hold: float) -> None:
    """Acquire an exclusive writer lease and hold it past the reader's timeout."""

    def build(_target: Path) -> None:
        ready.write_text("live")
        time.sleep(hold)

    _rwgate.write_index(index_path, build, timeout=30.0)


def test_query_under_live_writer_returns_index_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live writer lease forces the shipped query into a bounded index_busy (F1)."""
    monkeypatch.setenv("CODEMAP_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("CODEMAP_GATE_TIMEOUT", "1")
    index_path = str(_index_identity.resolve_index().index_path)
    ready = tmp_path / "writer.ready"

    writer = threading.Thread(target=_hold_writer_intent, args=(index_path, ready, 3.0))
    writer.start()
    deadline = time.time() + 5
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert ready.exists(), "writer never acquired intent"

    result = _run_cli(["query", "central"])
    writer.join(10)

    assert result.returncode == 1, f"expected index_busy exit 1, got {result.returncode}: {result.stderr}"
    assert json.loads(result.stderr.strip().splitlines()[-1])["error"] == "index_busy"
