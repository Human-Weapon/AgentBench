"""Emit a configured cost so CLI can exercise the cost-bound contract."""

from __future__ import annotations

import json
import sys

cost_arg = sys.argv[1] if len(sys.argv) > 1 else "0.8"
payload = {"telemetry": {}}
if cost_arg == "unknown":
    payload["telemetry"]["cost"] = None
else:
    payload["telemetry"]["cost"] = float(cost_arg)
print(json.dumps(payload))
