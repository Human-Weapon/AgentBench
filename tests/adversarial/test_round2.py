"""Round-2 Codex findings: payload JSON, strict config, pairing, money, caps."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from agentbench.cli import main
from agentbench.comparison import paired_comparison
from agentbench.errors import (
    ConfigurationError,
    CorruptResultError,
    PathEscapeError,
    TargetExecutionError,
    ValidationError,
)
from agentbench.jsonutil import to_jsonable
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
from agentbench.persistence import ResultStore
from agentbench.regression import RegressionPolicy
from agentbench.runner import ExperimentRunner, ExperimentSpec
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


def test_ab2001_command_stdin_preserves_nested_structure(scripts: Path) -> None:
    payload = {"outer": {"items": [1, 2, {"x": 3}], "ok": True, "missing": None}}
    case = BenchmarkCase(id="c", name="C", payload=payload, expected={"answer": 8})
    variant = Variant(id="v", name="V", config={"mode": "fast", "flags": ["a"]})
    target = CommandTarget([sys.executable, str(scripts / "echo_stdin.py")])
    result = target.run(case, variant, {"run_id": "r", "seed": 1, "repetition": 0})
    body = json.loads(result.stdout)
    assert body["case"]["payload"] == payload
    assert body["case"]["expected"] == {"answer": 8}
    assert body["variant"]["config"]["flags"] == ["a"]
    assert "mappingproxy" not in result.stdout


def test_ab2001_to_jsonable_rejects_objects() -> None:
    with pytest.raises(ValidationError, match="JSON-native"):
        to_jsonable(object(), name="payload")


def test_ab2001_shipped_example_profile(tmp_path: Path) -> None:
    suite = Path(__file__).resolve().parents[2] / "examples" / "suite.json"
    out = tmp_path / "ex"
    assert main(["run", str(suite), "-o", str(out), "--json"]) == 0
    runs = list((out / "runs").glob("*.json"))
    assert len(runs) == 8
    statuses = []
    for path in runs:
        data = json.loads(path.read_text(encoding="utf-8"))
        statuses.append(data["target"]["status"])
    assert statuses.count("SUCCESS") == 6
    assert statuses.count("FAILURE") == 2
    assert statuses.count("ERROR") == 0


def test_ab2002_string_hard_gate_rejected() -> None:
    with pytest.raises((ConfigurationError, ValidationError)):
        RegressionPolicy.from_config(
            {
                "baseline": "a",
                "rules": [
                    {
                        "metric": "success",
                        "direction": "HIGHER_IS_BETTER",
                        "absolute_threshold": 0.1,
                        "hard_gate": "false",
                    }
                ],
            }
        )


def test_ab2002_validate_rejects_string_hard_gate(tmp_path: Path, capsys) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "id": "s",
                "cases": [{"id": "c", "name": "C"}],
                "variants": [{"id": "v", "name": "V"}],
                "target": {"type": "command", "argv": [sys.executable, "-c", "pass"]},
                "regression": {
                    "baseline": "v",
                    "rules": [
                        {
                            "metric": "success",
                            "direction": "HIGHER_IS_BETTER",
                            "absolute_threshold": 0.1,
                            "hard_gate": "false",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", str(suite)]) != 0
    assert "Traceback" not in capsys.readouterr().err


def test_ab2002_validate_rejects_bad_pricing(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "id": "s",
                "cases": [{"id": "c", "name": "C"}],
                "variants": [{"id": "v", "name": "V"}],
                "target": {"type": "command", "argv": [sys.executable, "-c", "pass"]},
                "pricing": {"input_token_rate": "x", "output_token_rate": 1},
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", str(suite)]) != 0


def test_ab2002_unknown_regression_field_rejected() -> None:
    with pytest.raises(ConfigurationError, match="unknown"):
        RegressionPolicy.from_config(
            {
                "baseline": "a",
                "hardgate": True,
                "rules": [
                    {
                        "metric": "success",
                        "direction": "HIGHER_IS_BETTER",
                        "absolute_threshold": 0.1,
                    }
                ],
            }
        )


def test_ab2003_output_root_replacement_writes_nothing_outside(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = ResultStore(trusted)
    before = list(outside.rglob("*"))
    # Replace trusted directory with a link to outside.
    import shutil

    shutil.rmtree(trusted)
    try:
        if os.name == "nt":
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(trusted), str(outside)],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.fail(f"Windows junction required: {completed.stderr!r}")
        else:
            os.symlink(outside, trusted, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"platform link required: {exc}")
    with pytest.raises(PathEscapeError):
        store.write_json("experiment.json", {"ok": True})
    after = list(outside.rglob("*"))
    assert after == before


def test_ab007_nested_schema_rejects_malformed(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    base = {
        "schema_version": 1,
        "run_id": "s__c__v__r0__s0",
        "case_id": "c",
        "variant_id": "v",
        "repetition": 0,
        "seed": 0,
        "target": {"status": "SUCCESS", "telemetry": {}},
    }
    bad_targets = (
        {"status": "SUCCESS", "telemetry": []},
        {"status": "SUCCESS", "telemetry": ""},
        {"status": "SUCCESS", "telemetry": 1},
        {"status": "SUCCESS", "telemetry": True},
        {"status": "SUCCESS", "telemetry": {"cost": []}},
        {"status": "SUCCESS", "telemetry": {"cost": "unknown"}},
        {"status": "SUCCESS", "telemetry": {}, "artifacts": []},
    )
    for i, target in enumerate(bad_targets):
        ident = f"s__c__v__r{i}__s0"
        payload = dict(base, run_id=ident, target=target)
        path = store.root / "runs" / f"{ident}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(CorruptResultError):
            store.load_run(ident)


def test_ab011_none_is_not_success() -> None:
    def fn(case, variant, context):
        return None

    with pytest.raises(TargetExecutionError, match="None"):
        PythonCallableTarget(fn).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})


@pytest.mark.parametrize("bad", ["", 1, [], (), object()])
def test_ab011_invalid_callable_returns(bad) -> None:
    def fn(case, variant, context):
        return bad

    with pytest.raises(TargetExecutionError):
        PythonCallableTarget(fn).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})


def _run(variant: str, case: str, rep: int, seed: int, success: bool) -> RunResult:
    return RunResult(
        run_id=f"s__{case}__{variant}__r{rep}__s{seed}",
        case_id=case,
        variant_id=variant,
        repetition=rep,
        seed=seed,
        target=TargetResult(
            status=RunStatus.SUCCESS if success else RunStatus.FAILURE,
            telemetry=Telemetry(cost=1.0),
        ),
    )


def test_ab2004_different_seed_not_paired() -> None:
    paired = paired_comparison(
        [_run("base", "c", 0, 1, True)],
        [_run("cand", "c", 0, 2, True)],
        "success",
        direction=MetricDirection.HIGHER_IS_BETTER,
    )
    assert paired["paired_n"] == 0


def test_ab2004_same_seed_paired() -> None:
    paired = paired_comparison(
        [_run("base", "c", 0, 1, True)],
        [_run("cand", "c", 0, 1, False)],
        "success",
        direction=MetricDirection.HIGHER_IS_BETTER,
    )
    assert paired["paired_n"] == 1


def test_ab2004_duplicate_pair_key_rejected() -> None:
    with pytest.raises(ValidationError, match="ambiguous"):
        paired_comparison(
            [_run("base", "c", 0, 1, True), _run("base", "c", 0, 1, False)],
            [_run("cand", "c", 0, 1, True)],
            "success",
            direction=MetricDirection.HIGHER_IS_BETTER,
        )


def test_ab2005_three_tenths_do_not_exhaust(tmp_path: Path) -> None:
    invoked = []

    def fn(case, variant, context):
        invoked.append(variant.id)
        return {"telemetry": {"cost": 0.1}}

    suite = _suite(
        variants=tuple(Variant(id=f"v{i}", name=f"V{i}") for i in range(3)),
        budget=ExecutionBudget(max_total_cost=0.3, per_run_max_cost=0.1),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "out",
        )
    )
    assert invoked == ["v0", "v1", "v2"]
    assert outcome.executed_runs == 3
    assert outcome.cost_bound_violated is False


def test_ab2007_exact_cap_not_truncated(tmp_path: Path) -> None:
    script = tmp_path / "emit_exact.py"
    script.write_text(
        "import sys\nn = int(sys.argv[1])\nsys.stdout.buffer.write(b'X' * n)\n",
        encoding="utf-8",
    )
    target = CommandTarget(
        [sys.executable, str(script), "64"],
        max_stdout_bytes=64,
        timeout_seconds=10,
        stdin_payload=False,
    )
    result = target.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert result.artifacts["stdout_truncated"] is False
    assert len(result.stdout.encode("utf-8")) == 64
    target2 = CommandTarget(
        [sys.executable, str(script), "65"],
        max_stdout_bytes=64,
        timeout_seconds=10,
        stdin_payload=False,
    )
    over = target2.run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert over.artifacts["stdout_truncated"] is True


def test_ab2007_stderr_exact_cap(tmp_path: Path) -> None:
    script = tmp_path / "emit_err.py"
    script.write_text(
        "import sys\nn = int(sys.argv[1])\nsys.stderr.buffer.write(b'Y' * n)\n",
        encoding="utf-8",
    )
    exact = CommandTarget(
        [sys.executable, str(script), "32"],
        max_stderr_bytes=32,
        timeout_seconds=10,
        stdin_payload=False,
    ).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert exact.artifacts["stderr_truncated"] is False
    over = CommandTarget(
        [sys.executable, str(script), "33"],
        max_stderr_bytes=32,
        timeout_seconds=10,
        stdin_payload=False,
    ).run(BenchmarkCase(id="c", name="C"), Variant(id="v", name="V"), {})
    assert over.artifacts["stderr_truncated"] is True
