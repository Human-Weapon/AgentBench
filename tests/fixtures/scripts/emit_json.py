"""Emit structured JSON with a nested field."""

from __future__ import annotations

import json

print(json.dumps({"value": 42, "nested": {"flag": True}, "telemetry": {"total_tokens": 7}}))
