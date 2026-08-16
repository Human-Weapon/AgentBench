"""Exit 0 and emit cheap telemetry JSON."""

from __future__ import annotations

import json
import sys

payload = {}
try:
    payload = json.load(sys.stdin)
except Exception:
    payload = {}
print(
    json.dumps(
        {
            "ok": True,
            "echo": payload,
            "telemetry": {
                "cost": 0.01,
                "input_tokens": 8,
                "output_tokens": 4,
                "total_tokens": 12,
            },
        }
    )
)
raise SystemExit(0)
