"""Subprocess tests for ``hooks/batch-nudge.js``.

The hook tracks a streak of sequential *batchable* tool calls (Read/Grep/Glob,
read-only Bash prefixes) separated by gaps large enough to indicate a separate
model decision rather than a parallel dispatch from one message. At streak
``NUDGE_THRESHOLD`` it nudges via ``PostToolUse`` exit 2 (stderr feedback,
non-blocking — the tool already ran). ``PreToolUse`` never blocks.

Behavioural areas covered:

* **Never blocks on PreToolUse** — always exits 0 regardless of streak.
* **Streak accumulation** — sequential batchable calls with large gaps
  increment the streak; a small gap (same-message dispatch) resets it.
* **Non-batchable interruption** — a non-batchable tool (e.g. Edit) resets
  the streak, since it usually signals a real dependency, not a missed batch.
* **Nudge threshold** — the call that crosses ``NUDGE_THRESHOLD`` gets its
  own ``PostToolUse`` marked for a stderr reminder + exit 2; earlier calls
  in the streak do not.
* **UserPromptSubmit reset** — a new user turn always resets the streak.
* **Bash classification** — read-only prefixes (``git``, ``ls``, ...) count
  as batchable; everything else (including compound commands) does not.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Callable

import pytest

GAP_MS = 1500
NUDGE_THRESHOLD = 4


def _state_dir(session_id: str) -> Path:
    """Resolve the per-session batch state dir the hook reads/writes."""
    return Path("/tmp") / f"claude-state-{session_id}" / "batch"


@pytest.fixture
def session_id(request: pytest.FixtureRequest) -> Iterator[str]:
    """Unique session id per test, with state dir cleanup before AND after."""
    sid = f"test-batch-nudge-{request.node.name}"
    _rm(sid)
    yield sid
    _rm(sid)


def _rm(sid: str) -> None:
    import shutil

    shutil.rmtree(Path("/tmp") / f"claude-state-{sid}", ignore_errors=True)


def _backdate_last(sid: str, ms: int) -> None:
    """Push the recorded last-call timestamp back so the NEXT PreToolUse sees a large gap.

    No-op if ``last.json`` doesn't exist yet — e.g. no batchable call has landed
    (a non-batchable-tool test never writes it, by design).
    """
    last_file = _state_dir(sid) / "last.json"
    try:
        data = json.loads(last_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    data["ts"] -= ms
    last_file.write_text(json.dumps(data), encoding="utf-8")


def _pre(tool_name: str, sid: str, tool_use_id: str, tool_input: dict | None = None) -> dict:
    """Build a ``PreToolUse`` payload."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "session_id": sid,
        "tool_use_id": tool_use_id,
    }


def _post(tool_name: str, sid: str, tool_use_id: str, tool_input: dict | None = None) -> dict:
    """Build a ``PostToolUse`` payload."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "session_id": sid,
        "tool_use_id": tool_use_id,
    }


def _user_prompt(sid: str) -> dict:
    """Build a ``UserPromptSubmit`` payload."""
    return {"hook_event_name": "UserPromptSubmit", "session_id": sid}


def _run_streak(run_hook: Callable, sid: str, n: int, tool_name: str = "Read", tool_input: dict | None = None) -> list:
    """Fire ``n`` sequential batchable Pre/Post pairs with large backdated gaps.

    Returns the list of PostToolUse ``CompletedProcess`` results, one per call.
    """
    posts = []
    for i in range(n):
        tuid = f"tu{i}"
        if i > 0:
            # Backdate BEFORE this iteration's PreToolUse — its gap computation reads
            # last.json as written by the PREVIOUS iteration's PreToolUse.
            _backdate_last(sid, GAP_MS + 500)
        run_hook("batch-nudge.js", _pre(tool_name, sid, tuid, tool_input), cwd=Path("/tmp"))
        post = run_hook("batch-nudge.js", _post(tool_name, sid, tuid, tool_input), cwd=Path("/tmp"))
        posts.append(post)
    return posts


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
@pytest.mark.usefixtures("session_id")
class TestBatchNudge:
    """batch-nudge.js: non-blocking streak-based batching reminder."""

    def test_pretooluse_never_blocks(self, session_id: str, run_hook: Callable) -> None:
        """PreToolUse always exits 0, even mid-streak — only PostToolUse ever nudges."""
        for i in range(NUDGE_THRESHOLD + 2):
            result = run_hook("batch-nudge.js", _pre("Read", session_id, f"tu{i}"), cwd=Path("/tmp"))
            assert result.returncode == 0, result.stderr

    def test_no_nudge_below_threshold(self, session_id: str, run_hook: Callable) -> None:
        """Fewer than NUDGE_THRESHOLD sequential calls never trigger a nudge."""
        posts = _run_streak(run_hook, session_id, NUDGE_THRESHOLD - 1)

        assert all(p.returncode == 0 for p in posts)

    def test_nudge_fires_at_threshold(self, session_id: str, run_hook: Callable) -> None:
        """The call that crosses NUDGE_THRESHOLD gets a PostToolUse exit 2 + stderr reminder."""
        posts = _run_streak(run_hook, session_id, NUDGE_THRESHOLD)

        assert [p.returncode for p in posts] == [0, 0, 0, 2]
        assert "Batching reminder" in posts[-1].stderr

    def test_small_gap_resets_streak(self, session_id: str, run_hook: Callable) -> None:
        """Calls close in time (no backdating — same-message dispatch) never accumulate a streak."""
        posts = []
        for i in range(NUDGE_THRESHOLD + 2):
            tuid = f"tu{i}"
            run_hook("batch-nudge.js", _pre("Read", session_id, tuid), cwd=Path("/tmp"))
            post = run_hook("batch-nudge.js", _post("Read", session_id, tuid), cwd=Path("/tmp"))
            posts.append(post)

        assert all(p.returncode == 0 for p in posts)

    def test_non_batchable_tool_resets_streak(self, session_id: str, run_hook: Callable) -> None:
        """An Edit call mid-streak resets the counter — a dependency break, not a missed batch."""
        _run_streak(run_hook, session_id, NUDGE_THRESHOLD - 1)
        run_hook("batch-nudge.js", _pre("Edit", session_id, "tu-edit"), cwd=Path("/tmp"))

        posts = _run_streak(run_hook, session_id, NUDGE_THRESHOLD - 1)

        assert all(p.returncode == 0 for p in posts)

    def test_user_prompt_submit_resets_streak(self, session_id: str, run_hook: Callable) -> None:
        """A new user turn resets the streak regardless of what came before."""
        _run_streak(run_hook, session_id, NUDGE_THRESHOLD - 1)
        run_hook("batch-nudge.js", _user_prompt(session_id), cwd=Path("/tmp"))

        posts = _run_streak(run_hook, session_id, NUDGE_THRESHOLD - 1)

        assert all(p.returncode == 0 for p in posts)

    def test_readonly_bash_prefix_counts_as_batchable(self, session_id: str, run_hook: Callable) -> None:
        """`git log`-style read-only Bash commands accumulate the streak like Read/Grep/Glob."""
        posts = _run_streak(
            run_hook, session_id, NUDGE_THRESHOLD, tool_name="Bash", tool_input={"command": "git log -5"}
        )

        assert [p.returncode for p in posts] == [0, 0, 0, 2]

    def test_compound_bash_not_batchable(self, session_id: str, run_hook: Callable) -> None:
        """A compound command (`&&`/`;`/`|`) is skipped entirely — may write, never counted."""
        posts = _run_streak(
            run_hook, session_id, NUDGE_THRESHOLD, tool_name="Bash", tool_input={"command": "git status && rm -rf x"}
        )

        assert all(p.returncode == 0 for p in posts)

    def test_writing_bash_not_batchable(self, session_id: str, run_hook: Callable) -> None:
        """A mutating command (not in the read-only prefix set) never accumulates a streak."""
        posts = _run_streak(run_hook, session_id, NUDGE_THRESHOLD, tool_name="Bash", tool_input={"command": "rm x"})

        assert all(p.returncode == 0 for p in posts)
