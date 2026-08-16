from __future__ import annotations

import math

import pytest

from agentbench.errors import ValidationError
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDefinition,
    MetricDirection,
    PricingConfig,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
    make_run_id,
)


def test_duplicate_case_id_rejected() -> None:
    case = BenchmarkCase(id="a", name="A")
    variant = Variant(id="v", name="V")
    with pytest.raises(ValidationError, match="duplicate case"):
        BenchmarkSuite(
            id="s",
            name="S",
            cases=(case, BenchmarkCase(id="a", name="A2")),
            variants=(variant,),
        )


def test_duplicate_variant_id_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate variant"):
        BenchmarkSuite(
            id="s",
            name="S",
            cases=(BenchmarkCase(id="c", name="C"),),
            variants=(Variant(id="v", name="V"), Variant(id="v", name="V2")),
        )


def test_repetitions_zero_and_bool_rejected() -> None:
    kwargs = dict(
        id="s",
        name="S",
        cases=(BenchmarkCase(id="c", name="C"),),
        variants=(Variant(id="v", name="V"),),
    )
    with pytest.raises(ValidationError):
        BenchmarkSuite(**kwargs, repetitions=0)
    with pytest.raises(ValidationError):
        BenchmarkSuite(**kwargs, repetitions=-1)
    with pytest.raises(ValidationError):
        BenchmarkSuite(**kwargs, repetitions=True)


def test_timeout_nan_rejected() -> None:
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", timeout_seconds=math.nan)
    with pytest.raises(ValidationError):
        ExecutionBudget(per_run_timeout_seconds=math.inf)


def test_budget_zero_is_valid() -> None:
    budget = ExecutionBudget(max_runs=0, max_total_cost=0.0, max_failures=0)
    assert budget.max_runs == 0
    assert budget.max_total_cost == 0.0


def test_budget_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecutionBudget(max_runs=-1)


def test_missing_telemetry_stays_none() -> None:
    tel = Telemetry()
    assert tel.cost is None
    assert tel.input_tokens is None
    assert tel.stall_count is None
    assert tel.as_dict()["cost"] is None


def test_telemetry_zero_is_measured_zero() -> None:
    tel = Telemetry(cost=0.0, stalls=0)
    assert tel.cost == 0.0
    assert tel.stalls == 0


def test_telemetry_bool_and_nan_rejected() -> None:
    with pytest.raises(ValidationError):
        Telemetry(cost=True)
    with pytest.raises(ValidationError):
        Telemetry(latency_seconds=math.nan)


def test_pricing_does_not_invent_cost() -> None:
    cfg = PricingConfig()
    assert cfg.estimate(10, 10) is None
    priced = PricingConfig(input_token_rate=0.001, output_token_rate=0.002)
    assert priced.estimate(10, 5) == pytest.approx(0.02)
    assert priced.estimate(None, 5) is None


def test_shell_string_validation_command_rejected() -> None:
    with pytest.raises(ValidationError, match="argv"):
        BenchmarkCase(id="c", name="C", validation_command="rm -rf /")


def test_case_and_variant_ids_must_be_safe() -> None:
    with pytest.raises(ValidationError):
        BenchmarkCase(id="../escape", name="x")
    with pytest.raises(ValidationError):
        Variant(id="C:\\abs", name="x")
    with pytest.raises(ValidationError):
        BenchmarkCase(id="", name="x")


def test_timeout_status_is_explicit() -> None:
    result = TargetResult(status=RunStatus.TIMEOUT, timed_out=True)
    assert result.timed_out is True
    with pytest.raises(ValidationError):
        TargetResult(status=RunStatus.FAILURE, timed_out=True)


def test_metric_direction_required() -> None:
    MetricDefinition(name="latency", direction=MetricDirection.LOWER_IS_BETTER)
    with pytest.raises(ValidationError):
        MetricDefinition(name="x", direction="SIDEWAYS")


def test_run_id_is_deterministic() -> None:
    a = make_run_id("suite", "case", "var", 0, 42)
    b = make_run_id("suite", "case", "var", 0, 42)
    assert a == b
    assert a != make_run_id("suite", "case", "var", 1, 42)
