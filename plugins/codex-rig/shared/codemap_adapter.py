#!/usr/bin/env python3
"""codemap_adapter.py — lazy public-CLI probe for optional codemap-py structural context.

Consumes ONLY the public `codemap-py` CLI/JSON surface (`doctor --json`, `query <subcommand>`) —
never codemap-py cache internals, source-tree paths, or a cross-plugin Python import. Absence or
incompatibility is non-fatal: callers fall back to Codex Rig's own bounded file inspection. See
`codemap-contract.md` (this directory) for the persist-once rule and the category-to-query map.

Usage:
    python codemap_adapter.py probe [--timeout SECONDS]
    python codemap_adapter.py context --category {analysis,develop,review,audit} [--target QNAME]
        [--root PATH] [--out PATH] [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "codemap-py.integration.v1"
STATUS_AVAILABLE = "available"
STATUS_ABSENT = "absent"
STATUS_STALE = "stale"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_DEGRADED = "degraded"
_DEFAULT_TIMEOUT = 15.0
_EXIT_NOT_INDEXED = 3
_WINDOWS_EXECUTABLE_SUFFIXES = {".bat", ".cmd", ".com", ".exe"}


@dataclass(frozen=True)
class QuerySpec:
    """One planned `codemap-py query` call for a structural-context category."""

    subcommand: str
    requires_target: bool
    extra_args: tuple[str, ...] = ()


CATEGORY_QUERIES: dict[str, tuple[QuerySpec, ...]] = {
    # analysis/research: centrality, symbol/import context, completeness metadata (plan §8.4).
    "analysis": (
        QuerySpec("central", requires_target=False),
        QuerySpec("deps", requires_target=True),
    ),
    # develop/investigate/optimize: callers, coupling, test impact before implementation.
    "develop": (
        QuerySpec("rdeps", requires_target=True),
        QuerySpec("coupled", requires_target=False),
        QuerySpec("test-impact", requires_target=True),
    ),
    # code-review/code-remediate: changed-symbol/diff impact supplied once.
    "review": (QuerySpec("diff-impact", requires_target=False),),
    # audit/release: undocumented public surface + externally-uncalled modules (broken-ref proxy).
    "audit": (
        QuerySpec("undocumented", requires_target=False, extra_args=("--all",)),
        QuerySpec("dead-modules", requires_target=False),
    ),
}


@dataclass(frozen=True)
class DoctorReport:
    """Parsed `codemap-py doctor --json` payload."""

    python: str
    version: str
    implementation: str
    supported: bool
    plugin_root: str
    index_path: str


@dataclass(frozen=True)
class LauncherResolution:
    """One validated Codemap launcher decision reused for one adapter invocation."""

    launcher: str | None
    status: str
    detail: str


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of probing `codemap-py` availability and interpreter health."""

    status: str
    detail: str
    launcher: str | None
    doctor: DoctorReport | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view."""
        return {
            "status": self.status,
            "detail": self.detail,
            "launcher": self.launcher,
            "doctor": None if self.doctor is None else vars(self.doctor),
        }


@dataclass(frozen=True)
class QueryOutcome:
    """Result of one `codemap-py query` call, including completeness metadata."""

    subcommand: str
    target: str | None
    exit_code: int
    stale: bool
    query_complete: bool
    not_covered: tuple[str, ...]
    degraded_count: int
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view."""
        return {
            "subcommand": self.subcommand,
            "target": self.target,
            "exit_code": self.exit_code,
            "stale": self.stale,
            "query_complete": self.query_complete,
            "not_covered": list(self.not_covered),
            "degraded_count": self.degraded_count,
            "error": self.error,
        }


@dataclass(frozen=True)
class StructuralContext:
    """Persist-once structural-context evidence for one workflow decision point."""

    protocol_version: str
    category: str
    target: str | None
    status: str
    probe: ProbeResult
    queries: tuple[QueryOutcome, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON shape written once to a run artifact."""
        return {
            "protocol_version": self.protocol_version,
            "category": self.category,
            "target": self.target,
            "status": self.status,
            "probe": self.probe.to_dict(),
            "queries": [outcome.to_dict() for outcome in self.queries],
        }


def _run_json(argv: list[str], timeout: float) -> tuple[int, dict[str, Any] | None, str | None]:
    """Run one subprocess and parse stdout as JSON; never raise on failure.

    Returns:
        ``(exit_code, parsed_json_or_none, error_message_or_none)``.
    """
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return -1, None, str(error)
    try:
        return completed.returncode, json.loads(completed.stdout), None
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or completed.stdout.strip() or "non-JSON output"
        return completed.returncode, None, detail


def _configured_launcher_is_valid(candidate: Path) -> bool:
    """Return whether one explicit launcher meets the current platform's executable contract."""
    if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_file():
        return False
    if os.name == "nt":
        return candidate.suffix.casefold() in _WINDOWS_EXECUTABLE_SUFFIXES
    return os.access(candidate, os.X_OK)


def _resolve_codemap_executable() -> LauncherResolution:
    """Resolve one validated launcher, failing closed for a nonempty invalid `CODEMAP_BIN`."""
    configured = os.environ.get("CODEMAP_BIN")
    if configured:
        candidate = Path(configured)
        if _configured_launcher_is_valid(candidate):
            return LauncherResolution(str(candidate), STATUS_AVAILABLE, "configured launcher")
        return LauncherResolution(
            None,
            STATUS_INCOMPATIBLE,
            "CODEMAP_BIN must be an absolute, non-symlink executable file",
        )
    executable = shutil.which("codemap-py")
    if executable is None:
        return LauncherResolution(None, STATUS_ABSENT, "codemap-py not found on PATH")
    return LauncherResolution(executable, STATUS_AVAILABLE, "PATH launcher")


def _probe_codemap(resolution: LauncherResolution, timeout: float) -> ProbeResult:
    """Probe one resolved launcher through `doctor --json`; never re-resolve it."""
    if resolution.launcher is None:
        return ProbeResult(resolution.status, resolution.detail, None, None)
    exit_code, payload, error = _run_json([resolution.launcher, "doctor", "--json"], timeout)
    if exit_code != 0 or payload is None:
        return ProbeResult(
            status=STATUS_INCOMPATIBLE,
            detail=error or f"doctor exited {exit_code}",
            launcher=None,
            doctor=None,
        )
    if not isinstance(payload, dict):
        return ProbeResult(
            status=STATUS_INCOMPATIBLE,
            detail="doctor payload not a JSON object",
            launcher=None,
            doctor=None,
        )
    try:
        doctor = DoctorReport(
            python=str(payload["python"]),
            version=str(payload["version"]),
            implementation=str(payload["implementation"]),
            supported=bool(payload["supported"]),
            plugin_root=str(payload["plugin_root"]),
            index_path=str(payload["index_path"]),
        )
    except KeyError as missing:
        return ProbeResult(
            status=STATUS_INCOMPATIBLE,
            detail=f"doctor payload missing {missing}",
            launcher=None,
            doctor=None,
        )
    if not doctor.supported:
        detail = f"unsupported interpreter {doctor.implementation} {doctor.version}"
        return ProbeResult(STATUS_INCOMPATIBLE, detail, None, doctor)
    return ProbeResult(STATUS_AVAILABLE, "doctor healthy", resolution.launcher, doctor)


def probe_codemap(timeout: float = _DEFAULT_TIMEOUT) -> ProbeResult:
    """Probe `codemap-py` presence and interpreter health via the public CLI only.

    Examples:
        >>> probe_codemap().status in {"available", "absent", "incompatible"}
        True
    """
    return _probe_codemap(_resolve_codemap_executable(), timeout)


def _run_one_query(
    launcher: str, spec: QuerySpec, target: str | None, root: Path | None, timeout: float
) -> QueryOutcome:
    """Run one planned query and reduce its response to completeness metadata."""
    # `--root` is a top-level `query` flag (query.py registers it on the parent parser),
    # so it must precede the subcommand — argparse rejects it once the subcommand is consumed.
    argv = [launcher, "query", "--compact"]
    if root is not None:
        argv += ["--root", str(root)]
    argv.append(spec.subcommand)
    if spec.requires_target:
        if target is None:
            return QueryOutcome(spec.subcommand, target, -1, False, False, (), 0, "target required, none supplied")
        argv.append(target)
    argv.extend(spec.extra_args)
    exit_code, payload, error = _run_json(argv, timeout)
    if exit_code == _EXIT_NOT_INDEXED:
        return QueryOutcome(spec.subcommand, target, exit_code, False, False, (), 0, "target not indexed")
    if exit_code != 0 or payload is None:
        return QueryOutcome(spec.subcommand, target, exit_code, False, False, (), 0, error or "query failed")
    index = payload.get("index", {}) if isinstance(payload, dict) else {}
    complete = bool(index.get("query_complete", index.get("exhaustive", False)))
    return QueryOutcome(
        subcommand=spec.subcommand,
        target=target,
        exit_code=exit_code,
        stale=bool(index.get("stale", False)),
        query_complete=complete,
        not_covered=tuple(index.get("not_covered", ())),
        degraded_count=int(index.get("degraded", 0)),
        error=None,
    )


def _reduce_status(probe: ProbeResult, queries: tuple[QueryOutcome, ...]) -> str:
    """Reduce a probe plus its queries to one overall named status."""
    if probe.status != STATUS_AVAILABLE:
        return probe.status
    if not queries:
        return STATUS_AVAILABLE
    if any(outcome.stale for outcome in queries):
        return STATUS_STALE
    succeeded = [outcome for outcome in queries if outcome.error is None]
    if not succeeded:
        return STATUS_INCOMPATIBLE
    fully_clean = all(
        outcome.query_complete and not outcome.not_covered and outcome.degraded_count == 0 for outcome in succeeded
    )
    if fully_clean and len(succeeded) == len(queries):
        return STATUS_AVAILABLE
    return STATUS_DEGRADED


def gather_structural_context(
    category: str,
    target: str | None = None,
    root: Path | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> StructuralContext:
    """Probe once and run a category's mapped queries once; never re-query per child.

    Examples:
        >>> ctx = gather_structural_context("develop", target="pkg.mod")
        >>> ctx.protocol_version
        'codemap-py.integration.v1'
    """
    specs = CATEGORY_QUERIES.get(category)
    if specs is None:
        known = ", ".join(sorted(CATEGORY_QUERIES))
        raise ValueError(f"unknown category {category!r}; expected one of: {known}")
    resolution = _resolve_codemap_executable()
    probe = _probe_codemap(resolution, timeout)
    queries: tuple[QueryOutcome, ...] = ()
    if probe.status == STATUS_AVAILABLE and resolution.launcher is not None:
        queries = tuple(_run_one_query(resolution.launcher, spec, target, root, timeout) for spec in specs)
    status = _reduce_status(probe, queries)
    return StructuralContext(
        protocol_version=PROTOCOL_VERSION,
        category=category,
        target=target,
        status=status,
        probe=probe,
        queries=queries,
    )


def _write_output(payload: dict[str, Any], out_path: Path | None) -> None:
    """Print JSON to stdout and, when requested, persist it once to a run artifact."""
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    print(encoded)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(encoded + "\n", encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the adapter's two-subcommand CLI contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    probe_parser = sub.add_parser("probe", help="Probe codemap-py availability and interpreter health.")
    probe_parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)

    context_parser = sub.add_parser("context", help="Gather one category's structural-context evidence.")
    context_parser.add_argument("--category", required=True, choices=sorted(CATEGORY_QUERIES))
    context_parser.add_argument("--target", default=None, help="Dotted module or module::symbol qname.")
    context_parser.add_argument("--root", type=Path, default=None)
    context_parser.add_argument("--out", type=Path, default=None, help="Also persist JSON to this run-artifact path.")
    context_parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatch `probe`/`context`; always exits 0 — absence/incompatibility is data, not failure."""
    arguments = _parse_args(argv)
    if arguments.mode == "probe":
        _write_output(probe_codemap(timeout=arguments.timeout).to_dict(), None)
        return 0
    context = gather_structural_context(
        category=arguments.category,
        target=arguments.target,
        root=arguments.root,
        timeout=arguments.timeout,
    )
    _write_output(context.to_dict(), arguments.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
