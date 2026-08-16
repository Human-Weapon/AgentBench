"""AgentBench CLI. Domain errors print concise stderr and a stable exit code."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from ._version import __version__
from .comparison import compare
from .config import _load_raw, load_evaluators, load_policy, load_pricing, load_suite, load_target
from .errors import AgentBenchError, ConfigurationError
from .persistence import ResultStore, load_json_object
from .report import generate_report
from .runner import ExperimentRunner, ExperimentSpec
from .siblings import detect_integrations, sibling_versions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentbench",
        description=(
            "Objective benchmarking and regression evaluation for AI agents, "
            "prompts, skills, models, and execution strategies."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="print tracebacks")
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="machine-readable output"
    )
    sub = parser.add_subparsers(dest="command")

    def _common(subparser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        subparser.add_argument(
            "--json", action="store_true", dest="as_json", help="machine-readable output"
        )
        subparser.add_argument("--debug", action="store_true", help="print tracebacks")
        return subparser

    p_val = _common(sub.add_parser("validate", help="Validate a suite configuration."))
    p_val.add_argument("suite")

    p_run = _common(sub.add_parser("run", help="Run a benchmark suite."))
    p_run.add_argument("suite")
    p_run.add_argument("--output", "-o", default=".agentbench-out")

    p_cmp = _common(sub.add_parser("compare", help="Compare persisted results."))
    p_cmp.add_argument("results")
    p_cmp.add_argument("--baseline")

    p_rep = _common(
        sub.add_parser("report", help="Write a markdown report from persisted results.")
    )
    p_rep.add_argument("results")
    p_rep.add_argument("--output", "-o")

    _common(sub.add_parser("status", help="Show standalone / sibling integration status."))
    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    raw = _load_raw(args.suite)
    suite = load_suite(args.suite)
    load_evaluators(raw)
    load_target(raw, base_dir=Path(args.suite).parent)
    payload = {
        "ok": True,
        "suite_id": suite.id,
        "cases": [c.id for c in suite.cases],
        "variants": [v.id for v in suite.variants],
        "repetitions": suite.repetitions,
        "planned_runs": suite.planned_runs(),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"ok: suite {suite.id} "
            f"({len(suite.cases)} cases × {len(suite.variants)} variants × "
            f"{suite.repetitions} reps = {suite.planned_runs()} runs)"
        )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    raw = _load_raw(args.suite)
    suite = load_suite(args.suite)
    target = load_target(raw, base_dir=Path(args.suite).parent)
    evaluators = load_evaluators(raw)
    policy = load_policy(raw)
    pricing = load_pricing(raw)
    workspace = raw.get("workspace_template") or suite.workspace_template
    if workspace and not Path(workspace).is_absolute():
        workspace = str((Path(args.suite).parent / workspace).resolve())
    outcome = ExperimentRunner().run(
        ExperimentSpec(
            suite=suite,
            target=target,
            evaluators=evaluators,
            output_root=args.output,
            policy=policy,
            pricing=pricing,
            workspace_template=workspace,
        )
    )
    store = ResultStore(args.output)
    report = generate_report(outcome)
    store.write_text("report.md", report)
    payload = {
        "suite_id": outcome.suite_id,
        "runs": len(outcome.runs),
        "output": str(store.root),
        "budget_exhausted": outcome.budget_exhausted,
        "stopped_reason": outcome.stopped_reason,
        "hard_gate_passed": None
        if outcome.comparison is None
        else outcome.comparison.get("hard_gate_passed"),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"ran {payload['runs']} runs → {payload['output']}")
        if outcome.stopped_reason:
            print(f"stopped: {outcome.stopped_reason}")
    if outcome.comparison and outcome.comparison.get("hard_gate_passed") is False:
        return 5
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    store = ResultStore(args.results)
    runs = store.iter_runs()
    if not runs:
        raise ConfigurationError(f"no runs found under {store.root}")
    experiment = {}
    exp_path = store.root / "experiment.json"
    if exp_path.exists():
        experiment = load_json_object(exp_path)
    baseline = args.baseline or experiment.get("baseline")
    if not baseline:
        # Fall back to first variant observed.
        baseline = runs[0].variant_id
    result = compare(runs, baseline=baseline)
    store.write_json("comparison.json", result)
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"baseline: {result['baseline']}")
        print(f"hard gates: {'passed' if result['hard_gate_passed'] else 'failed'}")
        for block in result["comparisons"]:
            print(f"candidate {block['candidate']}")
            for metric in block["metrics"]:
                print(
                    f"  {metric['metric']}: {metric['classification']} Δ={metric['absolute_delta']}"
                )
    return 0 if result["hard_gate_passed"] else 5


def _cmd_report(args: argparse.Namespace) -> int:
    store = ResultStore(args.results)
    runs = store.iter_runs()
    summary = {}
    comparison = None
    summary_path = store.root / "summary.json"
    if summary_path.exists():
        summary = load_json_object(summary_path)
    cmp_path = store.root / "comparison.json"
    if cmp_path.exists():
        comparison = load_json_object(cmp_path)
    text = generate_report(runs=runs, summary=summary or None, comparison=comparison)
    dest = args.output or str(store.root / "report.md")
    Path(dest).write_text(text, encoding="utf-8")
    if args.as_json:
        print(json.dumps({"report": dest, "runs": len(runs)}, indent=2))
    else:
        print(text)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    payload = {
        "version": __version__,
        "integrations": detect_integrations(),
        "sibling_versions": sibling_versions(),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"agentbench {__version__}")
        for name, present in payload["integrations"].items():
            print(f"  {name}: {'installed' if present else 'absent'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handlers = {
        "validate": _cmd_validate,
        "run": _cmd_run,
        "compare": _cmd_compare,
        "report": _cmd_report,
        "status": _cmd_status,
    }
    try:
        return handlers[args.command](args)
    except AgentBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return getattr(exc, "exit_code", 1)
    except BrokenPipeError:  # pragma: no cover
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        print("error: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
