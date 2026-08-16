from __future__ import annotations

import math

import pytest

from agentbench.errors import ValidationError
from agentbench.numbers import (
    optional_number,
    percentile,
    relative_delta,
    require_int,
    require_number,
)


def test_bool_rejected_as_int() -> None:
    with pytest.raises(ValidationError):
        require_int(True, name="n")
    with pytest.raises(ValidationError):
        require_int(False, name="n")


def test_bool_rejected_as_number() -> None:
    with pytest.raises(ValidationError):
        require_number(True, name="cost")


def test_nan_and_infinity_rejected() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            require_number(value, name="latency")


def test_negative_rejected_unless_allowed() -> None:
    with pytest.raises(ValidationError):
        require_int(-1, name="max_runs")
    assert require_int(-3, name="seed", allow_negative=True) == -3


def test_zero_is_not_treated_as_missing() -> None:
    assert require_int(0, name="max_runs") == 0
    assert require_number(0.0, name="cost") == 0.0
    assert optional_number(None, name="cost") is None
    assert optional_number(0.0, name="cost") == 0.0


def test_float_rejected_as_int() -> None:
    with pytest.raises(ValidationError):
        require_int(1.5, name="reps")


def test_relative_delta_zero_baseline_is_none() -> None:
    assert relative_delta(0.0, 1.0) is None
    assert relative_delta(10.0, 12.0) == pytest.approx(0.2)


def test_percentile_documents_single_sample() -> None:
    assert percentile([4.0], 95) == 4.0
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 50) == pytest.approx(2.5)
    with pytest.raises(ValidationError):
        percentile([], 50)
