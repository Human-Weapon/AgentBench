"""Metric helpers and optional weighted composite scores."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import ValidationError
from .models import MetricDefinition, MetricDirection, MissingMetricBehavior
from .numbers import require_number


def normalize(value: float, definition: MetricDefinition) -> float:
    """Map ``value`` into ``[0, 1]`` using the declared range.

    Higher-is-better metrics keep the orientation; lower-is-better metrics
    are inverted so that 1.0 is always "better" after normalization.
    """
    if definition.minimum is None or definition.maximum is None:
        raise ValidationError(
            f"metric {definition.name} cannot be normalized without an explicit range"
        )
    low = definition.minimum
    high = definition.maximum
    if high == low:
        raise ValidationError(f"metric {definition.name} has zero-width range")
    unit = (value - low) / (high - low)
    unit = 0.0 if unit < 0 else 1.0 if unit > 1 else unit
    if definition.direction is MetricDirection.LOWER_IS_BETTER:
        return 1.0 - unit
    return unit


def composite_score(
    values: Mapping[str, float | None],
    definitions: Sequence[MetricDefinition],
    *,
    missing: MissingMetricBehavior = MissingMetricBehavior.SKIP,
) -> float | None:
    """Weighted mean of *normalized* component scores.

    Refuses to average raw success rate with tokens/latency/cost. Every
    component must declare a range, a direction, and a weight. Missing
    metrics follow ``missing`` (skip / fail / unknown).
    """
    if not definitions:
        raise ValidationError("composite_score requires at least one metric definition")
    weighted = 0.0
    total_weight = 0.0
    for definition in definitions:
        if definition.weight is None:
            raise ValidationError(f"metric {definition.name} is missing an explicit weight")
        raw = values.get(definition.name)
        if raw is None:
            if missing is MissingMetricBehavior.FAIL:
                raise ValidationError(f"metric {definition.name} is missing")
            if missing is MissingMetricBehavior.UNKNOWN:
                return None
            continue
        number = require_number(raw, name=definition.name, allow_negative=True)
        weighted += normalize(number, definition) * definition.weight
        total_weight += definition.weight
    if total_weight == 0:
        return None
    return weighted / total_weight
