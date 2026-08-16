"""Environment fingerprint for reproducibility. Git absence is not a failure."""

from __future__ import annotations

import platform
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ._version import __version__
from .models import EnvironmentFingerprint
from .numbers import require_int


def _git_sha(cwd: str | None) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    sha = (completed.stdout or "").strip()
    return sha or None


def collect_fingerprint(
    *,
    seed: int,
    cwd: str | None = None,
    target_metadata: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> EnvironmentFingerprint:
    return EnvironmentFingerprint(
        agentbench_version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        os_name=platform.system(),
        architecture=platform.machine(),
        seed=require_int(seed, name="seed", allow_negative=True),
        timestamp=datetime.now(timezone.utc).isoformat(),
        cwd_policy="isolated-copy" if cwd else "none",
        git_sha=_git_sha(cwd),
        target_metadata=dict(target_metadata or {}),
        extra=dict(extra or {}),
    )
