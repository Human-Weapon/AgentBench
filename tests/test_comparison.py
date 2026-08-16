from __future__ import annotations

import pytest

from agentbench.aggregation import detect_flaky, summarize_numbers
from agentbench.comparison import compare, compare_metric
from agentbench.errors import ValidationError
from agentbench.frontier import pareto_frontier
from agentbench.metrics import composite_score
from agentbench.models import (
    MetricDefinition,
    MetricDirection,
    MissingMetricBehavior,
    RegressionClass,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
)
from agentbench.regression import MetricRule, RegressionPolicy


def _run(
    variant: str, case: str, rep: int, *, success: bool, cost: float | None, latency: float
) -> RunResult:
    return RunResult(
        run_id=f"s__{case}__{variant}__r{rep}__s1",
        case_id=case,
        variant_id=variant,
        repetition=rep,
        seed=1,
        target=TargetResult(
            status=RunStatus.SUCCESS if success else RunStatus.FAILURE,
            duration_seconds=latency,
            telemetry=Telemetry(cost=cost, latency_seconds=latency),
        ),
    )


def test_lower_is_better_regression() -> None:
    policy = RegressionPolicy(
        baseline_variant_id="base",
        rules=(
            MetricRule(
                metric="latency_seconds",
                direction=MetricDirection.LOWER_IS_BETTER,
                relative_threshold=0.10,
                min_sample_size=2,
            ),
        ),
    )
    base = [_run("base", "c", i, success=True, cost=1.0, latency=1.0) for i in range(3)]
    worse = [_run("cand", "c", i, success=True, cost=1.0, latency=1.5) for i in range(3)]
    row = compare_metric(base, worse, "latency_seconds", policy=policy)
    assert row["classification"] == RegressionClass.REGRESSED.value
    better = [_run("cand2", "c", i, success=True, cost=1.0, latency=0.5) for i in range(3)]
    row2 = compare_metric(base, better, "latency_seconds", policy=policy)
    assert row2["classification"] == RegressionClass.IMPROVED.value


def test_higher_is_better_success_rate() -> None:
    policy = RegressionPolicy(
        baseline_variant_id="base",
        rules=(
            MetricRule(
                metric="success",
                direction=MetricDirection.HIGHER_IS_BETTER,
                absolute_threshold=0.02,
                min_sample_size=2,
            ),
        ),
    )
    base = [_run("base", "c", i, success=True, cost=1.0, latency=1.0) for i in range(4)]
    worse = [
        _run("cand", "c", 0, success=True, cost=1.0, latency=1.0),
        _run("cand", "c", 1, success=False, cost=1.0, latency=1.0),
        _run("cand", "c", 2, success=False, cost=1.0, latency=1.0),
        _run("cand", "c", 3, success=False, cost=1.0, latency=1.0),
    ]
    row = compare_metric(base, worse, "success", policy=policy)
    assert row["classification"] == RegressionClass.REGRESSED.value


def test_insufficient_samples_inconclusive() -> None:
    policy = RegressionPolicy(
        baseline_variant_id="base",
        rules=(
            MetricRule(
                metric="cost",
                direction=MetricDirection.LOWER_IS_BETTER,
                relative_threshold=0.1,
                min_sample_size=5,
            ),
        ),
    )
    base = [_run("base", "c", 0, success=True, cost=1.0, latency=1.0)]
    cand = [_run("cand", "c", 0, success=True, cost=2.0, latency=1.0)]
    row = compare_metric(base, cand, "cost", policy=policy)
    assert row["classification"] == RegressionClass.INCONCLUSIVE.value


def test_missing_cost_unavailable() -> None:
    base = [_run("base", "c", 0, success=True, cost=None, latency=1.0)]
    cand = [_run("cand", "c", 0, success=True, cost=None, latency=1.0)]
    row = compare_metric(base, cand, "cost")
    assert row["classification"] == RegressionClass.UNAVAILABLE.value
    assert row["relative_delta"] is None


def test_zero_baseline_relative_delta_unavailable() -> None:
    base = [_run("base", "c", i, success=True, cost=0.0, latency=1.0) for i in range(2)]
    cand = [_run("cand", "c", i, success=True, cost=1.0, latency=1.0) for i in range(2)]
    policy = RegressionPolicy(
        baseline_variant_id="base",
        rules=(
            MetricRule(
                metric="cost",
                direction=MetricDirection.LOWER_IS_BETTER,
                relative_threshold=0.1,
                min_sample_size=2,
            ),
        ),
    )
    row = compare_metric(base, cand, "cost", policy=policy)
    assert row["relative_delta"] is None
    assert row["classification"] == RegressionClass.INCONCLUSIVE.value


def test_paired_win_rate() -> None:
    runs = [
        _run("base", "c1", 0, success=True, cost=2.0, latency=2.0),
        _run("cand", "c1", 0, success=True, cost=1.0, latency=1.0),
        _run("base", "c2", 0, success=True, cost=2.0, latency=2.0),
        _run("cand", "c2", 0, success=True, cost=3.0, latency=3.0),
    ]
    result = compare(runs, baseline="base", candidates=["cand"], metrics=["cost"])
    paired = result["comparisons"][0]["metrics"][0]["paired"]
    assert paired["paired_n"] == 2
    assert paired["wins"] == 1
    assert paired["losses"] == 1


def test_flakiness_not_hidden() -> None:
    runs = [
        _run("v", "c", 0, success=True, cost=1.0, latency=1.0),
        _run("v", "c", 1, success=False, cost=1.0, latency=1.0),
        _run("v", "c", 2, success=True, cost=1.0, latency=1.0),
    ]
    flaky = detect_flaky(runs)
    assert flaky
    assert flaky[0]["case_id"] == "c"


def test_contradictory_rules_rejected() -> None:
    with pytest.raises(ValidationError, match="contradictory"):
        RegressionPolicy(
            baseline_variant_id="b",
            rules=(
                MetricRule("cost", MetricDirection.LOWER_IS_BETTER, absolute_threshold=1),
                MetricRule("cost", MetricDirection.HIGHER_IS_BETTER, absolute_threshold=1),
            ),
        )


def test_composite_requires_normalization() -> None:
    defs = (
        MetricDefinition(
            name="success",
            direction=MetricDirection.HIGHER_IS_BETTER,
            minimum=0,
            maximum=1,
            weight=1,
        ),
        MetricDefinition(
            name="cost",
            direction=MetricDirection.LOWER_IS_BETTER,
            minimum=0,
            maximum=10,
            weight=1,
        ),
    )
    score = composite_score({"success": 1.0, "cost": 0.0}, defs)
    assert score == pytest.approx(1.0)
    with pytest.raises(ValidationError):
        composite_score(
            {"success": 1.0},
            (
                MetricDefinition(
                    name="success",
                    direction=MetricDirection.HIGHER_IS_BETTER,
                    weight=1,
                ),
            ),
        )
    assert (
        composite_score(
            {"success": None, "cost": None}, defs, missing=MissingMetricBehavior.UNKNOWN
        )
        is None
    )


def test_p95_flags_single_sample() -> None:
    summary = summarize_numbers([3.0])
    assert summary["n"] == 1
    assert summary["percentile_meaningful"] is False
    assert summary["p95"] == 3.0


def test_pareto_frontier() -> None:
    result = pareto_frontier(
        {
            "cheap_ok": {"success": 0.8, "cost": 1.0},
            "expensive_best": {"success": 1.0, "cost": 5.0},
            "dominated": {"success": 0.7, "cost": 4.0},
            "no_cost": {"success": 0.9, "cost": None},
        },
        {
            "success": MetricDirection.HIGHER_IS_BETTER,
            "cost": MetricDirection.LOWER_IS_BETTER,
        },
    )
    assert "dominated" in result["dominated"]
    assert "cheap_ok" in result["frontier"]
    assert "expensive_best" in result["frontier"]
    assert "no_cost" in result["incomplete"]
