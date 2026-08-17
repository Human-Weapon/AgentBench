"""Echo stdin JSON so CommandTarget payload transport can be asserted."""

from __future__ import annotations

import sys

print(sys.stdin.read(), end="")
