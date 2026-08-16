"""Sleep longer than typical timeouts."""

from __future__ import annotations

import sys
import time

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
time.sleep(seconds)
raise SystemExit(0)
