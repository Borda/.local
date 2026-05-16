"""Tests for ``bin/find-polluter.py``.

Pure functions (``round_estimate``, ``binary_midpoint``) are covered by
``doctest`` in the source module; this file exercises subprocess-bound
behaviour via ``monkeypatch`` and ``capsys``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

# Test imports the module loaded by conftest.py — `find_polluter` is registered
# in `sys.modules` there via importlib.
import find_polluter  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess`` returned by mocks."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_run(monkeypatch: pytest.MonkeyPatch, responder):
    """Replace ``subprocess.run`` inside find_polluter with ``responder``."""
    monkeypatch.setattr(find_polluter.subprocess, "run", responder)


# ---------------------------------------------------------------------------
# round_estimate / binary_midpoint — pure helpers
# ---------------------------------------------------------------------------


def test_round_estimate_rejects_negative():
    """Pure function rejects nonsensical inputs explicitly."""
    with pytest.raises(ValueError):
        find_polluter.round_estimate(-1)


# ---------------------------------------------------------------------------
# passes_isolation
# ---------------------------------------------------------------------------


def test_passes_isolation_success(monkeypatch: pytest.MonkeyPatch):
    """`-q` summary ``1 passed`` → isolation check returns True."""

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="1 passed in 0.01s\n", returncode=0)

    _patch_run(monkeypatch, fake_run)
    assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"])


def test_passes_isolation_success_via_verbose_marker(
    monkeypatch: pytest.MonkeyPatch,
):
    """Verbose pytest line beginning ``PASSED`` also counts as isolation pass."""

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="PASSED tests/test_x.py::test_y\n", returncode=0)

    _patch_run(monkeypatch, fake_run)
    assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"])


def test_passes_isolation_failure(monkeypatch: pytest.MonkeyPatch):
    """Failure output (no PASSED/1 passed marker) → returns False."""

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(
            stdout="FAILED tests/test_x.py::test_y - AssertionError\n",
            returncode=1,
        )

    _patch_run(monkeypatch, fake_run)
    assert not find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"])


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


def test_collect_candidates_filters_failing_test(
    monkeypatch: pytest.MonkeyPatch,
):
    """Failing test, blank lines, and non-``::`` lines are stripped."""
    collected = (
        "tests/test_a.py::test_one\n"
        "tests/test_a.py::test_two\n"
        "tests/test_b.py::test_three\n"
        "\n"
        "3 tests collected in 0.02s\n"  # no `::` — filtered out
    )

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout=collected, returncode=0)

    _patch_run(monkeypatch, fake_run)
    candidates = find_polluter.collect_candidates(
        "tests",
        "tests/test_a.py::test_two",
        ["pytest"],
    )
    assert candidates == [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_three",
    ]


def test_collect_candidates_empty_when_only_failing_test(
    monkeypatch: pytest.MonkeyPatch,
):
    """When the failing test is the only collected item, candidates is empty."""

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="tests/test_a.py::only\n", returncode=0)

    _patch_run(monkeypatch, fake_run)
    assert find_polluter.collect_candidates("tests", "tests/test_a.py::only", ["pytest"]) == []


# ---------------------------------------------------------------------------
# binary_search
# ---------------------------------------------------------------------------


def test_binary_search_finds_polluter_in_first_half(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Polluter at index 1: binary search converges in O(log N) rounds."""
    candidates = [f"tests/test_x.py::t{i}" for i in range(8)]
    polluter_idx = 1

    def fake_run(argv: Sequence[str], **_: Any) -> _FakeCompleted:
        # The batch comes from argv between pytest_cmd and failing_test/flags.
        # Strip pytest_cmd prefix (["pytest"]) and trailing flags.
        # Easier: just look at which candidate strings appear before the
        # failing-test id ("FAIL").
        batch = [a for a in argv[1:] if a.startswith("tests/test_x.py::t")]
        if candidates[polluter_idx] in batch:
            return _FakeCompleted(stdout="FAILED something\n", returncode=1)
        return _FakeCompleted(stdout="ok\n", returncode=0)

    _patch_run(monkeypatch, fake_run)
    polluter, rounds = find_polluter.binary_search(candidates, "FAIL", ["pytest"])
    assert polluter == candidates[polluter_idx]
    # 8 candidates → at most ceil(log2(9)) = 4 rounds.
    assert 1 <= rounds <= 4

    out = capsys.readouterr().out
    assert "Round 1:" in out


def test_binary_search_single_candidate(monkeypatch: pytest.MonkeyPatch):
    """One candidate → no narrowing rounds; return that candidate directly."""

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:  # pragma: no cover
        raise AssertionError("subprocess.run should not be called for 1 candidate")

    _patch_run(monkeypatch, fake_run)
    polluter, rounds = find_polluter.binary_search(["tests/test_solo.py::test_one"], "FAIL", ["pytest"])
    assert polluter == "tests/test_solo.py::test_one"
    assert rounds == 0


def test_binary_search_rejects_empty():
    """Empty candidate list is a programmer error — raise immediately."""
    with pytest.raises(ValueError):
        find_polluter.binary_search([], "FAIL", ["pytest"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_no_args_exits_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Calling main with no args prints usage to stderr and returns 1."""
    rc = find_polluter.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Usage:" in err


def test_main_reports_polluter_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Drive main() through every step using a contamination-faking responder."""
    failing = "tests/test_z.py::test_fail"
    polluter = "tests/test_a.py::test_one"
    other = "tests/test_b.py::test_two"

    # Stub pytest resolution so we don't depend on the environment.
    monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

    state = {"call": 0}

    def fake_run(argv: Sequence[str], **_: Any) -> _FakeCompleted:
        state["call"] += 1
        # 1st call: isolation check (failing test alone) — must show passed.
        if "--tb=short" in argv:
            return _FakeCompleted(stdout="1 passed in 0.01s\n", returncode=0)
        # 2nd call: --collect-only — return our two candidates plus the failing.
        if "--collect-only" in argv:
            return _FakeCompleted(stdout=f"{polluter}\n{other}\n{failing}\n", returncode=0)
        # Subsequent calls: binary-search batches. Contamination occurs whenever
        # the polluter appears in the batch.
        if polluter in argv:
            return _FakeCompleted(stdout="FAILED in batch\n", returncode=1)
        return _FakeCompleted(stdout="all green\n", returncode=0)

    _patch_run(monkeypatch, fake_run)
    rc = find_polluter.main([failing, "tests"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "✓ Passes in isolation" in captured.out
    assert "Polluter found" in captured.out
    assert polluter in captured.out


def test_main_exits_1_when_isolation_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """If the failing test does not pass alone, exit 1 with guidance."""
    monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

    def fake_run(_argv: Sequence[str], **_: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="FAILED\n", returncode=1)

    _patch_run(monkeypatch, fake_run)
    rc = find_polluter.main(["tests/test_a.py::test_one"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "fails in isolation" in err


def test_main_exits_1_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Empty candidate set after exclusion → exit 1."""
    monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

    failing = "tests/test_z.py::test_only"

    def fake_run(argv: Sequence[str], **_: Any) -> _FakeCompleted:
        if "--tb=short" in argv:
            return _FakeCompleted(stdout="1 passed in 0.01s\n", returncode=0)
        if "--collect-only" in argv:
            # Only the failing test collected — nothing left after filter.
            return _FakeCompleted(stdout=f"{failing}\n", returncode=0)
        raise AssertionError("should not reach binary search")

    _patch_run(monkeypatch, fake_run)
    rc = find_polluter.main([failing])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No candidate tests found" in err


def test_main_exits_1_when_pytest_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """pytest not resolvable → exit 1 with clear message, no subprocess calls."""
    monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: None)

    def boom(*_: Any, **__: Any) -> _FakeCompleted:  # pragma: no cover
        raise AssertionError("subprocess.run must not be called")

    _patch_run(monkeypatch, boom)
    rc = find_polluter.main(["tests/test_a.py::test_one"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pytest not found" in err
