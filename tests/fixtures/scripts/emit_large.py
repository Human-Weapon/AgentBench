"""Emit several megabytes of stdout so capture limits can be exercised."""

from __future__ import annotations

import sys

megabytes = int(sys.argv[1]) if len(sys.argv) > 1 else 3
chunk = b"X" * 1024
for _ in range(megabytes * 1024):
    sys.stdout.buffer.write(chunk)
sys.stdout.buffer.flush()
print("DONE", file=sys.stderr)
