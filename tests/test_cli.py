from __future__ import annotations

import json
from pathlib import Path

from agentbench.cli import main
from agentbench.models import BenchmarkCase, BenchmarkSuite, ExecutionBudget, Variant
from agentbench.runner import ExperimentRunner, ExperimentSpec
from agentbench.siblings import detect_integrations
from agentbench.targets import PythonCallableTarget


def _write_suite(path: Path) -> Path:
    suite = {
        "id": "cli-suite",
        "name": "CLI suite",
        "seed": 1,
        "repetitions": 1,
        "baseline": "fast",
        "budget": {"per_run_timeout_seconds": 10, "max_runs": 4},
        "cases": [{"id": "add", "name": "add", "payload": {"n": 2}}],
        "variants": [
            {"id": "fast", "name": "fast", "config": {"mode": "fast"}},
            {"id": "slow", "name": "slow", "config": {"mode": "slow"}},
        ],
        "target": {"type": "command", "script": "does-not-matter.py"},
        "evaluators": [{"type": "exit_code", "expected": 0}],
    }
    path.write_text(json.dumps(suite), encoding="utf-8")
    return path


def test_help_exits_zero() -> None:
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_validate_ok_and_bad(tmp_path: Path, capsys) -> None:
    suite = _write_suite(tmp_path / "suite.json")
    # target script missing is ok for validate of suite structure? load_target will succeed
    # creating CommandTarget with argv from missing script path - that's fine, it doesn't run.
    assert main(["validate", str(suite)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_cli_bad_config_no_traceback(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "suite.json"
    bad.write_text(json.dumps({"id": "x", "cases": [], "variants": []}), encoding="utf-8")
    code = main(["validate", str(bad)])
    assert code != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_cli_debug_can_show_traceback(tmp_path: Path) -> None:
    # debug is only for unexpected errors; domain errors still print message
    bad = tmp_path / "suite.json"
    bad.write_text("{", encoding="utf-8")
    assert main(["--debug", "validate", str(bad)]) == 1


def test_report_and_compare_from_persisted(tmp_path: Path, capsys) -> None:
    def fn(case, variant, context):
        cost = 0.1 if variant.id == "fast" else 0.5
        success = variant.id != "fast" or case.payload.get("n", 0) < 10
        if not success:
            raise RuntimeError("wrong")
        return {"telemetry": {"cost": cost, "latency_seconds": cost}}

    suite = BenchmarkSuite(
        id="rep",
        name="rep",
        cases=(BenchmarkCase(id="c", name="C", payload={"n": 1}),),
        variants=(Variant(id="fast", name="fast"), Variant(id="slow", name="slow")),
        baseline_variant_id="fast",
        budget=ExecutionBudget(per_run_timeout_seconds=5),
    )
    out = tmp_path / "results"
    ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=out)
    )
    assert main(["compare", str(out), "--baseline", "fast", "--json"]) == 0
    assert main(["report", str(out)]) == 0
    if (out / "report.md").exists():
        text = (out / "report.md").read_text(encoding="utf-8")
    else:
        text = capsys.readouterr().out
    assert "objectively better" not in text.lower()
    assert "Baseline" in text or "baseline" in text.lower()


def test_status_standalone() -> None:
    assert main(["status", "--json"]) == 0
    flags = detect_integrations()
    assert set(flags) == {"promptgraph", "agentgear", "skillguard", "projectkaizen"}


def test_cli_run_survives_cp1252_stdout(tmp_path: Path, monkeypatch) -> None:
    """Windows CI: default console is cp1252 and cannot encode U+2192."""
    import io
    import sys

    from agentbench.cli import _emit

    class _Cp1252:
        encoding = "cp1252"

        def __init__(self) -> None:
            self.buffer = io.BytesIO()

        def write(self, text: str) -> int:
            self.buffer.write(text.encode("cp1252", errors="strict"))
            return len(text)

        def flush(self) -> None:
            pass

    _emit("ok")  # smoke the helper
    sink = _Cp1252()
    monkeypatch.setattr(sys, "stdout", sink)
    _emit("arrow → and delta Δ")
    decoded = sink.buffer.getvalue().decode("cp1252")
    assert "arrow" in decoded
    assert "delta" in decoded

    suite = {
        "id": "enc",
        "cases": [{"id": "c", "name": "c"}],
        "variants": [{"id": "v", "name": "v"}],
        "target": {"type": "command", "argv": [sys.executable, "-c", "print(0)"]},
        "budget": {"per_run_timeout_seconds": 10},
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    sink = _Cp1252()
    monkeypatch.setattr(sys, "stdout", sink)
    assert main(["run", str(path), "-o", str(tmp_path / "out")]) == 0
    text = sink.buffer.getvalue().decode("cp1252")
    assert "runs ->" in text
    assert "\u2192" not in text
