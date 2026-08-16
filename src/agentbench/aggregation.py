"""Statistical summaries. No significance claims. Stdlib only."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from .models import RunResult, RunStatus
from .numbers import percentile

NUMERIC_FIELDS = (
    "duration_seconds",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost",
    "latency_seconds",
    "tool_calls",
    "agent_count",
    "retries",
    "recoveries",
    "stalls",
    "errors",
    "files_created",
    "files_modified",
    "files_deleted",
    "tests_passed",
    "tests_failed",
    "stall_count",
    "recovery_attempts",
    "successful_recoveries",
)


def _metric_value(run: RunResult, name: str) -> float | None:
    if name == "duration_seconds":
        return run.target.duration_seconds
    if name == "success":
        return 1.0 if run.target.status is RunStatus.SUCCESS else 0.0
    if name == "validation_passed":
        flag = run.validation_passed
        if flag is None:
            return None
        return 1.0 if flag else 0.0
    tel = run.target.telemetry
    if hasattr(tel, name):
        value = getattr(tel, name)
        return None if value is None else float(value)
    if run.workspace_diff is not None and hasattr(run.workspace_diff, name):
        return float(getattr(run.workspace_diff, name))
    return None


def summarize_numbers(values: Sequence[float]) -> dict[str, Any]:
    """Distribution summary. Sample size is always reported."""
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "stdev": None,
            "p50": None,
            "p95": None,
            "percentile_meaningful": False,
        }
    ordered = list(values)
    return {
        "n": n,
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "min": min(ordered),
        "max": max(ordered),
        "stdev": statistics.stdev(ordered) if n >= 2 else None,
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "percentile_meaningful": n >= 2,
    }


def status_rates(runs: Sequence[RunResult]) -> dict[str, Any]:
    n = len(runs)
    counts = {status.value: 0 for status in RunStatus}
    for run in runs:
        counts[run.target.status.value] += 1
    rates = {f"{key.lower()}_rate": (counts[key] / n if n else None) for key in counts}
    return {"n": n, "counts": counts, **rates}


def detect_flaky(runs: Sequence[RunResult]) -> list[dict[str, Any]]:
    """Mark case/variant pairs whose outcomes are not identical across reps."""
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for run in runs:
        grouped[(run.case_id, run.variant_id)].append(run.target.status.value)
    flaky: list[dict[str, Any]] = []
    for (case_id, variant_id), statuses in sorted(grouped.items()):
        unique = set(statuses)
        if len(unique) > 1:
            flaky.append(
                {
                    "case_id": case_id,
                    "variant_id": variant_id,
                    "outcomes": statuses,
                    "unique_outcomes": sorted(unique),
                    "repetitions": len(statuses),
                }
            )
    return flaky


def case_outcomes(runs: Sequence[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for run in runs:
        grouped[(run.case_id, run.variant_id)].extend([run])
    rows: list[dict[str, Any]] = []
    for (case_id, variant_id), group in sorted(grouped.items()):
        statuses = [r.target.status for r in group]
        unique = {s.value for s in statuses}
        always_fail = unique == {RunStatus.FAILURE.value}
        always_timeout = unique == {RunStatus.TIMEOUT.value}
        always_success = unique == {RunStatus.SUCCESS.value}
        costs = [r.target.telemetry.cost for r in group if r.target.telemetry.cost is not None]
        rows.append(
            {
                "case_id": case_id,
                "variant_id": variant_id,
                "n": len(group),
                "outcomes": [s.value for s in statuses],
                "always_fail": always_fail,
                "always_timeout": always_timeout,
                "always_success": always_success,
                "flaky": len(unique) > 1,
                "mean_cost": None if not costs else statistics.fmean(costs),
            }
        )
    return rows


def aggregate_variant(variant_id: str, runs: Sequence[RunResult]) -> dict[str, Any]:
    rates = status_rates(runs)
    metrics: dict[str, Any] = {}
    for field in NUMERIC_FIELDS:
        values = [v for v in (_metric_value(r, field) for r in runs) if v is not None]
        metrics[field] = summarize_numbers(values)
    metrics["success"] = summarize_numbers(
        [v for v in (_metric_value(r, "success") for r in runs) if v is not None]
    )
    metrics["validation_passed"] = summarize_numbers(
        [v for v in (_metric_value(r, "validation_passed") for r in runs) if v is not None]
    )
    return {
        "variant_id": variant_id,
        "run_count": len(runs),
        **rates,
        "metrics": metrics,
        "flaky": detect_flaky(runs),
        "cases": case_outcomes(runs),
    }


def aggregate_experiment(runs: Sequence[RunResult]) -> dict[str, Any]:
    by_variant: dict[str, list[RunResult]] = defaultdict(list)
    for run in runs:
        by_variant[run.variant_id].append(run)
    variants = [aggregate_variant(vid, group) for vid, group in sorted(by_variant.items())]
    return {
        "schema_version": 1,
        "run_count": len(runs),
        **status_rates(runs),
        "variants": variants,
        "flaky": detect_flaky(runs),
        "cases": case_outcomes(runs),
    }


def values_for(runs: Iterable[RunResult], metric: str) -> list[float]:
    return [v for v in (_metric_value(r, metric) for r in runs) if v is not None]


def metric_lookup() -> tuple[str, ...]:
    return NUMERIC_FIELDS + ("success", "validation_passed")
