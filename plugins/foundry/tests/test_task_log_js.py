"""Subprocess tests for ``hooks/task-log.js``.

The hook is invoked as a Node.js child process with a JSON payload on
stdin and asserted against the per-session state directory written
under ``/tmp/claude-state-<session_id>``. No JS is mocked — each test
spawns the real script via ``node`` and inspects filesystem effects.

Three behavioural areas are covered:

* **Agent lifecycle** — ``PreToolUse`` / ``PostToolUse`` for ``Agent()``
  plus ``SubagentStart`` / ``SubagentStop`` events.
* **Codex tracking** — ``Skill(codex:*)`` creates a codex file consumed
  by the status line and cleaned up on ``PostToolUse``.
* **Tool counting** — non-Agent ``PreToolUse`` increments a per-tool
  counter file used by the status line's tool-activity segment.

Contract notes
--------------
This hook version writes the ``pending/<tool_use_id>.json`` cache on
``PreToolUse(Agent)`` and **consumes** it on ``SubagentStart`` (or
leaves it for ``SessionEnd`` to wipe). ``PostToolUse(Agent)`` deletes
**both** the ``agents/`` tracking file **and** the ``pending/`` marker so
that ``SubagentStart`` (which may fire after ``PostToolUse`` for
background agents) always creates a fresh ``agents/<agent_id>.json``
rather than silently skipping the write because it found a stale pending
entry.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sid(tmp_path: Path) -> Iterator[str]:
    """Yield a unique session id; clean ``/tmp/claude-state-<id>`` on teardown."""
    s = f"pytest-{tmp_path.name}"
    yield s
    shutil.rmtree(f"/tmp/claude-state-{s}", ignore_errors=True)


@pytest.fixture
def tmp_home(tmp_path: Path) -> Path:
    """Return an isolated HOME so audit-log writes don't pollute the real user dir."""
    h = tmp_path / "home"
    (h / ".claude" / "logs").mkdir(parents=True)
    return h


# ── Payload helpers (module-level, not fixtures) ─────────────────────────────


def _pre_agent(
    sid: str, tool_use_id: str, subagent_type: str = "foundry:sw-engineer", run_in_background: bool = False
) -> dict:
    """Build a ``PreToolUse`` payload for an ``Agent()`` tool call."""
    tool_input: dict = {"subagent_type": subagent_type, "description": "x", "prompt": "p"}
    if run_in_background:
        tool_input["run_in_background"] = True
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
        "session_id": sid,
    }


def _post_agent(sid: str, tool_use_id: str) -> dict:
    """Build a ``PostToolUse`` payload for an ``Agent()`` tool call.

    Mirrors the live payload where PostToolUse's ``tool_input`` omits ``run_in_background`` —
    the hook must recover background-ness from the ``pending/`` marker written at PreToolUse.
    """
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "foundry:sw-engineer"},
        "tool_use_id": tool_use_id,
        "session_id": sid,
    }


def _subagent_start(
    sid: str,
    agent_id: str,
    agent_type: str = "foundry:sw-engineer",
    tool_use_id: str | None = None,
) -> dict:
    """Build a ``SubagentStart`` payload."""
    payload: dict = {
        "hook_event_name": "SubagentStart",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "session_id": sid,
    }
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    return payload


def _subagent_stop(sid: str, agent_id: str) -> dict:
    """Build a ``SubagentStop`` payload."""
    return {
        "hook_event_name": "SubagentStop",
        "agent_id": agent_id,
        "session_id": sid,
    }


def _pre_skill(sid: str, tool_use_id: str, skill: str) -> dict:
    """Build a ``PreToolUse`` payload for a ``Skill()`` call."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": skill, "args": ""},
        "tool_use_id": tool_use_id,
        "session_id": sid,
    }


def _post_skill(sid: str, tool_use_id: str, skill: str) -> dict:
    """Build a ``PostToolUse`` payload for a ``Skill()`` call."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": skill, "args": ""},
        "tool_use_id": tool_use_id,
        "session_id": sid,
    }


def _pre_bash(sid: str, tool_use_id: str) -> dict:
    """Build a ``PreToolUse`` payload for a ``Bash`` call."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_use_id": tool_use_id,
        "session_id": sid,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestAgentLifecycle:
    """task-log.js: PreToolUse / PostToolUse / SubagentStart / SubagentStop for Agent()."""

    def test_pre_tool_use_creates_agents_and_pending(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """PreToolUse for Agent() writes both agents/<tool_use_id>.json and pending/<tool_use_id>.json."""
        tool_use_id = "tu-create"

        result = run_hook("task-log.js", _pre_agent(sid, tool_use_id), home=tmp_home)

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()
        assert (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

    def test_post_tool_use_deletes_agents_and_pending(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """PostToolUse for Agent() deletes both agents/ and pending/ markers.

        Both files must be removed so that a later SubagentStart (which fires
        after PostToolUse for background agents) does not find a stale pending
        entry and silently skip writing its own agents/<agent_id>.json.
        """
        tool_use_id = "tu-delete"
        run_hook("task-log.js", _pre_agent(sid, tool_use_id), home=tmp_home)
        assert (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()
        assert (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

        result = run_hook("task-log.js", _post_agent(sid, tool_use_id), home=tmp_home)

        assert result.returncode == 0, result.stderr
        assert not (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()
        assert not (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

    def test_background_agent_tracked_after_post_then_subagent_start(
        self, sid: str, tmp_home: Path, run_hook, state_dir
    ) -> None:
        """Background agents are tracked even when PostToolUse fires before SubagentStart.

        Regression test for the race condition where PostToolUse fires immediately
        after launch (before the agent starts), leaving a stale pending/ marker.
        SubagentStart must fall through to write a fresh agents/<agent_id>.json.
        """
        tool_use_id = "tu-bg"
        agent_id = "agent-bg"
        run_hook("task-log.js", _pre_agent(sid, tool_use_id), home=tmp_home)
        run_hook("task-log.js", _post_agent(sid, tool_use_id), home=tmp_home)
        assert not (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

        result = run_hook(
            "task-log.js",
            _subagent_start(sid, agent_id, tool_use_id=tool_use_id),
            home=tmp_home,
        )

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "agents" / f"{agent_id}.json").exists()

    def test_background_agent_survives_post_tool_use(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """run_in_background agents stay tracked after PostToolUse, which fires at dispatch.

        Regression: a background agent is still running when its Agent() tool call returns, so
        PostToolUse must NOT delete the agents/ entry — the 🤖 badge would otherwise show "none"
        for the agent's whole runtime. Background-ness is recovered from the pending/ marker,
        since PostToolUse's tool_input omits run_in_background.
        """
        tool_use_id = "tu-bgkeep"
        run_hook("task-log.js", _pre_agent(sid, tool_use_id, run_in_background=True), home=tmp_home)
        assert (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()

        result = run_hook("task-log.js", _post_agent(sid, tool_use_id), home=tmp_home)

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()
        assert (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

    def test_foreground_agent_subagent_start_consumes_pending(
        self, sid: str, tmp_home: Path, run_hook, state_dir
    ) -> None:
        """SubagentStart with a matching pending entry consumes it without double-writing agents/<agent_id>.json."""
        tool_use_id = "tu-fg"
        agent_id = "agent-fg"
        run_hook("task-log.js", _pre_agent(sid, tool_use_id), home=tmp_home)
        assert (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

        result = run_hook(
            "task-log.js",
            _subagent_start(sid, agent_id, tool_use_id=tool_use_id),
            home=tmp_home,
        )

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "agents" / f"{tool_use_id}.json").exists()
        assert not (state_dir(sid) / "agents" / f"{agent_id}.json").exists()
        assert not (state_dir(sid) / "pending" / f"{tool_use_id}.json").exists()

    def test_subagent_start_no_pending_writes_agent_file(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """Team-mode SubagentStart (no pending entry) writes agents/<agent_id>.json directly."""
        agent_id = "agent-team"

        result = run_hook(
            "task-log.js",
            _subagent_start(sid, agent_id, agent_type="foundry:qa-specialist"),
            home=tmp_home,
        )

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "agents" / f"{agent_id}.json").exists()

    def test_subagent_stop_removes_agent_file(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """SubagentStop deletes the per-agent file written by SubagentStart."""
        agent_id = "agent-stop"
        run_hook(
            "task-log.js",
            _subagent_start(sid, agent_id, agent_type="foundry:qa-specialist"),
            home=tmp_home,
        )
        assert (state_dir(sid) / "agents" / f"{agent_id}.json").exists()

        result = run_hook("task-log.js", _subagent_stop(sid, agent_id), home=tmp_home)

        assert result.returncode == 0, result.stderr
        assert not (state_dir(sid) / "agents" / f"{agent_id}.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestCodexTracking:
    """task-log.js: Skill(codex:*) tracking under state/codex/."""

    def test_codex_skill_pre_creates_codex_file(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """PreToolUse for Skill(codex:rescue) writes codex/<tool_use_id>.json."""
        tool_use_id = "tu-cdx-pre"

        result = run_hook(
            "task-log.js",
            _pre_skill(sid, tool_use_id, skill="codex:rescue"),
            home=tmp_home,
        )

        assert result.returncode == 0, result.stderr
        assert (state_dir(sid) / "codex" / f"{tool_use_id}.json").exists()

    def test_codex_skill_post_removes_codex_file(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """PostToolUse for Skill(codex:rescue) removes the codex tracking file."""
        tool_use_id = "tu-cdx-post"
        run_hook("task-log.js", _pre_skill(sid, tool_use_id, skill="codex:rescue"), home=tmp_home)
        assert (state_dir(sid) / "codex" / f"{tool_use_id}.json").exists()

        result = run_hook(
            "task-log.js",
            _post_skill(sid, tool_use_id, skill="codex:rescue"),
            home=tmp_home,
        )

        assert result.returncode == 0, result.stderr
        assert not (state_dir(sid) / "codex" / f"{tool_use_id}.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestToolCounting:
    """task-log.js: per-tool counter under state/tools/."""

    def test_pre_tool_use_bash_creates_counter(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """First Bash PreToolUse creates tools/Bash.json with count=1."""
        result = run_hook("task-log.js", _pre_bash(sid, "tu-bash-1"), home=tmp_home)

        assert result.returncode == 0, result.stderr
        counter = state_dir(sid) / "tools" / "Bash.json"
        assert counter.exists()
        data = json.loads(counter.read_text(encoding="utf-8"))
        assert data["count"] == 1
        assert data["tool"] == "Bash"

    def test_pre_tool_use_bash_increments_counter(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """Second Bash PreToolUse increments count to 2 (within 30s window)."""
        run_hook("task-log.js", _pre_bash(sid, "tu-bash-a"), home=tmp_home)
        result = run_hook("task-log.js", _pre_bash(sid, "tu-bash-b"), home=tmp_home)

        assert result.returncode == 0, result.stderr
        data = json.loads((state_dir(sid) / "tools" / "Bash.json").read_text(encoding="utf-8"))
        assert data["count"] == 2
