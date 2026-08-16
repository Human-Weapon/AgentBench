from __future__ import annotations

from pathlib import Path

from agentbench.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_example_suite_validate_run_compare_report(tmp_path: Path) -> None:
    suite = EXAMPLES / "suite.json"
    out = tmp_path / "results"
    assert main(["validate", str(suite)]) == 0
    assert main(["run", str(suite), "--output", str(out), "--json"]) == 0
    assert (out / "summary.json").is_file()
    assert (out / "report.md").is_file()
    assert (out / "runs").is_dir()
    assert list((out / "runs").glob("*.json"))
    assert main(["compare", str(out), "--baseline", "fast-cheap"]) == 0
    assert main(["report", str(out), "--output", str(out / "report2.md")]) == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "objectively better" not in report.lower()
    seed = EXAMPLES / "workspace" / "seed.txt"
    assert "template must stay put" in seed.read_text(encoding="utf-8")
