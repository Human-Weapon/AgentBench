"""Honest markdown + JSON reports. No 'objectively better' claims."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .aggregation import aggregate_experiment
from .frontier import pareto_frontier
from .models import MetricDirection, RunResult
from .runner import ExperimentOutcome


def _fmt(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def generate_report(
    outcome: ExperimentOutcome | None = None,
    *,
    runs: Sequence[RunResult] | None = None,
    summary: Mapping[str, Any] | None = None,
    comparison: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    if summary is None:
        used_runs = list(outcome.runs if outcome is not None else (runs or ()))
        summary = aggregate_experiment(used_runs)
    if comparison is None and outcome is not None:
        comparison = outcome.comparison

    lines: list[str] = []
    lines.append("# AgentBench report")
    lines.append("")
    lines.append("AgentBench measures. It does not decide which configuration to ship.")
    lines.append("")
    if outcome is not None:
        fp = outcome.fingerprint.as_dict()
        lines.append("## Experiment")
        lines.append("")
        lines.append(f"- suite: `{outcome.suite_id}`")
        lines.append(f"- seed: `{outcome.seed}`")
        lines.append(f"- agentbench: `{fp.get('agentbench_version')}`")
        lines.append(f"- python: `{fp.get('python_version')}`")
        lines.append(f"- platform: `{fp.get('platform')}`")
        lines.append(f"- git: `{fp.get('git_sha') or 'unavailable'}`")
        lines.append(f"- timestamp: `{fp.get('timestamp')}`")
        if outcome.stopped_reason:
            lines.append(f"- stopped: {outcome.stopped_reason}")
        lines.append("")

    lines.append("## Status counts")
    lines.append("")
    lines.append(f"- runs: {summary.get('run_count', summary.get('n'))}")
    counts = summary.get("counts") or {}
    for key in ("SUCCESS", "FAILURE", "TIMEOUT", "ERROR", "SKIPPED"):
        lines.append(f"- {key.lower()}: {counts.get(key, 0)}")
    lines.append("")

    lines.append("## Variants")
    lines.append("")
    for variant in summary.get("variants") or ():
        vid = variant.get("variant_id")
        metrics = variant.get("metrics") or {}
        success = (metrics.get("success") or {}).get("mean")
        cost = (metrics.get("cost") or {}).get("median")
        latency = (metrics.get("latency_seconds") or {}).get("median")
        tokens = (metrics.get("total_tokens") or {}).get("median")
        lines.append(f"### `{vid}`")
        lines.append("")
        lines.append(f"- runs: {variant.get('run_count')}")
        lines.append(f"- success rate: {_fmt(success)}")
        lines.append(f"- median cost: {_fmt(cost)}")
        lines.append(f"- median latency: {_fmt(latency)}")
        lines.append(f"- median tokens: {_fmt(tokens)}")
        lines.append(f"- stalls (mean): {_fmt((metrics.get('stall_count') or {}).get('mean'))}")
        lines.append(
            f"- recoveries (mean): {_fmt((metrics.get('successful_recoveries') or {}).get('mean'))}"
        )
        lines.append("")

    flaky = summary.get("flaky") or ()
    lines.append("## Flaky cases")
    lines.append("")
    if not flaky:
        lines.append("None detected.")
        lines.append("")
    else:
        for item in flaky:
            lines.append(f"- `{item['case_id']}` / `{item['variant_id']}`: {item['outcomes']}")
        lines.append("")

    lines.append("## Case outcomes")
    lines.append("")
    for row in summary.get("cases") or ():
        flags = []
        if row.get("always_fail"):
            flags.append("always-fail")
        if row.get("always_timeout"):
            flags.append("always-timeout")
        if row.get("flaky"):
            flags.append("flaky")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        lines.append(
            f"- `{row['case_id']}` / `{row['variant_id']}` "
            f"n={row['n']} cost={_fmt(row.get('mean_cost'))}{flag_text}"
        )
    lines.append("")

    if comparison:
        lines.append("## Comparison")
        lines.append("")
        lines.append(f"Baseline: `{comparison.get('baseline')}`.")
        lines.append("")
        for block in comparison.get("comparisons") or ():
            lines.append(f"### Candidate `{block['candidate']}`")
            lines.append("")
            for metric in block.get("metrics") or ():
                rel = metric.get("relative_delta")
                rel_text = "unavailable" if rel is None else f"{rel:.2%}"
                lines.append(
                    f"- {metric['metric']} ({metric['direction']}): "
                    f"baseline={_fmt(metric.get('baseline'))} "
                    f"candidate={_fmt(metric.get('candidate'))} "
                    f"Δ={_fmt(metric.get('absolute_delta'))} "
                    f"rel={rel_text} "
                    f"→ {metric.get('classification')} "
                    f"(n={metric.get('baseline_n')}/{metric.get('candidate_n')})"
                )
                paired = metric.get("paired") or {}
                if paired.get("paired_n"):
                    lines.append(
                        f"  paired win-rate={_fmt(paired.get('win_rate'))} "
                        f"({paired.get('wins')}-{paired.get('losses')}-{paired.get('ties')})"
                    )
            lines.append("")
        if comparison.get("hard_gate_failures"):
            lines.append("Hard regression gates failed:")
            for item in comparison["hard_gate_failures"]:
                lines.append(f"- {item}")
            lines.append("")
        elif comparison.get("hard_gate_passed") is False:
            lines.append("Hard regression gates failed.")
            lines.append("")

    # Optional frontier from variant means of success vs cost.
    variant_points: dict[str, dict[str, float | None]] = {}
    for variant in summary.get("variants") or ():
        metrics = variant.get("metrics") or {}
        variant_points[variant["variant_id"]] = {
            "success": (metrics.get("success") or {}).get("mean"),
            "cost": (metrics.get("cost") or {}).get("mean"),
        }
    if len(variant_points) >= 2:
        frontier = pareto_frontier(
            variant_points,
            {
                "success": MetricDirection.HIGHER_IS_BETTER,
                "cost": MetricDirection.LOWER_IS_BETTER,
            },
        )
        lines.append("## Quality / cost frontier")
        lines.append("")
        lines.append(
            "Non-dominated variants on mean success (higher is better) and mean cost "
            "(lower is better). This is analysis, not a routing decision."
        )
        lines.append("")
        lines.append(f"- frontier: {', '.join(f'`{v}`' for v in frontier['frontier']) or 'none'}")
        if frontier["dominated"]:
            for vid, by in frontier["dominated"].items():
                lines.append(f"- `{vid}` dominated by `{by}`")
        if frontier["incomplete"]:
            lines.append(
                f"- incomplete (missing success or cost): "
                f"{', '.join(f'`{v}`' for v in frontier['incomplete'])}"
            )
        lines.append("")

    lines.append("## Missing metrics")
    lines.append("")
    lines.append(
        "Any field listed as `unknown` was not measured. AgentBench does not invent "
        "cost, tokens, or latency. A single sample is not a meaningful p95."
    )
    lines.append("")
    if extra:
        lines.append("## Extra")
        lines.append("")
        for key, value in extra.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines) + "\n"
