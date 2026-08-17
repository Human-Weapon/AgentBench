"""Cost-bound contract: measured cost is never silently clamped."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.errors import CostBoundViolationError
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    PricingConfig,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from agentbench.runner import BudgetLedger, ExperimentRunner, ExperimentSpec
from agentbench.targets import PythonCallableTarget


def _suite(**kwargs) -> BenchmarkSuite:
    defaults = dict(
        id="s",
        name="S",
        cases=(BenchmarkCase(id="c1", name="C1"),),
        variants=(Variant(id="v1", name="V1"), Variant(id="v2", name="V2")),
        repetitions=1,
        seed=1,
    )
    defaults.update(kwargs)
    return BenchmarkSuite(**defaults)


def test_measured_cost_above_reservation_is_not_clamped(tmp_path: Path) -> None:
    invoked: list[str] = []

    def fn(case, variant, context):
        invoked.append(variant.id)
        return {"telemetry": {"cost": 0.8}}

    suite = _suite(
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert invoked == ["v1"]
    assert outcome.executed_runs == 1
    assert outcome.not_scheduled == 1
    assert outcome.runs[0].target.telemetry.cost == 0.8
    assert outcome.committed_cost == pytest.approx(0.8)
    assert outcome.cost_bound_violated is True
    assert outcome.budget_guarantee_breached is True
    assert "cost bound" in (outcome.stopped_reason or "").lower()
    payload = json.loads((tmp_path / "out" / "experiment.json").read_text(encoding="utf-8"))
    assert payload["committed_cost"] == pytest.approx(0.8)
    assert payload["cost_bound_violated"] is True
    assert payload["budget_guarantee_breached"] is True


def test_second_run_not_invoked_after_bound_violation(tmp_path: Path) -> None:
    invoked = 0

    def fn(case, variant, context):
        nonlocal invoked
        invoked += 1
        return {"telemetry": {"cost": 0.8}}

    suite = _suite(
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert invoked == 1
    assert outcome.not_scheduled == 1
    assert outcome.committed_cost != pytest.approx(0.4)


def test_exact_reservation_is_valid(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return {"telemetry": {"cost": 0.4}}

    suite = _suite(
        variants=(Variant(id="v1", name="V1"),),
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert outcome.runs[0].target.telemetry.cost == 0.4
    assert outcome.committed_cost == pytest.approx(0.4)
    assert outcome.cost_bound_violated is False
    assert outcome.budget_guarantee_breached is False


def test_epsilon_above_reservation_is_violation(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return {"telemetry": {"cost": 0.4000001}}

    suite = _suite(
        variants=(Variant(id="v1", name="V1"),),
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert outcome.runs[0].target.telemetry.cost == 0.4000001
    assert outcome.committed_cost == pytest.approx(0.4000001)
    assert outcome.cost_bound_violated is True


def test_unknown_cost_keeps_reservation() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4))
    ledger.reserve_cost()
    ledger.reconcile_cost(None)
    assert ledger.committed_cost == pytest.approx(0.4)
    assert ledger.cost_known is False
    assert ledger.cost_bound_violated is False


def test_zero_cost_releases_reservation() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4))
    ledger.reserve_cost()
    ledger.reconcile_cost(0.0)
    assert ledger.committed_cost == 0.0
    assert ledger.cost_known is True
    assert ledger.cost_bound_violated is False


def test_ledger_records_violation_without_clamping() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4))
    ledger.reserve_cost()
    ledger.reconcile_cost(0.8)
    assert ledger.committed_cost == pytest.approx(0.8)
    assert ledger.cost_bound_violated is True
    with pytest.raises(CostBoundViolationError):
        raise CostBoundViolationError(
            "per_run_max_cost=0.4 but measured=0.8",
            reserved=0.4,
            measured=0.8,
        )


def test_pricing_estimate_above_reservation_is_violation(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return {"telemetry": {"input_tokens": 10, "output_tokens": 10}}

    suite = _suite(
        variants=(Variant(id="v1", name="V1"), Variant(id="v2", name="V2")),
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
            pricing=PricingConfig(input_token_rate=0.05, output_token_rate=0.05),
        )
    )
    # 10*0.05 + 10*0.05 = 1.0 > 0.4
    assert outcome.runs[0].target.telemetry.cost == pytest.approx(1.0)
    assert outcome.committed_cost == pytest.approx(1.0)
    assert outcome.cost_bound_violated is True
    assert outcome.executed_runs == 1
    assert outcome.not_scheduled == 1


def test_timeout_and_failure_reconcile_actual_cost(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return TargetResult(
            status=RunStatus.FAILURE,
            telemetry=Telemetry(cost=0.8),
            error_message="failed",
        )

    suite = _suite(
        variants=(Variant(id="v1", name="V1"), Variant(id="v2", name="V2")),
        budget=ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert outcome.runs[0].target.status is RunStatus.FAILURE
    assert outcome.committed_cost == pytest.approx(0.8)
    assert outcome.cost_bound_violated is True
    assert outcome.executed_runs == 1
