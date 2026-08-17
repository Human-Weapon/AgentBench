"""Parent that launches a long-lived child, then sleeps. Used for process-tree tests."""

from __future__ import annotations

import subprocess
import sys
import time

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30
child = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])
print(f"CHILD_PID={child.pid}", flush=True)
time.sleep(seconds)
child.wait()
