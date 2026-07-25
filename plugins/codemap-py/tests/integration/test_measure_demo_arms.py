"""Tests for measure_demo_arms.py — the measured (not self-reported) demo A/B cost.

The script replaces each arm's self-reported b/g/r/sq counts with a measured token
proxy read from the telemetry shards: scan-query calls from cli_<session>.jsonl and
Grep/Read/Glob calls + target volume from tools_<session>.jsonl, attributed per arm by
session id. The report-header confidence is capped by the declared correctness signal:
ground_truth ≤ 0.9, agreement ≤ 0.7, plumbing ≤ 0.5 — and any run missing measured
records for an arm falls back to the plumbing cap. These tests pin those accept criteria.

conftest.py puts bin/ on sys.path, so the module imports directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import measure_demo_arms as mda


def _cli(session: str, cmd: str = "central") -> dict:
    """Build a cli.jsonl record: one scan-query subcommand call under *session*."""
    return {"ts": "2026-07-10T01:00:00Z", "layer": "cli", "cmd": cmd, "session": session, "argv": [cmd]}


def _tool(session: str, target: str, *, tool: str = "Grep") -> dict:
    """Build a tools.jsonl record: one *tool* call on *target* under *session*."""
    return {"ts": "2026-07-10T01:00:00Z", "layer": "tool", "tool": tool, "session": session, "target": target}


class TestTokens:
    """The token proxy weights each call class and folds in target volume (chars / 4)."""

    @pytest.mark.parametrize(
        ("sq", "tools", "chars", "expected"),
        [
            pytest.param(0, 0, 0, 0, id="empty"),
            pytest.param(1, 0, 0, mda.SQ_CALL_TOKENS, id="one-sq"),
            pytest.param(0, 1, 0, mda.TOOL_CALL_TOKENS, id="one-tool"),
            pytest.param(0, 0, 40, 10, id="target-volume-only"),
            pytest.param(2, 3, 80, 2 * mda.SQ_CALL_TOKENS + 3 * mda.TOOL_CALL_TOKENS + 20, id="mixed"),
        ],
    )
    def test_token_proxy(self, sq: int, tools: int, chars: int, expected: int) -> None:
        """Token proxy = sq*SQ_CALL + tool*TOOL_CALL + target_chars // CHARS_PER_TOKEN."""
        assert mda._tokens(sq, tools, chars) == expected


class TestMeasureArm:
    """Per-arm measurement filters shard records to the arm's session, then counts."""

    def test_counts_only_matching_session(self) -> None:
        """Records from another session never contribute to this arm's cost."""
        cli = [_cli("plain"), _cli("codemap")]
        tools = [_tool("plain", "import a"), _tool("codemap", "b")]

        cost = mda.measure_arm("plain", cli, tools)

        assert cost.sq_calls == 1
        assert cost.tool_calls == 1
        assert cost.target_chars == len("import a")

    def test_sums_target_volume_across_calls(self) -> None:
        """target_chars is the summed length of every matching tool call's target."""
        tools = [_tool("s", "aa"), _tool("s", "bbb"), _tool("s", "c")]

        cost = mda.measure_arm("s", [], tools)

        assert cost.tool_calls == 3
        assert cost.target_chars == 6

    def test_absent_session_is_zero_cost(self) -> None:
        """A session with no records measures as zero across every field."""
        cost = mda.measure_arm("ghost", [_cli("other")], [_tool("other", "x")])

        assert (cost.sq_calls, cost.tool_calls, cost.target_chars, cost.tokens) == (0, 0, 0, 0)


class TestConfidenceFor:
    """Confidence is capped by signal type, and by plumbing when an arm is unmeasured."""

    @pytest.mark.parametrize(
        ("signal", "expected"),
        [
            pytest.param("ground_truth", 0.9, id="ground-truth"),
            pytest.param("agreement", 0.7, id="agreement"),
            pytest.param("plumbing", 0.5, id="plumbing"),
        ],
    )
    def test_cap_by_signal_when_both_measured(self, signal: str, expected: float) -> None:
        """With both arms measured, the cap is exactly the signal's ceiling."""
        assert mda.confidence_for(signal, both_arms_measured=True) == expected

    @pytest.mark.parametrize(
        "signal",
        [
            pytest.param("ground_truth", id="ground-truth"),
            pytest.param("agreement", id="agreement"),
        ],
    )
    def test_unmeasured_arm_falls_back_to_plumbing_cap(self, signal: str) -> None:
        """No measured records for an arm caps the run at the plumbing ceiling regardless of signal."""
        assert mda.confidence_for(signal, both_arms_measured=False) == 0.5


class TestMainCli:
    """End-to-end CLI: shard resolution, signal-driven cap, JSON output, exit contract."""

    @staticmethod
    def _write_shards(log_dir: Path, cli_records: list[dict], tool_records: list[dict]) -> None:
        """Write cli/tools shards under *log_dir* for the --logs resolution path."""
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "cli_s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in cli_records))
        (log_dir / "tools_s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in tool_records))

    def test_ground_truth_run_reports_measured_totals_and_cap(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A ground-truth run with both arms measured reports per-arm tokens and caps at 0.9."""
        log_dir = tmp_path / "logs"
        self._write_shards(
            log_dir,
            [_cli("codemap"), _cli("codemap")],
            [_tool("plain", "import requests.models"), _tool("plain", "grep -r Session")],
        )

        code = mda.main(
            [
                "--logs",
                str(log_dir),
                "--plain-session",
                "plain",
                "--codemap-session",
                "codemap",
                "--signal",
                "ground_truth",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["signal_type"] == "ground_truth"
        assert payload["confidence"] == 0.9
        assert payload["codemap"]["sq_calls"] == 2
        assert payload["plain"]["tool_calls"] == 2

    def test_agreement_run_caps_at_0_7(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """An agreement run with both arms measured caps at 0.7 (consistency, not accuracy)."""
        log_dir = tmp_path / "logs"
        self._write_shards(log_dir, [_cli("codemap")], [_tool("plain", "x")])

        code = mda.main(
            [
                "--logs",
                str(log_dir),
                "--plain-session",
                "plain",
                "--codemap-session",
                "codemap",
                "--signal",
                "agreement",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["signal_type"] == "agreement"
        assert payload["confidence"] == 0.7

    def test_unmeasured_arm_downgrades_to_plumbing(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """When the codemap arm produced no records, the run downgrades to plumbing (0.5)."""
        log_dir = tmp_path / "logs"
        self._write_shards(log_dir, [], [_tool("plain", "x")])

        code = mda.main(
            [
                "--logs",
                str(log_dir),
                "--plain-session",
                "plain",
                "--codemap-session",
                "codemap",
                "--signal",
                "ground_truth",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["signal_type"] == "plumbing"
        assert payload["confidence"] == 0.5

    def test_text_output_names_signal_and_confidence(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Default text output labels the measured signal type and the capped confidence."""
        log_dir = tmp_path / "logs"
        self._write_shards(log_dir, [_cli("codemap")], [_tool("plain", "x")])

        code = mda.main(
            [
                "--logs",
                str(log_dir),
                "--plain-session",
                "plain",
                "--codemap-session",
                "codemap",
                "--signal",
                "agreement",
            ]
        )
        out = capsys.readouterr().out

        assert code == 0
        assert "signal: agreement (measured)" in out
        assert "capped confidence: 0.7" in out

    def test_missing_required_arg_exits_2(self) -> None:
        """Omitting a required argument is a usage error (argparse exits 2)."""
        with pytest.raises(SystemExit) as exc:
            mda.main(["--logs", "x", "--plain-session", "p", "--codemap-session", "c"])
        assert exc.value.code == 2

    def test_unknown_signal_exits_2(self) -> None:
        """An unknown --signal value is rejected by argparse choices (exit 2)."""
        with pytest.raises(SystemExit) as exc:
            mda.main(["--logs", "x", "--plain-session", "p", "--codemap-session", "c", "--signal", "bogus"])
        assert exc.value.code == 2
