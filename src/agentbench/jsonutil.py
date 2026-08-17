"""Convert frozen domain values to JSON-native transport structures."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ValidationError


def to_jsonable(value: Any, *, name: str = "value") -> Any:
    """Recursively convert immutable domain data to JSON-native types.

    Mapping / MappingProxyType → dict
    list / tuple → list
    JSON scalars preserved.
    Arbitrary objects raise ``ValidationError`` (never ``str()``).
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValidationError(f"{name} must be finite")
        return value
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item, name=f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_jsonable(item, name=f"{name}[{index}]") for index, item in enumerate(value)]
    raise ValidationError(f"{name} is not JSON-native ({type(value).__name__})")
