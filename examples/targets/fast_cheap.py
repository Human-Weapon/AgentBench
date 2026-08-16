"""Fast, cheap, occasionally imperfect local target. No network."""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    case = payload.get("case") or {}
    data = case.get("payload") or {}
    n = int(data.get("n", 0))
    # Cheap heuristic: even numbers are correct, odds are off-by-one.
    answer = n * 2 if n % 2 == 0 else n * 2 - 1
    expected = (case.get("expected") or {}).get("answer")
    ok = expected is None or answer == expected
    print(
        json.dumps(
            {
                "answer": answer,
                "ok": ok,
                "telemetry": {
                    "cost": 0.02,
                    "input_tokens": 20,
                    "output_tokens": 8,
                    "total_tokens": 28,
                    "latency_seconds": 0.01,
                },
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
