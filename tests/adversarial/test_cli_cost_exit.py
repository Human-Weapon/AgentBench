"""CLI must not return 0 when the cost-bound guarantee is breached."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agentbench.cli import main
from agentbench.errors import CostBoundViolationError


def _suite(path: Path, *, cost: str, hard_gate: bool = False) -> Path:
    script = Path(__file__).resolve().parents[1] / "fixtures" / "scripts" / "emit_cost.py"
    payload = {
        "id": "cli-cost",
        "name": "CLI cost bound",
        "seed": 1,
        "repetitions": 1,
        "baseline": "a",
        "budget": {
            "max_total_cost": 1.0,
            "per_run_max_cost": 0.4,
            "per_run_timeout_seconds": 10,
        },
        "cases": [{"id": "c", "name": "C", "payload": {"n": 1}}],
        "variants": [
            {"id": "a", "name": "A", "config": {"mode": "a"}},
            {"id": "b", "name": "B", "config": {"mode": "b"}},
        ],
        "target": {
            "type": "command",
            "argv": [sys.executable, str(script), cost],
        },
        "metrics": [
            {"name": "success", "direction": "HIGHER_IS_BETTER", "minimum": 0, "maximum": 1}
        ],
        "regression": {
            "baseline": "a",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.0,
                    "hard_gate": hard_gate,
                    "min_sample_size": 1,
                }
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_json_bound_violation_exits_6(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path / "suite.json", cost="0.8")
    out = tmp_path / "out"
    code = main(["run", str(suite), "-o", str(out), "--json"])
    captured = capsys.readouterr()
    assert captured.err == "" or "Traceback" not in captured.err
    payload = json.loads(captured.out)
    assert code == CostBoundViolationError.exit_code == 6
    assert payload["cost_bound_violated"] is True
    assert payload["budget_guarantee_breached"] is True
    assert payload["committed_cost"] == 0.8
    assert payload["runs"] == 1
    stored = json.loads((out / "experiment.json").read_text(encoding="utf-8"))
    assert stored["committed_cost"] == 0.8
    assert stored["cost_bound_violated"] is True
    assert stored["executed_runs"] == 1
    assert stored["not_scheduled"] == 1


def test_cli_human_bound_violation_exits_6(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path / "suite.json", cost="0.8")
    code = main(["run", str(suite), "-o", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == 6
    assert "Traceback" not in captured.err
    assert "ran 1 runs" in captured.out
    assert "cost bound" in captured.out.lower()


def test_cli_exact_bound_exits_0(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path / "suite.json", cost="0.4")
    # One variant only so second reservation is not attempted after exact spend.
    raw = json.loads(suite.read_text(encoding="utf-8"))
    raw["variants"] = [raw["variants"][0]]
    suite.write_text(json.dumps(raw), encoding="utf-8")
    code = main(["run", str(suite), "-o", str(tmp_path / "out"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["cost_bound_violated"] is False
    assert payload["committed_cost"] == 0.4


def test_cli_unknown_cost_is_not_violation(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path / "suite.json", cost="unknown")
    code = main(["run", str(suite), "-o", str(tmp_path / "out"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["cost_bound_violated"] is False
    assert payload["budget_guarantee_breached"] is False
    assert code == 0


def test_cli_hard_gate_exits_5(tmp_path: Path, capsys) -> None:
    script = tmp_path / "gate.py"
    script.write_text(
        "import json, os, sys\n"
        "if os.environ.get('AGENTBENCH_VARIANT_ID') == 'b':\n"
        "    raise SystemExit(1)\n"
        "print(json.dumps({'telemetry': {'cost': 0.1}}))\n",
        encoding="utf-8",
    )
    payload = {
        "id": "gate",
        "name": "gate",
        "seed": 1,
        "repetitions": 1,
        "baseline": "a",
        "cases": [{"id": "c", "name": "C"}],
        "variants": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "target": {"type": "command", "argv": [sys.executable, str(script)]},
        "metrics": [
            {"name": "success", "direction": "HIGHER_IS_BETTER", "minimum": 0, "maximum": 1}
        ],
        "regression": {
            "baseline": "a",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.0,
                    "hard_gate": True,
                    "min_sample_size": 1,
                }
            ],
        },
    }
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["run", str(suite), "-o", str(tmp_path / "out"), "--json"])
    assert code == 5
    assert json.loads(capsys.readouterr().out)["hard_gate_passed"] is False


def test_cli_cost_bound_precedes_hard_gate(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path / "suite.json", cost="0.8", hard_gate=True)
    code = main(["run", str(suite), "-o", str(tmp_path / "out"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["budget_guarantee_breached"] is True
    assert code == 6
