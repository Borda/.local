#!/usr/bin/env python3
"""Score behavioral calibration observations against known finding IDs.

The scorer intentionally separates measurement from model invocation. It expects
observations produced by a calibration run and computes recall, precision, and
confidence calibration against a fixed case set.

Example:
    >>> _round3(2 / 3)
    0.667
    >>> _safe_div(3, 0)
    0.0
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _round3(value: float) -> float:
    """Round metric values to three decimals."""
    return round(value, 3)


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    """Divide two numbers, returning 0.0 when the denominator is zero."""
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _raw_metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Compute unrounded recall, precision, and F1 for gate decisions.

    Example:
        >>> _raw_metrics(2999, 0, 1001)["recall"]
        0.74975
    """
    recall = _safe_div(tp, tp + fn)
    precision = _safe_div(tp, tp + fp)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def _is_fixture_source(source: str) -> bool:
    """Return whether an observation source is a fixture-only self-test.

    Example:
        >>> _is_fixture_source("fixture-selftest")
        True
        >>> _is_fixture_source("live-codex-cli")
        False
    """
    return source.startswith("fixture")


def _parse_observed_at(value: str) -> datetime:
    """Parse an observation timestamp as timezone-aware UTC.

    Example:
        >>> _parse_observed_at("2026-06-02T06:50:00Z").isoformat()
        '2026-06-02T06:50:00+00:00'
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            records.append(record)
    return records


def _load_cases(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    payload = _read_json(path)
    cases_raw = payload.get("cases", [])
    if not isinstance(cases_raw, list):
        raise ValueError("behavioral cases must contain a 'cases' list")

    cases: dict[str, dict[str, Any]] = {}
    for case in cases_raw:
        if not isinstance(case, dict):
            raise ValueError("each behavioral case must be a JSON object")
        case_id = case.get("id")
        expected = case.get("expected_findings")
        target = case.get("target")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("each behavioral case needs a non-empty string id")
        if not isinstance(target, str) or not target:
            raise ValueError(f"behavioral case {case_id} needs a non-empty target")
        if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
            raise ValueError(f"behavioral case {case_id} needs string expected_findings")
        cases[case_id] = {
            "target": target,
            "expected": set(expected),
        }

    thresholds_raw = payload.get("thresholds", {})
    if not isinstance(thresholds_raw, dict):
        raise ValueError("thresholds must be a JSON object")
    thresholds = {
        "min_observations": float(thresholds_raw.get("min_observations", 1)),
        "min_recall": float(thresholds_raw.get("min_recall", 0.0)),
        "min_precision": float(thresholds_raw.get("min_precision", 0.0)),
        "max_confidence_mae": float(thresholds_raw.get("max_confidence_mae", 1.0)),
        "max_mean_overconfidence": float(thresholds_raw.get("max_mean_overconfidence", 1.0)),
    }
    return cases, thresholds


def _validate_observation(
    record: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> tuple[str, str, set[str], float, str, str, str | None]:
    case_id = record.get("case_id")
    if not isinstance(case_id, str) or case_id not in cases:
        raise ValueError(f"unknown behavioral case_id: {case_id!r}")

    target = record.get("target", cases[case_id]["target"])
    if not isinstance(target, str) or target != cases[case_id]["target"]:
        raise ValueError(f"target mismatch for {case_id}: expected {cases[case_id]['target']!r}, got {target!r}")

    reported = record.get("reported_findings")
    if not isinstance(reported, list) or not all(isinstance(item, str) for item in reported):
        raise ValueError(f"observation {case_id} needs string reported_findings")

    confidence = record.get("confidence")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError(f"observation {case_id} needs confidence in [0.0, 1.0]")

    source = record.get("source", "unknown")
    if not isinstance(source, str) or not source:
        raise ValueError(f"observation {case_id} needs a non-empty source")

    run_id = record.get("run_id", "unknown")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"observation {case_id} needs a non-empty run_id")

    observed_at_raw = record.get("observed_at")
    if observed_at_raw is None:
        observed_at = None
    elif isinstance(observed_at_raw, str) and observed_at_raw:
        _parse_observed_at(observed_at_raw)
        observed_at = observed_at_raw
    else:
        raise ValueError(f"observation {case_id} needs observed_at as an ISO timestamp")

    return case_id, target, set(reported), float(confidence), source, run_id, observed_at


def _metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    raw = _raw_metrics(tp, fp, fn)
    return {
        "recall": _round3(raw["recall"]),
        "precision": _round3(raw["precision"]),
        "f1": _round3(raw["f1"]),
    }


def _score(cases_path: Path, observations_path: Path) -> dict[str, Any]:
    cases, thresholds = _load_cases(cases_path)
    observations = _read_jsonl(observations_path)
    by_target_counts: dict[str, Counter[str]] = defaultdict(Counter)
    by_target_conf_errors: dict[str, list[float]] = defaultdict(list)
    by_target_overconfidence: dict[str, list[float]] = defaultdict(list)
    by_source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    by_source_conf_errors: dict[str, list[float]] = defaultdict(list)
    by_source_overconfidence: dict[str, list[float]] = defaultdict(list)
    case_results: list[dict[str, Any]] = []
    sources: Counter[str] = Counter()
    run_ids: Counter[str] = Counter()
    observed_timestamps: list[datetime] = []
    missing_observed_at = 0

    total_counts: Counter[str] = Counter()
    total_conf_errors: list[float] = []
    total_overconfidence: list[float] = []

    for record in observations:
        case_id, target, reported, confidence, source, run_id, observed_at = _validate_observation(record, cases)
        expected = cases[case_id]["expected"]
        tp = len(expected & reported)
        fp = len(reported - expected)
        fn = len(expected - reported)
        case_metrics_raw = _raw_metrics(tp, fp, fn)
        case_metrics = _metrics(tp, fp, fn)
        case_f1 = case_metrics_raw["f1"]
        confidence_error = abs(confidence - case_f1)
        overconfidence = max(confidence - case_f1, 0.0)

        total_counts.update({"tp": tp, "fp": fp, "fn": fn, "observations": 1})
        by_target_counts[target].update({"tp": tp, "fp": fp, "fn": fn, "observations": 1})
        by_source_counts[source].update({"tp": tp, "fp": fp, "fn": fn, "observations": 1})
        total_conf_errors.append(confidence_error)
        total_overconfidence.append(overconfidence)
        by_target_conf_errors[target].append(confidence_error)
        by_target_overconfidence[target].append(overconfidence)
        by_source_conf_errors[source].append(confidence_error)
        by_source_overconfidence[source].append(overconfidence)
        sources[source] += 1
        run_ids[run_id] += 1
        if observed_at is None:
            missing_observed_at += 1
        else:
            observed_timestamps.append(_parse_observed_at(observed_at))

        case_results.append(
            {
                "case_id": case_id,
                "target": target,
                "source": source,
                "run_id": run_id,
                "observed_at": observed_at,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "confidence": _round3(confidence),
                "confidence_error": _round3(confidence_error),
                "overconfidence": _round3(overconfidence),
                **case_metrics,
            }
        )

    overall_raw = _summarize_counts_raw(total_counts, total_conf_errors, total_overconfidence)
    overall = _round_summary(overall_raw)
    by_target = {
        target: _round_summary(
            _summarize_counts_raw(counts, by_target_conf_errors[target], by_target_overconfidence[target])
        )
        for target, counts in sorted(by_target_counts.items())
    }
    by_source = {
        source: _round_summary(
            _summarize_counts_raw(counts, by_source_conf_errors[source], by_source_overconfidence[source])
        )
        for source, counts in sorted(by_source_counts.items())
    }
    fixture_observations = sum(count for source, count in sources.items() if _is_fixture_source(source))
    live_observations = len(observations) - fixture_observations
    freshness = _summarize_freshness(observed_timestamps, missing_observed_at, fixture_observations, live_observations)

    checks_failed = _threshold_failures(overall_raw, thresholds)
    notes = [
        "The scorer measures supplied observations; live Codex behavior is measured only when observations come from live calibration runs.",
        "fixture-selftest observations validate the scoring contract but are not evidence of current live model quality.",
    ]
    if live_observations == 0:
        notes.append(
            "No live Codex observations were supplied; use source=live-* rows to measure current model behavior."
        )
    return {
        "status": "fail" if checks_failed else "pass",
        "checks_failed": checks_failed,
        "thresholds": thresholds,
        "overall": overall,
        "gate_metrics_raw": overall_raw,
        "by_target": by_target,
        "by_source": by_source,
        "case_results": case_results,
        "observation_sources": dict(sorted(sources.items())),
        "observation_run_ids": dict(sorted(run_ids.items())),
        "observation_freshness": freshness,
        "notes": notes,
    }


def _summarize_counts_raw(
    counts: Counter[str], confidence_errors: list[float], overconfidence: list[float]
) -> dict[str, Any]:
    metrics = _raw_metrics(counts["tp"], counts["fp"], counts["fn"])
    confidence_mae = _safe_div(sum(confidence_errors), len(confidence_errors))
    mean_overconfidence = _safe_div(sum(overconfidence), len(overconfidence))
    return {
        "observations": counts["observations"],
        "tp": counts["tp"],
        "fp": counts["fp"],
        "fn": counts["fn"],
        **metrics,
        "confidence_mae": confidence_mae,
        "confidence_accuracy": max(0.0, 1.0 - confidence_mae),
        "mean_overconfidence": mean_overconfidence,
    }


def _round_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: _round3(value) if isinstance(value, float) else value for key, value in summary.items()}


def _summarize_freshness(
    observed_timestamps: list[datetime],
    missing_observed_at: int,
    fixture_observations: int,
    live_observations: int,
) -> dict[str, Any]:
    latest = max(observed_timestamps) if observed_timestamps else None
    latest_age_days = None
    if latest is not None:
        latest_age_days = _round3(max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 86400.0))
    return {
        "latest_observed_at": latest.isoformat().replace("+00:00", "Z") if latest is not None else None,
        "latest_age_days": latest_age_days,
        "missing_observed_at": missing_observed_at,
        "fixture_observations": fixture_observations,
        "live_observations": live_observations,
    }


def _threshold_failures(overall: dict[str, Any], thresholds: dict[str, float]) -> list[str]:
    """Return gate failures using unrounded metric values.

    Example:
        >>> rounded = _metrics(2999, 0, 1001)
        >>> rounded["recall"]
        0.75
        >>> _threshold_failures(
        ...     {
        ...         "observations": 16,
        ...         "recall": 0.74975,
        ...         "precision": 1.0,
        ...         "confidence_mae": 0.0,
        ...         "mean_overconfidence": 0.0,
        ...     },
        ...     {
        ...         "min_observations": 16.0,
        ...         "min_recall": 0.75,
        ...         "min_precision": 0.75,
        ...         "max_confidence_mae": 0.2,
        ...         "max_mean_overconfidence": 0.15,
        ...     },
        ... )
        ['behavioral-recall']
    """
    failures: list[str] = []
    if overall["observations"] < thresholds["min_observations"]:
        failures.append("behavioral-min-observations")
    if overall["recall"] < thresholds["min_recall"]:
        failures.append("behavioral-recall")
    if overall["precision"] < thresholds["min_precision"]:
        failures.append("behavioral-precision")
    if overall["confidence_mae"] > thresholds["max_confidence_mae"]:
        failures.append("behavioral-confidence-mae")
    if overall["mean_overconfidence"] > thresholds["max_mean_overconfidence"]:
        failures.append("behavioral-overconfidence")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    result = _score(args.cases, args.observations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
