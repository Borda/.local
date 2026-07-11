"""CLI/security tests for hyphenated ``test_find-polluter.py`` collection.

Covers:
* ``_is_safe_node_id`` — shell metacharacter rejection (SEC-F-1 security)
* ``round_estimate`` — pure-function boundary values and ValueError on negative
* ``binary_midpoint`` — pure-function floor-division correctness
* ``passes_isolation`` — subprocess output patterns → True / False
* ``collect_candidates`` — failing test excluded, blank/non-:: lines stripped,
  unsafe node IDs dropped with stderr warning (SEC-F-1 runtime path)
* ``binary_search`` — convergence, single-candidate shortcut, empty-list rejection,
  custom log stream
* ``main()`` — no-args usage, unsafe node ID, pytest missing, isolation failure,
  no candidates, path traversal rejection, polluter found (happy path),
  default test-dir

The companion ``test_find_polluter.py`` owns the core helper/unit matrix. This
file intentionally preserves coverage for the historical hyphenated test module
path plus CLI/security regressions such as traversal rejection.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

# find_polluter is loaded by conftest.py via importlib (bin/find-polluter.py
# has a hyphen; conftest replaces hyphens with underscores in sys.modules).
import find_polluter


class _FakeResult:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        """Initialise fake subprocess result."""
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_run(monkeypatch: pytest.MonkeyPatch, responder: Any) -> None:
    """Replace ``subprocess.run`` inside the module under test."""
    monkeypatch.setattr(find_polluter.subprocess, "run", responder)


def _read_batch(argv: Sequence[str], prefix: str) -> list[str]:
    """Return batch node IDs the module passed to pytest via ``@file`` args-from-file.

    ``_contaminates`` writes the candidate batch to a tempfile and hands pytest a
    single ``@<path>`` token instead of expanding the batch onto argv (argv-cap
    safety). Mirror pytest's args-from-file resolution: read the referenced file
    and keep the lines matching ``prefix``.
    """
    for token in argv[1:]:
        if token.startswith("@"):
            content = Path(token[1:]).read_text(encoding="utf-8")
            return [line for line in content.splitlines() if line.startswith(prefix)]
    return []


# ---------------------------------------------------------------------------
# _is_safe_node_id
# ---------------------------------------------------------------------------


class TestIsSafeNodeId:
    """_is_safe_node_id: shell metacharacter rejection (SEC-F-1)."""

    @pytest.mark.parametrize(
        "node_id",
        [
            "tests/test_foo.py::test_bar",
            "tests/test_foo.py::TestClass::test_method",
            "tests/test_foo.py::test_bar[param-1]",
            "tests/test_foo.py::test_bar[a-b-c]",
            "a/b/c.py::t",
        ],
    )
    def test_safe_ids_accepted(self, node_id: str) -> None:
        """Standard pytest node IDs without metacharacters are accepted."""
        assert find_polluter._is_safe_node_id(node_id) is True

    @pytest.mark.parametrize(
        "node_id",
        [
            "",
            "tests/test_foo.py::test_bar; rm -rf /",
            "tests/$(whoami).py::test_bar",
            "tests/test_foo.py::test_bar | cat /etc/passwd",
            "tests/test_foo.py::test_bar`id`",
            "tests/test_foo.py::test_bar\necho injected",
            "tests/test_foo.py::test_bar\t",
            "tests/test_foo.py::test_bar<file",
            "tests/test_foo.py::test_bar>file",
            "tests/test_foo.py::test_bar\\path",
            'tests/test_foo.py::test_bar"quoted"',
            "tests/test_foo.py::test_bar'quoted'",
            "tests/test_foo.py::test_bar(call)",
            "tests/test_foo.py::test_bar&background",
            "tests/test_foo.py::test_bar$VAR",
        ],
    )
    def test_unsafe_ids_rejected(self, node_id: str) -> None:
        """Node IDs containing shell metacharacters or empty string are rejected."""
        assert find_polluter._is_safe_node_id(node_id) is False


# ---------------------------------------------------------------------------
# round_estimate
# ---------------------------------------------------------------------------


class TestRoundEstimate:
    """round_estimate: ceil(log2(total+1)) boundary values."""

    @pytest.mark.parametrize(
        ("total", "expected"),
        [
            (0, 0),
            (1, 1),
            (2, 2),
            (7, 3),
            (8, 4),
            (1000, 10),
        ],
    )
    def test_known_values(self, total: int, expected: int) -> None:
        """round_estimate returns documented examples verbatim."""
        assert find_polluter.round_estimate(total) == expected

    def test_rejects_negative(self) -> None:
        """round_estimate raises ValueError for negative totals."""
        with pytest.raises(ValueError, match="non-negative"):
            find_polluter.round_estimate(-1)


# ---------------------------------------------------------------------------
# binary_midpoint
# ---------------------------------------------------------------------------


class TestBinaryMidpoint:
    """binary_midpoint: floor((lo+hi)/2) for documented examples."""

    @pytest.mark.parametrize(
        ("lo", "hi", "expected"),
        [
            (0, 10, 5),
            (3, 7, 5),
            (0, 1, 0),
            (4, 5, 4),
            (0, 0, 0),
        ],
    )
    def test_known_values(self, lo: int, hi: int, expected: int) -> None:
        """binary_midpoint returns floor of arithmetic midpoint."""
        assert find_polluter.binary_midpoint(lo, hi) == expected


# ---------------------------------------------------------------------------
# passes_isolation
# ---------------------------------------------------------------------------


class TestPassesIsolation:
    """passes_isolation: subprocess output patterns → True / False."""

    def test_summary_1_passed_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'-q' summary '1 passed' confirms isolation."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="1 passed in 0.01s\n")

        _patch_run(monkeypatch, fake_run)
        assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"]) is True

    def test_verbose_passed_marker_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Line-initial 'PASSED' also counts as isolation pass."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="PASSED tests/test_x.py::test_y\n")

        _patch_run(monkeypatch, fake_run)
        assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"]) is True

    def test_failed_output_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FAILED marker means isolation not confirmed."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="FAILED tests/test_x.py::test_y\n", returncode=1)

        _patch_run(monkeypatch, fake_run)
        assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"]) is False

    def test_empty_output_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No recognizable markers in output returns False."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="", returncode=1)

        _patch_run(monkeypatch, fake_run)
        assert find_polluter.passes_isolation("tests/test_x.py::test_y", ["pytest"]) is False


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


class TestCollectCandidates:
    """collect_candidates: filtering rules and SEC-F-1 unsafe-node-ID drop."""

    def test_filters_failing_test_and_noise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Failing test itself, blank lines, and non-:: lines are excluded."""
        stdout = "tests/test_a.py::t1\ntests/test_a.py::t2\ntests/test_b.py::t3\n\n3 tests collected\n"

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout=stdout)

        _patch_run(monkeypatch, fake_run)
        result = find_polluter.collect_candidates("tests", "tests/test_a.py::t2", ["pytest"])
        assert result == ["tests/test_a.py::t1", "tests/test_b.py::t3"]

    def test_returns_empty_when_only_failing_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Candidate list is empty when failing test is the sole collected item."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="tests/test_only.py::solo\n")

        _patch_run(monkeypatch, fake_run)
        result = find_polluter.collect_candidates("tests", "tests/test_only.py::solo", ["pytest"])
        assert result == []

    def test_unsafe_node_ids_dropped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unsafe node IDs are silently dropped; a warning is written to stderr."""
        hostile = "tests/test_x.py::evil; rm -rf /"
        safe = "tests/test_safe.py::ok"
        stdout = f"{hostile}\n{safe}\n"

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout=stdout)

        _patch_run(monkeypatch, fake_run)
        result = find_polluter.collect_candidates("tests", "tests/other.py::other", ["pytest"])
        assert safe in result
        assert hostile not in result
        err = capsys.readouterr().err
        assert "unsafe" in err.lower()

    def test_empty_collection_output_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All-blank pytest --collect-only output returns empty candidate list."""

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="\n\n\n")

        _patch_run(monkeypatch, fake_run)
        result = find_polluter.collect_candidates("tests", "tests/x.py::y", ["pytest"])
        assert result == []


# ---------------------------------------------------------------------------
# binary_search
# ---------------------------------------------------------------------------


class TestBinarySearch:
    """binary_search: convergence, single-candidate shortcut, empty-list rejection, log stream."""

    def test_finds_polluter_in_first_half(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Polluter at index 1 among 8 candidates is found within O(log N) rounds."""
        candidates = [f"tests/test_x.py::t{i}" for i in range(8)]
        polluter_idx = 1

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            batch = _read_batch(argv, "tests/test_x.py::t")
            if candidates[polluter_idx] in batch:
                return _FakeResult(stdout="FAILED\n", returncode=1)
            return _FakeResult(stdout="ok\n")

        _patch_run(monkeypatch, fake_run)
        polluter, rounds = find_polluter.binary_search(candidates, "FAIL_TARGET", ["pytest"])
        assert polluter == candidates[polluter_idx]
        assert 1 <= rounds <= 4
        assert "Round 1:" in capsys.readouterr().out

    def test_single_candidate_no_subprocess_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Single candidate is returned immediately without any subprocess call."""

        def boom(*_: Any, **__: Any) -> _FakeResult:  # pragma: no cover
            raise AssertionError("subprocess.run must not be called for 1 candidate")

        _patch_run(monkeypatch, boom)
        polluter, rounds = find_polluter.binary_search(["tests/test_solo.py::only"], "FAIL", ["pytest"])
        assert polluter == "tests/test_solo.py::only"
        assert rounds == 0

    def test_empty_candidates_raises_value_error(self) -> None:
        """Empty candidate list raises ValueError immediately."""
        with pytest.raises(ValueError, match="at least one"):
            find_polluter.binary_search([], "FAIL", ["pytest"])

    def test_log_stream_receives_round_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Round progress is written to the supplied log stream, not stdout."""
        candidates = [f"tests/t.py::t{i}" for i in range(4)]

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="FAILED\n", returncode=1)

        _patch_run(monkeypatch, fake_run)
        log = StringIO()
        find_polluter.binary_search(candidates, "FAIL", ["pytest"], log=log)
        assert "Round" in log.getvalue()

    def test_finds_polluter_in_second_half(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Polluter at last index among 4 candidates is correctly found."""
        candidates = [f"tests/t.py::t{i}" for i in range(4)]
        polluter_idx = 3

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            batch = _read_batch(argv, "tests/t.py::t")
            if candidates[polluter_idx] in batch:
                return _FakeResult(stdout="FAILED\n", returncode=1)
            return _FakeResult(stdout="ok\n")

        _patch_run(monkeypatch, fake_run)
        log = StringIO()
        polluter, _rounds = find_polluter.binary_search(candidates, "FAIL", ["pytest"], log=log)
        assert polluter == candidates[polluter_idx]


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    """main(): end-to-end CLI exercising all documented exit paths."""

    def test_no_args_prints_usage_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No arguments → usage on stderr and return code 1."""
        rc = find_polluter.main([])
        assert rc == 1
        assert "Usage:" in capsys.readouterr().err

    def test_unsafe_failing_test_id_rejected_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Failing-test node ID with shell metacharacters is rejected with exit 1."""
        rc = find_polluter.main(["tests/test_x.py::evil; rm -rf /"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "rejected" in err.lower() or "metacharacter" in err.lower()

    def test_pytest_missing_exits_1(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """pytest not resolvable → exit 1 with descriptive message."""
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: None)
        rc = find_polluter.main(["tests/test_a.py::test_one"])
        assert rc == 1
        assert "pytest not found" in capsys.readouterr().err

    def test_isolation_failure_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test failing in isolation → exit 1 with fix guidance."""
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

        def fake_run(_argv: Sequence[str], **_kw: Any) -> _FakeResult:
            return _FakeResult(stdout="FAILED\n", returncode=1)

        _patch_run(monkeypatch, fake_run)
        rc = find_polluter.main(["tests/test_a.py::test_bad"])
        assert rc == 1
        assert "fails in isolation" in capsys.readouterr().err

    def test_no_candidates_exits_1(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """Zero candidates after exclusion → exit 1 with 'No candidate tests found'."""
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])
        failing = "tests/test_z.py::only"

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            if "--tb=short" in argv:
                return _FakeResult(stdout="1 passed in 0.01s\n")
            if "--collect-only" in argv:
                return _FakeResult(stdout=f"{failing}\n")
            raise AssertionError("should not reach binary search")

        _patch_run(monkeypatch, fake_run)
        rc = find_polluter.main([failing])
        assert rc == 1
        assert "No candidate tests found" in capsys.readouterr().err

    def test_path_traversal_test_dir_rejected_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """test_dir escaping project root is rejected with security message and exit 1."""
        rc = find_polluter.main(["tests/test_x.py::test_ok", "../../etc"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "SECURITY" in err or "project root" in err.lower()

    def test_polluter_found_returns_0_with_report(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Full happy path: polluter identified, report printed, return code 0."""
        failing = "tests/test_z.py::fail"
        polluter = "tests/test_a.py::one"
        other = "tests/test_b.py::two"
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            if "--tb=short" in argv:
                return _FakeResult(stdout="1 passed in 0.01s\n")
            if "--collect-only" in argv:
                return _FakeResult(stdout=f"{polluter}\n{other}\n{failing}\n")
            if polluter in _read_batch(argv, "tests/"):
                return _FakeResult(stdout="FAILED\n", returncode=1)
            return _FakeResult(stdout="ok\n")

        _patch_run(monkeypatch, fake_run)
        rc = find_polluter.main([failing, "tests"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Polluter found" in out
        assert polluter in out

    def test_default_test_dir_is_tests(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Omitting test-dir defaults to 'tests' directory."""
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])
        collected_dirs: list[str] = []

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            if "--tb=short" in argv:
                return _FakeResult(stdout="1 passed in 0.01s\n")
            if "--collect-only" in argv:
                collected_dirs.extend(a for a in argv if not a.startswith("-") and a != "pytest")
                return _FakeResult(stdout="")
            return _FakeResult(stdout="ok\n")

        _patch_run(monkeypatch, fake_run)
        find_polluter.main(["tests/test_z.py::fail"])
        assert "tests" in collected_dirs

    def test_report_includes_verify_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Happy path stdout includes 'Verify with:' guidance block."""
        failing = "tests/test_z.py::fail"
        polluter = "tests/test_a.py::one"
        monkeypatch.setattr(find_polluter, "_resolve_pytest_cmd", lambda: ["pytest"])

        def fake_run(argv: Sequence[str], **_kw: Any) -> _FakeResult:
            if "--tb=short" in argv:
                return _FakeResult(stdout="1 passed in 0.01s\n")
            if "--collect-only" in argv:
                return _FakeResult(stdout=f"{polluter}\n{failing}\n")
            if polluter in _read_batch(argv, "tests/"):
                return _FakeResult(stdout="FAILED\n", returncode=1)
            return _FakeResult(stdout="ok\n")

        _patch_run(monkeypatch, fake_run)
        find_polluter.main([failing, "tests"])
        out = capsys.readouterr().out
        assert "Verify with:" in out
        assert "Next steps:" in out
