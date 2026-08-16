"""Hostile checks for the v0.1.0 self-audit list (A–T)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from agentbench.adapters import AgentGearEvidenceAdapter
from agentbench.cli import main
from agentbench.errors import BudgetExceededError, CorruptResultError, ValidationError
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDirection,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from agentbench.persistence import ResultStore
from agentbench.regression import MetricRule, RegressionPolicy
from agentbench.runner import BudgetLedger, ExperimentRunner, ExperimentSpec
from agentbench.siblings import detect_integrations
from agentbench.targets import CommandTarget, PythonCallableTarget


def test_a_bool_cannot_bypass_int() -> None:
    with pytest.raises(ValidationError):
        ExecutionBudget(max_runs=True)


def test_b_nan_cannot_enter_cost() -> None:
    with pytest.raises(ValidationError):
        Telemetry(cost=math.nan)
    with pytest.raises(ValidationError):
        Telemetry(latency_seconds=math.inf)


def test_c_timeout_does_not_hang(scripts: Path) -> None:
    result = CommandTarget(
        [sys.executable, str(scripts / "sleep.py"), "20"], timeout_seconds=0.25
    ).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.TIMEOUT
    assert result.duration_seconds < 5


def test_d_failed_case_keeps_prior_results(tmp_path: Path) -> None:
    def fn(case, variant, context):
        if case.id == "b":
            raise RuntimeError("fail")
        return {"ok": True}

    suite = BenchmarkSuite(
        id="keep",
        name="keep",
        cases=(BenchmarkCase(id="a", name="A"), BenchmarkCase(id="b", name="B")),
        variants=(Variant(id="v", name="V"),),
    )
    out = tmp_path / "out"
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=out)
    )
    first = out / "runs" / f"{outcome.runs[0].run_id}.json"
    assert first.is_file()
    assert json.loads(first.read_text(encoding="utf-8"))["case_id"] == "a"


def test_e_output_ids_cannot_escape(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "root")
    with pytest.raises(ValidationError):
        store.run_path("../../etc/passwd")


def test_f_command_target_never_shell() -> None:
    with pytest.raises(ValidationError):
        CommandTarget("echo pwned")
    target = CommandTarget([sys.executable, "-c", "print('ok')"])
    assert target.describe()["shell"] is False


def test_g_missing_cost_is_not_zero() -> None:
    tel = Telemetry()
    assert tel.cost is None
    adapter = AgentGearEvidenceAdapter()
    assert adapter.to_telemetry({}).cost is None
    assert adapter.to_telemetry({"cost": 0.0}).cost == 0.0


def test_h_lower_is_better_compare() -> None:
    from agentbench.comparison import compare_metric
    from agentbench.models import RunResult

    def r(vid, lat):
        return RunResult(
            run_id=f"s__c__{vid}__r0__s1",
            case_id="c",
            variant_id=vid,
            repetition=0,
            seed=1,
            target=TargetResult(
                status=RunStatus.SUCCESS,
                telemetry=Telemetry(latency_seconds=lat),
                duration_seconds=lat,
            ),
        )

    policy = RegressionPolicy(
        baseline_variant_id="b",
        rules=(
            MetricRule(
                "latency_seconds",
                MetricDirection.LOWER_IS_BETTER,
                relative_threshold=0.05,
                min_sample_size=1,
            ),
        ),
    )
    row = compare_metric(
        [r("b", 1.0), r("b", 1.0)],
        [r("c", 2.0), r("c", 2.0)],
        "latency_seconds",
        policy=policy,
    )
    assert row["classification"] == "REGRESSED"


def test_i_relative_delta_zero_baseline() -> None:
    from agentbench.numbers import relative_delta

    assert relative_delta(0.0, 5.0) is None


def test_j_insufficient_samples_not_improved() -> None:
    from agentbench.comparison import compare_metric
    from agentbench.models import RunResult

    policy = RegressionPolicy(
        baseline_variant_id="b",
        rules=(
            MetricRule(
                "success",
                MetricDirection.HIGHER_IS_BETTER,
                absolute_threshold=0.01,
                min_sample_size=10,
            ),
        ),
    )
    base = [
        RunResult(
            run_id="s__c__b__r0__s1",
            case_id="c",
            variant_id="b",
            repetition=0,
            seed=1,
            target=TargetResult(status=RunStatus.FAILURE),
        )
    ]
    cand = [
        RunResult(
            run_id="s__c__x__r0__s1",
            case_id="c",
            variant_id="x",
            repetition=0,
            seed=1,
            target=TargetResult(status=RunStatus.SUCCESS),
        )
    ]
    row = compare_metric(base, cand, "success", policy=policy)
    assert row["classification"] == "INCONCLUSIVE"


def test_k_corrupt_result_not_silent(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    path = store.root / "runs" / "x.json"
    path.write_text('{"schema_version": 1, "run_id": "x"}', encoding="utf-8")
    with pytest.raises(CorruptResultError):
        store.iter_runs()


def test_n_cli_no_traceback_for_bad_config(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "s.json"
    bad.write_text(
        '{"id": "s", "cases": [{"id": "c", "name": "c"}], "variants": []}',
        encoding="utf-8",
    )
    assert main(["validate", str(bad)]) != 0
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith("error:")


def test_p_max_runs_boundary() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_runs=3))
    for _ in range(3):
        ledger.check_can_start(elapsed_seconds=0)
        ledger.mark_started()
    with pytest.raises(BudgetExceededError):
        ledger.check_can_start(elapsed_seconds=0)


def test_q_timeout_is_not_infrastructure(scripts: Path) -> None:
    result = CommandTarget(
        [sys.executable, str(scripts / "sleep.py"), "10"], timeout_seconds=0.2
    ).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.TIMEOUT
    assert result.infrastructure_error is False


def test_s_t_no_sibling_behavior_duplicated() -> None:
    flags = detect_integrations()
    # Standalone: integrations may be true on this machine if siblings are
    # installed, but AgentBench must still import without them.
    import agentbench

    assert agentbench.detect_integrations() == flags
    from agentbench import AgentGearEvidenceAdapter

    tel = AgentGearEvidenceAdapter().to_telemetry({"stall_count": 2, "recovery_attempts": 1})
    assert tel.stall_count == 2
    assert tel.recovery_attempts == 1
