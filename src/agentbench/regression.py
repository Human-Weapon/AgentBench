"""Caller-defined regression gates. AgentBench never invents thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError
from .models import MetricDirection
from .numbers import optional_number, require_int, require_nonblank_str


@dataclass(frozen=True)
class MetricRule:
    metric: str
    direction: MetricDirection
    absolute_threshold: float | None = None
    relative_threshold: float | None = None
    min_sample_size: int = 1
    hard_gate: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", require_nonblank_str(self.metric, name="metric"))
        if isinstance(self.direction, str):
            try:
                object.__setattr__(self, "direction", MetricDirection(self.direction))
            except ValueError as exc:
                raise ValidationError(f"unknown direction: {self.direction!r}") from exc
        if not isinstance(self.direction, MetricDirection):
            raise ValidationError("direction must be a MetricDirection")
        object.__setattr__(
            self,
            "absolute_threshold",
            optional_number(self.absolute_threshold, name="absolute_threshold", allow_zero=True),
        )
        object.__setattr__(
            self,
            "relative_threshold",
            optional_number(self.relative_threshold, name="relative_threshold", allow_zero=True),
        )
        if self.absolute_threshold is None and self.relative_threshold is None:
            raise ValidationError(f"rule for {self.metric} needs an absolute or relative threshold")
        object.__setattr__(
            self,
            "min_sample_size",
            require_int(self.min_sample_size, name="min_sample_size", allow_zero=False, minimum=1),
        )
        if not isinstance(self.hard_gate, bool):
            raise ValidationError("hard_gate must be a bool")


@dataclass(frozen=True)
class RegressionPolicy:
    rules: tuple[MetricRule, ...]
    baseline_variant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "baseline_variant_id",
            require_nonblank_str(self.baseline_variant_id, name="baseline_variant_id"),
        )
        rules = tuple(self.rules)
        if not rules:
            raise ValidationError("RegressionPolicy requires at least one rule")
        seen: dict[str, MetricDirection] = {}
        for rule in rules:
            prior = seen.get(rule.metric)
            if prior is not None and prior is not rule.direction:
                raise ValidationError(
                    f"contradictory rules for metric {rule.metric}: {prior} vs {rule.direction}"
                )
            seen[rule.metric] = rule.direction
        object.__setattr__(self, "rules", rules)

    @classmethod
    def from_config(cls, raw: dict) -> RegressionPolicy:
        rules = tuple(
            MetricRule(
                metric=item["metric"],
                direction=item["direction"],
                absolute_threshold=item.get("absolute_threshold"),
                relative_threshold=item.get("relative_threshold"),
                min_sample_size=item.get("min_sample_size", 1),
                hard_gate=bool(item.get("hard_gate", False)),
            )
            for item in raw.get("rules") or ()
        )
        return cls(rules=rules, baseline_variant_id=raw["baseline"])
