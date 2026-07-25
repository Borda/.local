"""Contract test: record-exhausted.js writes the sentinel for REAL emitted commands.

The PostToolUse hook (`record-exhausted.js`) must recognise every command shape that
codemap skills actually emit — otherwise the exhausted-sentinel is never written and
`guard-redundant-scan.js` never fires, leaving the documented grep-loop worst case
unguarded. The command strings below are copied from the live SKILL.md / codemap-context
blocks that produce them:

- ``scan-query rdeps "mypackage.auth"``                       — query-code/SKILL.md
- ``scan-query fn-rdeps "mypackage.auth::validate_token"``    — query-code/SKILL.md
- ``$SQ rdeps "mypackage.auth"``                              — query-code missing-binary fallback
- ``scan-query --timeout 5 fn-rdeps "...::..." --exclude-tests`` — develop codemap-context.md

This converts the hook↔skill contract from silent breakage to a CI-caught failure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HOOK = Path(__file__).parent.parent.parent / "hooks" / "record-exhausted.js"

# scan-query embeds the coverage block under `index`. It emits the forward `query_complete`
# field and the legacy `exhaustive` alias byte-compatibly during the deprecation cycle.
_EXHAUSTIVE_RESPONSE = json.dumps(
    {"imported_by": ["pkg.a", "pkg.b"], "index": {"query_complete": True, "exhaustive": True, "stale": False}}
)
_NONEXHAUSTIVE_RESPONSE = json.dumps(
    {"imported_by": ["pkg.a"], "index": {"query_complete": False, "exhaustive": False, "stale": False}}
)
# Forward-only response: a future index that has dropped the legacy `exhaustive` alias must
# still arm the sentinel via `query_complete` alone.
_QUERY_COMPLETE_ONLY_RESPONSE = json.dumps(
    {"imported_by": ["pkg.a", "pkg.b"], "index": {"query_complete": True, "stale": False}}
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


def _run(command: str, response: str, session: str, tmp_path: Path) -> None:
    """Feed one PostToolUse(Bash) event through the hook with TMPDIR isolated to tmp_path."""
    payload = {"tool_input": {"command": command}, "tool_response": response, "session_id": session}
    # Node's os.tmpdir() uses TMPDIR on POSIX and TEMP/TMP on Windows.
    env = {**os.environ, "TMPDIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path)}
    result = subprocess.run(
        ["node", str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("command", "session"),
    [
        ('scan-query rdeps "mypackage.auth"', "sess-rdeps-quoted"),
        ("scan-query rdeps mypackage.auth", "sess-rdeps-bare"),
        ('scan-query fn-rdeps "mypackage.auth::validate_token"', "sess-fnrdeps"),
        ('$SQ rdeps "mypackage.auth"', "sess-sq-fallback"),
        ('scan-query --timeout 5 fn-rdeps "mypackage.auth::validate_token" --exclude-tests', "sess-interposed"),
    ],
)
def test_sentinel_written_for_real_commands(command: str, session: str, tmp_path: Path) -> None:
    """Every real emitted rdeps/fn-rdeps form must write the module to the sentinel."""
    _run(command, _EXHAUSTIVE_RESPONSE, session, tmp_path)

    sentinel = tmp_path / f"codemap-exhausted-{session}"
    assert sentinel.exists(), f"sentinel not written for command: {command}"
    lines = sentinel.read_text().split()
    # fn-rdeps records the module portion (before `::`), not the function.
    assert "mypackage.auth" in lines
    assert "mypackage/auth" in lines


def test_non_exhaustive_writes_no_sentinel(tmp_path: Path) -> None:
    """A non-exhaustive result must NOT arm the guard."""
    _run('scan-query rdeps "mypackage.auth"', _NONEXHAUSTIVE_RESPONSE, "sess-nonexh", tmp_path)
    assert not (tmp_path / "codemap-exhausted-sess-nonexh").exists()


def test_query_complete_alone_arms_sentinel(tmp_path: Path) -> None:
    """A forward-only result (query_complete, no legacy exhaustive) still arms the guard."""
    _run('scan-query rdeps "mypackage.auth"', _QUERY_COMPLETE_ONLY_RESPONSE, "sess-qc-only", tmp_path)

    sentinel = tmp_path / "codemap-exhausted-sess-qc-only"
    assert sentinel.exists(), "query_complete:true alone must write the sentinel"
    assert "mypackage.auth" in sentinel.read_text().split()


def test_unrelated_command_ignored(tmp_path: Path) -> None:
    """A command that is not a scan-query rdeps/fn-rdeps must be ignored."""
    _run('grep -r "import mypackage.auth" .', _EXHAUSTIVE_RESPONSE, "sess-grep", tmp_path)
    assert not (tmp_path / "codemap-exhausted-sess-grep").exists()


def test_codemap_hooks_read_stdin_by_fd_for_windows() -> None:
    """Codemap hooks must not use POSIX-only /dev/stdin."""
    hooks_dir = _HOOK.parent
    offenders = [
        path.name for path in sorted(hooks_dir.glob("*.js")) if "/dev/stdin" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
