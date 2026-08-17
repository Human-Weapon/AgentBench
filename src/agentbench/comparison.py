"""Baseline vs candidate comparison. Honest about missing data and sample size."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .aggregation import _metric_value, summarize_numbers
from .errors import ValidationError
from .models import MetricDirection, RegressionClass, RunResult
from .numbers import relative_delta
from .regression import MetricRule, RegressionPolicy


def _pair_key(run: RunResult) -> tuple[str, int, int]:
    return (run.case_id, run.repetition, run.seed)


def _pair_map(runs: Sequence[RunResult], *, role: str) -> dict[tuple[str, int, int], RunResult]:
    mapped: dict[tuple[str, int, int], RunResult] = {}
    for run in runs:
        key = _pair_key(run)
        if key in mapped:
            raise ValidationError(
                f"ambiguous {role} pair key {key}; duplicate case/repetition/seed"
            )
        mapped[key] = run
    return mapped


def _direction_for(metric: str, policy: RegressionPolicy | None) -> MetricDirection:
    if policy:
        for rule in policy.rules:
            if rule.metric == metric:
                return rule.direction
    if metric in {"success", "validation_passed", "tests_passed", "successful_recoveries"}:
        return MetricDirection.HIGHER_IS_BETTER
    return MetricDirection.LOWER_IS_BETTER


def classify(
    baseline: float,
    candidate: float,
    rule: MetricRule,
    *,
    baseline_n: int,
    candidate_n: int,
) -> RegressionClass:
    if baseline_n < rule.min_sample_size or candidate_n < rule.min_sample_size:
        return RegressionClass.INCONCLUSIVE
    abs_delta = candidate - baseline
    rel = relative_delta(baseline, candidate)
    improved = (
        abs_delta > 0 if rule.direction is MetricDirection.HIGHER_IS_BETTER else abs_delta < 0
    )
    worsened = (
        abs_delta < 0 if rule.direction is MetricDirection.HIGHER_IS_BETTER else abs_delta > 0
    )
    abs_breach = False
    rel_breach = False
    if rule.absolute_threshold is not None and worsened:
        abs_breach = abs(abs_delta) > rule.absolute_threshold
    if rule.relative_threshold is not None:
        if rel is None:
            # Cannot evaluate a relative rule when baseline is 0.
            return RegressionClass.INCONCLUSIVE
        if worsened:
            rel_breach = abs(rel) > rule.relative_threshold
    if not worsened and not improved:
        return RegressionClass.UNCHANGED
    if worsened and (abs_breach or rel_breach):
        return RegressionClass.REGRESSED
    if worsened:
        # Within allowed degradation.
        return RegressionClass.UNCHANGED
    return RegressionClass.IMPROVED


def compare_metric(
    baseline_runs: Sequence[RunResult],
    candidate_runs: Sequence[RunResult],
    metric: str,
    *,
    policy: RegressionPolicy | None = None,
) -> dict[str, Any]:
    b_vals = [v for v in (_metric_value(r, metric) for r in baseline_runs) if v is not None]
    c_vals = [v for v in (_metric_value(r, metric) for r in candidate_runs) if v is not None]
    direction = _direction_for(metric, policy)
    if not b_vals or not c_vals:
        return {
            "metric": metric,
            "direction": direction.value,
            "baseline": None,
            "candidate": None,
            "absolute_delta": None,
            "relative_delta": None,
            "classification": RegressionClass.UNAVAILABLE.value,
            "baseline_n": len(b_vals),
            "candidate_n": len(c_vals),
            "baseline_summary": summarize_numbers(b_vals),
            "candidate_summary": summarize_numbers(c_vals),
        }
    b_mean = sum(b_vals) / len(b_vals)
    c_mean = sum(c_vals) / len(c_vals)
    rule = None
    if policy:
        rule = next((r for r in policy.rules if r.metric == metric), None)
    if rule is None:
        classification = RegressionClass.INCONCLUSIVE
        # Still report direction-aware improvement without claiming a gate.
        if c_mean == b_mean:
            classification = RegressionClass.UNCHANGED
        elif (c_mean > b_mean) == (direction is MetricDirection.HIGHER_IS_BETTER):
            classification = RegressionClass.IMPROVED
        else:
            classification = RegressionClass.REGRESSED
        # Without a policy this is informational, not a gate.
    else:
        classification = classify(
            b_mean, c_mean, rule, baseline_n=len(b_vals), candidate_n=len(c_vals)
        )
    return {
        "metric": metric,
        "direction": direction.value,
        "baseline": b_mean,
        "candidate": c_mean,
        "absolute_delta": c_mean - b_mean,
        "relative_delta": relative_delta(b_mean, c_mean),
        "classification": classification.value,
        "hard_gate": bool(rule.hard_gate) if rule else False,
        "baseline_n": len(b_vals),
        "candidate_n": len(c_vals),
        "baseline_summary": summarize_numbers(b_vals),
        "candidate_summary": summarize_numbers(c_vals),
    }


def paired_comparison(
    baseline_runs: Sequence[RunResult],
    candidate_runs: Sequence[RunResult],
    metric: str,
    *,
    direction: MetricDirection,
) -> dict[str, Any]:
    base_map = _pair_map(baseline_runs, role="baseline")
    cand_map = _pair_map(candidate_runs, role="candidate")
    keys = sorted(set(base_map) & set(cand_map))
    wins = 0
    losses = 0
    ties = 0
    usable = 0
    deltas: list[float] = []
    for key in keys:
        b = _metric_value(base_map[key], metric)
        c = _metric_value(cand_map[key], metric)
        if b is None or c is None:
            continue
        usable += 1
        delta = c - b
        deltas.append(delta)
        if delta == 0:
            ties += 1
        elif (delta > 0) == (direction is MetricDirection.HIGHER_IS_BETTER):
            wins += 1
        else:
            losses += 1
    return {
        "paired_n": usable,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": None if usable == 0 else wins / usable,
        "mean_paired_delta": None if not deltas else sum(deltas) / len(deltas),
    }


def compare(
    runs: Sequence[RunResult],
    *,
    baseline: str,
    candidates: Sequence[str] | None = None,
    metrics: Sequence[str] | None = None,
    policy: RegressionPolicy | None = None,
) -> dict[str, Any]:
    if not baseline:
        raise ValidationError("baseline variant id is required")
    by_variant: dict[str, list[RunResult]] = defaultdict(list)
    for run in runs:
        by_variant[run.variant_id].append(run)
    if baseline not in by_variant:
        raise ValidationError(f"baseline variant {baseline!r} has no runs")
    if candidates is None:
        candidates = tuple(v for v in by_variant if v != baseline)
    if metrics is None:
        metrics = (
            "success",
            "duration_seconds",
            "latency_seconds",
            "cost",
            "total_tokens",
            "validation_passed",
        )
    baseline_runs = by_variant[baseline]
    comparisons: list[dict[str, Any]] = []
    hard_failures: list[str] = []
    for candidate in candidates:
        cand_runs = by_variant.get(candidate, [])
        metric_rows = []
        for metric in metrics:
            row = compare_metric(baseline_runs, cand_runs, metric, policy=policy)
            direction = MetricDirection(row["direction"])
            row["paired"] = paired_comparison(baseline_runs, cand_runs, metric, direction=direction)
            metric_rows.append(row)
            if row.get("hard_gate") and row["classification"] == RegressionClass.REGRESSED.value:
                hard_failures.append(f"{candidate}:{metric}")
        comparisons.append(
            {
                "baseline": baseline,
                "candidate": candidate,
                "metrics": metric_rows,
            }
        )
    return {
        "schema_version": 1,
        "baseline": baseline,
        "candidates": list(candidates),
        "comparisons": comparisons,
        "hard_gate_failures": hard_failures,
        "hard_gate_passed": not hard_failures,
    }
