"""Tests for assemble_vitality_scores.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assemble_vitality_scores import assemble_scores, load_weights, main


def _axis(score: float | None = 7.0, conf: float = 0.9, label: str = "🟢", signal: str = "ok") -> dict:
    return {"score": score, "conf": conf, "label": label, "signal": signal}


def _write_partial(
    tmp_path: Path, name: str, axes: dict, scored_at: str = "1700000000", extra: dict | None = None
) -> Path:
    p = tmp_path / name
    data: dict = {"axes": axes, "scored_at": scored_at}
    if extra:
        data.update(extra)
    p.write_text(json.dumps(data))
    return p


@pytest.fixture()
def partials(tmp_path: Path) -> tuple[Path, Path, Path]:
    pa = _write_partial(tmp_path, "a.json", {str(k): _axis() for k in [1, 2, 5, 6]})
    pb = _write_partial(tmp_path, "b.json", {str(k): _axis() for k in [4, 7, 8]})
    pc = _write_partial(
        tmp_path,
        "c.json",
        {str(k): _axis() for k in [3, 9]},
        extra={"axis3_weeks": 52},
    )
    return pa, pb, pc


@pytest.fixture()
def scoring_file(tmp_path: Path) -> Path:
    lines = "\n".join(
        f"| {n} axis-{n} | {w} |"
        for n, w in [(1, 0.17), (2, 0.18), (3, 0.14), (4, 0.11), (5, 0.09), (6, 0.07), (7, 0.09), (8, 0.07), (9, 0.08)]
    )
    p = tmp_path / "vitality-scoring.md"
    p.write_text(lines)
    return p


class TestLoadWeights:
    def test_parses_all_nine(self, scoring_file: Path) -> None:
        w = load_weights(scoring_file)
        assert len(w) == 9
        assert w[1] == pytest.approx(0.17)
        assert w[9] == pytest.approx(0.08)

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        w = load_weights(tmp_path / "missing.md")
        assert len(w) == 9
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_incomplete_file_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.md"
        p.write_text("| 1 foo | 0.17 |\n")
        w = load_weights(p)
        assert len(w) == 9  # fallback — only 1 entry parsed


class TestAssembleScores:
    def test_basic_assembly(self, partials: tuple, scoring_file: Path, tmp_path: Path) -> None:
        pa, pb, pc = partials
        result = assemble_scores(pa, pb, pc, scoring_file)
        assert "health_score_pct" in result
        assert 0.0 <= result["health_score_pct"] <= 100.0
        assert result["overall_confidence"] > 0.0
        assert len(result["axes"]) == 9

    def test_all_axes_present(self, partials: tuple, scoring_file: Path) -> None:
        pa, pb, pc = partials
        result = assemble_scores(pa, pb, pc, scoring_file)
        for n in range(1, 10):
            assert str(n) in result["axes"]

    def test_unavailable_axis_renormalization(self, tmp_path: Path, scoring_file: Path) -> None:
        pa = _write_partial(tmp_path, "a.json", {str(k): _axis() for k in [1, 2, 5, 6]})
        pb = _write_partial(tmp_path, "b.json", {str(k): _axis() for k in [4, 7, 8]})
        # Axis 3 unavailable (⚪, no score)
        pc = _write_partial(
            tmp_path,
            "c.json",
            {
                "3": {"score": None, "conf": 0.0, "label": "⚪", "signal": "", "unavailable_reason": "stats 202"},
                "9": _axis(),
            },
            extra={"axis3_weeks": None},
        )
        result = assemble_scores(pa, pb, pc, scoring_file)
        # health_score_pct still valid — axis3 weight renormalized out
        assert result["health_score_pct"] > 0.0
        assert result["axis3_202_pending"] is True

    def test_axis3_202_pending_flag_false(self, partials: tuple, scoring_file: Path) -> None:
        pa, pb, pc = partials
        result = assemble_scores(pa, pb, pc, scoring_file)
        assert result["axis3_202_pending"] is False

    def test_scored_at_from_partial_a(self, partials: tuple, scoring_file: Path) -> None:
        pa, pb, pc = partials
        result = assemble_scores(pa, pb, pc, scoring_file)
        assert result["analysis_now"] == "1700000000"

    def test_axis3_weeks_from_partial_c(self, partials: tuple, scoring_file: Path) -> None:
        pa, pb, pc = partials
        result = assemble_scores(pa, pb, pc, scoring_file)
        assert result["axis3_weeks"] == 52


class TestMain:
    def test_success(self, partials: tuple, scoring_file: Path, tmp_path: Path, capsys) -> None:
        pa, pb, pc = partials
        scores_file = tmp_path / "scores.json"
        rc = main([str(pa), str(pb), str(pc), str(scoring_file), str(scores_file)])
        assert rc == 0
        assert scores_file.exists()
        out = capsys.readouterr().out
        assert "[vitality] assembled:" in out

    def test_wrong_arg_count(self, capsys) -> None:
        rc = main(["a", "b"])
        assert rc == 1

    def test_missing_partial(self, tmp_path: Path, scoring_file: Path, capsys) -> None:
        scores_file = tmp_path / "scores.json"
        rc = main(["/no/such/a.json", "/no/b.json", "/no/c.json", str(scoring_file), str(scores_file)])
        assert rc == 1
