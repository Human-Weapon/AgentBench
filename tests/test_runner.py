from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentbench.errors import BudgetExceededError
from agentbench.evaluators import ExitCodeEvaluator
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from agentbench.runner import BudgetLedger, ExperimentRunner, ExperimentSpec
from agentbench.targets import CommandTarget, PythonCallableTarget


def _suite(**kwargs) -> BenchmarkSuite:
    defaults = dict(
        id="s",
        name="S",
        cases=(BenchmarkCase(id="c1", name="C1", payload={"n": 1}),),
        variants=(Variant(id="v1", name="V1"),),
        repetitions=1,
        seed=7,
    )
    defaults.update(kwargs)
    return BenchmarkSuite(**defaults)


def test_max_runs_allows_exactly_n(tmp_path: Path) -> None:
    ledger = BudgetLedger(ExecutionBudget(max_runs=2))
    ledger.check_can_start(elapsed_seconds=0)
    ledger.mark_started()
    ledger.check_can_start(elapsed_seconds=0)
    ledger.mark_started()
    with pytest.raises(BudgetExceededError):
        ledger.check_can_start(elapsed_seconds=0)


def test_max_runs_zero_rejects_first() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_runs=0))
    with pytest.raises(BudgetExceededError):
        ledger.check_can_start(elapsed_seconds=0)


def test_cost_budget_is_not_reused() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0))
    from agentbench.models import RunResult

    run = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(status=RunStatus.SUCCESS, telemetry=Telemetry(cost=0.6)),
    )
    ledger.mark_started()
    ledger.mark_finished(run)
    ledger.mark_started()
    ledger.mark_finished(run)
    with pytest.raises(BudgetExceededError, match="max_total_cost"):
        ledger.check_can_start(elapsed_seconds=0)
    assert ledger.committed_cost == pytest.approx(1.2)


def test_runner_hard_max_runs(tmp_path: Path) -> None:
    suite = _suite(
        variants=(Variant(id="a", name="A"), Variant(id="b", name="B")),
        budget=ExecutionBudget(max_runs=1, per_run_timeout_seconds=10),
    )

    def ok(case, variant, context):
        return {"telemetry": {"cost": 0.1}}

    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(ok),
            output_root=tmp_path / "out",
        )
    )
    executed = [r for r in outcome.runs if r.target.status is not RunStatus.SKIPPED]
    skipped = [r for r in outcome.runs if r.target.status is RunStatus.SKIPPED]
    assert len(executed) == 1
    assert len(skipped) == 1
    assert outcome.budget_exhausted is True
    assert (tmp_path / "out" / "runs").is_dir()
    assert len(list((tmp_path / "out" / "runs").glob("*.json"))) == 2


def test_target_failure_does_not_abort_experiment(tmp_path: Path) -> None:
    suite = _suite(
        cases=(
            BenchmarkCase(id="ok", name="ok"),
            BenchmarkCase(id="bad", name="bad"),
        )
    )

    def fn(case, variant, context):
        if case.id == "bad":
            raise RuntimeError("boom")
        return {"ok": True}

    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "out")
    )
    statuses = {r.case_id: r.target.status for r in outcome.runs}
    assert statuses["ok"] is RunStatus.SUCCESS
    assert statuses["bad"] is RunStatus.FAILURE
    assert all((tmp_path / "out" / "runs" / f"{r.run_id}.json").exists() for r in outcome.runs)


def test_later_failure_does_not_erase_earlier_results(tmp_path: Path) -> None:
    suite = _suite(
        cases=tuple(BenchmarkCase(id=f"c{i}", name=f"C{i}") for i in range(3)),
    )
    seen = []

    def fn(case, variant, context):
        seen.append(case.id)
        if case.id == "c2":
            raise RuntimeError("fail-last")
        return {"ok": True}

    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "out")
    )
    assert (tmp_path / "out" / "runs" / outcome.runs[0].run_id).with_suffix(".json").exists()
    assert (tmp_path / "out" / "runs" / outcome.runs[1].run_id).with_suffix(".json").exists()
    assert outcome.runs[2].target.status is RunStatus.FAILURE


def test_timeout_counts_as_benchmark_data(tmp_path: Path, scripts: Path) -> None:
    suite = _suite(budget=ExecutionBudget(per_run_timeout_seconds=0.3, max_runs=1))
    target = CommandTarget([sys.executable, str(scripts / "sleep.py"), "20"])
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=target, output_root=tmp_path / "out")
    )
    assert outcome.runs[0].target.status is RunStatus.TIMEOUT
    assert outcome.runs[0].target.timed_out is True
    assert outcome.runs[0].target.infrastructure_error is False


def test_validation_can_fail_when_target_succeeds(tmp_path: Path) -> None:
    suite = _suite(
        cases=(
            BenchmarkCase(
                id="c1",
                name="C1",
                validation_command=(sys.executable, "-c", "raise SystemExit(3)"),
            ),
        )
    )

    def ok(case, variant, context):
        return {"ok": True}

    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(ok),
            evaluators=(ExitCodeEvaluator(0),),
            output_root=tmp_path / "out",
        )
    )
    run = outcome.runs[0]
    assert run.target.status is RunStatus.SUCCESS
    assert run.validation_passed is False
    names = {ev.evaluator: ev.passed for ev in run.evaluations}
    assert names["validation_command"] is False


def test_workspace_source_unchanged_through_runner(tmp_path: Path, scripts: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    seed = template / "seed.txt"
    seed.write_text("keep", encoding="utf-8")
    suite = _suite(workspace_template=str(template))
    target = CommandTarget([sys.executable, str(scripts / "mutate_workspace.py")])
    ExperimentRunner().run(ExperimentSpec(suite=suite, target=target, output_root=tmp_path / "out"))
    assert seed.read_text(encoding="utf-8") == "keep"


def test_same_seed_is_deterministic_for_run_ids(tmp_path: Path) -> None:
    suite = _suite(seed=99)

    def ok(case, variant, context):
        return {"ok": True}

    a = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(ok), output_root=tmp_path / "a")
    )
    b = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(ok), output_root=tmp_path / "b")
    )
    assert [r.run_id for r in a.runs] == [r.run_id for r in b.runs]


def test_evaluator_raise_is_recorded(tmp_path: Path) -> None:
    class Boom:
        name = "boom"

        def evaluate(self, context):
            raise RuntimeError("evaluator exploded")

    def ok(case, variant, context):
        return {"ok": True}

    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=_suite(),
            target=PythonCallableTarget(ok),
            evaluators=(Boom(),),
            output_root=tmp_path / "out",
        )
    )
    assert outcome.runs[0].evaluations[0].error
    assert outcome.runs[0].evaluations[0].passed is None
    assert outcome.runs[0].target.status is RunStatus.SUCCESS
