"""Cross-runtime index identity, delegation reuse, and no-rebuild guarantees.

Proves the shared-index delegation contract (plan §4.4):

- one canonical resolver maps different working directories in the same repo, and
  either runtime, to the same index path/identity — runtime never in the path;
- after one build, resolving + reading the index from a subdir under runtime
  ``claude`` then ``codex`` triggers zero scanner invocations and preserves the
  index content hash and mtime (scanner-invocation counter oracle, not log text);
- ``CODEMAP_INDEX_DIR`` root-keys equal-basename projects to distinct reusable
  indexes; a symlink/case alias resolves to one identity;
- the legacy flat override is a read-only, root-matched compatibility candidate;
  a mismatch is ignored with an ``index_root_collision`` diagnostic;
- a stale index rebuilt through ``_rwgate`` rebuilds exactly once; the waiter reuses.

``_rwgate`` is imported for the gate-driven cases; those are guarded
with ``pytest.importorskip`` so the identity/reuse coverage stands alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import _index_identity as ii
import _runtime_log as rl

_BIN = Path(__file__).resolve().parents[1] / "bin"
SCAN_INDEX = _BIN / "scan-index"

# Scanner-invocation oracle: a thin shim that appends one line per real scan-index
# launch (via env CODEMAP_TEST_SCAN_COUNTER) then execs the real builder. Append is
# atomic for small writes, so a concurrent race cannot silently lose a count.
_SHIM_SOURCE = """\
import os
import subprocess
import sys

counter = os.environ.get("CODEMAP_TEST_SCAN_COUNTER")
if counter:
    with open(counter, "a", encoding="utf-8") as fh:
        fh.write("scan\\n")
scan_index = os.environ["CODEMAP_TEST_SCAN_INDEX"]
sys.exit(subprocess.run([sys.executable, scan_index, *sys.argv[1:]]).returncode)
"""

# Cross-process writer worker: two of these race through _rwgate.write_index on a
# stale index. The gate's writer-preferred linearisation (writer.json OS lock) must
# let exactly one build; the waiter's build_fn recheck then reuses the published
# index. Same-process threads cannot model this — writer intent is PID-owned.
_WORKER_SOURCE = """\
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.environ["CODEMAP_BIN"])
import _rwgate

target = sys.argv[1]


def build_fn(t):
    try:
        existing = json.loads(Path(t).read_bytes())
        if existing.get("scan_version") and existing.get("file_shas"):
            sys.stdout.write("reused")
            return "reused"
    except (OSError, ValueError):
        pass
    subprocess.run(
        [sys.executable, os.environ["CODEMAP_TEST_SHIM"], "--root", os.environ["CODEMAP_TEST_ROOT"]],
        check=True,
        capture_output=True,
    )
    sys.stdout.write("built")
    return "built"


try:
    _rwgate.write_index(target, build_fn, timeout=30)
except _rwgate.IndexBusy:
    sys.stdout.write("busy")
"""


def _git_init(root: Path) -> None:
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "-A"],
        ["commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def _count(counter: Path) -> int:
    try:
        return len(counter.read_text(encoding="utf-8").split())
    except OSError:
        return 0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def shim(tmp_path: Path) -> Path:
    p = tmp_path / "scan_shim.py"
    p.write_text(_SHIM_SOURCE, encoding="utf-8")
    return p


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    _git_init(root)
    return root


def _scan_env(counter: Path) -> dict:
    return {
        **os.environ,
        "CODEMAP_TEST_SCAN_COUNTER": str(counter),
        "CODEMAP_TEST_SCAN_INDEX": str(SCAN_INDEX),
    }


# ── identity resolution (no scanner) ──────────────────────────────────────────
def test_identity_same_path_from_repo_subdir(project: Path) -> None:
    ident = ii.resolve_index(root=project)
    sub = project / "a" / "b"
    sub.mkdir(parents=True)
    id_sub = ii.resolve_index(cwd=sub)
    assert id_sub.index_path == ident.index_path
    assert id_sub.root == ident.root
    assert id_sub.coordination_dir == ident.coordination_dir
    assert not ident.override


def test_override_root_keyed_layout(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    override = tmp_path / "shared"
    ident = ii.resolve_index(root=root, index_dir_override=str(override))
    assert ident.override
    assert ident.root_key == ii.root_key(ident.root)
    assert ident.index_path == override.resolve() / ident.root_key / "proj.json"
    assert ident.coordination_dir == override.resolve() / ident.root_key / ii.COORDINATION_DIRNAME


def test_equal_basename_distinct_root_keys_independent_reuse(tmp_path: Path) -> None:
    a = tmp_path / "a" / "proj"
    b = tmp_path / "b" / "proj"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    override = tmp_path / "shared"
    ia = ii.resolve_index(root=a, index_dir_override=str(override))
    ib = ii.resolve_index(root=b, index_dir_override=str(override))
    assert ia.project == ib.project == "proj"
    assert ia.root_key != ib.root_key
    assert ia.index_path != ib.index_path
    for ident, tok in ((ia, "A"), (ib, "B")):
        ident.index_dir.mkdir(parents=True, exist_ok=True)
        ident.index_path.write_text(json.dumps({"scan_root": str(ident.root), "tok": tok}), encoding="utf-8")
    assert json.loads(ia.index_path.read_text())["tok"] == "A"
    assert json.loads(ib.index_path.read_text())["tok"] == "B"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink alias identity")
def test_symlink_alias_same_identity(tmp_path: Path) -> None:
    real = tmp_path / "real_proj"
    real.mkdir()
    link = tmp_path / "link_proj"
    link.symlink_to(real, target_is_directory=True)
    id_real = ii.resolve_index(root=real)
    id_link = ii.resolve_index(root=link)
    assert id_real.index_path == id_link.index_path
    assert id_real.root_key == id_link.root_key


def test_legacy_flat_matching_root_is_readonly_candidate(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    override = tmp_path / "shared"
    override.mkdir()
    legacy = override / "proj.json"
    legacy.write_text(json.dumps({"scan_root": str(root.resolve())}), encoding="utf-8")
    ident = ii.resolve_index(root=root, index_dir_override=str(override))
    assert ident.legacy_candidate == legacy
    assert ident.diagnostics == ()
    # root-keyed target is distinct; legacy is never moved/overwritten.
    assert ident.index_path != legacy
    assert json.loads(legacy.read_text())["scan_root"] == str(root.resolve())


def test_legacy_flat_mismatch_emits_collision_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    override = tmp_path / "shared"
    override.mkdir()
    legacy = override / "proj.json"
    legacy.write_text(json.dumps({"scan_root": str(other.resolve())}), encoding="utf-8")
    ident = ii.resolve_index(root=root, index_dir_override=str(override))
    assert ident.legacy_candidate is None
    assert ii.INDEX_ROOT_COLLISION in [d.code for d in ident.diagnostics]
    # collision never blocks the usable root-keyed target, never touches the legacy file.
    assert ident.index_path.parent == override.resolve() / ident.root_key
    assert legacy.is_file()


def test_split_index_roots_diagnostic(tmp_path: Path) -> None:
    a = ii.resolve_index(root=tmp_path / "a")
    b = ii.resolve_index(root=tmp_path / "b")
    diag = ii.diagnose_split_index_roots(a.index_path, b.index_path)
    assert diag is not None and diag.code == ii.SPLIT_INDEX_ROOTS
    assert ii.diagnose_split_index_roots(a.index_path, a.index_path) is None


# ── build once, reuse across cwd + runtime, zero rebuild ──────────────────────
def test_reuse_across_cwd_and_runtime_no_rebuild(
    project: Path, shim: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rw = pytest.importorskip("_rwgate")
    monkeypatch.setenv("CODEMAP_LOGGING", "true")
    counter = tmp_path / "counter.txt"
    log_root = tmp_path / "logs"
    ident = ii.resolve_index(root=project)

    subprocess.run(
        [sys.executable, str(shim), "--root", str(ident.root)],
        cwd=str(project),
        env=_scan_env(counter),
        check=True,
        capture_output=True,
    )
    assert _count(counter) == 1
    assert ident.index_path.is_file()
    h0 = _sha(ident.index_path)
    m0 = ident.index_path.stat().st_mtime_ns

    sub = project / "pkg" / "deep"
    sub.mkdir(parents=True)
    id_sub = ii.resolve_index(cwd=sub)
    assert id_sub.index_path == ident.index_path

    # Delegated reuse: claude then codex read the same bytes through the gate; runtime
    # identity only routes the log, never the index path.
    for runtime in ("claude", "codex"):
        with rw.read_index(ident.index_path, timeout=5) as data:
            assert data["scan_root"] == str(ident.root)
            assert data["project"] == ident.project
        rl.write_log(runtime, {"event": "reused_index"}, session="deleg", root=project, override=str(log_root))

    assert _count(counter) == 1  # no rebuild on reuse
    assert _sha(ident.index_path) == h0
    assert ident.index_path.stat().st_mtime_ns == m0
    assert (log_root / "claude" / "cli_deleg.jsonl").is_file()
    assert (log_root / "codex" / "cli_deleg.jsonl").is_file()


# ── stale index: single effective rebuild under the gate, waiter reuses ────────
def test_stale_index_single_rebuild_waiter_reuses(project: Path, shim: Path, tmp_path: Path) -> None:
    pytest.importorskip("_rwgate")
    counter = tmp_path / "counter.txt"
    worker = tmp_path / "gate_worker.py"
    worker.write_text(_WORKER_SOURCE, encoding="utf-8")
    ident = ii.resolve_index(root=project)
    ident.index_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **_scan_env(counter),
        "CODEMAP_BIN": str(_BIN),
        "CODEMAP_TEST_SHIM": str(shim),
        "CODEMAP_TEST_ROOT": str(ident.root),
    }

    # Two separate processes race the stale index — the real delegation scenario
    # (Claude process vs Codex process), not two same-PID threads.
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker), str(ident.index_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=90) for p in procs]

    assert all(p.returncode == 0 for p in procs), outs
    labels = sorted(out.strip() for out, _err in outs)
    assert _count(counter) == 1
    assert labels == ["built", "reused"]
    published = json.loads(ident.index_path.read_bytes())
    assert published.get("scan_version") and published.get("file_shas")
