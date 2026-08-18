"""Round-4: explicit null vs omitted, timestamp parity, typed path/error fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentbench.errors import CorruptResultError, ValidationError
from agentbench.models import (
    EvaluationResult,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
    WorkspaceDiff,
)
from agentbench.persistence import ResultStore, run_result_from_dict


def _base_run(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "run_id": "s__c__v__r0__s0",
        "case_id": "c",
        "variant_id": "v",
        "repetition": 0,
        "seed": 0,
        "target": {"status": "SUCCESS"},
    }
    data.update(overrides)
    return data


def test_ab4001_explicit_null_details_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(
            _base_run(evaluations=[{"evaluator": "x", "passed": True, "details": None}])
        )


def test_ab4001_explicit_null_stdout_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(target={"status": "SUCCESS", "stdout": None}))


def test_ab4001_explicit_null_evaluations_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(evaluations=None))


def test_ab4001_explicit_null_path_list_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(workspace_diff={"created_paths": None}))


def test_ab4001_omitted_fields_remain_defaults() -> None:
    result = run_result_from_dict(_base_run())
    assert result.started_at == ""
    assert result.evaluations == ()
    assert result.target.stdout == ""
    assert result.target.telemetry.cost is None


def test_ab4002_none_timestamp_rejected_at_construction() -> None:
    with pytest.raises(ValidationError):
        RunResult(
            run_id="s__c__v__r0__s0",
            case_id="c",
            variant_id="v",
            repetition=0,
            seed=0,
            target=TargetResult(status=RunStatus.SUCCESS),
            started_at=None,  # type: ignore[arg-type]
        )


def test_ab4002_numeric_timestamp_rejected_at_construction() -> None:
    with pytest.raises(ValidationError):
        RunResult(
            run_id="s__c__v__r0__s0",
            case_id="c",
            variant_id="v",
            repetition=0,
            seed=0,
            target=TargetResult(status=RunStatus.SUCCESS),
            started_at=1710000000,  # type: ignore[arg-type]
        )


def test_ab4002_valid_iso_timestamp_round_trips(tmp_path: Path) -> None:
    stamp = "2026-04-08T12:00:00+00:00"
    result = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(status=RunStatus.SUCCESS),
        started_at=stamp,
        finished_at=stamp,
    )
    store = ResultStore(tmp_path)
    store.write_run(result)
    loaded = store.load_run(result.run_id)
    assert loaded.started_at == stamp
    assert loaded.finished_at == stamp


def test_ab4002_persisted_null_timestamp_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(started_at=None))


def test_ab4002_persisted_numeric_timestamp_is_corrupt() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(started_at=1))


def test_ab4003_workspace_paths_reject_non_strings() -> None:
    with pytest.raises(ValidationError):
        WorkspaceDiff(created_paths=({"p": 1},))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WorkspaceDiff(created_paths=(None,))  # type: ignore[arg-type]
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(workspace_diff={"created_paths": [{}]}))
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(workspace_diff={"created_paths": [1]}))


def test_ab4003_error_fields_reject_non_strings() -> None:
    with pytest.raises(ValidationError):
        TargetResult(status=RunStatus.SUCCESS, error_message={"x": 1})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        EvaluationResult(evaluator="x", passed=True, error=["nope"])  # type: ignore[arg-type]
    with pytest.raises(CorruptResultError):
        run_result_from_dict(_base_run(target={"status": "SUCCESS", "error_message": {"x": 1}}))
    with pytest.raises(CorruptResultError):
        run_result_from_dict(
            _base_run(evaluations=[{"evaluator": "x", "passed": True, "error": []}])
        )


def test_nullable_error_null_round_trips(tmp_path: Path) -> None:
    result = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(status=RunStatus.SUCCESS, error_message=None),
        evaluations=(EvaluationResult(evaluator="x", passed=True, error=None),),
    )
    store = ResultStore(tmp_path)
    store.write_run(result)
    loaded = store.load_run(result.run_id)
    assert loaded.target.error_message is None
    assert loaded.evaluations[0].error is None


def test_valid_falsey_values_round_trip(tmp_path: Path) -> None:
    result = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(
            status=RunStatus.SUCCESS,
            stdout="",
            telemetry=Telemetry(cost=0.0, extra={}),
            artifacts={},
        ),
        evaluations=(),
        workspace_diff=WorkspaceDiff(files_created=0, created_paths=()),
        started_at="",
        finished_at="",
    )
    store = ResultStore(tmp_path)
    store.write_run(result)
    loaded = store.load_run(result.run_id)
    assert loaded.target.stdout == ""
    assert loaded.target.telemetry.cost == 0.0
    assert loaded.workspace_diff is not None
    assert loaded.workspace_diff.files_created == 0
    assert loaded.workspace_diff.created_paths == ()
    assert loaded.started_at == ""
