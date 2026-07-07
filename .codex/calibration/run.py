#!/usr/bin/env python3
"""Run Codex calibration checks and write the calibration result artifact."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILLS = (
    "review",
    "develop",
    "resolve",
    "audit",
    "calibrate",
    "release",
    "investigate",
    "sync",
    "manage",
    "analyse",
    "optimize",
    "research",
)
AGENTS = (
    "sw-engineer",
    "qa-specialist",
    "squeezer",
    "doc-scribe",
    "security-auditor",
    "data-steward",
    "cicd-steward",
    "linting-expert",
    "oss-shepherd",
    "solution-architect",
    "web-explorer",
    "curator",
    "challenger",
    "scientist",
)
HIGH_MODEL_AGENTS = {
    "sw-engineer",
    "qa-specialist",
    "squeezer",
    "data-steward",
    "cicd-steward",
    "security-auditor",
    "solution-architect",
    "challenger",
    "scientist",
}
MINI_MODEL_AGENTS = {"doc-scribe", "web-explorer", "oss-shepherd", "curator", "linting-expert"}
XHIGH_EFFORT_AGENTS = {"challenger", "solution-architect", "security-auditor", "scientist"}
HIGH_EFFORT_AGENTS = {"sw-engineer", "qa-specialist", "squeezer", "data-steward", "cicd-steward"}
MEDIUM_EFFORT_AGENTS = {"doc-scribe", "web-explorer", "oss-shepherd", "curator", "linting-expert"}


@dataclass(slots=True)
class Paths:
    """Hold all paths used by the calibration run."""

    root: Path
    timestamp: str
    out_dir: Path
    project_cfg: Path
    home_cfg: Path
    tasks: Path
    benchmarks: Path
    behavioral_cases: Path
    behavioral_observations: Path
    behavioral_scorer: Path
    behavioral_result: Path
    quality_gates: Path
    native_skill_contract: Path
    run_gates: Path
    run_py: Path
    write_result_py: Path
    collect_diff: Path
    collect_pr: Path
    find_review_report: Path
    validate_artifacts: Path
    checks: Path
    leaks: Path
    recommendations: Path
    result: Path

    @classmethod
    def create(cls) -> "Paths":
        """Create the output directory and return resolved calibration paths."""
        root = Path(__file__).resolve().parents[2]
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = root / ".reports" / "codex" / "calibration" / timestamp
        out_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            timestamp=timestamp,
            out_dir=out_dir,
            project_cfg=root / ".codex" / "config.toml",
            home_cfg=Path.home() / ".codex" / "config.toml",
            tasks=root / ".codex" / "calibration" / "tasks.json",
            benchmarks=root / ".codex" / "calibration" / "benchmarks.json",
            behavioral_cases=root / ".codex" / "calibration" / "behavioral-cases.json",
            behavioral_observations=root / ".codex" / "calibration" / "behavioral-observations.jsonl",
            behavioral_scorer=root / ".codex" / "calibration" / "score_behavioral.py",
            behavioral_result=out_dir / "behavioral.json",
            quality_gates=root / ".codex" / "skills" / "_shared" / "quality-gates.md",
            native_skill_contract=root / ".codex" / "skills" / "_shared" / "native-skill-contract.md",
            run_gates=root / ".codex" / "skills" / "_shared" / "run-gates.sh",
            run_py=root / ".codex" / "calibration" / "run.py",
            write_result_py=root / ".codex" / "skills" / "_shared" / "write-result.py",
            collect_diff=root / ".codex" / "skills" / "_shared" / "collect-diff.sh",
            collect_pr=root / ".codex" / "skills" / "_shared" / "collect-pr.sh",
            find_review_report=root / ".codex" / "skills" / "_shared" / "find-review-report.py",
            validate_artifacts=root / ".codex" / "skills" / "_shared" / "validate-artifacts.py",
            checks=out_dir / "checks.txt",
            leaks=out_dir / "leaks.txt",
            recommendations=out_dir / "recommendations.md",
            result=out_dir / "result.json",
        )


@dataclass(slots=True)
class CalibrationRun:
    """Track mutable calibration state and provide check helpers."""

    paths: Paths
    fails: int = 0
    leaks: int = 0
    checks_failed: list[str] = field(default_factory=list)

    def mark_check_failed(self, check_id: str) -> None:
        """Record a failed check once."""
        if check_id not in self.checks_failed:
            self.checks_failed.append(check_id)

    def append_check(self, line: str) -> None:
        """Append a single check detail line."""
        append_line(self.paths.checks, line)

    def append_leak(self, line: str) -> None:
        """Append a single leak detail line."""
        append_line(self.paths.leaks, line)

    def leak_only(self, check_id: str, line: str) -> None:
        """Record a leak that should fail status through leak count."""
        self.append_leak(line)
        self.mark_check_failed(check_id)
        self.leaks += 1

    def fail_and_leak(self, check_id: str, line: str, count: int = 1) -> None:
        """Record a check failure with matching fail and leak counts."""
        self.append_leak(line)
        self.mark_check_failed(check_id)
        self.fails += count
        self.leaks += count


def append_line(path: Path, line: str) -> None:
    """Append one UTF-8 line to a file, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_text(path: Path) -> str:
    """Read a text file or return an empty string when it is absent."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def normalize_regex(pattern: str) -> str:
    """Convert shell-era POSIX space classes to Python regex syntax."""
    return pattern.replace("[[:space:]]", r"\s")


def check_contains(run: CalibrationRun, file: Path, pattern: str, check_id: str) -> None:
    """Check that a file contains a case-insensitive regex pattern."""
    text = read_text(file)
    try:
        matched = re.search(normalize_regex(pattern), text, flags=re.IGNORECASE | re.MULTILINE) is not None
    except re.error:
        matched = pattern.lower() in text.lower()
    if not matched:
        run.leak_only(check_id, f"missing:{pattern}:{file}")


def top_level_setting(file: Path, key: str) -> str | None:
    """Read a top-level TOML string setting before tables or developer instructions."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*(?:#.*)?$")
    for line in read_text(file).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^\s*developer_instructions\s*=", line) or re.match(r"^\s*\[", line):
            return None
        match = pattern.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            return raw[1:-1]
        return raw
    return None


def check_model(run: CalibrationRun, file: Path, label: str, check_id: str, expected: str = "gpt-5.5") -> None:
    """Check the configured top-level model value."""
    if top_level_setting(file, "model") == expected:
        run.append_check(f"{label}:model=ok")
        return
    run.append_check(f"{label}:model=fail")
    run.fail_and_leak(check_id, f"model-not-{expected}:{file}")


def check_review_model(run: CalibrationRun, file: Path, label: str) -> None:
    """Check the project review model policy."""
    if re.search(r'^\s*review_model\s*=\s*"gpt-5\.5"', read_text(file), flags=re.MULTILINE):
        run.append_check(f"{label}:review_model=ok")
        return
    run.append_check(f"{label}:review_model=fail")
    run.fail_and_leak("review-model-policy", f"review-model-not-gpt-5.5:{file}")


def check_reasoning_effort(run: CalibrationRun, file: Path, expected: str, label: str, check_id: str) -> None:
    """Check the configured model reasoning effort."""
    pattern = rf'^\s*model_reasoning_effort\s*=\s*"{re.escape(expected)}"'
    if re.search(pattern, read_text(file), flags=re.MULTILINE):
        run.append_check(f"{label}:effort={expected}")
        return
    run.append_check(f"{label}:effort=fail")
    run.fail_and_leak(check_id, f"reasoning-effort-mismatch:{label}:expected={expected}:{file}")


def check_no_deprecated_active_models(run: CalibrationRun) -> None:
    """Reject active deprecated model names in project and agent configs."""
    files = [run.paths.project_cfg, *sorted((run.paths.root / ".codex" / "agents").glob("*.toml"))]
    pattern = re.compile(r'^\s*(model|review_model)\s*=\s*"gpt-5\.(2|3-codex)"', flags=re.MULTILINE)
    for file in files:
        if pattern.search(read_text(file)):
            run.fail_and_leak("deprecated-model-policy", f"deprecated-active-model:{file}")


def check_behavioral_cases_version(run: CalibrationRun) -> None:
    """Ensure behavioral case versions only move one commit-relative step."""
    if not run.paths.behavioral_cases.exists():
        return
    if not (run.paths.root / ".git").exists():
        run.append_check("behavioral-version=skipped:no-git")
        return

    head_cases = run.paths.out_dir / "behavioral-cases.head.json"
    git_result = subprocess.run(
        ["git", "show", "HEAD:.codex/calibration/behavioral-cases.json"],
        cwd=run.paths.root,
        text=True,
        capture_output=True,
        check=False,
    )
    if git_result.returncode != 0:
        run.append_check("behavioral-version=skipped:no-head-version")
        return
    head_cases.write_text(git_result.stdout, encoding="utf-8")

    try:
        head_version = read_json_version(head_cases)
        current_version = read_json_version(run.paths.behavioral_cases)
        if not same_or_single_commit_bump(parse_version(head_version), parse_version(current_version)):
            raise ValueError(
                "current version must equal HEAD or be one commit-relative bump: "
                f"HEAD={head_version}, current={current_version}"
            )
    except Exception as exc:  # noqa: BLE001 - calibration must report the concrete parsing/version blocker.
        run.fail_and_leak("behavioral-version-policy", f"behavioral-version-gap:{exc}")
        return

    run.append_check(f"behavioral-version=ok:HEAD={head_version}:current={current_version}")


def read_json_version(path: Path) -> str:
    """Read a required string version from a JSON fixture file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"missing string version in {path}")
    return version.strip()


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted numeric version into comparable integer parts."""
    parts = value.split(".")
    if not parts or any(not part.isdecimal() for part in parts):
        raise ValueError(f"version must be dotted numeric: {value!r}")
    return tuple(int(part) for part in parts)


def same_or_single_commit_bump(head: tuple[int, ...], current: tuple[int, ...]) -> bool:
    """Return whether current is unchanged or one version step from HEAD."""
    width = max(len(head), len(current))
    head_parts = head + (0,) * (width - len(head))
    current_parts = current + (0,) * (width - len(current))
    if current_parts == head_parts:
        return True
    for index, (head_part, current_part) in enumerate(zip(head_parts, current_parts, strict=True)):
        if head_part == current_part:
            continue
        if current_part != head_part + 1:
            return False
        return all(part == 0 for part in current_parts[index + 1 :])
    return False


def check_skill_frontmatter(run: CalibrationRun, file: Path, skill: str) -> None:
    """Validate minimal YAML frontmatter for a skill file."""
    lines = read_text(file).splitlines()
    ok = len(lines) >= 4 and lines[0] == "---"
    if ok:
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            ok = False
        else:
            frontmatter = lines[1:end]
            ok = any(line.startswith("name:") for line in frontmatter) and any(
                line.startswith("description:") for line in frontmatter
            )
    if ok:
        run.append_check(f"skill-frontmatter:{skill}=ok")
        return
    run.fail_and_leak("skill-schema-all", f"skill-frontmatter-invalid:{file}")


def expected_agent_model(agent: str) -> str | None:
    """Return the expected model for an agent."""
    if agent in HIGH_MODEL_AGENTS:
        return "gpt-5.5"
    if agent in MINI_MODEL_AGENTS:
        return "gpt-5.4-mini"
    return None


def expected_agent_effort(agent: str) -> str | None:
    """Return the expected reasoning effort for an agent."""
    if agent in XHIGH_EFFORT_AGENTS:
        return "xhigh"
    if agent in HIGH_EFFORT_AGENTS:
        return "high"
    if agent in MEDIUM_EFFORT_AGENTS:
        return "medium"
    return None


def check_agent_model(run: CalibrationRun, agent: str, file: Path) -> None:
    """Check an agent model against policy."""
    expected = expected_agent_model(agent)
    if expected is None:
        run.fail_and_leak("agent-model-policy", f"agent-model-policy-missing:{agent}")
        return
    if top_level_setting(file, "model") == expected:
        run.append_check(f"agent-model:{agent}={expected}")
        return
    run.fail_and_leak("agent-model-policy", f"agent-model-mismatch:{agent}:expected={expected}:{file}")


def check_agent_effort(run: CalibrationRun, agent: str, file: Path) -> None:
    """Check an agent reasoning effort against policy."""
    expected = expected_agent_effort(agent)
    if expected is None:
        run.fail_and_leak("agent-effort-policy", f"agent-effort-policy-missing:{agent}")
        return
    check_reasoning_effort(run, file, expected, f"agent-effort:{agent}", "agent-effort-policy")


def check_core_configs(run: CalibrationRun) -> None:
    """Run project, skill, shared contract, and agent configuration checks."""
    run.paths.checks.write_text(f"calibration-start:{run.paths.timestamp}\n", encoding="utf-8")
    check_model(run, run.paths.project_cfg, "project-config", "project-model-default")
    check_model(run, run.paths.home_cfg, "home-config", "home-model-default")
    check_review_model(run, run.paths.project_cfg, "project-config")
    check_reasoning_effort(run, run.paths.project_cfg, "high", "project-config", "reasoning-effort-policy")
    check_no_deprecated_active_models(run)

    for skill in SKILLS:
        skill_file = run.paths.root / ".codex" / "skills" / skill / "SKILL.md"
        if not skill_file.exists():
            run.fail_and_leak("skill-schema-all", f"missing-skill:{skill}")
            continue
        check_skill_frontmatter(run, skill_file, skill)
        check_contains(run, skill_file, "^# ", "skill-schema-all")
        check_contains(run, skill_file, "Input Schema", "native-skill-contract")
        check_contains(run, skill_file, "Workflow", "skill-schema-all")
        check_contains(run, skill_file, "Fail-[Ff]ast Rules", "native-skill-contract")
        check_contains(run, skill_file, "Quality Gates", "native-skill-contract")
        check_contains(run, skill_file, "Calibration Hooks", "native-skill-contract")
        check_contains(run, skill_file, "Output Contract", "skill-schema-all")
        check_contains(run, skill_file, "quality-gates", "skill-schema-all")
        check_contains(run, skill_file, f".reports/codex/{skill}/", "skill-schema-all")
        check_contains(run, skill_file, "result-template.json", "skill-schema-all")
        template_file = skill_file.with_name("result-template.json")
        if not template_file.exists():
            run.fail_and_leak("skill-schema-all", f"missing-result-template:{skill}")
            continue
        try:
            json.loads(template_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            run.fail_and_leak("skill-schema-all", f"invalid-result-template:{skill}:{exc.lineno}")
            continue
        for field_name in ("status", "checks_run", "checks_failed", "findings", "confidence", "artifact_path"):
            check_contains(run, template_file, f'"{field_name}"', "skill-schema-all")
        check_contains(run, run.paths.project_cfg, rf'path\s*=\s*"skills/{skill}"', "skill-registration-project")
        check_contains(run, run.paths.home_cfg, rf'path\s*=\s*"(.*\/)?skills/{skill}"', "skill-registration-home")

    for file, check_id in (
        (run.paths.tasks, "fixed-task-set"),
        (run.paths.benchmarks, "benchmark-pattern-checks"),
        (run.paths.behavioral_cases, "behavioral-metrics"),
        (run.paths.behavioral_observations, "behavioral-metrics"),
        (run.paths.behavioral_scorer, "behavioral-metrics"),
    ):
        if not file.exists():
            name = file.stem.replace("-", "_")
            run.fail_and_leak(check_id, f"missing-{name}:{file}")

    check_behavioral_cases_version(run)
    check_shared_confidence_contracts(run)
    check_agents(run)


def check_shared_confidence_contracts(run: CalibrationRun) -> None:
    """Check shared confidence policy wording in shared contract files."""
    for shared_contract in (run.paths.quality_gates, run.paths.native_skill_contract):
        if not shared_contract.exists():
            run.fail_and_leak("confidence-policy", f"missing-shared-confidence-contract:{shared_contract}")
            continue
        check_contains(run, shared_contract, "confidence-not-acceptable", "confidence-policy")
        check_contains(run, shared_contract, "confidence-very-questionable", "confidence-policy")
        check_contains(run, shared_contract, "cautious-low", "confidence-policy")
        check_contains(run, shared_contract, "fair but not automatic", "confidence-policy")
        check_contains(run, shared_contract, "confidence_gap_closures", "confidence-policy")
        check_contains(run, shared_contract, "confidence_recovery", "confidence-policy")


def check_agents(run: CalibrationRun) -> None:
    """Run registration, schema, confidence, model, and effort checks for agents."""
    for agent in AGENTS:
        check_contains(run, run.paths.project_cfg, rf"\[agents\.{agent}\]", "agent-registration-project")
        check_contains(run, run.paths.home_cfg, rf"\[agents\.{agent}\]", "agent-registration-home")
        agent_file = run.paths.root / ".codex" / "agents" / f"{agent}.toml"
        if not agent_file.exists():
            run.fail_and_leak("agent-schema-all", f"missing-agent-file:{agent}")
            run.mark_check_failed("agent-model-policy")
            run.mark_check_failed("agent-effort-policy")
            continue
        for pattern in (
            r"^name\s*=",
            "developer_instructions",
            "Scope",
            "Boundaries",
            "Evidence Standard",
            "TRIGGER when",
            "SKIP when",
            "NOT for",
            "Output Format",
            "Output Contract",
        ):
            check_contains(
                run,
                agent_file,
                pattern,
                "agent-schema-all" if pattern in {r"^name\s*=", "developer_instructions"} else "native-agent-contract",
            )
        check_contains(run, agent_file, "confidence-band status", "confidence-policy")
        check_contains(run, agent_file, "confidence recovery", "confidence-policy")
        check_contains(run, agent_file, "confidence-gap closures", "confidence-policy")
        check_agent_model(run, agent, agent_file)
        check_agent_effort(run, agent, agent_file)


def check_native_runtime_leaks(run: CalibrationRun) -> None:
    """Scan native skills and agents for non-Codex runtime vocabulary leaks."""
    targets = sorted((run.paths.root / ".codex" / "skills").glob("*/SKILL.md"))
    targets.extend(sorted((run.paths.root / ".codex" / "agents").glob("*.toml")))
    patterns = {
        "external-path-variable": re.compile("CLAUDE_PLUGIN_ROOT"),
        "interactive-widget": re.compile("AskUserQuestion"),
        "task-widget-create": re.compile("TaskCreate"),
        "task-widget-update": re.compile("TaskUpdate"),
        "background-runner": re.compile("run_in_background"),
        "web-fetch-tool": re.compile("WebFetch"),
        "web-search-tool": re.compile("WebSearch"),
        "frontmatter-tools": re.compile(r"^tools\s*:", re.MULTILINE),
        "frontmatter-max-turns": re.compile(r"^maxTurns\s*:", re.MULTILINE),
        "frontmatter-isolation": re.compile(r"^isolation\s*:", re.MULTILINE),
        "frontmatter-memory": re.compile(r"^memory\s*:", re.MULTILINE),
        "frontmatter-tool-allowlist": re.compile("allowed-tools"),
        "frontmatter-disable-model": re.compile("disable-model-invocation"),
    }
    found = 0
    for path in targets:
        text = read_text(path)
        for label, pattern in patterns.items():
            if pattern.search(text):
                run.append_leak(f"native-runtime-leak:{label}:{path.relative_to(run.paths.root)}")
                found += 1
    if found:
        run.mark_check_failed("native-runtime-leakage")
        run.fails += found
        run.leaks += found


def is_executable(path: Path) -> bool:
    """Return whether a path exists and is executable."""
    return path.exists() and os.access(path, os.X_OK)


def run_command(args: list[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command and return captured text output."""
    return subprocess.run([str(arg) for arg in args], cwd=cwd, text=True, capture_output=True, check=False)


def check_python_syntax(run: CalibrationRun, path: Path, label: str) -> None:
    """Compile a Python file and record a shared-script selftest failure on syntax errors."""
    if not path.exists():
        run.fail_and_leak("shared-script-selftests", f"shared-script-missing:{path}")
        return
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(run.paths.out_dir / "pycache")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        run.fail_and_leak("shared-script-selftests", f"shared-script-syntax:{label}")


def check_shared_scripts(run: CalibrationRun) -> None:
    """Check shared helper executability and smoke selftests."""
    for script in (
        run.paths.run_gates,
        run.paths.run_py,
        run.paths.write_result_py,
        run.paths.collect_diff,
        run.paths.collect_pr,
        run.paths.find_review_report,
        run.paths.validate_artifacts,
    ):
        if not is_executable(script):
            run.fail_and_leak("shared-script-selftests", f"shared-script-not-executable:{script}")

    embedded_python_marker = "python3" + " -"
    if embedded_python_marker in read_text(run.paths.run_py):
        run.fail_and_leak("shared-script-selftests", f"shared-script-embedded-python:{run.paths.run_py}")
    if embedded_python_marker in read_text(run.paths.write_result_py):
        run.fail_and_leak("shared-script-selftests", f"shared-script-embedded-python:{run.paths.write_result_py}")
    check_python_syntax(run, run.paths.run_py, "run.py")
    check_python_syntax(run, run.paths.write_result_py, "write-result.py")
    run_selftests(run)


def run_selftests(run: CalibrationRun) -> None:
    """Run smoke tests for shared helpers that are safe offline."""
    selftest_dir = run.paths.out_dir / "selftest"
    selftest_dir.mkdir(parents=True, exist_ok=True)

    if is_executable(run.paths.run_gates):
        result = run_command(
            [
                run.paths.run_gates,
                "--out",
                selftest_dir / "gates",
                "--lint",
                "true",
                "--format",
                "true",
                "--types",
                "true",
                "--tests",
                "true",
                "--review",
                "true",
            ]
        )
        if result.returncode != 0 or not (selftest_dir / "gates" / "gates.json").exists():
            run.fail_and_leak("shared-script-selftests", "selftest-missing:gates.json")

    if is_executable(run.paths.write_result_py):
        metadata = {
            "confidence_gaps": ["synthetic writer selftest does not execute project behavior"],
            "confidence_gap_closures": [
                {
                    "gap": "synthetic writer selftest does not execute project behavior",
                    "status": "unresolved",
                    "rationale": "writer selftest validates result shape only",
                }
            ],
            "confidence_recovery": {
                "initial_confidence": 0.9,
                "final_confidence": 0.95,
                "status": "fair",
                "evidence": ["write-result selftest produced a JSON artifact"],
                "recovery_actions": ["included mandatory confidence metadata"],
                "remaining_limits": [],
            },
        }
        result = run_write_result(run, selftest_dir / "result.json", metadata)
        if result.returncode != 0 or not (selftest_dir / "result.json").exists():
            run.fail_and_leak("shared-script-selftests", "selftest-missing:result.json")

    if is_executable(run.paths.collect_diff):
        result = run_command(
            [run.paths.collect_diff, "--scope", "working-tree", "--out", selftest_dir / "diff"], cwd=run.paths.root
        )
        expected_files = ("status.txt", "diff.patch", "files.txt", "diffstat.txt", "numstat.txt", "untracked.txt")
        for expected in expected_files:
            if result.returncode != 0 or not (selftest_dir / "diff" / expected).exists():
                run.fail_and_leak("shared-script-selftests", f"selftest-missing:collect-diff:{expected}")

    if is_executable(run.paths.collect_pr):
        result = run_command(["bash", "-n", run.paths.collect_pr])
        if result.returncode != 0:
            run.fail_and_leak("shared-script-selftests", "selftest-syntax:collect-pr")

    if is_executable(run.paths.find_review_report):
        selftest_find_review_report(run, selftest_dir)

    if is_executable(run.paths.validate_artifacts) and is_executable(run.paths.write_result_py):
        selftest_validate_artifacts(run, selftest_dir)


def run_write_result(run: CalibrationRun, out_path: Path, metadata: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Run the shared write-result helper with a valid selftest payload."""
    return run_command(
        [
            run.paths.write_result_py,
            "--out",
            out_path,
            "--status",
            "pass",
            "--checks-run",
            "lint,format,types,tests,review",
            "--checks-failed",
            "",
            "--critical",
            "0",
            "--high",
            "0",
            "--medium",
            "0",
            "--low",
            "0",
            "--confidence",
            "0.95",
            "--metadata",
            json.dumps(metadata, separators=(",", ":")),
            "--artifact-path",
            out_path,
        ]
    )


def selftest_find_review_report(run: CalibrationRun, selftest_dir: Path) -> None:
    """Check that find-review-report selects the newest matching report."""
    fixture = selftest_dir / "review-reports"
    older = fixture / "2026-01-01T00-00-00Z"
    newer = fixture / "2026-01-02T00-00-00Z"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    for directory in (older, newer):
        (directory / "result.json").write_text("{}\n", encoding="utf-8")
        (directory / "pr.json").write_text(
            '{"number": 123, "url": "https://github.com/example/repo/pull/123"}\n',
            encoding="utf-8",
        )
    expected = newer / "result.json"
    result = run_command([run.paths.find_review_report, "--target", "#123", "--reports-dir", fixture])
    if result.returncode != 0:
        run.fail_and_leak("shared-script-selftests", "selftest-failed:find-review-report:match")
    elif result.stdout.strip() != str(expected):
        run.fail_and_leak("shared-script-selftests", f"selftest-mismatch:find-review-report:{result.stdout.strip()}")
    missing = run_command([run.paths.find_review_report, "--target", "#999", "--reports-dir", fixture])
    if missing.returncode == 0:
        run.fail_and_leak("shared-script-selftests", "selftest-failed:find-review-report:missing-target")


def selftest_validate_artifacts(run: CalibrationRun, selftest_dir: Path) -> None:
    """Create and validate a minimal develop artifact fixture."""
    validate_dir = selftest_dir / "validate"
    validate_dir.mkdir(parents=True, exist_ok=True)
    (validate_dir / "development-notes.md").write_text(
        "\n".join(
            [
                "# Development Notes",
                "",
                "## Scope",
                "Selftest.",
                "",
                "## Acceptance Criteria",
                "Selftest.",
                "",
                "## Evidence",
                "Selftest.",
                "",
                "## Specialist Policy",
                "Selftest.",
                "",
                "## Gates",
                "Selftest.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (validate_dir / "confidence-calibration.md").write_text(
        "\n".join(
            [
                "# Confidence Calibration",
                "",
                "## Initial Confidence",
                "0.9",
                "",
                "## Objective Evidence",
                "Selftest artifact shape was created and validated locally.",
                "",
                "## Confidence Gaps",
                "No known gaps for this validator selftest.",
                "",
                "## Recovery Actions",
                "Selftest includes the confidence artifact and matching result metadata.",
                "",
                "## Recomputed Confidence",
                "0.95",
                "",
                "## Remaining Limits",
                "None for this synthetic validator fixture.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    metadata = {
        "confidence_gaps": ["synthetic validator selftest does not execute project behavior"],
        "confidence_gap_closures": [
            {
                "gap": "synthetic validator selftest does not execute project behavior",
                "status": "unresolved",
                "rationale": "selftest validates artifact shape only and intentionally does not execute project behavior",
            }
        ],
        "confidence_recovery": {
            "initial_confidence": 0.9,
            "final_confidence": 0.95,
            "status": "fair",
            "evidence": ["selftest artifact shape was created and validated locally"],
            "recovery_actions": ["included the confidence artifact and matching result metadata"],
            "remaining_limits": [],
        },
    }
    result = run_write_result(run, validate_dir / "result.json", metadata)
    if result.returncode != 0:
        run.fail_and_leak("shared-script-selftests", "selftest-failed:validate-artifacts-write-result")
        return
    validation = run_command(
        [
            run.paths.validate_artifacts,
            "--skill",
            "develop",
            "--out",
            validate_dir,
            "--result",
            validate_dir / "result.json",
        ]
    )
    if validation.returncode != 0:
        run.fail_and_leak("shared-script-selftests", "selftest-failed:validate-artifacts")


def run_benchmark_pattern_checks(run: CalibrationRun) -> None:
    """Check benchmark regex patterns against skill and agent instruction files."""
    if not run.paths.benchmarks.exists():
        return
    data = json.loads(run.paths.benchmarks.read_text(encoding="utf-8"))
    before = count_leak_prefix(run.paths.leaks, "benchmark-")
    for skill, patterns in data.get("skills", {}).items():
        path = run.paths.root / ".codex" / "skills" / skill / "SKILL.md"
        text = read_text(path)
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE) is None:
                run.append_leak(f"benchmark-skill-miss:{skill}:{pattern}")
    for agent, patterns in data.get("agents", {}).items():
        path = run.paths.root / ".codex" / "agents" / f"{agent}.toml"
        text = read_text(path)
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE) is None:
                run.append_leak(f"benchmark-agent-miss:{agent}:{pattern}")
    new_fails = count_leak_prefix(run.paths.leaks, "benchmark-") - before
    if new_fails > 0:
        run.mark_check_failed("benchmark-pattern-checks")
        run.fails += new_fails
        run.leaks += new_fails


def count_leak_prefix(path: Path, prefix: str) -> int:
    """Count leak lines with a given prefix."""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(prefix))


def run_behavioral_scoring(run: CalibrationRun) -> None:
    """Run behavioral scoring and import failures into calibration status."""
    if not (
        run.paths.behavioral_cases.exists()
        and run.paths.behavioral_observations.exists()
        and run.paths.behavioral_scorer.exists()
    ):
        return
    result = run_command(
        [
            sys.executable,
            run.paths.behavioral_scorer,
            "--cases",
            run.paths.behavioral_cases,
            "--observations",
            run.paths.behavioral_observations,
            "--out",
            run.paths.behavioral_result,
        ]
    )
    if result.returncode != 0:
        run.fail_and_leak("behavioral-metrics", f"behavioral-scorer-error:{run.paths.behavioral_scorer}")
        return

    payload = json.loads(run.paths.behavioral_result.read_text(encoding="utf-8"))
    overall = payload["overall"]
    freshness = payload.get("observation_freshness", {})
    run.append_check(
        "behavioral:"
        f"status={payload['status']}:"
        f"recall={overall['recall']}:"
        f"precision={overall['precision']}:"
        f"confidence_accuracy={overall['confidence_accuracy']}:"
        f"live_observations={freshness.get('live_observations', 0)}"
    )
    if payload["status"] != "fail":
        return

    checks_failed = payload.get("checks_failed") or ["behavioral-status"]
    for check in checks_failed:
        run.append_leak(f"behavioral-fail:{check}")
    run.mark_check_failed("behavioral-metrics")
    run.fails += len(checks_failed)
    run.leaks += len(checks_failed)


def metric(behavioral_payload: dict[str, Any] | None, name: str, default: float = 0.0) -> float:
    """Read a behavioral metric from raw gate metrics or overall metrics."""
    if not behavioral_payload:
        return default
    return behavioral_payload.get("gate_metrics_raw", behavioral_payload.get("overall", {})).get(name, default)


def rounded(value: float) -> float:
    """Round a metric for recommendation text."""
    return round(float(value), 3)


def top_case_gaps(behavioral_payload: dict[str, Any] | None, key: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return the largest false-positive or false-negative behavioral case gaps."""
    if not behavioral_payload:
        return []
    cases = [case for case in behavioral_payload.get("case_results", []) if int(case.get(key, 0)) > 0]
    return sorted(
        cases,
        key=lambda case: (int(case.get(key, 0)), float(case.get("confidence_error", 0.0))),
        reverse=True,
    )[:limit]


def confidence_outliers(behavioral_payload: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
    """Return cases with the largest confidence calibration error."""
    if not behavioral_payload:
        return []
    return sorted(
        behavioral_payload.get("case_results", []),
        key=lambda case: float(case.get("confidence_error", 0.0)),
        reverse=True,
    )[:limit]


def build_recommendations(
    behavioral_payload: dict[str, Any] | None, failed_checks: list[str], leak_total: int
) -> tuple[list[str], list[str]]:
    """Build calibration recommendations and follow-up items from metrics."""
    recommendations: list[str] = []
    follow_up: list[str] = []

    if failed_checks:
        recommendations.append("Fix failed calibration checks first: " + ", ".join(failed_checks) + ".")
    if leak_total:
        recommendations.append(
            f"Inspect leaks.txt and fix {leak_total} missing or mismatched config references before widening changes."
        )
    if not behavioral_payload:
        recommendations.append("Restore behavioral scoring output; behavioral.json was not produced.")
        return recommendations, follow_up

    thresholds = behavioral_payload.get("thresholds", {})
    raw = behavioral_payload.get("gate_metrics_raw", behavioral_payload.get("overall", {}))
    recall = float(raw.get("recall", 0.0))
    precision = float(raw.get("precision", 0.0))
    confidence_mae = float(raw.get("confidence_mae", 0.0))
    confidence_accuracy = max(0.0, 1.0 - confidence_mae)
    mean_overconfidence = float(raw.get("mean_overconfidence", 0.0))
    observations = int(raw.get("observations", 0))

    if observations < float(thresholds.get("min_observations", 1.0)):
        recommendations.append(
            f"Add behavioral observations: {observations} present, threshold is {rounded(thresholds.get('min_observations', 1.0))}."
        )
    if recall < float(thresholds.get("min_recall", 0.75)) or int(raw.get("fn", 0)) > 0:
        gaps = top_case_gaps(behavioral_payload, "fn")
        if gaps:
            detail = "; ".join(f"{case['case_id']} missed {case['fn']} expected finding(s)" for case in gaps)
            recommendations.append(f"Improve recall by addressing missing expected findings: {detail}.")
        else:
            recommendations.append(
                f"Improve behavioral recall from {rounded(recall)} toward threshold {rounded(thresholds.get('min_recall', 0.75))}."
            )
    if precision < float(thresholds.get("min_precision", 0.75)) or int(raw.get("fp", 0)) > 0:
        gaps = top_case_gaps(behavioral_payload, "fp")
        if gaps:
            detail = "; ".join(f"{case['case_id']} reported {case['fp']} unsupported finding(s)" for case in gaps)
            recommendations.append(
                "Improve precision by removing unsupported observations or updating expected ground truth with evidence: "
                f"{detail}."
            )
        else:
            recommendations.append(
                f"Improve behavioral precision from {rounded(precision)} toward threshold {rounded(thresholds.get('min_precision', 0.75))}."
            )
    if confidence_mae > float(thresholds.get("max_confidence_mae", 0.2)):
        recommendations.append(
            "Reduce confidence calibration error: "
            f"MAE {rounded(confidence_mae)} exceeds threshold {rounded(thresholds.get('max_confidence_mae', 0.2))}."
        )
    elif confidence_accuracy < 0.9:
        detail = "; ".join(
            f"{case['case_id']} confidence {case['confidence']} vs F1 {case['f1']}"
            for case in confidence_outliers(behavioral_payload, limit=3)
        )
        recommendations.append(
            f"Review stale confidence labels; confidence accuracy is {rounded(confidence_accuracy)}. Largest gaps: {detail}."
        )
    if mean_overconfidence > float(thresholds.get("max_mean_overconfidence", 0.15)):
        recommendations.append(
            "Reduce overconfidence: "
            f"mean overconfidence {rounded(mean_overconfidence)} exceeds threshold "
            f"{rounded(thresholds.get('max_mean_overconfidence', 0.15))}."
        )

    freshness = behavioral_payload.get("observation_freshness", {})
    if int(freshness.get("live_observations", 0) or 0) == 0:
        follow_up.append(
            "Add source=live-* observations from real Codex calibration prompts before treating fixture metrics as live model quality."
        )
    if int(freshness.get("missing_observed_at", 0) or 0) > 0:
        follow_up.append("Backfill missing observed_at timestamps in behavioral observations.")
    if not recommendations:
        recommendations.append(
            "No blocking calibration fixes found; maintain the current gates and collect live observations next."
        )
    return recommendations, follow_up


def write_result(run: CalibrationRun) -> None:
    """Write result.json and recommendations.md for the calibration run."""
    if not run.paths.leaks.exists():
        run.paths.leaks.touch()
    status = "fail" if run.fails > 0 or run.leaks > 0 else "pass"
    behavioral = (
        json.loads(run.paths.behavioral_result.read_text(encoding="utf-8"))
        if run.paths.behavioral_result.exists()
        else None
    )
    recommendations, follow_up = build_recommendations(behavioral, run.checks_failed, run.leaks)
    payload = {
        "status": status,
        "timestamp": run.paths.timestamp,
        "checks_run": [
            "project-model-default",
            "home-model-default",
            "review-model-policy",
            "deprecated-model-policy",
            "skill-schema-all",
            "skill-registration-project",
            "skill-registration-home",
            "agent-registration-project",
            "agent-registration-home",
            "agent-schema-all",
            "agent-model-policy",
            "native-skill-contract",
            "native-agent-contract",
            "native-runtime-leakage",
            "confidence-policy",
            "fixed-task-set",
            "behavioral-version-policy",
            "benchmark-pattern-checks",
            "behavioral-metrics",
            "shared-script-selftests",
        ],
        "checks_failed": run.checks_failed,
        "findings": {"critical": 0, "high": run.leaks, "medium": 0, "low": 0},
        "confidence": 0.95,
        "artifact_path": f".reports/codex/calibration/{run.paths.timestamp}/result.json",
        "metadata": {
            "confidence_gaps": ["fixture-heavy calibration does not fully prove live model behavior"],
            "confidence_gap_closures": [
                {
                    "gap": "fixture-heavy calibration does not fully prove live model behavior",
                    "status": "unresolved",
                    "rationale": "behavioral metrics include fixture observations; live observations are reported separately",
                }
            ],
            "confidence_recovery": {
                "initial_confidence": 0.9,
                "final_confidence": 0.95,
                "status": "fair",
                "evidence": ["calibration checks completed and behavioral metrics were computed"],
                "recovery_actions": ["recorded fixture-vs-live observation counts and confidence calibration metrics"],
                "remaining_limits": ["live model quality still depends on live calibration observations"],
            },
        },
        "leaks_found": run.leaks,
        "behavioral": behavioral,
        "recommendations": recommendations,
        "follow_up": follow_up,
        "artifacts": {
            "checks": f".reports/codex/calibration/{run.paths.timestamp}/checks.txt",
            "leaks": f".reports/codex/calibration/{run.paths.timestamp}/leaks.txt",
            "behavioral": f".reports/codex/calibration/{run.paths.timestamp}/behavioral.json",
            "recommendations": f".reports/codex/calibration/{run.paths.timestamp}/recommendations.md",
            "result": f".reports/codex/calibration/{run.paths.timestamp}/result.json",
        },
    }
    run.paths.result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_recommendations(run, status, behavioral, recommendations, follow_up)


def write_recommendations(
    run: CalibrationRun,
    status: str,
    behavioral: dict[str, Any] | None,
    recommendations: list[str],
    follow_up: list[str],
) -> None:
    """Write the Markdown recommendations artifact."""
    lines = [
        "# Calibration Recommendations",
        "",
        f"Status: {status}",
        f"Checks failed: {', '.join(run.checks_failed) if run.checks_failed else 'none'}",
        f"Leaks found: {run.leaks}",
    ]
    if behavioral:
        overall = behavioral.get("overall", {})
        freshness = behavioral.get("observation_freshness", {})
        lines.extend(
            [
                "",
                "## Behavioral Summary",
                "",
                f"- Recall: {overall.get('recall')}",
                f"- Precision: {overall.get('precision')}",
                f"- F1: {overall.get('f1')}",
                f"- Confidence accuracy: {overall.get('confidence_accuracy')}",
                f"- Mean overconfidence: {overall.get('mean_overconfidence')}",
                f"- Fixture observations: {freshness.get('fixture_observations', 0)}",
                f"- Live observations: {freshness.get('live_observations', 0)}",
            ]
        )
    lines.extend(["", "## Recommendations", ""])
    lines.extend(f"- {item}" for item in recommendations)
    if follow_up:
        lines.extend(["", "## Follow-Up", ""])
        lines.extend(f"- {item}" for item in follow_up)
    leak_text = read_text(run.paths.leaks).strip()
    if leak_text:
        lines.extend(["", "## Leak Details", ""])
        lines.extend(f"- {line}" for line in leak_text.splitlines() if line.strip())
    run.paths.recommendations.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Run all calibration checks and print the result path."""
    paths = Paths.create()
    run = CalibrationRun(paths=paths)
    check_core_configs(run)
    check_native_runtime_leaks(run)
    check_shared_scripts(run)
    run_benchmark_pattern_checks(run)
    run_behavioral_scoring(run)
    write_result(run)
    print(run.paths.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
