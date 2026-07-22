"""Subprocess tests for ``hooks/sentinel-read-allow.js``.

The hook is a ``PreToolUse`` gate that auto-allows Bash commands whose ONLY
command substitutions are the plugin-blueprint sentinel-read idiom
``$(cat "${TMPDIR:-/tmp}/<name>")`` and whose every segment is read-only.
Its security contract:

* **Allow-original, never rewrite** — no ``updatedInput`` is emitted, so
  settings.json deny rules keep matching the original command string.
* **Sentinel shape only** — any non-sentinel substitution, backtick, process
  substitution, heredoc, or write-redirect passes through unchanged (empty
  stdout, exit 0) to real permission checking.
* **Read-only segments** — a whitelisted first token is required per segment;
  guarded CLIs (git, gh, rm, ...) always passthrough.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "sentinel-read-allow.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="requires node to execute the hook",
)

SENTINEL = '"${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"'


def _run(command: str) -> dict:
    """Invoke the hook with a Bash tool payload and return parsed stdout (or {})."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["node", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"hook exited {proc.returncode}: {proc.stderr}"
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def _is_allowed(result: dict) -> bool:
    """True when the hook emitted a permissionDecision allow."""
    try:
        return result["hookSpecificOutput"]["permissionDecision"] == "allow"
    except (KeyError, TypeError):
        return False


# ── Blueprint sentinel reads with read-only follow-ups are allowed ────────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            'export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"\n'
            f"RUN_DIR=$(cat {SENTINEL})\n"
            'cat "$RUN_DIR/foundry--solution-architect.md"',
            id="observed-run-dir-cat",
        ),
        pytest.param(
            f'RUN_DIR="$(cat {SENTINEL})"; ls "$RUN_DIR"/*.md',
            id="observed-quoted-assign-ls-glob",
        ),
        pytest.param(
            'FOUNDRY_SHARED=$(cat "${TMPDIR:-/tmp}/foundry-shared-dir-${CSID}"); '
            'cat "$FOUNDRY_SHARED/agent-spawn-protocol.md"',
            id="observed-shared-dir-cat",
        ),
        pytest.param(
            'V=$(cat ${TMPDIR:-/tmp}/dev-review-run-dir-123 2>/dev/null || echo "")',
            id="unquoted-path-variant",
        ),
        pytest.param(
            f'V=$(cat {SENTINEL} 2>/dev/null || echo "$CLEAN_ARGS")',
            id="default-from-variable",
        ),
        pytest.param(
            f'V=$(cat {SENTINEL}); grep -c "verdict" "$V/report.md" | head -5',
            id="pipe-into-whitelisted",
        ),
        pytest.param(
            f'V=$(cat {SENTINEL}); [ -z "$V" ] && echo missing',
            id="test-bracket-guard",
        ),
        pytest.param(
            'TS=$(date -u +%Y-%m-%dT%H-%M-%SZ); echo "$TS"',
            id="date-stamp-echo",
        ),
        pytest.param(
            'IFS= read -r TS < "${TMPDIR:-/tmp}/dev-fix-team-ts-${CSID}" 2>/dev/null || TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)',
            id="read-form-with-date-fallback",
        ),
        # Pure read-form anchor — ZERO substitutions. Prefix allow-rules can never
        # match it (first token = `IFS=` assignment), so the hook must carry it.
        pytest.param(
            'IFS= read -r RUN_DIR < "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}" 2>/dev/null || RUN_DIR=""',
            id="read-form-pure-no-subst",
        ),
        pytest.param(
            'IFS= read -r V < "${TMPDIR:-/tmp}/foundry-shared-dir-${CSID}" 2>/dev/null || V=""\n'
            'cat "$V/agent-spawn-protocol.md"',
            id="read-form-then-cat",
        ),
        pytest.param(
            "IFS= read -r V < ${TMPDIR:-/tmp}/dev-review-run-dir-123 2>/dev/null || V=x",
            id="read-form-unquoted-path",
        ),
    ],
)
def test_blueprint_sentinel_reads_are_allowed(command: str) -> None:
    """Sentinel-read idiom plus read-only segments gets permissionDecision allow."""
    result = _run(command)
    assert _is_allowed(result), f"{command!r} should be allowed, got: {result}"


def test_allow_emits_no_updated_input() -> None:
    """Allow decision must not rewrite the command — deny rules match the original."""
    result = _run(f"V=$(cat {SENTINEL})")
    assert "updatedInput" not in result["hookSpecificOutput"]


# ── Anything not provably the blueprint idiom must passthrough ────────────────


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(f"rm $(cat {SENTINEL})", id="rm-not-whitelisted"),
        pytest.param(f"V=$(cat {SENTINEL}); git push origin main", id="git-push-chain"),
        pytest.param('V=$(cat "/etc/passwd")', id="non-tmpdir-path"),
        pytest.param('V=$(cat "$HOME/.ssh/id_rsa")', id="home-path"),
        pytest.param(f"V=$(cat {SENTINEL}); W=$(date)", id="second-non-sentinel-subst"),
        pytest.param("V=`cat ${TMPDIR:-/tmp}/x`", id="backtick"),
        pytest.param(f"V=$(cat {SENTINEL}); diff <(echo a) <(echo b)", id="process-subst"),
        pytest.param(f"V=$(cat {SENTINEL}); cat <<EOF\nhi\nEOF", id="heredoc"),
        pytest.param(f'V=$(cat {SENTINEL}); echo hi > "$V/out.txt"', id="write-redirect"),
        pytest.param(
            'V=$(cat "${TMPDIR:-/tmp}/${X:-$(rm -rf /)}")',
            id="nested-subst-inside-param-expansion",
        ),
        pytest.param(
            'echo \\" ; rm -rf / ; echo \\"',
            id="escaped-quote-smuggling",
        ),
        pytest.param("ls -la", id="no-substitution-at-all"),
        # Read-form anchor must NOT loosen anything else:
        pytest.param('IFS= read -r V < "/etc/passwd"', id="read-form-non-tmpdir"),
        pytest.param(
            'IFS= read -r V < "${TMPDIR:-/tmp}/s-1" || V=""; rm -rf "$V"',
            id="read-form-then-rm",
        ),
        pytest.param('read -r V < "${TMPDIR:-/tmp}/../../etc/passwd"', id="read-form-traversal"),
        pytest.param(f"export PATH=/tmp/evil:$PATH; IFS= read -r V < {SENTINEL}", id="read-form-path-hijack"),
        pytest.param("TS=$(date +%s; rm -rf /)", id="date-with-injected-command"),
        pytest.param("TS=$(date -u +%Y -d yesterday)", id="date-with-extra-arg"),
        pytest.param(f"V=$(cat {SENTINEL}); python -c 'x'", id="python-not-whitelisted"),
        pytest.param(f"V=$(cat {SENTINEL}); curl https://x.example", id="curl-not-whitelisted"),
    ],
)
def test_non_blueprint_commands_passthrough(command: str) -> None:
    """Everything not provably the blueprint idiom falls through to real checks."""
    result = _run(command)
    assert result == {}, f"{command!r} was allowed — gate bypass risk: {result}"


# ── Codex adversarial-review PoCs (2026-07-22) — all MUST passthrough ─────────


@pytest.mark.parametrize(
    "command",
    [
        # Class 1 — unquoted path/default swallowing shell syntax (injection inside $()).
        pytest.param("V=$(cat ${TMPDIR:-/tmp}/sentinel;rm${IFS}/tmp/pwned)", id="poc-unquoted-semicolon-rm"),
        pytest.param("V=$(cat ${TMPDIR:-/tmp}/sentinel;curl${IFS}https://x.invalid)", id="poc-unquoted-curl"),
        pytest.param("V=$(cat ${TMPDIR:-/tmp}/sentinel>/tmp/pwned)", id="poc-unquoted-redirect-in-subst"),
        pytest.param("V=$(cat ${TMPDIR:-/tmp}/sentinel||echo ;>/tmp/pwned)", id="poc-unquoted-default-redirect"),
        pytest.param("V=$(cat ${TMPDIR:-/tmp}/sentinel)>(touch${IFS}/tmp/pwned)", id="poc-proc-subst-tail"),
        # Class 2 — find spawns / deletes.
        pytest.param(
            f"V=$(cat {SENTINEL}); find /tmp -exec sh -c 'touch /tmp/pwned' {{}} \\;",
            id="poc-find-exec",
        ),
        pytest.param(f"V=$(cat {SENTINEL}); find /tmp -exec curl https://x.invalid \\;", id="poc-find-exec-curl"),
        pytest.param(f"V=$(cat {SENTINEL}); find /tmp -delete", id="poc-find-delete"),
        # Class 3 — writer tokens.
        pytest.param(f"V=$(cat {SENTINEL}); touch /tmp/pwned", id="poc-touch"),
        pytest.param("TS=$(date +%s); mkdir -p /tmp/pwned-dir", id="poc-mkdir"),
        pytest.param("TS=$(date +%s); sort -o /tmp/pwned /etc/hosts", id="poc-sort-o"),
        pytest.param("TS=$(date +%s); date --set=@0", id="poc-date-set-token"),
        # Class 4 — path traversal (input-redirect `<` is intentionally allowed:
        # no escalation over what a whitelisted read-only token already reads).
        pytest.param('V=$(cat ${TMPDIR:-/tmp}/../../etc/passwd); printf %s "$V"', id="poc-traversal"),
        # Re-review pass 2 — loader/lookup-path hijack via sensitive assignment.
        pytest.param(f"export PATH=/tmp/attacker:$PATH; V=$(cat {SENTINEL})", id="poc-path-hijack"),
        pytest.param(f"PATH=/tmp/x:$PATH V=$(cat {SENTINEL})", id="poc-path-inline"),
        pytest.param(f"export LD_PRELOAD=/tmp/evil.so; V=$(cat {SENTINEL}); cat x", id="poc-ld-preload"),
        pytest.param(f"IFS=x; V=$(cat {SENTINEL})", id="poc-nonempty-ifs"),
        # Re-review pass 2 — unquoted bare $VAR word-split read (PV dropped from UPATH).
        pytest.param('export X=" /etc/passwd"; V=$(cat ${TMPDIR:-/tmp}/$X); printf %s "$V"', id="poc-var-split-read"),
    ],
)
def test_codex_poc_bypasses_are_closed(command: str) -> None:
    """Every confirmed Codex bypass PoC must fall through to the real prompt."""
    result = _run(command)
    assert result == {}, f"{command!r} STILL ALLOWED — bypass reopened: {result}"


# ── Basic hook hygiene ────────────────────────────────────────────────────────


def test_non_bash_tool_passthrough() -> None:
    """Non-Bash tool payloads are ignored."""
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    proc = subprocess.run(["node", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_malformed_json_exits_zero() -> None:
    """Malformed stdin never crashes or blocks."""
    proc = subprocess.run(["node", str(HOOK)], input="not json", capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
