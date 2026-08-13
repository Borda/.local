"""Subprocess tests for ``hooks/session-restore.js``.

The hook fires on ``SessionStart`` with matcher ``clear``.  It reads
``<cwd>/.claude/state/session/LATEST`` — resolving ``cwd`` from the hook
payload, never ``process.cwd()`` — and injects the handover document that
pointer names back into the fresh session as raw stdout.

Behavioural areas covered:

* **Silence by default** — no pointer, no ``cwd``, wrong event, wrong
  source, blank pointer, traversal pointer, malformed stdin: every one of
  them exits 0 with empty stdout.  A hook that blocks session start is
  worse than a hook that does nothing.
* **Gates** — a document is injected only while it is unconsumed *and*
  younger than 30 minutes.
* **Consumption** — a successful injection rewrites ``consumed: true`` and
  unlinks the pointer, so a second ``/clear`` re-injects nothing.
* **Size guard** — above ~8000 chars only ``## Goal``, the files table,
  ``## Next step`` and a ``/foundry:session recall`` pointer are injected.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOK = "session-restore.js"

pytestmark = pytest.mark.skipif(
    subprocess.run(["node", "--version"], capture_output=True, timeout=5).returncode != 0,
    reason="requires node on PATH",
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iso(minutes_ago: float = 0) -> str:
    """Return a UTC ISO8601 stamp *minutes_ago* minutes in the past."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_handover(
    project: Path,
    slug: str = "plan-x",
    *,
    consumed: str = "false",
    created: str | None = None,
    filler: str = "",
    pointer: str | None = None,
    newline: str = "\n",
) -> Path:
    """Create a handover doc plus its ``LATEST`` pointer under *project*.

    Written as bytes with an explicit line ending rather than through text mode: text mode
    silently emits CRLF on Windows, which made the platform — not the parameter — decide what
    the hook was fed. ``newline="\\r\\n"`` now exercises the CRLF path on every OS.

    Args:
        project: Directory standing in for the hook payload's ``cwd``.
        slug: Handover slug — also the document's basename.
        consumed: Raw value written to the ``consumed`` frontmatter field.
        created: ISO8601 stamp; defaults to now.
        filler: Extra body text appended under ``## Decisions``, used to
            push the document past the size guard.
        pointer: Contents of ``LATEST``; defaults to *slug*.
        newline: Line ending written into both the pointer and the document.

    Returns:
        Path of the handover document.
    """
    store_dir = project / ".claude" / "state" / "session"
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "LATEST").write_bytes(f"{slug if pointer is None else pointer}{newline}".encode())
    doc = store_dir / f"{slug}.md"
    doc.write_bytes(
        newline.join(
            [
                "---",
                f"slug: {slug}",
                f"created: {created or _iso()}",
                f"consumed: {consumed}",
                "branch: main",
                "---",
                "",
                "## Goal",
                "ship the session handover mechanism",
                "",
                "## Decisions",
                "- inline skill — why: a fork sees no conversation history",
                filler,
                "",
                "## Files touched",
                "",
                "| File | Change | State | Ref |",
                "| --- | --- | --- | --- |",
                "| `session-restore.js` | added SessionStart hook | done | +150/-0 |",
                "",
                "## Next step",
                "run the pytest suite",
                "",
            ]
        ).encode()
    )
    return doc


def payload(project: Path | None, **overrides) -> dict:
    """Build a SessionStart:clear hook payload for *project*."""
    data: dict = {"hook_event_name": "SessionStart", "source": "clear"}
    if project is not None:
        data["cwd"] = str(project)
    data.update(overrides)
    return data


# ── Silence by default ────────────────────────────────────────────────────────


def test_no_pointer_is_silent(run_hook, tmp_path: Path) -> None:
    (tmp_path / ".claude" / "state" / "session").mkdir(parents=True)
    result = run_hook(HOOK, payload(tmp_path))
    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_cwd_is_silent(run_hook) -> None:
    result = run_hook(HOOK, payload(None))
    assert result.returncode == 0
    assert result.stdout == ""


def test_other_event_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path)
    result = run_hook(HOOK, payload(tmp_path, hook_event_name="SessionEnd"))
    assert result.returncode == 0
    assert result.stdout == ""


def test_other_source_is_silent(run_hook, tmp_path: Path) -> None:
    """``matcher: clear`` filters in production; the in-code gate is a second line."""
    write_handover(tmp_path)
    result = run_hook(HOOK, payload(tmp_path, source="startup"))
    assert result.returncode == 0
    assert result.stdout == ""


def test_absent_source_still_injects(run_hook, tmp_path: Path) -> None:
    """Source gate is lenient — a payload without the field must not silently no-op."""
    write_handover(tmp_path)
    data = payload(tmp_path)
    del data["source"]
    result = run_hook(HOOK, data)
    assert "[session] restored" in result.stdout


def test_blank_pointer_is_silent(run_hook, tmp_path: Path) -> None:
    """``/foundry:session recall`` empties LATEST rather than deleting it."""
    write_handover(tmp_path, pointer="")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.returncode == 0
    assert result.stdout == ""


def test_traversal_pointer_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, pointer="../../../etc/passwd")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.returncode == 0
    assert result.stdout == ""


def test_pointer_to_missing_doc_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, pointer="does-not-exist")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.returncode == 0
    assert result.stdout == ""


def test_malformed_stdin_is_silent() -> None:
    """Bypasses ``run_hook`` deliberately — it JSON-encodes its payload."""
    hook_path = Path(__file__).resolve().parent.parent / "hooks" / HOOK
    result = subprocess.run(
        ["node", str(hook_path)],
        input="not json at all",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout == ""


# ── Gates ─────────────────────────────────────────────────────────────────────


def test_consumed_doc_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, consumed="true")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.stdout == ""


def test_expired_doc_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, created=_iso(minutes_ago=31))
    result = run_hook(HOOK, payload(tmp_path))
    assert result.stdout == ""


def test_doc_just_inside_window_injects(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, created=_iso(minutes_ago=29))
    result = run_hook(HOOK, payload(tmp_path))
    assert "[session] restored" in result.stdout


def test_unparseable_created_is_silent(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path, created="whenever")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.stdout == ""


# ── Injection content ─────────────────────────────────────────────────────────


def test_fresh_doc_injects_full_body(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path)
    out = run_hook(HOOK, payload(tmp_path)).stdout
    assert "[session] restored from `plan-x`" in out
    assert "branch main" in out
    assert "## Decisions" in out
    assert "## Files touched" in out
    assert "run the pytest suite" in out


def test_injection_strips_frontmatter(run_hook, tmp_path: Path) -> None:
    write_handover(tmp_path)
    out = run_hook(HOOK, payload(tmp_path)).stdout
    assert "slug: plan-x" not in out
    assert "consumed:" not in out


def test_oversized_doc_injects_head_only(run_hook, tmp_path: Path) -> None:
    filler = "- filler decision line, repeated for bulk\n" * 220
    write_handover(tmp_path, slug="big-x", filler=filler)
    out = run_hook(HOOK, payload(tmp_path)).stdout
    assert "filler decision line" not in out
    assert "## Goal" in out
    assert "## Files touched" in out
    assert "## Next step" in out
    assert "/foundry:session recall big-x" in out


# ── Consumption ───────────────────────────────────────────────────────────────


def test_injection_marks_consumed_and_clears_pointer(run_hook, tmp_path: Path) -> None:
    doc = write_handover(tmp_path)
    run_hook(HOOK, payload(tmp_path))
    assert "consumed: true" in doc.read_text(encoding="utf8")
    assert not (tmp_path / ".claude" / "state" / "session" / "LATEST").exists()


def test_second_clear_is_idempotent(run_hook, tmp_path: Path) -> None:
    doc = write_handover(tmp_path)
    first = run_hook(HOOK, payload(tmp_path))
    second = run_hook(HOOK, payload(tmp_path))
    assert "[session] restored" in first.stdout
    assert second.stdout == ""
    assert "consumed: true" in doc.read_text(encoding="utf8")


def test_consumption_rewrites_only_the_flag(run_hook, tmp_path: Path) -> None:
    """The rewrite must round-trip the doc — closing ``---`` delimiter and body intact."""
    doc = write_handover(tmp_path)
    before = doc.read_text(encoding="utf8")
    run_hook(HOOK, payload(tmp_path))
    after = doc.read_text(encoding="utf8")
    assert after == before.replace("consumed: false", "consumed: true", 1)
    assert after.split("\n")[5] == "---"


# ── CRLF documents ────────────────────────────────────────────────────────────
#
# A doc written on Windows carries CRLF. `.` in a JS regex excludes `\r` and `$` without the `m`
# flag anchors at end-of-string, so a frontmatter parser splitting on `\n` alone matched no line
# at all: every field came back undefined and each gate below it exited silent. These run on every
# platform — the line ending is written explicitly, not inherited from the host.


def test_crlf_doc_injects(run_hook, tmp_path: Path) -> None:
    """Frontmatter gates must parse a CRLF document, not fall through to silence."""
    write_handover(tmp_path, newline="\r\n")
    result = run_hook(HOOK, payload(tmp_path))
    assert "[session] restored from `plan-x`" in result.stdout
    assert "branch main" in result.stdout


def test_crlf_doc_gates_still_reject_consumed(run_hook, tmp_path: Path) -> None:
    """CRLF parsing must read the real flag value, not merely find the key."""
    write_handover(tmp_path, consumed="true", newline="\r\n")
    result = run_hook(HOOK, payload(tmp_path))
    assert result.stdout == ""


def test_crlf_consumption_preserves_line_endings(run_hook, tmp_path: Path) -> None:
    """The in-place rewrite round-trips byte for byte apart from the flag — no lone LF left behind."""
    doc = write_handover(tmp_path, newline="\r\n")
    before = doc.read_bytes()
    run_hook(HOOK, payload(tmp_path))
    after = doc.read_bytes()
    assert after == before.replace(b"consumed: false", b"consumed: true", 1)
    assert b"\n" not in after.replace(b"\r\n", b"")


# ── Registration ──────────────────────────────────────────────────────────────


def test_hook_is_registered_with_clear_matcher() -> None:
    """``agent-router.js`` has an unregistered SessionStart branch — this one must not."""
    hooks_json = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"
    entries = json.loads(hooks_json.read_text(encoding="utf8"))["hooks"]["SessionStart"]
    matching = [entry for entry in entries if any(HOOK in hook.get("command", "") for hook in entry.get("hooks", []))]
    assert len(matching) == 1
    assert matching[0].get("matcher") == "clear"
