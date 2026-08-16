from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentbench.cli import main
from agentbench.config import _load_raw, load_suite
from agentbench.errors import ConfigurationError, ValidationError
from agentbench.evaluators import (
    ContainsTextEvaluator,
    ExactTextEvaluator,
    FileChangeEvaluator,
    RegexEvaluator,
    TestsPassedEvaluator,
    ValidationCommandEvaluator,
    evaluator_from_config,
)
from agentbench.models import (
    BenchmarkCase,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from agentbench.numbers import require_int, require_number
from agentbench.persistence import ResultStore
from agentbench.targets import CommandTarget, PythonCallableTarget


def test_numbers_bounds() -> None:
    with pytest.raises(ValidationError):
        require_int(0, name="n", allow_zero=False)
    with pytest.raises(ValidationError):
        require_int(1, name="n", minimum=2)
    with pytest.raises(ValidationError):
        require_int(5, name="n", maximum=3)
    with pytest.raises(ValidationError):
        require_number(0.0, name="x", allow_zero=False)
    with pytest.raises(ValidationError):
        require_number(1.0, name="x", minimum=2)
    with pytest.raises(ValidationError):
        require_number(9.0, name="x", maximum=3)


def test_model_validation_edges() -> None:
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", tags="nope")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", metadata=[1])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", validation_command=())
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", validation_command=["", "x"])
    with pytest.raises(ValidationError):
        BenchmarkCase(id="c", name="C", description=1)  # type: ignore[arg-type]


def test_evaluators_error_paths() -> None:
    with pytest.raises(ValidationError):
        ExactTextEvaluator("x").evaluate({})
    with pytest.raises(ValidationError):
        ExactTextEvaluator("x", source="nope")
    with pytest.raises(ValidationError):
        ContainsTextEvaluator("x", source="nope")
    with pytest.raises(ValidationError):
        RegexEvaluator("(")
    ctx = {"target": TargetResult(status=RunStatus.SUCCESS, stdout="abc", exit_code=0)}
    assert ExactTextEvaluator("abc", source="stdout").evaluate(ctx).passed is True
    assert ContainsTextEvaluator("ab", source="stdout").evaluate(ctx).passed is True
    missing = FileChangeEvaluator(min_created=1).evaluate(ctx)
    assert missing.passed is False
    tel = TargetResult(
        status=RunStatus.SUCCESS,
        telemetry=Telemetry(tests_passed=3, tests_failed=0),
        exit_code=0,
    )
    assert TestsPassedEvaluator().evaluate({"target": tel}).passed is True
    with pytest.raises(ValidationError):
        evaluator_from_config("nope")  # type: ignore[arg-type]


def test_validation_timeout_and_spawn(tmp_path: Path) -> None:
    ev = ValidationCommandEvaluator(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_seconds=0.2,
    )
    result = ev.evaluate({"target": TargetResult(status=RunStatus.SUCCESS), "cwd": str(tmp_path)})
    assert result.passed is False
    assert result.details.get("timeout") is True
    missing = ValidationCommandEvaluator([str(tmp_path / "no-such-bin.exe")])
    spawned = missing.evaluate(
        {"target": TargetResult(status=RunStatus.SUCCESS), "cwd": str(tmp_path)}
    )
    assert spawned.passed is False


def test_command_target_validation_and_oserror() -> None:
    with pytest.raises(ValidationError):
        CommandTarget([])
    with pytest.raises(ValidationError):
        CommandTarget(["python", ""])
    with pytest.raises(ValidationError):
        CommandTarget(["python"], env="nope")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        CommandTarget(["python"], env={1: "x"})  # type: ignore[arg-type]
    result = CommandTarget([str(Path("no-such-agentbench-bin-xyz"))]).run(
        BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {}
    )
    assert result.status is RunStatus.ERROR
    assert result.infrastructure_error is True


def test_callable_returns_target_result() -> None:
    def fn(case, variant, context):
        return TargetResult(status=RunStatus.SUCCESS, stdout="x", exit_code=0)

    result = PythonCallableTarget(fn, name="ret").run(
        BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {}
    )
    assert result.status is RunStatus.SUCCESS
    assert result.stdout == "x"


def test_structured_json_after_logs() -> None:
    target = CommandTarget(
        [sys.executable, "-c", "print('log'); print('{\"telemetry\": {\"cost\": 1.5}}')"]
    )
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.telemetry.cost == 1.5


def test_cli_no_command_and_compare_empty(tmp_path: Path, capsys) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "validate" in out
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["compare", str(empty)]) != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_suite(tmp_path / "missing.json")
    with pytest.raises(ConfigurationError):
        _load_raw(tmp_path / "missing.json")


def test_iter_runs_empty(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    (store.root / "runs").rmdir()
    assert store.iter_runs() == []
