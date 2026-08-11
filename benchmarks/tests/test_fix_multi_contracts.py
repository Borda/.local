"""Independent caller-completeness oracle tests for the multi-file executable stage."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

SUITE_PATH = Path(__file__).resolve().parents[1] / "suites" / "tasks-fix-multi.json"
FROZEN_REPO = Path("/private/tmp/codemap-provider-parity-pl-2.6.5")
BENCHMARKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARKS))


def _runner() -> object:
    """Return the private Fix stage without invoking its CLI."""
    from _bench_codex import stage_fix

    return stage_fix


_RUNNER = _runner()


build_fix_multi_contract = _RUNNER.build_fix_multi_contract
run_fix_multi_oracle = _RUNNER.run_fix_multi_oracle


def _contract(task_id: str) -> object:
    """Return one immutable multi-file contract from the canonical task bytes."""
    tasks = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    return build_fix_multi_contract(next(task for task in tasks if task["id"] == task_id))


def _copy_contract_sources(repo_path: Path, destination: Path, contract: object) -> None:
    """Copy every source file declared by a contract into an isolated candidate tree."""
    for relative_path in contract.expected_paths:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_path / relative_path, target)


def _complete_early_stopping_source(source: str) -> str:
    """Return the FM-01 source with explicit callers and an observe-only dry run branch."""
    return (
        source.replace(
            'def _run_early_stopping_check(self, trainer: "pl.Trainer") -> None:',
            'def _run_early_stopping_check(self, trainer: "pl.Trainer", dry_run: bool = False) -> None:',
        )
        .replace("self._run_early_stopping_check(trainer)", "self._run_early_stopping_check(trainer, dry_run=False)")
        .replace(
            "        trainer.should_stop = trainer.should_stop or should_stop\n",
            "        if dry_run:\n"
            '            log.info(f"dry run: should_stop={should_stop}, reason={reason}")\n'
            "            return\n"
            "        trainer.should_stop = trainer.should_stop or should_stop\n",
        )
    )


def _complete_early_stopping_else_source(source: str) -> str:
    """Return the FM-01 source with an equivalent observe-only if/else branch."""
    source = source.replace(
        'def _run_early_stopping_check(self, trainer: "pl.Trainer") -> None:',
        'def _run_early_stopping_check(self, trainer: "pl.Trainer", dry_run: bool = False) -> None:',
    ).replace("self._run_early_stopping_check(trainer)", "self._run_early_stopping_check(trainer, dry_run=False)")
    normal_path = (
        "        trainer.should_stop = trainer.should_stop or should_stop\n"
        "        if should_stop:\n"
        "            self.stopped_epoch = trainer.current_epoch\n"
        "            self.stopping_reason_message = reason\n"
        "        if reason and self.verbose:\n"
        "            self._log_info(trainer, reason, self.log_rank_zero_only)\n"
    )
    dry_run_branch = (
        "        if dry_run:\n"
        '            self._log_info(trainer, f"dry run: should_stop={should_stop}, reason={reason}", self.log_rank_zero_only)\n'
        "        else:\n"
        "            trainer.should_stop = trainer.should_stop or should_stop\n"
        "            if should_stop:\n"
        "                self.stopped_epoch = trainer.current_epoch\n"
        "                self.stopping_reason_message = reason\n"
        "            if reason and self.verbose:\n"
        "                self._log_info(trainer, reason, self.log_rank_zero_only)\n"
    )
    return source.replace(normal_path, dry_run_branch)


def _complete_strategy_source(source: str, *, is_base: bool) -> str:
    """Return one FM-03 source with its verbose contract and required propagation or log."""
    source = source.replace(
        'def setup(self, trainer: "pl.Trainer") -> None:',
        'def setup(self, trainer: "pl.Trainer", verbose: bool = False) -> None:',
        1,
    )
    if is_base:
        return source.replace(
            'def setup(self, trainer: "pl.Trainer", verbose: bool = False) -> None:\n',
            'def setup(self, trainer: "pl.Trainer", verbose: bool = False) -> None:\n'
            "        if verbose:\n"
            '            log.debug("setting up strategy")\n',
            1,
        )
    return source.replace(
        'def setup(self, trainer: "pl.Trainer", verbose: bool = False) -> None:\n',
        'def setup(self, trainer: "pl.Trainer", verbose: bool = False) -> None:\n'
        "        super().setup(trainer, verbose=verbose)\n",
        1,
    )


def _complete_model_checkpoint_source(source: str) -> str:
    """Return the FM-02 source with exact persistence-boundary provenance labels."""
    source = source.replace(
        'def _save_checkpoint(self, trainer: "pl.Trainer", filepath: str) -> None:',
        'def _save_checkpoint(self, trainer: "pl.Trainer", filepath: str, reason: str = "") -> None:',
    ).replace(
        "        trainer.save_checkpoint(filepath, self.save_weights_only)\n",
        "        if reason:\n"
        '            rank_zero_info(f"{reason}: saving checkpoint to {filepath}")\n'
        "        trainer.save_checkpoint(filepath, self.save_weights_only)\n",
        1,
    )
    for reason in ("exception", "last", "none", "top_k"):
        source = source.replace(
            "self._save_checkpoint(trainer, filepath)",
            f"self._save_checkpoint(trainer, filepath, reason={reason!r})",
            1,
        )
    return source


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
@pytest.mark.parametrize("task_id", ("FM-01", "FM-02", "FM-03"))
def test_frozen_baseline_fails_every_complete_caller_oracle(task_id: str) -> None:
    """Each task begins from a baseline that cannot accidentally satisfy its new contract."""
    assert run_fix_multi_oracle(FROZEN_REPO, _contract(task_id)) is False


def test_strategy_contract_expands_the_stale_four_file_scaffold_to_all_declared_overrides() -> None:
    """The independent oracle follows the prompt's six overrides, not its stale file hint."""
    contract = _contract("FM-03")

    assert len(contract.expected_paths) == 7
    assert contract.expected_paths[-2:] == (
        "src/lightning/pytorch/strategies/single_xla.py",
        "src/lightning/pytorch/strategies/xla.py",
    )


def test_fix_multi_prompts_preserve_discovery_as_the_measured_work() -> None:
    """Prevent task text from giving every arm the caller and override answer surface."""
    tasks = {task["id"]: task for task in json.loads(SUITE_PATH.read_text(encoding="utf-8"))}

    for leaked_caller in (
        "on_exception",
        "_save_last_checkpoint",
        "_save_none_monitor_checkpoint",
        "_update_best_and_save",
    ):
        assert leaked_caller not in tasks["FM-02"]["prompt"]
    assert "all four" not in tasks["FM-02"]["prompt"].lower()

    for leaked_class in (
        "DDPStrategy",
        "FSDPStrategy",
        "DeepSpeedStrategy",
        "ModelParallelStrategy",
        "SingleXLAStrategy",
        "XLAStrategy",
    ):
        assert leaked_class not in tasks["FM-03"]["prompt"]
    assert "use codemap rdeps" not in tasks["FM-03"]["prompt"].lower()


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_early_stopping_contract_requires_explicit_callers_and_observable_decision_log(tmp_path: Path) -> None:
    """FM-01 rejects omitted callers and dry-run logs that do not describe the computed decision."""
    contract = _contract("FM-01")
    _copy_contract_sources(FROZEN_REPO, tmp_path, contract)
    target = tmp_path / contract.expected_paths[0]
    complete = _complete_early_stopping_source(target.read_text(encoding="utf-8"))
    target.write_text(complete, encoding="utf-8")

    assert run_fix_multi_oracle(tmp_path, contract) is True

    target.write_text(complete.replace("trainer, dry_run=False)", "trainer)", 1), encoding="utf-8")
    assert run_fix_multi_oracle(tmp_path, contract) is False

    target.write_text(
        complete.replace('log.info(f"dry run: should_stop={should_stop}, reason={reason}")', 'log.info("dry run")'),
        encoding="utf-8",
    )
    assert run_fix_multi_oracle(tmp_path, contract) is False

    target.write_text(
        complete.replace(
            "        if dry_run:\n",
            "        trainer.should_stop = trainer.should_stop or should_stop\n"
            "        self.stopped_epoch = trainer.current_epoch\n"
            "        if dry_run:\n",
            1,
        ),
        encoding="utf-8",
    )
    assert run_fix_multi_oracle(tmp_path, contract) is False


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_early_stopping_contract_accepts_semantically_equivalent_else_branch(tmp_path: Path) -> None:
    """FM-01 must not prefer early-return syntax over an observe-only if/else implementation."""
    contract = _contract("FM-01")
    _copy_contract_sources(FROZEN_REPO, tmp_path, contract)
    target = tmp_path / contract.expected_paths[0]
    complete = _complete_early_stopping_else_source(target.read_text(encoding="utf-8"))
    target.write_text(complete, encoding="utf-8")

    assert run_fix_multi_oracle(tmp_path, contract) is True

    target.write_text(
        complete.replace("            trainer.should_stop = trainer.should_stop or should_stop\n", "", 1),
        encoding="utf-8",
    )
    assert run_fix_multi_oracle(tmp_path, contract) is False


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_strategy_contract_requires_every_override_to_forward_verbose(tmp_path: Path) -> None:
    """FM-03 accepts the complete base-and-override propagation patch and rejects one missing forward."""
    contract = _contract("FM-03")
    _copy_contract_sources(FROZEN_REPO, tmp_path, contract)
    for relative_path in contract.expected_paths:
        target = tmp_path / relative_path
        target.write_text(
            _complete_strategy_source(
                target.read_text(encoding="utf-8"),
                is_base=relative_path.endswith("strategies/strategy.py"),
            ),
            encoding="utf-8",
        )

    assert run_fix_multi_oracle(tmp_path, contract) is True

    incomplete = tmp_path / contract.expected_paths[1]
    incomplete.write_text(
        incomplete.read_text(encoding="utf-8").replace("        super().setup(trainer, verbose=verbose)\n", "", 1),
        encoding="utf-8",
    )
    assert run_fix_multi_oracle(tmp_path, contract) is False


@pytest.mark.skipif(not FROZEN_REPO.is_dir(), reason="frozen benchmark repository is unavailable")
def test_model_checkpoint_contract_requires_exact_reasons_and_a_pre_save_provenance_log(tmp_path: Path) -> None:
    """FM-02 rejects generic labels and logging after the persistence boundary."""
    contract = _contract("FM-02")
    _copy_contract_sources(FROZEN_REPO, tmp_path, contract)
    target = tmp_path / contract.expected_paths[0]
    complete = _complete_model_checkpoint_source(target.read_text(encoding="utf-8"))
    target.write_text(complete, encoding="utf-8")

    assert run_fix_multi_oracle(tmp_path, contract) is True

    target.write_text(complete.replace("reason='top_k'", "reason='best'"), encoding="utf-8")
    assert run_fix_multi_oracle(tmp_path, contract) is False

    target.write_text(
        complete.replace(
            "        if reason:\n"
            '            rank_zero_info(f"{reason}: saving checkpoint to {filepath}")\n'
            "        trainer.save_checkpoint(filepath, self.save_weights_only)\n",
            "        trainer.save_checkpoint(filepath, self.save_weights_only)\n"
            "        if reason:\n"
            '            rank_zero_info(f"{reason}: saving checkpoint to {filepath}")\n',
        ),
        encoding="utf-8",
    )
    assert run_fix_multi_oracle(tmp_path, contract) is False
