"""Contract tests for the codemap JS hooks driven via stdin JSON subprocess.

Each hook is exercised exactly the way Claude Code drives it: a single event JSON is
piped to `node <hook>` on stdin, and the observable side effects (stdout shape, tmp
files written, spawn markers, exit code) are asserted. No production code is touched —
a suspected production bug is pinned with an ``xfail(strict=True)`` test plus a note in
the return envelope, never a fix.

Hooks under test:

- ``inject-preamble.js``       — UserPromptSubmit: index-status preamble, stale-index
                                  background refresh with an atomic O_EXCL lock, and
                                  a once-per-session emit flag. Both the lock and the
                                  session flag use ``readTimestamp`` which must map a
                                  corrupted (non-numeric/empty) file to a *stale* age
                                  rather than a NaN that poisons every comparison.
- ``guard-redundant-scan.js``  — PreToolUse(Bash): deny import-discovery greps for a
                                  module already marked exhaustive this session.
- ``seed-session.js``          — SessionStart: seed the per-project session tmpfile.
- ``log-skill-start.js``       — PreToolUse(Skill): log codemap:* skill invocations.

TEST SEAM (inject-preamble): the hook keys its lock/flag tmp files on the git-root
basename, resolves the index dir from ``CODEMAP_INDEX_DIR``, and resolves the
``scan-index`` binary from ``CLAUDE_PLUGIN_ROOT/bin/scan-index``. Every test therefore
builds a throwaway git repo (staleness is git-blob based), points ``CODEMAP_INDEX_DIR``
at a controlled index, and points ``CLAUDE_PLUGIN_ROOT`` at a fake plugin root whose
``bin/scan-index`` writes a marker file — so a background spawn is observable without a
real scan.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

_HOOKS = Path(__file__).parent.parent / "hooks"
_INJECT = _HOOKS / "inject-preamble.js"
_GUARD = _HOOKS / "guard-redundant-scan.js"
_SEED = _HOOKS / "seed-session.js"
_SKILL = _HOOKS / "log-skill-start.js"

# These must mirror the constants baked into inject-preamble.js.
_LOCK_TTL_MS = 10 * 60 * 1000  # LOCK_TTL_MS
_SESSION_TTL_MS = 30 * 60 * 1000  # SESSION_TTL_MS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


# ── helpers ──────────────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> None:
    """Run a git command inside *root*, asserting success."""
    result = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _init_repo(root: Path) -> str:
    """Init a git repo with one committed .py file; return the HEAD sha."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("def f():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True)
    return head.stdout.strip()


def _write_index(idx_dir: Path, proj: str, *, git_sha: str, modules: int = 2) -> Path:
    """Write a minimal codemap index header the preamble hook can peek at."""
    idx_dir.mkdir(parents=True, exist_ok=True)
    file_shas = {f"m{i}": "deadbeef" for i in range(modules)}
    payload = {
        "git_sha": git_sha,
        "scanned_at": "2026-06-20T00:00:00Z",
        "scan_root": str(idx_dir.parent),
        "file_shas": file_shas,
    }
    idx_path = idx_dir / f"{proj}.json"
    idx_path.write_text(json.dumps(payload))
    return idx_path


def _fake_plugin_root(root: Path, *, with_scan_bin: bool, marker: Path) -> Path:
    """Create a fake CLAUDE_PLUGIN_ROOT.

    When *with_scan_bin* is True, ``bin/scan-index`` is an executable shell stub that
    touches *marker* on spawn — the observable proof the hook launched a refresh.
    """
    plugin_root = root / "plugin"
    bin_dir = plugin_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if with_scan_bin:
        scan_bin = bin_dir / "scan-index"
        scan_bin.write_text(f'#!/bin/sh\necho spawned > "{marker}"\n')
        scan_bin.chmod(scan_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return plugin_root


def _run_inject(
    repo: Path,
    idx_dir: Path,
    plugin_root: Path,
    tmpdir: Path,
    *,
    prompt: str = "hello",
) -> subprocess.CompletedProcess:
    """Drive inject-preamble.js with all three seams pinned to controlled dirs."""
    env = {
        **os.environ,
        "CODEMAP_INDEX_DIR": str(idx_dir),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "TMPDIR": str(tmpdir),
        "TEMP": str(tmpdir),
        "TMP": str(tmpdir),
    }
    return subprocess.run(
        ["node", str(_INJECT)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env=env,
    )


def _lock_file(tmpdir: Path, proj: str) -> Path:
    return tmpdir / f"codemap-refresh-{proj}"


def _session_flag(tmpdir: Path, proj: str) -> Path:
    return tmpdir / f"codemap-preamble-{proj}"


# ── inject-preamble: staleness detection + preamble emit ─────────────────────────


class TestInjectPreambleCurrency:
    """Currency classification and the once-per-session emit gate."""

    def test_current_index_emits_preamble_once(self, tmp_path: Path) -> None:
        """A current index (sha matches HEAD, clean tree) emits the preamble line."""
        repo = tmp_path / "proj"
        head = _init_repo(repo)
        idx_dir = tmp_path / "idx"
        _write_index(idx_dir, repo.name, git_sha=head)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "[codemap]" in result.stdout
        assert "current" in result.stdout
        assert "2 modules" in result.stdout
        # current index never spawns a refresh
        assert not marker.exists()

    def test_session_flag_fresh_suppresses_second_emit(self, tmp_path: Path) -> None:
        """A valid session flag younger than SESSION_TTL_MS makes a current index exit silent."""
        repo = tmp_path / "proj"
        head = _init_repo(repo)
        idx_dir = tmp_path / "idx"
        _write_index(idx_dir, repo.name, git_sha=head)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        # Pre-seed a fresh, valid flag.
        _session_flag(tmpdir, repo.name).write_text(str(int(time.time() * 1000)))

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_corrupted_session_flag_still_emits_once(self, tmp_path: Path) -> None:
        """SESSION FLAG NaN: a corrupted flag must NOT early-exit — it falls through and re-emits.

        Pins the readTimestamp NaN guard: ``Date.now() - NaN`` is NaN, and the hook must
        treat that as "no valid flag" (emit) rather than silently exiting 0.
        """
        repo = tmp_path / "proj"
        head = _init_repo(repo)
        idx_dir = tmp_path / "idx"
        _write_index(idx_dir, repo.name, git_sha=head)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        # Corrupted (non-numeric) flag — must be treated as stale/absent.
        flag = _session_flag(tmpdir, repo.name)
        flag.write_text("not-a-number")

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "[codemap]" in result.stdout
        # Flag was rewritten to a valid numeric timestamp.
        assert int(flag.read_text().strip()) > 0

    def test_fail_open_on_non_git_no_index(self, tmp_path: Path) -> None:
        """FAIL-OPEN: a non-git dir with no index and no Python markers exits 0, silent, no throw."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "notes.txt").write_text("hi")  # non-Python, no index
        idx_dir = tmp_path / "idx-empty"  # never created
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_inject(plain, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert not marker.exists()


# ── inject-preamble: stale-index background refresh + lock lifecycle ──────────────


class TestInjectPreambleRefreshLock:
    """The O_EXCL lock lifecycle around the stale-index background scan spawn."""

    def _stale_repo(self, tmp_path: Path) -> tuple[Path, Path, str]:
        """Build a repo whose committed HEAD differs from the indexed sha (→ stale)."""
        repo = tmp_path / "proj"
        _init_repo(repo)
        idx_dir = tmp_path / "idx"
        # Index carries a bogus sha so currency resolves to "stale".
        _write_index(idx_dir, repo.name, git_sha="0" * 40)
        return repo, idx_dir, repo.name

    def test_stale_index_spawns_refresh_and_writes_lock(self, tmp_path: Path) -> None:
        """STALE → exactly one scan-index spawn; lockfile written; note says 'refresh started'."""
        repo, idx_dir, proj = self._stale_repo(tmp_path)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "stale" in result.stdout
        assert "refresh started" in result.stdout
        # Detached child may lag; poll briefly for the spawn marker.
        for _ in range(50):
            if marker.exists():
                break
            time.sleep(0.02)
        assert marker.exists(), "scan-index was not spawned for a stale index"
        assert _lock_file(tmpdir, proj).exists(), "lock file not written on spawn"

    def test_fresh_lock_blocks_second_spawn(self, tmp_path: Path) -> None:
        """LOCK CONTENTION: a fresh valid lock (age < TTL) suppresses the spawn.

        Note reads ' · refresh in progress' and no second scan-index is launched.
        """
        repo, idx_dir, proj = self._stale_repo(tmp_path)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        # Pre-seed a fresh lock so acquisition hits EEXIST + fresh → no takeover.
        _lock_file(tmpdir, proj).write_text(str(int(time.time() * 1000)))

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "refresh in progress" in result.stdout
        time.sleep(0.15)
        assert not marker.exists(), "a held fresh lock must suppress the spawn"

    def test_stale_lock_taken_over_single_spawn(self, tmp_path: Path) -> None:
        """STALE-LOCK TAKEOVER: a lock older than LOCK_TTL_MS is unlinked+recreated, one spawn."""
        repo, idx_dir, proj = self._stale_repo(tmp_path)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        # Lock timestamp well older than the TTL → taken over.
        stale_ts = int(time.time() * 1000) - (_LOCK_TTL_MS + 60_000)
        _lock_file(tmpdir, proj).write_text(str(stale_ts))

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "refresh started" in result.stdout
        for _ in range(50):
            if marker.exists():
                break
            time.sleep(0.02)
        assert marker.exists(), "a stale lock must be taken over and the scan spawned"

    def test_corrupted_lock_treated_as_stale(self, tmp_path: Path) -> None:
        """CORRUPTED LOCK: a non-numeric lock is NaN-aged → treated as stale, taken over, one spawn.

        Guards against ``Date.now() - NaN`` being read as "fresh" (which would wrongly
        suppress the takeover and leave the index stale forever).
        """
        repo, idx_dir, proj = self._stale_repo(tmp_path)
        marker = tmp_path / "spawned.marker"
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=True, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        _lock_file(tmpdir, proj).write_text("")  # empty → parseInt → NaN

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert "refresh started" in result.stdout
        for _ in range(50):
            if marker.exists():
                break
            time.sleep(0.02)
        assert marker.exists(), "a corrupted lock must be treated as stale and taken over"

    def test_missing_scan_bin_releases_lock_no_spawn(self, tmp_path: Path) -> None:
        """NO-SCANBIN LOCK RELEASE: no scan-index present → lock unlinked, no spawn (later retry)."""
        repo, idx_dir, proj = self._stale_repo(tmp_path)
        marker = tmp_path / "spawned.marker"
        # Fake plugin root WITHOUT a scan-index bin.
        plugin_root = _fake_plugin_root(tmp_path, with_scan_bin=False, marker=marker)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_inject(repo, idx_dir, plugin_root, tmpdir)

        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        # The lock the hook briefly acquired must be released so a later hook can retry.
        assert not _lock_file(tmpdir, proj).exists(), "lock must be released when scan bin absent"


# ── guard-redundant-scan ─────────────────────────────────────────────────────────


def _run_guard(command: str, session: str, tmpdir: Path) -> subprocess.CompletedProcess:
    """Drive guard-redundant-scan.js with an isolated TMPDIR for the sentinel lookup."""
    env = {**os.environ, "TMPDIR": str(tmpdir), "TEMP": str(tmpdir), "TMP": str(tmpdir)}
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session}
    return subprocess.run(
        ["node", str(_GUARD)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )


def _seed_sentinel(tmpdir: Path, session: str, modules: list[str]) -> None:
    """Write the exhausted-caller sentinel the guard reads (one module per line)."""
    (tmpdir / f"codemap-exhausted-{session}").write_text("\n".join(modules) + "\n")


class TestGuardRedundantScan:
    """Import-discovery grep denial keyed on the per-session exhausted sentinel."""

    @pytest.mark.parametrize(
        ("command", "form"),
        [
            pytest.param('grep -rn "import mypackage.auth" .', "dotted", id="dotted-import"),
            pytest.param('grep -rn "from mypackage/auth" src/', "slashed", id="slashed-from"),
            pytest.param('rg "import mypackage.auth"', "dotted", id="rg-dotted"),
        ],
    )
    def test_exhausted_module_grep_denied(self, command: str, form: str, tmp_path: Path) -> None:
        """A grep naming an exhausted module (dotted or slashed) is denied with a deny decision."""
        session = f"sess-{form}"
        # Sentinel carries both forms, as record-exhausted.js writes them.
        _seed_sentinel(tmp_path, session, ["mypackage.auth", "mypackage/auth"])

        result = _run_guard(command, session, tmp_path)

        assert result.returncode == 0, result.stderr
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "mypackage.auth" in decision["permissionDecisionReason"]

    @pytest.mark.parametrize(
        "command",
        [
            pytest.param('grep -rn "import mypackage.auth2" .', id="near-miss-suffix"),
            pytest.param('grep -rn "import notmypackage.auth" .', id="near-miss-prefix"),
        ],
    )
    def test_near_miss_module_not_denied(self, command: str, tmp_path: Path) -> None:
        """A near-miss module (name contains an exhausted module as a substring) must not be denied.

        The guard uses a word-boundary matcher (guard-redundant-scan.js matchesModule), so a
        grep for ``mypackage.auth2`` or ``notmypackage.auth`` — whose names merely *contain*
        the exhausted ``mypackage.auth`` — stays allowed rather than being falsely blocked.
        """
        session = "sess-nearmiss"
        _seed_sentinel(tmp_path, session, ["mypackage.auth", "mypackage/auth"])

        result = _run_guard(command, session, tmp_path)

        assert result.returncode == 0, result.stderr
        assert result.stdout == "", f"near-miss must not be denied: {command}"

    def test_no_sentinel_allows(self, tmp_path: Path) -> None:
        """No sentinel for the session → nothing marked exhaustive → allow."""
        result = _run_guard('grep -rn "import mypackage.auth" .', "sess-none", tmp_path)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_non_grep_command_untouched(self, tmp_path: Path) -> None:
        """A non-import-discovery command is never inspected, even with a live sentinel."""
        session = "sess-passthru"
        _seed_sentinel(tmp_path, session, ["mypackage.auth"])

        result = _run_guard("ls mypackage.auth", session, tmp_path)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_garbage_stdin_fails_open(self, tmp_path: Path) -> None:
        """Non-JSON stdin must fail open (exit 0, no deny)."""
        result = subprocess.run(
            ["node", str(_GUARD)],
            input="not json at all",
            text=True,
            capture_output=True,
            env={**os.environ, "TMPDIR": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


# ── seed-session ─────────────────────────────────────────────────────────────────


def _run_seed(payload: dict, cwd: Path, tmpdir: Path) -> subprocess.CompletedProcess:
    """Drive seed-session.js with cwd + TMPDIR pinned so the session tmpfile is observable."""
    env = {**os.environ, "TMPDIR": str(tmpdir), "TEMP": str(tmpdir), "TMP": str(tmpdir)}
    return subprocess.run(
        ["node", str(_SEED)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


class TestSeedSession:
    """SessionStart seeding of the per-project session tmpfile."""

    def test_writes_session_id_to_project_tmpfile(self, tmp_path: Path) -> None:
        """A non-empty session_id is written to codemap-<project>-session in TMPDIR."""
        repo = tmp_path / "proj"
        _init_repo(repo)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_seed({"session_id": "sid-xyz"}, repo, tmpdir)

        assert result.returncode == 0, result.stderr
        # Project name is the git-root basename.
        sidfile = tmpdir / f"codemap-{repo.name}-session"
        assert sidfile.exists()
        assert sidfile.read_text() == "sid-xyz"

    def test_empty_session_id_writes_nothing(self, tmp_path: Path) -> None:
        """An empty session_id is a no-op — no tmpfile written."""
        repo = tmp_path / "proj"
        _init_repo(repo)
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()

        result = _run_seed({"session_id": ""}, repo, tmpdir)

        assert result.returncode == 0, result.stderr
        assert not (tmpdir / f"codemap-{repo.name}-session").exists()

    def test_garbage_stdin_fails_open(self, tmp_path: Path) -> None:
        """Non-JSON stdin must fail open (exit 0), writing nothing."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        result = subprocess.run(
            ["node", str(_SEED)],
            input="}{ not json",
            text=True,
            capture_output=True,
            cwd=str(tmp_path),
            env={**os.environ, "TMPDIR": str(tmpdir)},
        )
        assert result.returncode == 0, result.stderr


# ── log-skill-start ──────────────────────────────────────────────────────────────


def _run_skill(payload: dict, cwd: Path, tmpdir: Path) -> subprocess.CompletedProcess:
    """Drive log-skill-start.js with cwd + TMPDIR pinned."""
    env = {**os.environ, "TMPDIR": str(tmpdir), "TEMP": str(tmpdir), "TMP": str(tmpdir)}
    return subprocess.run(
        ["node", str(_SKILL)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


def _skill_records(cwd: Path) -> list[dict]:
    """Return all records across every skills*.jsonl shard under the cwd log dir."""
    log_dir = cwd / ".cache" / "codemap" / "logs"
    records: list[dict] = []
    for shard in sorted(log_dir.glob("skills*.jsonl")):
        records += [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    return records


class TestLogSkillStart:
    """PreToolUse(Skill) logging of codemap:* skill invocations."""

    def test_codemap_skill_logged(self, tmp_path: Path) -> None:
        """A codemap:* Skill call appends one start record carrying skill + intent."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        payload = {
            "tool_name": "Skill",
            "tool_input": {"skill": "codemap:query-code", "args": "who calls foo"},
            "session_id": "hook-sid",
        }

        result = _run_skill(payload, tmp_path, tmpdir)

        assert result.returncode == 0, result.stderr
        records = _skill_records(tmp_path)
        assert len(records) == 1
        assert records[0]["skill"] == "codemap:query-code"
        assert records[0]["event"] == "start"
        assert records[0]["intent"] == "who calls foo"
        assert records[0]["layer"] == "skill"

    def test_non_codemap_skill_ignored(self, tmp_path: Path) -> None:
        """A non-codemap skill is ignored — no record written."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        payload = {"tool_name": "Skill", "tool_input": {"skill": "foundry:audit"}}

        result = _run_skill(payload, tmp_path, tmpdir)

        assert result.returncode == 0, result.stderr
        assert _skill_records(tmp_path) == []

    def test_non_skill_tool_ignored(self, tmp_path: Path) -> None:
        """A non-Skill tool call is ignored — no record written."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}

        result = _run_skill(payload, tmp_path, tmpdir)

        assert result.returncode == 0, result.stderr
        assert _skill_records(tmp_path) == []

    def test_seeded_session_shard_join(self, tmp_path: Path) -> None:
        """A seeded session tmpfile routes the record to skills_<session>.jsonl."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        # project = cwd basename (log-skill-start uses cwd basename, not git root).
        (tmpdir / f"codemap-{tmp_path.name}-session").write_text("seeded-sid")
        payload = {"tool_name": "Skill", "tool_input": {"skill": "codemap:test-impact"}}

        result = _run_skill(payload, tmp_path, tmpdir)

        assert result.returncode == 0, result.stderr
        shard = tmp_path / ".cache" / "codemap" / "logs" / "skills_seeded-sid.jsonl"
        assert shard.exists(), "record not routed to the seeded per-session shard"
        assert json.loads(shard.read_text().strip())["session"] == "seeded-sid"

    def test_garbage_stdin_fails_open(self, tmp_path: Path) -> None:
        """Non-JSON stdin must fail open (exit 0), writing nothing."""
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        result = subprocess.run(
            ["node", str(_SKILL)],
            input="not-json",
            text=True,
            capture_output=True,
            cwd=str(tmp_path),
            env={**os.environ, "TMPDIR": str(tmpdir)},
        )
        assert result.returncode == 0, result.stderr
        assert _skill_records(tmp_path) == []
