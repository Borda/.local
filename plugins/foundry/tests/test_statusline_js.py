"""Subprocess tests for ``hooks/statusline.js``.

The hook is a status-line renderer: it consumes a JSON payload on stdin
and writes a two-line ANSI string to stdout. State for the segments
lives under ``/tmp/claude-state-<session_id>/`` and is written by
``task-log.js`` at runtime. These tests seed that state directly, then
assert against ``statusline.js`` stdout.

Line 2 format: ``⚡ <skills> │ 🤖 <agents> │ 🛠️ <tools>``.
Agents (including codex:* types) appear in the ``🤖`` segment.
Assertions strip ANSI escape sequences before substring matching so
the rendered marker and label co-occurrence is testable irrespective
of color wrapping.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    """Remove ANSI CSI sequences so substring assertions are color-agnostic."""
    return _ANSI.sub("", s)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sid(tmp_path: Path) -> Iterator[str]:
    """Yield a unique session id; clean ``/tmp/claude-state-<id>`` on teardown."""
    s = f"pytest-{tmp_path.name}"
    yield s
    shutil.rmtree(f"/tmp/claude-state-{s}", ignore_errors=True)


@pytest.fixture
def tmp_home(tmp_path: Path) -> Path:
    """Return an isolated HOME with an empty subscription.json so reads succeed."""
    h = tmp_path / "home"
    sub_dir = h / ".claude" / "state"
    sub_dir.mkdir(parents=True)
    (sub_dir / "subscription.json").write_text("{}", encoding="utf-8")
    return h


# ── Payload helper ───────────────────────────────────────────────────────────


def _payload(sid: str) -> dict:
    """Return a minimal valid statusline stdin payload for the given session id."""
    return {
        "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
        "workspace": {"current_dir": "/tmp/test"},
        "context_window": {"tokens_used": 1000, "tokens_remaining": 9000, "remaining_percentage": 90},
        "cost": {"total_cost_usd": 0.1},
        "session_id": sid,
        "effort": {"level": "normal"},
    }


def _write_agent(sid: str, agent_id: str, *, since: str, agent_type: str = "foundry:sw-engineer") -> None:
    """Write an agents/<id>.json file under the per-session state dir."""
    d = Path("/tmp") / f"claude-state-{sid}" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{agent_id}.json").write_text(
        json.dumps({"id": agent_id, "type": agent_type, "model": "opus", "color": None, "since": since}),
        encoding="utf-8",
    )


def _write_codex(sid: str, tool_use_id: str, *, since: str) -> None:
    """Write a codex/<id>.json file under the per-session state dir."""
    d = Path("/tmp") / f"claude-state-{sid}" / "codex"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tool_use_id}.json").write_text(
        json.dumps({"id": tool_use_id, "since": since, "type": "rescue"}),
        encoding="utf-8",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestAgentDisplay:
    """statusline.js: 🤖 segment rendering across empty, active, and stale agents."""

    def test_no_agents_shows_none(self, sid: str, tmp_home: Path, run_hook) -> None:
        """Empty state directory renders the ``🤖 none`` marker for the agent segment."""
        result = run_hook("statusline.js", _payload(sid), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rendered = _strip_ansi(result.stdout)
        assert "🤖 none" in rendered

    def test_active_agent_shows_not_none(self, sid: str, tmp_home: Path, run_hook) -> None:
        """One fresh agent entry produces a 🤖 segment without the 'none' label."""
        _write_agent(sid, "a1", since=datetime.now(timezone.utc).isoformat())

        result = run_hook("statusline.js", _payload(sid), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rendered = _strip_ansi(result.stdout)
        assert "🤖" in rendered
        assert "🤖 none" not in rendered

    def test_stale_agent_shows_none(self, sid: str, tmp_home: Path, run_hook) -> None:
        """Agent older than the 10-min safety net is dropped → ``🤖 none`` rendered."""
        stale = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        _write_agent(sid, "a-stale", since=stale)

        result = run_hook("statusline.js", _payload(sid), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rendered = _strip_ansi(result.stdout)
        assert "🤖 none" in rendered


@pytest.mark.skipif(sys.platform == "win32", reason="uses /tmp/")
class TestCodexDisplay:
    """statusline.js: codex:* agents shown in 🤖 segment via agents/ dir."""

    def test_no_codex_shows_none(self, sid: str, tmp_home: Path, run_hook) -> None:
        """Empty agents directory renders the ``🤖 none`` marker."""
        result = run_hook("statusline.js", _payload(sid), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rendered = _strip_ansi(result.stdout)
        assert "🤖 none" in rendered

    def test_active_codex_agent_shows_type_label(self, sid: str, tmp_home: Path, run_hook) -> None:
        """codex:rescue agent in agents/ renders its short type label in the 🤖 segment."""
        _write_agent(sid, "tu-cdx-1", since=datetime.now(timezone.utc).isoformat(), agent_type="codex:rescue")

        result = run_hook("statusline.js", _payload(sid), home=tmp_home)

        assert result.returncode == 0, result.stderr
        rendered = _strip_ansi(result.stdout)
        assert "🤖" in rendered
        assert "rescue" in rendered
