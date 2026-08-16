"""Exit 1 and write stderr."""

from __future__ import annotations

import sys

sys.stdout.write("partial-out\n")
sys.stderr.write("target-failed\n")
raise SystemExit(1)
