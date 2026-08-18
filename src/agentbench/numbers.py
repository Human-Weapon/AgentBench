"""Strict numeric validation for public inputs.

Rejects bool (a subclass of int), NaN, ±Infinity, and negatives unless an
explicit flag allows a given class of values. Missing measurements stay
``None`` — never coerced to 0.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .errors import ValidationError


def _name(name: str) -> str:
    return name or "value"


def require_int(
    value: Any,
    *,
    name: str,
    allow_negative: bool = False,
    allow_zero: bool = True,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Return ``value`` as a real ``int`` or raise ``ValidationError``."""
    label = _name(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"{label} must be an int (bool/NaN/float rejected); got {type(value).__name__}"
        )
    if not allow_negative and value < 0:
        raise ValidationError(f"{label} must not be negative; got {value}")
    if not allow_zero and value == 0:
        raise ValidationError(f"{label} must not be zero")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{label} must be >= {minimum}; got {value}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{label} must be <= {maximum}; got {value}")
    return value


def require_number(
    value: Any,
    *,
    name: str,
    allow_negative: bool = False,
    allow_zero: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Return ``value`` as a finite float or raise ``ValidationError``.

    ``bool`` is rejected. ``int`` is accepted and coerced to ``float``.
    """
    label = _name(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(
            f"{label} must be a finite number (bool/str rejected); got {type(value).__name__}"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValidationError(f"{label} must be a finite number; got {value!r}")
    if not allow_negative and number < 0:
        raise ValidationError(f"{label} must not be negative; got {number}")
    if not allow_zero and number == 0:
        raise ValidationError(f"{label} must not be zero")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{label} must be >= {minimum}; got {number}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{label} must be <= {maximum}; got {number}")
    return number


def optional_int(value: Any, *, name: str, **kwargs: Any) -> int | None:
    """Like ``require_int`` but ``None`` stays ``None``."""
    if value is None:
        return None
    return require_int(value, name=name, **kwargs)


def optional_number(value: Any, *, name: str, **kwargs: Any) -> float | None:
    """Like ``require_number`` but ``None`` stays ``None`` (UNKNOWN)."""
    if value is None:
        return None
    return require_number(value, name=name, **kwargs)


def require_nonblank_str(value: Any, *, name: str) -> str:
    """Return a stripped non-empty string."""
    label = _name(name)
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string; got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValidationError(f"{label} must be a non-blank string")
    return text


def relative_delta(baseline: float, candidate: float) -> float | None:
    """``(candidate - baseline) / |baseline|`` or ``None`` when baseline is 0."""
    if baseline == 0:
        return None
    return (candidate - baseline) / abs(baseline)


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile (Hyndman & Fan type 7).

    ``p`` is in ``[0, 100]``. Sample size is not hidden: callers must report
    ``n``. A single sample returns that sample; it is not a meaningful p95.
    """
    if not values:
        raise ValidationError("percentile requires at least one value")
    p = require_number(p, name="p", allow_negative=False, minimum=0.0, maximum=100.0)
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[int(rank)]
    weight = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * weight


def reject_nonfinite_tree(value: Any, *, name: str = "value") -> Any:
    """Walk nested mappings/sequences and reject NaN / ±Infinity."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValidationError(f"{name} must be finite; got {value!r}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            reject_nonfinite_tree(item, name=f"{name}.{key}")
        return value
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_nonfinite_tree(item, name=f"{name}[{index}]")
        return value
    return value


def deep_freeze(value: Any) -> Any:
    """Defensive immutable copy of nested mappings/sequences."""
    from types import MappingProxyType

    if isinstance(value, Mapping):
        frozen: dict[Any, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"mapping keys must be strings; got {type(key).__name__}")
            frozen[key] = deep_freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(deep_freeze(v) for v in value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValidationError("NaN/Infinity rejected in nested data")
    return value


def require_bool(value: Any, *, name: str) -> bool:
    """Accept only real ``bool`` values. Strings/ints are rejected."""
    if not isinstance(value, bool):
        raise ValidationError(
            f"{name} must be a JSON boolean true/false; got {type(value).__name__}"
        )
    return value


def optional_bool(value: Any, *, name: str, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    return require_bool(value, name=name)


def money(value: Any, *, name: str) -> Decimal:
    """Deterministic cost accounting from JSON/Python numbers."""
    from decimal import Decimal, InvalidOperation

    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{name} must be a finite number")
    try:
        if isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, float):
            amount = Decimal(str(value))
        elif isinstance(value, str):
            amount = Decimal(value)
        else:
            raise ValidationError(f"{name} must be a finite number; got {type(value).__name__}")
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{name} is not a valid decimal: {value!r}") from exc
    if not amount.is_finite():
        raise ValidationError(f"{name} must be finite")
    return amount


def reject_json_constant(token: str) -> None:
    """``json.loads(..., parse_constant=...)`` hook."""
    raise ValidationError(f"non-finite JSON value rejected: {token}")
