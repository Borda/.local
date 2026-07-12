#!/usr/bin/env python3
"""Run explicit paid paired Codex model-route calibration campaigns."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_contract import build_prompt, candidate_findings, prompt_sha256, role_context, task_contract_sha256

PRICING_REF = "normalized-token-v1:uncached+0.1*cached+4*output"


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object from a file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one stable, human-readable JSON snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_input_snapshot(
    out_dir: Path,
    cases_payload: dict[str, Any],
    tasks_payload: dict[str, Any],
    policy_payload: dict[str, Any],
    root: Path,
    roles: set[str],
) -> Path:
    """Persist the exact scoring inputs before a paid campaign begins.

    The returned root contains the global and registered role instructions used
    to build every prompt. Scoring against this snapshot remains reproducible
    even when the project files change during a long-running campaign.
    """
    inputs_dir = out_dir / "inputs"
    if inputs_dir.exists():
        raise FileExistsError(f"calibration input snapshot already exists: {inputs_dir}")

    snapshot_root = inputs_dir / "root"
    snapshot_codex = snapshot_root / ".codex"
    snapshot_agents = snapshot_codex / "agents"
    snapshot_agents.mkdir(parents=True)
    (snapshot_codex / "AGENTS.md").write_text(
        (root / ".codex" / "AGENTS.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for role in sorted(roles):
        source = root / ".codex" / "agents" / f"{role}.toml"
        (snapshot_agents / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    _write_json(inputs_dir / "behavioral-cases.json", cases_payload)
    _write_json(inputs_dir / "live-ab-tasks.json", tasks_payload)
    _write_json(inputs_dir / "live-route-policy.json", policy_payload)
    _write_json(
        inputs_dir / "manifest.json",
        {
            "schema_version": 1,
            "roles": sorted(roles),
            "score_inputs": {
                "cases": "inputs/behavioral-cases.json",
                "root": "inputs/root",
                "route_policy": "inputs/live-route-policy.json",
                "tasks": "inputs/live-ab-tasks.json",
            },
        },
    )
    for role in roles:
        role_context(snapshot_root, role)
    return snapshot_root


def _response_schema() -> dict[str, Any]:
    """Return the strict response schema used for every paired model call."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reported_findings", "confidence"],
        "properties": {
            "reported_findings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }


def _validate_response(response: dict[str, Any]) -> None:
    """Validate constraints unsupported by the API response-schema subset."""
    findings = response.get("reported_findings")
    confidence = response.get("confidence")
    if not isinstance(findings, list) or not all(isinstance(item, str) for item in findings):
        raise ValueError("live-response-findings-invalid")
    if len(findings) != len(set(findings)):
        raise ValueError("live-response-findings-duplicate")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("live-response-confidence-invalid")


def _prepare_workspace(out_dir: Path, label: str, fixture_files: dict[str, str]) -> Path:
    """Create one isolated fixture workspace without accepting path traversal."""
    workspace = (out_dir / "workspaces" / label).resolve()
    workspace_root = (out_dir / "workspaces").resolve()
    if workspace.exists():
        raise FileExistsError(f"calibration workspace already exists: {workspace}")
    workspace.mkdir(parents=True)
    for relative, content in fixture_files.items():
        if not isinstance(relative, str) or not isinstance(content, str):
            raise ValueError("fixture_files must map string paths to string contents")
        destination = (workspace / relative).resolve()
        if not destination.is_relative_to(workspace_root) or not destination.is_relative_to(workspace):
            raise ValueError(f"fixture path escapes workspace: {relative!r}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return workspace


def _find_usage(value: Any) -> list[dict[str, int]]:
    """Recursively collect token-usage objects from Codex JSON events."""
    found: list[dict[str, int]] = []
    if isinstance(value, dict):
        if "input_tokens" in value and "output_tokens" in value:
            found.append(
                {
                    "input_tokens": int(value.get("input_tokens", 0)),
                    "cached_input_tokens": int(value.get("cached_input_tokens", 0)),
                    "output_tokens": int(value.get("output_tokens", 0)),
                }
            )
        for child in value.values():
            found.extend(_find_usage(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_usage(child))
    return found


def _usage_from_jsonl(stdout: str) -> dict[str, int]:
    """Extract the last cumulative token usage from Codex JSONL output."""
    usages: list[dict[str, int]] = []
    for line in stdout.splitlines():
        if line.strip():
            usages.extend(_find_usage(json.loads(line)))
    if not usages:
        raise ValueError("codex-exec-token-usage-missing")
    return max(usages, key=lambda item: item["input_tokens"] + item["output_tokens"])


def _cost_units(usage: dict[str, int]) -> float:
    """Compute the conservative normalized token-cost proxy."""
    uncached = max(usage["input_tokens"] - usage["cached_input_tokens"], 0)
    return round(uncached + 0.1 * usage["cached_input_tokens"] + 4.0 * usage["output_tokens"], 3)


def _require_local_subscription_run() -> None:
    """Fail unless paid execution is local and uses ChatGPT subscription auth."""
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit("live-paid-run-disabled-in-ci")
    if os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("live-paid-run-api-key-auth-disallowed")
    status = subprocess.run(
        ["codex", "login", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = f"{status.stdout}\n{status.stderr}"
    if status.returncode != 0 or "Logged in using ChatGPT" not in output:
        raise SystemExit("live-paid-run-requires-chatgpt-subscription-login")


def _run_model(
    work_dir: Path,
    out_dir: Path,
    prompt: str,
    model: str,
    effort: str,
    label: str,
    timeout_seconds: int,
    sandbox: str,
) -> tuple[dict[str, Any], dict[str, int], int, int]:
    """Execute one isolated Codex call and return response, usage, latency, and exit code."""
    last_message = out_dir / f"{label}.response.json"
    events = out_dir / f"{label}.events.jsonl"
    stderr_path = out_dir / f"{label}.stderr.txt"
    schema_path = out_dir / "response-schema.json"
    started = time.monotonic()
    process = subprocess.Popen(
        [
            "codex",
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "--cd",
            str(work_dir),
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message),
            prompt,
        ],
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        stderr = f"{stderr or ''}\ntimeout after {timeout_seconds} seconds\n"
        exit_code = 124
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    events.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")
    latency_ms = round((time.monotonic() - started) * 1000)
    response = _read_json(last_message) if exit_code == 0 and last_message.exists() else {}
    if exit_code == 0:
        try:
            _validate_response(response)
        except ValueError as exc:
            stderr_path.write_text(f"{stderr or ''}\n{exc}\n", encoding="utf-8")
            exit_code = 1
            response = {}
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    if stdout.strip():
        try:
            usage = _usage_from_jsonl(stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            stderr_path.write_text(f"{stderr or ''}\n{exc}\n", encoding="utf-8")
            exit_code = exit_code or 1
    return response, usage, latency_ms, exit_code


def _run_gate(work_dir: Path, out_dir: Path, label: str, command: str, timeout_seconds: int) -> int:
    """Run one argv-only executable gate and persist its output."""
    argv = shlex.split(command)
    if not argv:
        raise ValueError("tool-use task needs a non-empty gate_command")
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=work_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        stderr = f"{stderr or ''}\ntimeout after {timeout_seconds} seconds\n"
        exit_code = 124
    elapsed_ms = round((time.monotonic() - started) * 1000)
    (out_dir / f"{label}.gate.txt").write_text(
        f"command={argv!r}\nexit_code={exit_code}\nelapsed_ms={elapsed_ms}\n\nstdout:\n{stdout or ''}\n\nstderr:\n{stderr or ''}",
        encoding="utf-8",
    )
    return exit_code


def _observation(
    *,
    case: dict[str, Any],
    route_id: str,
    role: str,
    task_type: str,
    task_contract_sha: str,
    campaign_id: str,
    pair_id: str,
    pair_role: str,
    model: str,
    effort: str,
    prompt: str,
    response: dict[str, Any],
    usage: dict[str, int],
    latency_ms: int,
    exit_code: int,
    evidence_scope: str,
    gate_exit_code: int,
) -> dict[str, Any]:
    """Build one strict live observation row from execution evidence."""
    timed_out = exit_code == 124 or gate_exit_code == 124
    outcome = "pass" if exit_code == gate_exit_code == 0 else "timeout" if timed_out else "fail"
    return {
        "case_id": case["id"],
        "target": case["target"],
        "source": "live-codex-exec",
        "run_id": pair_id,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reported_findings": response.get("reported_findings", []),
        "confidence": response.get("confidence", 0.0),
        "pair_id": pair_id,
        "campaign_id": campaign_id,
        "pair_role": pair_role,
        "route_id": route_id,
        "role": role,
        "model": model,
        "reasoning_effort": effort,
        "prompt_sha256": prompt_sha256(prompt),
        "task_type": task_type,
        "task_contract_sha256": task_contract_sha,
        "evidence_scope": evidence_scope,
        **usage,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "tool_failure_count": 0 if exit_code == 0 else 1,
        "check_failure_count": 0 if gate_exit_code == 0 else 1,
        "estimated_cost_units": _cost_units(usage),
        "pricing_ref": PRICING_REF,
    }


def main() -> int:
    """Plan or execute a paid paired calibration campaign."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path, help="Behavioral case-set JSON.")
    parser.add_argument("--tasks", required=True, type=Path, help="Live A/B task-contract JSON.")
    parser.add_argument("--route-policy", required=True, type=Path, help="Paired route acceptance policy JSON.")
    parser.add_argument("--out", required=True, type=Path, help="Output directory for plans and observations.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root containing .codex agents.")
    parser.add_argument("--route", action="append", default=[], help="Route ID to run; repeat to select multiple.")
    parser.add_argument("--campaigns", type=int, help="Campaign count override; defaults to route policy.")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Timeout for each paid Codex call.")
    parser.add_argument(
        "--confirm-paid-run",
        choices=("chatgpt-subscription",),
        help="Execute locally with ChatGPT subscription auth; omitted means plan only.",
    )
    args = parser.parse_args()

    cases_payload = _read_json(args.cases)
    cases = {case["id"]: case for case in cases_payload["cases"]}
    tasks_payload = _read_json(args.tasks)
    policy_payload = _read_json(args.route_policy)
    tasks = tasks_payload["routes"]
    policy = policy_payload["routes"]
    selected_routes = args.route or sorted(policy)
    unknown_routes = sorted(set(selected_routes) - set(policy))
    if unknown_routes:
        raise ValueError(f"unknown routes: {unknown_routes}")
    roles: set[str] = set()
    for route_id in selected_routes:
        if route_id not in tasks:
            raise ValueError(f"live tasks missing route: {route_id}")
        for index, task in enumerate(tasks[route_id], start=1):
            if task.get("case_id") not in cases:
                raise ValueError(f"live task case missing: {route_id}:{index}")
            role = task.get("role")
            if not isinstance(role, str) or not role:
                raise ValueError(f"live task role missing: {route_id}:{index}")
            role_context(args.root, role)
            roles.add(role)
    required_campaigns = max(policy[route]["min_campaigns"] for route in selected_routes)
    campaigns = args.campaigns if args.campaigns is not None else required_campaigns
    if campaigns < 1:
        raise ValueError("campaigns must be a positive integer")
    call_count = campaigns * sum(2 * len(tasks[route]) for route in selected_routes)
    if not args.confirm_paid_run:
        scopes = {
            route: sorted({task.get("evidence_scope", "classification") for task in tasks[route]})
            for route in selected_routes
        }
        print(
            json.dumps(
                {
                    "status": "planned",
                    "routes": selected_routes,
                    "paid_model_calls": call_count,
                    "campaigns": campaigns,
                    "strict_acceptance_possible": all(
                        campaigns >= policy[route]["min_campaigns"] for route in selected_routes
                    ),
                    "evidence_scopes": scopes,
                    "paid_run_input_snapshot": "inputs/manifest.json",
                    "required_confirmation": "--confirm-paid-run=chatgpt-subscription",
                }
            )
        )
        return 0

    _require_local_subscription_run()
    args.out.mkdir(parents=True, exist_ok=True)
    snapshot_root = _write_input_snapshot(
        args.out,
        cases_payload,
        tasks_payload,
        policy_payload,
        args.root,
        roles,
    )
    (args.out / "response-schema.json").write_text(json.dumps(_response_schema(), indent=2) + "\n", encoding="utf-8")
    observations = args.out / "observations.jsonl"
    rows: list[dict[str, Any]] = []
    campaign_prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for route_id in selected_routes:
        route = policy[route_id]
        for campaign_index in range(1, campaigns + 1):
            campaign_id = f"{campaign_prefix}:c{campaign_index}"
            for index, task in enumerate(tasks[route_id], start=1):
                case = cases[task["case_id"]]
                evidence_scope = task.get("evidence_scope", "classification")
                role = task["role"]
                prompt = build_prompt(
                    case,
                    candidate_findings(case["id"], cases),
                    task,
                    role_context(snapshot_root, role),
                )
                pair_id = f"{campaign_id}:{route_id}:{index}"
                pair_roles = (
                    ("baseline", "candidate") if (campaign_index + index) % 2 == 0 else ("candidate", "baseline")
                )
                for pair_role in pair_roles:
                    model = route[f"{pair_role}_model"]
                    label = f"c{campaign_index}-{route_id}-{index}-{pair_role}"
                    if evidence_scope == "tool-use":
                        work_dir = _prepare_workspace(args.out, label, task["fixture_files"])
                        sandbox = "workspace-write"
                    else:
                        work_dir = args.root.resolve()
                        sandbox = "read-only"
                    response, usage, latency_ms, exit_code = _run_model(
                        work_dir,
                        args.out,
                        prompt,
                        model,
                        route["effort"],
                        label,
                        args.timeout_seconds,
                        sandbox,
                    )
                    gate_exit_code = (
                        _run_gate(work_dir, args.out, label, task["gate_command"], args.timeout_seconds)
                        if evidence_scope == "tool-use" and exit_code == 0
                        else 0
                        if evidence_scope == "classification" and exit_code == 0
                        else 1
                    )
                    rows.append(
                        _observation(
                            case=case,
                            route_id=route_id,
                            role=role,
                            task_type=task["task_type"],
                            task_contract_sha=task_contract_sha256(task),
                            campaign_id=campaign_id,
                            pair_id=pair_id,
                            pair_role=pair_role,
                            model=model,
                            effort=route["effort"],
                            prompt=prompt,
                            response=response,
                            usage=usage,
                            latency_ms=latency_ms,
                            exit_code=exit_code,
                            evidence_scope=evidence_scope,
                            gate_exit_code=gate_exit_code,
                        )
                    )
                    observations.write_text(
                        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
                    )
                    if exit_code != 0:
                        raise SystemExit(f"live-call-failed:{label}:see {label}.stderr.txt and {label}.events.jsonl")
    print(observations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
