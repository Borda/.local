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
