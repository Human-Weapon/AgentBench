"""Strict numeric validation for public inputs.

Rejects bool (a subclass of int), NaN, ±Infinity, and negatives unless an
explicit flag allows a given class of values. Missing measurements stay
``None`` — never coerced to 0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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
