"""Subprocess tests for ``hooks/enforce-review-header.js``.

The hook is a ``PreToolUse`` gate on ``AskUserQuestion``. Its contract:

* **Scoped to in-flight reviews** — it acts only when the Step-2 sentinel
  ``${TMPDIR:-/tmp}/dev-review-report-dir-<CSID>`` exists; without it every
  ``AskUserQuestion`` passes through untouched (empty stdout, exit 0).
* **Denies a missing report** — sentinel present but
  ``$REPORT_DIR/review-report.md`` absent or empty means Step 5 (consolidate) /
  Step 5b (print report header) never happened, so the call is denied with an
  actionable reason.
* **Fails open** — stale sentinel, implausible sentinel content, vanished report
  dir, unparsable payload: every can't-tell case allows the call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "enforce-review-header.js"

CSID = "test-session-1234"
SENTINEL_NAME = f"dev-review-report-dir-{CSID}"
TWO_HOURS_S = 2 * 60 * 60

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="requires node to execute the hook",
)


def _ask_payload(**overrides: object) -> dict:
    """Build a PreToolUse AskUserQuestion payload, applying `overrides`."""
    payload: dict = {
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "What next?"}]},
    }
    payload.update(overrides)
    return payload


def _run(tmp_path: Path, payload: dict, *, session_id_env: str | None = CSID, tmpdir_suffix: str = "") -> dict:
    """Invoke the hook with `payload` on stdin and return parsed stdout (or {})."""
    env = {**os.environ, "TMPDIR": f"{tmp_path}{tmpdir_suffix}"}
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    if session_id_env is not None:
        env["CLAUDE_CODE_SESSION_ID"] = session_id_env
    proc = subprocess.run(
        ["node", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 0, f"hook exited {proc.returncode}: {proc.stderr}"
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def _denial_reason(result: dict) -> str | None:
    """Denial reason emitted by the hook, or None when it did not deny."""
    hook_output = result.get("hookSpecificOutput", {})
    if hook_output.get("permissionDecision") != "deny":
        return None
    return hook_output.get("permissionDecisionReason", "")


@pytest.fixture
def review_run(tmp_path: Path) -> tuple[Path, Path]:
    """Stage a review that reached Step 2: report dir on disk plus its sentinel."""
    report_dir = tmp_path / "repo" / ".reports" / "review" / "2026-08-04T10-00-00Z"
    report_dir.mkdir(parents=True)
    sentinel = tmp_path / SENTINEL_NAME
    sentinel.write_text(f"{report_dir}\n", encoding="utf-8")
    return report_dir, sentinel


# ── Gate fires only for an in-flight review missing its report ────────────────


def test_missing_report_is_denied(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """Sentinel present without review-report.md → deny, naming the step to redo."""
    report_dir, _ = review_run

    reason = _denial_reason(_run(tmp_path, _ask_payload()))

    assert reason is not None, "AskUserQuestion must be denied while the report is missing"
    assert str(report_dir / "review-report.md") in reason
    assert "Step 5b" in reason


def test_denial_names_the_develop_skill(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """Reason identifies develop:review, so the oss gate is not blamed for it."""
    reason = _denial_reason(_run(tmp_path, _ask_payload()))

    assert reason is not None
    assert reason.startswith("develop:review report gate")


def test_empty_report_is_denied(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """A zero-byte review-report.md counts as not written → deny."""
    report_dir, _ = review_run
    (report_dir / "review-report.md").touch()

    assert _denial_reason(_run(tmp_path, _ask_payload())) is not None


def test_written_report_passes_through(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """Consolidator output present → hook stays silent and the call proceeds."""
    report_dir, _ = review_run
    (report_dir / "review-report.md").write_text("---\nTitle: develop-review\n---\n", encoding="utf-8")

    assert _run(tmp_path, _ask_payload()) == {}


def test_trailing_slash_tmpdir_resolves_sentinel(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """macOS exports TMPDIR with a trailing slash — the sentinel must still resolve."""
    assert _denial_reason(_run(tmp_path, _ask_payload(), tmpdir_suffix="/")) is not None


def test_sentinel_resolved_from_payload_session_id(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """CSID falls back to the payload's session_id when the env var is unset."""
    result = _run(tmp_path, _ask_payload(session_id=CSID), session_id_env=None)

    assert _denial_reason(result) is not None


# ── Everything outside an in-flight review passes through ────────────────────


def test_no_sentinel_passes_through(tmp_path: Path) -> None:
    """No develop:review run reached Step 2 → unrelated questions are never gated."""
    assert _run(tmp_path, _ask_payload()) == {}


def test_oss_sentinel_does_not_trigger_develop_gate(tmp_path: Path) -> None:
    """An in-flight /oss:review is gated by its own plugin's hook, not this one."""
    report_dir = tmp_path / "repo" / ".reports" / "review" / "2026-08-04T10-00-00Z"
    report_dir.mkdir(parents=True)
    (tmp_path / f"oss-review-report-dir-{CSID}").write_text(f"{report_dir}\n", encoding="utf-8")

    assert _run(tmp_path, _ask_payload()) == {}


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_ask_payload(tool_name="Bash"), id="other-tool"),
        pytest.param(_ask_payload(hook_event_name="PostToolUse"), id="other-event"),
    ],
)
def test_non_matching_payloads_pass_through(tmp_path: Path, review_run: tuple[Path, Path], payload: dict) -> None:
    """Only PreToolUse AskUserQuestion is inspected; anything else is untouched."""
    assert _run(tmp_path, payload) == {}


def test_stale_sentinel_passes_through(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """Sentinel older than the enforcement window is treated as a crashed run."""
    _, sentinel = review_run
    stale = time.time() - (TWO_HOURS_S + 600)
    os.utime(sentinel, (stale, stale))

    assert _run(tmp_path, _ask_payload()) == {}


def test_missing_report_dir_passes_through(tmp_path: Path, review_run: tuple[Path, Path]) -> None:
    """Report dir gone (worktree removed, TTL cleanup) → hook cannot judge, allows."""
    report_dir, _ = review_run
    report_dir.rmdir()

    assert _run(tmp_path, _ask_payload()) == {}


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n", id="whitespace"),
        pytest.param("repo/.reports/review/2026-08-04T10-00-00Z\n", id="relative-path"),
        pytest.param("/etc\n", id="not-a-review-dir"),
    ],
)
def test_implausible_sentinel_content_passes_through(tmp_path: Path, content: str) -> None:
    """Sentinel not holding an absolute .reports/review/ path is ignored."""
    (tmp_path / SENTINEL_NAME).write_text(content, encoding="utf-8")

    assert _run(tmp_path, _ask_payload()) == {}


@pytest.mark.parametrize(
    "session_id",
    [
        pytest.param("../../etc/passwd", id="traversal"),
        pytest.param("has space", id="space"),
        pytest.param("", id="blank"),
    ],
)
def test_unsafe_csid_passes_through(tmp_path: Path, review_run: tuple[Path, Path], session_id: str) -> None:
    """A CSID that cannot name a sentinel file is discarded, never path-joined."""
    assert _run(tmp_path, _ask_payload(), session_id_env=session_id) == {}


def test_malformed_stdin_passes_through(tmp_path: Path) -> None:
    """A hook bug or unparsable payload must never strand the session."""
    proc = subprocess.run(
        ["node", str(HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )

    assert (proc.returncode, proc.stdout.strip()) == (0, "")
