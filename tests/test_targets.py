from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentbench.errors import ValidationError
from agentbench.models import BenchmarkCase, RunStatus, Variant
from agentbench.targets import CommandTarget, PythonCallableTarget


def test_command_target_rejects_shell_string() -> None:
    with pytest.raises(ValidationError, match="list"):
        CommandTarget("echo hello")


def test_success_target(scripts: Path) -> None:
    target = CommandTarget([sys.executable, str(scripts / "succeed.py")])
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.SUCCESS
    assert result.exit_code == 0
    assert result.telemetry.cost == 0.01
    assert result.structured_output["ok"] is True
    assert result.timed_out is False
    assert result.infrastructure_error is False


def test_failing_target_is_data_not_infrastructure(scripts: Path) -> None:
    target = CommandTarget([sys.executable, str(scripts / "fail.py")])
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.FAILURE
    assert result.exit_code == 1
    assert "target-failed" in result.stderr
    assert result.infrastructure_error is False


def test_timeout_is_explicit_and_does_not_hang(scripts: Path) -> None:
    target = CommandTarget(
        [sys.executable, str(scripts / "sleep.py"), "30"],
        timeout_seconds=0.3,
    )
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.TIMEOUT
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.infrastructure_error is False
    assert result.duration_seconds < 10


def test_streams_captured(scripts: Path) -> None:
    target = CommandTarget([sys.executable, str(scripts / "write_streams.py")])
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert "STDOUT-MARKER" in result.stdout
    assert "STDERR-MARKER" in result.stderr


def test_invalid_json_does_not_crash(scripts: Path) -> None:
    target = CommandTarget([sys.executable, str(scripts / "emit_json.py")])
    good = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert good.structured_output["value"] == 42
    bad = CommandTarget([sys.executable, str(scripts / "invalid_json.py")])
    result = bad.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.status is RunStatus.SUCCESS
    assert result.structured_output is None


def test_callable_target_failure_is_not_infrastructure() -> None:
    def boom(case, variant, context):
        raise RuntimeError("nope")

    result = PythonCallableTarget(boom).run(
        BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {}
    )
    assert result.status is RunStatus.FAILURE
    assert result.infrastructure_error is False


def test_callable_missing_telemetry_stays_unknown() -> None:
    def ok(case, variant, context):
        return {"hello": "world"}

    result = PythonCallableTarget(ok).run(
        BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {}
    )
    assert result.status is RunStatus.SUCCESS
    assert result.telemetry.cost is None
    assert result.telemetry.input_tokens is None
