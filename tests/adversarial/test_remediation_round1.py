"""Round-1 remediation regressions. These exercise production boundaries."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from agentbench.aggregation import detect_flaky
from agentbench.cli import main
from agentbench.config import load_suite, suite_from_dict
from agentbench.errors import (
    ConfigurationError,
    CorruptResultError,
    TargetExecutionError,
    ValidationError,
)
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDirection,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from agentbench.persistence import ResultStore, assert_unused_output
from agentbench.regression import MetricRule, RegressionPolicy
from agentbench.runner import BudgetLedger, ExperimentRunner, ExperimentSpec
from agentbench.targets import CommandTarget, PythonCallableTarget
from agentbench.workspace import DirectoryCopyWorkspace


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


def test_ab001_hard_cost_requires_reservation() -> None:
    with pytest.raises(ValidationError, match="per_run_max_cost"):
        ExecutionBudget(max_total_cost=1.0)


def test_ab001_unknown_cost_cannot_bypass_cap(tmp_path: Path) -> None:
    invoked = []

    def fn(case, variant, context):
        invoked.append(variant.id)
        return {"telemetry": {"cost": None}}

    suite = _suite(
        variants=(Variant(id="a", name="A"), Variant(id="b", name="B")),
        budget=ExecutionBudget(
            max_total_cost=0.5,
            per_run_max_cost=0.5,
            per_run_timeout_seconds=5,
        ),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "out")
    )
    assert invoked == ["a"]
    assert outcome.executed_runs == 1
    assert outcome.not_scheduled == 1
    assert outcome.budget_exhausted is True
    assert outcome.runs[0].target.telemetry.cost is None


def test_ab001_next_reservation_not_invoked(tmp_path: Path) -> None:
    invoked = []

    def fn(case, variant, context):
        invoked.append(1)
        return {"telemetry": {"cost": 0.4}}

    suite = _suite(
        variants=(Variant(id="a", name="A"), Variant(id="b", name="B")),
        budget=ExecutionBudget(max_total_cost=0.5, per_run_max_cost=0.4),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "out")
    )
    assert invoked == [1]
    assert outcome.executed_runs == 1
    assert outcome.not_scheduled == 1


def test_ab001_zero_measured_cost_stays_zero() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.5))
    ledger.reserve_cost()
    run = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(status=RunStatus.SUCCESS, telemetry=Telemetry(cost=0.0)),
    )
    ledger.mark_finished(run)
    assert ledger.committed_cost == 0.0
    assert ledger.cost_known is True


def test_ab001_reservation_cannot_go_negative() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_cost=1.0, per_run_max_cost=0.2))
    ledger.reserve_cost()
    ledger.reconcile_cost(0.05)
    assert ledger.committed_cost == pytest.approx(0.05)
    ledger.committed_cost = 0.0
    ledger._open_reservation = 0.1
    ledger.reconcile_cost(0.0)
    assert ledger.committed_cost >= 0.0


def test_ab001_bool_nan_negative_cost_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecutionBudget(max_total_cost=True, per_run_max_cost=1.0)
    with pytest.raises(ValidationError):
        ExecutionBudget(max_total_cost=1.0, per_run_max_cost=float("nan"))
    with pytest.raises(ValidationError):
        ExecutionBudget(max_total_cost=-1.0, per_run_max_cost=1.0)


def test_ab002_case_workspace_source_unchanged(tmp_path: Path, scripts: Path) -> None:
    template = tmp_path / "case-template"
    template.mkdir()
    sentinel = template / "keep.txt"
    sentinel.write_text("original", encoding="utf-8")
    suite = _suite(
        cases=(
            BenchmarkCase(
                id="c1",
                name="C1",
                workspace_template=str(template),
            ),
        )
    )
    target = CommandTarget([sys.executable, str(scripts / "mutate_workspace.py")])
    ExperimentRunner().run(ExperimentSpec(suite=suite, target=target, output_root=tmp_path / "out"))
    assert sentinel.read_text(encoding="utf-8") == "original"


def test_ab002_mutating_original_template_is_detected(tmp_path: Path) -> None:
    from agentbench.errors import SourceMutationError

    template = tmp_path / "case-template"
    template.mkdir()
    (template / "keep.txt").write_text("original", encoding="utf-8")

    def mutate(case, variant, context):
        Path(case.workspace_template, "keep.txt").write_text("mutated", encoding="utf-8")
        return {"ok": True}

    suite = _suite(cases=(BenchmarkCase(id="c1", name="C1", workspace_template=str(template)),))
    with pytest.raises(SourceMutationError):
        ExperimentRunner().run(
            ExperimentSpec(
                suite=suite,
                target=PythonCallableTarget(mutate),
                output_root=tmp_path / "out",
            )
        )


def test_ab003_timeout_kills_child_process(tmp_path: Path, scripts: Path) -> None:
    suite = _suite(budget=ExecutionBudget(per_run_timeout_seconds=0.4, max_runs=1))
    target = CommandTarget([sys.executable, str(scripts / "spawn_child.py"), "30"])
    started = time.perf_counter()
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=target, output_root=tmp_path / "out")
    )
    elapsed = time.perf_counter() - started
    assert outcome.runs[0].target.status is RunStatus.TIMEOUT
    assert elapsed < 8
    stdout = outcome.runs[0].target.stdout
    if "CHILD_PID=" in stdout:
        child_pid = int(stdout.split("CHILD_PID=")[1].split()[0])
        deadline = time.time() + 3
        while time.time() < deadline:
            if not _pid_alive(child_pid):
                break
            time.sleep(0.05)
        assert not _pid_alive(child_pid)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_ab004_reuse_of_output_rejected(tmp_path: Path) -> None:
    out = tmp_path / "out"
    invoked = []

    def fn(case, variant, context):
        invoked.append(1)
        return {"ok": True}

    ExperimentRunner().run(
        ExperimentSpec(suite=_suite(), target=PythonCallableTarget(fn), output_root=out)
    )
    first = list(invoked)
    with pytest.raises(ConfigurationError, match="already contains"):
        ExperimentRunner().run(
            ExperimentSpec(suite=_suite(), target=PythonCallableTarget(fn), output_root=out)
        )
    assert invoked == first
    assert (out / "experiment.json").exists()


def test_ab004_empty_dir_allowed(tmp_path: Path) -> None:
    out = tmp_path / "empty"
    out.mkdir()
    assert_unused_output(out)
    ExperimentRunner().run(
        ExperimentSpec(
            suite=_suite(),
            target=PythonCallableTarget(lambda c, v, x: {"ok": True}),
            output_root=out,
        )
    )


def test_ab005_unscheduled_not_in_metrics(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return TargetResult(status=RunStatus.SUCCESS, exit_code=0)

    suite = _suite(
        repetitions=3,
        budget=ExecutionBudget(max_runs=2, per_run_timeout_seconds=5),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "out")
    )
    assert outcome.executed_runs == 2
    assert outcome.not_scheduled == 1
    assert all(r.target.status is RunStatus.SUCCESS for r in outcome.runs)
    assert detect_flaky(outcome.runs) == []
    rate = outcome.summary["success_rate"]
    assert rate == 1.0


def test_ab006_total_duration_caps_active_run(tmp_path: Path, scripts: Path) -> None:
    suite = _suite(
        budget=ExecutionBudget(
            per_run_timeout_seconds=30,
            max_total_duration_seconds=0.5,
            max_runs=1,
        )
    )
    target = CommandTarget([sys.executable, str(scripts / "sleep.py"), "20"])
    started = time.perf_counter()
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=target, output_root=tmp_path / "out")
    )
    elapsed = time.perf_counter() - started
    assert outcome.runs[0].target.status is RunStatus.TIMEOUT
    assert elapsed < 8


def test_ab007_nested_corrupt_storage_rejected(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    good = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(status=RunStatus.SUCCESS, telemetry=Telemetry(cost=1.0)),
    )
    path = store.write_run(good)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target"]["telemetry"]["cost"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorruptResultError):
        store.load_run(good.run_id)


def test_ab007_nested_nan_rejected(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    path = store.root / "runs" / "s__c__v__r0__s0.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "s__c__v__r0__s0",
                "case_id": "c",
                "variant_id": "v",
                "repetition": 0,
                "seed": 0,
                "target": {
                    "status": "SUCCESS",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_seconds": 0.1,
                    "telemetry": {"cost": float("nan")},
                },
            },
            allow_nan=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(CorruptResultError):
        store.load_run("s__c__v__r0__s0")


def test_ab008_nested_immutability() -> None:
    nested = {"a": {"b": [1, 2]}}
    case = BenchmarkCase(id="c", name="C", metadata=nested, payload={"x": [1]})
    nested["a"]["b"].append(3)
    nested["z"] = 9
    assert list(case.metadata["a"]["b"]) == [1, 2]
    assert "z" not in case.metadata
    with pytest.raises((TypeError, AttributeError)):
        case.metadata["a"]["b"].append(4)  # type: ignore[attr-defined]


def test_ab009_typo_rejected() -> None:
    with pytest.raises(ConfigurationError, match="unknown"):
        suite_from_dict({"id": "s", "cases": [], "variants": [], "repetitons": 3})


def test_ab009_relative_path_bound_to_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_dir = tmp_path / "cfg"
    other = tmp_path / "cwd"
    cfg_dir.mkdir()
    other.mkdir()
    ws = cfg_dir / "ws"
    ws.mkdir()
    (ws / "seed.txt").write_text("here", encoding="utf-8")
    cfg = cfg_dir / "suite.json"
    cfg.write_text(
        json.dumps(
            {
                "id": "rel",
                "cases": [{"id": "c", "name": "C"}],
                "variants": [{"id": "v", "name": "V"}],
                "workspace_template": "ws",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(other)
    suite = load_suite(cfg)
    assert Path(suite.workspace_template).resolve() == ws.resolve()


def test_ab010_duplicate_and_raw_enum() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        RegressionPolicy(
            baseline_variant_id="b",
            rules=(
                MetricRule("cost", MetricDirection.LOWER_IS_BETTER, absolute_threshold=1),
                MetricRule("cost", MetricDirection.LOWER_IS_BETTER, relative_threshold=0.1),
            ),
        )
    parsed = MetricDirection.parse("LOWER_IS_BETTER")
    assert parsed is MetricDirection.LOWER_IS_BETTER
    with pytest.raises(ValidationError):
        MetricDirection.parse("better")
    with pytest.raises(ValidationError):
        MetricDirection.parse(1)


def test_ab011_invalid_target_return(tmp_path: Path) -> None:
    def bad(case, variant, context):
        return "not-a-result"

    with pytest.raises(TargetExecutionError, match="TargetResult"):
        ExperimentRunner().run(
            ExperimentSpec(
                suite=_suite(),
                target=PythonCallableTarget(bad),
                output_root=tmp_path / "out",
            )
        )


def test_ab011_invalid_telemetry_not_unknown() -> None:
    def bad(case, variant, context):
        return {"telemetry": {"cost": float("nan")}}

    with pytest.raises(TargetExecutionError, match="telemetry"):
        PythonCallableTarget(bad).run(
            BenchmarkCase(id="c", name="C"),
            Variant(id="v", name="V"),
            {},
        )


def test_ab012_nan_in_config_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "suite.json"
    cfg.write_text(
        '{"id":"s","budget":{"per_run_timeout_seconds":NaN},"cases":[],"variants":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_suite(cfg)


def test_ab013_escaping_link_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("LEAK", encoding="utf-8")
    template = tmp_path / "template"
    template.mkdir()
    (template / "ok.txt").write_text("ok", encoding="utf-8")
    link = template / "escape"
    try:
        if os.name == "nt":
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip("junction creation not available")
        else:
            os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create link")
    with pytest.raises(ValidationError, match="escaping"):
        DirectoryCopyWorkspace(template)


def test_ab014_global_json_before_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "suite.json"
    cfg.write_text(
        json.dumps(
            {
                "id": "s",
                "cases": [{"id": "c", "name": "C"}],
                "variants": [{"id": "v", "name": "V"}],
                "target": {"type": "command", "argv": [sys.executable, "-c", "pass"]},
            }
        ),
        encoding="utf-8",
    )
    assert main(["--json", "validate", str(cfg)]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert main(["validate", str(cfg), "--json"]) == 0
    out2 = capsys.readouterr().out
    assert json.loads(out2)["ok"] is True


def test_ab015_stdout_bounded(scripts: Path) -> None:
    target = CommandTarget(
        [sys.executable, str(scripts / "emit_large.py"), "3"],
        max_stdout_bytes=64_000,
        timeout_seconds=20,
    )
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.SUCCESS
    assert result.artifacts["stdout_truncated"] is True
    assert len(result.stdout.encode("utf-8")) <= 64_000


def test_ab015_bool_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        CommandTarget([sys.executable, "-c", "pass"], max_stdout_bytes=True)
