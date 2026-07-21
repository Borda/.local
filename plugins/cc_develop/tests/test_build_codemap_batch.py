"""Tests for ``build_codemap_batch.py``.

Covers:
    - ``build_batch_request``: central-first ordering, seven queries per module,
      ``uncovered`` flag placement, empty-module request.
    - ``main()`` entry point: batch JSON written + modules printed (diff monkeypatched),
      bad-arg exit code.
"""

from __future__ import annotations

import json

import pytest

import build_codemap_batch as bcb


# ---------- Pure request builder ----------


class TestBuildBatchRequest:
    """``build_batch_request`` assembles the ordered scan-query batch array."""

    def test_central_always_first_and_alone_when_no_modules(self):
        """Empty module list yields exactly the central query."""
        assert bcb.build_batch_request([]) == [{"cmd": "central", "args": ["--top", "5"]}]

    def test_seven_queries_per_module_in_order(self):
        """Each module contributes the seven pre-flight queries after central."""
        req = bcb.build_batch_request(["pkg.mod"])
        assert len(req) == 1 + 7
        assert [item["cmd"] for item in req[1:]] == [
            "rdeps",
            "fn-rdeps",
            "fn-blast",
            "mock-rdeps",
            "uncovered",
            "xrefs",
            "undocumented",
        ]

    @pytest.mark.parametrize(
        ("index", "expected_args"),
        [
            pytest.param(1, ["pkg.mod"], id="rdeps-module-only"),
            pytest.param(2, ["pkg.mod", "--exclude-tests"], id="fn-rdeps-flag-after-module"),
            pytest.param(5, ["--top", "20", "pkg.mod"], id="uncovered-flags-before-module"),
            pytest.param(6, ["pkg.mod", "--broken"], id="xrefs-flag-after-module"),
        ],
    )
    def test_argument_placement(self, index, expected_args):
        """Flags precede the module only for ``uncovered``; other queries append them."""
        req = bcb.build_batch_request(["pkg.mod"])
        assert req[index]["args"] == expected_args

    def test_two_modules_grouped_per_module(self):
        """Queries stay grouped per module: all seven for the first, then the second."""
        req = bcb.build_batch_request(["a.one", "b.two"])
        assert len(req) == 1 + 14
        first_block = [item for item in req[1:8]]
        assert all("a.one" in item["args"] for item in first_block)
        assert all("b.two" in item["args"] for item in req[8:])


# ---------- main() entry point ----------


class TestMain:
    """``main`` writes the request file and prints derived modules."""

    def test_writes_json_and_prints_modules(self, tmp_path, monkeypatch, capsys):
        """Monkeypatched diff yields modules → JSON on disk + stdout list, exit 0."""
        monkeypatch.setattr(bcb, "_git_diff_files", lambda: ["src/pkg/mod.py"])
        out = tmp_path / "batch.json"
        rc = bcb.main([str(out)])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "pkg.mod"
        req = json.loads(out.read_text(encoding="utf-8"))
        assert req[0] == {"cmd": "central", "args": ["--top", "5"]}
        assert len(req) == 8

    def test_no_changed_files_still_writes_central_request(self, tmp_path, monkeypatch, capsys):
        """Empty diff → central-only request, empty stdout line, exit 0."""
        monkeypatch.setattr(bcb, "_git_diff_files", lambda: [])
        out = tmp_path / "batch.json"
        assert bcb.main([str(out)]) == 0
        assert capsys.readouterr().out.strip() == ""
        assert json.loads(out.read_text(encoding="utf-8")) == [{"cmd": "central", "args": ["--top", "5"]}]

    def test_missing_argument_exits_1(self, capsys):
        """No output path → usage on stderr, exit 1, nothing written."""
        assert bcb.main([]) == 1
        assert "usage" in capsys.readouterr().err

    def test_help_exits_zero(self, capsys):
        """``--help`` prints usage to stdout and exits 0 (argparse default)."""
        with pytest.raises(SystemExit) as exc:
            bcb.main(["--help"])
        assert exc.value.code == 0
        assert "usage" in capsys.readouterr().out.lower()
