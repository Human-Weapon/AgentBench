from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentbench.errors import ValidationError
from agentbench.evaluators import (
    ContainsTextEvaluator,
    ExactTextEvaluator,
    ExitCodeEvaluator,
    FileChangeEvaluator,
    JsonFieldEvaluator,
    RegexEvaluator,
    TestsPassedEvaluator,
    ValidationCommandEvaluator,
    evaluator_from_config,
)
from agentbench.models import RunStatus, TargetResult, WorkspaceDiff


def _ctx(**kwargs):
    target = kwargs.pop(
        "target", TargetResult(status=RunStatus.SUCCESS, stdout="hello", exit_code=0)
    )
    return {"target": target, **kwargs}


def test_exit_code_evaluator() -> None:
    assert ExitCodeEvaluator(0).evaluate(_ctx()).passed is True
    assert ExitCodeEvaluator(1).evaluate(_ctx()).passed is False


def test_text_evaluators() -> None:
    ctx = _ctx()
    assert ExactTextEvaluator("hello").evaluate(ctx).passed is True
    assert ContainsTextEvaluator("ell").evaluate(ctx).passed is True
    assert RegexEvaluator("h.l+o").evaluate(ctx).passed is True
    assert ContainsTextEvaluator("nope").evaluate(ctx).passed is False


def test_json_field_evaluator() -> None:
    ctx = _ctx(
        target=TargetResult(
            status=RunStatus.SUCCESS,
            structured_output={"nested": {"flag": True}},
            exit_code=0,
        )
    )
    assert JsonFieldEvaluator("nested.flag", True).evaluate(ctx).passed is True
    assert JsonFieldEvaluator("nested.flag", False).evaluate(ctx).passed is False


def test_tests_passed_unknown_when_missing() -> None:
    result = TestsPassedEvaluator().evaluate(_ctx())
    assert result.passed is None
    assert result.error


def test_file_change_evaluator() -> None:
    diff = WorkspaceDiff(files_created=1, files_modified=0, files_deleted=0)
    result = FileChangeEvaluator(min_created=1).evaluate(_ctx(workspace_diff=diff))
    assert result.passed is True


def test_validation_command_can_fail_when_target_succeeded(tmp_path: Path) -> None:
    target = TargetResult(status=RunStatus.SUCCESS, exit_code=0)
    ev = ValidationCommandEvaluator([sys.executable, "-c", "raise SystemExit(2)"])
    result = ev.evaluate({"target": target, "cwd": str(tmp_path)})
    assert result.passed is False
    assert result.details["exit_code"] == 2


def test_no_eval_from_config() -> None:
    with pytest.raises(ValidationError):
        evaluator_from_config({"type": "eval", "code": "1/0"})
    with pytest.raises(ValidationError):
        ValidationCommandEvaluator("echo hi")
