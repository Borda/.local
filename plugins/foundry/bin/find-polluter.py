#!/usr/bin/env python
"""find-polluter.py — binary-search test isolation.

Finds which test in a suite contaminates another test when run before it.
Uses binary search: O(log N) runs instead of O(N).

Usage (Claude Code plugin — CLAUDE_PLUGIN_ROOT is set automatically):
    python "${CLAUDE_PLUGIN_ROOT}/bin/find-polluter.py" <failing-test-id> [test-dir]

Arguments:
    failing-test-id   pytest node ID of the test that fails due to contamination
                      e.g. tests/test_foo.py::TestClass::test_method
    test-dir          directory to search for candidate tests (default: tests)

Example:
    python "${CLAUDE_PLUGIN_ROOT}/bin/find-polluter.py" tests/test_model.py::test_predict tests/

Requirements: pytest available on PATH (or via `python -m pytest`).

Exit codes:
    0   polluter found and reported
    1   validation failure (bad args, test passes when isolated, no candidates,
        or pytest unavailable)
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence

ISOLATION_PASS_RE = re.compile(r"^(PASSED|1 passed)", re.MULTILINE)
FAILURE_RE = re.compile(r"FAILED|ERROR")


def round_estimate(total: int) -> int:
    """Return upper bound on binary-search rounds for ``total`` candidates.

    Mirrors the bash version's ``ceil(log2(total + 1))`` formula.

    Args:
        total: Number of candidate tests (must be non-negative).

    Returns:
        Maximum number of binary-search rounds needed.

    Examples:
        >>> round_estimate(0)
        0
        >>> round_estimate(1)
        1
        >>> round_estimate(2)
        2
        >>> round_estimate(7)
        3
        >>> round_estimate(8)
        4
        >>> round_estimate(1000)
        10
    """
    if total < 0:
        raise ValueError(f"total must be non-negative, got {total}")
    if total == 0:
        return 0
    return math.ceil(math.log2(total + 1))


def binary_midpoint(lo: int, hi: int) -> int:
    """Return the integer midpoint between ``lo`` and ``hi``.

    Args:
        lo: Lower bound (inclusive).
        hi: Upper bound (exclusive).

    Returns:
        Floor of ``(lo + hi) / 2``.

    Examples:
        >>> binary_midpoint(0, 10)
        5
        >>> binary_midpoint(3, 7)
        5
        >>> binary_midpoint(0, 1)
        0
        >>> binary_midpoint(4, 5)
        4
        >>> binary_midpoint(0, 0)
        0
    """
    return (lo + hi) // 2


def _resolve_pytest_cmd() -> list[str] | None:
    """Locate the pytest executable; fall back to ``python -m pytest``.

    Returns:
        Argv prefix for invoking pytest, or ``None`` if pytest cannot be
        located.
    """
    pytest_bin = shutil.which("pytest")
    if pytest_bin:
        return [pytest_bin]
    # Fallback: try the running interpreter's pytest module.
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "pytest"]
    return None


def _run_pytest(pytest_cmd: Sequence[str], args: Sequence[str]) -> str:
    """Run pytest with ``args`` and return combined stdout+stderr text."""
    result = subprocess.run(
        [*pytest_cmd, *args],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return (result.stdout or "") + (result.stderr or "")


def passes_isolation(test_id: str, pytest_cmd: Sequence[str]) -> bool:
    """Return ``True`` when ``test_id`` passes when run in isolation.

    Args:
        test_id: pytest node ID of the candidate failing test.
        pytest_cmd: Argv prefix used to launch pytest.

    Returns:
        ``True`` if pytest output indicates the test passed; ``False``
        otherwise.
    """
    output = _run_pytest(pytest_cmd, [test_id, "-q", "--tb=short"])
    return bool(ISOLATION_PASS_RE.search(output))


def collect_candidates(
    test_dir: str,
    failing_test: str,
    pytest_cmd: Sequence[str],
) -> list[str]:
    """Collect candidate test node IDs, excluding the failing test itself.

    Args:
        test_dir: Directory to search for candidate tests.
        failing_test: pytest node ID to exclude from the candidate list.
        pytest_cmd: Argv prefix used to launch pytest.

    Returns:
        List of candidate node IDs (one per line of pytest collect output
        containing ``::``).
    """
    result = subprocess.run(
        [*pytest_cmd, test_dir, "--collect-only", "-q"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    # Mirror bash: `grep "::" | grep -v failing | grep -v ^$`. pytest writes
    # its collection lines to stdout; ignore stderr noise.
    candidates: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "::" not in stripped:
            continue
        if stripped == failing_test:
            continue
        candidates.append(stripped)
    return candidates


def _contaminates(
    batch: Sequence[str],
    failing_test: str,
    pytest_cmd: Sequence[str],
) -> bool:
    """Return ``True`` if running ``batch`` before ``failing_test`` fails it."""
    # Pass the batch via a tempfile (one test per line). pytest accepts
    # ``@filename`` for "args from file"; using a tempfile keeps the OS argv
    # cap from biting on large suites, mirroring bash's mktemp approach.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=True, encoding="utf-8") as batch_file:
        batch_file.write("\n".join(batch))
        batch_file.write("\n")
        batch_file.flush()
        args = [*batch, failing_test, "-q", "--tb=no"]
        output = _run_pytest(pytest_cmd, args)
    return bool(FAILURE_RE.search(output))


def binary_search(
    candidates: Sequence[str],
    failing_test: str,
    pytest_cmd: Sequence[str],
    log: object | None = None,
) -> tuple[str, int]:
    """Locate the polluting test via binary search.

    Args:
        candidates: Ordered list of candidate node IDs.
        failing_test: pytest node ID of the failing test.
        pytest_cmd: Argv prefix used to launch pytest.
        log: Stream for progress output; defaults to the *current* value of
            ``sys.stdout`` at call time (so test capture and stream redirection
            work correctly).

    Returns:
        Tuple of ``(polluter_node_id, rounds_used)``. Rounds is ``0`` when only
        a single candidate exists (no narrowing needed).

    Raises:
        ValueError: If ``candidates`` is empty.
    """
    if not candidates:
        raise ValueError("candidates must contain at least one test")

    stream = log if log is not None else sys.stdout
    lo = 0
    hi = len(candidates)
    rounds = 0

    while (hi - lo) > 1:
        rounds += 1
        mid = binary_midpoint(lo, hi)
        count = mid - lo
        print(
            f"  Round {rounds}: testing [{lo}–{mid}] ({count} tests)...",
            file=stream,
        )

        batch = list(candidates[lo:mid])
        if _contaminates(batch, failing_test, pytest_cmd):
            hi = mid  # polluter is in [lo, mid)
        else:
            lo = mid  # polluter is in [mid, hi)

    return candidates[lo], rounds


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: find-polluter.py <failing-test-id> [test-dir]\n\tExample: find-polluter.py tests/test_foo.py::test_bar tests/",
            file=sys.stderr,
        )
        return 1

    failing_test = args[0]
    test_dir = args[1] if len(args) > 1 else "tests"

    pytest_cmd = _resolve_pytest_cmd()
    if pytest_cmd is None:
        print("✗ pytest not found on PATH or via python -m pytest", file=sys.stderr)
        return 1

    # Step 1: verify the failing test passes in isolation.
    print(f"→ Checking {failing_test} in isolation...")
    if passes_isolation(failing_test, pytest_cmd):
        print("✓ Passes in isolation — test-ordering contamination confirmed")
    else:
        print(
            f"✗ {failing_test} fails in isolation — not a test-ordering issue\n\tFix the test itself before using this script.",
            file=sys.stderr,
        )
        return 1

    # Step 2: collect candidates.
    print(f"→ Collecting candidates from {test_dir}...")
    candidates = collect_candidates(test_dir, failing_test, pytest_cmd)
    total = len(candidates)
    if total == 0:
        print(f"✗ No candidate tests found in {test_dir}", file=sys.stderr)
        return 1

    rounds_upper = round_estimate(total)
    print(f"✓ Found {total} candidates — starting binary search (up to {rounds_upper} rounds)\n")

    # Step 3: binary search.
    polluter, rounds = binary_search(candidates, failing_test, pytest_cmd)

    # Step 4: report.
    pretty_cmd = " ".join(pytest_cmd)
    print(
        f"\n✓ Polluter found after {rounds} rounds:\n\n\t{polluter}\n\n"
        f'Verify with:\n\t{pretty_cmd} "{polluter}" "{failing_test}" -v\n\n'
        f"Next steps:\n"
        f"\t1. Run the verify command above to confirm\n"
        f"\t2. Check {polluter} for shared state mutation (module-level vars, fixtures, monkeypatches)\n"
        f"\t3. Add proper teardown or use pytest fixtures with 'function' scope to isolate the state"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
