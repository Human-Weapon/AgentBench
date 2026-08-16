"""Non-dominated (Pareto) variants on selected metrics. Analysis, not routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import MetricDirection


def _better(a: float, b: float, direction: MetricDirection) -> bool:
    return a > b if direction is MetricDirection.HIGHER_IS_BETTER else a < b


def _no_worse(a: float, b: float, direction: MetricDirection) -> bool:
    return a >= b if direction is MetricDirection.HIGHER_IS_BETTER else a <= b


def pareto_frontier(
    variants: Mapping[str, Mapping[str, float | None]],
    directions: Mapping[str, MetricDirection],
) -> dict[str, Any]:
    """Return non-dominated variants.

    A variant is dominated if another is at least as good on every selected
    metric and strictly better on at least one. Missing metrics exclude a
    variant from domination claims (it is reported as incomplete).
    """
    metrics = tuple(directions)
    complete: dict[str, dict[str, float]] = {}
    incomplete: list[str] = []
    for vid, values in variants.items():
        row: dict[str, float] = {}
        missing = False
        for metric in metrics:
            value = values.get(metric)
            if value is None:
                missing = True
                break
            row[metric] = value
        if missing:
            incomplete.append(vid)
        else:
            complete[vid] = row

    dominated: dict[str, str] = {}
    ids = list(complete)
    for left in ids:
        for right in ids:
            if left == right:
                continue
            at_least = all(
                _no_worse(complete[right][m], complete[left][m], directions[m]) for m in metrics
            )
            strictly = any(
                _better(complete[right][m], complete[left][m], directions[m]) for m in metrics
            )
            if at_least and strictly:
                dominated[left] = right
                break
    frontier = [vid for vid in ids if vid not in dominated]
    return {
        "metrics": list(metrics),
        "frontier": frontier,
        "dominated": dominated,
        "incomplete": incomplete,
    }
