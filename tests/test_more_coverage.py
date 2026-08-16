from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.adapters import AgentGearEvidenceAdapter
from agentbench.cli import main
from agentbench.config import load_evaluators, load_policy, load_pricing, load_suite, load_target
from agentbench.errors import ConfigurationError, ValidationError
from agentbench.fingerprint import collect_fingerprint
from agentbench.metrics import composite_score, normalize
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    MetricDefinition,
    MetricDirection,
    MissingMetricBehavior,
    PricingConfig,
    Variant,
)
from agentbench.persistence import ResultStore
from agentbench.report import generate_report
from agentbench.runner import ExperimentRunner, ExperimentSpec
from agentbench.siblings import sibling_versions
from agentbench.targets import PythonCallableTarget, default_python_argv


def test_cli_run_example_and_report_branches(tmp_path: Path) -> None:
    suite = Path(__file__).resolve().parents[1] / "examples" / "suite.json"
    out = tmp_path / "out"
    assert main(["--json", "validate", str(suite)]) == 0
    assert main(["run", str(suite), "-o", str(out)]) == 0
    assert main(["status"]) == 0
    assert (out / "report.md").is_file()
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "AgentBench report" in text
    assert "unknown" in text or "cost" in text


def test_generate_report_direct(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return {"telemetry": {"cost": 0.2 if variant.id == "a" else 0.9, "latency_seconds": 0.1}}

    suite = BenchmarkSuite(
        id="rep",
        name="rep",
        cases=(BenchmarkCase(id="c", name="C"),),
        variants=(Variant(id="a", name="A"), Variant(id="b", name="B")),
        baseline_variant_id="a",
        repetitions=2,
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path)
    )
    md = generate_report(outcome, extra={"note": "ok"})
    assert "Variant" in md or "variants" in md.lower()
    assert "frontier" in md.lower()
    assert "ok" in md


def test_load_target_and_policy(tmp_path: Path) -> None:
    raw = {
        "id": "s",
        "cases": [{"id": "c", "name": "c"}],
        "variants": [{"id": "v", "name": "v"}],
        "target": {"type": "command", "script": "targets/fast_cheap.py"},
        "evaluators": [
            {"type": "exit_code", "expected": 0},
            {"type": "contains_text", "needle": "x"},
            {"type": "regex", "pattern": "x"},
            {"type": "exact_text", "expected": "x"},
            {"type": "json_field", "field": "a", "expected": 1},
            {"type": "file_change", "min_created": 0},
            {"type": "tests_passed"},
            {"type": "target_status", "expected": "SUCCESS"},
        ],
        "regression": {
            "baseline": "v",
            "rules": [
                {
                    "metric": "success",
                    "direction": "HIGHER_IS_BETTER",
                    "absolute_threshold": 0.1,
                }
            ],
        },
        "pricing": {"input_token_rate": 0.001, "output_token_rate": 0.002},
    }
    path = tmp_path / "s.json"
    payload = {**raw, "target": {"type": "command", "argv": ["python", "-c", "pass"]}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    suite = load_suite(path)
    assert suite.id == "s"
    target = load_target(
        {"target": {"type": "command", "argv": ["python", "-c", "pass"]}},
        base_dir=tmp_path,
    )
    assert target.describe()["shell"] is False
    assert load_evaluators(raw)
    assert load_policy(raw) is not None
    assert load_pricing(raw) is not None
    with pytest.raises(ConfigurationError):
        load_target({"target": {"type": "python_callable"}})
    with pytest.raises(ConfigurationError):
        load_target({"target": {"type": "mystery"}})
    with pytest.raises(ConfigurationError):
        load_target({})


def test_default_python_argv() -> None:
    argv = default_python_argv("script.py")
    assert argv[-1] == "script.py"
    with pytest.raises(ValidationError):
        default_python_argv("")


def test_store_write_text_and_json(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    store.write_text("hello.md", "# hi\n")
    store.write_json("meta.json", {"ok": True})
    assert (tmp_path / "out" / "hello.md").read_text(encoding="utf-8") == "# hi\n"
    with pytest.raises(ValidationError):
        store.write_text("../x.md", "no")


def test_adapter_none_and_non_mapping() -> None:
    adapter = AgentGearEvidenceAdapter()
    assert adapter.to_telemetry(None).cost is None
    assert adapter.to_telemetry("nope").cost is None  # type: ignore[arg-type]


def test_sibling_versions() -> None:
    versions = sibling_versions()
    assert "promptgraph" in versions


def test_fingerprint_git_present() -> None:
    fp = collect_fingerprint(seed=0, cwd=".")
    assert fp.os_name


def test_normalize_and_composite_fail() -> None:
    definition = MetricDefinition(
        name="x",
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=10,
        weight=1,
    )
    assert normalize(10, definition) == 1.0
    assert normalize(-1, definition) == 0.0
    low = MetricDefinition(
        name="lat",
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
        maximum=10,
        weight=1,
    )
    assert normalize(0, low) == 1.0
    with pytest.raises(ValidationError):
        composite_score({"x": 1}, (), missing=MissingMetricBehavior.SKIP)
    with pytest.raises(ValidationError):
        composite_score({"x": None}, (definition,), missing=MissingMetricBehavior.FAIL)


def test_case_level_workspace(tmp_path: Path) -> None:
    template = tmp_path / "tpl"
    template.mkdir()
    (template / "seed.txt").write_text("s", encoding="utf-8")

    def fn(case, variant, context):
        Path(context["cwd"], "new.txt").write_text("n", encoding="utf-8")
        return {"ok": True}

    suite = BenchmarkSuite(
        id="ws",
        name="ws",
        cases=(BenchmarkCase(id="c", name="C", workspace_template=str(template)),),
        variants=(Variant(id="v", name="V"),),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(suite=suite, target=PythonCallableTarget(fn), output_root=tmp_path / "o")
    )
    assert outcome.runs[0].workspace_diff is not None
    assert outcome.runs[0].workspace_diff.files_created >= 1
    assert (template / "seed.txt").read_text(encoding="utf-8") == "s"


def test_pricing_applied_when_tokens_known(tmp_path: Path) -> None:
    def fn(case, variant, context):
        return {"telemetry": {"input_tokens": 10, "output_tokens": 10}}

    suite = BenchmarkSuite(
        id="p",
        name="p",
        cases=(BenchmarkCase(id="c", name="C"),),
        variants=(Variant(id="v", name="V"),),
    )
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=PythonCallableTarget(fn),
            output_root=tmp_path / "o",
            pricing=PricingConfig(input_token_rate=0.1, output_token_rate=0.2),
        )
    )
    assert outcome.runs[0].target.telemetry.cost == pytest.approx(3.0)
