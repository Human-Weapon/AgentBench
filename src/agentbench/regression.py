"""Caller-defined regression gates. AgentBench never invents thresholds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ConfigurationError, ValidationError
from .models import MetricDirection
from .numbers import optional_bool, optional_number, require_int, require_nonblank_str

_POLICY_KEYS = {"baseline", "rules"}
_RULE_KEYS = {
    "metric",
    "direction",
    "absolute_threshold",
    "relative_threshold",
    "min_sample_size",
    "hard_gate",
}


def _unknown(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ConfigurationError(f"unknown {where} field(s): {extra}")


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
        object.__setattr__(self, "direction", MetricDirection.parse(self.direction))
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
            raise ValidationError("hard_gate must be a JSON boolean true/false")


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
        seen: set[str] = set()
        for rule in rules:
            if rule.metric in seen:
                raise ValidationError(
                    f"duplicate regression rule for metric {rule.metric}; "
                    "conflicting rules are rejected"
                )
            seen.add(rule.metric)
        object.__setattr__(self, "rules", rules)

    @classmethod
    def from_config(cls, raw: object) -> RegressionPolicy:
        if not isinstance(raw, Mapping):
            raise ConfigurationError("regression must be an object")
        _unknown(raw, _POLICY_KEYS, "regression")
        if "baseline" not in raw:
            raise ConfigurationError("regression.baseline is required")
        rules_raw = raw.get("rules")
        if not isinstance(rules_raw, list):
            raise ConfigurationError("regression.rules must be an array")
        rules = []
        for item in rules_raw:
            if not isinstance(item, Mapping):
                raise ConfigurationError("each regression rule must be an object")
            _unknown(item, _RULE_KEYS, "regression rule")
            if "metric" not in item or "direction" not in item:
                raise ConfigurationError("regression rule requires metric and direction")
            hard = item.get("hard_gate")
            rules.append(
                MetricRule(
                    metric=item["metric"],
                    direction=item["direction"],
                    absolute_threshold=item.get("absolute_threshold"),
                    relative_threshold=item.get("relative_threshold"),
                    min_sample_size=item.get("min_sample_size", 1),
                    hard_gate=False if hard is None else optional_bool(hard, name="hard_gate"),
                )
            )
        return cls(rules=tuple(rules), baseline_variant_id=raw["baseline"])
