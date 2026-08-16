"""Dispatch to the local fast or accurate target from variant metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    variant = payload.get("variant") or {}
    config = variant.get("config") or {}
    mode = config.get("mode") or variant.get("id") or "fast"
    script = HERE / ("slow_accurate.py" if mode in {"slow", "accurate", "slow-accurate"} else "fast_cheap.py")
    # Re-exec as a fresh interpreter invocation would lose stdin; import instead.
    sys.stdin = __import__("io").StringIO(raw)
    if mode in {"slow", "accurate", "slow-accurate"}:
        from slow_accurate import main as inner
    else:
        from fast_cheap import main as inner
    return inner()


if __name__ == "__main__":
    raise SystemExit(main())
