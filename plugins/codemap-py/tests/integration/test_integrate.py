"""codemap-py integrate engine — check/plan/apply/sync/demo (plan §8.3, w-engine.md).

Black-box against the public API in ``src/codemap_py/integration.py``: ``run``,
``build_plan``, ``compute_plan_sha256``, ``load_plan``, ``verify_approval``,
``apply_plan``, ``sync_plan``, ``build_check_report``, ``run_demo``, ``resolve_targets``,
``Journal``, ``IntegrationError``/``RefusalError``/``ApprovalError``, and the module's own
named internal helpers (``_render_managed_block``, ``_managed_block_status``,
``_unsafe_windows_batch_argv``, ``_resolve_native_command``) that w-engine.md calls out as
test-writer-facing.

Every apply/sync test builds a disposable fixture repo under ``tmp_path`` mirroring the
closed target set's directory shape (``plugins/cc_*``, ``plugins/codex-rig``,
``plugins/codemap-py``) and ``monkeypatch.chdir``s into it so ``index_paths.canonical_root()``
resolves there — the real ``plugins/cc_*``/``plugins/codemap-py`` trees are never touched.
Native-CLI-dependent ``sync`` behavior is exercised by monkeypatching the module's own
``_native_json_probe``/``_run_native_required`` seams rather than requiring an installed
``claude``/``codex`` CLI on the test runner.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codemap_py import integration

_PATH_CLASSES = {"normal": "repo", "spaces_nonascii": "a repo café"}


# --------------------------------------------------------------------------------------
# Fixture-tree builder — disposable consumer/provider trees, never the real repo.
# --------------------------------------------------------------------------------------


def _seed(path: Path, text: str) -> None:
    """Write *text* verbatim (LF-only, no OS newline translation) so fixtures are byte-exact cross-platform."""
    path.write_text(text, newline="\n")


def _write_manifest(plugin_dir: Path, runtime: str, name: str, version: str) -> None:
    manifest_dir = plugin_dir / (".claude-plugin" if runtime == "claude" else ".codex-plugin")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    _seed(manifest_dir / "plugin.json", json.dumps({"name": name, "version": version}))


def _build_repo(base: Path, *, path_class: str = "normal") -> Path:
    """Build a disposable repo tree with every closed-set consumer + provider manifest."""
    root = base / _PATH_CLASSES[path_class]
    root.mkdir(parents=True)
    for target in integration.ALL_TARGETS:
        _write_manifest(root / target.plugin_dir, target.runtime, target.consumer, "1.0.0")
    _write_manifest(root / integration.PROVIDER_DIR, "claude", integration.PROVIDER_NAME, "9.9.9")
    _write_manifest(root / integration.PROVIDER_DIR, "codex", integration.PROVIDER_NAME, "9.9.9")
    return root


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """Return every regular file's repo-relative path mapped to its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr


def _git_commit_all(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture baseline")


@pytest.fixture(params=["normal", "spaces_nonascii"])
def path_class(request: pytest.FixtureRequest) -> str:
    """Fixture project/plugin roots vary over normal vs. space+non-ASCII path classes (F8)."""
    return request.param


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_class: str) -> Path:
    """A disposable fixture repo, chdir'd into so ``canonical_root()`` resolves to it."""
    root = _build_repo(tmp_path, path_class=path_class)
    monkeypatch.chdir(root)
    return root


# --------------------------------------------------------------------------------------
# check — zero-write.
# --------------------------------------------------------------------------------------


def test_check_is_zero_write(repo: Path) -> None:
    """``build_check_report`` never mutates the fixture tree."""
    before = _tree_snapshot(repo)
    report = integration.build_check_report("both", repo / integration.PROVIDER_DIR)
    assert report["protocol"] == integration.PROTOCOL_VERSION
    assert _tree_snapshot(repo) == before


def test_check_cli_json_exits_zero(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``integrate check --json`` exits 0 and prints the check report as parseable JSON."""
    code = integration.run(["check", "--runtime", "both", "--json"], repo / integration.PROVIDER_DIR)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["protocol"] == integration.PROTOCOL_VERSION


def test_check_reports_absent_consumer_as_named_state_not_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed-set consumer with no manifest on disk is reported ``absent``, not raised as an error."""
    root = tmp_path / "no-oss"
    root.mkdir()
    for target in integration.ALL_TARGETS:
        if target.consumer != "oss":
            _write_manifest(root / target.plugin_dir, target.runtime, target.consumer, "1.0.0")
    _write_manifest(root / integration.PROVIDER_DIR, "claude", integration.PROVIDER_NAME, "9.9.9")
    monkeypatch.chdir(root)
    monkeypatch.setattr(integration, "_native_json_probe", lambda argv: None)
    report = integration.build_check_report("claude", root / integration.PROVIDER_DIR)
    oss_status = report["claude"]["consumers"]["oss"]
    assert oss_status == {
        "manifest_present": False,
        "name_matches": False,
        "source_version": None,
        "installed_version": None,
    }


# --------------------------------------------------------------------------------------
# plan — zero-mutation report artifact, stable SHA-256.
# --------------------------------------------------------------------------------------


def test_plan_writes_only_its_out_artifact(repo: Path, tmp_path: Path) -> None:
    """``plan --out <path>`` writes nothing under the fixture tree besides the named artifact."""
    before = _tree_snapshot(repo)
    out = tmp_path / "plan.json"
    code = integration.run(["plan", "--runtime", "claude", "--out", str(out)], repo / integration.PROVIDER_DIR)
    assert code == 0
    assert out.is_file()
    assert _tree_snapshot(repo) == before


def test_plan_default_out_confined_to_reports_dir(repo: Path) -> None:
    """Without ``--out``, the artifact lands only under the fixture's own ``.reports/integrate/``."""
    before = _tree_snapshot(repo)
    code = integration.run(["plan", "--runtime", "claude", "--consumers", "oss"], repo / integration.PROVIDER_DIR)
    assert code == 0
    after = _tree_snapshot(repo)
    changed = {k for k in after if after.get(k) != before.get(k)}
    assert changed
    assert all(k.startswith(".reports/integrate/") for k in changed)


def test_plan_sha256_is_stable_and_self_consistent(repo: Path) -> None:
    """The recorded ``plan_sha256`` equals the digest recomputed over the plan's own body."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    assert integration.compute_plan_sha256(plan) == plan["plan_sha256"]


def test_plan_unknown_consumer_exits_usage(repo: Path) -> None:
    """An unrecognized ``--consumers`` name is a ``2``-class syntax error, never a lookup."""
    code = integration.run(
        ["plan", "--runtime", "claude", "--consumers", "not-a-target"], repo / integration.PROVIDER_DIR
    )
    assert code == integration._EXIT_USAGE


# --------------------------------------------------------------------------------------
# Approval digest.
# --------------------------------------------------------------------------------------


def test_approve_malformed_rejected(repo: Path) -> None:
    """A non-hex/wrong-length ``--approve`` value is ``approve_malformed``."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    with pytest.raises(integration.ApprovalError) as exc:
        integration.verify_approval(plan, "not-a-sha256")
    assert exc.value.code == "approve_malformed"


def test_approve_mismatch_rejected(repo: Path) -> None:
    """A well-formed but wrong SHA-256 is ``approve_mismatch``."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    with pytest.raises(integration.ApprovalError) as exc:
        integration.verify_approval(plan, "0" * 64)
    assert exc.value.code == "approve_mismatch"


def test_approve_correct_sha_proceeds(repo: Path) -> None:
    """The plan's own recorded SHA-256 verifies without raising."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    integration.verify_approval(plan, plan["plan_sha256"])  # no raise


def test_apply_cli_bad_approve_exits_usage(repo: Path, tmp_path: Path) -> None:
    """``apply`` at the CLI boundary maps a bad ``--approve`` to exit ``2``."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    plan_path = tmp_path / "plan.json"
    _seed(plan_path, json.dumps(plan))
    code = integration.run(["apply", "--plan", str(plan_path), "--approve", "nope"], repo / integration.PROVIDER_DIR)
    assert code == integration._EXIT_USAGE


# --------------------------------------------------------------------------------------
# apply — refusal matrix (each: exit-mapped RefusalError, target file left untouched).
# --------------------------------------------------------------------------------------


def _single_op_plan(repo: Path, consumer: str = "oss") -> dict:
    return integration.build_plan("claude", [consumer], None, repo / integration.PROVIDER_DIR)


def _assert_refused(repo: Path, plan: dict, code: str, original_bytes: bytes | None) -> None:
    target_path = repo / plan["ops"][0]["path"]
    with pytest.raises(integration.RefusalError) as exc:
        integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR)
    assert exc.value.code == code
    after = target_path.read_bytes() if target_path.is_file() else None
    assert after == original_bytes


def test_apply_refuses_installed_cache_root(repo: Path) -> None:
    """A target resolving under any ``plugins/cache/...`` tree is refused, never written."""
    plan = _single_op_plan(repo)
    plan["ops"][0]["path"] = "plugins/cache/oss/skills/_shared/codemap-context.md"
    plan["plan_sha256"] = integration.compute_plan_sha256(plan)
    _assert_refused(repo, plan, "installed_cache_root", None)


def test_apply_refuses_path_escape(repo: Path) -> None:
    """A target outside its consumer's own plugin directory is refused."""
    plan = _single_op_plan(repo)
    plan["ops"][0]["path"] = "plugins/some-other-dir/escape.md"
    plan["plan_sha256"] = integration.compute_plan_sha256(plan)
    _assert_refused(repo, plan, "path_escape", None)


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs elevated privileges on Windows")
def test_apply_refuses_symlink_target(repo: Path) -> None:
    """A target path traversing a symlink is refused, even though the plan itself is unmodified.

    The symlink points at a sibling file *inside* the same consumer plugin dir, so the
    resolved path still passes the path-containment check — isolating ``symlink_target``
    from ``path_escape`` (both fire on an out-of-tree symlink target; only this shape proves
    the symlink check specifically).
    """
    plan = _single_op_plan(repo)
    target_path = repo / plan["ops"][0]["path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sibling = target_path.parent / "sibling.md"
    _seed(sibling, "not a managed block\n")
    os.symlink(sibling, target_path)
    _assert_refused(repo, plan, "symlink_target", sibling.read_bytes())


def test_apply_refuses_dirty_overlap(repo: Path) -> None:
    """Uncommitted local changes on the target file refuse the overlay."""
    plan = _single_op_plan(repo)
    target_path = repo / plan["ops"][0]["path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _seed(target_path, "tracked content\n")
    _git_commit_all(repo)
    original = target_path.read_bytes()
    _seed(target_path, "tracked content\nuncommitted local edit\n")
    dirtied = target_path.read_bytes()
    # before_hash in the plan was computed pre-git-commit against the same bytes; the refusal
    # fires on the *uncommitted* overlay, independent of before_hash matching or not.
    _assert_refused(repo, plan, "dirty_overlap", dirtied)
    assert dirtied != original


def test_apply_refuses_unverified_product_identity(repo: Path) -> None:
    """A consumer manifest whose ``name`` no longer matches the plan's target is refused."""
    plan = _single_op_plan(repo)
    manifest_path = repo / "plugins" / "cc_oss" / ".claude-plugin" / "plugin.json"
    _seed(manifest_path, json.dumps({"name": "tampered-name", "version": "1.0.0"}))
    _assert_refused(repo, plan, "unverified_product_identity", None)


def test_apply_refuses_foreign_or_modified_marker(repo: Path) -> None:
    """A managed block whose embedded sha256 does not match its own body is a foreign/tampered marker."""
    target = integration.CLAUDE_TARGETS[0]
    rel_path = f"{target.plugin_dir}/{integration.CONSUMER_MANAGED_FILE[target.consumer]}"
    target_path = repo / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    real_block = integration._render_managed_block("some body\n")
    stamp_index = real_block.index("sha256=") + len("sha256=")
    flipped_digit = "0" if real_block[stamp_index] != "0" else "1"
    tampered = real_block[:stamp_index] + flipped_digit + real_block[stamp_index + 1 :]
    _seed(target_path, tampered)
    original = target_path.read_bytes()

    plan = integration.build_plan("claude", [target.consumer], None, repo / integration.PROVIDER_DIR)
    _assert_refused(repo, plan, "foreign_or_modified_marker", original)


def test_apply_refuses_drift_on_out_of_band_edit(repo: Path) -> None:
    """A target edited out of band between ``plan`` and ``apply`` invalidates the approval."""
    target = integration.CLAUDE_TARGETS[0]
    rel_path = f"{target.plugin_dir}/{integration.CONSUMER_MANAGED_FILE[target.consumer]}"
    target_path = repo / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _seed(target_path, "original prose\n")

    plan = integration.build_plan("claude", [target.consumer], None, repo / integration.PROVIDER_DIR)
    _seed(target_path, "original prose\nedited after the plan was made\n")
    dirtied = target_path.read_bytes()
    _assert_refused(repo, plan, "drift", dirtied)


def test_apply_refuses_drift_when_block_unexpectedly_appears(repo: Path) -> None:
    """A managed block appearing where the plan expected a first-time insert is also drift."""
    target = integration.CLAUDE_TARGETS[0]
    plan = integration.build_plan("claude", [target.consumer], None, repo / integration.PROVIDER_DIR)
    assert plan["ops"][0]["first_time"] is True

    target_path = repo / plan["ops"][0]["path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _seed(target_path, integration._render_managed_block("unexpected pre-existing block\n"))
    dirtied = target_path.read_bytes()
    _assert_refused(repo, plan, "drift", dirtied)


# --------------------------------------------------------------------------------------
# apply — in-file mutation semantics.
# --------------------------------------------------------------------------------------


def test_apply_first_time_insert_preserves_existing_content(repo: Path) -> None:
    """A first-time apply appends the managed block; real pre-existing prose survives byte-for-byte."""
    target = integration.CLAUDE_TARGETS[0]
    rel_path = f"{target.plugin_dir}/{integration.CONSUMER_MANAGED_FILE[target.consumer]}"
    target_path = repo / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    original = "# Codemap context\n\nHuman-authored notes that must survive.\n"
    _seed(target_path, original)

    plan = integration.build_plan("claude", [target.consumer], None, repo / integration.PROVIDER_DIR)
    integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR)

    mutated = target_path.read_text()
    assert mutated.startswith(original)
    assert "codemap-py:integration:begin" in mutated


def test_apply_writes_lf_only_managed_block(repo: Path) -> None:
    """A first-time apply's managed block is LF-only on disk, regardless of host OS."""
    target = integration.CLAUDE_TARGETS[0]
    plan = integration.build_plan("claude", [target.consumer], None, repo / integration.PROVIDER_DIR)
    integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR)

    target_path = repo / plan["ops"][0]["path"]
    data = target_path.read_bytes()
    assert b"\r\n" not in data
    assert b"codemap-py:integration:begin" in data


def test_apply_reapply_is_idempotent_zero_byte_noop(repo: Path) -> None:
    """Re-running the same approved plan against an already-wired file is a zero-byte no-op, exit 0."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    result1 = integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR)
    assert result1["state"] == "complete"
    target_path = repo / plan["ops"][0]["path"]
    bytes_after_first = target_path.read_bytes()

    result2 = integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR)
    assert result2["state"] == "complete"
    assert target_path.read_bytes() == bytes_after_first


# --------------------------------------------------------------------------------------
# Journal transitions.
# --------------------------------------------------------------------------------------


def test_journal_records_full_success_sequence(repo: Path, tmp_path: Path) -> None:
    """A clean single-target apply journals ``approved -> applying -> verified -> complete``."""
    plan = integration.build_plan("claude", ["oss"], None, repo / integration.PROVIDER_DIR)
    journal_dir = tmp_path / "journal"
    result = integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR, journal_dir=journal_dir)
    assert result["state"] == "complete"
    states = [json.loads(line)["state"] for line in (journal_dir / "journal.jsonl").read_text().splitlines()]
    assert states == ["approved", "applying", "verified", "complete"]


# --------------------------------------------------------------------------------------
# Rollback — partial multi-target failure, both target orders (Phase-4 exit requirement).
# --------------------------------------------------------------------------------------


def _tamper_identity(root: Path, target: integration.ConsumerTarget) -> None:
    dirname = ".claude-plugin" if target.runtime == "claude" else ".codex-plugin"
    manifest_path = root / target.plugin_dir / dirname / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = "tampered-name"
    _seed(manifest_path, json.dumps(manifest))


def _seed_prose(root: Path, consumer: str, text: str) -> Path:
    target = next(t for t in integration.CLAUDE_TARGETS if t.consumer == consumer)
    rel_path = f"{target.plugin_dir}/{integration.CONSUMER_MANAGED_FILE[consumer]}"
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _seed(path, text)
    return path


@pytest.mark.parametrize(
    ("first_consumer", "second_consumer"),
    [pytest.param("oss", "develop", id="oss-then-develop"), pytest.param("develop", "oss", id="develop-then-oss")],
)
def test_rollback_restores_first_target_both_orders(
    repo: Path, tmp_path: Path, first_consumer: str, second_consumer: str
) -> None:
    """First target verified, second fails -> rollback restores the first target's full original file."""
    first_path = _seed_prose(repo, first_consumer, f"{first_consumer} original notes\n")
    _seed_prose(repo, second_consumer, f"{second_consumer} original notes\n")
    original_first_bytes = first_path.read_bytes()

    plan = integration.build_plan("claude", [first_consumer, second_consumer], None, repo / integration.PROVIDER_DIR)
    second_target = next(t for t in integration.CLAUDE_TARGETS if t.consumer == second_consumer)
    _tamper_identity(repo, second_target)

    journal_dir = tmp_path / "journal"
    with pytest.raises(integration.IntegrationError) as exc:
        integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR, journal_dir=journal_dir)

    assert exc.value.detail["state"] == "rollback-succeeded"
    assert exc.value.detail["applied"] == [0]
    assert first_path.read_bytes() == original_first_bytes


def test_rollback_failure_reports_recovery_required(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When rollback itself cannot restore the first target, the engine reports ``recovery-required``.

    Rollback failure is forced deterministically by stubbing ``Journal.save_before_image`` to a
    no-op — the first target then applies successfully (its own write is untouched) but leaves no
    before-image to restore from, so the post-rollback hash check finds the (deleted) file's hash
    doesn't match the plan's recorded ``before_hash`` and reports ``rollback-failed``.
    """
    first_path = _seed_prose(repo, "oss", "oss original notes\n")
    _seed_prose(repo, "develop", "develop original notes\n")

    plan = integration.build_plan("claude", ["oss", "develop"], None, repo / integration.PROVIDER_DIR)
    develop_target = next(t for t in integration.CLAUDE_TARGETS if t.consumer == "develop")
    _tamper_identity(repo, develop_target)
    monkeypatch.setattr(integration.Journal, "save_before_image", lambda self, index, data: None)

    journal_dir = tmp_path / "journal"
    with pytest.raises(integration.IntegrationError) as exc:
        integration.apply_plan(plan, plan["plan_sha256"], repo / integration.PROVIDER_DIR, journal_dir=journal_dir)
    assert exc.value.code == "recovery_required"
    assert exc.value.detail["state"] == "rollback-failed"
    assert exc.value.detail["recovery_commands"]
    assert not first_path.is_file()  # rollback fell back to unlink; no before-image existed to restore


# --------------------------------------------------------------------------------------
# sync — drift refusal before any native command runs (CI-safe: no real claude/codex CLI).
# --------------------------------------------------------------------------------------


def test_sync_refuses_drift_before_native_call(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``sync`` revalidates installed state immediately before every plugin op; drift stops it early."""
    monkeypatch.setattr(integration, "_native_json_probe", lambda argv: None)
    plan = integration.build_plan("claude", ["oss"], "local-candidate", repo / integration.PROVIDER_DIR)

    fake_installed = [{"id": "codemap-py@borda-ai-rig", "version": "9.9.9", "enabled": True}]
    monkeypatch.setattr(integration, "_native_json_probe", lambda argv: fake_installed)
    calls: list[list[str]] = []
    monkeypatch.setattr(integration, "_run_native_required", lambda argv: calls.append(list(argv)))

    with pytest.raises(integration.IntegrationError) as exc:
        integration.sync_plan(plan, plan["plan_sha256"], "local-candidate", repo / integration.PROVIDER_DIR)
    assert exc.value.code == "drift"
    assert len(calls) == 1  # only the marketplace op (no before-state to drift-check) ran


def test_sync_approve_source_mismatch_is_approval_error(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``sync --source`` must match the plan's own recorded source, or approval is rejected."""
    monkeypatch.setattr(integration, "_native_json_probe", lambda argv: None)
    plan = integration.build_plan("claude", ["oss"], "local-candidate", repo / integration.PROVIDER_DIR)
    with pytest.raises(integration.ApprovalError) as exc:
        integration.sync_plan(plan, plan["plan_sha256"], "release", repo / integration.PROVIDER_DIR)
    assert exc.value.code == "source_mismatch"


# --------------------------------------------------------------------------------------
# win_quoting — Windows batch-quoting guard (pure logic; runs on every OS via windows=True).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "unsafe"),
    [
        pytest.param(["install", "oss@borda-ai-rig"], False, id="clean-argv"),
        pytest.param(["install", "oss name with spaces"], True, id="space-in-arg"),
        pytest.param(["install", "oss&whoami"], True, id="ampersand-injection"),
        pytest.param(["install", 'oss"quoted"'], True, id="quote-in-arg"),
        pytest.param(["install", ""], True, id="empty-arg"),
    ],
)
def test_win_quoting_guard_flags_unsafe_argv(arguments: list[str], unsafe: bool) -> None:
    """``_unsafe_windows_batch_argv`` flags spaces/shell-metacharacters unsafe for a ``.bat``/``.cmd`` launcher."""
    assert integration._unsafe_windows_batch_argv("claude.cmd", arguments) is unsafe


def test_win_quoting_resolve_rejects_unsafe_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A Windows batch launcher refuses to resolve argv containing shell metacharacters."""
    fake_cmd = tmp_path / "claude.cmd"
    _seed(fake_cmd, "@echo off\n")
    monkeypatch.setattr(integration.shutil, "which", lambda name: str(fake_cmd))
    with pytest.raises(integration.IntegrationError) as exc:
        integration._resolve_native_command(["claude", "plugin", "install", "oss & whoami"], windows=True)
    assert exc.value.code == "unsafe_windows_argv"


def test_win_quoting_resolve_builds_quoted_line_for_safe_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A safe argv on a Windows batch launcher resolves to one quoted shell command line."""
    fake_cmd = tmp_path / "claude.cmd"
    _seed(fake_cmd, "@echo off\n")
    monkeypatch.setattr(integration.shutil, "which", lambda name: str(fake_cmd))
    resolved, shell = integration._resolve_native_command(
        ["claude", "plugin", "install", "oss@borda-ai-rig"], windows=True
    )
    assert shell is True
    assert resolved == f'"{fake_cmd}" plugin install oss@borda-ai-rig'


# --------------------------------------------------------------------------------------
# demo — disposable evidence only.
# --------------------------------------------------------------------------------------


def test_demo_returns_evidence_confined_to_its_own_report(repo: Path) -> None:
    """``run_demo`` returns check + query evidence and writes only its own disposable report."""
    before = _tree_snapshot(repo)
    demo = integration.run_demo("claude", repo / integration.PROVIDER_DIR)
    assert demo["protocol"] == integration.PROTOCOL_VERSION
    assert "check" in demo
    assert "query_evidence" in demo
    assert Path(demo["report_path"]).is_file()

    after = _tree_snapshot(repo)
    changed = {k for k in after if after.get(k) != before.get(k)}
    assert all(k.startswith(".reports/integrate/") for k in changed)


def test_demo_cli_exits_zero_with_no_index_built(repo: Path) -> None:
    """``integrate demo`` exits 0 when there is simply no index yet (not a failure)."""
    code = integration.run(["demo", "--runtime", "claude"], repo / integration.PROVIDER_DIR)
    assert code == 0
