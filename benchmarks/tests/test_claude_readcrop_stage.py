"""No-model contract tests for the Claude ReadCrop adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _write_readcrop_sources(repo_path: Path) -> None:
    """Create the six locked task symbols in a disposable source tree."""
    sources = {
        "lightning.pytorch.core.module": "class LightningModule:\n    def log(self, value, prog_bar=False, logger=True, on_step=None, on_epoch=None, reduce_fx='mean', sync_dist=False, batch_size=None, rank_zero_only=False, add_dataloader_idx=True, metric_attribute=None, enable_graph=False):\n        pass\n",
        "lightning.pytorch.trainer.trainer": "class Trainer:\n    def fit(self, model, train_dataloaders=None, val_dataloaders=None, datamodule=None, ckpt_path=None):\n        pass\n\n    def __init__(self, enable_checkpointing=True, val_check_interval=1.0, check_val_every_n_epoch=1, accumulate_grad_batches=1, fast_dev_run=False, detect_anomaly=False):\n        pass\n",
        "lightning.pytorch.callbacks.early_stopping": "class EarlyStopping:\n    def __init__(self, monitor='x', min_delta=0.0, patience=3, mode='min', stopping_threshold=None, divergence_threshold=None, check_finite=True, check_on_train_epoch_end=None):\n        pass\n",
        "lightning.pytorch.callbacks.model_checkpoint": "class ModelCheckpoint:\n    def _save_checkpoint(self, trainer, filepath):\n        pass\n",
        "lightning.pytorch.strategies.fsdp": "class FSDPStrategy:\n    def setup(self, trainer):\n        pass\n",
    }
    for module, source in sources.items():
        path = repo_path / Path(*module.split(".")).with_suffix(".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_readcrop_dry_run_plans_all_locked_cells_without_a_claude_call(
    tmp_path: Path, capsys: Any, script_run_agentic: Any
) -> None:
    """The no-model entry point binds the shared six-task suite to all A/B/C arms.

    Regression: ReadCrop was only a legacy agentic task type, so no immutable
    shared-contract plan or scope could be reviewed before spending.
    """
    _write_readcrop_sources(tmp_path)

    script_run_agentic.main(repo_path=tmp_path, study="readcrop", dry_run=True)

    output = capsys.readouterr().out
    assert output.count("PLAN    RC-") == 18
    assert "PLAN    RC-06  rep=1  C_strict" in output
    assert "SCOPE   " in output


def test_readcrop_strict_prompt_uses_the_installed_skill_namespace_and_exact_symbol_query(
    script_run_agentic: Any,
) -> None:
    """Strict Claude treatment preserves the installed Codemap integration."""
    prompt = script_run_agentic.readcrop_prompt(
        "C_strict",
        {"symbol": "Example.method", "prompt": "Describe Example.method."},
    )

    assert "/codemap-py:query-code symbol Example.method" in prompt


def test_readcrop_parser_scores_the_strict_envelope_without_inventing_tool_tokens(script_run_agentic: Any) -> None:
    """Claude-native usage stays intact when tool-result token usage is unavailable.

    Regression: a generic output scorer accepted prose-only answers and could
    manufacture tiktoken estimates despite Claude not emitting this metric.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}},
        {
            "type": "result",
            "subtype": "success",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 1,
                "output_tokens": 3,
            },
        },
    ]

    row = script_run_agentic.parse_claude_readcrop_events(events, arm="A_plain", contract=contract)

    assert row["success"] is True
    assert row["primary_correct"] is True
    assert row["input_tokens"] == 13
    assert row["cached_input_tokens"] == 3
    assert row["tool_result_tokens"] is None
    assert row["compliance"] is True
    assert row["provider_binding"] == dict(contract.provider_binding())


def test_readcrop_parser_rejects_prose_and_flags_strict_arm_noncompliance(script_run_agentic: Any) -> None:
    """Missing JSON and an unused C treatment remain distinct diagnosable failures.

    Regression: formatting failures could receive keyword credit, while C could
    be reported compliant without a Claude Codemap tool invocation.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "value only"}]}},
        {"type": "result", "subtype": "success", "usage": {}},
    ]

    row = script_run_agentic.parse_claude_readcrop_events(events, arm="C_strict", contract=contract)

    assert row["success"] is False
    assert row["answer_error"] == "missing strict read-crop answer envelope"
    assert row["compliance"] is False


def test_readcrop_parser_makes_missing_or_forbidden_codemap_use_primary_ineligible(script_run_agentic: Any) -> None:
    """A valid answer cannot rescue an invalid A/C treatment assignment.

    Regression: the parser exposed a false C ``success`` when the answer was
    correct but no Codemap query occurred; this could pool a treatment failure
    with valid answer-quality evidence.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    complete = {"type": "result", "subtype": "success", "usage": {"input_tokens": 1, "output_tokens": 1}}

    missing_c = script_run_agentic.parse_claude_readcrop_events(
        [{"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}}, complete],
        arm="C_strict",
        contract=contract,
    )
    contaminated_a = script_run_agentic.parse_claude_readcrop_events(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Skill", "input": {"skill": "codemap-py:query-code"}},
                        {"type": "text", "text": answer},
                    ]
                },
            },
            complete,
        ],
        arm="A_plain",
        contract=contract,
    )

    assert missing_c["primary_correct"] is True
    assert missing_c["compliance"] is False
    assert missing_c["success"] is False
    assert contaminated_a["primary_correct"] is True
    assert contaminated_a["contaminated"] is True
    assert contaminated_a["success"] is False


def test_readcrop_parser_requires_a_successful_codemap_result_not_a_mere_attempt(script_run_agentic: Any) -> None:
    """C-strict eligibility depends on completed query evidence, not a tool-use block.

    Regression: treating an attempted or errored Codemap call as C compliance
    would pool a treatment that never received the frozen graph answer.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    tool_use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "attempt",
                    "name": "Bash",
                    "input": {"command": "codemap-py query refs Example.method"},
                },
                {"type": "text", "text": answer},
            ]
        },
    }
    complete = {"type": "result", "subtype": "success", "usage": {"input_tokens": 1, "output_tokens": 1}}

    errored = script_run_agentic.parse_claude_readcrop_events(
        [
            tool_use,
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "attempt",
                            "is_error": True,
                            "content": "command unavailable",
                        }
                    ]
                },
            },
            complete,
        ],
        arm="C_strict",
        contract=contract,
    )
    completed = script_run_agentic.parse_claude_readcrop_events(
        [
            tool_use,
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "attempt",
                            "is_error": False,
                            "content": "query completed",
                        }
                    ]
                },
            },
            complete,
        ],
        arm="C_strict",
        contract=contract,
    )

    assert errored["codemap_calls"] == 1
    assert errored["codemap_successful_calls"] == 0
    assert errored["compliance"] is False
    assert errored["success"] is False
    assert completed["codemap_successful_calls"] == 1
    assert completed["strict_query_conformance"] is False
    assert completed["compliance"] is False
    assert completed["success"] is False


def test_readcrop_strict_credits_only_completed_underlying_cli_queries(script_run_agentic: Any) -> None:
    """A successful Skill launch cannot stand in for the frozen query result.

    Regression: the Claude artifact recorded a successful ``Skill`` wrapper
    despite the wrapped command being permission-denied. The decision-grade
    C arm must therefore observe its completed ``codemap-py query`` or legacy
    ``scan-query`` Bash call with the canonical arguments.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    skill_only = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "skill",
                        "name": "Skill",
                        "input": {"skill": "codemap-py:query-code", "args": "symbol Example.method"},
                    },
                    {"type": "text", "text": answer},
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "skill", "is_error": False, "content": "started"}]
            },
        },
        {"type": "result", "subtype": "success", "usage": {}},
    ]
    canonical_bash = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "query",
                        "name": "Bash",
                        "input": {"command": "codemap-py query symbol Example.method 2>/dev/null"},
                    },
                    {"type": "text", "text": answer},
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "query", "is_error": False, "content": "{}"}]
            },
        },
        {"type": "result", "subtype": "success", "usage": {}},
    ]
    integrated = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "skill",
                        "name": "Skill",
                        "input": {"skill": "codemap-py:query-code", "args": "symbol Example.method"},
                    },
                    {
                        "type": "tool_use",
                        "id": "query",
                        "name": "Bash",
                        "input": {"command": "codemap-py query symbol Example.method"},
                    },
                    {"type": "text", "text": answer},
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "skill", "is_error": False, "content": "started"},
                    {"type": "tool_result", "tool_use_id": "query", "is_error": False, "content": "{}"},
                ]
            },
        },
        {"type": "result", "subtype": "success", "usage": {}},
    ]

    wrapped = script_run_agentic.parse_claude_readcrop_events(skill_only, arm="C_strict", contract=contract)
    direct_only = script_run_agentic.parse_claude_readcrop_events(canonical_bash, arm="C_strict", contract=contract)
    completed = script_run_agentic.parse_claude_readcrop_events(integrated, arm="C_strict", contract=contract)

    assert wrapped["codemap_successful_calls"] == 0
    assert wrapped["compliance"] is False
    assert wrapped["pooling_eligible"] is False
    assert direct_only["codemap_successful_calls"] == 1
    assert direct_only["codemap_query_skill_launches"] == 0
    assert direct_only["compliance"] is False
    assert completed["successful_query_arguments"] == [["symbol", "Example.method"]]
    assert completed["codemap_query_skill_launches"] == 1
    assert completed["compliance"] is True
    assert completed["pooling_eligible"] is True


def test_readcrop_parser_accepts_only_the_installable_launcher_outside_the_worktree(script_run_agentic: Any) -> None:
    """Installable launcher forms are valid, but their parent directory is not.

    Regression: the production Skill invokes its absolute ``bin/codemap-py``
    launcher without changing cwd. Treating that path as source contamination
    rejects a valid integration; exempting the parent would hide an escaped
    ``cd`` and stale index lookup.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )

    def events(command: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "skill",
                            "name": "Skill",
                            "input": {"skill": "codemap-py:query-code", "args": "symbol Example.method"},
                        },
                        {"type": "tool_use", "id": "query", "name": "Bash", "input": {"command": command}},
                        {"type": "text", "text": answer},
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "skill", "is_error": False, "content": "started"},
                        {"type": "tool_result", "tool_use_id": "query", "is_error": False, "content": "{}"},
                    ]
                },
            },
            {"type": "result", "subtype": "success", "usage": {}},
        ]

    launcher_path = "/opt/codemap-py/bin/codemap-py"
    launcher = f"{launcher_path} query --compact symbol Example.method"
    literal = '"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" query --compact symbol Example.method'
    valid = script_run_agentic.parse_claude_readcrop_events(
        events(launcher), arm="C_strict", contract=contract, workspace_root=Path("/disposable/repository")
    )
    quoted = script_run_agentic.parse_claude_readcrop_events(
        events(f'"{launcher_path}" query --compact symbol Example.method'),
        arm="C_strict",
        contract=contract,
        workspace_root=Path("/disposable/repository"),
    )
    variable = script_run_agentic.parse_claude_readcrop_events(
        events(literal), arm="C_strict", contract=contract, workspace_root=Path("/disposable/repository")
    )
    escaped = script_run_agentic.parse_claude_readcrop_events(
        events(f'cd /opt/codemap-py && "{launcher_path}" query --compact symbol Example.method'),
        arm="C_strict",
        contract=contract,
        workspace_root=Path("/disposable/repository"),
    )

    assert valid["successful_query_arguments"] == [["symbol", "Example.method"]]
    assert valid["outside_workspace_paths"] == []
    assert valid["pooling_eligible"] is True
    assert quoted["successful_query_arguments"] == [["symbol", "Example.method"]]
    assert quoted["outside_workspace_paths"] == []
    assert quoted["pooling_eligible"] is True
    assert variable["successful_query_arguments"] == [["symbol", "Example.method"]]
    assert variable["outside_workspace_paths"] == []
    assert variable["pooling_eligible"] is True
    assert escaped["outside_workspace_paths"] == ["/opt/codemap-py"]
    assert escaped["contaminated"] is True
    assert escaped["pooling_eligible"] is False


def test_readcrop_parser_quarantines_external_paths_and_frozen_index_recovery(script_run_agentic: Any) -> None:
    """External source reads and attempts to rebuild the frozen index cannot pool.

    Regression: RC-02 read an unrelated checkout after a stale-index recovery
    attempt, while the result still appeared as a valid C treatment.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "query",
                        "name": "Bash",
                        "input": {"command": "codemap-py query symbol Example.method"},
                    },
                    {
                        "type": "tool_use",
                        "id": "rebuild",
                        "name": "Bash",
                        "input": {"command": "codemap-py scan --incremental"},
                    },
                    {
                        "type": "tool_use",
                        "id": "read",
                        "name": "Read",
                        "input": {"file_path": "/outside/repository/module.py"},
                    },
                    {"type": "text", "text": answer},
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "query", "is_error": False, "content": "{}"},
                    {"type": "tool_result", "tool_use_id": "rebuild", "is_error": False, "content": "built"},
                    {"type": "tool_result", "tool_use_id": "read", "is_error": False, "content": "source"},
                ]
            },
        },
        {"type": "result", "subtype": "success", "usage": {}},
    ]

    row = script_run_agentic.parse_claude_readcrop_events(
        events,
        arm="C_strict",
        contract=contract,
        workspace_root=Path("/disposable/repository"),
    )

    assert row["outside_workspace_paths"] == ["/outside/repository/module.py"]
    assert row["frozen_index_recovery_attempted"] is True
    assert row["contaminated"] is True
    assert row["pooling_eligible"] is False


def test_readcrop_parser_records_but_does_not_quarantine_a_denied_external_read(script_run_agentic: Any) -> None:
    """A denied path guess cannot leak source bytes or invalidate an otherwise clean cell.

    Regression: the paid Claude calibration marked A/B cells contaminated from
    permission-denied absolute Reads before they found the disposable source.
    """
    task = {
        "id": "RC-fixture",
        "type": "read_crop",
        "prompt": "Describe Example.method.",
        "symbol": "Example.method",
        "expected_keywords": ["value"],
    }
    contract = script_run_agentic.build_readcrop_contract(
        task,
        source="def method(self, value: int) -> None:\n    pass\n",
    )
    answer = (
        "BEGIN_READ_CROP_JSON\n"
        '{"signature":"Example.method(self, value: int) -> None","parameters":["self","value"],'
        '"behavior":"Records the supplied value."}\nEND_READ_CROP_JSON'
    )
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "denied-read",
                        "name": "Read",
                        "input": {"file_path": "/outside/repository/module.py"},
                    },
                    {"type": "text", "text": answer},
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "denied-read",
                        "is_error": True,
                        "content": "Permission denied",
                    }
                ]
            },
        },
        {"type": "result", "subtype": "success", "usage": {}},
    ]

    row = script_run_agentic.parse_claude_readcrop_events(
        events,
        arm="A_plain",
        contract=contract,
        workspace_root=Path("/disposable/repository"),
    )

    assert row["attempted_outside_workspace_paths"] == ["/outside/repository/module.py"]
    assert row["outside_workspace_paths"] == []
    assert row["contaminated"] is False
    assert row["pooling_eligible"] is True


def test_external_path_evidence_ignores_relative_find_glob(script_run_agentic: Any) -> None:
    """A successful workspace-relative ``find -path`` glob is not an absolute access.

    Regression: the RC-01/B paid cell was quarantined because the scanner read
    the slash in ``*/package/module/*`` as an absolute ``/package/module/*``.
    """
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "find",
                        "name": "Bash",
                        "input": {"command": 'find . -type f -name "module.py" -path "*/lightning/pytorch/core/*"'},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "find",
                        "is_error": False,
                        "content": "./src/lightning/pytorch/core/module.py",
                    }
                ]
            },
        },
    ]

    attempted, successful = script_run_agentic._outside_workspace_path_evidence(
        events, Path("/tmp/disposable/repository")
    )

    assert attempted == []
    assert successful == []


def test_claude_stage_row_reports_only_successful_codemap_queries(script_run_agentic: Any) -> None:
    """The human row never reports Codemap use when every query was denied."""
    row = {
        "success": False,
        "task_id": "RC-01",
        "arm": "C_strict",
        "input_tokens": 10,
        "output_tokens": 2,
        "command_calls": 1,
        "elapsed_s": 1.0,
        "quality_score": 1.0,
        "study": "readcrop",
        "primary_correct": True,
        "codemap_used": False,
        "codemap_attempted": True,
        "codemap_successful_calls": 0,
    }

    rendered = script_run_agentic._format_claude_stage_row(row, completed=1, total=3)

    assert "correct=✓ codemap=✗" in rendered


def test_readcrop_scope_is_deterministic_and_source_bound(script_run_agentic: Any) -> None:
    """Scope approval changes when a frozen source contract changes."""
    task = {
        "id": "RC-01",
        "contract": type("Contract", (), {"task_id": "RC-01", "oracle_sha256": "a" * 64, "source_sha256": "b" * 64})(),
    }
    changed = {
        "id": "RC-01",
        "contract": type("Contract", (), {"task_id": "RC-01", "oracle_sha256": "a" * 64, "source_sha256": "c" * 64})(),
    }

    first = script_run_agentic.resolve_readcrop_scope([task])
    second = script_run_agentic.resolve_readcrop_scope([changed])

    assert first["total_cells"] == 3
    assert first["scope_sha256"] != second["scope_sha256"]
    assert json.loads(json.dumps(first))["arms"] == ["A_plain", "B_auto", "C_strict"]


def test_fix_multi_dry_run_reuses_the_shared_contract_without_a_claude_call(
    capsys: Any, script_run_agentic: Any
) -> None:
    """Claude planning binds the same multi-caller task bytes and scorer hashes as Codex.

    Regression: Claude's historical Fix-Multi path used diagnostic keyword recall,
    so an adapter could silently disagree with Codex executable scoring.
    """
    script_run_agentic.main(study="fix-multi", dry_run=True)

    output = capsys.readouterr().out
    assert output.count("PLAN    FM-") == 9
    assert "PLAN    FM-03  rep=1  C_strict" in output
    assert "SCOPE   " in output


def test_fix_multi_scope_changes_when_a_shared_oracle_hash_changes(script_run_agentic: Any) -> None:
    """The Claude scope records shared scorer and oracle fields rather than keyword heuristics."""
    binding = {
        "canonical_task_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "baseline_commit": "c" * 40,
        "oracle_sha256": "d" * 64,
        "scorer_sha256": "e" * 64,
    }
    changed = {**binding, "oracle_sha256": "f" * 64}
    first = {
        "task": {},
        "contract": type("Contract", (), {"task_id": "FM-01", "provider_binding": lambda _: binding})(),
    }
    second = {
        "task": {},
        "contract": type("Contract", (), {"task_id": "FM-01", "provider_binding": lambda _: changed})(),
    }

    first_scope = script_run_agentic.resolve_claude_fix_multi_scope([first])
    second_scope = script_run_agentic.resolve_claude_fix_multi_scope([second])

    assert first_scope["total_cells"] == 3
    assert first_scope["scope_sha256"] != second_scope["scope_sha256"]
