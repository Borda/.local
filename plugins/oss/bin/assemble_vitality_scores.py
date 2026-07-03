#!/usr/bin/env python3
"""assemble_vitality_scores.py — merge 3 parallel axis-scoring partials into unified health score.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/assemble_vitality_scores.py" \\
        PARTIAL_A PARTIAL_B PARTIAL_C SCORING_FILE SCORES_FILE

Reads three partial JSON files (one per oss:repo-warden axis group A/B/C), loads
axis weights from the vitality-scoring.md rubric, renormalizes weights for
unavailable axes (score==null or label==⚪), and writes the assembled result to
SCORES_FILE.  Extracted from oss:analyse vitality Step 3 inline python -c block.

Exit codes:
    0  on success
    1  on wrong argument count, I/O error, or JSON parse error
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_DEFAULT_WEIGHTS: dict[int, float] = {
    1: 0.17,
    2: 0.18,
    3: 0.14,
    4: 0.11,
    5: 0.09,
    6: 0.07,
    7: 0.09,
    8: 0.07,
    9: 0.08,
}

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — F-10 guard against runaway reads


def _read_text_guarded(path: Path) -> str:
    """Read text file after enforcing a 10 MB size cap.

    Args:
        path: Filesystem path to read.

    Returns:
        File contents as string.

    Raises:
        ValueError: when file exceeds ``_MAX_FILE_SIZE`` bytes.

    Examples:
        >>> import tempfile, pathlib
        >>> tmp = pathlib.Path(tempfile.mktemp(suffix=".txt"))
        >>> _ = tmp.write_text("hello")
        >>> _read_text_guarded(tmp)
        'hello'
        >>> tmp.unlink()
    """
    if path.stat().st_size > _MAX_FILE_SIZE:
        raise ValueError(f"File too large ({path.stat().st_size} bytes): {path}")
    return path.read_text()


def load_weights(scoring_file: Path) -> dict[int, float]:
    """Load per-axis weights from the vitality-scoring.md rubric table.

    Parses lines of the form ``| N  axis-name | 0.XX |``.  Falls back to
    ``_DEFAULT_WEIGHTS`` when the file is absent or yields fewer than 9 entries.

    Args:
        scoring_file: Path to the vitality-scoring.md rubric file.

    Returns:
        Dict mapping axis number (1–9) to float weight.

    Examples:
        >>> import tempfile, pathlib
        >>> tmp = pathlib.Path(tempfile.mktemp(suffix=".md"))
        >>> _ = tmp.write_text("| 1 foo | 0.17 |\\n| 2 bar | 0.18 |\\n")
        >>> w = load_weights(tmp)
        >>> len(w)  # only 2 entries → fallback
        9
        >>> tmp.unlink()
    """
    weights: dict[int, float] = {}
    seen: set[int] = set()
    malformed = False
    try:
        for line in _read_text_guarded(scoring_file).splitlines():
            m = re.match(r"\|\s*(\d+)\s+[^|]+\|\s*(0\.\d+)\s*\|", line)
            if m:
                axis = int(m.group(1))
                if axis in seen:
                    malformed = True
                seen.add(axis)
                weights[axis] = float(m.group(2))
    except (OSError, ValueError):
        pass
    return weights if not malformed and set(weights) == set(_DEFAULT_WEIGHTS) else _DEFAULT_WEIGHTS.copy()


def assemble_scores(
    partial_a: Path,
    partial_b: Path,
    partial_c: Path,
    scoring_file: Path,
) -> dict:
    """Merge three axis-group partial JSON files into a unified vitality scores dict.

    Weights are renormalized over available axes only (unavailable = score is None
    or label is "⚪") so the health percentage remains meaningful even when data is
    missing for some axes.

    Args:
        partial_a: Group A partial JSON (axes 1, 2, 5, 6).
        partial_b: Group B partial JSON (axes 4, 7, 8).
        partial_c: Group C partial JSON (axes 3 → 9).
        scoring_file: vitality-scoring.md rubric for weight table.

    Returns:
        Assembled scores dict suitable for JSON serialization.

    Examples:
        No doctest — requires on-disk JSON fixtures; covered by pytest.
    """
    weights = load_weights(scoring_file)

    axes: dict[str, dict] = {}
    for path in (partial_a, partial_b, partial_c):
        d = json.loads(_read_text_guarded(path))
        axes.update(d["axes"])

    available = {k: v for k, v in axes.items() if v.get("label") != "⚪" and v.get("score") is not None}
    total_w = sum(weights[int(k)] for k in available)
    health = sum(weights[int(k)] * v["score"] / 10.0 for k, v in available.items()) / total_w * 100 if total_w else 0.0

    conf_vals = [v["conf"] for v in available.values() if v.get("conf", 0) > 0]
    overall_conf = sum(conf_vals) / len(conf_vals) if conf_vals else 0.0

    partial_c_data = json.loads(_read_text_guarded(partial_c))
    partial_a_data = json.loads(_read_text_guarded(partial_a))

    return {
        "analysis_now": partial_a_data["scored_at"],
        "health_score_pct": round(health, 1),
        "overall_confidence": round(overall_conf, 2),
        "axes": {str(k): v for k, v in axes.items()},
        "weights": {str(k): v for k, v in weights.items()},
        "axis3_weeks": partial_c_data.get("axis3_weeks"),
        "axis3_202_pending": any(
            axes.get(str(k), {}).get("label") == "⚪" and "stats" in axes.get(str(k), {}).get("unavailable_reason", "")
            for k in [3]
        ),
        "total_passes": 1,
        "confidence_history": str(round(overall_conf, 2)),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list override for testing. Defaults to sys.argv[1:].

    Returns:
        Exit code: 0 on success, 1 on error.

    Examples:
        No doctest — requires on-disk fixtures; covered by pytest.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 5:
        print(
            f"Usage: {sys.argv[0]} PARTIAL_A PARTIAL_B PARTIAL_C SCORING_FILE SCORES_FILE",
            file=sys.stderr,
        )
        return 1

    partial_a, partial_b, partial_c, scoring_file, scores_file = (Path(a) for a in args)

    try:
        result = assemble_scores(partial_a, partial_b, partial_c, scoring_file)
        scores_file.write_text(json.dumps(result, indent=2))
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"[vitality] assembled: health={result['health_score_pct']}% conf={result['overall_confidence']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
