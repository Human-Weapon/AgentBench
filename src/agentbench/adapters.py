"""Optional adapters for sibling evidence. No hard dependency on AgentGear."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import Telemetry
from .numbers import optional_int, optional_number


class AgentGearEvidenceAdapter:
    """Convert AgentGear-shaped evidence mappings into ``Telemetry``.

    Does not import ``agentgear``. Unknown / missing keys stay ``None``.
    Zero is recorded only when the evidence actually supplied zero.
    """

    KNOWN = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "total_tokens": "total_tokens",
        "cost": "cost",
        "average_cost": "cost",
        "latency_seconds": "latency_seconds",
        "average_latency_seconds": "latency_seconds",
        "tool_calls": "tool_calls",
        "agent_count": "agent_count",
        "retries": "retries",
        "recoveries": "recoveries",
        "stalls": "stalls",
        "stall_count": "stall_count",
        "recovery_attempts": "recovery_attempts",
        "successful_recoveries": "successful_recoveries",
        "errors": "errors",
    }

    INT_FIELDS = {
        "tool_calls",
        "agent_count",
        "retries",
        "recoveries",
        "stalls",
        "stall_count",
        "recovery_attempts",
        "successful_recoveries",
        "errors",
    }

    def to_telemetry(self, evidence: Mapping[str, Any] | None) -> Telemetry:
        if evidence is None:
            return Telemetry()
        if not isinstance(evidence, Mapping):
            return Telemetry()
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in evidence.items():
            dest = self.KNOWN.get(key)
            if dest is None:
                extra[str(key)] = value
                continue
            if dest in self.INT_FIELDS:
                kwargs[dest] = optional_int(value, name=dest, allow_zero=True)
            else:
                kwargs[dest] = optional_number(value, name=dest, allow_zero=True)
        if extra:
            kwargs["extra"] = extra
        return Telemetry(**kwargs)
