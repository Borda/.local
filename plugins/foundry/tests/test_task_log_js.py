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


def _pre_tool_with_cwd(sid: str, tool_use_id: str, cwd: str, tool_name: str = "Read") -> dict:
    """Build a PreToolUse payload carrying a ``cwd`` (a subagent's worktree working dir).

    Mirrors the live CC hook contract where PreToolUse payloads include ``cwd`` but no
    ``agent_id`` — the field ``touchAgentLastActive`` uses to attribute worktree activity.
    """
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": "/x"} if tool_name == "Read" else {"command": "echo hi"},
        "tool_use_id": tool_use_id,
        "session_id": sid,
        "cwd": cwd,
    }


def _pre_compact(sid: str, transcript_path: str) -> dict:
    """Build a ``PreCompact`` payload pointing at a transcript file."""
    return {
        "hook_event_name": "PreCompact",
        "transcript_path": transcript_path,
        "session_id": sid,
    }


def _write_agent_file(state_dir, sid: str, agent_id: str) -> None:
    """Seed an agents/<agent_id>.json record with a fixed dispatch time and no last_active.

    The fixed ``since`` (2000-01-01) lets a test assert it is preserved untouched by a refresh.
    """
    d = state_dir(sid) / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{agent_id}.json").write_text(
        json.dumps(
            {
                "id": agent_id,
                "type": "foundry:sw-engineer",
                "model": "inherit",
                "color": None,
                "since": "2000-01-01T00:00:00.000Z",
            }
        ),
        encoding="utf-8",
    )


def _write_transcript(path: Path, file_paths: list[str]) -> None:
    """Write a minimal JSONL transcript with Write tool_use blocks for ``file_paths``."""
    lines = []
    for fp in file_paths:
        block = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": fp}}]},
        }
        lines.append(json.dumps(block))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestAgentLivenessRefresh:
    """task-log.js: touchAgentLastActive refreshes a worktree subagent's last_active on tool activity."""

    def test_worktree_tool_event_stamps_last_active(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """A tool event with cwd = .claude/worktrees/agent-<id> stamps last_active on agents/<id>.json.

        The agent file is keyed by agent_id (as SubagentStart writes it); the worktree cwd basename
        (agent-<id>) resolves back to that key, so the still-running agent's freshness is renewed.
        """
        agent_id = "a0abc123"
        _write_agent_file(state_dir, sid, agent_id)
        cwd = f"/repo/.claude/worktrees/agent-{agent_id}"

        result = run_hook("task-log.js", _pre_tool_with_cwd(sid, "tu-r1", cwd), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rec = json.loads((state_dir(sid) / "agents" / f"{agent_id}.json").read_text(encoding="utf-8"))
        assert "last_active" in rec
        assert rec["since"] == "2000-01-01T00:00:00.000Z"  # dispatch time preserved, not overwritten

    def test_non_worktree_cwd_does_not_stamp(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """A tool event whose cwd is the project root (not a worktree) leaves last_active unset.

        Non-worktree agents share the parent's cwd, so their activity can't be attributed to a
        specific agent — the record must stay unchanged and rely on the staleness backstop.
        """
        agent_id = "a0def456"
        _write_agent_file(state_dir, sid, agent_id)
        cwd = "/repo"  # project root, not a worktree

        result = run_hook("task-log.js", _pre_tool_with_cwd(sid, "tu-r2", cwd), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rec = json.loads((state_dir(sid) / "agents" / f"{agent_id}.json").read_text(encoding="utf-8"))
        assert "last_active" not in rec

    def test_worktree_cwd_no_matching_agent_is_noop(self, sid: str, tmp_home: Path, run_hook, state_dir) -> None:
        """A worktree cwd whose agent file is absent (agent finished) is a silent no-op, not an error."""
        cwd = "/repo/.claude/worktrees/agent-a0gone999"

        result = run_hook("task-log.js", _pre_tool_with_cwd(sid, "tu-r3", cwd), home=tmp_home)

        assert result.returncode == 0, result.stderr
        assert not (state_dir(sid) / "agents" / "a0gone999.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestPreCompactContract:
    """task-log.js: PreCompact writes session-context.md and preserves the skill contract verbatim.

    PreCompact writes ``<cwd>/.claude/state/session-context.md`` (cwd = project root),
    not the ``/tmp/claude-state-<sid>`` ephemeral dir — so these tests pass ``cwd`` and
    read the context file from that project-local state dir.
    """

    def test_precompact_appends_contract_verbatim(self, sid: str, tmp_home: Path, tmp_path: Path, run_hook) -> None:
        """A staged skill-contract.md is appended verbatim under its own section alongside Files Modified."""
        proj = tmp_path / "proj"
        state = proj / ".claude" / "state"
        state.mkdir(parents=True)
        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript, ["/proj/src/foo.py"])
        contract = "CONTRACT: keep phase 3 in-progress; do NOT re-run steps 1-2.\n- next: verify tests"
        (state / "skill-contract.md").write_text(contract, encoding="utf-8")

        result = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)

        assert result.returncode == 0, result.stderr
        written = (state / "session-context.md").read_text(encoding="utf-8")
        assert "## Files Modified This Session" in written
        assert "- /proj/src/foo.py" in written
        assert "## Skill Compaction Contract" in written
        assert contract in written

    def test_precompact_no_contract_writes_files_only(self, sid: str, tmp_home: Path, tmp_path: Path, run_hook) -> None:
        """With no skill-contract.md, PreCompact writes Files Modified and no contract section, no error."""
        proj = tmp_path / "proj"
        (proj / ".claude" / "state").mkdir(parents=True)
        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript, ["/proj/src/bar.py"])

        result = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)

        assert result.returncode == 0, result.stderr
        written = (proj / ".claude" / "state" / "session-context.md").read_text(encoding="utf-8")
        assert "## Files Modified This Session" in written
        assert "- /proj/src/bar.py" in written
        assert "## Skill Compaction Contract" not in written


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestPreCompactParkedItems:
    """task-log.js: PreCompact preserves the foundry:session ``## Parked items`` section.

    The session skill writes ``## Parked items`` into the same session-context.md that
    PreCompact rewrites from scratch. Without carry-over the rewrite clobbers parked items —
    these tests assert the section survives compaction, coexists with the fresh Files-Modified
    and Skill-Compaction-Contract sections, and never duplicates across repeated compactions.
    """

    _PARKED = "## Parked items\n- [ ] investigate flaky timing test\n- [ ] revisit split ratio 80/20"

    def _seed(self, tmp_path: Path, prior_context: str) -> tuple[Path, Path, Path]:
        """Create a project tree with a pre-existing session-context.md and a transcript."""
        proj = tmp_path / "proj"
        state = proj / ".claude" / "state"
        state.mkdir(parents=True)
        (state / "session-context.md").write_text(prior_context, encoding="utf-8")
        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript, ["/proj/src/foo.py"])
        return proj, state, transcript

    def test_precompact_preserves_parked_items(self, sid: str, tmp_home: Path, tmp_path: Path, run_hook) -> None:
        """A pre-existing ``## Parked items`` section survives the PreCompact rewrite alongside Files Modified."""
        prior = (
            f"# Session Context (auto-generated)\n## Files Modified This Session\n- /old/stale.py\n\n{self._PARKED}\n"
        )
        proj, state, transcript = self._seed(tmp_path, prior)

        result = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)

        assert result.returncode == 0, result.stderr
        written = (state / "session-context.md").read_text(encoding="utf-8")
        assert "## Files Modified This Session" in written
        assert "- /proj/src/foo.py" in written  # fresh scan, not the stale prior entry
        assert "- /old/stale.py" not in written
        assert "## Parked items" in written
        assert "- [ ] investigate flaky timing test" in written
        assert "- [ ] revisit split ratio 80/20" in written

    def test_precompact_preserves_parked_and_contract(self, sid: str, tmp_home: Path, tmp_path: Path, run_hook) -> None:
        """Parked items coexist with a staged skill contract and the fresh Files-Modified section."""
        prior = f"# Session Context (auto-generated)\n## Files Modified This Session\n- /old/x.py\n\n{self._PARKED}\n"
        proj, state, transcript = self._seed(tmp_path, prior)
        contract = "CONTRACT: keep phase 3 in-progress; do NOT re-run steps 1-2."
        (state / "skill-contract.md").write_text(contract, encoding="utf-8")

        result = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)

        assert result.returncode == 0, result.stderr
        written = (state / "session-context.md").read_text(encoding="utf-8")
        assert "## Files Modified This Session" in written
        assert "## Skill Compaction Contract" in written
        assert contract in written
        assert "## Parked items" in written
        assert "- [ ] investigate flaky timing test" in written

    def test_precompact_parked_items_idempotent(self, sid: str, tmp_home: Path, tmp_path: Path, run_hook) -> None:
        """Firing PreCompact twice keeps exactly one ``## Parked items`` section (no accumulation)."""
        prior = f"# Session Context (auto-generated)\n## Files Modified This Session\n- /old/x.py\n\n{self._PARKED}\n"
        proj, state, transcript = self._seed(tmp_path, prior)

        first = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)
        second = run_hook("task-log.js", _pre_compact(sid, str(transcript)), home=tmp_home, cwd=proj)

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        written = (state / "session-context.md").read_text(encoding="utf-8")
        assert written.count("## Parked items") == 1
        assert written.count("- [ ] investigate flaky timing test") == 1
