"""Round-3 Codex findings: null gates, lossless keys, closed schemas, report containment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from agentbench.cli import main
from agentbench.errors import (
    ConfigurationError,
    CorruptResultError,
    ValidationError,
)
from agentbench.jsonutil import to_jsonable
from agentbench.models import (
    BenchmarkCase,
    RunStatus,
    TargetResult,
    Telemetry,
)
from agentbench.persistence import ResultStore, run_result_from_dict
from agentbench.regression import RegressionPolicy


def _base_suite(**extra) -> dict:
    data = {
        "id": "s",
        "cases": [{"id": "c", "name": "C"}],
        "variants": [{"id": "v", "name": "V"}],
        "target": {"type": "command", "argv": [sys.executable, "-c", "print(0)"]},
    }
    data.update(extra)
    return data


def _write_suite(path: Path, **extra) -> Path:
    path.write_text(json.dumps(_base_suite(**extra)), encoding="utf-8")
    return path


def test_hard_gate_omitted_defaults_false() -> None:
    policy = RegressionPolicy.from_config(
        {
            "baseline": "v",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.1,
                }
            ],
        }
    )
    assert policy.rules[0].hard_gate is False


@pytest.mark.parametrize("value", [True, False])
def test_hard_gate_bool_accepted(value: bool) -> None:
    policy = RegressionPolicy.from_config(
        {
            "baseline": "v",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.1,
                    "hard_gate": value,
                }
            ],
        }
    )
    assert policy.rules[0].hard_gate is value


@pytest.mark.parametrize("bad", [None, "false", 0, 1, [], {}])
def test_hard_gate_invalid_rejected(bad) -> None:
    with pytest.raises((ConfigurationError, ValidationError)):
        RegressionPolicy.from_config(
            {
                "baseline": "v",
                "rules": [
                    {
                        "metric": "success",
                        "direction": "HIGHER_IS_BETTER",
                        "absolute_threshold": 0.1,
                        "hard_gate": bad,
                    }
                ],
            }
        )


def test_validate_and_run_reject_hard_gate_null(tmp_path: Path) -> None:
    suite = _write_suite(
        tmp_path / "suite.json",
        regression={
            "baseline": "v",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.1,
                    "hard_gate": None,
                }
            ],
        },
    )
    assert main(["validate", str(suite)]) != 0
    assert main(["run", str(suite), "-o", str(tmp_path / "out")]) != 0


def test_to_jsonable_rejects_non_string_keys() -> None:
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({1: "a"})
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({True: "a"})
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({None: "a"})
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({(1, 2): "a"})
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({"outer": {1: "nested"}})
    with pytest.raises(ValidationError, match="strings"):
        to_jsonable({1: "a", "1": "b"})
    assert to_jsonable({"ok": {"inner": [1, None, False]}}) == {"ok": {"inner": [1, None, False]}}


def test_case_payload_rejects_int_keys() -> None:
    with pytest.raises(ValidationError, match="strings"):
        BenchmarkCase(id="c", name="C", payload={1: "a", "1": "b"})


def test_unknown_target_and_evaluator_fields_rejected(tmp_path: Path) -> None:
    suite = _write_suite(
        tmp_path / "t.json",
        target={"type": "command", "argv": [sys.executable, "-c", "pass"], "shell": True},
    )
    assert main(["validate", str(suite)]) != 0
    suite2 = _write_suite(
        tmp_path / "e.json",
        evaluators=[{"type": "exit_code", "expected": 0, "unexpected": 1}],
    )
    assert main(["validate", str(suite2)]) != 0


def test_falsey_config_does_not_become_default(tmp_path: Path) -> None:
    suite = _write_suite(tmp_path / "b.json", budget=[])
    assert main(["validate", str(suite)]) != 0
    suite2 = _write_suite(tmp_path / "m.json")
    raw = json.loads(suite2.read_text(encoding="utf-8"))
    raw["variants"][0]["config"] = []
    suite2.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["validate", str(suite2)]) != 0


@pytest.mark.parametrize("bad", [0, 1, None, "false", 0.0, [], {}])
def test_target_result_bools_strict(bad) -> None:
    with pytest.raises(ValidationError):
        TargetResult(status=RunStatus.SUCCESS, timed_out=bad)  # type: ignore[arg-type]


def test_target_result_round_trip(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    from agentbench.models import RunResult

    result = RunResult(
        run_id="s__c__v__r0__s0",
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=0,
        target=TargetResult(
            status=RunStatus.SUCCESS,
            timed_out=False,
            infrastructure_error=False,
            telemetry=Telemetry(cost=0.1),
        ),
    )
    store.write_run(result)
    loaded = store.load_run(result.run_id)
    assert loaded.target.timed_out is False
    assert loaded.target.telemetry.cost == 0.1


def test_persist_does_not_rewrite_falsey_workspace_counts() -> None:
    with pytest.raises(CorruptResultError):
        run_result_from_dict(
            {
                "schema_version": 1,
                "run_id": "s__c__v__r0__s0",
                "case_id": "c",
                "variant_id": "v",
                "repetition": 0,
                "seed": 0,
                "target": {"status": "SUCCESS"},
                "workspace_diff": {"files_created": False},
            }
        )
    with pytest.raises(CorruptResultError):
        run_result_from_dict(
            {
                "schema_version": 1,
                "run_id": "s__c__v__r0__s0",
                "case_id": "c",
                "variant_id": "v",
                "repetition": 0,
                "seed": 0,
                "target": {"status": "SUCCESS"},
                "evaluations": [{"evaluator": "x", "passed": True, "details": []}],
            }
        )


def test_report_refuses_linked_escape(tmp_path: Path) -> None:
    store_dir = tmp_path / "results"
    store = ResultStore(store_dir)
    store.write_json("summary.json", {"schema_version": 1})
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "stolen.md"
    sentinel.write_text("KEEP", encoding="utf-8")
    link = store_dir / "report.md"
    if os.name == "nt":
        import subprocess

        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            # File symlink may need admin; a directory junction on report.md
            # name still redirects writes if the CLI followed it.
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/H", str(link), str(sentinel)],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.fail(f"Windows link required: {completed.stderr!r}")
    else:
        os.symlink(sentinel, link)
    before = sentinel.read_text(encoding="utf-8")
    code = main(["report", str(store_dir), "--output", str(link)])
    assert code != 0
    assert sentinel.read_text(encoding="utf-8") == before
    assert list(outside.glob("*")) == [sentinel] or sentinel.exists()
