"""Write distinct stdout and stderr."""

from __future__ import annotations

import sys

sys.stdout.write("STDOUT-MARKER\n")
sys.stderr.write("STDERR-MARKER\n")
raise SystemExit(0)
